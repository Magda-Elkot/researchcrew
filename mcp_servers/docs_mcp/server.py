"""docs-mcp: an MCP server (FastMCP, streamable HTTP) for semantic search over our PDFs.

Exposes:
- tool `search_documents(query, top_k)`: the most similar chunks, with page numbers
- tool `get_document(doc_id, start_page, end_page, max_chars)`: a page range of one document
- resource `docs://list`: every indexed document (JSON)
- HTTP `GET /health` for Docker healthchecks (not part of MCP)

Run: `uv run docs-mcp` (MCP endpoint at http://127.0.0.1:8001/mcp).
"""

import json
from typing import Annotated

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import get_settings
from app.log import get_logger
from mcp_servers.docs_mcp.embeddings import Embedder, SentenceTransformerEmbedder
from mcp_servers.docs_mcp.store import DocStore, DocumentDetail, SearchHit

logger = get_logger(__name__)

INSTRUCTIONS = (
    "Search a curated library of PDF reports (WHO public health, UNESCO AI ethics, IRENA "
    "renewable energy; English and Arabic). Use search_documents to find relevant passages "
    "and cite them by doc_id and page; use get_document for a document's full text; read "
    "docs://list to see which documents exist."
)


def create_server(
    store: DocStore, embedder: Embedder, host: str = "127.0.0.1", port: int = 8001
) -> FastMCP:
    """Build the MCP server around a store and an embedder (fakes in tests, real in main)."""
    mcp = FastMCP("docs-mcp", instructions=INSTRUCTIONS, host=host, port=port)

    @mcp.tool()
    async def search_documents(
        query: Annotated[str, Field(min_length=1, max_length=2000, description="What to look for")],
        top_k: Annotated[int, Field(ge=1, le=20, description="How many passages to return")] = 5,
    ) -> list[SearchHit]:
        """Semantic search over the PDF library (English and Arabic).

        Returns the most relevant passages with doc_id, title, page range and a similarity
        score. Cite a passage by its doc_id and page numbers.
        """

        def run() -> list[SearchHit]:
            return store.search(embedder.embed([query])[0], top_k)

        hits = await anyio.to_thread.run_sync(run)
        logger.info("search_documents", extra={"top_k": top_k, "hits": len(hits)})
        return hits

    @mcp.tool()
    async def get_document(
        doc_id: Annotated[
            str, Field(min_length=1, description="A doc_id from search or docs://list")
        ],
        start_page: Annotated[int, Field(ge=1, description="First page to return")] = 1,
        end_page: Annotated[
            int | None, Field(ge=1, description="Last page to return (default: the last page)")
        ] = None,
        max_chars: Annotated[
            int, Field(ge=1_000, le=50_000, description="Maximum characters of text to return")
        ] = 12_000,
    ) -> DocumentDetail:
        """Read a page range of one document, with its metadata.

        Long reports don't fit in one call: the text is capped at max_chars. When `truncated`
        is true, call again with start_page = end_page (+1 if that page was complete) to
        continue. `pages` is the document's total page count. Each page starts with a
        "[page N]" marker for citations.
        """

        def run() -> DocumentDetail | None:
            return store.get_document(doc_id, start_page, end_page, max_chars)

        try:
            doc = await anyio.to_thread.run_sync(run)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        if doc is None:
            raise ToolError(f"Unknown doc_id: {doc_id}. Read docs://list for valid ids.")
        return doc

    @mcp.resource(
        "docs://list",
        name="document-list",
        description="All indexed documents: doc_id, title, language, pages, chunks.",
        mime_type="application/json",
    )
    async def list_documents() -> str:
        docs = await anyio.to_thread.run_sync(store.list_documents)
        return json.dumps([d.model_dump(mode="json") for d in docs], ensure_ascii=False)

    # FastMCP's custom_route decorator has no type hints; the function itself is fully typed.
    @mcp.custom_route("/health", methods=["GET"])  # type: ignore[untyped-decorator]
    async def health(_: Request) -> Response:
        return JSONResponse({"status": "ok", "version": get_settings().app_version})

    return mcp


def main() -> None:
    settings = get_settings()
    store = DocStore.from_settings(settings)
    store.ensure_collection()
    embedder = SentenceTransformerEmbedder.from_settings(settings)
    embedder.load()  # load bge-m3 at startup so the first search is not slow
    server = create_server(store, embedder, settings.docs_mcp_host, settings.docs_mcp_port)
    logger.info(
        "docs-mcp starting",
        extra={"host": settings.docs_mcp_host, "port": settings.docs_mcp_port, "path": "/mcp"},
    )
    server.run(transport="streamable-http")


if __name__ == "__main__":
    main()
