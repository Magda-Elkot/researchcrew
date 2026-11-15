"""Tests for app.agents.evidence: only evidence grounded in a recorded tool result survives."""

import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.agents.evidence import (
    EvidenceCheck,
    check_evidence,
    fragments,
    make_evidence_guardrail,
    normalize,
    parse_evidence_text,
)
from app.schemas import EvidenceItem, EvidenceSet

DOC_HIT = json.dumps(
    {
        "doc_id": "irena-gcc-2023-en",
        "page_start": 22,
        "text": "The UAE installed 2.4 GW of solar PV in 2022,\nmore than any other GCC country.",
    }
)
WEB_RESULT = (
    "Title: Gulf solar boom\nURL: https://www.example.com/gulf-solar/\n"
    "Content: Saudi Arabia tendered 3 GW of new solar capacity in 2023."
)
ARABIC_HIT = json.dumps(
    {"doc_id": "who-emro-ar", "text": "سلامة المرضى أولوية في جميع المستشفيات"},
    ensure_ascii=False,
)


def item(snippet: str, source: str, source_type: str = "doc", **kwargs: Any) -> EvidenceItem:
    values: dict[str, Any] = {
        "id": "x",
        "sub_question_id": "wrong",
        "claim": "a claim",
        "snippet": snippet,
        "source_type": source_type,
        "source": source,
    }
    return EvidenceItem.model_validate({**values, **kwargs})


def run(items: list[EvidenceItem], outputs: list[str], max_items: int = 5) -> EvidenceCheck:
    return check_evidence(items, outputs, "sq1", max_items=max_items, snippet_max_chars=300)


def test_normalize_undoes_json_escapes_spacing_and_case() -> None:
    assert normalize('A\\n  "B"\\tC') == normalize("a 'b' c") == "a 'b' c"


def test_normalize_unifies_quotes_and_dashes() -> None:
    assert normalize("Kuwait\u2019s Vision \u2013 \u2018New Kuwait\u2019") == normalize(
        'Kuwait\'s Vision - "New Kuwait"'
    )
    assert normalize("renewable\u2011energy") == "renewable-energy"


def test_normalize_handles_arabic_forms_and_diacritics() -> None:
    assert normalize("ﻣﺮﺣﺒﺎ") == normalize("مرحبا")  # presentation forms (from PDFs)
    assert normalize("سَلامَة") == normalize("سلامة")  # harakat
    assert normalize("سـلامة") == normalize("سلامة")  # tatweel


def test_verbatim_doc_snippet_is_kept_with_a_stable_id() -> None:
    snippet = "The UAE installed 2.4 GW of solar PV in 2022, more than any other GCC country."
    check = run([item(snippet, "irena-gcc-2023-en")], [DOC_HIT])
    (kept,) = check.kept
    assert kept.id == "sq1-e1"
    assert kept.sub_question_id == "sq1"
    assert check.dropped == []


def test_invented_snippet_is_dropped() -> None:
    check = run(
        [item("GCC renewable jobs reached 300,000 in 2022", "irena-gcc-2023-en")], [DOC_HIT]
    )
    assert check.kept == []
    assert check.dropped[0][1] == "snippet not found in any tool result"


def test_real_snippet_with_an_invented_url_is_dropped() -> None:
    snippet = "Saudi Arabia tendered 3 GW of new solar capacity"
    fake = item(snippet, "https://www.reuters.com/gcc-solar-2024", source_type="web")
    check = run([fake], [WEB_RESULT, DOC_HIT])
    assert check.kept == []
    assert "source not found" in check.dropped[0][1]


def test_url_is_matched_without_scheme_www_and_trailing_slash() -> None:
    snippet = "Saudi Arabia tendered 3 GW of new solar capacity"
    check = run([item(snippet, "http://example.com/gulf-solar", source_type="web")], [WEB_RESULT])
    assert len(check.kept) == 1


def test_source_must_be_in_the_same_result_as_the_snippet() -> None:
    snippet = "Saudi Arabia tendered 3 GW of new solar capacity"
    # The doc_id exists, but only in a different result than the snippet.
    check = run([item(snippet, "irena-gcc-2023-en")], [WEB_RESULT, DOC_HIT])
    assert check.kept == []


def test_arabic_snippet_matches_despite_diacritics() -> None:
    check = run([item("سَلامة المرضى أولوية في جميع", "who-emro-ar")], [ARABIC_HIT])
    assert len(check.kept) == 1


def test_too_short_snippet_is_dropped() -> None:
    check = run([item("the GCC", "irena-gcc-2023-en")], [DOC_HIT])
    assert check.dropped[0][1] == "snippet too short"


def test_duplicates_and_items_over_the_limit_are_dropped() -> None:
    a = "The UAE installed 2.4 GW of solar PV in 2022"
    b = "more than any other GCC country"
    c = "installed 2.4 GW of solar PV"
    doc = "irena-gcc-2023-en"
    items = [item(a, doc), item(a.upper(), doc), item(b, doc), item(c, doc)]
    check = run(
        items,
        [DOC_HIT],
        max_items=2,
    )
    assert [k.id for k in check.kept] == ["sq1-e1", "sq1-e2"]
    assert [reason for _, reason in check.dropped] == [
        "duplicate snippet",
        "over the per-sub-question limit",
    ]


def test_kept_snippet_is_cut_to_the_max_length() -> None:
    snippet = "The UAE installed 2.4 GW of solar PV in 2022"
    check = check_evidence(
        [item(snippet, "irena-gcc-2023-en")], [DOC_HIT], "sq1", max_items=5, snippet_max_chars=25
    )
    assert check.kept[0].snippet == snippet[:25]


def test_no_tool_results_means_no_evidence() -> None:
    snippet = "The UAE installed 2.4 GW of solar PV in 2022"
    assert run([item(snippet, "irena-gcc-2023-en")], []).kept == []


# --- as a CrewAI task guardrail ---

GOOD = "The UAE installed 2.4 GW of solar PV in 2022"


def test_guardrail_returns_only_kept_items_as_json() -> None:
    checks: list[EvidenceCheck] = []
    guardrail = make_evidence_guardrail(lambda: [DOC_HIT], "sq2", 3, 300, checks.append)
    evidence = EvidenceSet(
        items=[item(GOOD, "irena-gcc-2023-en"), item("invented text of some length", "x")]
    )
    ok, result = guardrail(SimpleNamespace(pydantic=evidence, raw=""))
    assert ok is True
    cleaned = EvidenceSet.model_validate_json(result)
    assert [i.id for i in cleaned.items] == ["sq2-e1"]
    assert len(checks[0].dropped) == 1


def test_guardrail_reads_raw_json_when_there_is_no_pydantic_output() -> None:
    guardrail = make_evidence_guardrail(lambda: [DOC_HIT], "sq1", 3, 300)
    raw = EvidenceSet(items=[item(GOOD, "irena-gcc-2023-en")]).model_dump_json()
    _, result = guardrail(SimpleNamespace(pydantic=None, raw=raw))
    assert len(EvidenceSet.model_validate_json(result).items) == 1


@pytest.mark.parametrize("raw", ["not json", '{"items": [{"id": 1}]}'])
def test_guardrail_turns_unreadable_output_into_no_evidence(raw: str) -> None:
    guardrail = make_evidence_guardrail(lambda: [DOC_HIT], "sq1", 3, 300)
    ok, result = guardrail(SimpleNamespace(pydantic=None, raw=raw))
    assert ok is True
    assert EvidenceSet.model_validate_json(result).items == []


# --- reading the Researcher's text answer ---

TEXT_ANSWER = """Here is what I found.

source_type: doc
source: irena-gcc-2023-en
claim: The UAE leads the GCC in solar.
snippet: "The UAE installed 2.4 GW of solar PV in 2022,
more than any other GCC country."

- **source_type**: web
- **source**: https://www.example.com/gulf-solar/
- **claim**: Saudi Arabia is tendering more solar.
- **snippet**: Saudi Arabia tendered 3 GW of new solar capacity in 2023.
"""


def test_parse_labelled_blocks_with_markdown_and_wrapped_lines() -> None:
    first, second = parse_evidence_text(TEXT_ANSWER, "sq1")
    assert (first.source_type, first.source) == ("doc", "irena-gcc-2023-en")
    assert first.snippet == (
        "The UAE installed 2.4 GW of solar PV in 2022, more than any other GCC country."
    )
    assert first.sub_question_id == "sq1"
    assert (second.source_type, second.source) == ("web", "https://www.example.com/gulf-solar/")
    assert second.claim == "Saudi Arabia is tendering more solar."


def test_parse_then_check_keeps_both_items() -> None:
    items = parse_evidence_text(TEXT_ANSWER, "sq1")
    assert len(run(items, [DOC_HIT, WEB_RESULT]).kept) == 2


def test_parse_arabic_labels_values_and_fullwidth_colon() -> None:
    raw = (
        "source_type: doc\n"
        "source\uff1a who-emro-ar\n"  # full-width colon
        "claim: سلامة المرضى أولوية\n"
        "snippet: «سلامة المرضى أولوية في جميع المستشفيات»"
    )
    (only,) = parse_evidence_text(raw, "sq2")
    assert only.source == "who-emro-ar"
    assert only.snippet == "سلامة المرضى أولوية في جميع المستشفيات"


def test_parse_guesses_a_missing_source_type_and_skips_incomplete_blocks() -> None:
    raw = "source: https://a.example/x\nclaim: c\nsnippet: s\n\nsource_type: doc\nclaim: no source"
    (only,) = parse_evidence_text(raw, "sq1")
    assert only.source_type == "web"


@pytest.mark.parametrize("raw", ["NO EVIDENCE", "", "I could not find anything."])
def test_parse_no_evidence(raw: str) -> None:
    assert parse_evidence_text(raw, "sq1") == []


def test_parse_still_accepts_json_even_in_a_code_fence() -> None:
    evidence = EvidenceSet(items=[item(GOOD, "irena-gcc-2023-en")])
    raw = f"```json\n{evidence.model_dump_json()}\n```"
    assert [i.source for i in parse_evidence_text(raw, "sq1")] == ["irena-gcc-2023-en"]


def test_guardrail_reads_the_text_format() -> None:
    guardrail = make_evidence_guardrail(lambda: [DOC_HIT, WEB_RESULT], "sq1", 3, 300)
    _, result = guardrail(SimpleNamespace(pydantic=None, raw=TEXT_ANSWER))
    assert [i.id for i in EvidenceSet.model_validate_json(result).items] == ["sq1-e1", "sq1-e2"]


# --- quotes that skip text with an ellipsis ---

LONG_DOC = json.dumps(
    {
        "doc_id": "irena-gcc-2023-en",
        "text": "In 2019, Saudi Arabia announced a new target for renewable energy. Several "
        "reforms followed. Capacity from solar and wind should reach 58 000 MW by 2030.",
    }
)


def test_fragments_split_at_ellipses() -> None:
    assert fragments(normalize("“A long first part… a second part...third.”")) == [
        "a long first part",
        "a second part",
        "third",
    ]


def test_quote_with_ellipsis_is_kept_when_every_piece_is_verbatim_and_in_order() -> None:
    snippet = "In 2019, Saudi Arabia announced a new target… solar and wind should reach 58 000 MW"
    assert len(run([item(snippet, "irena-gcc-2023-en")], [LONG_DOC]).kept) == 1


def test_pieces_in_the_wrong_order_are_dropped() -> None:
    snippet = "solar and wind should reach 58 000 MW… Saudi Arabia announced a new target"
    assert run([item(snippet, "irena-gcc-2023-en")], [LONG_DOC]).kept == []


def test_an_invented_piece_between_ellipses_is_dropped() -> None:
    snippet = "Saudi Arabia announced a new target… 300,000 new jobs… reach 58 000 MW"
    assert run([item(snippet, "irena-gcc-2023-en")], [LONG_DOC]).kept == []


def test_pieces_from_two_different_results_are_dropped() -> None:
    snippet = "The UAE installed 2.4 GW of solar PV… Saudi Arabia tendered 3 GW of new solar"
    assert run([item(snippet, "irena-gcc-2023-en")], [DOC_HIT, WEB_RESULT]).kept == []


def test_only_tiny_pieces_count_as_too_short() -> None:
    check = run([item("In 2019… a new… by 2030", "irena-gcc-2023-en")], [LONG_DOC])
    assert check.dropped[0][1] == "snippet too short"
