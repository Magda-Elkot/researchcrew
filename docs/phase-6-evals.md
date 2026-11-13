# Phase 6 — Evaluation suite and results

**Status:** high-level. This gets a detailed plan when the phase starts. [Back to master plan](PLAN.md)

## Goal
Measure report quality and cost, comparing 2 configurations: **sequential vs hierarchical** process.

## Scope
- **Dataset:** `evals/dataset.jsonl` with 25–30 questions (English + Arabic) covering the sample PDF topics. It's uploaded as a Langfuse dataset.
- **Metrics per run:**
  - Citation coverage: an automatic check of the share of sentences with a valid `[n]` → Citation → Evidence chain.
  - Faithfulness, scored 1–5: an LLM judge (Gemini, a different model from the generator) checks each claim against its cited evidence.
  - Completeness, scored 1–5: the same judge checks that every sub-question was answered.
  - Tool-call success rate and average tool calls per run.
  - Latency p50/p95 and cost per report.
- **Scores are attached** to the Langfuse traces.
- **`make eval`:**
  - Runs both configs, quick depth by default.
  - Concurrency is configurable, with backoff on 429 responses.
  - **Resumable:** progress is saved per question and config in `evals/runs/`, so a run can span several days within free-tier limits.
  - Writes `evals/results.md` with a summary table.
- **Hierarchical config:** a manager-agent variant, added here only as the second eval configuration.

## Key files
- `evals/{dataset.jsonl, run.py, metrics.py, judge.py, report.py}`

## Tests
- The metrics functions, with fixtures.
- The judge prompt parsing, with the LLM mocked.
- Resume logic.

## Definition of done
`make eval` runs the full dataset for 2 configs and writes evals/results.md.

## Open items
- The full eval needs roughly 60 runs. That likely spans several days on Groq's free tier, which is expected.
