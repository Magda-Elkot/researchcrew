# Phase 2 — docs-mcp server + ingestion + tests

**Status:** high-level. This gets a detailed plan when the phase starts. [Back to master plan](PLAN.md)

## Goal
Build our own MCP server, `docs-mcp`, with FastMCP. It does semantic search over a folder of PDFs indexed in Qdrant with BAAI/bge-m3.

## Scope
- **Sample data:** I propose 2–3 topics and 10–15 freely licensed PDFs (English + Arabic), and you approve them. Sources are documented in `data/SOURCES.md`.
- **Extraction:** PyMuPDF. An Arabic check runs on ≥2 PDFs to catch reversed or broken letters, with a fix if needed.
- **Chunking:** ~800 tokens with ~100 overlap, counted with the bge-m3 tokenizer. Metadata per chunk: doc_id, title, page, language, chunk index.
- **Embeddings:** bge-m3 dense vectors (1024-d) through sentence-transformers on CPU torch.
- **Qdrant:** collection `documents`, cosine distance. Ingest is idempotent: there's a stable doc_id and re-ingesting replaces the document's points.
- **`ingest` CLI:** indexes a folder of PDFs, e.g. `uv run ingest data/pdfs`.
- **FastMCP server**, run over streamable HTTP:
  - tool `search_documents(query, top_k)`
  - tool `get_document(doc_id)`: full text + metadata
  - resource `docs://list`
- **Container:** `docker/docs-mcp.Dockerfile` (multi-stage, non-root, healthcheck) and a compose service. The model is cached in a volume.

## Key files
- `mcp_servers/docs_mcp/{server.py, ingest.py, extract.py, chunking.py, embeddings.py, store.py}`
- `tests/docs_mcp/`
- `data/SOURCES.md`

## Tests
- A unit test for every tool and the resource, with the embedder and Qdrant mocked.
- Unit tests for chunking and extraction (including an Arabic fixture).

## Definition of done
- `ingest` indexes data/pdfs.
- Every docs-mcp tool has passing unit tests.
- The server works with the MCP Inspector.

## Open items
- The final topic and PDF list (needs your approval).
- Model download size (~2.3GB) and how long the first startup takes.
