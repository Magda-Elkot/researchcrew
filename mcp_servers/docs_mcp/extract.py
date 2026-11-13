"""PDF text extraction for docs-mcp: PyMuPDF + NFKC normalisation + an Arabic quality check.

Only born-digital PDFs are supported (no OCR). Arabic text is checked for two known
extraction problems:
- presentation forms (U+FB50-U+FDFF, U+FE70-U+FEFF): glyph shapes instead of letters.
  NFKC maps them back to the base letters.
- visual (reversed) order: words come out backwards, so the article "ال" appears as
  "لا" at the end of words. Detected heuristically and fixed by reversing Arabic lines.
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


class ExtractionError(Exception):
    """Raised when a PDF has no usable text layer."""


class ArabicQuality(BaseModel):
    """Arabic extraction diagnostics, measured on the raw (pre-NFKC) text."""

    arabic_ratio: float  # Arabic letters / all letters
    presentation_form_ratio: float  # presentation-form chars / Arabic chars
    reversed_suspected: bool


class PageText(BaseModel):
    page: int  # 1-based page number
    text: str


class ExtractedDocument(BaseModel):
    title: str
    language: Language
    pages: list[PageText]
    arabic: ArabicQuality
    reversed_fixed: bool = False

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

    return ArabicQuality(
        arabic_ratio=arabic_total / letters if letters else 0.0,
        presentation_form_ratio=forms / arabic_total if arabic_total else 0.0,
        reversed_suspected=ends_la >= 3 and ends_la > 2 * starts_al,
    )


def reverse_arabic_lines(text: str) -> str:
    """Undo visual-order extraction: reverse every line that contains Arabic letters."""
    return "\n".join(
        line[::-1] if _ARABIC_LETTER.search(line) else line for line in text.split("\n")
    )


def extract_pdf(path: Path) -> ExtractedDocument:
    """Extract normalised per-page text from a born-digital PDF."""
    with pymupdf.open(path) as doc:
        raw_pages = [page.get_text("text") for page in doc]
        title = (doc.metadata or {}).get("title") or path.stem

    raw_text = "\n".join(raw_pages)
    if len(raw_text.strip()) < MIN_CHARS_PER_PAGE * max(len(raw_pages), 1):
        raise ExtractionError(f"{path.name}: no usable text layer (scanned PDF? no OCR)")

    quality = arabic_quality(raw_text)
    fix = quality.reversed_suspected
    pages = [
        PageText(page=i, text=normalize(reverse_arabic_lines(raw) if fix else raw))
        for i, raw in enumerate(raw_pages, start=1)
    ]
    language: Language = "ar" if quality.arabic_ratio >= ARABIC_LANGUAGE_THRESHOLD else "en"
    return ExtractedDocument(
        title=normalize(title),
        language=language,
        pages=pages,
        arabic=quality,
        reversed_fixed=fix,
    )
