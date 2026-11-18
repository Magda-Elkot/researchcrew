"""Tracing of research runs in self-hosted Langfuse (Phase 5, DECISIONS #92-94).

- `setup_tracing(settings)` runs once per process (CLI start, API startup). Without Langfuse
  keys it does nothing at all: no client, no instrumentation, runs work exactly as before.
  With keys it creates the Langfuse client (which becomes the global OpenTelemetry tracer
  provider) and instruments CrewAI (a span per crew, agent task and tool call) and LiteLLM
  (a span per LLM call, with tokens).
- `traced_run(...)` opens the root span of one run. Every span CrewAI and LiteLLM create
  inside it joins the same trace, and `propagate_attributes` puts the trace name, the tags
  (depth, model, process, version) and the job id on all of them.
- A logging filter adds `trace_id` to every log line written while a run's span is active.

Langfuse's SDK and the instrumentors are imported only when tracing is on.
"""

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from opentelemetry import trace as otel_trace

from app.config import Settings
from app.log import get_logger

logger = get_logger(__name__)

TRACE_NAME = "research"
_lock = threading.Lock()
_state: dict[str, Any] = {"done": False, "client": None}


def tracing_configured(settings: Settings) -> bool:
    return bool(settings.langfuse_public_key and settings.langfuse_secret_key)


class TraceIdFilter(logging.Filter):
    """Adds the active OpenTelemetry trace id to log records (if a span is active)."""

    def filter(self, record: logging.LogRecord) -> bool:
        context = otel_trace.get_current_span().get_span_context()
        if context.is_valid and not hasattr(record, "trace_id"):
            record.trace_id = format(context.trace_id, "032x")
        return True


def setup_tracing(settings: Settings) -> bool:
    """Turn tracing on once per process; returns whether it is on."""
    with _lock:
        if _state["done"]:
            return _state["client"] is not None
        _state["done"] = True
        if not tracing_configured(settings):
            logger.info("tracing off: LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY not set")
            return False

        from langfuse import Langfuse
        from openinference.instrumentation.crewai import CrewAIInstrumentor
        from openinference.instrumentation.litellm import LiteLLMInstrumentor

        assert settings.langfuse_secret_key is not None  # checked by tracing_configured
        client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key.get_secret_value(),
            base_url=settings.langfuse_base_url,
            environment=settings.langfuse_tracing_environment,
            release=settings.app_version,
        )
        CrewAIInstrumentor().instrument(skip_dep_check=True)
        LiteLLMInstrumentor().instrument()
        for handler in logging.getLogger().handlers:
            handler.addFilter(TraceIdFilter())
        _state["client"] = client
    reachable = _auth_check(client)
    logger.info(
        "tracing on",
        extra={"langfuse_url": settings.langfuse_base_url, "reachable": reachable},
    )
    return True


def _auth_check(client: Any) -> bool:
    """Warn early if Langfuse is down or the keys are wrong (runs still work, untraced)."""
    try:
        ok = bool(client.auth_check())
    except Exception as exc:
        logger.warning("langfuse not reachable; traces will be lost", extra={"error": str(exc)})
        return False
    if not ok:
        logger.warning("langfuse rejected the keys; traces will be lost")
    return ok


@dataclass
class RunTrace:
    """The root span of one run, as seen by the pipeline."""

    trace_id: str | None = None
    span: Any = None

    def finish(self, output: dict[str, Any], error: str | None = None) -> None:
        """Record the run's summary on the root span (no-op when tracing is off)."""
        if self.span is None:
            return
        if error:
            self.span.update(output=output, level="ERROR", status_message=error)
        else:
            self.span.update(output=output)


@contextmanager
def traced_run(
    *, job_id: str, question: str, depth: str, process: str, model: str, version: str
) -> Iterator[RunTrace]:
    """One trace for one research run; yields a `RunTrace` (empty when tracing is off)."""
    client = _state["client"]
    if client is None:
        yield RunTrace()
        return

    from langfuse import propagate_attributes

    tags = [f"depth:{depth}", f"model:{model}", f"process:{process}", f"version:{version}"]
    with (
        client.start_as_current_observation(
            as_type="span", name="research-run", input={"question": question, "depth": depth}
        ) as span,
        propagate_attributes(
            trace_name=TRACE_NAME, tags=tags, metadata={"job_id": job_id}, version=version
        ),
    ):
        yield RunTrace(trace_id=client.get_current_trace_id(), span=span)


def trace_url(settings: Settings, trace_id: str | None) -> str | None:
    """A browser link to the trace (Langfuse redirects /trace/<id> to the project's page)."""
    if not trace_id:
        return None
    return f"{settings.langfuse_ui_url.rstrip('/')}/trace/{trace_id}"


def flush_tracing() -> None:
    """Send buffered spans now (the CLI calls it before exiting, the API at shutdown)."""
    client = _state["client"]
    if client is not None:
        client.flush()
