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
| 30 | Store design: one Qdrant point per chunk (payload: doc_id, title, language, chunk_index, page range, text). Chunk 0 also holds the document record (metadata + full text) used by `get_document` and `docs://list`. Point ids are `uuid5(doc_id:chunk_index)`, and re-ingest deletes the doc's points first. | No second collection or database needed; idempotent re-ingest; `docs://list` is one filtered scroll. Search excludes the heavy payload fields. |
| 31 | Chunking counts **bge-m3 tokens** via the tokenizer's offset mapping and keeps `page_start`/`page_end` per chunk. Tokenizer and embedder are Protocols; tests use a whitespace tokenizer and a hashing fake embedder. | Correct sizes for Arabic and English alike; pages for citations; tests stay offline. |
| 32 | Arabic: fix swapped lam-alef ligatures (`ا[اأإآ]ل` → `ال[اأإآ]`, safe because two alef-type letters never follow each other), and **reject** PDFs where other letter pairs are swapped (`يف` > `في`, words ending `ىل`). | Found on the real WHO EMRO PDFs: the 2025 report needed 1,122 lam-alef fixes; the 2019 overview had `يف` 2207× vs `في` 2× and cannot be fixed safely, so it is rejected. |
| 33 | Sample data (step 8): 5 PDFs: WHO EMRO annual report 2024/2025 (EN + AR), IRENA Arab region 2016 and GCC 2023 (EN), UNESCO AI-ethics flyer (EN, local only: no licence statement). The UNESCO full Recommendation (EN/AR) and an Arabic energy report still need a manual browser download (`data/SOURCES.md`). | UNESCO, the UN Digital Library and ESCWA block scripted downloads; we don't work around bot protection. |
| 34 | `EMBEDDING_THREADS` (default 4) caps torch CPU threads. Ingest skips files whose fingerprint (SHA-256 of file + model + chunk settings) is unchanged; `--force` re-embeds. Noisy HTTP loggers are set to WARNING. | Embedding is the CPU-heavy step (bge-m3, 568M parameters, no bf16/AMX on this CPU). Re-runs become nearly free. |
| 35 | docs-mcp container: only the `docs` group; model not baked into the image but mounted at `/models`: a named volume by default, or the host HF cache via `MODEL_CACHE_HOST_DIR` + `HF_HUB_OFFLINE=1`. Compose `environment` forces `DOCS_MCP_HOST=0.0.0.0`, the in-network `QDRANT_URL` and `MODEL_CACHE_DIR`. | Keeps the image smaller and rebuilds fast; no 2.3 GB re-download on this machine. `environment` beats `env_file`, so a local `.env` can't break the container. |
| 36 | FastMCP's DNS-rebinding protection is on for `127.0.0.1` (local runs) and off for `0.0.0.0` (Docker network). No auth in v1. | Auth is a SPEC non-goal; docs-mcp only serves read-only public documents and is not exposed publicly. |
| 37 | Server tests use a real MCP client session in memory (`create_connected_server_and_client_session`), not direct function calls. | Exercises the protocol (schemas, validation, errors, resources) the way CrewAI and the Inspector will. |
| 38 | Lint/type exceptions: ruff `allowed-confusables = ["ا"]`; `# type: ignore[untyped-decorator]` on FastMCP's `custom_route`; pytest ignores Qdrant's in-memory "payload indexes have no effect" warning. | Each one is the narrowest switch for a known, intentional case. |

## 2026-11-13: Review of Phases 1–2 before push

| # | Decision | Why |
|---|---|---|
| 39 | All compose ports are published on `127.0.0.1` only. | Qdrant has no auth; with `0.0.0.0` anyone on the same network could read or delete the collection. Verified: not reachable from the LAN address. |
| 40 | Ingest fingerprint includes `PIPELINE_VERSION` (bump on extraction/chunking changes). `--prune` deletes documents whose PDF is gone. Two files mapping to the same doc_id are reported as an error, not overwritten. | Otherwise code fixes never reach already-indexed PDFs, renamed files leave duplicates in search, and `a b.pdf` / `a-b.pdf` silently overwrite each other. |
| 41 | `EMBEDDING_THREADS=0` means all cores (empty = default 4). | With `env_ignore_empty`, "leave empty for all cores" could never work. |
| 42 | **SPEC extension:** `get_document(doc_id, start_page=1, end_page=None, max_chars=12000)` returns a page range with `[page N]` markers, capped (1,000–50,000 chars), with `truncated`, `end_page` and the total `pages`. Text is stored per page on chunk 0 (`pages_text`); `PIPELINE_VERSION` bumped to 2. | The full text of the IRENA GCC report is ~358,000 characters (~90,000 tokens), far above Groq's free tier (~12,000 tokens/min). A safe default lets agents read long reports page by page, and the page markers help citations. Chosen by you in the pre-push review. |

## 2026-11-13: Phase 2b

| # | Decision | Why |
|---|---|---|
| 43 | Keep PyTorch + sentence-transformers for bge-m3; do **not** switch to the local ONNX export (`models/bge-m3-onnx`, git-ignored). | Measured on 24 real chunks, 4 threads: ONNX 2.02 s/chunk vs PyTorch 1.47 s/chunk (411 weights stored as graph inputs block ONNX Runtime optimisations), and its vectors don't match bge-m3's dense vectors (cosine 0.60–0.67 vs the stored ones; it pools differently). A correct ONNX export (CLS pooling, constant weights, optional int8) would need `optimum`: optional, Phase 7. |
| 44 | HF Space design (spike): ONE container = docs-mcp + the Qdrant binary (copied from `qdrant/qdrant:v1.20.1`, bound to 127.0.0.1) + bge-m3 baked in (downloaded at build time, pinned revision, saved as a plain folder) + a Qdrant snapshot of the indexed collection restored at every start into `/tmp`. Port 7860, uid 1000, `HF_HUB_OFFLINE=1`, `EMBEDDING_THREADS=2`. Files in `deploy/hf-space/`; `prepare.sh` assembles the Space folder (git-ignored `build/`). | Fits HF's limits: one port, uid 1000, no persistent disk (data is rebuilt from the snapshot in 2 s), no runtime ingest, no Hub access at runtime. |
| 45 | In the Space Dockerfile the model download layer comes **before** our code is copied. | Otherwise every code change re-downloads ~2.3 GB (found in the 2b review). |
| 46 | Log redaction also covers field names `*_token`, `token`, `*_secret` (singular), but not token counts (`*_tokens`). | Phase 2b introduces `HF_TOKEN`; the old rule (`*_api_key`, `*_secret_key`, password, authorization) would have logged it. |
| 47 | **Known limitation, accepted:** the WHO EMRO Arabic PDF stores *every* lam-alef ligature reversed. Only the safe case (`ا[اأإآ]ل`, 1,122 fixes) is repaired; mid-word forms stay broken (e.g. الإسالمية 11×, السالمة 6×, الالجئين 5×, المالريا 2×; correct forms 0×), because no rule can tell them from real words (سالم, لإلغاء). | Measured search impact with bge-m3: "malaria control" → broken chunk #2 (top-1 is the English report's malaria page); "refugee health" → #1; "patient safety" → not in top 10. Mostly tolerable, and the English twin covers the same content. Better fix: cleaner Arabic sources; Phase 6 evals will measure Arabic retrieval. |
| 48 | **Finding (2026-11-13):** Hugging Face no longer hosts Docker (or Gradio) Spaces on the free `cpu-basic` tier: `hf repos create … --space-sdk docker` returned **402 Payment Required: "requires a PRO subscription"**. Only static Spaces are free. Nothing was created. The demo-host decision (SPEC: "HF Spaces, Docker SDK"; non-goal: "any paid cloud service") is **pending your choice**. | Found by the Phase 2b spike, as intended: before Phase 3, not in Phase 7. The local measurements under HF-like limits (#44, Measurements) still hold for any 2-CPU / 16 GB host. |
| 49 | **Demo host = Google Cloud Run** (your choice; SPEC updated). The spike moved from `deploy/hf-space/` to host-neutral `deploy/demo/`; the entrypoint listens on `$PORT` (Cloud Run) else 7860. Deploy: `make demo-deploy` = `gcloud run deploy --source` (Cloud Build builds the Dockerfile) as a **private** service (`--no-allow-unauthenticated`), us-central1, 2 vCPU, 4 GiB, `--cpu-boost`, min 0 / max 1 instance. Verified locally the Cloud Run way (`PORT=8080`, 4 GB): start 8.5 s, RAM 1.15 GB, search median 104 ms. | Cloud Run is SPEC's named alternative: same container, scales to zero, monthly free allowance (180k vCPU-s, 360k GiB-s, 2M requests). Needs a billing account; Artifact Registry storage for the 4.13 GB image may cost a few cents/month (free amount not confirmed), so the guide sets a budget alert and includes clean-up. Max 1 instance caps cost. |
| 50 | **Supersedes #49 — free tools only, no card (your requirement).** No paid or card-backed hosting. Public demo = a **free static page** (HF static Space or GitHub Pages: example reports EN/AR, architecture, eval results, screenshots, GIF). Live system = **local** `docker compose`; for a live demo, a temporary public link with a **Cloudflare quick tunnel** (`cloudflared`, free, no account) via `make demo-tunnel`. Cloud Run target removed; the `$PORT` support in the demo entrypoint stays (harmless, host-neutral). | HF Docker Spaces need PRO (#48); Cloud Run needs a billing card and image storage may cost cents. Free no-card container hosts offer ~512 MB RAM, but bge-m3 alone needs ~1.2 GB. A quick tunnel exposes the local container publicly **only while it runs**; it has no auth, so use it only for the read-only docs-mcp/demo and stop it afterwards. |

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
| 2026-11-13 | Ingest, 5 PDFs → 230 chunks, all 14 threads (i7-13650HX, no bf16/AMX) | 5 min 0 s wall, 1303% CPU, 3.0 GB RAM |
| 2026-11-13 | Ingest, same, `EMBEDDING_THREADS=4` | 5 min 49 s wall (+16%), 391% CPU, 3.0 GB RAM |
| 2026-11-13 | Ingest again, nothing changed (fingerprints match) | 1.1 s (0.1 s of work) |
| 2026-11-13 | Embedding speed, CPU | ~1.25 s per 800-token chunk (14 threads), ~1.5 s (4 threads) |
| 2026-11-13 | bge-m3 load from local cache | 6.6 s; one search (embed + Qdrant) 60–90 ms |
| 2026-11-13 | bge-m3 on disk (HF cache, 2 snapshots) | 4.3 GB (a single snapshot is ~2.3 GB) |
| 2026-11-13 | docs-mcp image (`docs` group, CPU torch, no model) | 1.73 GB; build 2 min 33 s |
| 2026-11-13 | docs-mcp container start → healthy (model from mounted cache) | 12 s |
| 2026-11-13 | Test suite (114 tests) | ~2 s |
| 2026-11-13 | **HF Space image** (docs-mcp + Qdrant + bge-m3 + snapshot) | **4.13 GB** (model 2.29, Python env 1.61, Qdrant 0.10, snapshot 0.014) |
| 2026-11-13 | HF Space image build, local legacy builder, model download ~3 MB/s | 19.6 min (mostly the model download; deps cached) |
| 2026-11-13 | **Cold start** under HF limits (`--cpus=2 --memory=16g --user 1000`) | **9.1 s** to `/health` (Qdrant snapshot restore 2 s, model load ~2 s) |
| 2026-11-13 | **RAM** under HF limits | **1.15 GB** idle and after 5 searches (of 16 GB) |
| 2026-11-13 | **Search latency** under HF limits (MCP client, 5 EN/AR queries) | **median 103 ms, max 136 ms** |
| 2026-11-13 | ONNX export vs PyTorch, 24 chunks, 4 threads | ONNX 2.02 s/chunk vs PyTorch 1.47 s/chunk; cosine to stored vectors 0.60–0.67 |
