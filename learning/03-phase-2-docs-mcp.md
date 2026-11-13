# 3. Phase 2: docs-mcp (our own MCP server)

**Goal of the whole phase:** build an MCP server that lets the AI agents **search inside our PDFs**.

**Result:** 5 PDFs indexed (230 chunks), search works in English and Arabic (and across them),
**114 tests passing**.

## Files in Phase 2

| File | What it does | Explained in |
|---|---|---|
| `app/config.py` (changed) | docs-mcp settings: model, chunk size, threads, port | 3.3 |
| `app/log.py` (changed) | Quiets noisy library logs | 3.12 |
| `mcp_servers/docs_mcp/extract.py` | Reads PDFs, NFKC cleanup, Arabic checks and fixes | 3.4–3.6, 3.8 |
| `mcp_servers/docs_mcp/chunking.py` | Cuts text into ~800-token pieces with page numbers | 3.9 |
| `mcp_servers/docs_mcp/embeddings.py` | Loads bge-m3 and turns text into 1024 numbers | 3.10 |
| `mcp_servers/docs_mcp/store.py` | Saves and searches the numbers in Qdrant | 3.11 |
| `mcp_servers/docs_mcp/ingest.py` | The `ingest` command: a PDF folder → Qdrant | 3.12 |
| `mcp_servers/docs_mcp/server.py` | The MCP server: 2 tools, 1 resource, `/health` | 3.13 |
| `tests/docs_mcp/*.py` | 50+ tests (fake model, in-memory Qdrant, real MCP client) | 3.14 |
| `data/pdfs/*.pdf`, `data/SOURCES.md` | The 5 sample PDFs and where they come from | 3.15 |
| `data/notes/*.md` | Short topic notes (for the filesystem MCP in Phase 3) | 3.15 |
| `docker/docs-mcp.Dockerfile`, `docker-compose.yml` | The docs-mcp container | 3.16 |
| `pyproject.toml` (changed) | `ingest` and `docs-mcp` commands; lint/type exceptions | 3.14 |

## Where does the bge-m3 model come from?

| Question | Answer |
|---|---|
| Who made it? | **BAAI** (Beijing Academy of Artificial Intelligence). It's open source. |
| Where is it? | On the **Hugging Face Hub**: `huggingface.co/BAAI/bge-m3` (a free website for AI models). |
| Is it local or online? | **Local.** It's downloaded **once** (~2.3 GB), then runs on **your own computer's CPU**. No API, no key, no cost, no internet needed after the download. |
| Is it downloaded already? | **Yes, by another project** (2026-08-20). It's saved in `/home/magda-elkot/.cache/huggingface/hub/models--BAAI--bge-m3` (4.3 GB: two versions of ~2.2 GB each). ResearchCrew doesn't use it yet; only its **name** is in `app/config.py`. |
| Where is the model saved? | In the **Hugging Face cache**: one shared folder for every project on your computer. Any project that asks for `BAAI/bge-m3` finds it there and doesn't download it again. `MODEL_CACHE_DIR` can point to a different folder. |
| When will ResearchCrew use it? | **Step 4** writes the code that loads it (`embeddings.py`). **Step 9** runs it for real. Decision at step 9: keep it in the home cache, or move it to the Data drive (the home drive is 92% full). In Docker (step 11) it gets its own volume. |
| Which library loads it? | `sentence-transformers` (in the `docs` group), running on CPU torch. |
| Why this model? | It's **multilingual** (English + Arabic in the same space), good at search, and free. Chosen in SPEC. |
| Do tests download it? | **Never.** Tests use a fake embedder, so they stay fast and offline. |

---

## 3.1 What is an MCP server?

- An **MCP server** offers capabilities.
- An **MCP client** (our CrewAI agent, or the MCP Inspector tool) connects and uses them.

A server can offer two main things:

| Type | Meaning | Example in docs-mcp |
|---|---|---|
| **Tool** | An **action** the AI decides to call, with arguments | `search_documents(query="solar energy", top_k=5)` |
| **Resource** | **Read-only data** the client can fetch by address (URI) | `docs://list`: the list of indexed PDFs |

Simple rule: a **tool = a verb** (do something), a **resource = a noun** (read something).

## 3.2 How searching PDFs will work (the pipeline)

```
 PDF file
   │  step 2 ✅  EXTRACT   read the text of each page, clean it
   ▼
 Clean text
   │  step 3     CHUNK     cut it into pieces of ~800 tokens (100 overlap)
   ▼
 Chunks
   │  step 4     EMBED     turn each chunk into 1024 numbers (bge-m3 model)
   ▼
 Vectors
   │  step 5     STORE     save them in Qdrant (collection "documents")
   ▼
 Qdrant  ◀── step 7: search_documents("question") turns the question into numbers
                    too, and finds the chunks with the closest numbers
```

**Why numbers (embeddings)?** Texts with **similar meaning** get **similar numbers**,
even with different words, and even in different languages.
"renewable energy" and "الطاقة المتجددة" end up close together. This is called **semantic search**.

## 3.3 Step 1: settings (done)

We added the docs-mcp settings to the **same** `Settings` class from Phase 1
(one config system for the whole project):

| Setting | Value | Meaning |
|---|---|---|
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | The model that turns text into numbers. It's multilingual (English + Arabic). |
| `EMBEDDING_DIM` | `1024` | How many numbers per chunk. Must match Qdrant. |
| `CHUNK_TOKENS` | `800` | Size of each piece of text |
| `CHUNK_OVERLAP` | `100` | Repeated part between neighbouring pieces. Must be smaller than 800. |
| `MODEL_CACHE_DIR` | (empty) | Where the 2.3 GB model is saved. We'll put it on the Data drive, because your home drive is 92% full. |
| `DOCS_MCP_PORT` | `8001` | The server's port (the API uses 8000) |

**`env_ignore_empty=True`:** a line like `MODEL_CACHE_DIR=` (empty) means "not set", not "empty text".

## 3.4 Step 2: PDF extraction (done): `mcp_servers/docs_mcp/extract.py`

### What it does, in order
1. **Open the PDF** with **PyMuPDF** and read the text of each page.
2. **Reject scanned PDFs.** A scanned PDF is just **pictures** of pages, with no real text inside.
   Reading pictures needs OCR, which is outside our scope. If there's almost no text, we stop with a clear error.
3. **Check the Arabic quality** (see 3.6).
4. **Fix reversed Arabic** if it was detected.
5. **Normalise with NFKC** (see 3.5) and clean the spaces.
6. **Detect the language:** if 30% or more of the letters are Arabic, the document is `"ar"`, otherwise `"en"`.
7. **Find the title:** from the PDF's info, or from the file name if there's none.

### Born-digital vs scanned
| Type | How it was made | Text inside? | Can we use it? |
|---|---|---|---|
| **Born-digital** | Exported from Word, LaTeX and so on | ✅ Yes | ✅ Yes |
| **Scanned** | A photo or scan of paper | ❌ Only images | ❌ No (needs OCR) |

## 3.5 NFKC: the most important new concept

### The problem
Computers store each character as a **number (code point)**.
**The same-looking character can have different numbers:**

| You see | Code point | What it is |
|---|---|---|
| ا | `U+0627` | The **real** Arabic letter alef |
| ﺍ | `U+FE8D` | A **drawing shape** of alef (presentation form) |
| fi | `U+0066 U+0069` | Two letters |
| ﬁ | `U+FB01` | One "ligature" shape |
| 2 | `U+0032` | A normal digit |
| ２ | `U+FF12` | A "full-width" digit |

For the computer, `"ا" == "ﺍ"` is **False**. So searching for the real word won't find the shape version.

### Why PDFs have this problem
A PDF stores **what to draw**, not words. Arabic letters change shape by position
(start, middle, end, alone), and some PDF tools save the **shapes** instead of the **letters**.

### The solution
**NFKC** (Normalization Form, Compatibility, Composed) is a standard Unicode cleanup:
- **K (compatibility):** replace look-alike variants with the plain character. `ﺍ` → `ا`, `ﬁ` → `fi`, `２` → `2`.
- **C (composed):** join pieces into one character. `e` + `´` → `é`.

In Python it's one line: `unicodedata.normalize("NFKC", text)`.

### Two things to remember
- NFKC changes a little meaning: `km²` → `km2`. That's fine for **search**, but don't use it for exact display.
- NFKC does **not** change Arabic-Indic digits: `٢٠٢٥` stays `٢٠٢٥`. They are real digits, not shapes.

## 3.6 The Arabic quality check: `arabic_quality()`

It runs on the **raw** text, before NFKC, so it can still **see** the problems, and it measures:

| Measure | Meaning | Problem if… |
|---|---|---|
| `arabic_ratio` | Share of letters that are Arabic | Used to decide the language |
| `presentation_form_ratio` | Share of Arabic characters that are **shapes** | High → the PDF stored shapes (NFKC fixes it) |
| `reversed_suspected` | Does the text look **backwards**? | True → we reverse the Arabic lines |

**How we detect reversed text:** in normal Arabic, many words **start** with "ال" (the).
If the text is reversed, they **end** with "لا" instead.
- Normal: `الصحة العامة` (public health)
- Reversed: `ةماعلا ةحصلا`

If at least 3 words end with "لا" and they are more than double the words starting with "ال",
we call the text reversed. (A few real words end with "لا", like "مثلا", so we need a clear majority.)

**Known limitation:** reversing a whole line also reverses numbers inside it (`2025` → `5202`).
We'll check this on real Arabic PDFs in step 8.

## 3.7 How we tested it, without real PDFs

- English test PDFs are **created inside the test** with PyMuPDF, then read back.
- A "scanned" PDF = a PDF with empty pages → must raise an error.
- Arabic is tested with **text strings**: normal, reversed and presentation shapes.
- No internet, no model download. Fast (0.1 s).

## 3.8 Two problems we met (and what they teach)

| Problem | Meaning | Fix |
|---|---|---|
| ruff `I001` | Imports must be in 3 groups (standard library, other packages, our code) with no blank lines inside a group | `make format` fixes it automatically |
| mypy `no-untyped-call` | PyMuPDF's `Document` has no type hints, so strict mypy refuses to call it | `untyped_calls_exclude = ["pymupdf"]`: allowed for that library only (DECISIONS #28) |

---

## 3.8 A real problem we found: broken Arabic fonts

When we read the real WHO Arabic PDFs, the text **looked** right but some letter pairs were **swapped**.
The PDF's font stores some two-letter shapes (ligatures) in the wrong order:

| In the PDF text | Should be | Fixable? |
|---|---|---|
| `اإلقليم` | `الإقليم` (the region) | ✅ Yes: **lam-alef fix** |
| `األمراض` | `الأمراض` (diseases) | ✅ Yes |
| `يف` | `في` (in) | ❌ No safe rule |
| `عىل` | `على` (on) | ❌ No safe rule |

**Lam-alef fix:** in correct Arabic, an alef (`ا`) is **never** followed directly by another alef-type
letter (`ا أ إ آ`). So the pattern `ا` + alef-type + `ل` can only be this bug → swap it back.
The 2025 WHO Arabic report needed **1,122** fixes.

**Unfixable cases → reject:** the 2019 WHO Arabic report had `يف` 2,207 times and `في` only 2 times.
Too many different pairs are broken, so `extract.py` **rejects** such a PDF with a clear message
(like scanned PDFs). Better no document than a wrong one.

**Lesson (good interview story):** always test with **real** data. Our unit tests passed, but only the
real PDFs showed this problem.

## 3.9 Step 3: chunking (`chunking.py`)

**Why chunk?** A 150-page report is too long to search as one piece. We cut it into pieces of
**~800 tokens** (about 1–2 pages), so a search returns the exact part that answers the question.

**Why tokens, not characters?** The model reads **tokens** and has a token limit. Arabic and English use
very different numbers of characters per token, so tokens are the fair measure.

**Why overlap (100 tokens)?** If an important sentence is cut at the border, the next piece repeats the
end of the previous one, so the idea is complete in at least one piece:
```
piece 1: [tokens 0 ........ 799]
piece 2:              [tokens 700 ........ 1499]     ← 100 tokens repeated
```
**Page numbers:** each piece remembers the page where it starts and ends (`page_start`, `page_end`),
so answers can cite "page 12–15".

## 3.10 Step 4: embeddings (`embeddings.py`)

- Loads **bge-m3** with `sentence-transformers` on the **CPU**.
- `embed(texts)` → one list of **1024 numbers** per text.
- The vectors are **normalised** (length 1), so "cosine similarity" = how close two meanings are.
- The model loads **lazily** (only when first needed), so tests and imports stay fast.
- **Tests use a fake embedder** (simple word hashing): fast, offline, no download.

## 3.11 Step 5: Qdrant store (`store.py`)

| Qdrant word | Meaning in our project |
|---|---|
| **Collection** | `documents`: like a table |
| **Point** | One chunk: its 1024 numbers (vector) + its **payload** |
| **Payload** | Extra data on the point: doc_id, title, language, pages, text |
| **Cosine distance** | How we measure "close in meaning" |

**Idempotent ingest** = running it twice gives the same result (no duplicates):
- Each point's id is **calculated** from `doc_id + chunk number`, so it's always the same id.
- Before saving a document again, all its old points are **deleted**.

**Chunk 0 is special:** it also stores the whole document's metadata and full text. That's how
`get_document` and `docs://list` work without a second database.

## 3.12 Step 6: the `ingest` command (`ingest.py`)

`uv run ingest data/pdfs` runs **extract → chunk → embed → store** for every PDF.
- One bad PDF (scanned, broken font) is **logged and skipped**; the others continue.
- **Skip unchanged files:** ingest saves a **fingerprint** (SHA-256 hash) of each file + model + chunk
  settings. Next time, an unchanged file is skipped (0 seconds). `--force` re-does everything.
- **`EMBEDDING_THREADS=4`:** limits the CPU cores the model uses, so your computer stays responsive.

**Measured on your laptop (i7-13650HX):**

| Run | Threads | Time for 5 PDFs (230 chunks) |
|---|---|---|
| First ingest | 14 (all cores) | 5 min 0 s |
| With the limit | 4 | 5 min 49 s: only **16% slower**, using **3.9 cores instead of 13** |
| Again, nothing changed | — | **1.1 s** (all 5 files skipped) |

Why are 4 threads almost as fast? The model's speed is limited by **memory speed**, not by the number
of cores, so extra cores add little.

## 3.13 Step 7: the MCP server (`server.py`)

Built with **FastMCP** and served over **streamable HTTP** at `http://127.0.0.1:8001/mcp`.

| Name | Type | Input | Output |
|---|---|---|---|
| `search_documents` | Tool | `query` (text), `top_k` (1–20, default 5) | The best chunks: doc_id, title, pages, score, text |
| `get_document` | Tool | `doc_id`, `start_page` (1), `end_page` (last), `max_chars` (12,000) | Metadata + the text of those pages, each starting with `[page N]`; `truncated=true` if the cap cut it |
| `docs://list` | Resource | — | JSON list of all documents |
| `/health` | Plain HTTP (not MCP) | — | `{"status": "ok"}` for Docker |

- **Input validation is automatic:** `top_k=50` or an empty `query` returns an error to the AI.
- **Blocking work runs in a thread** (`anyio.to_thread`), so one slow search doesn't freeze the server.
- **Tool descriptions matter:** the AI reads them to decide **when** to call a tool.
- **Why `get_document` reads pages, not the whole file:** one IRENA report is ~358,000 characters
  (~90,000 tokens), but Groq's free tier allows only ~12,000 tokens per minute. So the tool returns
  at most 12,000 characters by default and says `truncated=true`; the agent asks for the next pages
  if it needs more.

## 3.18 Review before push: what we found and fixed

A careful review found problems that **all tests had missed**:

| Problem | Fix |
|---|---|
| Docker ports were open to the whole Wi-Fi network; Qdrant has **no password** | Ports now listen on `127.0.0.1` only (your computer) |
| Improving our code would never re-process old PDFs (they were "unchanged") | `PIPELINE_VERSION` is part of the fingerprint |
| Renamed or deleted PDFs stayed in search forever | `ingest --prune` removes them |
| `a b.pdf` and `a-b.pdf` got the same id and overwrote each other | Reported as an error |
| `get_document` could return 90,000 tokens | Page ranges + a size cap |

**Lesson:** passing tests ≠ correct. Also review for **security**, **behaviour over time** (re-runs, renames)
and **real limits** (token budgets).

**Real searches (it works across languages!):**

| Question | Found |
|---|---|
| "solar energy deployment in Saudi Arabia" | IRENA GCC report, pages 83–84 (Vision 2030) |
| "الطاقة المتجددة في دول الخليج" (Arabic) | The **English** IRENA GCC report |
| "vaccine production in the region" (English) | The English **and** Arabic WHO reports, same pages 12–15 |

One search takes about **60–90 ms**.

## 3.14 How we tested without the real model

| Test file | What it tests | Trick |
|---|---|---|
| `test_extract.py` | PDF reading, NFKC, Arabic checks | Creates small PDFs inside the test |
| `test_chunking.py` | Sizes, overlap, pages | "Tokenizer" = split on spaces |
| `test_store.py` | Save, search, replace, list | Qdrant **in-memory mode** (no server) |
| `test_ingest.py` | The whole pipeline, skipping, bad PDFs | Fake embedder |
| `test_server.py` | The MCP tools and resource | A **real MCP client** talking to our server in memory |

## 3.15 Step 8: the sample documents

| Document | Language | Topic |
|---|---|---|
| WHO EMRO annual report 2024/2025 | English + Arabic | Public health |
| IRENA: Renewable energy in the Arab region (2016) | English | Energy |
| IRENA: Renewable energy markets GCC (2023) | English | Energy |
| UNESCO flyer on AI ethics | English | AI ethics (kept local: no licence statement) |

Details and licences: `data/SOURCES.md`. Some sites (UNESCO, UN library) **block automatic downloads**,
so the full UNESCO Recommendation (English + Arabic) must be downloaded by hand in a browser.

## 3.16 Step 11: Docker (`docker/docs-mcp.Dockerfile`)

- Same pattern as the api image (two stages, non-root), but installs **only the `docs` group**.
- The model is **not inside the image**. It's mounted at `/models`:
  - default: a Docker volume (downloads the model once);
  - on your laptop: your existing Hugging Face folder (`MODEL_CACHE_HOST_DIR`) + `HF_HUB_OFFLINE=1`.
- Inside Docker the server listens on `0.0.0.0` so other containers can reach it.
- Measured: image **1.73 GB**, container **healthy in 12 s**, runs as non-root user `app`.

## 3.17 Step 10: testing with the MCP Inspector

The **MCP Inspector** is the official tool for testing MCP servers by hand (like Bruno, but for MCP).
We used its command-line mode:

| What we asked | What happened |
|---|---|
| `tools/list` | Saw `search_documents` and `get_document` with their descriptions |
| `resources/read docs://list` | Got the list of 5 documents |
| `search_documents` with an **Arabic** question about vaccines | Found the WHO section on vaccine manufacturing, pages 12–15 |
| `search_documents` with `top_k=50` | A clear error ("must be ≤ 20"); the server kept running |

Try the web version yourself: start the server (`make docs-mcp` or `make up`), run `make inspect`,
then in the browser choose transport **Streamable HTTP** and URL `http://localhost:8001/mcp`.

## Phase 2: done ✅
All three "definition of done" checks pass: ingest works, every tool has tests, the Inspector works.
