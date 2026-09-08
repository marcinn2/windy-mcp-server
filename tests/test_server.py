"""End-to-end tests over the MCP tool surface, with the Windy API stubbed."""

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

import server.server as srv


class _StubResponse:
    def __init__(self, status_code: int, body: dict | None, text: str = ""):
        self.status_code = status_code
        self._body = body
        self.text = text

    def json(self) -> dict:
        return self._body


DEFAULT_BODY = {
    "ts": [1700000000000, 1700010800000],
    "units": {
        "temp-surface": "K",
        "wind_u-surface": "m*s-1",
        "wind_v-surface": "m*s-1",
        "past3hprecip-surface": "m",
    },
    "temp-surface": [273.15, 283.15],
    "wind_u-surface": [3.0, 3.0],
    "wind_v-surface": [4.0, 4.0],
    "past3hprecip-surface": [0.002, 0.0],
}


@pytest.fixture
def windy(monkeypatch):
    """Capture the outgoing request and control the stubbed API response."""
    state = {"status": 200, "body": DEFAULT_BODY, "text": "", "sent": None}

    async def fake_post(self, url, json=None, **kwargs):
        state["url"] = url
        state["sent"] = json
        return _StubResponse(state["status"], state["body"], state["text"])

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    return state


def _series(result):
    return {s["parameter_level"]: s for s in result.data["series"]}


# --- Registration --------------------------------------------------------


async def test_tools_and_prompts_are_registered():
    async with Client(srv.mcp) as client:
        tools = {t.name for t in await client.list_tools()}
        prompts = {p.name for p in await client.list_prompts()}
    assert tools == {
        "get_weather_forecast",
        "get_wave_forecast",
        "get_air_quality_forecast",
        "get_windy_map",
    }
    assert prompts == {
        "weather_briefing",
        "surf_report",
        "air_quality_check",
        "weather_map",
    }


async def test_coordinate_bounds_are_advertised_in_the_schema():
    async with Client(srv.mcp) as client:
        tool = next(
            t for t in await client.list_tools() if t.name == "get_weather_forecast"
        )
    lat = tool.inputSchema["properties"]["lat"]
    assert lat["minimum"] == -90 and lat["maximum"] == 90


# --- Request construction ------------------------------------------------


async def test_request_body_matches_the_documented_shape(windy):
    async with Client(srv.mcp) as client:
        await client.call_tool(
            "get_weather_forecast",
            {
                "lat": 49.809,
                "lon": 16.787,
                "parameters": ["temp", "wind"],
                "levels": ["surface", "850h"],
            },
        )
    assert windy["url"] == "https://api.windy.com/api/point-forecast/v2"
    assert windy["sent"] == {
        "lat": 49.809,
        "lon": 16.787,
        "model": "gfs",
        "parameters": ["temp", "wind"],
        "levels": ["surface", "850h"],
        "key": "test-point-key",
    }


async def test_temp_unit_is_not_sent_to_windy(windy):
    async with Client(srv.mcp) as client:
        await client.call_tool(
            "get_weather_forecast",
            {"lat": 0, "lon": 0, "parameters": ["temp"], "temp_unit": "kelvin"},
        )
    assert "temp_unit" not in windy["sent"]


@pytest.mark.parametrize("lat,lon", [(91, 0), (0, 181)])
async def test_out_of_range_coordinates_are_rejected(windy, lat, lon):
    async with Client(srv.mcp) as client:
        with pytest.raises(ToolError):
            await client.call_tool(
                "get_weather_forecast",
                {"lat": lat, "lon": lon, "parameters": ["temp"]},
            )
    assert windy["sent"] is None


# --- Response shaping ----------------------------------------------------


async def test_wind_is_reported_as_speed_and_bearing(windy):
    async with Client(srv.mcp) as client:
        result = await client.call_tool(
            "get_weather_forecast",
            {"lat": 0, "lon": 0, "parameters": ["temp", "wind", "precip"]},
        )
    series = _series(result)
    assert "wind_u-surface" not in series
    assert series["wind_speed-surface"]["values"] == [5.0, 5.0]
    assert "blows FROM" in series["wind_dir-surface"]["description"]


async def test_units_are_converted_for_the_reader(windy):
    async with Client(srv.mcp) as client:
        result = await client.call_tool(
            "get_weather_forecast",
            {"lat": 0, "lon": 0, "parameters": ["temp", "precip"]},
        )
    series = _series(result)
    assert series["temp-surface"]["unit"] == "°C"
    assert series["temp-surface"]["values"] == [0.0, 10.0]
    assert series["past3hprecip-surface"]["unit"] == "mm"
    assert series["past3hprecip-surface"]["values"] == [2.0, 0.0]


async def test_timestamps_are_formatted_in_utc(windy):
    async with Client(srv.mcp) as client:
        result = await client.call_tool(
            "get_weather_forecast", {"lat": 0, "lon": 0, "parameters": ["temp"]}
        )
    assert result.data["timestamps_utc"][0].endswith("UTC")


async def test_unsupported_parameters_are_explained_not_silently_dropped(windy):
    windy["body"] = {
        "ts": [1700000000000],
        "units": {"aqi_us-surface": None},
        "aqi_us-surface": [42.0],
    }
    async with Client(srv.mcp) as client:
        result = await client.call_tool(
            "get_air_quality_forecast",
            {"lat": 0, "lon": 0, "parameters": ["aqi", "pollenBirch"]},
        )
    notes = " ".join(result.data["notes"])
    assert "pollenBirch" in notes and "camsEu" in notes


async def test_pressure_levels_without_a_level_aware_parameter_are_flagged(windy):
    async with Client(srv.mcp) as client:
        result = await client.call_tool(
            "get_weather_forecast",
            {"lat": 0, "lon": 0, "parameters": ["precip"], "levels": ["850h"]},
        )
    assert any("surface values" in note for note in result.data["notes"])


async def test_no_notes_when_the_model_answers_everything(windy):
    async with Client(srv.mcp) as client:
        result = await client.call_tool(
            "get_weather_forecast", {"lat": 0, "lon": 0, "parameters": ["temp"]}
        )
    assert "notes" not in result.data


async def test_extra_api_fields_are_surfaced(windy):
    windy["body"] = dict(DEFAULT_BODY, warning="degraded model run")
    async with Client(srv.mcp) as client:
        result = await client.call_tool(
            "get_weather_forecast", {"lat": 0, "lon": 0, "parameters": ["temp"]}
        )
    assert result.data["api_fields"] == {"warning": "degraded model run"}


# --- Error handling ------------------------------------------------------


async def test_impossible_model_parameter_pairing_is_refused_before_the_call(windy):
    async with Client(srv.mcp) as client:
        with pytest.raises(ToolError, match="camsEu"):
            await client.call_tool(
                "get_air_quality_forecast",
                {"lat": 0, "lon": 0, "parameters": ["pollenBirch"], "model": "cams"},
            )
    assert windy["sent"] is None


async def test_204_blames_the_model_not_the_location(windy):
    windy["status"] = 204
    windy["body"] = None
    async with Client(srv.mcp) as client:
        with pytest.raises(ToolError) as excinfo:
            await client.call_tool(
                "get_weather_forecast", {"lat": 0, "lon": 0, "parameters": ["temp"]}
            )
    message = str(excinfo.value)
    assert "not a limitation of the location" in message


async def test_400_is_reported_as_an_invalid_request(windy):
    windy["status"] = 400
    windy["text"] = "bad body"
    async with Client(srv.mcp) as client:
        with pytest.raises(ToolError, match="Invalid request"):
            await client.call_tool(
                "get_wave_forecast", {"lat": 0, "lon": 0, "parameters": ["waves"]}
            )


async def test_500_is_reported_as_a_windy_failure(windy):
    windy["status"] = 500
    async with Client(srv.mcp) as client:
        with pytest.raises(ToolError, match="server error"):
            await client.call_tool(
                "get_wave_forecast", {"lat": 0, "lon": 0, "parameters": ["waves"]}
            )


# --- Sea coverage --------------------------------------------------------


async def test_currents_are_available_through_the_cmems_model(windy):
    windy["body"] = {
        "ts": [1700000000000],
        "units": {"seacurrents_u-surface": "m*s-1"},
        "seacurrents_u-surface": [0.3],
    }
    async with Client(srv.mcp) as client:
        result = await client.call_tool(
            "get_wave_forecast",
            {"lat": 0, "lon": 0, "parameters": ["currents"], "model": "cmems"},
        )
    assert windy["sent"]["model"] == "cmems"
    assert "seacurrents_u-surface" in _series(result)


# --- Map embed -----------------------------------------------------------


async def test_map_html_follows_the_windy_boot_contract():
    async with Client(srv.mcp) as client:
        result = await client.call_tool(
            "get_windy_map", {"lat": 46.5, "lon": 10.0, "overlay": "rainAccu"}
        )
    html = result.data["html"]
    assert '<div id="windy"></div>' in html
    assert "leaflet@1.4.0/dist/leaflet.js" in html
    assert "api.windy.com/assets/map-forecast/libBoot.js" in html
    assert '"overlay": "rainAccu"' in html
    assert '"key": "test-map-key"' in html
    # The overlay is an init option, so it is not set a second time.
    assert "store.set" not in html
    # Leaflet's stylesheet is documented as buggy with the Windy map.
    assert "leaflet.css" not in html


@pytest.mark.parametrize("zoom", [2, 19])
async def test_map_zoom_is_bounded(zoom):
    async with Client(srv.mcp) as client:
        with pytest.raises(ToolError):
            await client.call_tool("get_windy_map", {"lat": 0, "lon": 0, "zoom": zoom})
