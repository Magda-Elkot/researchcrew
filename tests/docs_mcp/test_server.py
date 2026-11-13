"""Tests for the docs-mcp server, through a real MCP client session (in memory).

The embedder is a fake and Qdrant runs in-memory, so no model download and no network.
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import TextResourceContents
from pydantic import AnyUrl
from qdrant_client import QdrantClient
from starlette.testclient import TestClient

from app import __version__
from mcp_servers.docs_mcp.chunking import Chunk
from mcp_servers.docs_mcp.server import create_server
from mcp_servers.docs_mcp.store import DocStore, DocumentInfo, utc_now
from tests.docs_mcp.fakes import FakeEmbedder


def _seeded_store(embedder: FakeEmbedder) -> DocStore:
    store = DocStore(QdrantClient(":memory:"), "documents", embedder.dim)
    store.ensure_collection()
    docs = {
        "irena-energy": ("en", ["solar and wind power capacity grew", "grid storage batteries"]),
        "who-health-ar": ("ar", ["الصحة العامة واللقاحات", "المياه النظيفة"]),
    }
    for doc_id, (lang, texts) in docs.items():
        chunks = [
            Chunk(index=i, text=t, page_start=i + 1, page_end=i + 1, token_count=3)
            for i, t in enumerate(texts)
        ]
        info = DocumentInfo(
            doc_id=doc_id,
            title=doc_id.upper(),
            language=lang,  # type: ignore[arg-type]
            source_file=f"{doc_id}.pdf",
            pages=2,
            chunks=2,
            ingested_at=utc_now(),
        )
        store.replace_document(info, texts, chunks, embedder.embed(texts))
    return store


@asynccontextmanager
async def _client() -> AsyncIterator[ClientSession]:
    embedder = FakeEmbedder()
    server = create_server(_seeded_store(embedder), embedder)
    async with create_connected_server_and_client_session(server) as session:
        yield session


async def test_lists_two_tools_and_the_resource() -> None:
    async with _client() as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        resources = [str(r.uri) for r in (await client.list_resources()).resources]
    assert set(tools) == {"search_documents", "get_document"}
    top_k = tools["search_documents"].inputSchema["properties"]["top_k"]
    assert (top_k["minimum"], top_k["maximum"], top_k["default"]) == (1, 20, 5)
    assert tools["search_documents"].description
    assert resources == ["docs://list"]


async def test_search_documents_returns_ranked_hits_with_pages() -> None:
    async with _client() as client:
        result = await client.call_tool("search_documents", {"query": "wind and solar", "top_k": 2})
    assert not result.isError
    assert result.structuredContent is not None
    hits: list[dict[str, Any]] = result.structuredContent["result"]
    assert len(hits) == 2
    assert hits[0]["doc_id"] == "irena-energy"
    assert hits[0]["page_start"] == 1
    assert hits[0]["score"] >= hits[1]["score"]
    assert "pages_text" not in hits[0]
    assert "document" not in hits[0]


async def test_search_documents_validates_arguments() -> None:
    async with _client() as client:
        empty = await client.call_tool("search_documents", {"query": ""})
        too_many = await client.call_tool("search_documents", {"query": "x", "top_k": 50})
    assert empty.isError
    assert too_many.isError


async def test_get_document_returns_pages_with_markers() -> None:
    async with _client() as client:
        result = await client.call_tool("get_document", {"doc_id": "who-health-ar"})
    assert not result.isError
    doc = result.structuredContent
    assert doc is not None
    assert doc["language"] == "ar"
    assert doc["text"].startswith("[page 1]")
    assert "اللقاحات" in doc["text"]
    assert (doc["start_page"], doc["end_page"], doc["truncated"]) == (1, 2, False)


async def test_get_document_page_range_and_bad_range() -> None:
    async with _client() as client:
        page2 = await client.call_tool("get_document", {"doc_id": "who-health-ar", "start_page": 2})
        bad = await client.call_tool("get_document", {"doc_id": "who-health-ar", "start_page": 9})
        tiny = await client.call_tool("get_document", {"doc_id": "x", "max_chars": 10})
    assert page2.structuredContent is not None
    assert page2.structuredContent["text"] == "[page 2]\nالمياه النظيفة"
    assert bad.isError
    assert "invalid page range" in json.dumps(bad.model_dump(mode="json"), ensure_ascii=False)
    assert tiny.isError  # max_chars below the 1000 minimum


async def test_get_unknown_document_is_a_tool_error() -> None:
    async with _client() as client:
        result = await client.call_tool("get_document", {"doc_id": "nope"})
    assert result.isError
    assert "Unknown doc_id" in json.dumps(result.model_dump(mode="json"))


async def test_docs_list_resource() -> None:
    async with _client() as client:
        result = await client.read_resource(AnyUrl("docs://list"))
    content = result.contents[0]
    assert isinstance(content, TextResourceContents)
    assert content.mimeType == "application/json"
    docs = json.loads(content.text)
    assert [d["doc_id"] for d in docs] == ["irena-energy", "who-health-ar"]
    assert docs[1]["language"] == "ar"


def test_health_route() -> None:
    embedder = FakeEmbedder()
    server = create_server(_seeded_store(embedder), embedder)
    with TestClient(server.streamable_http_app()) as http:
        response = http.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}
