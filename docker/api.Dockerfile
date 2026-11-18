# ResearchCrew API image (multi-stage, non-root).
# Builder installs the locked `api` group into /app/.venv; runtime copies only that venv.
# Both stages use the same base image so the venv's Python path is identical.
# A Node stage installs the pinned filesystem MCP server; runtime copies only `node` and the
# server, so agents start it as a local command (no npx download at run time; DECISIONS #76).

# ---- filesystem MCP server (Node) ---------------------------------------------
# node:24-bookworm-slim = Node v24.22.3, pinned by digest (the server needs Node >= 24).
FROM node:24-bookworm-slim@sha256:dc26ae92c9fb15cf6b1d63e20f0944b2efe0f115b20e00be48fb23fceb061c54 AS mcp-fs
ARG FILESYSTEM_MCP_PACKAGE=@modelcontextprotocol/server-filesystem@2.3.0
RUN npm install --global --prefix /opt/mcp-fs --omit=dev "$FILESYSTEM_MCP_PACKAGE" \
    && npm cache clean --force

# ---- builder -------------------------------------------------------------------
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# 1) Dependencies only: this layer is cached until pyproject.toml/uv.lock change.
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --group api --no-install-project

# 2) The project itself (installed as a normal, non-editable package).
# --reinstall-package: uv decides whether to rebuild our package from pyproject.toml only, so
# with the cache mount a code-only change would install the previous build (DECISIONS #96).
COPY app ./app
COPY mcp_servers ./mcp_servers
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --group api --no-editable --reinstall-package researchcrew

# ---- runtime -------------------------------------------------------------------
FROM python:3.12-slim AS runtime

RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=mcp-fs /usr/local/bin/node /usr/local/bin/node
COPY --from=mcp-fs /opt/mcp-fs /opt/mcp-fs
# uvicorn's own logs (startup, access) as JSON, like the app's (Phase 5).
COPY app/api/uvicorn_log.json /app/uvicorn_log.json
# The CLI writes reports to outputs/; the API keeps its SQLite job store in var/ (a volume).
RUN mkdir -p /app/outputs /app/var && chown app:app /app/outputs /app/var

ENV PATH="/app/.venv/bin:/opt/mcp-fs/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FILESYSTEM_MCP_COMMAND=mcp-server-filesystem

USER app
EXPOSE 8000

# No curl in slim images: use Python's urllib (non-2xx raises -> exit code 1).
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--log-config", "/app/uvicorn_log.json"]
