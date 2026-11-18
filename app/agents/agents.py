"""The five agents and the LLM they share.

Prompts are short on purpose: every token here is resent on every LLM call of the agent, and
Groq's free tier allows 8K tokens per minute (DECISIONS #69, #73).

`RecoveringLLM` handles one gpt-oss quirk (DECISIONS #104): asked for structured output while
tools are offered, it sometimes "answers" by calling a tool that doesn't exist (`json`,
`report`). Groq rejects that with `tool_use_failed` and includes the attempted call, whose
arguments are the answer. Instead of failing the run, that answer is returned as text, and
CrewAI validates it against the task's output model as usual.
"""

import json
from typing import Any

from crewai import LLM, Agent
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.log import get_logger

logger = get_logger(__name__)

# Agent-loop iterations (LLM calls) per task. The Researcher needs room for its tool calls
# plus the final answer; the others answer from their context in one or two calls.
RESEARCHER_MAX_ITER = 6
DEFAULT_MAX_ITER = 3


def _offered_tool_names(tools: list[Any] | None) -> set[str]:
    names = set()
    for tool in tools or []:
        if isinstance(tool, dict):
            function = tool.get("function")
            name = function.get("name") if isinstance(function, dict) else tool.get("name")
            if isinstance(name, str):
                names.add(name)
    return names


def recover_fake_tool_call(error: BaseException, offered: set[str]) -> str | None:
    """The arguments of a rejected call to a tool that wasn't offered, as JSON text; else None.

    Only Groq's `tool_use_failed` with a `failed_generation` counts. A call to an offered tool
    (e.g. with bad arguments) is a real error and is not touched."""
    current: BaseException | None = error
    while current is not None:
        text = str(current)
        if "tool_use_failed" in text and "failed_generation" in text and "{" in text:
            try:
                body, _ = json.JSONDecoder().raw_decode(text[text.index("{") :])
                attempt = json.loads(body["error"]["failed_generation"])
            except (ValueError, KeyError, TypeError):
                return None
            name, arguments = attempt.get("name"), attempt.get("arguments")
            if not isinstance(name, str) or name in offered or arguments is None:
                return None
            return arguments if isinstance(arguments, str) else json.dumps(arguments)
        current = current.__cause__ or current.__context__
    return None


class RecoveringLLM(LLM):
    """`crewai.LLM` that turns a call to a non-existent tool into a normal text answer."""

    def call(self, messages: Any, tools: Any = None, *args: Any, **kwargs: Any) -> Any:
        try:
            return super().call(messages, tools, *args, **kwargs)
        except Exception as exc:
            answer = recover_fake_tool_call(exc, _offered_tool_names(tools))
            if answer is None:
                raise
            # CrewAI's structured path (response_model) expects a model instance, not text.
            # LLM.call's positional order: callbacks, available_functions, from_task,
            # from_agent, response_model.
            response_model = kwargs.get("response_model") or (args[4] if len(args) > 4 else None)
            if isinstance(response_model, type) and issubclass(response_model, BaseModel):
                try:
                    result: Any = response_model.model_validate_json(answer)
                except ValidationError:
                    raise exc from None  # the recovered arguments don't fit: the original error
            else:
                result = answer
            logger.warning(
                "recovered an answer sent as a fake tool call", extra={"chars": len(answer)}
            )
            return result

    # The parent `call` already has CrewAI's rate-limit retry; this flag (checked by
    # BaseLLM.__init_subclass__) stops CrewAI from wrapping this override a second time.
    call._crewai_rate_limit_wrapped = True  # type: ignore[attr-defined]


def build_llm(settings: Settings) -> LLM:
    """The LLM all agents use (provider-agnostic through LiteLLM)."""
    api_key = settings.groq_api_key.get_secret_value() if settings.groq_api_key else None
    # One ignore: the pydantic mypy plugin gives subclasses of LLM a strict constructor, but
    # LLM accepts extra LiteLLM arguments such as num_retries (same case as Agent, #74).
    return RecoveringLLM(  # type: ignore[call-arg]
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
