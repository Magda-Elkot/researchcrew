# Phase 7 — Deployment and README

**Status:** high-level. This gets a detailed plan when the phase starts. [Back to master plan](PLAN.md)

## Goal
A public demo on Hugging Face Spaces (Docker SDK, free CPU tier) and a polished README.
It builds on the Phase 2b spike results.

## Scope
- **Final pass on all Dockerfiles:** multi-stage, non-root, healthchecks. `.env.example` is complete.
- **`Dockerfile.space`:** one combined image, because a Space runs a single container.
  - A small supervisor script starts Qdrant, docs-mcp, the api and Streamlit, which is the only exposed port.
  - Files are owned by uid 1000 (the user HF runs the container as).
  - **No runtime ingest:** the pre-built Qdrant collection and the bge-m3 model are baked into the image (approach proven in Phase 2b).
  - SQLite job history is temporary: it's lost when the Space restarts or sleeps. This is documented as a limitation.
  - API keys are set as Space secrets.
- **Protecting the shared keys** (there's no auth, which is a SPEC non-goal):
  - a global daily run limit and a per-client cooldown, both configurable
  - when the limit is reached, the UI shows pre-generated example reports (EN + AR) instead of starting a run
- **Deploy instructions:** in `docs/deploy.md`.
- **README:**
  - the problem
  - a Mermaid architecture diagram
  - agent roles
  - how MCP is used (ready-made and custom servers)
  - setup
  - the eval results table
  - a Langfuse trace screenshot
  - a demo GIF
  - limitations and next steps (including the free-tier limits, temporary storage, and PyMuPDF's AGPL licence with pypdf as the alternative)

## Key files
- `Dockerfile.space`
- `scripts/start_space.sh`
- `README.md`
- `docs/deploy.md`
- `docs/assets/`
- `examples/` (pre-generated reports)

## Definition of done
The public demo URL works, and the README has the diagram, results table, screenshot and GIF.

## Open items
- You record the GIF and take the screenshot; I'll give exact steps.
