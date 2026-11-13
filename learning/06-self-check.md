# 6. Self-check: interview-style questions

Try to answer out loud first, then click to see the answer.

## Phase 1

<details><summary><b>1. What is the difference between <code>pyproject.toml</code> and <code>uv.lock</code>?</b></summary>

`pyproject.toml` lists what we need, with allowed ranges (`crewai>=1.15.41`).
`uv.lock` records the **exact** versions chosen for all 204 packages, so every install is identical
(your laptop, CI, Docker).
</details>

<details><summary><b>2. uv installed crewai 1.6.1 without any error. Why was that a problem, and how did you fix it?</b></summary>

uv went back to an old crewai to satisfy our `mcp>=2.3` and `pydantic>=2.14` requirements.
We spotted it with `uv tree --outdated`. Forcing `crewai>=1.15.41` showed the real conflict:
new crewai needs `mcp<2` and `pydantic<2.13`. We chose the newest crewai and accepted those limits,
and recorded the reason in DECISIONS #20.
</details>

<details><summary><b>3. Why are API keys optional when the code is imported, but checked at startup?</b></summary>

So tests, CI and `/health` work without secrets. But the real app still fails **fast** with a clear message
(`Missing required environment variable: GROQ_API_KEY`) when it starts, not later in the middle of a job.
</details>

<details><summary><b>4. How do logs hide API keys but still show token usage?</b></summary>

Two layers: (1) fields **named** like secrets (`*_api_key`, `password`, `authorization`) become `***`;
(2) every string is scrubbed of the **actual secret values** and of `?apiKey=` in URLs.
We don't hide by the word "token", so `prompt_tokens` stays visible for cost tracking.
</details>

<details><summary><b>5. Why is the metric labelled <code>/research/{id}</code> and not the real path?</b></summary>

Every different label value creates a new time series in Prometheus. Real ids would create endless series
(unbounded cardinality) and use more and more memory. The route template keeps the number fixed.
</details>

<details><summary><b>6. Why a multi-stage Dockerfile, and why copy <code>uv.lock</code> before the code?</b></summary>

Multi-stage: build tools stay in the builder stage; the final image only gets `.venv` and runs as a non-root user.
Copying the lock files first lets Docker **cache** the slow "install packages" layer.
Changing only our code doesn't reinstall everything.
</details>

<details><summary><b>7. Why do tests never call the real LLM?</b></summary>

Real calls are slow, cost money, need keys and network, and give different answers each time.
Mocks make tests fast, free, offline and repeatable.
</details>

## Phase 2

<details><summary><b>8. What is the difference between an MCP tool and an MCP resource?</b></summary>

A **tool** is an action the model chooses to call with arguments (`search_documents(query, top_k)`).
A **resource** is read-only data the client fetches by URI (`docs://list`). Tool = verb, resource = noun.
</details>

<details><summary><b>9. What is NFKC and why do we need it for Arabic PDFs?</b></summary>

A Unicode normalisation that converts look-alike variants into plain characters (K = compatibility)
and combines character pieces (C = composed). Some PDFs store Arabic **shape** characters
(presentation forms, `U+FB50–U+FEFF`) instead of real letters. They look the same but don't match in search.
NFKC maps them back to the real letters.
</details>

<details><summary><b>10. How do you detect Arabic text that was extracted backwards?</b></summary>

Normal Arabic has many words **starting** with "ال". Reversed text makes them **end** with "لا".
If those clearly outnumber the "ال" words (at least 3, and more than double), we flag the text as reversed
and reverse the Arabic lines.
</details>

<details><summary><b>11. Why don't we support scanned PDFs?</b></summary>

They only contain images, with no text layer. Reading them needs OCR, which is out of scope (DECISIONS #16).
We detect "almost no text" and raise a clear error instead of indexing empty content.
</details>

<details><summary><b>12. Why do we check Arabic quality on the raw text, before NFKC?</b></summary>

NFKC removes the presentation forms. If we measured after it, we could never see whether a PDF had that problem.
</details>

<details><summary><b>13. How did you test PDF extraction without storing PDFs or using the internet?</b></summary>

The tests **create** small PDFs with PyMuPDF at runtime (English text, empty "scanned" pages) and read them back.
The Arabic cases are tested with text strings (normal, reversed, presentation forms).
</details>

## Phase 2 (continued)

<details><summary><b>14. Why do we count chunk size in tokens and use overlap?</b></summary>

The model reads and limits **tokens**, and Arabic and English use very different characters per token.
Overlap (100 tokens) repeats the end of one chunk at the start of the next, so an idea cut at the border
is still complete in one chunk.
</details>

<details><summary><b>15. How is ingest idempotent, and how does it skip unchanged files?</b></summary>

Point ids are computed from `doc_id + chunk number` (uuid5), and a document's old points are deleted
before new ones are saved, so there are never duplicates. A fingerprint (SHA-256 of the file + model +
chunk settings) is stored. If it matches next time, the file is skipped (re-running took 1.1 s).
</details>

<details><summary><b>16. Tell me about a real bug you found with real data.</b></summary>

The WHO Arabic PDFs extracted "الإقليم" as "اإلقليم" (the font stores the lam-alef ligature in the wrong
order). Unit tests passed; only real PDFs showed it. Two alef-type letters never follow each other in Arabic,
so we fix that pattern safely (1,122 fixes in one report). Another PDF had many different swapped pairs
("يف" instead of "في" 2,207 times), which can't be fixed safely, so we detect it and reject the file.
</details>

<details><summary><b>17. How did you reduce CPU usage?</b></summary>

Measured first: ingest used 13 cores. We capped torch to 4 threads (`EMBEDDING_THREADS`): only 16% slower,
because the model is limited by memory speed more than by cores. And we skip unchanged files entirely.
</details>

<details><summary><b>18. How do you test an MCP server without the real model or a database server?</b></summary>

A fake embedder (word hashing), Qdrant's in-memory mode, and a **real MCP client session** connected
to the server in memory. That checks tool schemas, validation errors and the resource exactly as a real
client sees them. Then a manual check with the MCP Inspector against the real server.
</details>

<details><summary><b>19. Why isn't the model inside the Docker image?</b></summary>

It's 2.3 GB. Baking it in makes every image build and push huge. Mounting it as a volume keeps the image
at 1.73 GB, and the same downloaded model is reused (on your laptop, from the existing Hugging Face cache,
with `HF_HUB_OFFLINE=1` so the container never downloads).
</details>

<details><summary><b>20. Your tests all passed. What did the pre-push review still find?</b></summary>

Security (Qdrant without a password was reachable from the Wi-Fi → ports bound to 127.0.0.1), behaviour over time
(code fixes never reached already-indexed PDFs → pipeline version in the fingerprint; renamed files left duplicates
→ `--prune`), and real limits (`get_document` could return ~90,000 tokens vs Groq's ~12,000/min → page ranges with a cap).
</details>

## Phase 2b

<details><summary><b>21. How do you run a vector database and an MCP server on a host that allows one port and no disk?</b></summary>

Put both in one container: Qdrant listens only on 127.0.0.1 and docs-mcp on the one public port (7860). There is no persistent
disk, so the index ships as a Qdrant **snapshot** inside the image and is restored at every start (2 s). The model is baked in too,
so the container never downloads anything. Measured with HF's limits: cold start 9.1 s, RAM 1.15 GB, search ~100 ms.
</details>

<details><summary><b>22. Someone says "use ONNX, it's faster". What did you do?</b></summary>

Measured on 24 real chunks: the available ONNX export was 37% slower (its weights were stored as graph inputs, blocking
optimisations) and produced different vectors (cosine ~0.6 with the indexed ones, because of different pooling).
So we kept PyTorch and noted a correct export as an optional later optimisation.
</details>

<details><summary><b>23. Why does the order of steps in a Dockerfile matter?</b></summary>

Docker caches each step and rebuilds everything after the first changed one. Put slow, rarely-changing steps (dependencies,
a 2.3 GB model download) before often-changing ones (your code), or every code change repeats the slow steps.
</details>

<details><summary><b>24. Your planned free host turned out to be paid. What did you do?</b></summary>

The spike found it early: creating the Hugging Face Docker Space returned `402 Payment Required` (PRO needed). Cloud Run
works with the same container but needs a card. With a "free tools only" rule, we split the demo: a free static page
(example reports, results, GIF) is the public face, the live system runs locally with docker compose, and for live demos a
free Cloudflare quick tunnel gives a temporary public link. The reason: the model alone needs ~1.2 GB RAM, more than free
no-card hosts give (~512 MB).
</details>
