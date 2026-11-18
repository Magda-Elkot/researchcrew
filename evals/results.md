# Evaluation results

Status: **in progress: 2 of 52** runs · updated 2026-11-18 22:30 UTC · generator: Groq gpt-oss-120b, quick depth · judge: `gemini/gemini-3.5-flash-lite`

Metrics (DECISIONS #98-103): citation coverage = share of report claims whose [n] markers all resolve to grounded evidence; faithfulness = judge's 1-5 per cited claim against the raw tool output, averaged; completeness = 1-5 computed from the judge's yes/partly/no per expected aspect; tool success = executed tool calls without error.

## By configuration

| Config | Runs | Citation coverage | Faithfulness (1-5) | Completeness (1-5) | Tool success | Tool calls / run | Latency p50 / p95 (s) | Cost / report | Tokens / report |
|---|---|---|---|---|---|---|---|---|---|
| sequential | 1 | 100 % | 4.64 | 1.50 | 100 % | 6.0 | 314 / 314 | $0.0097 | 46,181 |
| hierarchical | 0 (+1 failed) | - | - | - | - | - | - / - | - | - |

## By configuration and language

| Config | Runs | Citation coverage | Faithfulness (1-5) | Completeness (1-5) | Tool success | Tool calls / run | Latency p50 / p95 (s) | Cost / report | Tokens / report |
|---|---|---|---|---|---|---|---|---|---|
| sequential · en | 1 | 100 % | 4.64 | 1.50 | 100 % | 6.0 | 314 / 314 | $0.0097 | 46,181 |
| hierarchical · en | 0 (+1 failed) | - | - | - | - | - | - / - | - | - |

## Per question

| Question | Lang | sequential (cov / faith / compl) | hierarchical (cov / faith / compl) |
|---|---|---|---|
| q01 | en | 100 % / 4.6 / 1.5 | failed |
