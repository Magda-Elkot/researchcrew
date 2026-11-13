# 4. Glossary: short definitions

| Word | Simple meaning |
|---|---|
| **Agent** | An AI model with a role, a goal and tools (for example the "Researcher"). |
| **CrewAI** | A Python library for running a team ("crew") of agents. |
| **LLM** | Large Language Model: the AI that writes text (we use Llama 3.3 70B on Groq). |
| **LiteLLM** | One interface to many LLM providers (Groq, OpenAI, Gemini), so we can switch easily. |
| **MCP** | Model Context Protocol: a standard plug between AI apps and tools. |
| **MCP server / client** | The server **offers** tools and resources; the client (the agent) **uses** them. |
| **Tool (MCP)** | An action the AI calls with arguments, like `search_documents(...)`. |
| **Resource (MCP)** | Read-only data addressed by a URI, like `docs://list`. |
| **FastMCP** | The easy way to write an MCP server in Python (part of the `mcp` package). |
| **Embedding** | A list of numbers that represents the **meaning** of a text. |
| **bge-m3** | The multilingual embedding model we use (1024 numbers per text). |
| **Semantic search** | Searching by **meaning** (close numbers), not exact words. |
| **Vector database** | A database that stores embeddings and finds the closest ones fast. |
| **Qdrant** | Our vector database. |
| **Collection** | A "table" in Qdrant. Ours is called `documents`. |
| **Chunk** | A small piece of a long document (~800 tokens). |
| **Token** | A piece of a word that the model reads. One English word is about 1–2 tokens. |
| **Overlap** | Text repeated at the start of the next chunk, so ideas cut at the border aren't lost. |
| **Code point** | The number a computer uses for one character (for example `U+0627` = ا). |
| **Unicode normalisation** | Converting text to one standard form, so equal-looking text is really equal. |
| **NFKC** | The normalisation that also replaces look-alike variants (shapes, ligatures, full-width). |
| **Presentation forms** | Arabic **shape** characters (`U+FB50–U+FEFF`) used for drawing, not real letters. |
| **Born-digital PDF** | A PDF made by software, with real text inside. |
| **Scanned PDF** | A PDF that contains only images of pages. Needs OCR. |
| **OCR** | Optical Character Recognition: reading text from images. Out of our scope. |
| **PyMuPDF** | The Python library that reads PDFs (imported as `pymupdf`). |
| **uv** | A fast Python package and project manager. |
| **pyproject.toml** | The list of what the project needs, plus tool settings. |
| **uv.lock / lockfile** | The exact versions installed, so every machine is the same. |
| **.venv** | The project's private folder of installed packages. |
| **Dependency group** | A named set of extra packages (`api`, `docs`, `frontend`, `dev`). |
| **Transitive dependency** | A package your package needs (you didn't ask for it directly). |
| **Environment variable** | A named value set outside the code (for example `GROQ_API_KEY`). |
| **.env / .env.example** | Your real values (secret, not committed) / a template with fake values (committed). |
| **Pydantic** | A library that checks data against typed classes and gives clear errors. |
| **pydantic-settings** | Pydantic for configuration: fills a class from environment variables. |
| **Schema / data contract** | The agreed shape of data (fields and rules). |
| **Redaction** | Hiding secrets in logs (replacing them with `***`). |
| **FastAPI** | A Python web framework for building APIs. |
| **Endpoint** | One URL of an API, like `GET /health`. |
| **Lifespan** | Code that runs when the server starts and stops. |
| **Middleware** | Code that runs around **every** request (we use it to measure time). |
| **Prometheus** | A monitoring tool that reads numbers from `/metrics`. |
| **Docker image / container** | A packaged app / a running copy of that package. |
| **Multi-stage build** | Build in one stage, copy only the result into a smaller final stage. |
| **Non-root user** | Running without admin rights, for safety. |
| **Healthcheck** | Docker regularly asks "are you OK?" (for us, it calls `/health`). |
| **docker compose** | Starts several containers together (api + qdrant). |
| **Port** | A "door number" on a computer. API = 8000, Qdrant = 6333 (6335 on your machine). |
| **ruff** | A linter (finds problems) and formatter (fixes style). |
| **mypy** | A type checker (finds type mistakes without running the code). |
| **pytest** | The test runner. |
| **Mock / fake** | A pretend version of something (an AI, a database) used in tests. |
| **CI** | Continuous Integration: automatic checks on every push (GitHub Actions). |
| **Langfuse** | A tool to trace AI runs: steps, tokens, cost (Phase 5). |
| **Ingest** | Loading documents into the search database: extract → chunk → embed → store. |
| **Ligature** | Two letters drawn as one shape (for example لا). Some PDF fonts store them in the wrong order. |
| **Lam-alef fix** | Our safe repair of `اإل` → `الإ`, because two alef-type letters never follow each other in Arabic. |
| **Payload (Qdrant)** | Extra data stored next to a vector: doc_id, title, pages, text. |
| **Point (Qdrant)** | One stored item: a vector + its payload (for us, one chunk). |
| **Idempotent** | Running something twice gives the same result as once (no duplicates). |
| **Fingerprint / hash (SHA-256)** | A short code computed from a file's bytes. Same file → same code, so unchanged files can be skipped. |
| **Thread** | A worker the CPU runs in parallel. `EMBEDDING_THREADS=4` uses 4 of them. |
| **Streamable HTTP** | The MCP transport we use: the client talks to the server over normal HTTP at `/mcp`. |
| **MCP Inspector** | The official tool to test an MCP server by hand. |
| **Cross-lingual search** | An Arabic question finds English text (and the other way round), because bge-m3 puts both in the same "meaning space". |
| **Hugging Face Space** | Hosting for AI demos. Static pages are free; Docker apps now need a paid PRO plan. |
| **Google Cloud Run** | Google's container hosting with a free allowance, but it needs a card, so we didn't use it (free tools only). |
| **Static page / static Space** | A website made only of files (HTML, images): free to host on HF or GitHub Pages, but it can't run Python. |
| **Cloudflare quick tunnel** | A free command (`cloudflared tunnel --url …`) that gives a program on your laptop a temporary public https address. No account, no card. |
| **402 Payment Required** | An HTTP error meaning "you must pay for this". |
| **Spike** | A short experiment to check a risk early. Not the final version. |
| **Cold start** | Time from "container starts" to "ready to answer" (ours: 9.1 s). |
| **Snapshot (Qdrant)** | A file containing a whole collection; restored at start instead of re-indexing. |
| **uid 1000** | The user id HF runs containers as; files must belong to it to be writable. |
| **ONNX / ONNX Runtime** | A portable model format and a fast engine to run it. Our tested ONNX file was slower and gave different vectors, so we kept PyTorch. |
| **Docker layer cache** | Docker reuses unchanged build steps; a changed step rebuilds everything after it. |
| **Volume (Docker)** | Storage that lives outside the container, so data (like the model) survives restarts. |
