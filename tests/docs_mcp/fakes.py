"""Test doubles for docs-mcp: a whitespace tokenizer and a deterministic fake embedder.

They let every docs-mcp test run offline, without downloading bge-m3.
"""

import hashlib
import math
import re


class WhitespaceTokenizer:
    """Every run of non-space characters is one token."""

    def token_spans(self, text: str) -> list[tuple[int, int]]:
        return [m.span() for m in re.finditer(r"\S+", text)]


class FakeEmbedder(WhitespaceTokenizer):
    """Bag-of-words hashing embedder: texts sharing words get similar unit vectors."""

    def __init__(self, dim: int = 16) -> None:
        self.dim = dim
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [self._vector(t) for t in texts]

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for word in re.findall(r"\w+", text.lower()):
            bucket = int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dim
            vec[bucket] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]
