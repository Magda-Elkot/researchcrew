"""Add the self-hosted Langfuse secrets to .env (Phase 5, DECISIONS #91).

Run: `make langfuse-env` (or `uv run python scripts/langfuse_env.py [path/to/.env]`).

Langfuse's official compose file ships default passwords marked CHANGEME. This script appends
long random values for every Langfuse secret that `.env` doesn't have yet, plus the headless
init values (organisation, project, API keys, first user) and the app's own LANGFUSE_* keys,
which are the init project's keys. Existing values are never changed and no value is printed:
only the names of the variables that were added.
"""

import secrets
import sys
from collections.abc import Callable
from pathlib import Path

from app.log import get_logger

logger = get_logger(__name__)


def _hex(n_bytes: int) -> Callable[[], str]:
    return lambda: secrets.token_hex(n_bytes)


def _password() -> str:
    return secrets.token_urlsafe(24)


# name -> how to create a value (a function) or a fixed, non-secret value (a string).
DEFAULTS: dict[str, Callable[[], str] | str] = {
    # Secrets of the Langfuse services (docker-compose.yml, profile "observability").
    "LANGFUSE_NEXTAUTH_SECRET": _hex(32),
    "LANGFUSE_SALT": _hex(32),
    "LANGFUSE_ENCRYPTION_KEY": _hex(32),  # must be 64 hex characters
    "LANGFUSE_POSTGRES_PASSWORD": _hex(16),  # goes into a URL: hex needs no escaping
    "LANGFUSE_CLICKHOUSE_PASSWORD": _hex(16),
    "LANGFUSE_REDIS_AUTH": _hex(16),
    "LANGFUSE_MINIO_PASSWORD": _hex(16),
    # Headless init: created by langfuse-web at its first start.
    "LANGFUSE_INIT_ORG_ID": "researchcrew",
    "LANGFUSE_INIT_PROJECT_ID": "researchcrew",
    "LANGFUSE_INIT_PROJECT_PUBLIC_KEY": lambda: f"pk-lf-{secrets.token_hex(16)}",
    "LANGFUSE_INIT_PROJECT_SECRET_KEY": lambda: f"sk-lf-{secrets.token_hex(16)}",
    "LANGFUSE_INIT_USER_EMAIL": "admin@researchcrew.local",
    "LANGFUSE_INIT_USER_PASSWORD": _password,
}
# The app's keys are copies of the init project's keys.
APP_KEYS = {
    "LANGFUSE_PUBLIC_KEY": "LANGFUSE_INIT_PROJECT_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY": "LANGFUSE_INIT_PROJECT_SECRET_KEY",
}


def read_env(path: Path) -> dict[str, str]:
    """Non-empty `NAME=value` lines (comments and blank values are ignored)."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.strip().partition("=")
        if sep and not name.startswith("#") and value.strip():
            values[name.strip()] = value.strip()
    return values


def missing_values(existing: dict[str, str]) -> dict[str, str]:
    """New values for every Langfuse variable that `existing` lacks."""
    added: dict[str, str] = {}
    for name, make in DEFAULTS.items():
        if name not in existing:
            added[name] = make if isinstance(make, str) else make()
    merged = {**existing, **added}
    for app_name, init_name in APP_KEYS.items():
        if app_name not in existing:
            added[app_name] = merged[init_name]
    return added


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    path = Path(args[0] if args else ".env")
    added = missing_values(read_env(path))
    if not added:
        logger.info("langfuse secrets already in place", extra={"file": str(path)})
        return 0
    lines = ["", "# --- Self-hosted Langfuse (added by scripts/langfuse_env.py) ---"]
    lines += [f"{name}={value}" for name, value in added.items()]
    with path.open("a", encoding="utf-8") as env_file:
        env_file.write("\n".join(lines) + "\n")
    path.chmod(0o600)  # secrets: readable by you only
    logger.info("langfuse secrets added", extra={"file": str(path), "names": list(added)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
