# ResearchCrew API image (multi-stage, non-root).
# Builder installs the locked `api` group into /app/.venv; runtime copies only that venv.
# Both stages use the same base image so the venv's Python path is identical.

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
COPY app ./app
COPY mcp_servers ./mcp_servers
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --group api --no-editable

# ---- runtime -------------------------------------------------------------------
FROM python:3.12-slim AS runtime

RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER app
EXPOSE 8000

# No curl in slim images: use Python's urllib (non-2xx raises -> exit code 1).
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
