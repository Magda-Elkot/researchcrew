"""Tests for app.observability (Langfuse and the instrumentors are fakes: no network)."""

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, ClassVar

import pytest
from opentelemetry.sdk.trace import TracerProvider

from app import observability
from app.agents import pipeline
from app.config import Settings
from tests.test_pipeline import FakeSteps, run


class FakeSpan:
    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []

    def update(self, **fields: Any) -> None:
        self.updates.append(fields)


class FakeLangfuse:
    instances: ClassVar[list["FakeLangfuse"]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.spans: list[tuple[dict[str, Any], FakeSpan]] = []
        self.flushed = 0
        FakeLangfuse.instances.append(self)

    def auth_check(self) -> bool:
        return True

    @contextmanager
    def start_as_current_observation(self, **kwargs: Any) -> Iterator[FakeSpan]:
        span = FakeSpan()
        self.spans.append((kwargs, span))
        yield span

    def get_current_trace_id(self) -> str:
        return "a" * 32

    def flush(self) -> None:
        self.flushed += 1


class FakeInstrumentor:
    calls: ClassVar[list[str]] = []

    def instrument(self, **kwargs: Any) -> None:
        FakeInstrumentor.calls.append(type(self).__name__)


class CrewAIInstrumentor(FakeInstrumentor):
    pass


class LiteLLMInstrumentor(FakeInstrumentor):
    pass


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(observability, "_state", {"done": False, "client": None})
    FakeLangfuse.instances.clear()
    FakeInstrumentor.calls.clear()
    yield
    for handler in logging.getLogger().handlers:  # don't leak the filter into other tests
        for f in [f for f in handler.filters if isinstance(f, observability.TraceIdFilter)]:
            handler.removeFilter(f)


@pytest.fixture
def propagated(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Fake Langfuse SDK modules; returns what `propagate_attributes` received."""
    import langfuse
    import openinference.instrumentation.crewai as oi_crewai
    import openinference.instrumentation.litellm as oi_litellm

    seen: list[dict[str, Any]] = []

    @contextmanager
    def propagate_attributes(**kwargs: Any) -> Iterator[None]:
        seen.append(kwargs)
        yield

    monkeypatch.setattr(langfuse, "Langfuse", FakeLangfuse)
    monkeypatch.setattr(langfuse, "propagate_attributes", propagate_attributes)
    monkeypatch.setattr(oi_crewai, "CrewAIInstrumentor", CrewAIInstrumentor)
    monkeypatch.setattr(oi_litellm, "LiteLLMInstrumentor", LiteLLMInstrumentor)
    return seen


def keyed() -> Settings:
    return Settings(langfuse_public_key="pk-lf-x", langfuse_secret_key="sk-lf-y")  # type: ignore[arg-type]


def test_without_keys_nothing_is_set_up(propagated: list[dict[str, Any]]) -> None:
    assert observability.setup_tracing(Settings()) is False
    assert FakeLangfuse.instances == [] and FakeInstrumentor.calls == []
    with observability.traced_run(
        job_id="j", question="q", depth="quick", process="sequential", model="m", version="v"
    ) as trace:
        assert trace.trace_id is None
        trace.finish({"status": "completed"})  # a no-op, not an error
    observability.flush_tracing()


def test_with_keys_the_client_and_both_instrumentors_start_once(
    propagated: list[dict[str, Any]],
) -> None:
    assert observability.setup_tracing(keyed()) is True
    assert observability.setup_tracing(keyed()) is True  # second call: nothing new
    [client] = FakeLangfuse.instances
    assert client.kwargs["public_key"] == "pk-lf-x"
    assert client.kwargs["secret_key"] == "sk-lf-y"
    assert client.kwargs["base_url"] == "http://localhost:3000"
    assert FakeInstrumentor.calls == ["CrewAIInstrumentor", "LiteLLMInstrumentor"]


def test_a_run_is_one_root_span_with_tags_and_output(propagated: list[dict[str, Any]]) -> None:
    observability.setup_tracing(keyed())
    with observability.traced_run(
        job_id="j1",
        question="q?",
        depth="deep",
        process="sequential",
        model="groq/x",
        version="0.1",
    ) as trace:
        assert trace.trace_id == "a" * 32
        trace.finish({"status": "failed"}, error="daily limit")
    [(kwargs, span)] = FakeLangfuse.instances[0].spans
    assert kwargs == {
        "as_type": "span",
        "name": "research-run",
        "input": {"question": "q?", "depth": "deep"},
    }
    assert propagated == [
        {
            "trace_name": "research",
            "tags": ["depth:deep", "model:groq/x", "process:sequential", "version:0.1"],
            "metadata": {"job_id": "j1"},
            "version": "0.1",
        }
    ]
    assert span.updates == [
        {"output": {"status": "failed"}, "level": "ERROR", "status_message": "daily limit"}
    ]


def test_the_pipeline_puts_the_trace_id_on_the_result(propagated: list[dict[str, Any]]) -> None:
    observability.setup_tracing(keyed())
    result, _ = run(FakeSteps())
    assert result.status == "completed"
    assert result.trace_id == "a" * 32
    [(_, span)] = FakeLangfuse.instances[0].spans
    output = span.updates[0]["output"]
    assert output["status"] == "completed"
    assert output["title"] == "Solar"


def test_the_pipeline_without_tracing_has_no_trace_id() -> None:
    result, _ = run(FakeSteps())
    assert result.trace_id is None


def test_log_lines_inside_a_span_carry_the_trace_id(capsys: pytest.CaptureFixture[str]) -> None:
    logger = pipeline.logger  # any app logger: they share the root handler
    for handler in logging.getLogger().handlers:
        handler.addFilter(observability.TraceIdFilter())
    tracer = TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("run") as span:
        logger.info("inside")
        expected = format(span.get_span_context().trace_id, "032x")
    logger.info("outside")
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    inside = next(line for line in lines if line["message"] == "inside")
    outside = next(line for line in lines if line["message"] == "outside")
    assert inside["trace_id"] == expected
    assert "trace_id" not in outside


def test_trace_url() -> None:
    settings = Settings(langfuse_ui_url="http://localhost:3000/")
    assert observability.trace_url(settings, "abc") == "http://localhost:3000/trace/abc"
    assert observability.trace_url(settings, None) is None


def test_flush_reaches_the_client(propagated: list[dict[str, Any]]) -> None:
    observability.setup_tracing(keyed())
    observability.flush_tracing()
    assert FakeLangfuse.instances[0].flushed == 1
