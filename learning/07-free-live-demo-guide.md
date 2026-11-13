# 7. Guide (optional, free): a temporary public link to the demo container

**Free tools only, no card** (DECISIONS #50). Hugging Face Docker Spaces are paid and Cloud Run needs
a card, so the live system runs **on your laptop**. When you want to show it to someone over the
internet (for example in an interview), a **Cloudflare quick tunnel** gives it a temporary public
`https://` address. Free, no account, no card. Time: about 15 minutes.

```
someone's browser / MCP client ──https──▶ random-words.trycloudflare.com ──tunnel──▶ your laptop :7860
```

> ⚠️ **While the tunnel runs, anyone who has the link can use the service** (there's no login).
> That's OK for the docs-mcp demo (it only searches public documents), but share the link only with
> people you choose, and stop it (Ctrl+C) when you're done. The link changes every time.

---

## Part A: install `cloudflared` (once, ~2 min)

```bash
curl -L -o /tmp/cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i /tmp/cloudflared.deb
cloudflared --version
```
| Command | What it does |
|---|---|
| `curl -L -o …` | Downloads Cloudflare's official installer package from their GitHub releases |
| `sudo dpkg -i …` | Installs it (asks for your password) |
| `cloudflared --version` | Checks it works: prints `cloudflared version 20xx.x.x` |

## Part B: start the demo container (terminal 1)

```bash
cd /media/magda-elkot/Data/downloads/Doc/USS/researchcrew/researchcrew
make demo-run
```
Wait for: `Uvicorn running on http://0.0.0.0:7860`. Leave this terminal open.
(If the image doesn't exist yet: `docker compose up -d qdrant && make demo-prepare && make demo-build` first.)

## Part C: open the tunnel (terminal 2)

```bash
make demo-tunnel
```
After a few seconds it prints a box with your link, like:
```
Your quick Tunnel has been created! Visit it at:
https://some-random-words.trycloudflare.com
```
Copy that address: below it's `<LINK>`. Leave this terminal open too.

## Part D: test it through the internet (terminal 3)

```bash
curl -s <LINK>/health
uv run python deploy/demo/smoke_test.py <LINK>/mcp
```
Expected: `{"status":"ok","version":"0.1.0"}`, then `tools: [...]`, `documents: 4` and 5 search lines.
(4, not 5: the demo container removes the UNESCO flyer at startup, because its licence isn't confirmed
and a tunnel makes the demo public.)
Times are higher than on localhost because the requests travel through Cloudflare.

You can also test it with the MCP Inspector (`make inspect`, transport **Streamable HTTP**, URL `<LINK>/mcp`),
or send `<LINK>/mcp` to someone with an MCP client.

## Part E: stop everything

- Terminal 2 (tunnel): **Ctrl+C** → the public link stops working immediately.
- Terminal 1 (demo): **Ctrl+C** → the container stops.

## Send Claude (optional)

The `curl` and smoke-test output from Part D (the link itself is temporary, so it's fine to include).

---

## If something goes wrong

| You see | Meaning | Fix |
|---|---|---|
| `cloudflared: command not found` | Not installed | Part A |
| `make demo-run`: port 7860 already in use | An old demo container is still running | `docker rm -f researchcrew-demo`, then try again |
| Tunnel prints errors about `connection refused` | The demo container isn't running yet | Start Part B first and wait for `Uvicorn running` |
| `curl <LINK>/health` → error 1033 / 530 | Tunnel not ready yet | Wait 10–20 seconds and try again |
| Smoke test hangs or times out | Slow network | Run it again; send Claude the output if it repeats |
