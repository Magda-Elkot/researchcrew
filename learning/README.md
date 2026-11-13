# Learning notes: ResearchCrew

Simple explanations of what we have built so far. Read them in order.

| # | File | What you learn | Time |
|---|---|---|---|
| 1 | [01-big-picture.md](01-big-picture.md) | What the project is and how the parts fit together | 5 min |
| 2 | [02-phase-1-foundation.md](02-phase-1-foundation.md) | Phase 1: tools, config, logging, data models, API, Docker, CI | 20 min |
| 3 | [03-phase-2-docs-mcp.md](03-phase-2-docs-mcp.md) | Phase 2: MCP server, PDF extraction, NFKC, Arabic fixes, chunking, embeddings, Qdrant, ingest, Docker | 30 min |
| 3b | [03b-phase-2b-hosting.md](03b-phase-2b-hosting.md) | Phase 2b: can it be hosted for free? One container, snapshot, cold start, ONNX test, free-only decision | 10 min |
| 4 | [04-glossary.md](04-glossary.md) | Short definitions of every new word | look up as needed |
| 5 | [05-commands.md](05-commands.md) | Every command we used, and what it does | look up as needed |
| 6 | [06-self-check.md](06-self-check.md) | Interview-style questions with answers | 15 min |
| 7 | [07-free-live-demo-guide.md](07-free-live-demo-guide.md) | **How-to (optional, free):** a temporary public link to the demo with a Cloudflare quick tunnel | 15 min |

**Tip:** in VS Code, open a file and press `Ctrl+Shift+V` to see it formatted.

## Where we are (2026-11-13)

```
Phase 1  Foundation ............ DONE, reviewed, pushed, CI green
Phase 2  docs-mcp server ....... DONE, reviewed, pushed, CI green
Phase 2b hosting test .......... DONE (free tools only: static page + local live + optional tunnel)
Phase 3  CrewAI agents ......... not started
Phase 4  API + frontend ........ not started
Phase 5  Langfuse tracing ...... not started
Phase 6  Evaluation ............ not started
Phase 7  Deployment + README ... not started
```

These notes are updated as we finish more steps.
