"""Tests for RecoveringLLM: answers sent as calls to non-existent tools (no real LLM call)."""

import json
from typing import Any

import pytest
from crewai import LLM

from app.agents.agents import RecoveringLLM, build_llm, recover_fake_tool_call
from app.config import Settings


def groq_error(name: str, arguments: Any) -> Exception:
    """The error text Groq returned in the hierarchical pilot (2026-11-18), shortened."""
    generation = json.dumps({"name": name, "arguments": arguments})
    body = json.dumps(
        {
            "error": {
                "message": f"Tool call validation failed: attempted to call tool '{name}' "
                "which was not in request.tools",
                "type": "invalid_request_error",
                "code": "tool_use_failed",
                "failed_generation": generation,
            }
        }
    )
    return Exception(f"litellm.BadRequestError: GroqException - {body}")


FINDINGS = {
    "findings": [
        {
            "id": "f1",
            "statement": "Solar is cheap.",
            "evidence_ids": ["sq3-e1"],
            "confidence": "medium",
        }
    ]
}
OFFERED = [{"type": "function", "function": {"name": "Delegate work to coworker"}}]


def test_the_arguments_of_a_fake_json_tool_call_are_the_answer() -> None:
    answer = recover_fake_tool_call(groq_error("json", FINDINGS), {"Delegate work to coworker"})
    assert answer is not None and json.loads(answer) == FINDINGS


def test_a_wrapped_error_is_found_through_its_cause() -> None:
    try:
        try:
            raise groq_error("report", {"title": "T"})
        except Exception as inner:
            raise RuntimeError("crew step failed") from inner
    except RuntimeError as outer:
        assert recover_fake_tool_call(outer, set()) == '{"title": "T"}'


@pytest.mark.parametrize(
    "error",
    [
        groq_error("Delegate work to coworker", {"task": "x"}),  # an offered tool: real error
        Exception("litellm.RateLimitError: tokens per minute"),
        Exception('GroqException - {"error": {"code": "tool_use_failed"}}'),  # no generation
        Exception("tool_use_failed failed_generation {not json"),
    ],
)
def test_other_errors_are_not_recovered(error: Exception) -> None:
    assert recover_fake_tool_call(error, {"Delegate work to coworker"}) is None


def test_call_returns_the_recovered_answer_and_reraises_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    errors = [groq_error("json", FINDINGS), ValueError("something else")]

    def failing_call(self: Any, messages: Any, tools: Any = None, *a: Any, **k: Any) -> Any:
        raise errors.pop(0)

    monkeypatch.setattr(LLM, "call", failing_call)
    llm = RecoveringLLM(model="groq/openai/gpt-oss-120b", api_key="test-key")
    assert json.loads(llm.call([{"role": "user", "content": "x"}], OFFERED)) == FINDINGS
    with pytest.raises(ValueError, match="something else"):
        llm.call([{"role": "user", "content": "x"}], OFFERED)


def test_crewai_does_not_wrap_the_override_in_a_second_retry_loop() -> None:
    # BaseLLM.__init_subclass__ wraps a subclass's `call` unless it carries this flag; if CrewAI
    # renames the flag, this test fails instead of rate-limit retries silently multiplying.
    method = RecoveringLLM.__dict__["call"]
    assert getattr(method, "_crewai_rate_limit_wrapped", False) is True
    assert not hasattr(method, "__wrapped__")


def test_build_llm_uses_the_recovering_llm() -> None:
    assert isinstance(build_llm(Settings()), RecoveringLLM)


def test_the_structured_path_gets_a_validated_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.schemas import FindingSet

    errors = [groq_error("json", FINDINGS), groq_error("json", {"wrong": "shape"})]

    def failing_call(self: Any, messages: Any, tools: Any = None, *a: Any, **k: Any) -> Any:
        raise errors.pop(0)

    monkeypatch.setattr(LLM, "call", failing_call)
    llm = RecoveringLLM(model="groq/openai/gpt-oss-120b", api_key="test-key")
    result = llm.call("x", OFFERED, response_model=FindingSet)
    assert isinstance(result, FindingSet) and result.findings[0].id == "f1"
    with pytest.raises(Exception, match="tool_use_failed"):  # doesn't fit: the original error
        llm.call("x", OFFERED, None, None, None, None, FindingSet)
