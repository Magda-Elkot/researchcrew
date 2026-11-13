"""Qdrant storage for docs-mcp: one point per chunk in the `documents` collection.

- Point ids are deterministic (uuid5 of doc_id + chunk index), and re-ingesting a document
  first deletes all its points, so ingest is idempotent.
- Chunk 0 of each document also stores the document's metadata and its text per page; it is
  the "document record" used by `get_document` and `docs://list`.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from qdrant_client import QdrantClient, models

from app.config import Settings
from app.schemas import Language
from mcp_servers.docs_mcp.chunking import Chunk

_NAMESPACE = uuid.UUID("6f1c0a52-4d8e-4b8a-9a52-2f6c3d1e7b10")
_DOC_RECORD_FIELDS = ["document", "pages_text"]  # heavy fields on chunk 0, never in search


class DocumentInfo(BaseModel):
    doc_id: str
    title: str
    language: Language
    source_file: str
    pages: int
    chunks: int
    ingested_at: datetime
    content_hash: str = ""  # SHA-256 of the PDF file, to skip unchanged files on re-ingest
    embedding_model: str = ""  # model that produced the vectors


class DocumentDetail(DocumentInfo):
    """A page range of one document. `pages` (inherited) is the document's total page count."""

    start_page: int
    end_page: int  # last page included (possibly cut short when truncated)
    truncated: bool  # True when max_chars cut the text before end_page was complete
    text: str  # each page starts with a "[page N]" marker


class SearchHit(BaseModel):
    doc_id: str
    title: str
    language: Language
    chunk_index: int
    page_start: int
    page_end: int
    score: float
    text: str


def point_id(doc_id: str, chunk_index: int) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{doc_id}:{chunk_index}"))


def _doc_filter(doc_id: str) -> models.Filter:
    return models.Filter(
        must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))]
    )


class DocStore:
    def __init__(self, client: QdrantClient, collection: str, dim: int) -> None:
        self.client = client
        self.collection = collection
        self.dim = dim

    @classmethod
    def from_settings(cls, settings: Settings) -> "DocStore":
        return cls(
            QdrantClient(url=settings.qdrant_url),
            settings.qdrant_collection,
            settings.embedding_dim,
        )

    def ensure_collection(self) -> None:
        """Create the collection (cosine distance) and payload indexes if missing."""
        if self.client.collection_exists(self.collection):
            return
        self.client.create_collection(
            self.collection,
            vectors_config=models.VectorParams(size=self.dim, distance=models.Distance.COSINE),
        )
        for field, schema in [
            ("doc_id", models.PayloadSchemaType.KEYWORD),
            ("chunk_index", models.PayloadSchemaType.INTEGER),
            ("language", models.PayloadSchemaType.KEYWORD),
        ]:
            self.client.create_payload_index(self.collection, field, field_schema=schema)

    def replace_document(
        self,
        info: DocumentInfo,
        pages_text: list[str],
        chunks: list[Chunk],
        vectors: list[list[float]],
    ) -> None:
        """Delete any old points of this document, then upsert the new chunks."""
        if len(chunks) != len(vectors) or not chunks:
            raise ValueError("need one vector per chunk and at least one chunk")
        self.delete_document(info.doc_id)
        doc_payload = info.model_dump(mode="json")
        points = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            payload: dict[str, Any] = {
                "doc_id": info.doc_id,
                "title": info.title,
                "language": info.language,
                "chunk_index": chunk.index,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "text": chunk.text,
            }
            if chunk.index == 0:
                payload |= {"document": doc_payload, "pages_text": pages_text}
            pid = point_id(info.doc_id, chunk.index)
            points.append(models.PointStruct(id=pid, vector=vector, payload=payload))
        self.client.upsert(self.collection, points=points, wait=True)

    def delete_document(self, doc_id: str) -> None:
        self.client.delete(
            self.collection, points_selector=models.FilterSelector(filter=_doc_filter(doc_id))
        )

    def search(self, vector: list[float], top_k: int) -> list[SearchHit]:
        result = self.client.query_points(
            self.collection,
            query=vector,
            limit=top_k,
            with_payload=models.PayloadSelectorExclude(exclude=_DOC_RECORD_FIELDS),
        )
        hits = []
        for point in result.points:
            p = point.payload or {}
            hits.append(
                SearchHit(
                    doc_id=p["doc_id"],
                    title=p["title"],
                    language=p["language"],
                    chunk_index=p["chunk_index"],
                    page_start=p["page_start"],
                    page_end=p["page_end"],
                    score=point.score,
                    text=p["text"],
                )
            )
        return hits

    def get_info(self, doc_id: str) -> DocumentInfo | None:
        """Metadata only (cheap): used by ingest to skip unchanged files."""
        if not self.client.collection_exists(self.collection):
            return None
        points = self.client.retrieve(
            self.collection, ids=[point_id(doc_id, 0)], with_payload=["document"]
        )
        if not points or not points[0].payload:
            return None
        return DocumentInfo(**points[0].payload["document"])

    def get_document(
        self,
        doc_id: str,
        start_page: int = 1,
        end_page: int | None = None,
        max_chars: int = 12_000,
    ) -> DocumentDetail | None:
        """Text of pages start_page..end_page (inclusive), capped at max_chars.

        Returns None for an unknown doc_id; raises ValueError for an impossible page range.
        """
        points = self.client.retrieve(
            self.collection, ids=[point_id(doc_id, 0)], with_payload=_DOC_RECORD_FIELDS
        )
        if not points or not points[0].payload:
            return None
        info = DocumentInfo(**points[0].payload["document"])
        pages: list[str] = points[0].payload["pages_text"]
        last = info.pages if end_page is None else min(end_page, info.pages)
        if start_page < 1 or start_page > info.pages or last < start_page:
            raise ValueError(
                f"invalid page range {start_page}-{end_page}; the document has {info.pages} pages"
            )

        parts: list[str] = []
        used = 0
        truncated = False
        included_last = start_page
        for number in range(start_page, last + 1):
            block = f"[page {number}]\n{pages[number - 1]}"
            if used + len(block) > max_chars:
                parts.append(block[: max(max_chars - used, 0)])
                included_last, truncated = number, True
                break
            parts.append(block)
            used += len(block) + 2
            included_last = number
        return DocumentDetail(
            **info.model_dump(),
            start_page=start_page,
            end_page=included_last,
            truncated=truncated,
            text="\n\n".join(parts),
        )

    def list_documents(self) -> list[DocumentInfo]:
        first_chunks = models.Filter(
            must=[models.FieldCondition(key="chunk_index", match=models.MatchValue(value=0))]
        )
        docs: list[DocumentInfo] = []
        offset: Any = None
        while True:
            points, offset = self.client.scroll(
                self.collection,
                scroll_filter=first_chunks,
                limit=256,
                offset=offset,
                with_payload=["document"],
            )
            docs.extend(DocumentInfo(**(p.payload or {})["document"]) for p in points)
            if offset is None:
                break
        return sorted(docs, key=lambda d: d.doc_id)


def utc_now() -> datetime:
    return datetime.now(UTC)
