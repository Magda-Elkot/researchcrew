# Phase 2b — Spike: Hugging Face Space feasibility

**Status:** high-level. This gets a detailed plan when the phase starts. [Back to master plan](PLAN.md)

## Why a spike
The demo host (HF Spaces, free CPU tier) has hard limits that could change the design:
- a single container with one exposed port
- runs as uid 1000
- no persistent disk, and the Space sleeps when idle
- 2 vCPUs

The heavy parts (torch, bge-m3, Qdrant) already exist after Phase 2, so we check them now rather than in Phase 7.
This is throwaway-quality work: a **private** Space. Nothing here is the final deployment.

## Scope
- A minimal combined image: docs-mcp + Qdrant (binary copied from the pinned `qdrant/qdrant` image) + bge-m3 baked in.
- **No runtime ingest:** the collection is built locally and shipped in the image (a Qdrant snapshot, or a storage folder copied in).
- Measure and record in DECISIONS.md:
  - image size and build time
  - cold-start time
  - RAM in use
  - latency of one `search_documents` call
- Confirm file ownership works for uid 1000.

## Definition of done
A search query against the private Space returns results, and the numbers above are recorded.
If any limit fails, I report it with options before Phase 3 starts.

## Out of scope
The api, Streamlit, Node, and public access.
