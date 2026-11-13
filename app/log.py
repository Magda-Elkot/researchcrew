"""Structured JSON logging with secret redaction (stdlib only).

Named `log.py`, not `logging.py`, so it never shadows the standard library module.
Redaction has two layers:
1. Field names that look like secrets (e.g. `groq_api_key`, `password`) are replaced.
   Token *counts* such as `prompt_tokens` are deliberately kept (SPEC needs them).
2. Every string is scrubbed of loaded secret values and of secret URL query params.
"""

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

from app.config import get_settings, secret_values

REDACTED = "***"

_SENSITIVE_KEY = re.compile(
    r"^(api_key|.*_api_key|.*_secret_key|password|authorization)$", re.IGNORECASE
)
# Query params like ?apiKey=, &tavilyApiKey=, ?access_token=, ?key=
_URL_SECRET_PARAM = re.compile(
    r"([?&](?:[\w.-]*?(?:api[_-]?key|token|secret|password)|key)=)[^&\s#\"']+",
    re.IGNORECASE,
)

# Attributes every LogRecord has; anything else came from `extra=`.
_STANDARD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message",
    "asctime",
    "taskName",
}

_configured = False


def scrub(text: str) -> str:
    """Remove loaded secret values and secret URL query parameters from a string."""
    for secret in secret_values():
        text = text.replace(secret, REDACTED)
    return _URL_SECRET_PARAM.sub(rf"\1{REDACTED}", text)


def redact(value: Any, key: str | None = None) -> Any:
    """Recursively redact sensitive keys and scrub string values."""
    if key is not None and _SENSITIVE_KEY.match(key):
        return REDACTED
    if isinstance(value, dict):
        return {k: redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return scrub(value)
    return value


class JsonFormatter(logging.Formatter):
    """Format each record as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(redact(payload), default=str, ensure_ascii=False)


class _StdoutHandler(logging.Handler):
    """Writes to the *current* sys.stdout (so redirection/capture keeps working)."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            sys.stdout.write(self.format(record) + "\n")
            sys.stdout.flush()
        except Exception:
            self.handleError(record)


def _configure() -> None:
    global _configured
    if _configured:
        return
    handler = _StdoutHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(get_settings().log_level.upper())
    # Libraries that log every HTTP request at INFO: keep only their warnings.
    for noisy in ("httpx", "httpcore", "huggingface_hub", "sentence_transformers", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a logger that writes structured JSON to stdout."""
    _configure()
    return logging.getLogger(name)
