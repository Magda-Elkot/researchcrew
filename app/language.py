"""Detect whether a question is Arabic or English, so the report is written in the same language.

A simple script count, no library: a question is Arabic when at least `ARABIC_SHARE` of its
letters are Arabic script. Mixed questions ("ما هي وظائف IRENA في GCC؟") still count as Arabic.
"""

import unicodedata

from app.schemas import Language

ARABIC_SHARE = 0.3

# Unicode blocks that hold Arabic letters (base, supplement, extended-A, presentation forms).
_ARABIC_RANGES = (
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFF),
)


def _is_arabic(char: str) -> bool:
    code = ord(char)
    return any(low <= code <= high for low, high in _ARABIC_RANGES)


def detect_language(text: str) -> Language:
    """Return "ar" if enough of the letters are Arabic, else "en" (also when there are none)."""
    letters = [c for c in text if unicodedata.category(c).startswith("L")]
    if not letters:
        return "en"
    arabic = sum(1 for c in letters if _is_arabic(c))
    return "ar" if arabic / len(letters) >= ARABIC_SHARE else "en"
