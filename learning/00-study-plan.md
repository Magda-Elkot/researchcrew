# 0. Study plan: Phases 1, 2 and 2b (tools + logic)

Follow the sessions in order. Each session has: **read** (our simple notes) → **code** (where the
logic lives) → **try** (small hands-on commands) → **official docs** (to go deeper) → **check yourself**.

Run every command from the project folder:
`cd /media/magda-elkot/Data/downloads/Doc/USS/researchcrew/researchcrew`

| Session | Topic | Time |
|---|---|---|
| 1 | The big picture | 30 min |
| 2 | Phase 1: tools (uv, ruff, mypy, pytest, Make) | 1 h |
| 3 | Phase 1: logic (config, logging, schemas, API) | 1.5 h |
| 4 | Phase 1: Docker + CI | 1 h |
| 5 | Phase 2: from PDF to text (extraction, NFKC, Arabic) | 1.5 h |
| 6 | Phase 2: from text to search (chunks, embeddings, Qdrant, ingest) | 1.5 h |
| 7 | Phase 2: the MCP server | 1 h |
| 8 | Phase 2b: one container, hosting, free demo | 45 min |
| 9 | Review: self-check + explain it out loud | 1 h |

---

## Session 1: the big picture (30 min)

- **Read:** [01-big-picture.md](01-big-picture.md), then skim `SPEC.md` (what we build) and the
  first table in `DECISIONS.md` (why).
- **Goal:** explain in 2 minutes what ResearchCrew does, what the 5 agents do, and what MCP is.

---

## Session 2: Phase 1 tools (1 h)

- **Read:** [02-phase-1-foundation.md](02-phase-1-foundation.md) sections 2.1–2.4, 2.10, 2.11.

| Tool | What it does | Where in the project | Official docs |
|---|---|---|---|
| **uv** | Installs packages, lockfile, runs commands | `pyproject.toml`, `uv.lock` | https://docs.astral.sh/uv/ |
| **ruff** | Lint + format | `[tool.ruff]` in `pyproject.toml` | https://docs.astral.sh/ruff/ |
| **mypy** | Type checking | `[tool.mypy]` in `pyproject.toml` | https://mypy.readthedocs.io/ |
| **pytest** | Tests | `tests/`, `[tool.pytest.ini_options]` | https://docs.pytest.org/ |
| **Make** | Shortcuts | `Makefile` | (run `make` targets, read the file) |

- **Try:**
  ```bash
  uv tree --depth 1                 # what we depend on, per group
  uv tree --depth 1 --outdated      # see the crewai/mcp/pydantic version caps (DECISIONS #20)
  make check                        # everything CI runs
  uv run pytest tests/test_schemas.py -v
  ```
- **Check yourself:** what's the difference between `pyproject.toml` and `uv.lock`? Why did uv
  install an old crewai, and how did we notice?

---

## Session 3: Phase 1 logic (1.5 h)

- **Read:** [02-phase-1-foundation.md](02-phase-1-foundation.md) sections 2.5–2.8.

| Logic | Code file | Read these parts first |
|---|---|---|
| Settings from env vars | `app/config.py` | `Settings`, `get_settings()`, `require()` |
| JSON logs + hiding secrets | `app/log.py` | `_SENSITIVE_KEY`, `scrub()`, `redact()`, `JsonFormatter` |
| Data contracts | `app/schemas.py` | `ResearchPlan` (3–6 sub-questions), `ResearchRequest`, `JobResult` |
| API | `app/api/main.py` | `lifespan`, `metrics_middleware`, `_route_label`, `/health`, `/metrics` |
| Tests that explain the rules | `tests/test_config.py`, `tests/test_logging.py`, `tests/test_schemas.py`, `tests/test_api_health.py` | read the test **names**: they describe the behaviour |

- **Try:**
  ```bash
  # 1. A secret is never printed (SecretStr):
  GROQ_API_KEY=gsk-demo uv run python -c "from app.config import get_settings; print(get_settings().groq_api_key)"
  # 2. require() names the missing variable. Your .env has a PLACEHOLDER key, so this prints
  #    nothing (it passes!). Run it from a folder without .env to see the error:
  uv run python -c "from app.config import require; require('GROQ_API_KEY')"
  (cd /tmp && uv run --project "$OLDPWD" python -c "from app.config import require; require('GROQ_API_KEY')")
  #    → ConfigError: Missing required environment variable: GROQ_API_KEY
  #    (Phase 3 will treat placeholder values like "your-...-here" as missing too.)
  # 3. Pydantic rejects a plan with only 2 sub-questions:
  uv run python -c "
  from app.schemas import ResearchPlan
  ResearchPlan.model_validate({'question':'Q','language':'en','sub_questions':[{'id':'1','text':'a','rationale':''},{'id':'2','text':'b','rationale':''}]})"
  # 4. Logs hide api keys and tokens but keep token counts:
  uv run python -c "
  from app.log import get_logger
  get_logger('demo').info('call', extra={'groq_api_key':'gsk-x','hf_token':'hf_x','prompt_tokens':120})"
  ```
- **Official docs:** Pydantic https://docs.pydantic.dev/ · pydantic-settings
  https://docs.pydantic.dev/latest/concepts/pydantic_settings/ · FastAPI https://fastapi.tiangolo.com/
  (read "Lifespan Events" and "Middleware") · Prometheus client https://prometheus.github.io/client_python/
- **Check yourself:** questions 1–7 in [06-self-check.md](06-self-check.md).

---

## Session 4: Phase 1 Docker + CI (1 h)

- **Read:** [02-phase-1-foundation.md](02-phase-1-foundation.md) sections 2.9 and 2.12.

| Logic | File |
|---|---|
| Two-stage api image, non-root, healthcheck | `docker/api.Dockerfile` |
| api + docs-mcp + Qdrant together, ports on 127.0.0.1 only | `docker-compose.yml` |
| Files Docker must not copy | `.dockerignore` |
| Automatic checks on every push | `.github/workflows/ci.yml` |

- **Try:**
  ```bash
  make up                       # build + start
  docker compose ps             # all "healthy"
  curl localhost:8000/health
  curl -s localhost:8000/metrics | grep http_requests_total
  docker compose logs api --tail 5
  make down
  ```
  On GitHub: your repo → **Actions** tab → open a run → see the `lint-test` and `docker` jobs.
- **Official docs:** multi-stage builds https://docs.docker.com/build/building/multi-stage/ ·
  Compose https://docs.docker.com/compose/ · GitHub Actions https://docs.github.com/actions
- **Check yourself:** why copy `uv.lock` before the code in a Dockerfile? Why are the ports bound to
  `127.0.0.1` (DECISIONS #39)?

---

## Session 5: Phase 2, from PDF to clean text (1.5 h)

- **Read:** [03-phase-2-docs-mcp.md](03-phase-2-docs-mcp.md) sections 3.1–3.8 (NFKC and the Arabic
  problems are the most important).
- **Code:** `mcp_servers/docs_mcp/extract.py`, read in this order:
  `extract_pdf()` → `arabic_quality()` → `fix_lam_alef()` → `normalize()` → `clean_title()`.
  Tests: `tests/docs_mcp/test_extract.py`.
- **Try:**
  ```bash
  # NFKC in action (shape characters → real letters):
  uv run python -c "import unicodedata as u; s='ﺍﻟﺴﺤﺔ'; print([hex(ord(c)) for c in s], '->', [hex(ord(c)) for c in u.normalize('NFKC', s)])"
  # Extract a real Arabic PDF and see its quality numbers:
  uv run python -c "
  from pathlib import Path; from mcp_servers.docs_mcp.extract import extract_pdf
  d = extract_pdf(Path('data/pdfs/who-emro-annual-report-2024-2025-ar.pdf'))
  print(d.language, d.arabic, 'lam-alef fixes:', d.lam_alef_fixes); print(d.pages[0].text[:200])"
  ```
- **Official docs:** PyMuPDF https://pymupdf.readthedocs.io/ · Unicode normalization (NFC/NFKC)
  https://unicode.org/reports/tr15/
- **Check yourself:** questions 9–13 and 16 in [06-self-check.md](06-self-check.md).

---

## Session 6: Phase 2, from text to search (1.5 h)

- **Read:** [03-phase-2-docs-mcp.md](03-phase-2-docs-mcp.md) sections 3.9–3.12.

| Step | Code file | Key idea |
|---|---|---|
| Chunking | `mcp_servers/docs_mcp/chunking.py` → `chunk_pages()` | 800 **tokens**, 100 overlap, page range per chunk |
| Embeddings | `mcp_servers/docs_mcp/embeddings.py` → `SentenceTransformerEmbedder` | bge-m3, 1024 numbers, normalised, lazy load, thread cap |
| Storage + search | `mcp_servers/docs_mcp/store.py` → `DocStore` | point id = uuid5(doc_id:chunk), chunk 0 = document record, `search()` |
| Pipeline | `mcp_servers/docs_mcp/ingest.py` → `ingest_folder()` | fingerprint → skip unchanged, `--prune`, bad PDFs skipped |
| Test helpers | `tests/docs_mcp/fakes.py` | whitespace tokenizer + fake embedder: tests without the model |

- **Try:**
  ```bash
  docker compose up -d qdrant
  make ingest                        # all 5 "unchanged, skipped" (fingerprints)
  curl -s localhost:6335/collections/documents | python3 -m json.tool | head -20
  # Your own semantic search (English question → Arabic results too):
  uv run python -c "
  from app.config import get_settings; from mcp_servers.docs_mcp.store import DocStore
  from mcp_servers.docs_mcp.embeddings import SentenceTransformerEmbedder as E
  s=get_settings(); st=DocStore.from_settings(s); e=E.from_settings(s)
  for h in st.search(e.embed(['vaccine production'])[0], 3): print(round(h.score,3), h.doc_id, 'p.', h.page_start)"
  docker compose down
  ```
- **Official docs:** Qdrant concepts (collections, points, payload, filtering)
  https://qdrant.tech/documentation/concepts/ · sentence-transformers https://sbert.net/ ·
  bge-m3 model card https://huggingface.co/BAAI/bge-m3
- **Check yourself:** questions 14, 15, 17 in [06-self-check.md](06-self-check.md).

---

## Session 7: Phase 2, the MCP server (1 h)

- **Read:** [03-phase-2-docs-mcp.md](03-phase-2-docs-mcp.md) sections 3.13–3.18.
- **Code:** `mcp_servers/docs_mcp/server.py` → `create_server()`: the two `@mcp.tool()` functions,
  the `@mcp.resource("docs://list")`, `/health`. Tests: `tests/docs_mcp/test_server.py` (a real MCP
  client in memory).
- **Try (the best way to understand MCP):**
  ```bash
  make up                 # starts docs-mcp on :8001
  make inspect            # browser opens → transport "Streamable HTTP", URL http://localhost:8001/mcp → Connect
  ```
  In the Inspector: **Tools** → `search_documents` → try an English and an Arabic query →
  `get_document` with `start_page`/`end_page` → **Resources** → `docs://list`.
  Then `make down`.
- **Official docs:** MCP concepts (tools, resources, transports) https://modelcontextprotocol.io/ ·
  Python SDK / FastMCP https://github.com/modelcontextprotocol/python-sdk ·
  Inspector https://github.com/modelcontextprotocol/inspector
- **Check yourself:** questions 8, 18, 20 in [06-self-check.md](06-self-check.md).

---

## Session 8: Phase 2b, one container and free hosting (45 min)

- **Read:** [03b-phase-2b-hosting.md](03b-phase-2b-hosting.md), then optionally
  [07-free-live-demo-guide.md](07-free-live-demo-guide.md).
- **Code:** `deploy/demo/Dockerfile` (layer order: model **before** code), `deploy/demo/entrypoint.sh`
  (Qdrant → wait → exclude unlicensed docs → docs-mcp), `deploy/demo/prepare.sh` (snapshot),
  `deploy/demo/smoke_test.py` (MCP client + timings).
- **Try:** `make demo-run`, then in another terminal
  `uv run python deploy/demo/smoke_test.py http://localhost:7860/mcp`.
- **Official docs:** Qdrant snapshots https://qdrant.tech/documentation/concepts/snapshots/ ·
  Cloudflare quick tunnels https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/
- **Check yourself:** questions 19, 21–24 in [06-self-check.md](06-self-check.md).

---

## Session 9: review (1 h)

1. Answer **all** questions in [06-self-check.md](06-self-check.md) out loud, then open the answers.
2. Draw the pipeline from memory: PDF → extract → chunk → embed → Qdrant → MCP tool → agent.
3. Explain 3 "real-data" stories: the crewai version trap (DECISIONS #20), the broken Arabic fonts
   (#32, #47), the hosting surprise (#48–50).
4. Look up unknown words in [04-glossary.md](04-glossary.md) and commands in [05-commands.md](05-commands.md).

**Tip for reading code:** follow the data. Start where data enters (`ingest_folder`, a tool function),
then follow each function call one level down. Read the test file next to it: tests show the expected
behaviour in small examples.
