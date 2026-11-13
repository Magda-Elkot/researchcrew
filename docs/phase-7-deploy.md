# Phase 7 — Deployment and README

**Status:** high-level. This gets a detailed plan when the phase starts. [Back to master plan](PLAN.md)

## Goal
A public demo on Hugging Face Spaces (Docker SDK, free CPU tier) and a polished README.

## Scope
- **Final pass on all Dockerfiles:** multi-stage, non-root, healthchecks. `.env.example` is complete.
- **`Dockerfile.space`:** one combined image, because a Space runs a single container.
  - A small supervisor script starts Qdrant, docs-mcp, the api and Streamlit, which is the only exposed port.
  - At build time or first startup, the sample PDFs are ingested so the demo has data.
  - API keys are set as Space secrets.
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
  - limitations and next steps

## Key files
- `Dockerfile.space`
- `scripts/start_space.sh`
- `README.md`
- `docs/deploy.md`
- `docs/assets/`

## Definition of done
The public demo URL works, and the README has the diagram, results table, screenshot and GIF.

## Open items
- Image size and startup time with bge-m3 + torch on the free CPU tier (16GB RAM).
- You record the GIF and take the screenshot; I'll give exact steps.
