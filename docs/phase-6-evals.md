# Phase 6 — Evaluation suite and results

**Status:** high-level. This gets a detailed plan when the phase starts. [Back to master plan](PLAN.md)

## Goal
Measure report quality and cost, comparing 2 configurations: **sequential vs hierarchical** process.

**Fallback:** if the hierarchical config can't reliably finish runs (the manager's delegation fails or loops on the free tier),
switch to **two generator models** on the sequential crew. SPEC allows either. The switch and its reason are recorded in DECISIONS.md.

## Scope
- **Dataset:** `evals/dataset.jsonl` with **25 questions** (the SPEC minimum; English + Arabic) covering the sample PDF and notes topics. It's drafted on the parallel track during Phase 1 and uploaded as a Langfuse dataset. Each line is:
  `{id, question, language, expected_aspects: [3–5 reference key points]}`
- **Metrics per run:**
  - Citation coverage: an automatic check of the share of claims with a valid `[n]` → Citation → Evidence chain. Claims are split on `.`, `?`, `!`, `؟` and list items; headings are skipped.
  - Faithfulness, scored 1–5: an LLM judge (Gemini, a different model from the generator) checks each claim against the **raw tool output** behind its cited evidence, not against the LLM-written snippet.
  - Completeness, scored 1–5: the same judge checks the report against the dataset's `expected_aspects`. Coverage of the Planner's sub-questions is a secondary check.
  - Tool-call success rate and average tool calls per run, taken from the guarded-tool records.
  - Latency p50/p95 and cost per report.
- **Scores are attached** to the Langfuse traces.
- **`make eval`:**
  - Runs both configs at quick depth.
  - Concurrency is configurable, with backoff on 429 responses.
  - **Resumable:** progress is saved per question and config in `evals/runs/`, so a run can span several weeks within free-tier limits.
  - **Tavily cache:** results are cached per eval question, so reruns don't spend credits.
  - Writes `evals/results.md` with a summary table.
- **Hierarchical config:** built by the Phase 3b crew factory with `Process.hierarchical` + `manager_llm`. Same agents and tasks.

## Key files
- `evals/{dataset.jsonl, run.py, metrics.py, judge.py, report.py}`

## Tests
- The metrics functions, with fixtures (including Arabic sentence splitting).
- The judge prompt parsing, with the LLM mocked.
- Resume logic.

## Definition of done
`make eval` runs the full dataset for 2 configs and writes evals/results.md.

## Open items
- 25 questions × 2 configs = 50 runs. At ~30–80K tokens per quick run against ~100K tokens/day on Groq's free tier, that is expected to take **several weeks**. The Phase 3b token measurements will give a firmer estimate.
- Gemini free-tier limits for the judge (checked when the phase starts).
