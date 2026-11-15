"""The tasks: what each agent must produce, as a Pydantic model (SPEC data contracts).

Every task lists its `context` explicitly. By default a sequential crew passes every earlier
output to every task, which would break Groq's 8K tokens/min (DECISIONS #69). Here a research
task sees only its own sub-question, the Analyst sees the evidence, the Writer sees evidence and
findings, and the Reviewer sees only the report.

The research task asks for plain labelled text, not `output_pydantic` (DECISIONS #75); its
guardrail turns the text into a checked `EvidenceSet`.
"""

from collections.abc import Callable
from typing import Any

from crewai import Agent, Task
from crewai.tools import BaseTool

from app.schemas import (
    EvidenceSet,
    FindingSet,
    Language,
    Report,
    ResearchPlan,
    ReviewResult,
    SubQuestion,
)

LANGUAGE_NAMES: dict[Language, str] = {"en": "English", "ar": "Arabic"}


def plan_task(agent: Agent, question: str, language: Language, sub_questions: int) -> Task:
    return Task(
        description=(
            f"Research question: {question}\n\n"
            f"Split it into exactly {sub_questions} sub-questions that together answer it. "
            f"Give them the ids sq1, sq2, ... Write them in {LANGUAGE_NAMES[language]}. "
            "Each needs a one-sentence rationale."
        ),
        expected_output=f'A research plan with language "{language}".',
        agent=agent,
        output_pydantic=ResearchPlan,
    )


def research_task(
    agent: Agent,
    question: str,
    sub_question: SubQuestion,
    language: Language,
    tools: list[BaseTool],
    tool_calls: int,
    max_items: int,
    notes_dir: str,
    guardrail: Callable[[Any], tuple[bool, Any]],
) -> Task:
    return Task(
        description=(
            f"Main question (for context): {question}\n"
            f"Your sub-question ({sub_question.id}): {sub_question.text}\n\n"
            f"You may make at most {tool_calls} tool calls. Search the document library "
            "(search_documents) first; use web search (tavily_search) when the library has "
            f"nothing relevant. Short topic notes are in {notes_dir} (read_text_file).\n\n"
            f"Then answer with up to {max_items} evidence blocks as plain text (not JSON, not "
            "a tool call), separated by a blank line, exactly like this:\n"
            "source_type: doc or web\n"
            "source: the doc_id or URL shown in the SAME tool result as the snippet\n"
            f"claim: one sentence in {LANGUAGE_NAMES[language]} that the snippet supports\n"
            "snippet: 1-2 sentences copied EXACTLY, character for character, from that tool "
            "result (at most 300 characters)\n\n"
            "If the tools found nothing relevant, answer: NO EVIDENCE. Never invent a quote, "
            "a number or a source."
        ),
        expected_output="Evidence blocks whose snippets are exact quotes from tool results.",
        agent=agent,
        tools=tools,
        context=[],
        guardrail=guardrail,
        guardrail_max_retries=0,
    )


def analyst_task(agent: Agent, research: list[Task], language: Language) -> Task:
    return Task(
        description=(
            "The context holds evidence items gathered for each sub-question.\n"
            "Combine them into findings: merge duplicates, and when items contradict each other "
            "say so in the finding. Each finding has an id (f1, f2, ...), a statement in "
            f"{LANGUAGE_NAMES[language]}, the ids of the evidence items that support it (only ids "
            "from the context), and a confidence: high (two or more agreeing sources), medium "
            "(one clear source), low (weak or conflicting). Use no outside knowledge."
        ),
        expected_output="Findings, each linked to the evidence ids that support it.",
        agent=agent,
        context=research,
        output_pydantic=FindingSet,
    )


def _writer_instructions(question: str, plan: ResearchPlan) -> str:
    sub_questions = "\n".join(f"- {sq.id}: {sq.text}" for sq in plan.sub_questions)
    return (
        f"Research question: {question}\nSub-questions:\n{sub_questions}\n\n"
        f'Write the report in {LANGUAGE_NAMES[plan.language]} (language: "{plan.language}"): '
        "a title, a 3-5 sentence executive summary, and one section per sub-question. "
        "Use only the findings and evidence given. End every factual sentence with a citation "
        "marker [n]. In the citation list, give each number once: number n, source (the "
        "evidence item's doc_id or URL), a short title for the source, and the evidence_id of "
        "the evidence item. If a sub-question has no evidence, its section must say that no "
        "evidence was found (that sentence gets no marker); never fill the gap from memory."
    )


def writer_task(
    agent: Agent, question: str, plan: ResearchPlan, research: list[Task], analysis: Task
) -> Task:
    return Task(
        description=_writer_instructions(question, plan),
        expected_output="A complete report with numbered citations.",
        agent=agent,
        context=[*research, analysis],
        output_pydantic=Report,
    )


def reviewer_task(agent: Agent, question: str, plan: ResearchPlan, report: Task) -> Task:
    sub_questions = "\n".join(f"- {sq.id}: {sq.text}" for sq in plan.sub_questions)
    return Task(
        description=(
            f"Research question: {question}\nSub-questions:\n{sub_questions}\n\n"
            "Review the report in the context. Check that it answers the question and every "
            "sub-question (or says clearly that no evidence was found), and that every factual "
            "sentence ends with a [n] citation (a sentence saying no evidence was found needs "
            "none). Set approved to true only if there are no "
            "issues. List each issue briefly; quote every sentence that lacks a citation in "
            "uncited_claims."
        ),
        expected_output="A review verdict with issues and uncited claims.",
        agent=agent,
        context=[report],
        output_pydantic=ReviewResult,
    )


def revision_task(
    agent: Agent,
    question: str,
    plan: ResearchPlan,
    previous: Report,
    issues: list[str],
    evidence: EvidenceSet,
    findings: FindingSet,
) -> Task:
    """The one allowed rewrite: the data is in the description, so no context is needed."""
    problems = "\n".join(f"- {issue}" for issue in issues)
    evidence_json = evidence.model_dump_json(exclude={"items": {"__all__": {"retrieved_at"}}})
    return Task(
        description=(
            f"{_writer_instructions(question, plan)}\n\n"
            f"A reviewer rejected this report:\n{previous.model_dump_json()}\n\n"
            f"Fix these issues:\n{problems}\n\n"
            f"Findings:\n{findings.model_dump_json()}\n\n"
            f"Evidence:\n{evidence_json}"
        ),
        expected_output="The corrected report with numbered citations.",
        agent=agent,
        output_pydantic=Report,
    )
