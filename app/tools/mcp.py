"""MCP client connections for the agents: docs-mcp, Tavily web search and the filesystem server.

Each server is described by an `MCPServerSpec` (connection settings + the tools agents may use),
built from settings by a pure function. `open_mcp_tools()` opens the servers with the crewai-tools
`MCPServerAdapter`, keeps the sessions open for the `with` block, and skips a server that fails
to connect (logged), so one broken server never stops a run.

Every tool is wrapped in a `CompactTool` before an agent sees it (DECISIONS #68):
- it shows the LLM only the tool's required arguments (CrewAI sends tool schemas in strict mode,
  where every argument is required; models leave optional ones out and Groq rejects the call);
- it adds fixed arguments the LLM doesn't choose (e.g. `top_k` for document search);
- it shortens the result, so one prompt stays under Groq's free-tier tokens-per-minute limit.
"""

import ast
import json
from collections.abc import Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any

from crewai.tools import BaseTool
from crewai_tools import MCPServerAdapter
from mcp import StdioServerParameters
from pydantic import BaseModel, Field, create_model

from app.config import ConfigError, Settings
from app.log import get_logger

logger = get_logger(__name__)

# Tavily search defaults: basic depth costs 1 credit per search; 5 results keep prompts small.
TAVILY_DEFAULT_PARAMETERS: dict[str, Any] = {"max_results": 5, "search_depth": "basic"}

DOCS_MCP_TOOLS = ("search_documents", "get_document")
TAVILY_TOOLS = ("tavily_search",)  # extract/crawl/research cost more credits
FILESYSTEM_TOOLS = ("read_text_file", "list_directory", "search_files")


@dataclass(frozen=True)
class MCPServerSpec:
    """How to reach one MCP server and which of its tools the agents may use."""

    name: str
    params: StdioServerParameters | dict[str, Any]
    tool_names: tuple[str, ...]
    # Arguments always sent to a tool, hidden from the LLM: {tool name: {argument: value}}.
    fixed_args: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


def docs_mcp_spec(settings: Settings) -> MCPServerSpec:
    """Our own docs-mcp server over streamable HTTP."""
    return MCPServerSpec(
        name="docs-mcp",
        params={"url": settings.docs_mcp_url, "transport": "streamable-http"},
        tool_names=DOCS_MCP_TOOLS,
        fixed_args={
            "search_documents": {"top_k": settings.mcp_search_top_k},
            # Leave ~1000 characters of the result budget for the metadata around the text.
            "get_document": {"max_chars": settings.mcp_max_result_chars - 1000},
        },
    )


def tavily_spec(settings: Settings) -> MCPServerSpec:
    """Tavily's hosted MCP server. The API key travels in a header, never in the URL."""
    if settings.tavily_api_key is None or not settings.tavily_api_key.get_secret_value():
        raise ConfigError("Missing required environment variable: TAVILY_API_KEY")
    headers = {
        "Authorization": f"Bearer {settings.tavily_api_key.get_secret_value()}",
        "DEFAULT_PARAMETERS": json.dumps(TAVILY_DEFAULT_PARAMETERS),
    }
    return MCPServerSpec(
        name="tavily",
        params={"url": settings.tavily_mcp_url, "transport": "streamable-http", "headers": headers},
        tool_names=TAVILY_TOOLS,
    )


def filesystem_spec(settings: Settings) -> MCPServerSpec:
    """The official filesystem server over stdio: pinned, read-only, limited to the notes folder."""
    notes_dir = str(Path(settings.notes_dir).resolve())
    command = settings.filesystem_mcp_command
    server_args = ["--read-only", notes_dir]
    if command == "npx":
        server_args = ["-y", settings.filesystem_mcp_package, *server_args]
    return MCPServerSpec(
        name="filesystem",
        # No `env`: the MCP SDK then passes only a minimal environment (PATH, HOME, ...),
        # so our API keys never reach the Node process.
        params=StdioServerParameters(command=command, args=server_args),
        tool_names=FILESYSTEM_TOOLS,
    )


def default_specs(settings: Settings) -> list[MCPServerSpec]:
    """The three servers the Researcher uses, in a fixed order."""
    return [docs_mcp_spec(settings), tavily_spec(settings), filesystem_spec(settings)]


# --- What the LLM sees: required arguments only, short results ---

TRUNCATED = "…[truncated]"


def required_only_schema(schema: type[BaseModel]) -> type[BaseModel]:
    """A copy of a tool's argument schema without its optional arguments."""
    fields: dict[str, Any] = {
        name: (info.annotation, info)
        for name, info in schema.model_fields.items()
        if info.is_required()
    }
    return create_model(schema.__name__, **fields)


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + TRUNCATED


def _split_items(raw: str) -> list[str]:
    """mcpadapt joins a result with several content items as `str(list_of_texts)`; undo that."""
    if raw.startswith(("['", '["')):
        try:
            value = ast.literal_eval(raw)  # parses Python literals only, never runs code
        except (ValueError, SyntaxError):
            return [raw]
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            return value
    return [raw]


def _shorten_item(item: str, limit: int) -> str:
    """Shorten one item: its `text` field if it is a JSON object (a search hit), else the item."""
    try:
        data = json.loads(item)
    except json.JSONDecodeError:
        return _cut(item, limit)
    if isinstance(data, dict) and isinstance(data.get("text"), str):
        data["text"] = _cut(data["text"], limit)
        # ensure_ascii=False keeps Arabic as letters; \uXXXX escapes would cost many more tokens.
        return json.dumps(data, ensure_ascii=False)
    return _cut(item, limit)


def compact_result(raw: str, max_item_chars: int, max_result_chars: int) -> str:
    """Make a tool result small enough for the LLM.

    A result with several items (e.g. search hits) keeps every item, each with its text cut to
    `max_item_chars`; then the whole result is cut to `max_result_chars`. What remains is
    verbatim text from the tool, so snippets quoted from it can still be checked.
    """
    items = _split_items(raw)
    if len(items) > 1:
        items = [_shorten_item(item, max_item_chars) for item in items]
    return _cut("\n\n".join(items), max_result_chars)


class CompactTool(BaseTool):
    """An MCP tool as the LLM sees it: required arguments, fixed extras, shortened output."""

    inner: BaseTool
    fixed_args: dict[str, Any] = Field(default_factory=dict)
    max_item_chars: int
    max_result_chars: int

    def _run(self, **kwargs: Any) -> str:
        # `inner._run`, not `inner.run`: run() validates against the full schema and fills every
        # optional argument with None, which MCP servers reject ("expected number, received
        # null"). Our own run() has already validated the arguments the LLM may send.
        raw = self.inner._run(**{**kwargs, **self.fixed_args})
        return compact_result(str(raw), self.max_item_chars, self.max_result_chars)


def compact_tool(
    tool: BaseTool,
    fixed_args: Mapping[str, Any],
    max_item_chars: int,
    max_result_chars: int,
) -> CompactTool:
    """Wrap one MCP tool; it keeps its name and description."""
    return CompactTool(
        name=tool.name,
        description=tool.description,
        args_schema=required_only_schema(tool.args_schema),
        inner=tool,
        fixed_args=dict(fixed_args),
        max_item_chars=max_item_chars,
        max_result_chars=max_result_chars,
    )


def _stop(adapter: MCPServerAdapter, name: str) -> None:
    """Close one server; a failure while closing is logged, not raised."""
    try:
        adapter.stop()
    except Exception as exc:
        logger.warning("mcp server stop failed", extra={"server": name, "error": str(exc)})


@contextmanager
def open_mcp_tools(specs: Sequence[MCPServerSpec], settings: Settings) -> Iterator[list[BaseTool]]:
    """Open every server in `specs` and yield their allowed tools, wrapped as `CompactTool`s;
    close them all on exit.

    A server that fails to connect is logged and skipped, so the run continues with the others.
    """
    with ExitStack() as stack:
        tools: list[BaseTool] = []
        for spec in specs:
            started = perf_counter()
            try:
                adapter = MCPServerAdapter(
                    spec.params, *spec.tool_names, connect_timeout=settings.mcp_connect_timeout
                )
            except Exception as exc:
                logger.warning(
                    "mcp server unavailable, skipping",
                    extra={"server": spec.name, "error": str(exc)},
                )
                continue
            stack.callback(_stop, adapter, spec.name)

            server_tools = list(adapter.tools)
            found = {tool.name for tool in server_tools}
            missing = [name for name in spec.tool_names if name not in found]
            if missing:
                logger.warning(
                    "mcp server is missing expected tools",
                    extra={"server": spec.name, "missing": missing},
                )
            logger.info(
                "mcp server connected",
                extra={
                    "server": spec.name,
                    "tools": sorted(found),
                    "connect_ms": round((perf_counter() - started) * 1000),
                },
            )
            tools.extend(
                compact_tool(
                    tool,
                    spec.fixed_args.get(tool.name, {}),
                    settings.mcp_max_item_chars,
                    settings.mcp_max_result_chars,
                )
                for tool in server_tools
            )
        yield tools
