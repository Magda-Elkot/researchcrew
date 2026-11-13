# 3b. Phase 2b: hosting test (spike): can it be hosted for free?

**Question we answered:** can docs-mcp (the model, Qdrant and the search) run on **Hugging Face's
free hosting**? We checked **now** instead of in Phase 7, because the model and Qdrant are the
heaviest parts. A **spike** is a short experiment to remove a risk early. It's not the final version.

**Answer:** technically yes (it fits small hosts easily), but **no free no-card host can run it**, so the public demo is a free static page and the live system runs locally (section 6).

## 1. What is a Hugging Face Space?

A **Space** is a free web app hosted by Hugging Face. With the **Docker SDK**, you give it a
`Dockerfile` and HF builds and runs your container.

The free CPU tier has **hard limits**:

| Limit | What it means for us |
|---|---|
| 2 vCPUs | Embedding is slow, so no ingest at runtime, and `EMBEDDING_THREADS=2` |
| 16 GB RAM | bge-m3 + Qdrant must fit |
| **One** exposed port (7860) | docs-mcp listens on 7860; Qdrant stays inside (127.0.0.1) |
| Runs as **uid 1000** | Files must be owned by user 1000, or writing fails |
| **No persistent disk**, sleeps when idle | Everything is rebuilt at every start, so it must start fast |

## 2. Our design: everything in ONE container

```
┌──────────────── one container (port 7860) ────────────────┐
│ entrypoint.sh                                              │
│   1. start Qdrant (only 127.0.0.1) + restore the snapshot  │
│   2. wait until Qdrant is ready                            │
│   3. start docs-mcp on 0.0.0.0:7860                        │
│                                                            │
│ baked into the image:                                      │
│   • bge-m3 model (2.29 GB)                                 │
│   • Qdrant program (98 MB, copied from the official image) │
│   • snapshot of our 230 chunks (14 MB)                     │
└────────────────────────────────────────────────────────────┘
```

| Word | Meaning |
|---|---|
| **Snapshot** | A file that contains a whole Qdrant collection. We make it from your local Qdrant, ship it in the image, and Qdrant **restores** it at start (2 s). So no ingest on the slow 2 CPUs. |
| **Baked in** | Stored inside the image, not downloaded when it runs. The Space never needs the internet. |
| **Cold start** | The time from "container starts" to "ready to answer" |

## 3. Files (`deploy/demo/`)

| File | Job |
|---|---|
| `Dockerfile` | Builds the image: Python env → **model** → our code → runtime with Qdrant |
| `entrypoint.sh` | Starts Qdrant, waits, then docs-mcp |
| `prepare.sh` | Makes the demo folder: code + lockfile + **snapshot** (`make demo-prepare`) |
| `README.md` | What the container is (and how to make it an HF Space, if ever) |
| `smoke_test.py` | A real MCP client: connects, searches in English and Arabic, measures time |

## 4. Results (your laptop, limited to 2 CPUs / 16 GB / uid 1000)

| Measurement | Result | OK? |
|---|---|---|
| Image size | 4.13 GB | ✅ |
| Cold start | **9.1 s** | ✅ |
| RAM | **1.15 GB** of 16 GB | ✅ |
| One search | **~100 ms** (median 103, max 136) | ✅ |
| Runs as uid 1000, files writable | yes | ✅ |
| Answers are the same as locally | yes (EN + AR) | ✅ |

## 5. Lessons from this phase

**Layer order matters in Dockerfiles.** Docker rebuilds every step after the first changed step.
At first the model download came **after** copying our code, so **every code change would
re-download 2.3 GB**. Moving the model step **before** the code fixed it.

**The ONNX test.** You had an ONNX version of bge-m3. We **measured** before deciding:

| | PyTorch (kept) | Your ONNX file |
|---|---|---|
| Speed | 1.47 s/chunk | 2.02 s/chunk (slower) |
| Same vectors? | — | No (similarity 0.6, not ~1.0) |

It was exported in a way that blocks ONNX Runtime's optimisations, and it uses a different pooling.
**Lesson:** "ONNX is faster" is often true, but **measure** first.

**Fixes from the reviews:**
- Log redaction now also hides fields like `hf_token` (this phase introduced a Hugging Face token).
- The demo container **removes the UNESCO flyer at startup**: its licence isn't confirmed, and a tunnel would
  make the demo public, which would mean publishing it. So the shareable demo serves 4 documents.

## 6. Surprise: Hugging Face is no longer free for Docker apps

Creating the Space failed with **`402 Payment Required`**: *"hosting Gradio and Docker Spaces on free
cpu-basic requires a PRO subscription"*. Only static Spaces (plain web pages) stay free.
**This is exactly why we did a spike now:** we found it before Phase 3, not at the end.

Then we looked at **Google Cloud Run**: it runs the same container (we tested it locally the Cloud Run way:
`PORT=8080`, 4 GB → start 8.5 s, RAM 1.15 GB, search ~104 ms), but it **needs a card**, and storing the 4 GB
image may cost cents.

**Your rule: free tools only, no card.** Free no-card container hosts give ~512 MB RAM, but bge-m3 alone needs
~1.2 GB. So the decision (DECISIONS #50):

| Part | How (all free) |
|---|---|
| Public demo | A **static page** (HF static Space or GitHub Pages): example reports EN/AR, results, screenshots, GIF |
| Live system | Runs on **your laptop** with `docker compose` |
| Live demo in an interview | `make demo-tunnel`: a **Cloudflare quick tunnel** gives a temporary public https link, stopped with Ctrl+C |

We renamed the folder from `deploy/hf-space/` to **`deploy/demo/`** because it's no longer HF-specific.

## 7. Optional (you): try the free public link

Follow **[07-free-live-demo-guide.md](07-free-live-demo-guide.md)**: about 15 minutes, no account, no card.
