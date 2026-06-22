# syntax=docker/dockerfile:1

# --- Build stage: resolve and install dependencies with uv ---
FROM python:3.12-slim-bookworm AS build

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    PIP_NO_CACHE_DIR=1

# Install uv from PyPI (avoids depending on an external container registry).
RUN pip install "uv>=0.9,<0.10"

WORKDIR /app

# Install dependencies first for better layer caching (no project code yet).
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Then install the project itself into the venv (non-editable).
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable


# --- Runtime stage: minimal image with just the venv ---
FROM python:3.12-slim-bookworm AS runtime

# Run as a non-root user.
RUN groupadd --system app && useradd --system --gid app --home-dir /app app

WORKDIR /app
COPY --from=build --chown=app:app /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    WINDY_MCP_HOST=0.0.0.0 \
    WINDY_MCP_PORT=8000 \
    WINDY_MCP_PATH=/mcp/

USER app
EXPOSE 8000

# Liveness probe hits the unauthenticated /health endpoint.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import os,sys,urllib.request; p=os.environ.get('WINDY_MCP_PORT','8000'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{p}/health', timeout=2).status==200 else 1)"

# Always start the Streamable HTTP server. Supply WINDY_POINT_API_KEY at runtime, and
# set WINDY_MCP_AUTH_TOKEN to require a bearer token on the MCP endpoint
# (the /health endpoint stays unauthenticated):
#   docker run -e WINDY_POINT_API_KEY=... -e WINDY_MCP_AUTH_TOKEN=... -p 8000:8000 windy-mcp-server
# Host/port/path are configurable via the WINDY_MCP_* env vars above
# (e.g. -e WINDY_MCP_PORT=9000 -p 9000:9000).
ENTRYPOINT ["windy-mcp-server", "--transport", "http"]
