"""Tests for app.tools.mcp: server specs, the CompactTool wrapper and opening/closing MCP
connections (no network)."""

import json
import logging
from pathlib import Path
from typing import Any, ClassVar

import pytest
from crewai.tools import BaseTool
from mcp import StdioServerParameters
from pydantic import BaseModel

from app.config import ConfigError, get_settings
from app.tools import mcp as mcp_tools
from app.tools.mcp import (
    TRUNCATED,
    CompactTool,
    MCPServerSpec,
    compact_result,
    compact_tool,
    default_specs,
    docs_mcp_spec,
    filesystem_spec,
    open_mcp_tools,
    required_only_schema,
    tavily_spec,
)

# --- specs (pure functions) ---


def test_docs_mcp_spec_uses_streamable_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCS_MCP_URL", "http://docs-mcp:8001/mcp")
    spec = docs_mcp_spec(get_settings())
    assert spec.name == "docs-mcp"
    assert spec.params == {"url": "http://docs-mcp:8001/mcp", "transport": "streamable-http"}
    assert spec.tool_names == ("search_documents", "get_document")
    assert spec.fixed_args == {
        "search_documents": {"top_k": 3},
        "get_document": {"max_chars": 5000},
    }


def test_docs_mcp_fixed_args_follow_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_SEARCH_TOP_K", "2")
    monkeypatch.setenv("MCP_MAX_RESULT_CHARS", "3000")
    spec = docs_mcp_spec(get_settings())
    assert spec.fixed_args["search_documents"] == {"top_k": 2}
    assert spec.fixed_args["get_document"] == {"max_chars": 2000}


def test_tavily_key_is_in_header_not_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-secret")
    spec = tavily_spec(get_settings())
    assert isinstance(spec.params, dict)
    assert "tvly-secret" not in spec.params["url"]
    assert spec.params["transport"] == "streamable-http"
    assert spec.params["headers"]["Authorization"] == "Bearer tvly-secret"
    defaults = json.loads(spec.params["headers"]["DEFAULT_PARAMETERS"])
    assert defaults == {"max_results": 5, "search_depth": "basic"}
    assert spec.tool_names == ("tavily_search",)


def test_tavily_spec_requires_key() -> None:
    with pytest.raises(ConfigError, match="TAVILY_API_KEY"):
        tavily_spec(get_settings())


def test_filesystem_spec_is_pinned_read_only_and_limited_to_notes(tmp_path: Path) -> None:
    spec = filesystem_spec(get_settings())
    assert isinstance(spec.params, StdioServerParameters)
    assert spec.params.command == "npx"
    assert spec.params.args == [
        "-y",
        "@modelcontextprotocol/server-filesystem@2.3.0",
        "--read-only",
        str(tmp_path / "data" / "notes"),  # conftest runs each test inside tmp_path
    ]
    assert spec.params.env is None  # minimal environment: no API keys for the Node process
    assert set(spec.tool_names) == {"read_text_file", "list_directory", "search_files"}
    assert not {"write_file", "edit_file", "move_file"} & set(spec.tool_names)


def test_filesystem_spec_with_an_installed_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FILESYSTEM_MCP_COMMAND", "mcp-server-filesystem")
    spec = filesystem_spec(get_settings())
    assert isinstance(spec.params, StdioServerParameters)
    assert spec.params.command == "mcp-server-filesystem"
    assert spec.params.args == ["--read-only", str(tmp_path / "data" / "notes")]


def test_default_specs_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-secret")
    assert [s.name for s in default_specs(get_settings())] == ["docs-mcp", "tavily", "filesystem"]


# --- open_mcp_tools (MCPServerAdapter replaced by a fake) ---


class FakeArgs(BaseModel):
    query: str
    limit: int | None = None


class FakeTool(BaseTool):
    """Echoes the arguments it received as JSON."""

    name: str
    description: str = "fake"
    args_schema: type[BaseModel] = FakeArgs

    def _run(self, **kwargs: Any) -> str:
        return json.dumps(kwargs, sort_keys=True)


class FakeAdapter:
    """Mimics MCPServerAdapter: connects in __init__, filters tools by name, stop() closes."""

    available: ClassVar[dict[str, list[str]]] = {}
    failing: ClassVar[set[str]] = set()
    stopped: ClassVar[list[str]] = []
    created: ClassVar[list[tuple[str, tuple[str, ...], int]]] = []

    def __init__(self, params: dict[str, Any], *tool_names: str, connect_timeout: int) -> None:
        self.url = params["url"]
        FakeAdapter.created.append((self.url, tool_names, connect_timeout))
        if self.url in FakeAdapter.failing:
            raise RuntimeError("Failed to initialize MCP Adapter: connection refused")
        names = FakeAdapter.available.get(self.url, [])
        self.tools = [FakeTool(name=n) for n in names if not tool_names or n in tool_names]

    def stop(self) -> None:
        FakeAdapter.stopped.append(self.url)


@pytest.fixture
def fake_adapter(monkeypatch: pytest.MonkeyPatch) -> type[FakeAdapter]:
    FakeAdapter.available = {}
    FakeAdapter.failing = set()
    FakeAdapter.stopped = []
    FakeAdapter.created = []
    monkeypatch.setattr(mcp_tools, "MCPServerAdapter", FakeAdapter)
    return FakeAdapter


def _spec(name: str, *tools: str) -> MCPServerSpec:
    return MCPServerSpec(name=name, params={"url": name}, tool_names=tools)


def test_tools_from_all_servers_and_filtered(
    fake_adapter: type[FakeAdapter], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_CONNECT_TIMEOUT", "7")
    fake_adapter.available = {"a": ["search", "delete"], "b": ["read"]}
    specs = [_spec("a", "search"), _spec("b", "read")]
    with open_mcp_tools(specs, get_settings()) as tools:
        assert [t.name for t in tools] == ["search", "read"]  # "delete" filtered out
        assert all(isinstance(t, CompactTool) for t in tools)
    assert fake_adapter.created == [("a", ("search",), 7), ("b", ("read",), 7)]


def test_opened_tools_get_their_fixed_args(fake_adapter: type[FakeAdapter]) -> None:
    fake_adapter.available = {"a": ["search", "read"]}
    spec = MCPServerSpec(
        name="a",
        params={"url": "a"},
        tool_names=("search", "read"),
        fixed_args={"search": {"limit": 3}},
    )
    with open_mcp_tools([spec], get_settings()) as tools:
        search, read = tools
        assert json.loads(search.run(query="q")) == {"limit": 3, "query": "q"}
        # Optional arguments the LLM can't see are not sent at all, not even as None.
        assert json.loads(read.run(query="q")) == {"query": "q"}


def test_servers_are_stopped_on_exit_even_after_error(fake_adapter: type[FakeAdapter]) -> None:
    fake_adapter.available = {"a": ["x"], "b": ["y"]}
    with (
        pytest.raises(ValueError),
        open_mcp_tools([_spec("a", "x"), _spec("b", "y")], get_settings()),
    ):
        raise ValueError("crew failed")
    assert sorted(fake_adapter.stopped) == ["a", "b"]


def test_failing_server_is_skipped_and_logged(
    fake_adapter: type[FakeAdapter], caplog: pytest.LogCaptureFixture
) -> None:
    fake_adapter.available = {"a": ["x"], "b": ["y"]}
    fake_adapter.failing = {"a"}
    specs = [_spec("a", "x"), _spec("b", "y")]
    with caplog.at_level(logging.WARNING), open_mcp_tools(specs, get_settings()) as tools:
        assert [t.name for t in tools] == ["y"]
    assert "mcp server unavailable, skipping" in caplog.text
    assert fake_adapter.stopped == ["b"]  # the failed one was never opened, so never stopped


def test_missing_expected_tool_is_warned(
    fake_adapter: type[FakeAdapter], caplog: pytest.LogCaptureFixture
) -> None:
    fake_adapter.available = {"a": ["x"]}
    with (
        caplog.at_level(logging.WARNING),
        open_mcp_tools([_spec("a", "x", "renamed")], get_settings()) as tools,
    ):
        assert [t.name for t in tools] == ["x"]
    message = "mcp server is missing expected tools"
    record = next(r for r in caplog.records if r.getMessage() == message)
    assert record.missing == ["renamed"]


def test_stop_failure_is_logged_not_raised(
    fake_adapter: type[FakeAdapter],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_adapter.available = {"a": ["x"]}

    def broken_stop(self: FakeAdapter) -> None:
        raise RuntimeError("already closed")

    monkeypatch.setattr(FakeAdapter, "stop", broken_stop)
    with caplog.at_level(logging.WARNING), open_mcp_tools([_spec("a", "x")], get_settings()):
        pass
    assert "mcp server stop failed" in caplog.text


def test_all_servers_failing_yields_no_tools(fake_adapter: type[FakeAdapter]) -> None:
    fake_adapter.failing = {"a", "b"}
    with open_mcp_tools([_spec("a", "x"), _spec("b", "y")], get_settings()) as tools:
        assert tools == []


# --- CompactTool: what the LLM sees ---


def test_required_only_schema_drops_optional_arguments() -> None:
    schema = required_only_schema(FakeArgs)
    assert list(schema.model_fields) == ["query"]
    assert schema.model_json_schema()["required"] == ["query"]


def test_compact_tool_hides_optional_args_and_sends_fixed_ones() -> None:
    tool = compact_tool(FakeTool(name="search"), {"limit": 3}, 1200, 6000)
    assert tool.name == "search"
    assert tool.description == "fake"
    assert list(tool.args_schema.model_fields) == ["query"]
    assert json.loads(tool.run(query="solar")) == {"limit": 3, "query": "solar"}


def test_compact_tool_never_sends_none_for_hidden_optional_args() -> None:
    # Regression: MCP servers reject null for optional numbers (read_text_file's head/tail).
    tool = compact_tool(FakeTool(name="read"), {}, 1200, 6000)
    assert json.loads(tool.run(query="q", limit=200)) == {"query": "q"}


def test_compact_tool_shortens_the_result() -> None:
    class BigTool(FakeTool):
        def _run(self, **kwargs: Any) -> str:
            return "x" * 5000

    tool = compact_tool(BigTool(name="big"), {}, 200, 2000)
    assert tool.run(query="q") == "x" * 2000 + TRUNCATED


def test_compact_result_keeps_a_short_single_item_unchanged() -> None:
    raw = '{\n  "doc_id": "d1",\n  "text": "short"\n}'
    assert compact_result(raw, 100, 1000) == raw


def test_compact_result_splits_items_and_cuts_each_text() -> None:
    hits = [
        json.dumps({"doc_id": "d1", "page_start": 2, "text": "a" * 50}, indent=2),
        json.dumps({"doc_id": "d2", "page_start": 7, "text": "طاقة متجددة " * 10}, indent=2),
    ]
    out = compact_result(str(hits), 20, 10_000)  # what mcpadapt returns for 2 content items
    first, second = (json.loads(part) for part in out.split("\n\n"))
    assert first == {"doc_id": "d1", "page_start": 2, "text": "a" * 20 + TRUNCATED}
    assert second["doc_id"] == "d2"
    assert second["text"] == ("طاقة متجددة " * 10)[:20] + TRUNCATED
    assert "طاقة" in out  # Arabic stays as letters, not \\uXXXX escapes


def test_compact_result_cuts_plain_text_items() -> None:
    out = compact_result(str(["p" * 30, "q" * 5]), 10, 10_000)
    assert out == "p" * 10 + TRUNCATED + "\n\n" + "q" * 5


def test_compact_result_caps_the_whole_result() -> None:
    out = compact_result("z" * 3000, 100, 2000)  # a single item is only cut by the total cap
    assert out == "z" * 2000 + TRUNCATED


def test_compact_result_treats_list_lookalike_text_as_one_item() -> None:
    raw = "['not a list"
    assert compact_result(raw, 5, 1000) == raw
