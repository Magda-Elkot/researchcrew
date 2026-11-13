"""Text embeddings for docs-mcp: BAAI/bge-m3 dense vectors via sentence-transformers on CPU.

The model is loaded lazily (first use), so importing this module is cheap and tests never
download anything. Vectors are L2-normalised, so cosine similarity equals the dot product.
"""

from typing import TYPE_CHECKING, Any, Protocol

from app.config import Settings
from app.log import get_logger

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = get_logger(__name__)

BATCH_SIZE = 8


class Embedder(Protocol):
    """What docs-mcp needs from an embedding model."""

    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one normalised vector per text."""
        ...

    def token_spans(self, text: str) -> list[tuple[int, int]]:
        """Character spans of the model's tokens (used for chunking)."""
        ...


class SentenceTransformerEmbedder:
    """bge-m3 (or any sentence-transformers model) running on CPU."""

    def __init__(
        self,
        model_name: str,
        dim: int,
        cache_dir: str | None = None,
        threads: int = 0,
    ) -> None:
        self.model_name = model_name
        self.dim = dim
        self.cache_dir = cache_dir
        self.threads = threads
        self._model: SentenceTransformer | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> "SentenceTransformerEmbedder":
        return cls(
            settings.embedding_model,
            settings.embedding_dim,
            settings.model_cache_dir,
            settings.embedding_threads,
        )

    @property
    def model(self) -> "SentenceTransformer":
        if self._model is None:
            import torch
            from sentence_transformers import SentenceTransformer  # heavy import: torch

            if self.threads > 0:
                torch.set_num_threads(self.threads)  # cap CPU use; 0 = all cores
            logger.info(
                "loading embedding model",
                extra={"model": self.model_name, "threads": torch.get_num_threads()},
            )
            model = SentenceTransformer(self.model_name, device="cpu", cache_folder=self.cache_dir)
            actual = model.get_embedding_dimension()
            if actual != self.dim:
                raise ValueError(
                    f"{self.model_name} outputs {actual} dims, but EMBEDDING_DIM={self.dim}"
                )
            self._model = model
        return self._model

    def load(self) -> None:
        """Load the model now (e.g. at server start) instead of on the first request."""
        _ = self.model

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: Any = self.model.encode(
            texts, batch_size=BATCH_SIZE, normalize_embeddings=True, convert_to_numpy=True
        )
        return [[float(x) for x in row] for row in vectors]

    def token_spans(self, text: str) -> list[tuple[int, int]]:
        encoded = self.model.tokenizer(
            text, add_special_tokens=False, return_offsets_mapping=True, verbose=False
        )
        return [(int(s), int(e)) for s, e in encoded["offset_mapping"] if e > s]
