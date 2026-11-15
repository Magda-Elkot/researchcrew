"""Token usage and cost for one run.

A run uses several crews (Planner, main crew, maybe one revision); their usage is summed here.
Cost is computed with LiteLLM's price table at list price. On a free tier you pay nothing, but
the list price is what SPEC's budget (< $0.05 per quick report) is measured against.
"""

from typing import Any

import litellm

from app.log import get_logger
from app.schemas import TokenUsage

logger = get_logger(__name__)


def add_usage(total: TokenUsage, usage: Any) -> TokenUsage:
    """Add a CrewAI `UsageMetrics` (or anything with the same three counters) to `total`."""
    if usage is None:
        return total
    return TokenUsage(
        prompt_tokens=total.prompt_tokens + int(getattr(usage, "prompt_tokens", 0) or 0),
        completion_tokens=total.completion_tokens
        + int(getattr(usage, "completion_tokens", 0) or 0),
        total_tokens=total.total_tokens + int(getattr(usage, "total_tokens", 0) or 0),
    )


def cost_usd(model: str, usage: TokenUsage) -> float:
    """List-price cost of `usage` for `model`; 0.0 (logged) if LiteLLM has no price for it."""
    try:
        prompt_cost, completion_cost = litellm.cost_per_token(
            model=model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
        )
    except Exception as exc:  # LiteLLM raises a plain Exception for unknown models
        logger.warning("no price for model", extra={"model": model, "error": str(exc)[:200]})
        return 0.0
    return round(prompt_cost + completion_cost, 6)
