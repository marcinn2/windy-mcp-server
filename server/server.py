import argparse
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Literal

from dotenv import load_dotenv
from fastmcp import Context, FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
from pydantic import Field
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
    describe_unsupported,
    unusable_levels,
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

WaveModel = Literal["gfsWave", "iconWave", "iconEuWave", "canRdwpsWave", "cmems"]

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

WaveParameter = Literal[
    "waves",
    "windWaves",
    "wavesPower",
    "swell1",
    "swell2",
    "currents",
    "currentsTide",
]

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

Latitude = Annotated[
    float, Field(ge=-90, le=90, description="Latitude in decimal degrees")
]
Longitude = Annotated[
    float, Field(ge=-180, le=180, description="Longitude in decimal degrees")
]

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


def _series_payload(s) -> dict:
    payload = {
        "parameter_level": s.parameter_level,
        "unit": s.unit,
        "values": s.values,
    }
    # Only carried for parameters whose meaning or encoding is not self-evident,
    # so ordinary series stay compact.
    if s.description:
        payload["description"] = s.description
    if s.legend:
        payload["legend"] = s.legend
    return payload


def _build_response(response, notes: list[str]) -> dict:
    payload: dict = {
        "timestamps_utc": [_fmt_ts(ts) for ts in response.timestamps],
        "series": [_series_payload(s) for s in response.series],
    }
    if notes:
        payload["notes"] = notes
    if response.extras:
        payload["api_fields"] = response.extras
    return payload


async def _call_forecast(client: WindyClient, request: ForecastRequest) -> dict:
    # Windy drops unsupported parameter/level series without comment, so say up
    # front what the chosen model will not answer rather than leaving a silent
    # gap in the result.
    notes = [
        note
        for note in (
            describe_unsupported(request.model, request.parameters),
            unusable_levels(request.parameters, request.levels),
        )
        if note
    ]
    try:
        response = await client.get_forecast(request)
        return _build_response(response, notes)
    except WindyNoContentError as e:
        raise ValueError(
            f"Model '{request.model}' returned no data for the requested "
            "parameters. The model does not provide them; choose a model that "
            "does. This is not a limitation of the location."
        ) from e
    except WindyBadRequestError as e:
        raise ValueError(f"Invalid request: {e}") from e
    except WindyServerError as e:
        raise RuntimeError(f"Windy API server error: {e}") from e


# --- Tools ---


async def get_weather_forecast(
    lat: Latitude,
    lon: Longitude,
    parameters: list[WeatherParameter],
    ctx: Context,
    model: WeatherModel = "gfs",
    levels: list[PressureLevel] | None = None,
    temp_unit: TemperatureUnit = "celsius",
) -> dict:
    """Get a weather forecast for a specific location from the Windy point forecast API.

    Returns forecast time series for the requested parameters. Only the parameters you
    explicitly list are fetched — request only what you need.

    Reading the result:
        - Wind comes back as "wind_speed-<level>" plus "wind_dir-<level>", the bearing
          in degrees that the wind blows FROM. There are no raw u/v components.
        - "precip", "snowPrecip" and "convPrecip" come back as "past3hprecip" and
          friends: an accumulation over the preceding 3 hours, in millimetres.
        - "ptype" and "weatherWarnings" are numeric codes. Each carries a "legend"
          mapping the codes present to their meaning. Never guess at these codes.
        - Every series states its own unit. Report the unit given, not an assumed one.

    Model coverage is not uniform, and parameters a model lacks are simply missing
    from the result, with an explanation in the response "notes":
        - "gh" needs icon, iconD2 or iconEu.
        - "cbase" needs arome or aromeAntilles.
        - "visibility" needs aromeFrance or aromeReunion.
        - "weatherWarnings" needs namConus or canHrdps.
        - "snowPrecip" is unavailable on namHawaii and canHrdps.
        - Everything else works with any weather model.

    Args:
        lat: Latitude in decimal degrees (-90 to 90).
        lon: Longitude in decimal degrees (-180 to 180).
        parameters: Weather parameters to fetch. Choose from temperature, wind,
            precipitation, clouds, visibility, and atmospheric instability indicators.
        ctx: Injected server context.
        model: Forecast model to use. Defaults to GFS (global coverage). Regional
            models are higher resolution but only cover their own area.
        levels: Pressure levels for vertical atmosphere data. Defaults to surface only.
            Use hPa values (e.g. "850h", "500h") for upper-atmosphere queries. Levels
            only apply to temp, dewpoint, wind, gh and rh; every other parameter is
            returned at the surface whatever you ask for.
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
    return await _call_forecast(client, request)


async def get_wave_forecast(
    lat: Latitude,
    lon: Longitude,
    parameters: list[WaveParameter],
    ctx: Context,
    model: WaveModel = "gfsWave",
) -> dict:
    """Get an ocean wave or current forecast from the Windy point forecast API.

    Returns forecast time series for the requested sea parameters. Only the parameters
    you explicitly list are fetched — request only what you need.

    Reading the result:
        - Each wave parameter expands into height, period and direction series, e.g.
          "waves" becomes "waves_height-surface", "waves_period-surface" and
          "waves_direction-surface".
        - "currents" and "currentsTide" come back as u/v vector components.
        - Every series states its own unit. Report the unit given, not an assumed one.

    Model coverage is not uniform, and parameters a model lacks are simply missing
    from the result, with an explanation in the response "notes":
        - "waves", "wavesPower", "swell1" and "swell2" need a wave model
          (gfsWave, iconWave, iconEuWave or canRdwpsWave).
        - "windWaves" needs gfsWave or iconWave.
        - "currents" and "currentsTide" need cmems, which provides nothing else.

    Args:
        lat: Latitude in decimal degrees (-90 to 90).
        lon: Longitude in decimal degrees (-180 to 180).
        parameters: Sea parameters to fetch (wave height, wind waves, swell, wave
            power, sea currents).
        ctx: Injected server context.
        model: Sea forecast model to use. Defaults to GFS Wave (global coverage).
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
    return await _call_forecast(client, request)


async def get_air_quality_forecast(
    lat: Latitude,
    lon: Longitude,
    parameters: list[AirQualityParameter],
    ctx: Context,
    model: AirQualityModel = "cams",
) -> dict:
    """Get an air quality and pollen forecast for a location from the Windy API.

    Returns forecast time series for the requested air quality or pollen parameters.
    Only the parameters you explicitly list are fetched — request only what you need.

    Reading the result:
        - Keys are prefixed by family: "aqi_us-surface", "chem_so2sm-surface",
          "pollen_birch-surface" and so on.
        - "aqi" is the US EPA air quality index, where higher is worse.
        - Every series states its own unit. Report the unit given, not an assumed one.

    Model coverage matters here: the six pollen parameters are available ONLY from
    "camsEu", which covers Europe. Requesting pollen from the default "cams" returns
    no pollen at all, so pass model="camsEu" for any pollen question. Parameters a
    model lacks are missing from the result, with an explanation in "notes".

    Args:
        lat: Latitude in decimal degrees (-90 to 90).
        lon: Longitude in decimal degrees (-180 to 180).
        parameters: Air quality or pollen parameters to fetch
            (AQI, particulates, gases, pollen types).
        ctx: Injected server context.
        model: Air quality model to use. Defaults to CAMS (global Copernicus service).
            Use "camsEu" for higher-resolution European data and for all pollen.
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
    return await _call_forecast(client, request)


# --- Map tool (Windy Map Forecast API) ---


async def get_windy_map(
    lat: Latitude,
    lon: Longitude,
    overlay: MapOverlay = "wind",
    zoom: Annotated[int, Field(ge=3, le=18)] = 5,
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
        zoom: Initial zoom level, from 3 (continental) to 18 (street). Roughly 5 for
            a region and 11 for a city. Defaults to 5.
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
        f"Use get_air_quality_forecast to fetch AQI, PM2.5, PM10, NO2 and O3 for "
        f"{location}, then summarize the air quality outlook. Pollen is only "
        f"available from the camsEu model (Europe), so if {location} is in Europe "
        f"make a second call with model='camsEu' for the relevant pollen types."
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
