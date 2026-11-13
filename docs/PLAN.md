# ResearchCrew — Master Plan

> Source of truth for scope: [../SPEC.md](../SPEC.md). This plan explains how we build it.
> Work goes one phase at a time. Each phase stops for review before the next one starts.

## Context
ResearchCrew is a portfolio project: a multi-agent research assistant built with CrewAI and MCP.
A user asks a research question in English or Arabic. Five agents (Planner, Researcher, Analyst,
Writer, Reviewer) produce a cited Markdown report. MCP is the centrepiece:
- **Ready-made servers:** Tavily web search and the filesystem server.
- **Our own server:** `docs-mcp`, built in Python with FastMCP. It does semantic search over local PDFs stored in Qdrant, using bge-m3 embeddings.

## Resolved decisions
These supplement the DECISIONS section of SPEC.md. They are also recorded in [../DECISIONS.md](../DECISIONS.md).

| Topic | Decision |
|---|---|
| Tavily MCP | Tavily's **hosted remote MCP endpoint**, reached over streamable HTTP. Needs no Node. |
| Filesystem MCP | Official server run with `npx` over stdio inside the api image. Node is added in Phase 3. Read-only: `./data` is mounted `:ro` and only read tools are exposed to agents. |
| Extra libraries | sentence-transformers (CPU torch), PyMuPDF, prometheus-client, tenacity |
| HF Spaces deploy | Separate `Dockerfile.space`: one combined image, with a small supervisor script running api + docs-mcp + Streamlit + Qdrant. docker-compose stays multi-container. |
| Free-tier limits | Evals are throttled (configurable concurrency + backoff) and **resumable**. They default to quick depth. |
| Depth | **quick:** 3 sub-questions, top_k 3, ≤12 tool calls. **deep:** ≤6 sub-questions, top_k 5, ≤25 tool calls. |
| Revision loop | A CrewAI **Flow** wraps the crew: plan → research → analyse → write → review, with at most 1 rewrite. |
| Claim definition | A claim is one sentence in a section body. It counts as cited if its `[n]` points to a real Citation, and that Citation points to a real EvidenceItem. |
| Cost | Calculated at list price using LiteLLM's price table, even when the free tier bills $0. |
| Filesystem MCP purpose | Reads plain-text/Markdown notes in `data/notes/`. |
| Chunk tokens | Counted with the bge-m3 tokenizer (~800 tokens, ~100 overlap). |
| Python | 3.12. mypy is a dev dependency. |

## Cost & licensing — no payment required
- **Open-source libraries and tools (all free):**
  - CrewAI, crewai-tools, MCP SDK, LiteLLM, FastAPI, Pydantic, prometheus-client, tenacity, uv, ruff, mypy and pytest are MIT, Apache or BSD licensed.
  - Streamlit, Qdrant (self-hosted), sentence-transformers and OpenInference are Apache-2.0.
  - The bge-m3 model is MIT.
  - The filesystem MCP server is MIT.
  - PyMuPDF is **AGPL**: free and open source, but copyleft. That's fine for a public repo.
- **Free tiers of hosted services (API key needed, no card):**
  - Groq: serves Llama 3.3 70B, which is open-weights under the Llama license.
  - Gemini: the judge model.
  - Tavily: about 1,000 credits/month.
  - Langfuse Cloud Hobby: Langfuse itself is MIT and can be self-hosted instead.
  - Hugging Face Spaces: CPU basic tier.
  - GitHub Actions: free for public repos.
- **Caveat:** the Brave Search fallback may ask for card verification, so Tavily stays primary.

## Phases
| # | Phase | Plan | Definition of done (from SPEC) |
|---|---|---|---|
| 1 | Skeleton, config, Docker, CI | [phase-1-skeleton.md](phase-1-skeleton.md) — **detailed** | `docker compose up` starts api placeholder + Qdrant; `/health` returns 200; CI green |
| 2 | docs-mcp server + ingestion + tests | [phase-2-docs-mcp.md](phase-2-docs-mcp.md) | `ingest` indexes data/pdfs; every tool has passing tests; works in MCP Inspector |
| 3 | CrewAI agents + MCP tools + CLI | [phase-3-crew.md](phase-3-crew.md) | `uv run researchcrew "question"` produces valid Report JSON + Markdown |
| 4 | FastAPI + SSE + Streamlit | [phase-4-api-ui.md](phase-4-api-ui.md) | POST/GET work; frontend shows live SSE progress and the report |
| 5 | Langfuse tracing | [phase-5-langfuse.md](phase-5-langfuse.md) | One trace per run with agent, tool and LLM spans, tokens and cost |
| 6 | Evaluation suite | [phase-6-evals.md](phase-6-evals.md) | `make eval` runs the dataset for 2 configs and writes evals/results.md |
| 7 | Deployment + README | [phase-7-deploy.md](phase-7-deploy.md) | Public demo URL works; README has diagram, results, screenshot, GIF |

Phases 2–7 currently hold a high-level plan. Each one is expanded into a detailed plan when its phase
starts, and you review it before any code is written.
