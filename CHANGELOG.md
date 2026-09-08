# Changelog

## v0.3.1 (2026-09-08)

### BREAKING CHANGE

- Weather forecasts no longer return the raw `wind_u-*` / `wind_v-*` vector components. Wind is now reported as `wind_speed-*` and `wind_dir-*` (the bearing the wind blows from, degrees clockwise from true north), which is what callers were misreading the components as.

### Fixes

- fix: Convert accumulated precipitation from metres to millimetres, and label it as a 3-hour accumulation
- fix: Decode `ptype` and `weatherWarnings` numeric codes by attaching a legend of the codes present in the response
- fix: Add the missing `cmems` sea model with its `currents` and `currentsTide` parameters
- fix: Validate latitude and longitude ranges in the tool schemas instead of forwarding out-of-range coordinates to Windy
- fix: Reject a model/parameter pairing the model cannot answer at all, naming the models that can, instead of returning an opaque 204
- fix: Explain in a `notes` field which requested parameters the chosen model omits, rather than silently returning fewer series
- fix: Warn when pressure levels are requested but no requested parameter varies by level
- fix: Correct the 204 error message, which blamed the location for what is a model limitation
- fix: Surface non-series fields from the Windy response instead of discarding them
- fix: Point the `air_quality_check` prompt at `camsEu`, without which it could never return pollen
- fix: Bound the map zoom level and drop the redundant overlay assignment from the generated map page

### Changes

- feat: Document per-model parameter coverage and response units in the tool descriptions
- test: Add a test suite covering the request shape, support matrix, unit conversion and error mapping, and run it in CI
- feat: Pushing a version tag now runs the tests, publishes a multi-architecture container image to the GitHub Container Registry, and creates the GitHub Release
- ci: Disable PyPI publishing; releases ship as container images, and the test suite runs before every release build


## v0.3.0 (2026-06-22)

### BREAKING CHANGE

- The API key environment variable was renamed `WINDY_API_KEY` → `WINDY_POINT_API_KEY` to reflect that it is a Windy **Point Forecast** API key. Update your MCP client config / environment accordingly.

### Changes

- feat: Add Streamable HTTP transport via --transport/--host/--port/--path flags (env: WINDY_MCP_*)
- feat: Add static bearer-token auth for the HTTP transport via WINDY_MCP_AUTH_TOKEN
- feat: Add unauthenticated GET /health endpoint and Docker HEALTHCHECK
- feat: Start without WINDY_POINT_API_KEY instead of erroring; forecast tools are hidden until a key is configured
- feat: Read optional WINDY_MAP_API_KEY (Windy Map Forecast API key) from configuration
- feat: Add get_windy_map tool that renders an interactive Windy map (HTML) via the Map Forecast API, gated on WINDY_MAP_API_KEY
- docs: Add Data handling & security section (transport security, access-log IPs, data flow to Windy) and disclaimer
- feat: Add predefined MCP prompts (weather_briefing, surf_report, air_quality_check, weather_map), gated on the relevant API key
- docs: Add example prompts for each tool
- feat: Add Dockerfile and .dockerignore for containerized HTTP deployment
- chore: Upgrade fastmcp to 3.4.2 and refresh dependencies
- refactor: Use StrEnum and drop redundant payload serialization in the client

## v0.2.2 (2026-06-01)


- ci: Fix failing cicd

## v0.2.1 (2026-06-01)


- docs: Add license file
- Update publish
- Merge remote-tracking branch 'refs/remotes/origin/main'
- fix: Fix broken gh action

## v0.2.0 (2026-06-01)


- feat: Add support for pypi
- ci: Add commitizen support
- Add quality check action
- Add ruff and pre-commit
- Add documentation
- Initial commit
- Initial commit
