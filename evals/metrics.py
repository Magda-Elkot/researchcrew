"""Automatic eval metrics (no LLM): citation coverage, tool-call success, percentiles.

Citation coverage (SPEC): the share of report claims with a valid citation. A claim is one
sentence or list item of the executive summary or a section body; headings are skipped. A claim
is *covered* when it has at least one [n] marker and every marker resolves, through the citation
list, to evidence that passed the grounding check. Sentences that state that no evidence was
found are not claims (the Writer is told to leave them uncited, DECISIONS #12).
"""

import math
import re
from dataclasses import dataclass, field

from app.agents.pipeline import ToolCall
from app.agents.report import cited_numbers
from app.schemas import Report

# A sentence ends at . ! ? or the Arabic question mark, followed by space (or the end).
_SENTENCE_END = re.compile(r"(?<=[.!?؟])\s+")
_LIST_ITEM = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_HAS_LETTER = re.compile(r"[^\W\d_]")
_NO_EVIDENCE = re.compile(
    r"no evidence|not (?:be )?found|could not (?:be )?(?:found|determined)|"
    r"لم (?:يتم العثور|تتوفر|نعثر|يُعثر|يعثر)|لا تتوفر|لا توجد أدلة",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Claim:
    text: str
    numbers: list[int]  # citation markers in the claim


def split_claims(markdown: str) -> list[Claim]:
    """Sentences and list items of a Markdown body; headings, quotes and empty lines skipped."""
    claims: list[Claim] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ">", "|")):
            continue
        stripped = _LIST_ITEM.sub("", stripped)
        for sentence in _SENTENCE_END.split(stripped):
            sentence = sentence.strip()
            if _HAS_LETTER.search(sentence) and len(sentence) >= 15:
                claims.append(Claim(sentence, cited_numbers(sentence)))
    return claims


def report_claims(report: Report) -> list[Claim]:
    """Every claim of the report, without the "no evidence was found" statements."""
    bodies = [report.executive_summary, *(s.body_markdown for s in report.sections)]
    return [c for body in bodies for c in split_claims(body) if not _NO_EVIDENCE.search(c.text)]


@dataclass
class Coverage:
    claims: int = 0
    covered: int = 0
    uncovered: list[str] = field(default_factory=list)

    @property
    def rate(self) -> float | None:
        return self.covered / self.claims if self.claims else None


def citation_coverage(report: Report, evidence_ids: set[str]) -> Coverage:
    valid_numbers = {c.number for c in report.citations if c.evidence_id in evidence_ids}
    result = Coverage()
    for claim in report_claims(report):
        result.claims += 1
        if claim.numbers and all(n in valid_numbers for n in claim.numbers):
            result.covered += 1
        else:
            result.uncovered.append(claim.text)
    return result


@dataclass(frozen=True)
class ToolStats:
    calls: int
    ok: int

    @property
    def success_rate(self) -> float | None:
        return self.ok / self.calls if self.calls else None


def tool_stats(tool_log: list[ToolCall]) -> ToolStats:
    """Executed tool calls (refused "budget used up" requests are not tool calls)."""
    return ToolStats(calls=len(tool_log), ok=sum(call.ok for call in tool_log))


def percentile(values: list[float], p: float) -> float | None:
    """The p-th percentile (0-100), nearest-rank method; None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return ordered[rank - 1]
