# Decisions

Non-trivial decisions and why. SPEC.md's DECISIONS section is the baseline; this file records what was added or changed.
The summary table lives in [docs/PLAN.md](docs/PLAN.md#resolved-decisions).

## 2026-11-13 — Plan review

| # | Decision | Why |
|---|---|---|
| 1 | One Crew with 5 tasks; a thin Flow handles only the review → rewrite loop. | A Flow that drives every step leaves no Crew to switch to hierarchical, so the Phase 6 comparison wouldn't be possible. |
| 2 | Second eval config: sequential vs hierarchical, with **two generator models** as the fallback. | Hierarchical delegation is often unreliable with Llama on the free tier. SPEC allows either comparison. |
| 3 | Evidence passed between tasks is capped; eval = 25 questions × 2 configs at quick depth, expected to take several weeks. | Groq's free tier (~12K tokens/min, ~100K tokens/day for Llama 3.3 70B; check current limits) allows only a few reports per day. |
| 4 | The eval dataset has `expected_aspects` per question; completeness is judged against them. | Judging only against the Planner's own sub-questions would reward weak plans. |
| 5 | Faithfulness is judged against raw tool output; snippets must be verbatim substrings of it. | LLM-written snippets can be invented, which would make the metric meaningless. |
| 6 | One guarded-tool wrapper handles the call cap, retry, deadline, events and raw-result recording. | CrewAI has no per-run global tool cap, and SSE, evals and guardrails all need the same per-call data. |
| 7 | The timeout is cooperative; the job is marked failed on time; one uvicorn worker. | Synchronous `kickoff()` threads can't be killed, and the in-memory SSE queues need a single process. |
| 8 | Phase 3 split into a 3a MCP spike + 3b full crew; Phase 2b HF Space spike added. | De-risks the MCP adapter and the HF free-tier limits early. |
| 9 | Token usage and cost are collected in Phase 3b (LiteLLM price table); basic tracing in 3b, completed in Phase 5. | Phase 4's API must return them, and SPEC BUDGET needs them logged per run. Instrumentation has to happen before crewai is imported. |
| 10 | Log redaction uses explicit key names plus value scrubbing; the Tavily URL is built from the key in code. | Redacting by the substring "token" would hide the token usage SPEC requires, and the Tavily MCP URL carries the key. |
| 11 | Dependencies: light shared deps; separate `api`/`docs`/`frontend`/`dev` groups; CI uses `--all-groups`. | Groups are added on top of the project dependencies; otherwise the docs-mcp image would include crewai, and CI would miss the docs imports. |
| 12 | Schema additions: `EvidenceSet`, `FindingSet`, `Report.unanswered_sub_question_ids`, API request/result models. | CrewAI `output_pydantic` needs a model rather than a list; SPEC error handling needs a way to record unanswered sub-questions. |
| 13 | API keys are optional at import, but the API lifespan and the CLI fail fast at startup. | Meets SPEC's "clear startup error" while keeping `/health` and CI working without secrets. |
| 14 | HF Space: pre-built Qdrant collection and model baked into the image; daily run limit + example reports. | No persistent disk on the free tier; CPU ingest is slow; a public demo without auth would use up the shared keys. |
| 15 | Filesystem MCP: pinned version installed at build time; reads curated notes in `data/notes/`. | Avoids unpinned runtime `npx` downloads and gives the server a real, testable role. |
| 16 | Born-digital PDFs only; NFKC normalisation and a presentation-form check for Arabic. | Scanned PDFs would need OCR (out of scope); some PDFs extract Arabic as presentation forms. |
| 17 | Python 3.12 (`>=3.12,<3.13`). | SPEC says 3.11+; 3.12 is a deliberate, current choice. |
| 18 | SPEC's "sequential process with a manager agent" is read as: sequential now, hierarchical (manager) only as the Phase 6 config. | Only the hierarchical process uses a manager agent. |
| 19 | Logger module is `app/log.py`. | Avoids having the same name as the stdlib `logging` module. |

## 2026-11-13 — Phase 1 dependency resolution

| # | Decision | Why |
|---|---|---|
| 20 | Use the latest crewai/crewai-tools (`>=1.15.41`) and accept the caps they impose: `mcp>=1.30.0,<2` and pydantic `<2.13` (resolved: mcp 1.30.0, pydantic 2.12.5). docs-mcp is written against the mcp 1.x API (`mcp.server.fastmcp`). | With `mcp>=2.3.0` and `pydantic>=2.14.3`, uv silently backtracked crewai to 1.6.1, which is 9 minor versions behind, doesn't match the current docs, and may not be tested against mcp 2.x. One lockfile means all groups share the same mcp version. Revisit when crewai supports mcp 2.x. |
| 21 | Shared dependencies get loose minimums (`pydantic>=2.11.9`, `pydantic-settings>=2.10`); litellm has no minimum, so crewai's range decides. | `uv add` writes the newest release as the minimum, which caused the conflicts above. The exact versions live in `uv.lock`. |
| 22 | Build backend: `uv_build` with a flat layout (`module-root = ""`, modules `app` and `mcp_servers`). | Needed for the `researchcrew` console script. It comes with uv, so no extra tool is added. |
| 23 | HTTP metrics are labelled by route **template** + status; unmatched paths are labelled `unmatched`. | Raw paths (e.g. `/research/abc123`) would create unbounded Prometheus label cardinality. |
| 24 | Compose overrides `QDRANT_URL=http://qdrant:6333` for the api container; host ports are configurable (`API_HOST_PORT`, `QDRANT_HOST_PORT`, defaults 8000/6333). Qdrant pinned to `v1.20.1` (matches qdrant-client 1.20). | `.env` holds the localhost URL for local runs. On the dev machine, 6333 is already used by another project's Qdrant. |
| 25 | Docker: builder and runtime both use `python:3.12-slim`; uv is copied from `ghcr.io/astral-sh/uv:0.12.19`; the project is installed `--no-editable`; runtime user `app` (uid 10001). | The same base image means the venv's Python path matches; only `.venv` is copied to the runtime image. |
| 26 | The log handler writes to the *current* `sys.stdout`; uvicorn's own access logs stay in uvicorn's plain format for now. | Lets tests and redirection capture logs. Routing uvicorn logs through the JSON formatter is deferred to Phase 4. |

## 2026-11-13 — Phase 2 start

| # | Decision | Why |
|---|---|---|
| 27 | Sample-data topics: **public health** (WHO), **AI ethics** (UNESCO) and **renewable energy** (IRENA), each with English and Arabic PDFs. | All three publishers release born-digital PDFs with official Arabic editions under licences that allow reuse with attribution (WHO CC BY-NC-SA 3.0 IGO, UNESCO CC BY-SA 3.0 IGO, IRENA attribution terms). The exact files are listed in `data/SOURCES.md` after you approve them. |
| 28 | mypy `untyped_calls_exclude = ["pymupdf"]` (strict mode otherwise unchanged). | PyMuPDF's `Document` constructor has no type hints. This allows calls into that one package without `type: ignore` comments or loosening checks on our own code. |
| 29 | `env_ignore_empty=True` in Settings: `VAR=` in `.env` means unset. | `.env.example` leaves optional values (e.g. `MODEL_CACHE_DIR`) empty; an empty `GROQ_API_KEY=` also counts as missing for `require()`. |

## Pinned versions
Resolved 2026-11-13 with uv 0.12.19 on Python 3.12.3. 204 packages are locked in `uv.lock`; this table lists only the direct dependencies.

| Group | Package | Version |
|---|---|---|
| shared | pydantic | 2.12.5 (crewai caps it at <2.13) |
| shared | pydantic-settings | 2.16.3 |
| api | crewai / crewai-tools[mcp] | 1.15.41 |
| api, docs | mcp | 1.30.0 (capped at <2, see #20) |
| api | litellm | 1.109.1 |
| api | fastapi | 0.162.6 |
| api | uvicorn[standard] | 0.54.0 |
| api, frontend | httpx | 0.28.1 |
| api, docs | qdrant-client | 1.20.0 |
| api | prometheus-client | 0.26.0 |
| api | tenacity | 9.2.1 |
| api | langfuse | 5.2.0 |
| api | openinference-instrumentation-crewai | 1.1.27 |
| api | openinference-instrumentation-litellm | 0.1.58 |
| docs | torch | 2.15.0+cpu (from the pytorch-cpu index) |
| docs | sentence-transformers | 6.3.0 |
| docs | pymupdf | 2.1 |
| frontend | streamlit | 1.67.0 |
| dev | pytest / pytest-asyncio | 9.2.0 / 1.5.0 |
| dev | ruff / mypy | 0.17.5 / 2.4.1 |

## Measurements
_Filled in during Phases 1, 2b, 3a and 3b: image sizes, startup times, tokens and cost per run._

| Date | What | Value |
|---|---|---|
| 2026-11-13 | api image (`researchcrew-api:dev`, `api` group, no torch) | 1.47 GB |
| 2026-11-13 | Local `.venv` (all groups incl. CPU torch) | 2.4 GB |
| 2026-11-13 | api container start → healthy | ~10 s |
| 2026-11-13 | Test suite (55 tests) | ~0.3 s |
