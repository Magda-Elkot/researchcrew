# Phase 2 — docs-mcp server + ingestion + tests

**Status:** done locally 2026-11-13 (steps 1–2 in learning mode, 3–12 by Claude on request). Detailed steps are at the end of this file. [Back to master plan](PLAN.md)

## Goal
Build our own MCP server, `docs-mcp`, with FastMCP. It does semantic search over a folder of PDFs indexed in Qdrant with BAAI/bge-m3.

## Scope
- **Sample data** (chosen on the parallel track during Phase 1, approved by you):
  - 2–3 topics and 10–15 freely licensed, **born-digital** PDFs (English + Arabic; no scanned PDFs, since OCR is out of scope). Sources are documented in `data/SOURCES.md`.
  - Curated Markdown topic notes in `data/notes/` (glossary, key facts with sources) for the filesystem MCP.
- **Extraction:** PyMuPDF, then NFKC normalisation. An Arabic check runs on ≥2 PDFs to catch reversed or broken letters. It flags a high share of Arabic presentation-form characters (U+FB50–U+FEFF) and reversed words, and a fix is applied if needed.
- **Chunking:** ~800 tokens with ~100 overlap, counted with the bge-m3 tokenizer. Metadata per chunk: doc_id, title, page, language, chunk index.
- **Embeddings:** bge-m3 dense vectors (1024-d) through sentence-transformers on CPU torch.
- **Qdrant:** collection `documents`, cosine distance. Ingest is idempotent: there's a stable doc_id and re-ingesting replaces the document's points.
- **`ingest` CLI:** indexes a folder of PDFs, e.g. `uv run ingest data/pdfs`.
- **FastMCP server**, run over streamable HTTP:
  - tool `search_documents(query, top_k)`
  - tool `get_document(doc_id)`: full text + metadata
  - resource `docs://list`
- **Container:** `docker/docs-mcp.Dockerfile` (multi-stage, non-root, healthcheck; installs only the `docs` group) and a compose service. The model is cached in a volume.

## Key files
- `mcp_servers/docs_mcp/{server.py, ingest.py, extract.py, chunking.py, embeddings.py, store.py}`
- `tests/docs_mcp/`
- `data/SOURCES.md`, `data/notes/`

## Tests
- A unit test for every tool and the resource, with the embedder and Qdrant mocked.
- Unit tests for chunking and extraction (including an Arabic fixture).
- **No network access in tests:** chunking tests use a small local tokenizer stub, not a bge-m3 download from the Hugging Face Hub.

## Definition of done
- `ingest` indexes data/pdfs.
- Every docs-mcp tool has passing unit tests.
- The server works with the MCP Inspector (`npx @modelcontextprotocol/inspector`; needs Node on your machine).

## Detailed steps (learning mode: Claude explains and writes files, you run commands)

| # | Step | Files | Concept explained first | You run |
|---|---|---|---|---|
| 1 | Settings for docs-mcp | `app/config.py`, `.env.example`, tests | Why docs-mcp reuses the shared `app.config` and `app.log` | `make check` |
| 2 | PDF text extraction + Arabic check | `extract.py`, `tests/docs_mcp/test_extract.py` (PDF fixtures generated in the test with PyMuPDF) | Born-digital vs scanned PDFs, NFKC, Arabic presentation forms, visual vs logical order | `uv run pytest tests/docs_mcp` |
| 3 | Token-based chunking | `chunking.py` + tests (tokenizer stub) | Why chunk, why count tokens (not characters), why overlap | pytest |
| 4 | Embeddings | `embeddings.py` + tests (fake embedder) | Dense embeddings, bge-m3, normalising vectors for cosine similarity | pytest |
| 5 | Qdrant store | `store.py` + tests (qdrant-client in-memory mode, no server) | Collections, points, payloads, filters; idempotent upsert with deterministic point ids | pytest |
| 6 | `ingest` CLI | `ingest.py`, `[project.scripts] ingest` + tests | A stable `doc_id` and replace-on-reingest | pytest |
| 7 | FastMCP server | `server.py` + tests (tools and resource called in-process) | MCP tools vs resources, the streamable HTTP transport | pytest, then `uv run docs-mcp` |
| 8 | Sample data | `data/pdfs/*`, `data/SOURCES.md`, `data/notes/*.md` | Licences and attribution | Download the approved PDFs; the Arabic check on ≥2 PDFs |
| 9 | Real ingest | — | Model download and caching (`HF_HOME` on the Data drive: the home drive is 92% full) | `uv run ingest data/pdfs` (time it) |
| 10 | MCP Inspector | — | How an MCP client discovers and calls tools | `npx @modelcontextprotocol/inspector` |
| 11 | Docker | `docker/docs-mcp.Dockerfile`, compose service, model-cache volume; Bruno request for the docs-mcp health route | Baking vs mounting the model | `docker compose up --build`, healthy check |
| 12 | Wrap-up | DECISIONS (measurements: model size, first start, ingest time), PROGRESS, CLAUDE.md commands | — | Local commit (no push) |

## Open items
- The final PDF and notes list: topics are decided (DECISIONS #27: WHO health, UNESCO AI ethics, IRENA energy); the exact files still need your approval at step 8.
- Model download size (~2.3GB), how long the first startup takes, and how long ingest takes on CPU. Phase 2b uses these numbers.
