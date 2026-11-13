# Progress

## Current phase
**Phase 2 (docs-mcp) complete locally, 2026-11-13; waiting for your review.** CI for Phase 2 runs when you push. Phase 1 is complete with green CI (30e1594, 93b30ab).

## Done
- 2026-11-13: plan reviewed against SPEC.md. Docs updated: PLAN.md, all phase docs, and the new phase-2b spike. Decisions recorded in DECISIONS.md.
- 2026-11-13: Phase 1.
  - All dependency groups (`api`, `docs`, `frontend`, `dev`) resolved together in one `uv.lock` (204 packages). CPU-only torch.
  - crewai 1.15.41 forces mcp 1.x and pydantic <2.13 (DECISIONS #20–21).
  - `app/config.py` (Settings, `get_settings`, `require`), `app/log.py` (JSON + redaction), `app/schemas.py` (all SPEC contracts + API models).
  - Placeholder API (`/health`, `/metrics`, startup key check) and CLI stub (`uv run researchcrew`).
  - 55 tests passing; ruff and mypy (strict) clean.
  - Docker: multi-stage non-root api image (1.47 GB) + Qdrant v1.20.1; both healthy in compose.
  - Makefile, `.gitignore`, `.dockerignore`, `.env.example`, GitHub Actions CI (lint-test + docker build).
- 2026-11-13: Phase 2: docs-mcp (DECISIONS #27–38, measurements in DECISIONS).
  - `extract.py`: PyMuPDF, NFKC, scanned-PDF rejection, Arabic checks (presentation forms, reversed text), lam-alef fix, rejection of swapped-pair fonts. Found and handled on real WHO PDFs.
  - `chunking.py` (bge-m3 tokens, 800/100, page ranges), `embeddings.py` (bge-m3 CPU, thread cap), `store.py` (Qdrant, idempotent), `ingest.py` (`uv run ingest`, skips unchanged files).
  - `server.py`: FastMCP over streamable HTTP; tools `search_documents`, `get_document`; resource `docs://list`; `/health`.
  - 5 sample PDFs (WHO EMRO EN+AR, IRENA ×2, UNESCO flyer) → 230 chunks; `data/SOURCES.md`; topic notes in `data/notes/`.
  - 114 tests passing (fake embedder, in-memory Qdrant, real in-memory MCP client session); ruff + mypy strict clean.
  - Verified with MCP Inspector 2.13.0 (CLI): list tools/resources, both tools, the resource, a validation error.
  - Docker: `docs-mcp` image 1.73 GB, healthy in 12 s, non-root; model mounted from the host cache; CI builds both images.
  - Bruno: `docs_mcp_health.bru` added.
- 2026-11-13: review of Phases 1–2 (DECISIONS #39–41): ports bound to localhost (security), pipeline version in the ingest fingerprint, `--prune`, duplicate doc_id detection, `EMBEDDING_THREADS=0` = all cores; `get_document` now reads page ranges, capped (DECISIONS #42). 125 tests passing.

## Definition of done: Phase 2
- [x] `ingest` indexes data/pdfs (5 PDFs, 230 chunks; the broken 2019 WHO PDF is rejected by design).
- [x] Every docs-mcp tool (and the resource) has passing unit tests.
- [x] The server works with the MCP Inspector.

## Next
- Your review of Phase 2, then a local commit (commands in the Phase 2 summary). CI runs on your next push.
- Optional data top-up (manual browser download, see `data/SOURCES.md`): the UNESCO Recommendation full text (EN + AR) and an Arabic renewable-energy report. Then `make ingest`.
- Phase 2b (HF Space spike) or Phase 3a (MCP spike with CrewAI), per docs/PLAN.md.
- Parallel track (needs your approval): 25 eval questions with `expected_aspects`, covering the indexed topics.

## Known issues / risks
- The Groq free-tier token/day limit means the eval will take several weeks (measured in Phase 3b).
- Hierarchical mode may be unreliable; the fallback is a two-model comparison.
- HF Space limits: api image 1.47 GB, docs-mcp image 1.73 GB + a 2.3 GB model; to be tested in Phase 2b.
- mcp is pinned below 2 because of crewai; revisit when crewai supports mcp 2.x.
- Starlette warns that `TestClient` with `httpx` is deprecated in favour of `httpx2`. Harmless for now; switching would add a library, so it needs approval.
- uvicorn's own access logs are not JSON yet (planned for Phase 4).
- On this machine port 6333 is used by another Qdrant (`de-rs`), so the local `.env` sets `QDRANT_HOST_PORT=6335` and `QDRANT_URL=http://localhost:6335`.
- Sample data is thinner than planned (5 PDFs, not 10–15; AI ethics only a 2-page flyer; no Arabic energy document), because several publishers block scripted downloads.
- The UNESCO flyer has no licence statement, so it's git-ignored until confirmed.
- The WHO PDFs have no title metadata, so their title is the file name.
- Arabic numbers and punctuation can appear out of place inside RTL lines (PDF bidi order); search still works.
- The lam-alef fix covers only the safe "ال + alef-type" case; other swapped pairs make a PDF be rejected, not fixed.
- VS Code shows "pydantic is not installed": select the project interpreter `.venv/bin/python`.
