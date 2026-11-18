"""Structured JSON logging with secret redaction (stdlib only).

Named `log.py`, not `logging.py`, so it never shadows the standard library module.
Redaction has two layers:
1. Field names that look like secrets (e.g. `groq_api_key`, `password`) are replaced.
   Token *counts* such as `prompt_tokens` are deliberately kept (SPEC needs them).
2. Every string is scrubbed of loaded secret values and of secret URL query params.

`extra=` keys that clash with LogRecord's own attributes (`args`, `process`, `name`, ...) are
renamed with a trailing underscore instead of crashing the log call (it happened three times).
"""

import json
import logging
import re
import sys
from collections.abc import MutableMapping
from datetime import UTC, datetime
from typing import Any

from app.config import get_settings, secret_values

REDACTED = "***"

# Secret-looking field names. "token" is singular on purpose: `hf_token` / `access_token` are
# secrets, but token *counts* such as `prompt_tokens` and `total_tokens` must stay visible.
_SENSITIVE_KEY = re.compile(
    r"^(api_key|.*_api_key|.*_secret_key|(.*_)?secret|(.*_)?token|password|authorization)$",
    re.IGNORECASE,
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
    "color_message",  # uvicorn: the message again, with terminal colour codes
    "litellm_redacted",  # LiteLLM's "already scrubbed" marker on records its filter saw
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
    # LiteLLM logs two INFO lines per LLM call, also through its own plain-text handler; the MCP
    # client logs each session handshake (DECISIONS #88).
    for noisy in (
        "httpx",
        "httpcore",
        "huggingface_hub",
        "sentence_transformers",
        "urllib3",
        "LiteLLM",
        "LiteLLM Router",
        "LiteLLM Proxy",
        "mcp.client.streamable_http",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True


class SafeExtraAdapter(logging.LoggerAdapter[logging.Logger]):
    """Renames `extra` keys that LogRecord reserves (`process` -> `process_`)."""

    def process(
        self, msg: Any, kwargs: MutableMapping[str, Any]
    ) -> tuple[Any, MutableMapping[str, Any]]:
        extra = kwargs.get("extra")
        if extra:
            kwargs["extra"] = {
                (f"{key}_" if key in _STANDARD_ATTRS else key): value
                for key, value in extra.items()
            }
        return msg, kwargs


def get_logger(name: str) -> SafeExtraAdapter:
    """Return a logger that writes structured JSON to stdout."""
    _configure()
    return SafeExtraAdapter(logging.getLogger(name))
