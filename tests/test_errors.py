"""Tests for app.agents.errors.readable_error (provider texts copied from real Groq errors)."""

import pytest

from app.agents.errors import readable_error

TPD = (
    "litellm.RateLimitError: GroqException - Rate limit reached for model `openai/gpt-oss-120b` "
    "on tokens per day (TPD): Limit 200000, Used 199182, Requested 1840. "
    "Please try again in 3m56.3s."
)
TPM = (
    "litellm.RateLimitError: GroqException - Rate limit reached for model `openai/gpt-oss-120b` "
    "on tokens per minute (TPM): Limit 8000, Used 7100, Requested 1500. "
    "Please try again in 4.5s."
)


class RateLimitError(Exception):
    pass


def test_daily_limit() -> None:
    message = readable_error(RateLimitError(TPD))
    assert message.startswith("The LLM provider's daily token limit is reached")
    assert "Try again in about 4 min" in message
    assert "LLM_MODEL" in message
    assert "199182" not in message  # no raw provider body


def test_minute_limit_in_a_wrapped_exception() -> None:
    try:
        try:
            raise RateLimitError(TPM)
        except RateLimitError as inner:
            raise RuntimeError("crew step failed") from inner
    except RuntimeError as outer:
        message = readable_error(outer)
    assert message == (
        "The LLM provider's rate limit was still exceeded after retries. Try again in about 4 s."
    )


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (Exception("AuthenticationError: Invalid API Key"), "rejected the API key"),
        (TimeoutError("request timed out"), "did not answer in time"),
        (RateLimitError("rate limit"), "Try again later."),
    ],
)
def test_known_errors(exc: Exception, expected: str) -> None:
    assert expected in readable_error(exc)


def test_unknown_errors_keep_type_and_a_short_message() -> None:
    assert readable_error(ValueError("x" * 1000)) == "ValueError: " + "x" * 300
