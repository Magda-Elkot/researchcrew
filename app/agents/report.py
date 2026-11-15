"""Report helpers: a deterministic citation check and the Markdown rendering.

`check_citations` finds mechanical problems the Reviewer agent might miss (exact, no tokens):
markers without a citation, citations pointing to evidence that was dropped or never existed,
unused or duplicate citation numbers. Its issues are merged into the review, so they can trigger
the one allowed revision.
"""

import re

from app.schemas import Report

# [1], [2, 3] and [4][5] all count; numbers inside other brackets ("[page 4]") don't.
_MARKER = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


def cited_numbers(text: str) -> list[int]:
    """Citation numbers used in `text`, in order of appearance."""
    return [int(n) for group in _MARKER.findall(text) for n in group.split(",")]


def check_citations(report: Report, evidence_ids: set[str]) -> list[str]:
    """Problems with the report's citations; an empty list means they are consistent."""
    issues: list[str] = []
    texts = [report.executive_summary] + [s.body_markdown for s in report.sections]
    used = {n for text in texts for n in cited_numbers(text)}
    numbers = [c.number for c in report.citations]

    if report.sections and not used:
        issues.append("The report has no [n] citation markers.")
    for n in sorted({n for n in numbers if numbers.count(n) > 1}):
        issues.append(f"Citation number [{n}] is used for more than one source.")
    for n in sorted(used - set(numbers)):
        issues.append(f"Marker [{n}] has no entry in the citation list.")
    for citation in report.citations:
        if citation.evidence_id not in evidence_ids:
            issues.append(
                f"Citation [{citation.number}] points to unknown evidence "
                f"'{citation.evidence_id}'; cite only the evidence ids you were given."
            )
        if citation.number not in used:
            issues.append(f"Citation [{citation.number}] is never used in the text.")
    return issues


def to_markdown(report: Report) -> str:
    """The report as Markdown; Arabic reports are wrapped for right-to-left display."""
    lines = [f"# {report.title}", "", report.executive_summary, ""]
    for section in report.sections:
        lines += [f"## {section.heading}", "", section.body_markdown, ""]
    if report.unanswered_sub_question_ids:
        note = (
            "لم تتوفر أدلة لبعض الأسئلة الفرعية: "
            if report.language == "ar"
            else "No evidence could be found for some sub-questions: "
        )
        lines += [f"> {note}{', '.join(report.unanswered_sub_question_ids)}", ""]
    heading = "المراجع" if report.language == "ar" else "References"
    lines += [f"## {heading}", ""]
    for c in sorted(report.citations, key=lambda c: c.number):
        title = f"{c.title}, " if c.title else ""
        lines.append(f"[{c.number}] {title}{c.source}  ")
    body = "\n".join(lines).rstrip() + "\n"
    if report.language == "ar":
        return f'<div dir="rtl">\n\n{body}\n</div>\n'
    return body
