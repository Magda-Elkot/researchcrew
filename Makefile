# Shortcuts for common tasks. Run `make <target>`.
.PHONY: install lint format typecheck test check up down eval

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

eval:  ## Placeholder until Phase 6
	@echo "make eval is available in Phase 6"
	@exit 1
