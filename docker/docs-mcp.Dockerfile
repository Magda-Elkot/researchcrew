# docs-mcp image (multi-stage, non-root): MCP server over streamable HTTP on port 8001.
# Installs only the `docs` dependency group (CPU torch, sentence-transformers, pymupdf,
# qdrant-client, mcp). The bge-m3 model is NOT baked in: it lives in a volume at /models.

# ---- builder -------------------------------------------------------------------
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --group docs --no-install-project

COPY app ./app
COPY mcp_servers ./mcp_servers
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --group docs --no-editable

# ---- runtime -------------------------------------------------------------------
FROM python:3.12-slim AS runtime

RUN useradd --create-home --uid 10001 app \
    && mkdir -p /models \
    && chown app:app /models
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MODEL_CACHE_DIR=/models \
    DOCS_MCP_HOST=0.0.0.0 \
    DOCS_MCP_PORT=8001

USER app
EXPOSE 8001

# Loading bge-m3 on CPU takes a while (and the very first start downloads ~2.3 GB).
HEALTHCHECK --interval=20s --timeout=5s --start-period=180s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=3)"]

CMD ["docs-mcp"]
