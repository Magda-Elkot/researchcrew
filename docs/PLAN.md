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
| Tavily MCP | Tavily's **hosted remote MCP endpoint**, reached over streamable HTTP. Needs no Node. The URL is built in code from `TAVILY_API_KEY`, so a URL containing the key is never stored in config or logged. Basic search only (1 credit). |
| Filesystem MCP | Official server, a **pinned version installed with `npm i -g` at image build time** (no runtime `npx` download), run over stdio inside the api image. Node is added in Phase 3a. Read-only: `./data` is mounted `:ro` and only read tools are exposed to agents. |
| Filesystem MCP purpose | Reads curated Markdown topic notes (glossary, key facts with sources) in `data/notes/`. They're written in Phase 2 alongside the PDFs, and some eval questions depend on them. |
| Extra libraries | sentence-transformers (CPU torch), PyMuPDF, prometheus-client, tenacity |
| Crew architecture | **One Crew with 5 tasks** (sequential process). A thin CrewAI **Flow** wraps it only for the review → rewrite loop (at most 1 rewrite). That keeps the hierarchical variant possible: it's the same Crew with `Process.hierarchical` + `manager_llm`. |
| Second eval config | **Sequential vs hierarchical**. If hierarchical can't reliably finish runs on the free tier, the fallback is **two generator models** on the sequential crew (SPEC allows either). The switch is recorded in DECISIONS.md if it happens. |
| Tool guardrails | One wrapper module (`app/tools/guarded.py`) wraps every MCP tool: per-run call counter, deadline check, retry once (tenacity), `tool_called`/`tool_failed` events, and recording the raw tool output. It's the single source for limits, SSE tool events, the eval tool-success rate and faithfulness evidence. |
| Evidence integrity | An `EvidenceItem.snippet` must be a verbatim substring of a recorded raw tool result (after whitespace/Unicode normalisation), checked in code. Items that fail are dropped and logged. |
| Timeout | Cooperative: the tool wrapper and each task boundary check a per-run deadline. The API marks the job `failed` when the deadline passes, even if the worker thread is still finishing. uvicorn runs with **one worker**. |
| Demo (free only) | **Changed 2026-11-13 (DECISIONS #48–50):** no paid/card hosting. A free static page (HF static Space or GitHub Pages) shows example reports, results, screenshots and a GIF; the live system runs locally with docker compose, optionally exposed temporarily with a free Cloudflare quick tunnel. A daily run limit + example-report fallback still protect the shared API keys when exposed. |
| Free-tier limits | Evidence passed between tasks has a size cap (snippet length, top-N findings). Evals are throttled (configurable concurrency + backoff), **resumable**, and use quick depth. Tavily results are cached per eval question for reruns. |
| Eval size | The SPEC minimum: **25 questions × 2 configs**, quick depth. On Groq's free tier (~100K tokens/day) this is expected to take **several weeks**. |
| Completeness metric | Each dataset line has 3–5 reference `expected_aspects`. Completeness is judged against them; coverage of the Planner's sub-questions is a secondary check. |
| Depth | **quick:** 3 sub-questions, top_k 3, ≤12 tool calls. **deep:** ≤6 sub-questions, top_k 5, ≤25 tool calls. |
| Claim definition | A claim is one sentence in a section body (split on `.`, `?`, `!`, `؟`, and on list items; headings are skipped). It counts as cited if its `[n]` points to a real Citation, and that Citation points to a real EvidenceItem. |
| Token usage & cost | Collected in Phase 3 from CrewAI/LiteLLM usage. Cost is calculated at list price with LiteLLM's price table, even when the free tier bills $0. Langfuse mirrors these numbers; it isn't their source. |
| Tracing timing | Basic Langfuse/OpenInference instrumentation starts in Phase 3b (set up before crewai is imported, one parent span per run). Phase 5 adds tags, the API trace id, cost definitions and polish. |
| API keys | Keys are optional when config is imported, so `/health` and CI work without secrets. The API lifespan and the CLI entry point **fail fast at startup** with an error naming the missing variable. |
| Chunk tokens | Counted with the bge-m3 tokenizer (~800 tokens, ~100 overlap). Tests use a small local tokenizer stub, so there's no network access. |
| Arabic PDFs | Born-digital PDFs only (no OCR). Text is NFKC-normalised, and a check flags PDFs with a high share of Arabic presentation-form characters or reversed text. |
| Dependency layout | `[project.dependencies]` holds only shared, light libraries. `api`, `docs`, `frontend` and `dev` are separate uv dependency groups. Each Dockerfile installs only its group, and CI installs all groups. |
| Python | 3.12 (SPEC says 3.11+; 3.12 is a deliberate pick). mypy is a dev dependency. |

## Cost & licensing — no payment required
- **Open-source libraries and tools (all free):**
  - CrewAI, crewai-tools, MCP SDK, LiteLLM, FastAPI, Pydantic, prometheus-client, tenacity, uv, ruff, mypy and pytest are MIT, Apache or BSD licensed.
  - Streamlit, Qdrant (self-hosted), sentence-transformers and OpenInference are Apache-2.0.
  - The bge-m3 model is MIT.
  - The filesystem MCP server is MIT.
  - PyMuPDF is **AGPL**: free and open source, but copyleft. That's fine for a public repo. The README will name pypdf (BSD) as the permissive alternative.
- **Free tiers of hosted services (API key needed, no card):**
  - Groq: serves Llama 3.3 70B, which is open-weights under the Llama license. The free tier is the main bottleneck (~100K tokens/day; check current limits in the Groq console).
  - Gemini: the judge model.
  - Tavily: about 1,000 credits/month.
  - Langfuse Cloud Hobby: Langfuse itself is MIT and can be self-hosted instead.
  - Hosting: free tools only, no card. HF Docker Spaces need a paid plan and Cloud Run needs a card (DECISIONS #48–50), so the public demo is a static page and the live system runs locally.
  - GitHub Actions: free for public repos.
- **Caveat:** the Brave Search fallback may ask for card verification, so Tavily stays primary.

## Phases
The order differs slightly from SPEC's 7 phases: two short **spikes** (2b, 3a) de-risk the biggest unknowns early.
SPEC's definitions of done are unchanged.

| # | Phase | Plan | Definition of done |
|---|---|---|---|
| 1 | Skeleton, config, Docker, CI | [phase-1-skeleton.md](phase-1-skeleton.md) — **detailed** | `docker compose up` starts api placeholder + Qdrant; `/health` returns 200; CI green |
| 2 | docs-mcp server + ingestion + tests | [phase-2-docs-mcp.md](phase-2-docs-mcp.md) | `ingest` indexes data/pdfs; every tool has passing tests; works in MCP Inspector |
| 2b | Spike: hosting feasibility | [phase-2b-space-spike.md](phase-2b-space-spike.md) | One demo container (docs-mcp + Qdrant + model + snapshot) answers searches under small-host limits; size, RAM, startup recorded; free hosting decision made |
| 3a | Spike: MCP connectivity from CrewAI | [phase-3-crew.md](phase-3-crew.md#phase-3a--mcp-connectivity-spike) | One agent calls docs-mcp, Tavily and filesystem tools from the CLI; adapter lifecycle decided; tokens per call measured |
| 3b | Full crew + Flow + guardrails + CLI | [phase-3-crew.md](phase-3-crew.md#phase-3b--full-crew) | `uv run researchcrew "question"` produces valid Report JSON + Markdown; tokens, cost and a basic trace recorded |
| 4 | FastAPI + SSE + Streamlit | [phase-4-api-ui.md](phase-4-api-ui.md) | POST/GET work; frontend shows live SSE progress and the report |
| 5 | Langfuse tracing (complete) | [phase-5-langfuse.md](phase-5-langfuse.md) | One trace per run with agent, tool and LLM spans, tokens and cost |
| 6 | Evaluation suite | [phase-6-evals.md](phase-6-evals.md) | `make eval` runs the dataset for 2 configs and writes evals/results.md |
| 7 | Deployment + README | [phase-7-deploy.md](phase-7-deploy.md) | Public demo URL works; README has diagram, results, screenshot, GIF |

**Parallel track (needs your approval, starts during Phase 1):** choose the sample PDFs and topic notes, and draft the
eval questions with their `expected_aspects`. Phase 2 and Phase 6 both depend on them.

Phases 2–7 currently hold a high-level plan. Each one is expanded into a detailed plan when its phase
starts, and you review it before any code is written.
