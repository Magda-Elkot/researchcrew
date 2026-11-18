# Progress

## Current phase
**5 of 7 phases done (1–5, all committed, CI green). Phase 6 planned (docs/phase-6-evals.md); waiting for a Gemini key.**

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

- 2026-11-13: Phase 2b local part (DECISIONS #43–46): single-container Space image (docs-mcp + Qdrant + bge-m3 + snapshot) passes every HF free-tier limit locally: 4.13 GB, cold start 9.1 s, RAM 1.15 GB, search median 103 ms on 2 CPUs, uid 1000. Your ONNX bge-m3 export was tested and not adopted (slower, different vectors). Review fixes: `*_token`/`*_secret` log redaction, entrypoint readiness check, model layer before code. 126 tests passing.

## Definition of done: Phase 2
- [x] `ingest` indexes data/pdfs (5 PDFs, 230 chunks; the broken 2019 WHO PDF is rejected by design).
- [x] Every docs-mcp tool (and the resource) has passing unit tests.
- [x] The server works with the MCP Inspector.

- 2026-11-15: hardware checked (i7-13650HX, 31 GB RAM, RTX 3050 Laptop 6 GB, no NVIDIA driver yet). An on-prem LLM plan (Ollama, vLLM benchmark, SearXNG; DECISIONS #52–59) was drafted, then reverted the same day because the NVIDIA driver couldn't be installed (see Known issues). Kept: self-hosted Langfuse, all tracing in Phase 5 (DECISIONS #60).

- 2026-11-15: Phase 3a done (DECISIONS #61–71).
  - Config: Tavily key, MCP client settings, tool-result size limits; `require()` rejects `.env.example` placeholders.
  - `app/tools/mcp.py`: server specs, `open_mcp_tools()` (skips a failing server, closes all on exit), `CompactTool` (required args only, hidden fixed args, shortened results). 154 tests passing; ruff + mypy clean.
  - `scripts/spike_mcp.py bench`: adapter vs native (docs search 75 vs 202 ms; filesystem 2 vs 827 ms) → MCPServerAdapter, connections per job.
  - `scripts/spike_mcp.py agent`: Llama 3.3 70B is gone from Groq → gpt-oss-120b. Found and fixed: strict tool schemas, null optional args, oversized results. Found for 3b: the model loops on tools without a budget and invents evidence when tools don't deliver.

- 2026-11-15: Phase 3b done (DECISIONS #72–82).
  - Plain-Python pipeline `run_research()`: Planner crew → main crew (one research task per sub-question with its own guarded tools → Analyst → Writer → Reviewer) → citation check → at most one revision.
  - `guarded.py` (budgets, deadline, retry once, events, recording), `evidence.py` (verbatim check incl. "…" quotes; labelled-text answers), `report.py` (citation check, Markdown with RTL), `language.py`, `usage.py`, `pacing.py` (token pacing + capped retry waits), `limits.py`.
  - CLI: `uv run researchcrew "question" [--depth] [--process]` → `outputs/<id>.json` + `.md`; exit codes 0/1/2.
  - api image: Node 24 + pinned filesystem MCP server (1.61 GB), verified in the container.
  - Real English run: completed, 7 evidence items, all sub-questions answered, 52K tokens, $0.012.
  - 255 tests passing; ruff + mypy strict clean.
- 2026-11-18: Phase 5 done (DECISIONS #90–97).
  - Self-hosted Langfuse 4.80.0 in compose profile `observability` (web, worker, Postgres, ClickHouse, Redis, MinIO; pinned; only the UI published on 127.0.0.1:3000); `make langfuse-env` (random secrets + headless-init keys into `.env`), `make langfuse-up` / `langfuse-down`.
  - `app/observability.py`: tracing on only with Langfuse keys; CrewAI + LiteLLM instrumented; one root span per run with tags depth/model/process/version and the job id; `trace_id` on `RunResult`, in `GET /research/{id}` (+ `trace_url`) and on every log line inside a run.
  - uvicorn logs as JSON. Bug fixed: Docker images installed a stale build of our package after code-only changes (#96).
  - Real traced run: 45 observations (3 crews, 8 agent tasks, 18 LLM calls, 15 tool spans), tokens identical to ours, cost within 0.5 % (Langfuse knows Groq's cached-token price). The API container's spans reach Langfuse at `langfuse-web:3000` and are stored (re-checked after freeing disk space; the first API-run trace was lost to the full disk).
- 2026-11-16: Phase 4 done (DECISIONS #85–89).
  - `app/api/jobs.py`: SQLite job + event store (WAL, conditional status updates, final event saved with the result, timeout on read, restart cleanup).
  - `app/api/runner.py`: one job at a time in a worker thread; later jobs `queued`.
  - `app/api/routes.py`: `POST /research` (202), `GET /research/{id}` (+ `report_markdown`), `GET /research/{id}/events` (FastAPI built-in SSE, `Last-Event-ID` resume). Startup requires GROQ/TAVILY keys.
  - `app/agents/errors.py`: readable provider errors; LiteLLM/MCP INFO logs and CrewAI's checkpoint warning silenced.
  - `frontend/`: `client.py` (SSE parsing, reconnect) + `streamlit_app.py` (live feed, metrics, report, RTL via CSS, Markdown download).
  - Docker: frontend image (591 MB, non-root, healthcheck), compose service on 127.0.0.1:8501, `jobs_db` volume; CI builds it; `make api`, `make frontend`.
  - Real run through the API: 21 live SSE events, completed, 6 citations, 45.8K tokens, $0.0095, 340 s; the page rendered it (AppTest against the live API). Whole compose stack healthy.
  - Bugs found by the checks and fixed: the SSE parser waited for the whole stream; `frontend/app.py` shadowed the `app` package under Streamlit; local Streamlit listened on all interfaces.
  - 303 tests passing; ruff + mypy strict (now incl. `frontend`) clean.
- 2026-11-16: Phase 3 Arabic exit check (DECISIONS #84): completed on gpt-oss-120b; Arabic RTL report with citations, cross-lingual search into an English PDF, an honest "no evidence" for sq1; 53K tokens, $0.011, 428 s.

## Next
- **You:** create a Gemini API key (https://aistudio.google.com/apikey) and add `GEMINI_API_KEY` to `.env`; tell me the free-tier limits AI Studio shows for the Flash models.
- Phase 6 (plan: `docs/phase-6-evals.md`): judge + metrics + resumable runner, a 2-question pilot (sequential vs hierarchical), the 25-question dataset, then `make eval` once a day (~13–16 days).
- Optional: take the Langfuse trace screenshot for the README (login: `LANGFUSE_INIT_USER_EMAIL` / `LANGFUSE_INIT_USER_PASSWORD` in `.env`); add sample PDFs (`data/SOURCES.md`); test the demo container over a Cloudflare quick tunnel (learning/07-free-live-demo-guide.md).

## Known issues / risks
- Langfuse needs free disk space: when the disk was nearly full (2026-11-18, a container from another project), its MinIO refused writes and an API-run trace was lost (HTTP 500 on span upload). Fixed by freeing space; re-checked from the api container.
- Langfuse needs ~3–4 GB RAM while running (6 containers); start it only when you want traces (`make langfuse-up`). Without it, runs work the same; with keys set but Langfuse stopped, the API logs a warning and spans are dropped.
- Our cost numbers ignore Groq's cached-input discount (~0.5 % high); Langfuse shows the exact cost.
- CrewAI calls `load_dotenv()` when imported (`crewai/llm.py`): python-dotenv searches upward from CrewAI's own folder, so the project `.env` is loaded into the environment even when a command runs from another folder. Harmless (our settings read the same `.env`), but a "missing key" test only works without that file (found in the 2026-11-16 review).
- When the filesystem MCP server can't start (e.g. no `data/notes` in the working folder), it is skipped correctly, but only after the full `MCP_CONNECT_TIMEOUT` (30 s).
- gpt-oss on Groq sometimes answers a structured step (Writer `Report`) by calling a non-existent tool (`report`), like the `json` case (#75); CrewAI recovered in the run, but it costs one extra call.
- Jobs run one at a time: a second question waits until the first is done (~5–10 min each on the free tier).
- `make up` publishes the UI on 8501 and the API on 8000; if you run `make api`/`make frontend` locally at the same time, set `API_HOST_PORT`/`FRONTEND_HOST_PORT`/`DOCS_MCP_HOST_PORT` to other ports.
- gpt-oss-20b (tested as a second model, own 200K/day): Arabic path worked in one run (Arabic plan and queries, English chunks retrieved, first real web search), but the next run failed at the Planner: "Tool choice is required, but model did not call a tool" (structured output). gpt-oss-120b never failed there. If 20b becomes the Phase 6 comparison model, structured steps need one retry.
- **Groq free tier: 200K tokens/day = ~4 quick reports/day.** The daily window is rolling; spikes and diagnostics count too. Phase 6 needs a plan (spread over days, or a second model with its own quota).
- With 2 tool calls per sub-question (quick), the Researcher uses search_documents + get_document, so when the library has nothing it never reaches web search (Arabic run, sq1). Candidate fix in Phase 4/6: tell it to try the web when the search finds nothing, or drop get_document in quick mode.
- The References list repeats one document once per evidence item (no merging, no page numbers).
- docs-mcp run in a terminal must stay in the foreground: Ctrl+Z suspends it, and it keeps port 8001 but never answers (curl hangs). Use `fg` to resume, or Ctrl+C to stop.
- Reports cite only the PDF library so far: with "library first" the Researcher never needed web search in the real runs, and all citations came from one IRENA report. Citations show the doc_id, not page numbers yet.
- The Researcher sometimes returns an evidence block with an empty snippet (dropped); the raw answer is now logged to find the cause.
- `capped_retry_waits` patches a CrewAI internal (`crewai.llms.retry.get_retry_delay_seconds`); a test fails if CrewAI changes it.
- The filesystem MCP server needs Node >= 24 (the image has it); this machine has Node 22, which works through npx but is unsupported.
- Groq free tier for gpt-oss-120b: 8,000 tokens/min and 1,000 requests; one request may not exceed 8K tokens. A 5-agent run will be slow (minutes), and the eval will take many days (measured in Phase 3b).
- gpt-oss-120b keeps calling tools unless a budget stops it, and invents citations when tools return nothing useful (DECISIONS #69–70).
- The top search hits for "renewable energy jobs GCC" contain no jobs data: check eval questions against what the PDFs really cover.
- Hierarchical mode may be unreliable; the fallback is a two-model comparison.
- Self-hosted Langfuse needs ~4–6 GB RAM (6 containers); it lives in a compose profile and starts only when needed.
- `apt update` fails on `https://archive.ubuntu.com` with "certificate issuer unknown" (clock, certificate store or HTTPS interception on the network; not investigated, your choice). Effects: apt packages can't be installed or updated (the NVIDIA driver install failed), and the same network may break Docker image pulls, e.g. for Langfuse. Bruno's apt repo also refuses connections.
- HF Space: the docs-mcp spike fits locally; not yet verified on a real Space. The api + agents (Phase 3+) will add more RAM/CPU load.
- This machine's `docker build` is the legacy builder (no buildx plugin), so no BuildKit cache mounts outside compose.
- mcp is pinned below 2 because of crewai; revisit when crewai supports mcp 2.x.
- Starlette warns that `TestClient` with `httpx` is deprecated in favour of `httpx2`. Harmless for now; switching would add a library, so it needs approval.
- On this machine port 6333 is used by another Qdrant (`de-rs`), so the local `.env` sets `QDRANT_HOST_PORT=6335` and `QDRANT_URL=http://localhost:6335`.
- Sample data is thinner than planned (5 PDFs, not 10–15; AI ethics only a 2-page flyer; no Arabic energy document), because several publishers block scripted downloads.
- The UNESCO flyer has no licence statement, so it's git-ignored until confirmed.
- The WHO PDFs have no title metadata, so their title is the file name.
- Arabic numbers and punctuation can appear out of place inside RTL lines (PDF bidi order); search still works.
- The lam-alef fix covers only the safe "ال + alef-type" case. The WHO Arabic PDF also has mid-word reversed lam-alef (e.g. السالمة for السلامة); some Arabic queries lose recall ("patient safety" not in top 10). DECISIONS #47.
- VS Code shows "pydantic is not installed": select the project interpreter `.venv/bin/python`.
