# Shortcuts for common tasks. Run `make <target>`.
.PHONY: install lint format typecheck test check up down ingest docs-mcp inspect eval

install:  ## Install all dependency groups into .venv
	uv sync --all-groups

lint:  ## Lint and check formatting (no changes)
	uv run ruff check .
	uv run ruff format --check .

format:  ## Auto-fix lint issues and format code
	uv run ruff check . --fix
	uv run ruff format .

typecheck:  ## Static type check
	uv run mypy app mcp_servers

test:  ## Run the test suite (no network, no keys)
	uv run pytest

check: lint typecheck test  ## Everything CI runs (except the Docker build)

up:  ## Build and start api + qdrant in the background
	docker compose up --build -d

down:  ## Stop the stack (keeps the qdrant volume)
	docker compose down

ingest:  ## Index data/pdfs into Qdrant (skips unchanged files; needs Qdrant running)
	uv run ingest data/pdfs

docs-mcp:  ## Run the docs-mcp server locally (http://127.0.0.1:8001/mcp)
	uv run docs-mcp

inspect:  ## Open the MCP Inspector web UI (connect to http://localhost:8001/mcp, transport HTTP)
	npx -y @modelcontextprotocol/inspector@2.13.0

eval:  ## Placeholder until Phase 6
	@echo "make eval is available in Phase 6"
	@exit 1
