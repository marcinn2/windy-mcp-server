import argparse
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Literal

from dotenv import load_dotenv
from fastmcp import Context, FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
from starlette.requests import Request
from starlette.responses import JSONResponse

from client import (
    ForecastRequest,
    Level,
    Model,
    Parameter,
    TempUnit,
    WindyBadRequestError,
    WindyClient,
    WindyNoContentError,
    WindyServerError,
)
from server.map_embed import build_map_embed_html

load_dotenv()

logger = logging.getLogger(__name__)

# Windy API keys. The Point Forecast key gates the forecast tools: when it is
# absent the server still starts (e.g. for health checks) but exposes no tools
# (see the conditional registration near the bottom of this module). The Map
# Forecast key is optional and reserved for map-based features.
POINT_API_KEY = os.environ.get("WINDY_POINT_API_KEY")
MAP_API_KEY = os.environ.get("WINDY_MAP_API_KEY")

# --- Type aliases for tool parameter schemas ---

WeatherModel = Literal[
    "gfs",
    "icon",
    "iconEu",
    "iconD2",
    "arome",
    "aromeAntilles",
    "aromeFrance",
    "aromeReunion",
    "namConus",
    "namHawaii",
    "namAlaska",
    "hrrrConus",
    "hrrrAlaska",
    "canHrdps",
]

WaveModel = Literal["gfsWave", "iconWave", "iconEuWave", "canRdwpsWave"]

AirQualityModel = Literal["cams", "camsEu"]

WeatherParameter = Literal[
    "temp",
    "dewpoint",
    "rh",
    "pressure",
    "gh",
    "precip",
    "snowPrecip",
    "convPrecip",
    "wind",
    "windGust",
    "lclouds",
    "mclouds",
    "hclouds",
    "cbase",
    "visibility",
    "cape",
    "ptype",
    "weatherWarnings",
]

WaveParameter = Literal["waves", "windWaves", "wavesPower", "swell1", "swell2"]

AirQualityParameter = Literal[
    "aqi",
    "so2sm",
    "dustsm",
    "cosc",
    "go3",
    "no2",
    "pm10",
    "pm2p5",
    "pollenAlder",
    "pollenBirch",
    "pollenGrass",
    "pollenMugwort",
    "pollenOlive",
    "pollenRagweed",
]

PressureLevel = Literal[
    "surface",
    "1000h",
    "950h",
    "925h",
    "900h",
    "850h",
    "800h",
    "700h",
    "600h",
    "500h",
    "400h",
    "300h",
    "200h",
    "150h",
]

TemperatureUnit = Literal["celsius", "kelvin"]

MapOverlay = Literal[
    "wind",
    "gust",
    "temp",
    "dewpoint",
    "rh",
    "pressure",
    "clouds",
    "rain",
    "rainAccu",
    "snowAccu",
    "thunder",
    "waves",
    "swell1",
    "cape",
]


# --- Lifespan: manage WindyClient lifecycle ---


@asynccontextmanager
async def lifespan(server: FastMCP):
    if not POINT_API_KEY:
        # No key: the forecast tools are not registered, so no client is needed.
        yield {"client": None}
        return
    client = WindyClient(api_key=POINT_API_KEY)
    try:
        yield {"client": client}
    finally:
        await client.close()


def _build_auth() -> StaticTokenVerifier | None:
    """Enable static bearer-token auth when WINDY_MCP_AUTH_TOKEN is set.

    When configured, the HTTP transport requires an `Authorization: Bearer
    <token>` header on the MCP endpoint. Returns None (no auth) otherwise.
    """
    token = os.environ.get("WINDY_MCP_AUTH_TOKEN")
    if not token:
        return None
    return StaticTokenVerifier(tokens={token: {"client_id": "windy-mcp-server"}})


mcp = FastMCP("Windy Point Forecast", lifespan=lifespan, auth=_build_auth())


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Unauthenticated liveness probe (bypasses bearer auth)."""
    return JSONResponse({"status": "ok"})


# --- Helpers ---


def _fmt_ts(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")


def _build_response(response) -> dict:
    return {
        "timestamps_utc": [_fmt_ts(ts) for ts in response.timestamps],
        "series": [
            {
                "parameter_level": s.parameter_level,
                "unit": s.unit,
                "values": s.values,
            }
            for s in response.series
        ],
    }


async def _call_forecast(
    client: WindyClient, request: ForecastRequest, model_name: str
) -> dict:
    try:
        response = await client.get_forecast(request)
        return _build_response(response)
    except WindyNoContentError as e:
        raise ValueError(
            f"No data available for model '{model_name}' with the requested"
            " parameters at this location"
        ) from e
    except WindyBadRequestError as e:
        raise ValueError(f"Invalid request: {e}") from e
    except WindyServerError as e:
        raise RuntimeError(f"Windy API server error: {e}") from e


# --- Tools ---


async def get_weather_forecast(
    lat: float,
    lon: float,
    parameters: list[WeatherParameter],
    ctx: Context,
    model: WeatherModel = "gfs",
    levels: list[PressureLevel] | None = None,
    temp_unit: TemperatureUnit = "celsius",
) -> dict:
    """Get a weather forecast for a specific location from the Windy point forecast API.

    Returns forecast time series for the requested parameters. Only the parameters you
    explicitly list are fetched — request only what you need.

    Args:
        lat: Latitude in decimal degrees (-90 to 90).
        lon: Longitude in decimal degrees (-180 to 180).
        parameters: Weather parameters to fetch. Choose from temperature, wind,
            precipitation, clouds, visibility, and atmospheric instability indicators.
        ctx: Injected server context.
        model: Forecast model to use. Defaults to GFS (global coverage).
        levels: Pressure levels for vertical atmosphere data. Defaults to surface only.
            Use hPa values (e.g. "850h", "500h") for upper-atmosphere queries.
        temp_unit: Unit for temperature values. Defaults to celsius.
    """
    client: WindyClient = ctx.lifespan_context["client"]
    resolved_levels = [Level(lv) for lv in levels] if levels else [Level.surface]
    request = ForecastRequest(
        lat=lat,
        lon=lon,
        model=Model(model),
        parameters=[Parameter(p) for p in parameters],
        levels=resolved_levels,
        temp_unit=TempUnit.celsius if temp_unit == "celsius" else TempUnit.kelvin,
    )
    return await _call_forecast(client, request, model)


async def get_wave_forecast(
    lat: float,
    lon: float,
    parameters: list[WaveParameter],
    ctx: Context,
    model: WaveModel = "gfsWave",
) -> dict:
    """Get an ocean wave forecast for a location from the Windy point forecast API.

    Returns forecast time series for the requested wave parameters. Only the parameters
    you explicitly list are fetched — request only what you need.

    Args:
        lat: Latitude in decimal degrees (-90 to 90).
        lon: Longitude in decimal degrees (-180 to 180).
        parameters: Wave parameters to fetch
            (wave height, wind waves, swell, wave power).
        ctx: Injected server context.
        model: Wave forecast model to use. Defaults to GFS Wave (global coverage).
    """
    client: WindyClient = ctx.lifespan_context["client"]
    request = ForecastRequest(
        lat=lat,
        lon=lon,
        model=Model(model),
        parameters=[Parameter(p) for p in parameters],
        levels=[Level.surface],
        temp_unit=TempUnit.kelvin,
    )
    return await _call_forecast(client, request, model)


async def get_air_quality_forecast(
    lat: float,
    lon: float,
    parameters: list[AirQualityParameter],
    ctx: Context,
    model: AirQualityModel = "cams",
) -> dict:
    """Get an air quality and pollen forecast for a location from the Windy API.

    Returns forecast time series for the requested air quality or pollen parameters.
    Only the parameters you explicitly list are fetched — request only what you need.

    Args:
        lat: Latitude in decimal degrees (-90 to 90).
        lon: Longitude in decimal degrees (-180 to 180).
        parameters: Air quality or pollen parameters to fetch
            (AQI, particulates, gases, pollen types).
        ctx: Injected server context.
        model: Air quality model to use. Defaults to CAMS (global Copernicus service).
            Use "camsEu" for higher-resolution European data.
    """
    client: WindyClient = ctx.lifespan_context["client"]
    request = ForecastRequest(
        lat=lat,
        lon=lon,
        model=Model(model),
        parameters=[Parameter(p) for p in parameters],
        levels=[Level.surface],
        temp_unit=TempUnit.kelvin,
    )
    return await _call_forecast(client, request, model)


# --- Map tool (Windy Map Forecast API) ---


async def get_windy_map(
    lat: float,
    lon: float,
    overlay: MapOverlay = "wind",
    zoom: int = 5,
) -> dict:
    """Render an interactive Windy weather map for a location (Windy Map Forecast API).

    The Map Forecast API is a browser (Leaflet) library, not a data endpoint, so this
    returns a self-contained HTML page that displays the interactive Windy map centered
    on the coordinates with the chosen weather overlay. Save the returned HTML to a file
    and open it in a browser to view the map.

    Args:
        lat: Latitude in decimal degrees (-90 to 90).
        lon: Longitude in decimal degrees (-180 to 180).
        overlay: Weather layer to display (e.g. wind, temp, rain, clouds).
            Defaults to wind.
        zoom: Initial zoom level, roughly 3 (continental) to 11 (city). Defaults to 5.
    """
    html = build_map_embed_html(
        key=MAP_API_KEY, lat=lat, lon=lon, zoom=zoom, overlay=overlay
    )
    return {
        "lat": lat,
        "lon": lon,
        "overlay": overlay,
        "zoom": zoom,
        "format": "html",
        "html": html,
    }


# --- Predefined prompts ---
# Reusable templates clients can list and invoke; they guide the assistant to
# call the right tools. Registered alongside the tools they depend on.


def weather_briefing(location: str, days: int = 3) -> str:
    """Summarized weather outlook for a location over the next few days."""
    return (
        f"Use get_weather_forecast to fetch temperature, wind, wind gusts, "
        f"precipitation, and low/mid/high cloud cover for {location}. Summarize the "
        f"outlook for the next {days} days, highlighting rain windows, wind peaks, "
        f"and notable changes. Report times in the location's local timezone."
    )


def surf_report(spot: str) -> str:
    """Surf and wind conditions for a coastal spot."""
    return (
        f"Use get_wave_forecast (significant wave height, primary swell, wave power) "
        f"and get_weather_forecast (wind and wind gusts) for {spot}. Assess whether "
        f"conditions look good for surfing over the coming days and explain why."
    )


def air_quality_check(location: str, health_context: str = "") -> str:
    """Air quality and pollen outlook, optionally tailored to a health concern."""
    prompt = (
        f"Use get_air_quality_forecast to fetch AQI, PM2.5, PM10, NO2, O3, and the "
        f"relevant pollen types for {location}, then summarize the air quality outlook."
    )
    if health_context:
        prompt += f" Tailor the advice to this health context: {health_context}."
    return prompt


def weather_map(location: str, overlay: MapOverlay = "wind") -> str:
    """Render an interactive Windy weather map for a location."""
    return (
        f"Use get_windy_map to render an interactive '{overlay}' map centered on "
        f"{location}, then return the HTML and tell me how to open it in a browser."
    )


# --- Tool & prompt registration ---
# Capabilities are exposed only when their API key is configured. Without the
# relevant key the server still runs (health checks, etc.) but advertises less.
if POINT_API_KEY:
    mcp.tool(get_weather_forecast)
    mcp.tool(get_wave_forecast)
    mcp.tool(get_air_quality_forecast)
    mcp.prompt(weather_briefing)
    mcp.prompt(surf_report)
    mcp.prompt(air_quality_check)
else:
    logger.warning(
        "WINDY_POINT_API_KEY is not set; forecast tools are disabled. Set it to "
        "expose get_weather_forecast, get_wave_forecast, and "
        "get_air_quality_forecast."
    )

if MAP_API_KEY:
    mcp.tool(get_windy_map)
    mcp.prompt(weather_map)
else:
    logger.info("WINDY_MAP_API_KEY is not set; the get_windy_map tool is disabled.")


def main():
    parser = argparse.ArgumentParser(
        prog="windy-mcp-server",
        description="MCP server for the Windy Point Forecast API.",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=os.environ.get("WINDY_MCP_TRANSPORT", "stdio"),
        help="Transport to serve on. 'stdio' (default) for local subprocess "
        "clients; 'http' for a networked Streamable HTTP server. "
        "Env: WINDY_MCP_TRANSPORT.",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("WINDY_MCP_HOST", "127.0.0.1"),
        help="Host to bind when --transport http (default: 127.0.0.1). "
        "Env: WINDY_MCP_HOST.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("WINDY_MCP_PORT", "8000")),
        help="Port to bind when --transport http (default: 8000). Env: WINDY_MCP_PORT.",
    )
    parser.add_argument(
        "--path",
        default=os.environ.get("WINDY_MCP_PATH", "/mcp/"),
        help="URL path for the Streamable HTTP endpoint (default: /mcp/). "
        "Env: WINDY_MCP_PATH.",
    )
    args = parser.parse_args()

    if args.transport == "http":
        if not os.environ.get("WINDY_MCP_AUTH_TOKEN"):
            logger.warning(
                "Serving HTTP without authentication. Set WINDY_MCP_AUTH_TOKEN "
                "to require a bearer token on the MCP endpoint."
            )
        mcp.run(transport="http", host=args.host, port=args.port, path=args.path)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
