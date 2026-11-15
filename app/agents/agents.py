"""The five agents and the LLM they share.

Prompts are short on purpose: every token here is resent on every LLM call of the agent, and
Groq's free tier allows 8K tokens per minute (DECISIONS #69, #73).
"""

from crewai import LLM, Agent

from app.config import Settings

# Agent-loop iterations (LLM calls) per task. The Researcher needs room for its tool calls
# plus the final answer; the others answer from their context in one or two calls.
RESEARCHER_MAX_ITER = 6
DEFAULT_MAX_ITER = 3


def build_llm(settings: Settings) -> LLM:
    """The LLM all agents use (provider-agnostic through LiteLLM)."""
    api_key = settings.groq_api_key.get_secret_value() if settings.groq_api_key else None
    return LLM(
        model=settings.llm_model,
        api_key=api_key,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout_s,
        num_retries=settings.llm_num_retries,  # passed through to litellm.completion
    )


def _agent(role: str, goal: str, backstory: str, llm: LLM, max_iter: int) -> Agent:
    # One ignore for all agents: Agent's fields live in a base class the pydantic mypy plugin
    # can't see, so strict mypy reports them as unexpected keywords (DECISIONS #66, #74).
    return Agent(  # type: ignore[call-arg]
        role=role,
        goal=goal,
        backstory=backstory,
        llm=llm,
        max_iter=max_iter,
        allow_delegation=False,
        verbose=False,
    )


def planner(llm: LLM) -> Agent:
    return _agent(
        "Research Planner",
        "Split a research question into a few focused, answerable sub-questions.",
        "You plan research projects. Each sub-question covers one distinct aspect.",
        llm,
        DEFAULT_MAX_ITER,
    )


def researcher(llm: LLM) -> Agent:
    return _agent(
        "Researcher",
        "Find evidence for one sub-question with the tools, copying quotes exactly.",
        "You search the document library first, then the web. You never invent a quote, "
        "a number or a source: everything you report comes from a tool result.",
        llm,
        RESEARCHER_MAX_ITER,
    )


def analyst(llm: LLM) -> Agent:
    return _agent(
        "Analyst",
        "Turn evidence into distinct findings, resolving duplicates and contradictions.",
        "You weigh evidence carefully and rate how well each finding is supported.",
        llm,
        DEFAULT_MAX_ITER,
    )


def writer(llm: LLM) -> Agent:
    return _agent(
        "Writer",
        "Write a clear, well-structured report in which every claim carries a citation.",
        "You write professional research reports. You only state what the findings support.",
        llm,
        DEFAULT_MAX_ITER,
    )


def reviewer(llm: LLM) -> Agent:
    return _agent(
        "Reviewer",
        "Check that the report answers the question and every claim has a citation.",
        "You are a strict editor. You approve only reports you would publish.",
        llm,
        DEFAULT_MAX_ITER,
    )
