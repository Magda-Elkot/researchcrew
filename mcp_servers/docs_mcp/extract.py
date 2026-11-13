"""PDF text extraction for docs-mcp: PyMuPDF + NFKC normalisation + an Arabic quality check.

Only born-digital PDFs are supported (no OCR). Arabic text is checked for known
extraction problems:
- presentation forms (U+FB50-U+FDFF, U+FE70-U+FEFF): glyph shapes instead of letters.
  NFKC maps them back to the base letters.
- visual (reversed) order: words come out backwards, so the article "ال" appears as
  "لا" at the end of words. Detected heuristically and fixed by reversing Arabic lines.
- swapped lam-alef ligatures: the font maps "لإ" to "إل", so "الإقليم" comes out as
  "اإلقليم". An alef is never followed by another alef-type letter in correct Arabic,
  so "ا[اأإآ]ل" is always this bug and is fixed by swapping back.
- swapped letter pairs in general ("في" -> "يف", "على" -> "عىل", "بين" -> "بني"):
  too many pairs to fix safely, so such a PDF is rejected with a clear error.
"""

import re
import unicodedata
from pathlib import Path

import pymupdf
from pydantic import BaseModel

from app.schemas import Language

# A document with fewer extracted characters per page than this is treated as scanned.
MIN_CHARS_PER_PAGE = 20
# Share of letters that must be Arabic for the document language to be "ar".
ARABIC_LANGUAGE_THRESHOLD = 0.3

_ARABIC_LETTER = re.compile(r"[ؠ-يٱ-ۓ]")
_PRESENTATION_FORM = re.compile(r"[ﭐ-﷿ﹰ-ﻼ]")
_ARABIC_WORD = re.compile(r"[؀-ۿﭐ-﷿ﹰ-ﻼ]{3,}")
_ARABIC_TOKEN = re.compile(r"[؀-ۿﭐ-﷿ﹰ-ﻼ]+")
_SWAPPED_LAM_ALEF = re.compile("ا([اأإآ])ل")
# A document needs at least this many broken markers before it is rejected.
MIN_SWAPPED_MARKERS = 10


class ExtractionError(Exception):
    """Raised when a PDF has no usable text layer or unfixable broken text."""


class ArabicQuality(BaseModel):
    """Arabic extraction diagnostics, measured on the raw (pre-fix) text."""

    arabic_ratio: float  # Arabic letters / all letters
    presentation_form_ratio: float  # presentation-form chars / Arabic chars
    reversed_suspected: bool
    swapped_pairs_suspected: bool = False  # "يف"/"عىل" outnumber "في"/"على"


class PageText(BaseModel):
    page: int  # 1-based page number
    text: str


class ExtractedDocument(BaseModel):
    title: str
    language: Language
    pages: list[PageText]
    arabic: ArabicQuality
    reversed_fixed: bool = False
    lam_alef_fixes: int = 0

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages if p.text)


def normalize(text: str) -> str:
    """NFKC-normalise and tidy whitespace (keeps paragraph breaks)."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("­", "")  # soft hyphen
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def arabic_quality(text: str) -> ArabicQuality:
    """Measure how Arabic the text is and whether it looks broken."""
    letters = sum(1 for ch in text if ch.isalpha())
    arabic = len(_ARABIC_LETTER.findall(text))
    forms = len(_PRESENTATION_FORM.findall(text))
    arabic_total = arabic + forms

    # In normal Arabic many words start with "ال"; reversed text ends them with "لا".
    words = [unicodedata.normalize("NFKC", w) for w in _ARABIC_WORD.findall(text)]
    starts_al = sum(1 for w in words if w.startswith("ال"))
    ends_la = sum(1 for w in words if w.endswith("لا"))

    # "ى" only ever ends a word, so "ىل" (from "لى") and the word "يف" (from "في") only
    # appear when the font maps letter pairs in the wrong order.
    tokens = [unicodedata.normalize("NFKC", t) for t in _ARABIC_TOKEN.findall(text)]
    swapped = sum(1 for t in tokens if t == "يف" or t.endswith("ىل"))
    correct = sum(1 for t in tokens if t == "في" or t.endswith("لى"))

    return ArabicQuality(
        arabic_ratio=arabic_total / letters if letters else 0.0,
        presentation_form_ratio=forms / arabic_total if arabic_total else 0.0,
        reversed_suspected=ends_la >= 3 and ends_la > 2 * starts_al,
        swapped_pairs_suspected=swapped >= MIN_SWAPPED_MARKERS and swapped > correct,
    )


def fix_lam_alef(text: str) -> tuple[str, int]:
    """Swap "ا" + alef-type + "ل" back to "ال" + alef-type; return (text, fixes)."""
    return _SWAPPED_LAM_ALEF.subn(r"ال\1", text)


def reverse_arabic_lines(text: str) -> str:
    """Undo visual-order extraction: reverse every line that contains Arabic letters."""
    return "\n".join(
        line[::-1] if _ARABIC_LETTER.search(line) else line for line in text.split("\n")
    )


_JUNK_TITLE = re.compile(r"(microsoft (word|powerpoint)|\.(docx?|pdf|indd|pptx?)$|^untitled)", re.I)


def clean_title(metadata_title: str | None, fallback: str) -> str:
    """Use the PDF's title unless it is empty or tool-generated junk."""
    title = normalize(metadata_title or "")
    if len(title) < 4 or _JUNK_TITLE.search(title):
        return normalize(fallback)
    return title


def extract_pdf(path: Path) -> ExtractedDocument:
    """Extract normalised per-page text from a born-digital PDF."""
    with pymupdf.open(path) as doc:
        raw_pages = [page.get_text("text") for page in doc]
        title = clean_title((doc.metadata or {}).get("title"), path.stem)

    raw_text = "\n".join(raw_pages)
    if len(raw_text.strip()) < MIN_CHARS_PER_PAGE * max(len(raw_pages), 1):
        raise ExtractionError(f"{path.name}: no usable text layer (scanned PDF? no OCR)")

    quality = arabic_quality(raw_text)
    if quality.swapped_pairs_suspected:
        raise ExtractionError(
            f"{path.name}: Arabic letter pairs are extracted in the wrong order "
            "(e.g. 'يف' instead of 'في'); the PDF's font mapping is broken"
        )
    fix = quality.reversed_suspected
    pages: list[PageText] = []
    lam_alef_fixes = 0
    for i, raw in enumerate(raw_pages, start=1):
        text, fixes = fix_lam_alef(normalize(reverse_arabic_lines(raw) if fix else raw))
        pages.append(PageText(page=i, text=text))
        lam_alef_fixes += fixes
    language: Language = "ar" if quality.arabic_ratio >= ARABIC_LANGUAGE_THRESHOLD else "en"
    return ExtractedDocument(
        title=title,
        language=language,
        pages=pages,
        arabic=quality,
        reversed_fixed=fix,
        lam_alef_fixes=lam_alef_fixes,
    )
