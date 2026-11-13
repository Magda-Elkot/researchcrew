"""Phase 2b smoke test: connect to a docs-mcp endpoint as a real MCP client and time searches.

Usage:
    uv run python deploy/demo/smoke_test.py http://localhost:7860/mcp
    uv run python deploy/demo/smoke_test.py https://<random>.trycloudflare.com/mcp

For a private service, pass --token-env NAME: the bearer token is read from that environment
variable (never printed).
"""

import argparse
import asyncio
import json
import os
import statistics
import time

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from pydantic import AnyUrl

QUERIES = [
    "solar energy deployment in Saudi Arabia",
    "ما هي أولويات منظمة الصحة العالمية في إقليم شرق المتوسط؟",
    "vaccine production in the region",
    "الطاقة المتجددة في دول الخليج",
    "ethical principles for artificial intelligence",
]


async def run(url: str, headers: dict[str, str]) -> None:
    started = time.perf_counter()
    async with (
        streamablehttp_client(url, headers=headers, timeout=60) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        print(f"connected + initialized in {time.perf_counter() - started:.2f}s")

        tools = [t.name for t in (await session.list_tools()).tools]
        print("tools:", tools)

        listing = await session.read_resource(AnyUrl("docs://list"))
        first = listing.contents[0]
        docs = json.loads(first.text) if hasattr(first, "text") else []
        print("documents:", len(docs))

        timings = []
        for query in QUERIES:
            t = time.perf_counter()
            result = await session.call_tool("search_documents", {"query": query, "top_k": 3})
            timings.append((time.perf_counter() - t) * 1000)
            hits = (result.structuredContent or {}).get("result", [])
            top = f"{hits[0]['doc_id']} p.{hits[0]['page_start']}" if hits else "NO HITS"
            print(f"  {timings[-1]:7.0f} ms  {query[:45]!r:50} -> {top}")
        print(
            f"search latency: median {statistics.median(timings):.0f} ms, "
            f"max {max(timings):.0f} ms (first call includes warm-up)"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url", help="MCP endpoint, e.g. http://localhost:7860/mcp")
    parser.add_argument("--token-env", help="env var holding a bearer token (private service)")
    args = parser.parse_args()
    headers = {}
    if args.token_env:
        token = os.environ.get(args.token_env)
        if not token:
            raise SystemExit(f"environment variable {args.token_env} is not set")
        headers["Authorization"] = f"Bearer {token}"
    asyncio.run(run(args.url, headers))


if __name__ == "__main__":
    main()
