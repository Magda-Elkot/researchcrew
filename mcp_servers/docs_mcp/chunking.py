"""Token-based chunking with overlap, keeping page numbers for citations.

Sizes are counted in *model* tokens (the embedder's tokenizer), not characters, because the
model's limits and cost are in tokens and Arabic and English use very different
characters-per-token. A tokenizer is anything that returns the character span of each token,
so tests can use a tiny whitespace stub instead of downloading bge-m3.
"""

from bisect import bisect_right
from typing import Protocol

from pydantic import BaseModel

from mcp_servers.docs_mcp.extract import PageText


class Tokenizer(Protocol):
    def token_spans(self, text: str) -> list[tuple[int, int]]:
        """Return (start, end) character offsets of every token in `text`."""
        ...


class Chunk(BaseModel):
    index: int  # 0-based position in the document
    text: str
    page_start: int  # 1-based page where the chunk starts
    page_end: int  # 1-based page where the chunk ends
    token_count: int


PAGE_SEPARATOR = "\n\n"


def chunk_pages(
    pages: list[PageText], tokenizer: Tokenizer, chunk_tokens: int, overlap: int
) -> list[Chunk]:
    """Split the pages of one document into overlapping token windows."""
    if overlap >= chunk_tokens:
        raise ValueError("overlap must be smaller than chunk_tokens")

    # Join pages into one text and remember where each page starts.
    page_starts: list[int] = []
    page_numbers: list[int] = []
    parts: list[str] = []
    offset = 0
    for page in pages:
        if not page.text:
            continue
        page_starts.append(offset)
        page_numbers.append(page.page)
        parts.append(page.text)
        offset += len(page.text) + len(PAGE_SEPARATOR)
    text = PAGE_SEPARATOR.join(parts)

    spans = tokenizer.token_spans(text)
    if not spans:
        return []

    def page_at(char_offset: int) -> int:
        return page_numbers[max(bisect_right(page_starts, char_offset) - 1, 0)]

    chunks: list[Chunk] = []
    step = chunk_tokens - overlap
    for start in range(0, len(spans), step):
        window = spans[start : start + chunk_tokens]
        char_start, char_end = window[0][0], window[-1][1]
        chunks.append(
            Chunk(
                index=len(chunks),
                text=text[char_start:char_end].strip(),
                page_start=page_at(char_start),
                page_end=page_at(max(char_end - 1, char_start)),
                token_count=len(window),
            )
        )
        if start + chunk_tokens >= len(spans):
            break  # the last window already reached the end
    return chunks
