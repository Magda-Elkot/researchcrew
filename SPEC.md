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
1. `docker compose up` starts all services; `/health` returns 200; CI is green.
2. `ingest` indexes data/pdfs; every docs-mcp tool has passing unit tests;
   the server works with the MCP Inspector.
3. `uv run researchcrew "question"` produces a valid Report JSON + Markdown file.
4. POST/GET endpoints work; the frontend shows live SSE progress and the report.
5. One Langfuse trace per run with agent, tool and LLM spans, tokens and cost.
6. `make eval` runs the full dataset for 2 configs and writes evals/results.md.
7. Public demo URL works; README has diagram, results table, screenshot and GIF.
