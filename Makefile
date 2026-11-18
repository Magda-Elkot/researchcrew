# Shortcuts for common tasks. Run `make <target>`.
.PHONY: install lint format typecheck test check up down ingest docs-mcp api frontend langfuse-env langfuse-up langfuse-down inspect demo-prepare demo-build demo-run demo-tunnel eval

install:  ## Install all dependency groups into .venv
	uv sync --all-groups

lint:  ## Lint and check formatting (no changes)
	uv run ruff check .
	uv run ruff format --check .

format:  ## Auto-fix lint issues and format code
	uv run ruff check . --fix
	uv run ruff format .

typecheck:  ## Static type check
	uv run mypy app mcp_servers frontend

test:  ## Run the test suite (no network, no keys)
	uv run pytest

check: lint typecheck test  ## Everything CI runs (except the Docker build)

up:  ## Build and start qdrant, docs-mcp, api and frontend in the background
	docker compose up --build -d

down:  ## Stop the stack (keeps the qdrant volume)
	docker compose down

ingest:  ## Index data/pdfs into Qdrant (skips unchanged files; needs Qdrant running)
	uv run ingest data/pdfs

docs-mcp:  ## Run the docs-mcp server locally (http://127.0.0.1:8001/mcp)
	uv run docs-mcp

api:  ## Run the API locally with reload off, one worker (http://127.0.0.1:8000/docs)
	uv run uvicorn app.api.main:app --host 127.0.0.1 --port 8000 --workers 1 --log-config app/api/uvicorn_log.json

frontend:  ## Run the Streamlit page locally (http://localhost:8501; needs the API)
	uv run streamlit run frontend/streamlit_app.py --server.address=127.0.0.1 --server.headless=true --browser.gatherUsageStats=false

langfuse-env:  ## Add random Langfuse secrets + API keys to .env (only the missing ones; prints names, never values)
	uv run python scripts/langfuse_env.py .env

langfuse-up:  ## Start self-hosted Langfuse (6 containers, ~2-3 min to be ready; UI http://localhost:3000)
	docker compose --profile observability up -d langfuse-web langfuse-worker

langfuse-down:  ## Stop Langfuse (keeps its data volumes)
	docker compose --profile observability stop langfuse-web langfuse-worker langfuse-postgres langfuse-clickhouse langfuse-minio langfuse-redis

inspect:  ## Open the MCP Inspector web UI (connect to http://localhost:8001/mcp, transport HTTP)
	npx -y @modelcontextprotocol/inspector@2.13.0

demo-prepare:  ## Phase 2b: assemble the demo container folder (needs indexed local Qdrant)
	deploy/demo/prepare.sh

demo-build:  ## Phase 2b: build the demo image from that folder
	docker build -t researchcrew-demo:dev deploy/demo/build/space

demo-run:  ## Phase 2b: run it like a 2-vCPU host (2 CPUs, 4 GB, uid 1000) on :7860
	docker run --rm --name researchcrew-demo --cpus=2 --memory=4g --user 1000 \
		-p 127.0.0.1:7860:7860 researchcrew-demo:dev

demo-tunnel:  ## Phase 2b: TEMPORARY free public https link to the demo on :7860 (needs cloudflared; Ctrl+C stops it)
	cloudflared tunnel --url http://localhost:7860

eval:  ## Placeholder until Phase 6
	@echo "make eval is available in Phase 6"
	@exit 1
