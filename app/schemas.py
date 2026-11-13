"""Pydantic v2 data contracts shared by agents, API, SSE events and evals (see SPEC.md).

Conventions: all ids are `str`; all timestamps are timezone-aware (UTC by default).
"""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints

Language = Literal["en", "ar"]
SourceType = Literal["web", "doc"]
Confidence = Literal["high", "medium", "low"]
Depth = Literal["quick", "deep"]
JobStatus = Literal["queued", "running", "completed", "failed"]
EventType = Literal[
    "agent_started",
    "tool_called",
    "tool_failed",
    "agent_finished",
    "revision_requested",
    "job_completed",
    "job_failed",
]

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def utc_now() -> datetime:
    """Current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


# --- Agent outputs -------------------------------------------------------------


class SubQuestion(BaseModel):
    id: NonEmptyStr
    text: NonEmptyStr
    rationale: str


class ResearchPlan(BaseModel):
    question: NonEmptyStr
    language: Language
    sub_questions: list[SubQuestion] = Field(min_length=3, max_length=6)


class EvidenceItem(BaseModel):
    id: NonEmptyStr
    sub_question_id: NonEmptyStr
    claim: NonEmptyStr
    snippet: str
    source_type: SourceType
    source: NonEmptyStr  # URL for web, doc_id for doc
    retrieved_at: AwareDatetime = Field(default_factory=utc_now)


class EvidenceSet(BaseModel):
    """Wrapper because CrewAI `output_pydantic` needs a model, not a list."""

    items: list[EvidenceItem]


class Finding(BaseModel):
    id: NonEmptyStr
    statement: NonEmptyStr
    evidence_ids: list[str] = Field(min_length=1)
    confidence: Confidence


class FindingSet(BaseModel):
    """Wrapper because CrewAI `output_pydantic` needs a model, not a list."""

    findings: list[Finding]


class Section(BaseModel):
    heading: NonEmptyStr
    body_markdown: str  # claims use [n] citation markers


class Citation(BaseModel):
    number: int = Field(ge=1)
    source: NonEmptyStr
    title: str
    evidence_id: NonEmptyStr


class Report(BaseModel):
    title: NonEmptyStr
    language: Language
    executive_summary: str
    sections: list[Section]
    citations: list[Citation]
    # Addition to SPEC (DECISIONS #12): sub-questions where every tool failed.
    unanswered_sub_question_ids: list[str] = Field(default_factory=list)


class ReviewResult(BaseModel):
    approved: bool
    issues: list[str] = Field(default_factory=list)
    uncited_claims: list[str] = Field(default_factory=list)


# --- SSE ----------------------------------------------------------------------


class ProgressEvent(BaseModel):
    job_id: NonEmptyStr
    type: EventType
    agent: str | None = None
    message: str
    timestamp: AwareDatetime = Field(default_factory=utc_now)


# --- API ----------------------------------------------------------------------


class ResearchRequest(BaseModel):
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]
    depth: Depth = "quick"


class JobCreated(BaseModel):
    job_id: NonEmptyStr


class TokenUsage(BaseModel):
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class JobResult(BaseModel):
    job_id: NonEmptyStr
    status: JobStatus
    report: Report | None = None
    citations: list[Citation] = Field(default_factory=list)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    cost_usd: float = Field(default=0.0, ge=0)
    latency_s: float | None = Field(default=None, ge=0)
    error: str | None = None
