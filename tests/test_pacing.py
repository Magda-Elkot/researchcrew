"""Tests for app.agents.pacing: the one-minute token window (fake clock, no real waiting)."""

from types import SimpleNamespace

import crewai.llms.retry as crewai_retry
import pytest
from crewai.hooks.llm_hooks import get_before_llm_call_hooks

from app.agents.pacing import (
    ANSWER_RESERVE_TOKENS,
    OVERHEAD_TOKENS,
    TokenPacer,
    capped_retry_waits,
    estimate_tokens,
    paced_llm_calls,
    wait_from_message,
)


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def pacer(tokens_per_minute: int = 10_000) -> tuple[TokenPacer, FakeTime]:
    t = FakeTime()
    return TokenPacer(tokens_per_minute, clock=t.clock, sleep=t.sleep), t


def test_estimate_counts_message_text_plus_reserves() -> None:
    messages = [{"role": "user", "content": "x" * 400}, {"role": "system", "content": None}]
    assert estimate_tokens(messages) == 100 + OVERHEAD_TOKENS + ANSWER_RESERVE_TOKENS


def test_budget_keeps_a_margin_below_the_limit() -> None:
    p, _ = pacer(8000)
    assert p.budget == 7200


def test_calls_that_fit_do_not_wait() -> None:
    p, t = pacer()  # budget 9000
    p.wait_for(4000)
    p.wait_for(4000)
    assert t.sleeps == []
    assert p.used() == 8000


def test_a_call_that_does_not_fit_waits_for_the_oldest_to_expire() -> None:
    p, t = pacer()
    p.wait_for(5000)
    t.now = 20
    p.wait_for(3000)
    t.now = 30
    p.wait_for(4000)  # 12000 > 9000: wait until the first call (t=0) leaves the window
    assert t.sleeps == [30.1]
    assert p.used() == 7000
    assert p.waited_s == 30.1


def test_oversized_call_goes_once_the_window_is_empty() -> None:
    p, t = pacer()
    p.wait_for(1000)
    p.wait_for(20_000)
    assert len(t.sleeps) == 1  # waited for the window to empty, then sent anyway


def test_old_calls_leave_the_window() -> None:
    p, t = pacer()
    p.wait_for(8000)
    t.now = 61
    assert p.used() == 0


def test_hook_reads_the_messages_from_the_context() -> None:
    p, _ = pacer()
    p.before_call(SimpleNamespace(messages=[{"role": "user", "content": "y" * 40}]))
    assert p.used() == 10 + OVERHEAD_TOKENS + ANSWER_RESERVE_TOKENS


def test_context_manager_registers_and_removes_the_hook() -> None:
    before = len(get_before_llm_call_hooks())
    with paced_llm_calls(8000) as p:
        assert p is not None
        assert len(get_before_llm_call_hooks()) == before + 1
    assert len(get_before_llm_call_hooks()) == before


def test_zero_turns_pacing_off() -> None:
    before = len(get_before_llm_call_hooks())
    with paced_llm_calls(0) as p:
        assert p is None
        assert len(get_before_llm_call_hooks()) == before


def test_retry_wait_is_capped_and_restored() -> None:
    original = crewai_retry.get_retry_delay_seconds
    with capped_retry_waits(60):
        # A daily-limit retry-after of 654 s (seen on Groq) is cut to 60 s ...
        assert crewai_retry.get_retry_delay_seconds(1, retry_after_seconds=654) == 60
        # ... a short hint is kept.
        assert crewai_retry.get_retry_delay_seconds(1, retry_after_seconds=2.5) == 2.5
    assert crewai_retry.get_retry_delay_seconds is original


def test_crewai_retry_loop_still_uses_the_patched_functions() -> None:
    # Guards the patch against a CrewAI upgrade that renames or inlines these functions.
    import inspect

    source = inspect.getsource(crewai_retry.run_with_rate_limit_retry)
    assert "get_retry_delay_seconds(" in source
    assert "_retry_after_seconds(error)" in source


GROQ_TPM = (
    "Rate limit reached for model `openai/gpt-oss-20b` ... on tokens per minute (TPM): "
    "Limit 8000, Used 6620, Requested 4547. Please try again in 23.752499999s. Need more tokens?"
)


@pytest.mark.parametrize(
    ("message", "seconds"),
    [
        (GROQ_TPM, 23.752499999),
        ("... Please try again in 3m56.304s. Need more", 236.304),
        ("... Please try again in 1h2m3s.", 3723.0),
        ("... Please try again in 577ms.", 0.577),
        ("connection reset by peer", None),
    ],
)
def test_wait_is_read_from_the_provider_message(message: str, seconds: float | None) -> None:
    result = wait_from_message(RuntimeError(message))
    assert result == pytest.approx(seconds) if seconds is not None else result is None


def test_retry_uses_the_wait_from_the_message_when_there_is_no_header() -> None:
    error = RuntimeError(GROQ_TPM)
    original = crewai_retry._retry_after_seconds
    with capped_retry_waits(60):
        assert crewai_retry._retry_after_seconds(error) == pytest.approx(23.7525, abs=1e-3)
        long_wait = RuntimeError("Please try again in 10m53.6s")
        delay = crewai_retry.get_retry_delay_seconds(
            1, retry_after_seconds=crewai_retry._retry_after_seconds(long_wait)
        )
        assert delay == 60  # a daily-limit wait is still capped
    assert crewai_retry._retry_after_seconds is original
