# Changelog

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
