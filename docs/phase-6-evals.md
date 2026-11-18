# Phase 6 — Evaluation suite and results

**Status:** built (2026-11-18); pilot done, full eval runs over the coming days (DECISIONS #101–105).
[Back to master plan](PLAN.md)

## Goal
Measure report quality, tool reliability, latency and cost on a fixed question set, for two
configurations, and publish the numbers (`evals/results.md`, Langfuse scores).

## Your decisions (2026-11-18, DECISIONS #98–100)
- **Judge:** Gemini Flash through LiteLLM (`GEMINI_API_KEY`, free AI Studio key; the exact
  model is chosen from your project's free-tier limits). A different provider and model family
  from the generator.
- **Comparison:** sequential vs hierarchical (both gpt-oss-120b, SPEC decision #2). Fallback if
  hierarchical can't finish runs reliably: two generator models (recorded if used).
- **Data:** the dataset is written on the 5 indexed PDFs + `data/notes` now; questions are added
  if you add PDFs before the full run.

## Budget (measured, not guessed)
A quick run is ~45–53K tokens (Phases 3–5: 52.4K, 53.0K, 45.8K, 49.1K, 50.9K). Hierarchical adds
the manager's calls (measured in the pilot). 26 questions × 2 configs ≈ 2.5–3M tokens against
200K tokens/day for gpt-oss-120b ⇒ **~13–16 days** of runs. So the runner is **resumable**:
each (question, config) result is a file in `evals/runs/`, `make eval` skips finished ones,
and it stops cleanly (no failed results saved) when Groq's daily limit is reached.

## Metrics per run
| Metric | How | Where |
|---|---|---|
| Citation coverage | share of report sentences with a valid `[n]` → Citation → kept Evidence chain; sentences split on `. ? ! ؟` and list items; headings and the "no evidence" note skipped | `evals/metrics.py` (pure Python) |
| Faithfulness 1–5 | the judge reads each cited claim with the **raw tool output** its evidence came from (not the snippet) | `evals/judge.py` |
| Completeness 1–5 | the judge reads the report and the question's `expected_aspects` | `evals/judge.py` |
| Tool-call success rate, tool calls per run | the guarded-tool records (executed calls; refused "budget used up" requests counted separately) | `evals/metrics.py` |
| Latency p50/p95, cost per report, tokens | `RunResult` | `evals/report.py` |

## Design
- **`evals/dataset.jsonl`:** 26 questions (15 EN, 11 AR) `{id, question, language, topic,
  expected_aspects: [3–5 key points]}`, each answerable from the indexed documents. Uploaded as a
  Langfuse dataset (`researchcrew-eval`).
- **Raw tool outputs:** `RunResult` gains the run's tool records (tool, ok, output, scope), so the
  judge can check claims against what the tools really returned. The API keeps returning only
  the SPEC fields.
- **`evals/run.py` (`make eval`):** for each config and question not yet in `evals/runs/`:
  `run_research` (traced, environment `eval`, tag `process:<config>`) → metrics → judge → save →
  Langfuse scores on the run's trace (no dataset-run linking, #103). Concurrency 1 by default (one Groq quota);
  judge calls retry with backoff on 429.
- **`evals/report.py`:** `evals/results.md` with one row per config (means, p50/p95, cost, n),
  plus per-question details.
- **Judge model:** `gemini/gemini-3.5-flash-lite`, pinned (#101); completeness computed from per-aspect verdicts (#102); Langfuse dataset + scores, no run linking (#103); `RecoveringLLM` (#104).
- **No Tavily cache** (was planned): web search is rarely used and Tavily's free credits cover
  the whole eval; a cache would add code for nothing.

## Steps
1. Pilot first (cheap): judge + metrics + runner on 2 questions × 2 configs, to measure the
   hierarchical token cost and check it finishes.
2. Dataset (26 questions) + Langfuse dataset upload.
3. Full run over the following days (`make eval` once a day), then `evals/results.md`.

## Tests
Metrics with fixtures (incl. Arabic sentence splitting), judge prompt/answer parsing with the LLM
mocked, resume logic, budget stop, Langfuse score calls mocked.

## Definition of done
`make eval` runs the full dataset for 2 configs and writes evals/results.md.
