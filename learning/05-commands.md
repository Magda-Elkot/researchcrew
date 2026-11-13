# 5. Commands we used

Run them from the project folder:
`/media/magda-elkot/Data/downloads/Doc/USS/researchcrew/researchcrew`

## Everyday

| Command | What it does |
|---|---|
| `make format` | Auto-fix lint problems and format the code. **Run before `make check`.** |
| `make check` | Lint + format check + type check + all tests (what CI runs) |
| `make test` | Only the tests |
| `uv run pytest tests/docs_mcp -v` | Only the docs-mcp tests, showing each test name (`-v` = verbose) |
| `make up` | Build and start api + Qdrant in Docker (in the background) |
| `make down` | Stop them (the Qdrant data is kept) |
| `uv run researchcrew` | The CLI (a stub until Phase 3) |
| `make ingest` / `uv run ingest data/pdfs` | Index the PDFs into Qdrant (skips unchanged files) |
| `uv run ingest data/pdfs --force` | Re-embed everything, even unchanged files |
| `make docs-mcp` / `uv run docs-mcp` | Run the MCP server locally at `http://127.0.0.1:8001/mcp` |
| `make inspect` | Open the MCP Inspector in the browser |
| `docker compose run --rm docs-mcp ingest /app/data/pdfs` | Run ingest inside the docs-mcp container |

## uv (packages)

| Command | What it does |
|---|---|
| `uv init --bare` | Create only a `pyproject.toml` |
| `uv python pin 3.12` | Write `.python-version` so everyone uses Python 3.12 |
| `uv add pkg` | Add a shared package, update the lock, install |
| `uv add --dev pkg` | Add to the `dev` group |
| `uv add --group api pkg` | Add to the `api` group |
| `uv lock` | Only work out the versions and write `uv.lock` (no install) |
| `uv lock --check` | Is `uv.lock` up to date with `pyproject.toml`? |
| `uv sync` | Make `.venv` match `uv.lock` (shared + dev) |
| `uv sync --all-groups` | Install every group |
| `uv tree --depth 1 --outdated` | Show direct packages and whether newer versions exist |
| `uv run <cmd>` | Run a command inside `.venv` |

**Version specifiers:** `>=1.15.41` = this version or newer; `>=1.30.0,<2` = at least 1.30 but below 2.

## Docker

| Command | What it does |
|---|---|
| `docker compose up --build -d` | Build the images and start the containers (`-d` = in the background) |
| `docker compose ps` | List the containers and their health |
| `docker compose logs api` | Show the api container's logs |
| `docker compose down` | Stop and remove the containers (named volumes are kept) |
| `docker image ls` | List images and their sizes |

## Checking the running app

| Command | Expected |
|---|---|
| `curl localhost:8000/health` | `{"status":"ok","version":"0.1.0"}` |
| `curl localhost:8000/metrics` | Lines like `http_requests_total{...}` |
| `curl localhost:6335/readyz` | `all shards are ready` (our Qdrant, on port 6335 on your machine) |
| `curl localhost:8001/health` | `{"status":"ok","version":"0.1.0"}` (docs-mcp) |
| `curl localhost:6335/collections/documents` | Collection info, including `points_count` (230) |

Or open the Bruno collection: `/media/magda-elkot/Backup/Documents/Collections/researchcrew/researchcrew`.

## Git (you run these yourself)

| Command | What it does |
|---|---|
| `git status` | What changed. Check that `.env` is **not** listed. |
| `git add .` | Stage all changes |
| `git commit -m "message"` | Save a snapshot locally |

## Reading errors (what we learned)

| You see | Meaning |
|---|---|
| `No solution found when resolving dependencies` | Two packages want incompatible versions. Read the "Because…" chain. |
| `I001 Import block is un-sorted` | Import order problem → `make format` |
| `E501 Line too long` | Over 100 characters → split the line |
| `[no-untyped-call]` (mypy) | Calling a library function without type hints |
| `port is already allocated` | Another program uses that port → use another host port |
| `make: *** [...] Error 1` | That make step failed, so later steps did not run |
