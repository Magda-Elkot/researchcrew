"""Readable error messages for failed runs (DECISIONS #88).

A failed run used to show the raw exception, e.g. 400 characters of a Groq JSON body. Users of
the API and the UI need one sentence saying what happened and what to do; the full exception
stays in the server log (`run failed`). Matching is on the text of the exception and its causes,
because CrewAI and LiteLLM wrap provider errors in their own types.
"""

from app.agents.pacing import wait_from_message

MAX_DETAIL_CHARS = 300
# Part of the daily-limit message; the eval runner looks for it to stop and resume next day.
DAILY_LIMIT_MARKER = "daily token limit is reached"


def _chain_text(exc: BaseException) -> str:
    """Type names and messages of the exception and everything it was raised from."""
    parts: list[str] = []
    current: BaseException | None = exc
    while current is not None and len(parts) < 10:
        parts.append(f"{type(current).__name__}: {current}")
        current = current.__cause__ or current.__context__
    return " | ".join(parts)


def _try_again(text: str) -> str:
    seconds = wait_from_message(Exception(text))  # the wait may be in a wrapped cause
    if seconds is None:
        return "Try again later"
    if seconds < 90:
        return f"Try again in about {max(1, round(seconds))} s"
    return f"Try again in about {round(seconds / 60)} min"


def readable_error(exc: BaseException) -> str:
    """One sentence for the user; unknown errors keep their type and a short message."""
    text = _chain_text(exc)
    lowered = text.lower()
    if "tokens per day" in lowered or "(tpd)" in lowered:
        return (
            f"The LLM provider's {DAILY_LIMIT_MARKER} (Groq free tier). "
            f"{_try_again(text)}, or set LLM_MODEL to a model with its own quota."
        )
    if "ratelimit" in lowered or "rate limit" in lowered:
        retry = _try_again(text)
        return f"The LLM provider's rate limit was still exceeded after retries. {retry}."
    if "authenticationerror" in lowered or "invalid api key" in lowered:
        return "The LLM provider rejected the API key. Check GROQ_API_KEY in .env."
    if "timeout" in lowered:
        return "The LLM provider did not answer in time (LLM_TIMEOUT_S). Try again."
    return f"{type(exc).__name__}: {str(exc)[:MAX_DETAIL_CHARS]}"
