# Phase 2b spike: docs-mcp + Qdrant + bge-m3 in ONE container for a small host (runs locally;
# also works on HF Spaces / Cloud Run, which are paid or need a card: DECISIONS #48–50). Assumptions: one public port ($PORT, else 7860),
# any uid (built for 1000), no persistent disk, 2 vCPU. So everything is baked in: the model
# and a snapshot of the indexed PDFs; Qdrant listens on 127.0.0.1 only.
# Build context: the folder made by deploy/demo/prepare.sh (also what Cloud Build receives).

# ---- builder: Python env + model ------------------------------------------------
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --group docs --no-install-project

# Download bge-m3 once and save it as a plain folder (safetensors + tokenizer), so the
# runtime never talks to the Hub. The revision is pinned for reproducibility.
# This layer comes BEFORE our code is copied: it depends only on the lockfile, so code
# changes reuse the cached ~2.3 GB model instead of downloading it again.
ARG MODEL_ID=BAAI/bge-m3
ARG MODEL_REVISION=5617a9f61b028005a4858fdac845db406aefb181
RUN /app/.venv/bin/python -c "\
from sentence_transformers import SentenceTransformer; \
m = SentenceTransformer('${MODEL_ID}', revision='${MODEL_REVISION}', device='cpu', cache_folder='/tmp/hf'); \
m.save('/models/bge-m3')" \
    && rm -rf /tmp/hf

COPY app ./app
COPY mcp_servers ./mcp_servers
RUN uv sync --frozen --no-dev --group docs --no-editable

# ---- runtime ---------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Qdrant's binary needs libunwind. HF runs containers as uid 1000.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libunwind8 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 user

COPY --from=qdrant/qdrant:v1.20.1 /qdrant/qdrant /usr/local/bin/qdrant
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder --chown=user:user /models /models
COPY --chown=user:user documents.snapshot /data/documents.snapshot
COPY --chown=user:user entrypoint.sh /app/entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HUB_OFFLINE=1 \
    EMBEDDING_MODEL=/models/bge-m3 \
    EMBEDDING_THREADS=2 \
    QDRANT_URL=http://127.0.0.1:6333 \
    QDRANT_COLLECTION=documents \
    DOCS_MCP_HOST=0.0.0.0 \
    DOCS_MCP_PORT=7860 \
    QDRANT__SERVICE__HOST=127.0.0.1 \
    QDRANT__STORAGE__STORAGE_PATH=/tmp/qdrant/storage \
    QDRANT__STORAGE__SNAPSHOTS_PATH=/tmp/qdrant/snapshots \
    QDRANT__TELEMETRY_DISABLED=true \
    QDRANT_INIT_FILE_PATH=/tmp/qdrant/.initialized

USER user
WORKDIR /home/user
EXPOSE 7860

HEALTHCHECK --interval=20s --timeout=5s --start-period=180s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/health', timeout=3)"]

CMD ["/app/entrypoint.sh"]
