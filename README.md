# windy-mcp-server

> **Unofficial** MCP server for the [Windy Point Forecast API](https://api.windy.com/point-forecast/docs). This project is not affiliated with, endorsed by, or sponsored by Windy.com, and is maintained independently in the author's free time. See the [Disclaimer](#disclaimer).

An MCP (Model Context Protocol) server that exposes weather, ocean wave, and air quality forecasts to AI assistants via the Windy Point Forecast API.

## Tools

### `get_weather_forecast`
Fetch atmospheric weather data for any coordinates.

- **Parameters:** temperature, dewpoint, relative humidity, pressure, geopotential height, precipitation (total/snow/convective), wind, wind gusts, cloud cover (low/mid/high), cloud base, visibility, CAPE, precipitation type, weather warnings
- **Models:** GFS, ICON, ICON-EU, ICON-D2, AROME (France, Antilles, Réunion), NAM (CONUS/Hawaii/Alaska), HRRR (CONUS/Alaska), HRDPS
- **Pressure levels:** surface through 150 hPa (14 levels)
- **Temperature units:** Celsius or Kelvin

### `get_wave_forecast`
Fetch ocean wave and current data for any coastal or open-water coordinates.

- **Parameters:** significant wave height, wind waves, wave power, swell 1 & 2, sea currents, tidal currents
- **Models:** GFS Wave, ICON Wave, ICON-EU Wave, RDWPS (Canada), CMEMS (currents only)

### `get_air_quality_forecast`
Fetch air quality and pollen forecasts for any location.

- **Parameters:** AQI, SO₂, dust, CO, O₃, NO₂, PM10, PM2.5, pollen (alder, birch, grass, mugwort, olive, ragweed)
- **Models:** CAMS (global), CAMS-EU (higher-resolution European data). **Pollen is CAMS-EU only.**

### `get_windy_map`
Render an interactive Windy weather map for any location using the Windy **Map Forecast API**. Requires `WINDY_MAP_API_KEY`.

Because the Map Forecast API is a browser (Leaflet) library rather than a data endpoint, this tool returns a **self-contained HTML page** that boots the interactive Windy map centered on the coordinates with the chosen overlay — save it to a file and open it in a browser.

- **Overlays:** wind, gust, temperature, dew point, humidity, pressure, clouds, rain, accumulated rain/snow, thunder, waves, swell, CAPE
- **Parameters:** lat, lon, overlay, zoom

> **Note:** The returned HTML embeds your Map Forecast API key client-side (as the Windy Map API requires) and loads third-party scripts (`unpkg.com`, `api.windy.com`). [Domain-restrict the Map key](https://api.windy.com/keys) in your Windy dashboard, and if you publish the page to end users, the Windy map library may set cookies/local storage in their browser — add cookie consent/notice as required by the ePrivacy Directive. See [Data handling & security](#data-handling--security).

## Reading the results

Windy returns raw model output. These tools decode the parts that are easy to misread:

| Windy returns | The tools return |
| --- | --- |
| `wind_u` / `wind_v` vector components | `wind_speed` plus `wind_dir`, the bearing in degrees the wind blows **from** |
| Temperature in Kelvin | Celsius by default, at every pressure level (`temp_unit` switches it back) |
| `past3hprecip` in metres | Millimetres, labelled as a 3-hour accumulation |
| `ptype` / `weatherWarnings` integer codes | The same codes plus a `legend` naming the ones present |

Model coverage is uneven: `gh` needs an ICON model, `cbase` needs AROME, `visibility` needs AROME France or Réunion, `weatherWarnings` needs NAM CONUS or HRDPS, `windWaves` needs GFS Wave or ICON Wave, currents need CMEMS, and pollen needs CAMS-EU. Windy drops unsupported series silently, so a response that is missing one carries a `notes` entry naming the models that do provide it. Asking a model for nothing it supports is refused before the request is sent.

## Prompts

The server ships **predefined MCP prompts** — reusable templates your client can list and invoke (often as slash-commands) that steer the assistant to the right tools. They appear only when the required key is configured.

| Prompt | Arguments | Needs |
| --- | --- | --- |
| `weather_briefing` | `location`, `days` (default 3) | `WINDY_POINT_API_KEY` |
| `surf_report` | `spot` | `WINDY_POINT_API_KEY` |
| `air_quality_check` | `location`, `health_context` (optional) | `WINDY_POINT_API_KEY` |
| `weather_map` | `location`, `overlay` (default wind) | `WINDY_MAP_API_KEY` |

## Example prompts

You don't have to use the predefined prompts — just ask in natural language and the assistant picks the right tool, coordinates, model, and parameters.

**Weather** (`get_weather_forecast`)
- "What's the wind and temperature forecast for Lisbon over the next 3 days?"
- "Give me precipitation and cloud cover for Munich using the ICON-EU model, in Celsius."
- "Show the temperature and geopotential height at 850 hPa and 500 hPa over Denver."
- "Will there be thunderstorms near Miami tomorrow? Check CAPE and precipitation type."

**Waves** (`get_wave_forecast`)
- "What's the significant wave height and swell off Nazaré, Portugal this weekend?"
- "Wave power and wind waves near Sydney using the ICON Wave model."
- "Is it a good day to surf at Tarifa? Show wave height and primary swell."

**Air quality & pollen** (`get_air_quality_forecast`)
- "What's the air quality (AQI, PM2.5, PM10) forecast for Kraków?"
- "Birch and grass pollen outlook for Berlin using CAMS-EU."
- "Compare ozone and NO₂ levels in Paris over the next two days."

**Interactive map** (`get_windy_map`, requires `WINDY_MAP_API_KEY`)
- "Render an interactive wind map centered on the Alps."
- "Give me a temperature map of Florida at city-level zoom."
- "Build a rain-accumulation map for the UK and save it so I can open it in a browser."

**Multi-step**
- "Compare the wind forecast for Tarifa and Nazaré this weekend and tell me which looks better for surfing."
- "I have asthma and I'm traveling to Milan — check the air quality and pollen, then summarize whether it's a concern."

## Setup

**Prerequisites:** a [Windy API key](https://api.windy.com/keys), plus either [uv](https://docs.astral.sh/uv/) (local stdio) or Docker (networked HTTP).

Releases are published as **container images on the GitHub Container Registry**. This repository does **not** publish to PyPI: the `windy-mcp-server` package on PyPI comes from the upstream project and does not carry the changes here, so install from the container image or straight from git.

**Local stdio client.** Add to your MCP client config (e.g. `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "windy": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/marcinn2/windy-mcp-server",
        "windy-mcp-server"
      ],
      "env": {
        "WINDY_POINT_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

Pin a release by appending the tag: `git+https://github.com/marcinn2/windy-mcp-server@v0.3.1`.

**Networked client.** Run the published image and point your client at its HTTP endpoint, see [Docker](#docker). The image's entrypoint always starts the Streamable HTTP transport, so it does not serve stdio.

| Env | Required | Description |
| --- | --- | --- |
| `WINDY_POINT_API_KEY` | Yes (to expose tools) | Windy **Point Forecast** API key. Without it the server still starts but exposes no tools. |
| `WINDY_MAP_API_KEY` | No | Windy **Map Forecast** API key. Enables the `get_windy_map` tool. |

By default the server communicates over **stdio**, which is what the config above uses.

## Transport

The server supports two transports, selectable via CLI flags (or the matching `WINDY_MCP_*` environment variables):

| Flag | Env | Default | Description |
| --- | --- | --- | --- |
| `--transport` | `WINDY_MCP_TRANSPORT` | `stdio` | `stdio` for local subprocess clients, `http` for a networked [Streamable HTTP](https://modelcontextprotocol.io/specification/basic/transports) server |
| `--host` | `WINDY_MCP_HOST` | `127.0.0.1` | Host to bind (HTTP only) |
| `--port` | `WINDY_MCP_PORT` | `8000` | Port to bind (HTTP only) |
| `--path` | `WINDY_MCP_PATH` | `/mcp/` | Endpoint path (HTTP only) |

Run a Streamable HTTP server. The `windy-mcp-server` command below assumes an installed checkout; to run it without installing, use the published image (see [Docker](#docker)) or prefix the examples with `uvx --from git+https://github.com/marcinn2/windy-mcp-server`.

```bash
WINDY_POINT_API_KEY=your_api_key_here windy-mcp-server --transport http --port 8000
# endpoint: http://127.0.0.1:8000/mcp/
```

### Authentication

Set `WINDY_MCP_AUTH_TOKEN` to require a static **bearer token** on the MCP endpoint when using the HTTP transport. Clients must then send `Authorization: Bearer <token>`; requests without a valid token get `401`. If the variable is unset, the endpoint is unauthenticated (and a warning is logged on startup).

```bash
WINDY_POINT_API_KEY=your_api_key_here WINDY_MCP_AUTH_TOKEN=your_secret_token \
  windy-mcp-server --transport http
```

### Health check

A `GET /health` endpoint returns `{"status": "ok"}` and is **always unauthenticated**, so it can be used as a liveness/readiness probe regardless of the auth setting.

## Docker

Prebuilt images are published to the GitHub Container Registry on every release, for `linux/amd64` and `linux/arm64`:

```bash
docker pull ghcr.io/marcinn2/windy-mcp-server:latest    # or a version, e.g. :0.3.1
```

The image's entrypoint always starts the Streamable HTTP transport on port 8000.

```bash
docker run --rm -p 8000:8000 \
  -e WINDY_POINT_API_KEY=your_api_key_here \
  -e WINDY_MCP_AUTH_TOKEN=your_secret_token \
  ghcr.io/marcinn2/windy-mcp-server:latest
# endpoint: http://localhost:8000/mcp/  (Authorization: Bearer your_secret_token)
# health:   http://localhost:8000/health
```

To build it yourself instead:

```bash
docker build -t windy-mcp-server .
docker run --rm -p 8000:8000 \
  -e WINDY_POINT_API_KEY=your_api_key_here \
  -e WINDY_MCP_AUTH_TOKEN=your_secret_token \
  windy-mcp-server
# endpoint: http://localhost:8000/mcp/  (Authorization: Bearer your_secret_token)
# health:   http://localhost:8000/health
```

`WINDY_MCP_AUTH_TOKEN` is optional but recommended for HTTP. Override host/port/path via the `WINDY_MCP_*` env vars, e.g. `-e WINDY_MCP_PORT=9000 -p 9000:9000`. The image also defines a `HEALTHCHECK` against `/health`.

## Development

```bash
uv sync --group dev
uv run pytest            # test suite (no API key or network access required)
uv run pre-commit run --all-files
```

The tests stub the Windy HTTP call, so they assert the request body, the model/parameter
support matrix, unit conversion, and error mapping without spending API quota.

## Data handling & security

This server is **stateless**: it stores no personal data — no database, files, cookies, analytics, or tracking. The notes below are for operators deploying it (especially over HTTP) and reflect a preliminary GDPR/ePrivacy review; they are not legal advice.

- **What data flows where.** Forecast tools forward the requested coordinates (`lat`/`lon`) and parameters to the Windy Point Forecast API (`api.windy.com`, operated by Windyty S.E. in the EU/Czech Republic) over HTTPS. Coordinates are **not stored** by this server. If you offer the service to end users, tell them their query coordinates are sent to Windy, and review Windy's [terms](https://www.windy.com/terms) and whether a processor agreement applies to your use.
- **Transport security.** The HTTP transport binds plain HTTP and is **unauthenticated unless `WINDY_MCP_AUTH_TOKEN` is set**. For anything beyond local/loopback use, run it **behind a TLS-terminating proxy** and always set a bearer token — otherwise request payloads and the token travel in cleartext. The default bind host is `127.0.0.1`; only expose a public host (`0.0.0.0`) behind such a proxy.
- **Access logs / IP addresses.** When running over HTTP, the underlying server (uvicorn) writes access logs containing **client IP addresses** (personal data under GDPR). This project does not log request contents. Set a retention/rotation policy for those logs, and disable access logging if you don't need it (e.g. `--no-access-log` via your process manager / a custom uvicorn log config).
- **Secrets.** API keys and the bearer token are read from environment variables and never persisted. The Windy Point key is sent only over HTTPS; the Map key is embedded client-side by design (see [`get_windy_map`](#get_windy_map)).

## Disclaimer

This is an **unofficial**, independent project. It is **not affiliated with, endorsed by, or sponsored by Windy.com**. "Windy" and related names and trademarks belong to their respective owners and are used here only to describe interoperability.

I build and maintain this project in my **free time**, with no warranty and no guarantee of support, availability, or updates. Use of the Windy APIs is subject to Windy's own terms of service and requires your own API key.

## License

[MIT](LICENSE)
