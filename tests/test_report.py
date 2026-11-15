"""Tests for app.agents.report: citation check and Markdown rendering."""

from typing import Any

from app.agents.report import check_citations, cited_numbers, to_markdown
from app.schemas import Citation, Report, Section


def make_report(**overrides: Any) -> Report:
    values: dict[str, Any] = {
        "title": "Solar in the GCC",
        "language": "en",
        "executive_summary": "The UAE leads [1].",
        "sections": [Section(heading="Capacity", body_markdown="2.4 GW in 2022 [1], tenders [2].")],
        "citations": [
            Citation(number=1, source="irena-gcc-2023-en", title="IRENA GCC", evidence_id="sq1-e1"),
            Citation(number=2, source="https://example.com/a", title="", evidence_id="sq2-e1"),
        ],
    }
    return Report.model_validate({**values, **overrides})


EVIDENCE = {"sq1-e1", "sq2-e1"}


def test_cited_numbers_reads_all_marker_styles() -> None:
    assert cited_numbers("a [1] b [2, 3] c [4][5] d [page 6] e [x]") == [1, 2, 3, 4, 5]


def test_consistent_report_has_no_issues() -> None:
    assert check_citations(make_report(), EVIDENCE) == []


def test_marker_without_citation() -> None:
    report = make_report(executive_summary="Leads [3].")
    assert "Marker [3] has no entry in the citation list." in check_citations(report, EVIDENCE)


def test_citation_to_unknown_evidence() -> None:
    issues = check_citations(make_report(), {"sq1-e1"})
    assert any("unknown evidence 'sq2-e1'" in issue for issue in issues)


def test_unused_and_duplicate_citations() -> None:
    extra = Citation(number=2, source="x", title="", evidence_id="sq1-e1")
    report = make_report(citations=[*make_report().citations, extra])
    issues = check_citations(report, EVIDENCE)
    assert "Citation number [2] is used for more than one source." in issues

    unused = Citation(number=9, source="x", title="", evidence_id="sq1-e1")
    report = make_report(citations=[*make_report().citations, unused])
    assert "Citation [9] is never used in the text." in check_citations(report, EVIDENCE)


def test_report_without_any_marker() -> None:
    report = make_report(
        executive_summary="No markers.",
        sections=[Section(heading="h", body_markdown="text")],
        citations=[],
    )
    assert check_citations(report, EVIDENCE) == ["The report has no [n] citation markers."]


def test_markdown_english() -> None:
    md = to_markdown(make_report(unanswered_sub_question_ids=["sq3"]))
    assert md.startswith("# Solar in the GCC\n")
    assert "## Capacity" in md
    assert "No evidence could be found for some sub-questions: sq3" in md
    assert "## References" in md
    assert "[1] IRENA GCC, irena-gcc-2023-en" in md
    assert "[2] https://example.com/a" in md
    assert "dir=" not in md


def test_markdown_arabic_is_right_to_left() -> None:
    md = to_markdown(make_report(language="ar", title="الطاقة الشمسية"))
    assert md.startswith('<div dir="rtl">')
    assert "## المراجع" in md
    assert "[1]" in md  # citations stay as [n]
