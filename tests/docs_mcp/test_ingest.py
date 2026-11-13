"""Tests for docs_mcp.ingest: doc ids, folder ingest, idempotency and skipping bad PDFs."""

from pathlib import Path

import pymupdf
import pytest
from qdrant_client import QdrantClient

from app.config import get_settings
from mcp_servers.docs_mcp.extract import clean_title
from mcp_servers.docs_mcp.ingest import fingerprint, ingest_folder, main, make_doc_id
from mcp_servers.docs_mcp.store import DocStore
from tests.docs_mcp.fakes import FakeEmbedder


def _pdf(path: Path, text: str) -> None:
    doc = pymupdf.open()
    if text:
        doc.new_page().insert_text((72, 72), text)
    else:
        doc.new_page()
    doc.save(path)
    doc.close()


def _store(embedder: FakeEmbedder) -> DocStore:
    return DocStore(QdrantClient(":memory:"), "documents", embedder.dim)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("WHO Report 2025.pdf", "who-report-2025"),
        ("irena_renewable-stats.PDF", "irena-renewable-stats"),
        ("تقرير الصحة.pdf", "تقرير-الصحة"),
        ("___.pdf", "document"),
    ],
)
def test_make_doc_id(name: str, expected: str) -> None:
    assert make_doc_id(Path(name)) == expected


@pytest.mark.parametrize(
    ("meta", "expected"),
    [
        ("World Health Statistics 2025", "World Health Statistics 2025"),
        ("Microsoft Word - draft_v3.docx", "fallback"),
        ("report.pdf", "fallback"),
        ("", "fallback"),
        (None, "fallback"),
    ],
)
def test_clean_title(meta: str | None, expected: str) -> None:
    assert clean_title(meta, "fallback") == expected


def test_ingest_folder_indexes_pdfs_and_skips_bad_ones(tmp_path: Path) -> None:
    _pdf(tmp_path / "energy.pdf", "Solar and wind power capacity grew strongly this year.")
    _pdf(tmp_path / "health.pdf", "Vaccines protect children from many serious diseases.")
    _pdf(tmp_path / "scanned.pdf", "")
    (tmp_path / "notes.txt").write_text("not a pdf")
    embedder = FakeEmbedder()
    store = _store(embedder)

    result = ingest_folder(tmp_path, store, embedder)

    assert result.indexed == ["energy", "health"]
    assert list(result.failed) == ["scanned.pdf"]
    assert result.chunks == 2
    assert [d.doc_id for d in store.list_documents()] == ["energy", "health"]


def test_reingest_does_not_duplicate(tmp_path: Path) -> None:
    _pdf(tmp_path / "energy.pdf", "Solar and wind power capacity grew strongly this year.")
    embedder = FakeEmbedder()
    store = _store(embedder)
    ingest_folder(tmp_path, store, embedder)
    ingest_folder(tmp_path, store, embedder)
    assert store.client.count("documents").count == 1


def test_main_rejects_missing_folder(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main([str(tmp_path / "missing")])


def test_unchanged_files_are_skipped_and_changed_ones_reindexed(tmp_path: Path) -> None:
    _pdf(tmp_path / "energy.pdf", "Solar and wind power capacity grew strongly this year.")
    _pdf(tmp_path / "health.pdf", "Vaccines protect children from many serious diseases.")
    embedder = FakeEmbedder()
    store = _store(embedder)
    ingest_folder(tmp_path, store, embedder)
    calls_after_first = embedder.calls

    second = ingest_folder(tmp_path, store, embedder)
    assert second.indexed == []
    assert second.skipped == ["energy", "health"]
    assert embedder.calls == calls_after_first  # nothing re-embedded

    _pdf(tmp_path / "health.pdf", "Clean water and sanitation prevent many diseases.")
    third = ingest_folder(tmp_path, store, embedder)
    assert third.indexed == ["health"]
    assert third.skipped == ["energy"]


def test_force_reembeds_everything(tmp_path: Path) -> None:
    _pdf(tmp_path / "energy.pdf", "Solar and wind power capacity grew strongly this year.")
    embedder = FakeEmbedder()
    store = _store(embedder)
    ingest_folder(tmp_path, store, embedder)
    again = ingest_folder(tmp_path, store, embedder, force=True)
    assert again.indexed == ["energy"]
    assert again.skipped == []


def test_fingerprint_changes_with_chunk_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "a.pdf"
    _pdf(pdf, "Some text that is long enough for the check.")
    before = fingerprint(pdf)
    monkeypatch.setenv("CHUNK_TOKENS", "500")
    get_settings.cache_clear()
    assert fingerprint(pdf) != before


def test_prune_removes_documents_whose_pdf_is_gone(tmp_path: Path) -> None:
    _pdf(tmp_path / "old-name.pdf", "Solar and wind power capacity grew strongly this year.")
    embedder = FakeEmbedder()
    store = _store(embedder)
    ingest_folder(tmp_path, store, embedder)
    (tmp_path / "old-name.pdf").rename(tmp_path / "new-name.pdf")

    kept = ingest_folder(tmp_path, store, embedder)  # without --prune the old copy stays
    assert [d.doc_id for d in store.list_documents()] == ["new-name", "old-name"]
    assert kept.pruned == []

    pruned = ingest_folder(tmp_path, store, embedder, prune=True)
    assert pruned.pruned == ["old-name"]
    assert [d.doc_id for d in store.list_documents()] == ["new-name"]


def test_duplicate_doc_ids_are_reported_not_overwritten(tmp_path: Path) -> None:
    _pdf(tmp_path / "a b.pdf", "Solar and wind power capacity grew strongly this year.")
    _pdf(tmp_path / "a-b.pdf", "Vaccines protect children from many serious diseases.")
    embedder = FakeEmbedder()
    store = _store(embedder)
    result = ingest_folder(tmp_path, store, embedder)
    assert result.indexed == ["a-b"]  # "a b.pdf" sorts first and keeps the id
    assert list(result.failed) == ["a-b.pdf"]
    assert "already used by a b.pdf" in result.failed["a-b.pdf"]


def test_fingerprint_includes_pipeline_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "a.pdf"
    _pdf(pdf, "Some text that is long enough for the check.")
    before = fingerprint(pdf)
    monkeypatch.setattr("mcp_servers.docs_mcp.ingest.PIPELINE_VERSION", "999")
    assert fingerprint(pdf) != before
