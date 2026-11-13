# ResearchCrew — Specification

## OVERVIEW
The user asks a research question in Arabic or English. A team of five AI agents works
together to produce a professional report with citations.

- Planner splits the question into 3 to 6 sub-questions.
- Researcher answers each one using tools connected through MCP.
- Analyst removes duplicate information and resolves contradictions.
- Writer produces the final report.
- Reviewer checks that every claim has a source, and can send the report back to the
  Writer once for fixes.

The MCP part is the most important part for interviews: use ready-made MCP servers for
web search and file access, and build my own MCP server in Python, called docs-mcp,
that searches a folder of PDFs stored in Qdrant using a multilingual embedding model
(bge-m3).

---

You are helping me build a portfolio project called "ResearchCrew": a production-style multi-agent research assistant built with CrewAI and the Model Context Protocol (MCP). Work in phases. At the end of each phase, stop, summarise what you built, and wait for me to review before continuing.

## GOAL
The user submits a research question (English or Arabic). A crew of agents plans the research, gathers evidence through MCP tools, analyses it, writes a structured Markdown report with citations, and a reviewer agent quality-checks it before it is returned.

## TECH STACK
- Python 3.11+, uv for dependency management
- CrewAI (hierarchical or sequential process with a manager agent)
- MCP Python SDK: CrewAI connects to MCP servers as tools (use the crewai-tools MCP adapter)
- LLM: provider-agnostic via LiteLLM; default Groq (Llama 3.3 70B), optional OpenAI/Gemini via env vars
- FastAPI backend + a simple Streamlit or HTML frontend
- Pydantic v2 for all agent outputs
- Langfuse for tracing (OpenTelemetry/OpenInference instrumentation for CrewAI)
- Docker + docker-compose, pytest, GitHub Actions

## AGENTS
1. Planner: breaks the question into 3 to 6 sub-questions (Pydantic ResearchPlan).
2. Researcher: answers each sub-question using MCP tools only; returns evidence items with a source URL or document id.
3. Analyst: deduplicates evidence, resolves contradictions, extracts key findings with confidence levels.
4. Writer: produces the final report (title, executive summary, sections, numbered citations).
5. Reviewer: checks every claim has a citation and the report answers the question; can send it back to the Writer once (max 1 revision loop).

## MCP SERVERS
- Use an existing web search MCP server (e.g. Tavily or Brave Search, free API key) and the filesystem MCP server.
- BUILD MY OWN MCP SERVER in Python called docs-mcp using the official MCP SDK (FastMCP). It must expose:
  - tool search_documents(query, top_k): semantic search over a local folder of PDFs indexed in Qdrant with a multilingual embedding model (e.g. BAAI/bge-m3)
  - tool get_document(doc_id): returns full text and metadata
  - resource docs://list listing indexed documents
  - an ingest CLI to index a folder of PDFs
- Run docs-mcp over streamable HTTP transport as its own container. Add unit tests for every tool.

## API
- POST /research {question, depth: quick|deep} returns a job id; GET /research/{id} returns status, report, citations, token usage, cost, latency.
- Run crews as background tasks; stream agent progress events via Server-Sent Events.
- Guardrails: max iterations per agent, timeouts, tool-call limits, graceful errors when a tool fails.

## OBSERVABILITY
- Trace every run in Langfuse: one trace per request, spans per agent, per tool call and per LLM call, with tokens, cost and latency.
- Tag traces with depth, model and app version. Attach evaluation scores to traces.
- Structured JSON logging; /health and /metrics endpoints.

## EVALUATION (folder evals/)
- Dataset of 25 to 30 research questions (mix of English and Arabic) as JSONL, uploaded as a Langfuse dataset.
- Metrics per run:
  - Citation coverage: % of report claims with a valid citation (automatic check)
  - Faithfulness: LLM-as-judge checks each claim against its cited evidence (1 to 5)
  - Completeness: LLM-as-judge checks every sub-question was answered (1 to 5)
  - Tool-call success rate and average tool calls per run
  - Latency p50/p95 and cost per report
- A make eval command runs the dataset, pushes scores to Langfuse and writes evals/results.md with a summary table. Compare at least 2 configurations (e.g. sequential vs hierarchical process, or two models).

## DEPLOYMENT
- Dockerfiles for api, docs-mcp and frontend; docker-compose also starts Qdrant (and optionally self-hosted Langfuse).
- Multi-stage builds, non-root user, healthchecks, .env.example with every variable.
- Deploy instructions for Hugging Face Spaces (Docker SDK) or Google Cloud Run free tier.

## QUALITY
- Structure: app/agents, app/tools, app/api, mcp_servers/docs_mcp, evals/, tests/
- Type hints, ruff, pytest with mocked LLM calls, GitHub Actions running lint + tests on every push.
- README: problem, architecture diagram (Mermaid), agent roles, how MCP is used, setup, eval results table, Langfuse trace screenshot, demo GIF, limitations and next steps.

## PHASES
1. Project skeleton, config, Docker, CI.
2. docs-mcp server + ingestion + tests.
3. CrewAI agents and tasks with MCP tools, CLI run.
4. FastAPI + SSE + frontend.
5. Langfuse tracing.
6. Evaluation suite and results.
7. Deployment and README.

---

## DECISIONS (fixed unless I change them)
- CrewAI process: start with SEQUENTIAL; hierarchical is added in Phase 6 only as
  the second eval configuration.
- Web search MCP: Tavily (fallback: Brave). Filesystem MCP: read-only, limited to ./data.
- Embeddings: BAAI/bge-m3 (dense vectors only, 1024 dims), cosine distance.
- Qdrant collection name: "documents". Chunk size ~800 tokens, overlap ~100.
- Generator model: Groq Llama 3.3 70B. Judge model: a DIFFERENT model
  (e.g. Gemini) to reduce self-grading bias.
- Job storage: SQLite for jobs and results (no Redis/Celery in v1).
- Frontend: Streamlit (single page).
- Observability: Langfuse Cloud (free Hobby plan) by default; self-hosting is optional.
- Demo host: Hugging Face Spaces (Docker SDK).
- Pin all dependency versions in Phase 1; record them in DECISIONS.md.

## NON-GOALS (do not build in v1)
- User accounts/authentication, multi-tenancy, payment
- Kubernetes, Terraform, any paid cloud service
- Fine-tuning or training models
- Real-time collaboration or report editing in the UI

## DATA CONTRACTS (Pydantic v2, in app/schemas.py)
- ResearchPlan: question, language ("en"|"ar"), sub_questions: list[SubQuestion] (3–6)
- SubQuestion: id, text, rationale
- EvidenceItem: id, sub_question_id, claim, snippet, source_type ("web"|"doc"),
  source (URL or doc_id), retrieved_at
- Finding: id, statement, evidence_ids: list[str], confidence ("high"|"medium"|"low")
- Report: title, language, executive_summary, sections: list[Section],
  citations: list[Citation]
- Section: heading, body_markdown (claims use [n] citation markers)
- Citation: number, source, title, evidence_id
- ReviewResult: approved: bool, issues: list[str], uncited_claims: list[str]
- JobStatus: "queued" | "running" | "completed" | "failed"

## SSE EVENT FORMAT
Each event is JSON: {job_id, type, agent, message, timestamp}
type ∈ agent_started | tool_called | tool_failed | agent_finished |
       revision_requested | job_completed | job_failed

## LANGUAGE HANDLING
- Detect the question's language; the report is written in the same language.
- Arabic reports: correct RTL rendering in the frontend; citations stay as [n].
- Test PDF text extraction on at least 2 Arabic PDFs (check for reversed or
  broken letters) before indexing.

## SAMPLE DATA
- data/pdfs/: 10–15 freely licensed PDFs (mix of English and Arabic) on 2–3 topics
  that the eval questions cover. Document the sources in data/SOURCES.md.

## ERROR HANDLING
- A failed tool call is retried once, then logged and skipped; the run continues.
- If all tools fail for a sub-question, the report says so instead of inventing.
- Per-run limits: max 25 tool calls, max 15 min, max 1 review revision.
- Missing API keys produce a clear startup error naming the variable.

## BUDGET
- Target cost per "quick" report: < $0.05 on free tiers; log token usage per run.
- Eval runs must respect free-tier rate limits (configurable concurrency + backoff).

## DEFINITION OF DONE PER PHASE
1. `docker compose up` starts the skeleton services (api placeholder + Qdrant);
   `/health` returns 200; CI is green.
2. `ingest` indexes data/pdfs; every docs-mcp tool has passing unit tests;
   the server works with the MCP Inspector.
3. `uv run researchcrew "question"` produces a valid Report JSON + Markdown file.
4. POST/GET endpoints work; the frontend shows live SSE progress and the report.
5. One Langfuse trace per run with agent, tool and LLM spans, tokens and cost.
6. `make eval` runs the full dataset for 2 configs and writes evals/results.md.
7. Public demo URL works; README has diagram, results table, screenshot and GIF.
