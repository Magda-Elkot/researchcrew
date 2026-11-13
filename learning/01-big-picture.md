# 1. The big picture

## What is ResearchCrew?

You ask a research question (in English or Arabic).
A **team of 5 AI agents** works together and gives you a **report with sources**.

Think of a small research office:

| Agent | Job in the office | What it produces |
|---|---|---|
| **Planner** | The manager. Splits the big question into 3–6 smaller questions. | A research plan |
| **Researcher** | Goes to the library and the internet. Collects facts **with their source**. | Evidence |
| **Analyst** | Removes duplicates and decides what to do when two sources disagree. | Key findings |
| **Writer** | Writes the final report with numbered citations `[1]`, `[2]`. | The report |
| **Reviewer** | Checks that every sentence has a source. Can send the report back **once**. | Approve / fix list |

## How do the agents get information? → MCP

An AI model alone only knows what it learned during training. To look things up, it needs **tools**.

**MCP (Model Context Protocol)** is a standard "plug" between AI apps and tools, like USB for devices:
any MCP tool works with any MCP app.

Our Researcher agent will use three MCP servers:

| MCP server | What it gives | Who builds it |
|---|---|---|
| Web search (Tavily) | Search the internet | Ready-made |
| Filesystem | Read our notes in `data/notes/` | Ready-made |
| **docs-mcp** | Search inside our own PDF collection | **We build it (Phase 2)**: the most important part for interviews |

## The whole system (the final goal)

```
 You ──question──▶ Streamlit page ──▶ FastAPI (api)
                                          │ runs
                                          ▼
                         CrewAI: Planner → Researcher → Analyst → Writer → Reviewer
                                              │ calls tools through MCP
                       ┌──────────────────────┼──────────────────────┐
                       ▼                      ▼                      ▼
                 Tavily web search     filesystem (notes)      docs-mcp (ours)
                                                                     │
                                                                     ▼
                                                        Qdrant (vector database)
                                                        with our PDFs inside

 Everything is traced in Langfuse (who did what, how many tokens, how much it cost).
```

## The 7 phases

| Phase | What we build | Status |
|---|---|---|
| 1 | Foundation: project setup, config, logging, data models, Docker, CI | ✅ Done |
| 2 | docs-mcp: our own MCP server that searches PDFs | 🔄 Steps 1–2 of 12 |
| 3 | The 5 CrewAI agents, run from the command line | — |
| 4 | Web API + live progress + simple web page | — |
| 5 | Tracing with Langfuse | — |
| 6 | Measuring quality (evaluation) | — |
| 7 | Public demo on Hugging Face + README | — |

## Important files to know

| File | Purpose |
|---|---|
| `SPEC.md` | **What** we build (the specification). The source of truth. |
| `CLAUDE.md` | **How** we work (rules for Claude: learning mode, no secrets, and so on). |
| `DECISIONS.md` | **Why** we chose something. Every important decision, numbered. |
| `PROGRESS.md` | **Where** we are now. |
| `docs/phase-*.md` | The detailed plan for each phase. |
