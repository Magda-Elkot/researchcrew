"""Client-side pacing for the LLM's tokens-per-minute limit (Groq free tier: 8K/min).

CrewAI retries a rate-limited call only 3 times, trusting the provider's short retry-after hint,
so a busy minute could fail a whole run (DECISIONS #79). Instead, every LLM call first passes
through `TokenPacer.before_call` (registered with CrewAI's official before-LLM-call hook): it
estimates the request's size, and if it would not fit in the last 60 seconds' budget it waits
until enough earlier calls have left the window. CrewAI's retries stay as a backup.

The estimate counts the messages *and* the schemas of the tools offered with the call (~4
characters per token, plus a reserve for formatting and the answer). After each call,
`after_call` replaces the estimate in the window with the real token count from the LLM's usage
counter, so one wrong guess can't push the next minute over the limit (DECISIONS #106: in the
hierarchical pilot a request estimated at 3.2K tokens was 5.2K, because the manager's tools
weren't counted). The budget leaves a margin below the provider's limit.

`capped_retry_waits` makes CrewAI's rate-limit retries wait as long as the provider asks (read
from Groq's message when there is no header), capped: on Groq's *daily* limit CrewAI once slept
654 s per attempt and the run looked frozen (DECISIONS #81, #83).
"""

import json
import re
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import crewai.llms.retry as crewai_retry
from crewai.hooks.llm_hooks import (
    register_after_llm_call_hook,
    register_before_llm_call_hook,
    unregister_after_llm_call_hook,
    unregister_before_llm_call_hook,
)

from app.log import get_logger

logger = get_logger(__name__)

WINDOW_S = 60.0
# Calibrated on a real quick run (34 calls, ~1,540 tokens each; the first guess of ~3 chars per
# token + 1,200 reserve overestimated ~2.8x and spent 694 of 731 s waiting, DECISIONS #79).
CHARS_PER_TOKEN = 4.0
OVERHEAD_TOKENS = 300  # formatting not visible in the messages
ANSWER_RESERVE_TOKENS = 300
BUDGET_SHARE = 0.9  # stay below the provider's limit; our count is an estimate


def _tool_chars(tools: list[Any]) -> int:
    """Characters of the tool definitions sent with a call (name, description, argument schema)."""
    chars = 0
    for tool in tools:
        schema = getattr(tool, "args_schema", None)
        try:
            schema_text = json.dumps(schema.model_json_schema()) if schema is not None else ""
        except Exception:  # an unusual schema: count what we can
            schema_text = ""
        chars += len(str(getattr(tool, "name", ""))) + len(str(getattr(tool, "description", "")))
        chars += len(schema_text)
    return chars


def estimate_tokens(messages: list[Any], tools: list[Any] | None = None) -> int:
    """A cautious size estimate for one request: messages + tool definitions + reserves."""
    chars = _tool_chars(tools or [])
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else message
        chars += len(str(content or ""))
    return int(chars / CHARS_PER_TOKEN) + OVERHEAD_TOKENS + ANSWER_RESERVE_TOKENS


def _offered_tools(context: Any) -> list[Any]:
    """The tools CrewAI sends with this call (the executor's, else the agent's)."""
    tools = getattr(getattr(context, "executor", None), "original_tools", None)
    if not tools:
        tools = getattr(getattr(context, "agent", None), "tools", None)
    return list(tools or [])


def _total_tokens(llm: Any) -> int | None:
    """The LLM's cumulative token count, or None if it doesn't keep one."""
    try:
        return int(llm.get_token_usage_summary().total_tokens)
    except Exception:
        return None


class TokenPacer:
    """A sliding one-minute window of estimated tokens."""

    def __init__(
        self,
        tokens_per_minute: int,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.budget = int(tokens_per_minute * BUDGET_SHARE)
        self.clock = clock
        self.sleep = sleep
        self.window: deque[tuple[float, int]] = deque()
        self.waited_s = 0.0
        self._lock = threading.Lock()
        self._tokens_before: int | None = None  # the LLM's usage counter before the last call

    def _drop_old(self, now: float) -> None:
        while self.window and now - self.window[0][0] >= WINDOW_S:
            self.window.popleft()

    def used(self) -> int:
        self._drop_old(self.clock())
        return sum(tokens for _, tokens in self.window)

    def wait_for(self, tokens: int) -> None:
        """Block until `tokens` fit in the window, then count them."""
        with self._lock:
            while True:
                now = self.clock()
                self._drop_old(now)
                in_window = sum(t for _, t in self.window)
                # An oversized request still goes once the window is empty (it can't do better).
                if in_window + tokens <= self.budget or not self.window:
                    break
                delay = self.window[0][0] + WINDOW_S - now + 0.1
                logger.info(
                    "pacing llm call",
                    extra={"wait_s": round(delay, 1), "in_window": in_window, "next": tokens},
                )
                self.sleep(delay)
                self.waited_s += delay
            self.window.append((self.clock(), tokens))

    def before_call(self, context: Any) -> None:
        """CrewAI before-LLM-call hook: never blocks the call, only delays it."""
        messages = list(getattr(context, "messages", []) or [])
        self.wait_for(estimate_tokens(messages, _offered_tools(context)))
        self._tokens_before = _total_tokens(getattr(context, "llm", None))

    def after_call(self, context: Any) -> None:
        """CrewAI after-LLM-call hook: put the call's real token count in the window."""
        before, self._tokens_before = self._tokens_before, None
        after = _total_tokens(getattr(context, "llm", None))
        if before is None or after is None or after <= before:
            return  # no usage reported (e.g. a failed call): keep the estimate
        with self._lock:
            if self.window:
                started, estimate = self.window[-1]
                self.window[-1] = (started, after - before)
                if after - before > estimate * 1.5:
                    logger.info(
                        "llm call larger than estimated",
                        extra={"estimate": estimate, "actual": after - before},
                    )


@contextmanager
def paced_llm_calls(tokens_per_minute: int) -> Iterator[TokenPacer | None]:
    """Pace every LLM call made inside the block; `0` turns pacing off."""
    if tokens_per_minute <= 0:
        yield None
        return
    pacer = TokenPacer(tokens_per_minute)
    register_before_llm_call_hook(pacer.before_call)
    register_after_llm_call_hook(pacer.after_call)
    try:
        yield pacer
    finally:
        unregister_before_llm_call_hook(pacer.before_call)
        unregister_after_llm_call_hook(pacer.after_call)
        logger.info("llm pacing summary", extra={"waited_s": round(pacer.waited_s, 1)})


_TRY_AGAIN = re.compile(r"try again in ((?:\d+h)?(?:\d+m(?!s))?(?:[\d.]+s)?(?:[\d.]+ms)?)", re.I)
_DURATION_PART = re.compile(r"([\d.]+)(h|ms|m|s)")


def wait_from_message(error: BaseException) -> float | None:
    """Seconds from a provider message like "Please try again in 3m56.3s" (Groq), else None."""
    match = _TRY_AGAIN.search(str(error))
    if not match or not match.group(1):
        return None
    factor = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}
    return sum(float(n) * factor[unit] for n, unit in _DURATION_PART.findall(match.group(1)))


@contextmanager
def capped_retry_waits(max_wait_s: float) -> Iterator[None]:
    """While the block runs, make CrewAI's rate-limit retries wait as long as the provider asks,
    but never longer than `max_wait_s`.

    Patches two functions in `crewai.llms.retry` (both looked up on each retry) and restores
    them afterwards; tests check they still exist, so a CrewAI upgrade can't silently undo this:
    - `_retry_after_seconds`: CrewAI reads only a `retry-after` header, which LiteLLM doesn't pass
      on for Groq; the wait is in the message instead ("try again in 23.75s"). Without it CrewAI
      retried after 1-4 s and every retry failed again.
    - `get_retry_delay_seconds`: capped, because a daily limit asks for many minutes.
    """
    original_delay = crewai_retry.get_retry_delay_seconds
    original_after = crewai_retry._retry_after_seconds

    def retry_after(error: BaseException) -> float | None:
        from_header = original_after(error)
        return from_header if from_header is not None else wait_from_message(error)

    def capped(retry_number: int, **kwargs: Any) -> float:
        delay = original_delay(retry_number, **kwargs)
        if delay > max_wait_s:
            logger.warning(
                "provider asked for a long wait; capping it",
                extra={"asked_s": round(delay), "wait_s": max_wait_s},
            )
        return min(delay, max_wait_s)

    crewai_retry._retry_after_seconds = retry_after
    crewai_retry.get_retry_delay_seconds = capped
    try:
        yield
    finally:
        crewai_retry._retry_after_seconds = original_after
        crewai_retry.get_retry_delay_seconds = original_delay
