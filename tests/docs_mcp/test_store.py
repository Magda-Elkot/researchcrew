"""Tests for docs_mcp.store using qdrant-client's in-memory mode (no server, no network)."""

import pytest
from qdrant_client import QdrantClient

from mcp_servers.docs_mcp.chunking import Chunk
from mcp_servers.docs_mcp.store import DocStore, DocumentInfo, point_id, utc_now
from tests.docs_mcp.fakes import FakeEmbedder

EMB = FakeEmbedder()


def _store() -> DocStore:
    store = DocStore(QdrantClient(":memory:"), "documents", EMB.dim)
    store.ensure_collection()
    return store


def _add(store: DocStore, doc_id: str, texts: list[str], language: str = "en") -> None:
    chunks = [
        Chunk(index=i, text=t, page_start=i + 1, page_end=i + 1, token_count=len(t.split()))
        for i, t in enumerate(texts)
    ]
    info = DocumentInfo(
        doc_id=doc_id,
        title=f"Title {doc_id}",
        language=language,  # type: ignore[arg-type]
        source_file=f"{doc_id}.pdf",
        pages=len(texts),
        chunks=len(texts),
        ingested_at=utc_now(),
    )
    store.replace_document(info, texts, chunks, EMB.embed(texts))  # one page per text


def test_point_ids_are_deterministic() -> None:
    assert point_id("doc-a", 0) == point_id("doc-a", 0)
    assert point_id("doc-a", 0) != point_id("doc-a", 1)
    assert point_id("doc-a", 0) != point_id("doc-b", 0)


def test_ensure_collection_is_idempotent() -> None:
    store = _store()
    store.ensure_collection()
    assert store.client.collection_exists("documents")


def test_search_finds_the_most_similar_chunk() -> None:
    store = _store()
    _add(store, "energy", ["solar panels and wind turbines", "hydro power dams"])
    _add(store, "health", ["malaria vaccines for children", "clean water and sanitation"])
    hits = store.search(EMB.embed(["wind turbines and solar"])[0], top_k=2)
    assert hits[0].doc_id == "energy"
    assert hits[0].chunk_index == 0
    assert hits[0].page_start == 1
    assert hits[0].text == "solar panels and wind turbines"
    assert hits[0].score >= hits[1].score
    assert len(hits) == 2


def test_get_document_returns_metadata_and_all_pages() -> None:
    store = _store()
    _add(store, "health", ["first part", "second part"], language="ar")
    doc = store.get_document("health")
    assert doc is not None
    assert doc.title == "Title health"
    assert doc.language == "ar"
    assert (doc.pages, doc.chunks) == (2, 2)
    assert (doc.start_page, doc.end_page, doc.truncated) == (1, 2, False)
    assert doc.text == "[page 1]\nfirst part\n\n[page 2]\nsecond part"


def test_get_document_page_range() -> None:
    store = _store()
    _add(store, "doc", ["one", "two", "three", "four"])
    doc = store.get_document("doc", start_page=2, end_page=3)
    assert doc is not None
    assert doc.text == "[page 2]\ntwo\n\n[page 3]\nthree"
    assert (doc.start_page, doc.end_page, doc.pages) == (2, 3, 4)


def test_get_document_is_capped_and_can_continue() -> None:
    store = _store()
    _add(store, "long", ["a" * 600, "b" * 600, "c" * 600])
    first = store.get_document("long", max_chars=1000)
    assert first is not None
    assert first.truncated
    assert len(first.text) <= 1000
    assert first.end_page == 2  # page 2 was cut short
    rest = store.get_document("long", start_page=first.end_page)
    assert rest is not None
    assert not rest.truncated
    assert rest.text.startswith("[page 2]") and rest.text.endswith("c" * 600)


def test_get_document_end_page_past_the_end_is_clamped() -> None:
    store = _store()
    _add(store, "doc", ["one", "two"])
    doc = store.get_document("doc", start_page=2, end_page=99)
    assert doc is not None
    assert doc.end_page == 2


@pytest.mark.parametrize(("start", "end"), [(0, None), (3, None), (2, 1)])
def test_get_document_rejects_impossible_ranges(start: int, end: int | None) -> None:
    store = _store()
    _add(store, "doc", ["one", "two"])
    with pytest.raises(ValueError, match="invalid page range"):
        store.get_document("doc", start_page=start, end_page=end)


def test_get_unknown_document_returns_none() -> None:
    assert _store().get_document("nope") is None


def test_list_documents_returns_one_entry_per_document() -> None:
    store = _store()
    _add(store, "b-doc", ["x one", "x two", "x three"])
    _add(store, "a-doc", ["y one"])
    docs = store.list_documents()
    assert [d.doc_id for d in docs] == ["a-doc", "b-doc"]
    assert docs[1].chunks == 3


def test_reingest_replaces_old_chunks() -> None:
    store = _store()
    _add(store, "doc", ["old one", "old two", "old three"])
    _add(store, "doc", ["new only"])
    assert store.client.count("documents").count == 1
    doc = store.get_document("doc")
    assert doc is not None
    assert doc.text == "[page 1]\nnew only"


def test_delete_document() -> None:
    store = _store()
    _add(store, "doc", ["text"])
    store.delete_document("doc")
    assert store.list_documents() == []


def test_replace_requires_matching_vectors() -> None:
    store = _store()
    chunk = Chunk(index=0, text="t", page_start=1, page_end=1, token_count=1)
    info = DocumentInfo(
        doc_id="d",
        title="t",
        language="en",
        source_file="d.pdf",
        pages=1,
        chunks=1,
        ingested_at=utc_now(),
    )
    with pytest.raises(ValueError, match="one vector per chunk"):
        store.replace_document(info, ["t"], [chunk], [])
