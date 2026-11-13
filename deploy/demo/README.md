# ResearchCrew docs-mcp demo container (Phase 2b spike)

One container with the docs-mcp MCP server (semantic search over WHO, IRENA and UNESCO PDFs in
English and Arabic), Qdrant (localhost only) and the BAAI/bge-m3 model baked in. The indexed
collection ships as a Qdrant snapshot and is restored at every start.

- MCP endpoint: `/mcp` (streamable HTTP) on `$PORT` if set, else 7860
- Health: `/health`
- Documents without a confirmed licence are removed at startup (`DEMO_EXCLUDE_DOC_IDS`, default: the UNESCO flyer), so a tunnel never serves them.

Free tools only (DECISIONS #48–50): runs locally (`make demo-run`); a temporary public link via a free Cloudflare quick tunnel (`make demo-tunnel`). Not the final deployment. Document sources and
licences: `data/SOURCES.md` in the ResearchCrew repository.

To run it as a Hugging Face Docker Space instead (paid PRO plan), add this front matter at the top:
`---` / `sdk: docker` / `app_port: 7860` / `---`.
