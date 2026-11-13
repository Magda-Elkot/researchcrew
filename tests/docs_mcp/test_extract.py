"""Tests for docs_mcp.extract: PDF extraction, normalisation and the Arabic check."""

from pathlib import Path

import pymupdf
import pytest

from mcp_servers.docs_mcp.extract import (
    ExtractionError,
    arabic_quality,
    extract_pdf,
    fix_lam_alef,
    normalize,
    reverse_arabic_lines,
)

# "Public health in the Arab world" (logical order, as it should be extracted).
ARABIC = "الصحة العامة في العالم العربي والمنطقة"
# The same text in visual order, as some PDFs extract it.
ARABIC_REVERSED = ARABIC[::-1]
# "السحة" written with presentation-form glyphs: alef, lam, seen, hah, teh marbuta.
PRESENTATION_FORMS = "ﺍﻟﺴﺤﺔ"
BASE_LETTERS = "السحة"


def _make_pdf(path: Path, pages: list[str], title: str = "") -> Path:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    if title:
        doc.set_metadata({"title": title})
    doc.save(path)
    doc.close()
    return path


# --- normalize ---------------------------------------------------------------------


def test_nfkc_maps_presentation_forms_to_letters() -> None:
    assert normalize(PRESENTATION_FORMS) == BASE_LETTERS


def test_normalize_tidies_whitespace_and_soft_hyphens() -> None:
    assert normalize("  a­b   c \n\n\n\n d  ") == "ab c\n\nd"


# --- arabic_quality --------------------------------------------------------------


def test_quality_of_clean_arabic() -> None:
    q = arabic_quality(ARABIC)
    assert q.arabic_ratio == 1.0
    assert q.presentation_form_ratio == 0.0
    assert not q.reversed_suspected


def test_quality_detects_presentation_forms() -> None:
    q = arabic_quality(PRESENTATION_FORMS)
    assert q.presentation_form_ratio == 1.0
    assert q.arabic_ratio == 1.0


def test_quality_detects_reversed_text() -> None:
    assert arabic_quality(ARABIC_REVERSED).reversed_suspected


def test_quality_of_english_text() -> None:
    q = arabic_quality("Renewable energy capacity grew in 2025.")
    assert q.arabic_ratio == 0.0
    assert not q.reversed_suspected


def test_reverse_arabic_lines_restores_order_and_skips_latin_lines() -> None:
    text = f"{ARABIC_REVERSED}\nIRENA 2025"
    assert reverse_arabic_lines(text) == f"{ARABIC}\nIRENA 2025"


# --- extract_pdf -------------------------------------------------------------------


def test_extract_english_pdf(tmp_path: Path) -> None:
    pdf = _make_pdf(
        tmp_path / "irena-report.pdf",
        ["Solar capacity reached a new record this year.", "Wind power also grew strongly."],
        title="Renewable Capacity Statistics",
    )
    doc = extract_pdf(pdf)
    assert doc.title == "Renewable Capacity Statistics"
    assert doc.language == "en"
    assert [p.page for p in doc.pages] == [1, 2]
    assert "Solar capacity" in doc.pages[0].text
    assert "Wind power" in doc.full_text
    assert not doc.reversed_fixed


def test_title_falls_back_to_file_name(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "who-fact-sheet.pdf", ["Some long enough text on this page."])
    assert extract_pdf(pdf).title == "who-fact-sheet"


def test_scanned_pdf_without_text_is_rejected(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "scan.pdf", ["", ""])
    with pytest.raises(ExtractionError, match="no usable text layer"):
        extract_pdf(pdf)


# --- swapped ligatures (found in real WHO EMRO Arabic PDFs) ----------------------------


def test_fix_lam_alef_restores_article_before_hamza_alef() -> None:
    # "الإقليم" (the region), "الأمراض" (diseases), "الاتصالات" (communications)
    broken = "اإلقليم و األمراض و االتصاالت"
    fixed, count = fix_lam_alef(broken)
    assert fixed == "الإقليم و الأمراض و الاتصالات"
    assert count == 4


def test_fix_lam_alef_leaves_correct_text_alone() -> None:
    assert fix_lam_alef(ARABIC) == (ARABIC, 0)
    assert fix_lam_alef("إلى الإقليم") == ("إلى الإقليم", 0)


def test_quality_detects_swapped_letter_pairs() -> None:
    broken = " ".join(["يف الصحة عىل"] * 6)  # "في" -> "يف", "على" -> "عىل"
    assert arabic_quality(broken).swapped_pairs_suspected
    assert not arabic_quality(" ".join(["في الصحة على"] * 6)).swapped_pairs_suspected


def test_a_few_swapped_markers_are_tolerated() -> None:
    mostly_fine = " ".join(["في الصحة على"] * 20) + " يف عىل"
    assert not arabic_quality(mostly_fine).swapped_pairs_suspected


def test_extract_rejects_pdf_with_swapped_pairs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Base-14 PDF fonts can't draw Arabic, so feed the broken text in through PyMuPDF.
    pdf = _make_pdf(tmp_path / "broken.pdf", ["placeholder text long enough for the check"])
    broken = " ".join(["يف الصحة عىل"] * 6)
    monkeypatch.setattr(pymupdf.Page, "get_text", lambda self, *a, **k: broken)
    with pytest.raises(ExtractionError, match="wrong order"):
        extract_pdf(pdf)


def test_extract_fixes_lam_alef_and_counts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf = _make_pdf(tmp_path / "region.pdf", ["placeholder text long enough for the check"])
    monkeypatch.setattr(
        pymupdf.Page, "get_text", lambda self, *a, **k: "تقرير المديرة اإلقليمية عن األمراض"
    )
    doc = extract_pdf(pdf)
    assert doc.pages[0].text == "تقرير المديرة الإقليمية عن الأمراض"
    assert doc.lam_alef_fixes == 2
    assert doc.language == "ar"
