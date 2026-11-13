# Progress

## Current phase
**Phase 2 (docs-mcp) started 2026-11-13, in learning mode.** Phase 1 is complete locally; CI is unverified because nothing has been pushed yet.

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

## Next
- CI stays unverified until you decide to push (nothing is pushed for now).
- Phase 2 (in progress, learning mode): docs-mcp server + ingestion + tests, following [docs/phase-2-docs-mcp.md](docs/phase-2-docs-mcp.md).
  - Done: step 1 (docs-mcp settings), step 2 (`extract.py`: PyMuPDF + NFKC + Arabic check). 70 tests passing.
  - Next: step 3 (token-based chunking).
- Parallel track (needs your approval): sample PDFs + `data/notes/` topics, and 25 eval questions with `expected_aspects`.

## Known issues / risks
- The Groq free-tier token/day limit means the eval will take several weeks (measured in Phase 3b).
- Hierarchical mode may be unreliable; the fallback is a two-model comparison.
- HF Space limits (image size, RAM, cold start) are still unmeasured until Phase 2b. The api image is already 1.47 GB.
- mcp is pinned below 2 because of crewai; revisit when crewai supports mcp 2.x.
- Starlette warns that `TestClient` with `httpx` is deprecated in favour of `httpx2`. Harmless for now; switching would add a library, so it needs approval.
- uvicorn's own access logs are not JSON yet (planned for Phase 4).
- On this machine port 6333 is used by another Qdrant (`de-rs`), so the local `.env` sets `QDRANT_HOST_PORT=6335`.
- VS Code shows "pydantic is not installed": select the project interpreter `.venv/bin/python`.
