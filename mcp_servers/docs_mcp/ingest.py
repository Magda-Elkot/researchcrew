"""`ingest` CLI: index a folder of PDFs into Qdrant (extract -> chunk -> embed -> store).

Usage: `uv run ingest data/pdfs [--force] [--prune]`. Re-running is safe and cheap:
- each PDF's doc_id comes from its file name, and its old points are replaced;
- a PDF whose fingerprint (file bytes + model + chunk settings) is unchanged is skipped, so
  only new or changed files are embedded (embedding is the CPU-heavy step). --force re-embeds;
- --prune deletes documents whose PDF was removed or renamed.
A PDF that fails (e.g. scanned, broken Arabic font mapping) is logged and skipped.
"""

import argparse
import hashlib
import re
import time
import unicodedata
from pathlib import Path

from pydantic import BaseModel

from app.config import get_settings
from app.log import get_logger
from mcp_servers.docs_mcp.chunking import chunk_pages
from mcp_servers.docs_mcp.embeddings import Embedder, SentenceTransformerEmbedder
from mcp_servers.docs_mcp.extract import ExtractionError, extract_pdf
from mcp_servers.docs_mcp.store import DocStore, DocumentInfo, utc_now

logger = get_logger(__name__)

# Bump when extraction or chunking logic changes, so unchanged PDFs are re-processed once.
PIPELINE_VERSION = "2"  # 2: per-page text stored for get_document page ranges


class IngestResult(BaseModel):
    indexed: list[str]
    skipped: list[str] = []  # unchanged since the last ingest
    pruned: list[str] = []  # in Qdrant but no longer in the folder (only with prune=True)
    failed: dict[str, str]  # file name -> error
    chunks: int
    seconds: float


def make_doc_id(path: Path) -> str:
    """Stable id from the file name: 'WHO Report 2025.pdf' -> 'who-report-2025'."""
    stem = unicodedata.normalize("NFKC", path.stem).lower()
    slug = re.sub(r"[\W_]+", "-", stem).strip("-")
    return slug or "document"


def fingerprint(path: Path) -> str:
    """SHA-256 of the file plus everything that changes the vectors (code, model, chunking)."""
    settings = get_settings()
    digest = hashlib.sha256(path.read_bytes())
    config = (
        f"{PIPELINE_VERSION}|{settings.embedding_model}"
        f"|{settings.chunk_tokens}|{settings.chunk_overlap}"
    )
    digest.update(config.encode())
    return digest.hexdigest()


def ingest_file(path: Path, store: DocStore, embedder: Embedder, content_hash: str) -> DocumentInfo:
    settings = get_settings()
    started = time.perf_counter()
    doc = extract_pdf(path)
    chunks = chunk_pages(doc.pages, embedder, settings.chunk_tokens, settings.chunk_overlap)
    if not chunks:
        raise ExtractionError(f"{path.name}: no text to index")
    vectors = embedder.embed([c.text for c in chunks])
    info = DocumentInfo(
        doc_id=make_doc_id(path),
        title=doc.title,
        language=doc.language,
        source_file=path.name,
        pages=len(doc.pages),
        chunks=len(chunks),
        ingested_at=utc_now(),
        content_hash=content_hash,
        embedding_model=settings.embedding_model,
    )
    store.replace_document(info, [p.text for p in doc.pages], chunks, vectors)
    logger.info(
        "indexed document",
        extra={
            "doc_id": info.doc_id,
            "language": info.language,
            "pages": info.pages,
            "chunks": info.chunks,
            "arabic_ratio": round(doc.arabic.arabic_ratio, 3),
            "presentation_form_ratio": round(doc.arabic.presentation_form_ratio, 3),
            "reversed_fixed": doc.reversed_fixed,
            "lam_alef_fixes": doc.lam_alef_fixes,
            "seconds": round(time.perf_counter() - started, 1),
        },
    )
    return info


def ingest_folder(
    folder: Path,
    store: DocStore,
    embedder: Embedder,
    force: bool = False,
    prune: bool = False,
) -> IngestResult:
    started = time.perf_counter()
    store.ensure_collection()
    result = IngestResult(indexed=[], failed={}, chunks=0, seconds=0.0)
    pdfs = sorted(p for p in folder.iterdir() if p.suffix.lower() == ".pdf")
    if not pdfs:
        logger.warning("no PDFs found", extra={"folder": str(folder)})
    seen: dict[str, str] = {}  # doc_id -> file name
    for path in pdfs:
        doc_id = make_doc_id(path)
        if doc_id in seen:
            error = f"doc_id '{doc_id}' already used by {seen[doc_id]}; rename one of the files"
            logger.error("duplicate doc_id", extra={"file": path.name, "error": error})
            result.failed[path.name] = error
            continue
        seen[doc_id] = path.name
        content_hash = fingerprint(path)
        existing = store.get_info(doc_id)
        if not force and existing is not None and existing.content_hash == content_hash:
            logger.info("unchanged, skipped", extra={"doc_id": existing.doc_id})
            result.skipped.append(existing.doc_id)
            continue
        try:
            info = ingest_file(path, store, embedder, content_hash)
        except Exception as exc:  # one bad PDF must not stop the whole run
            logger.error("failed to index document", extra={"file": path.name, "error": str(exc)})
            result.failed[path.name] = str(exc)
            continue
        result.indexed.append(info.doc_id)
        result.chunks += info.chunks
    if prune:
        for doc in store.list_documents():
            if doc.doc_id not in seen:
                store.delete_document(doc.doc_id)
                logger.info("pruned document", extra={"doc_id": doc.doc_id})
                result.pruned.append(doc.doc_id)
    result.seconds = round(time.perf_counter() - started, 1)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ingest", description="Index a folder of PDFs.")
    parser.add_argument("folder", type=Path, help="folder containing .pdf files")
    parser.add_argument("--force", action="store_true", help="re-embed unchanged files too")
    parser.add_argument(
        "--prune", action="store_true", help="delete indexed documents whose PDF is gone"
    )
    args = parser.parse_args(argv)
    if not args.folder.is_dir():
        parser.error(f"not a folder: {args.folder}")

    settings = get_settings()
    store = DocStore.from_settings(settings)
    embedder = SentenceTransformerEmbedder.from_settings(settings)
    result = ingest_folder(args.folder, store, embedder, force=args.force, prune=args.prune)
    logger.info("ingest finished", extra=result.model_dump())
    return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
