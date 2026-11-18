"""Tests for evals.metrics (pure functions, no LLM)."""

from app.agents.pipeline import ToolCall
from app.schemas import Citation, Report, Section
from evals.metrics import (
    citation_coverage,
    percentile,
    report_claims,
    split_claims,
    tool_stats,
)


def report(summary: str, *bodies: str, citations: list[Citation] | None = None) -> Report:
    return Report(
        title="T",
        language="en",
        executive_summary=summary,
        sections=[Section(heading=f"S{i}", body_markdown=b) for i, b in enumerate(bodies)],
        citations=citations
        if citations is not None
        else [
            Citation(number=1, source="d", title="", evidence_id="sq1-e1"),
            Citation(number=2, source="d", title="", evidence_id="sq2-e1"),
        ],
    )


def test_sentences_and_list_items_are_claims_headings_are_not() -> None:
    text = (
        "## Heading\n"
        "Solar capacity grew fast in 2022 [1]. Wind followed later [2].\n\n"
        "- Saudi Arabia leads the region [1]\n"
        "1. The UAE has the largest plants [2]\n"
        "> a quoted note\n"
        "Ok."
    )
    claims = split_claims(text)
    assert [c.text for c in claims] == [
        "Solar capacity grew fast in 2022 [1].",
        "Wind followed later [2].",
        "Saudi Arabia leads the region [1]",
        "The UAE has the largest plants [2]",
    ]
    assert [c.numbers for c in claims] == [[1], [2], [1], [2]]


def test_arabic_sentences_split_on_the_arabic_question_mark_and_full_stop() -> None:
    text = "ما الذي يدفع النمو؟ انخفاض تكلفة الطاقة الشمسية [1]. وتزايد الطلب على الكهرباء [2]."
    claims = split_claims(text)
    assert [c.numbers for c in claims] == [[], [1], [2]]
    assert claims[0].text == "ما الذي يدفع النمو؟"


def test_no_evidence_statements_are_not_claims() -> None:
    r = report(
        "Costs fell sharply [1].",
        "No evidence was found in the available data about policies.",
        "لم يتم العثور على أدلة حول السياسات الحكومية في البيانات المتاحة.",
    )
    assert [c.text for c in report_claims(r)] == ["Costs fell sharply [1]."]


def test_coverage_counts_only_claims_whose_markers_all_resolve() -> None:
    citations = [
        Citation(number=1, source="d", title="", evidence_id="sq1-e1"),
        Citation(number=2, source="d", title="", evidence_id="dropped-e9"),
    ]
    r = report(
        "Costs fell sharply in the region [1].",
        "Capacity doubled between 2020 and 2023 [1][2].\nDemand keeps growing every year.\n"
        "Prices are falling due to new auctions [3].",
        citations=citations,
    )
    coverage = citation_coverage(r, {"sq1-e1"})
    assert (coverage.claims, coverage.covered) == (4, 1)
    assert coverage.rate == 0.25
    assert "Demand keeps growing every year." in coverage.uncovered


def test_coverage_of_a_report_without_claims_is_none() -> None:
    assert citation_coverage(report("", ""), set()).rate is None


def test_tool_stats() -> None:
    log = [
        ToolCall(tool="search_documents", scope="sq1", ok=True, output="x"),
        ToolCall(tool="tavily_search", scope="sq2", ok=False, output=""),
    ]
    stats = tool_stats(log)
    assert (stats.calls, stats.ok, stats.success_rate) == (2, 1, 0.5)
    assert tool_stats([]).success_rate is None


def test_percentile_nearest_rank() -> None:
    values = [10.0, 20.0, 30.0, 40.0, 100.0]
    assert percentile(values, 50) == 30.0
    assert percentile(values, 95) == 100.0
    assert percentile([], 50) is None
