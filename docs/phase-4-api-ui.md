# Phase 4 — FastAPI + SSE + Streamlit frontend

**Status:** done (2026-11-16), waiting for review. [Back to master plan](PLAN.md)

## Goal
Expose the crew through an async job API with live progress, and add a single-page Streamlit UI.

## Design (DECISIONS #85–89)
```
Streamlit ──POST /research──▶ FastAPI ──submit──▶ JobRunner (1 worker thread)
    │                            │                    │ run_research(emit=...)
    │◀─GET /research/{id}/events─┤                    ▼
    │   (SSE, polls SQLite)      └──── SQLite: jobs + events ◀── writes
    └──GET /research/{id}──────────────▶ result JSON
```
- **SQLite (stdlib `sqlite3`), two tables:** `jobs` (status, question, depth, timestamps,
  result JSON, error) and `events` (an autoincrement `seq` per event, the `ProgressEvent` JSON).
  The worker thread writes, the SSE endpoint reads rows with `seq > last_seen` every 0.5 s.
  No thread-to-asyncio queue, and a client can reconnect (`Last-Event-ID` = last `seq`).
- **One job at a time** (`MAX_CONCURRENT_JOBS=1`): Groq's 8K tokens/min is shared, and the
  token pacer and retry patch are process-wide. Extra jobs wait as `queued`.
- **Result first, then the final event:** the runner holds back `job_completed`/`job_failed`
  until the result is saved, so a client that reacts to that event always finds the result.
- **Timeout:** a job still `running` after `RUN_TIMEOUT_S + JOB_TIMEOUT_GRACE_S` is marked
  `failed` when anyone reads it (GET or SSE); a late result from the thread is then ignored
  (Python threads can't be killed; the run's own guard already stops tools at the deadline).
- **Restart:** jobs left `queued`/`running` by a previous process are marked `failed` at startup.
- **Friendly errors:** known provider errors (daily/minute rate limit, rejected key, timeout)
  become one readable sentence; the full error stays in the server log.
- **Report rendering:** the API also returns the report as Markdown (no HTML wrapper). The
  frontend shows it with Streamlit's Markdown (raw HTML stays escaped, so model or web text
  can't inject HTML) inside a keyed container whose CSS sets `direction: rtl` for Arabic.
- FastAPI's built-in SSE (`fastapi.sse.EventSourceResponse`, keep-alive ping every 15 s):
  no extra library.

## Endpoints
- `POST /research {question, depth}` → `202 {job_id}`.
- `GET /research/{id}` → status, question, depth, report, report_markdown, citations, token
  usage, cost, latency, error. Unknown id → 404.
- `GET /research/{id}/events` → SSE: one `data:` line of `ProgressEvent` JSON per event,
  `id:` = event seq; the stream ends after `job_completed`/`job_failed`.
- `/health`, `/metrics` as before. Startup fails naming a missing `GROQ_API_KEY`/`TAVILY_API_KEY`.

## Steps (one small group of files each)
1. Config (`JOBS_DB_PATH`, `MAX_CONCURRENT_JOBS`, `SSE_POLL_INTERVAL_S`, `JOB_TIMEOUT_GRACE_S`)
   + `app/api/jobs.py` (JobStore) + tests.
2. `app/api/runner.py` (JobRunner) + friendly errors + quieter third-party logs + tests.
3. `app/api/routes.py` + `app/api/main.py` (app factory, lifespan) + endpoint/SSE tests.
4. `frontend/client.py` (HTTP + SSE parsing, tested) + `frontend/streamlit_app.py` (Streamlit page).
5. `docker/frontend.Dockerfile`, compose service, jobs volume, Makefile, `.env.example`,
   CLAUDE.md commands; then a real end-to-end run through the UI.

## Tests
- JobStore: create/get, status transitions, finish ignored after timeout, events after a seq,
  restart cleanup.
- Runner: success, failure, held-back final event, friendly error texts.
- Endpoints: POST/GET, unknown id → 404, validation error → 422, SSE format and end, timeout →
  `failed`, reconnect with `Last-Event-ID`. The crew is always faked.
- Frontend client: SSE line parsing.

## Definition of done
POST/GET endpoints work, and the frontend shows live SSE progress and the report.
