"""Tests for docs_mcp.chunking: token windows, overlap and page tracking."""

import pytest

from mcp_servers.docs_mcp.chunking import chunk_pages
from mcp_servers.docs_mcp.extract import PageText
from tests.docs_mcp.fakes import WhitespaceTokenizer

TOK = WhitespaceTokenizer()


def _words(prefix: str, n: int) -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


def test_short_text_is_one_chunk() -> None:
    chunks = chunk_pages([PageText(page=1, text="a b c")], TOK, chunk_tokens=10, overlap=2)
    assert len(chunks) == 1
    assert chunks[0].text == "a b c"
    assert chunks[0].token_count == 3
    assert (chunks[0].page_start, chunks[0].page_end) == (1, 1)


def test_windows_have_the_right_size_and_overlap() -> None:
    chunks = chunk_pages([PageText(page=1, text=_words("w", 25))], TOK, chunk_tokens=10, overlap=3)
    # starts at tokens 0, 7, 14, 21 -> the last window (21..24) reaches the end
    assert [c.token_count for c in chunks] == [10, 10, 10, 4]
    assert [c.index for c in chunks] == [0, 1, 2, 3]
    first, second = chunks[0].text.split(), chunks[1].text.split()
    assert first[-3:] == second[:3]  # the 3 overlapping tokens


def test_no_tiny_tail_chunk_when_text_fits_exactly() -> None:
    chunks = chunk_pages([PageText(page=1, text=_words("w", 10))], TOK, chunk_tokens=10, overlap=3)
    assert len(chunks) == 1


def test_page_numbers_follow_the_text() -> None:
    pages = [
        PageText(page=1, text=_words("p1_", 6)),
        PageText(page=2, text=""),  # empty pages are skipped
        PageText(page=3, text=_words("p3_", 6)),
    ]
    chunks = chunk_pages(pages, TOK, chunk_tokens=8, overlap=2)
    assert (chunks[0].page_start, chunks[0].page_end) == (1, 3)
    assert (chunks[-1].page_start, chunks[-1].page_end) == (3, 3)


def test_arabic_text_is_chunked() -> None:
    text = "الطاقة المتجددة في العالم العربي تنمو بسرعة كبيرة"
    chunks = chunk_pages([PageText(page=1, text=text)], TOK, chunk_tokens=4, overlap=1)
    assert chunks[0].text == "الطاقة المتجددة في العالم"
    assert chunks[1].text.startswith("العالم")


def test_empty_document_gives_no_chunks() -> None:
    assert chunk_pages([PageText(page=1, text="")], TOK, chunk_tokens=5, overlap=1) == []


def test_overlap_must_be_smaller_than_chunk() -> None:
    with pytest.raises(ValueError, match="overlap"):
        chunk_pages([PageText(page=1, text="a b")], TOK, chunk_tokens=5, overlap=5)
