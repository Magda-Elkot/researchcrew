"""Tests for app.language.detect_language."""

import pytest

from app.language import detect_language


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("What does IRENA say about renewable energy jobs in the GCC?", "en"),
        ("ما هي فرص العمل في الطاقة المتجددة في دول الخليج؟", "ar"),
        ("ما هي وظائف IRENA في GCC؟", "ar"),  # mixed: mostly Arabic letters
        ("Explain the term الطاقة in one line", "en"),  # one Arabic word in English text
        ("ﻣﺮﺣﺒﺎ", "ar"),  # Arabic presentation forms (seen in PDFs)
        ("2030?", "en"),  # no letters at all
        ("", "en"),
    ],
)
def test_detect_language(text: str, expected: str) -> None:
    assert detect_language(text) == expected
