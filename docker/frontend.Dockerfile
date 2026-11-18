# ResearchCrew Streamlit frontend (multi-stage, non-root).
# Builder installs only the locked `frontend` group (streamlit, httpx) plus the project package
# (the page uses app.log for JSON logging); runtime copies the venv and the page.

# ---- builder -------------------------------------------------------------------
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# 1) Dependencies only: cached until pyproject.toml/uv.lock change.
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --group frontend --no-install-project

# 2) The project package (its build needs both package folders).
COPY app ./app
COPY mcp_servers ./mcp_servers
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --group frontend --no-editable

# ---- runtime -------------------------------------------------------------------
FROM python:3.12-slim AS runtime

RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
# The page is a plain folder, not part of the package: PYTHONPATH makes `frontend.*` importable.
COPY frontend ./frontend

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    API_URL=http://api:8000

USER app
EXPOSE 8501

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)"]

CMD ["streamlit", "run", "frontend/streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501", \
     "--server.headless=true", "--browser.gatherUsageStats=false"]
