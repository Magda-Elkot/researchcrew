"""Tests for app.usage: summing token usage and list-price cost (no network)."""

from types import SimpleNamespace

from app.schemas import TokenUsage
from app.usage import add_usage, cost_usd


def test_add_usage_sums_counters() -> None:
    total = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    crew = SimpleNamespace(prompt_tokens=100, completion_tokens=20, total_tokens=120)
    assert add_usage(total, crew) == TokenUsage(
        prompt_tokens=110, completion_tokens=25, total_tokens=135
    )


def test_add_usage_ignores_missing_values() -> None:
    total = TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2)
    assert add_usage(total, None) == total
    assert add_usage(total, SimpleNamespace(prompt_tokens=None)) == total


def test_cost_uses_litellm_price_table() -> None:
    # LiteLLM's local price table (no network): gpt-oss-120b on Groq, $0.15 / $0.60 per 1M.
    usage = TokenUsage(prompt_tokens=1_000_000, completion_tokens=100_000, total_tokens=1_100_000)
    assert cost_usd("groq/openai/gpt-oss-120b", usage) == 0.21


def test_cost_of_unknown_model_is_zero() -> None:
    usage = TokenUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20)
    assert cost_usd("nowhere/no-such-model", usage) == 0.0
