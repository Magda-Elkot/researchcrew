# Phase 2b — Spike: hosting feasibility

**Status:** ✅ done 2026-11-13. The demo container meets small-host limits locally. Hosting finding: HF Docker Spaces need a paid plan (#48), Cloud Run needs a card (#49), so with **free tools only** the demo is a static page + the live system run locally, optionally exposed with a free Cloudflare quick tunnel (#50, SPEC updated). [Back to master plan](PLAN.md)

## Why a spike
The demo host's limits could change the design: one public port, no persistent disk, scale to zero / sleep, small CPUs. The heavy parts (torch, bge-m3, Qdrant) exist after Phase 2, so we check them now, not in Phase 7. Throwaway quality; a **private** service; not the final deployment.

## What was built (`deploy/demo/`)
- One container: docs-mcp + the Qdrant binary (from the pinned `qdrant/qdrant` image, on 127.0.0.1 only) + bge-m3 baked in (downloaded at build time, pinned revision).
- **No runtime ingest:** the indexed collection ships as a Qdrant snapshot, restored at every start.
- Listens on `$PORT` if set, else 7860; built for uid 1000; `HF_HUB_OFFLINE=1`; `EMBEDDING_THREADS=2`.
- `prepare.sh` (assemble the folder), `entrypoint.sh`, `Dockerfile`, `smoke_test.py` (MCP client + timings).

## Measurements (DECISIONS → Measurements)
| | Result |
|---|---|
| Image | 4.13 GB (model 2.29, Python env 1.61) |
| Cold start (2 CPUs) | 9.1 s (16 GB, port 7860) / 8.5 s (4 GB, `PORT=8080`) |
| RAM | 1.15 GB |
| Search latency | median ~104 ms |
| uid 1000 file ownership | OK |

## How to run it locally
```bash
make up && make ingest      # local Qdrant with the indexed collection
make demo-prepare           # assemble deploy/demo/build/space (code + snapshot)
make demo-build             # build the image (downloads bge-m3 once)
make demo-run               # 2 CPUs, 4 GB, uid 1000 on http://localhost:7860
uv run python deploy/demo/smoke_test.py http://localhost:7860/mcp
```

## Optional: free public test link (you run it)
Guide: [learning/07-free-live-demo-guide.md](../learning/07-free-live-demo-guide.md).
```bash
make demo-run                    # terminal 1
make demo-tunnel                 # terminal 2 → prints https://<random>.trycloudflare.com
uv run python deploy/demo/smoke_test.py https://<random>.trycloudflare.com/mcp
```

## Definition of done
The demo container answers MCP searches under small-host limits with numbers recorded (done), and a free hosting approach is decided (done: DECISIONS #50).

## Out of scope
The api, Streamlit, Node, public access.
