#!/usr/bin/env bash
# Assemble a self-contained deploy folder in deploy/demo/build/space:
#   Dockerfile, README.md, entrypoint.sh, code, lockfile, and a Qdrant snapshot
#   of the already-indexed `documents` collection (no ingest at runtime).
# The local Docker build uses exactly this folder, and it is what gets uploaded to Cloud Build.
#
# Needs: local Qdrant running with the collection indexed (`make up` / `make ingest`).
# Usage: deploy/demo/prepare.sh [qdrant_url]   (default: QDRANT_URL from .env)
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../.." && pwd)"
out="$here/build/space"
qdrant_url="${1:-$(grep -E '^QDRANT_URL=' "$root/.env" 2>/dev/null | cut -d= -f2- || true)}"
qdrant_url="${qdrant_url:-http://localhost:6333}"
collection="documents"

echo "Assembling $out (Qdrant: $qdrant_url)"
if ! curl -sf "$qdrant_url/collections/$collection" >/dev/null; then
  echo "Qdrant at $qdrant_url has no '$collection' collection. Start it and index first:" >&2
  echo "  docker compose up -d qdrant && make ingest" >&2
  exit 1
fi
rm -rf "$out"
mkdir -p "$out"

cp "$here/Dockerfile" "$here/entrypoint.sh" "$here/README.md" "$out/"
chmod +x "$out/entrypoint.sh"
cp "$root/pyproject.toml" "$root/uv.lock" "$root/.python-version" "$out/"
cp -r "$root/app" "$root/mcp_servers" "$out/"
find "$out" -name "__pycache__" -type d -prune -exec rm -rf {} +

# Snapshot of the indexed collection, made by the Qdrant server and downloaded.
name=$(curl -sf -X POST "$qdrant_url/collections/$collection/snapshots?wait=true" \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['result']['name'])")
curl -sf -o "$out/documents.snapshot" "$qdrant_url/collections/$collection/snapshots/$name"
curl -sf -X DELETE "$qdrant_url/collections/$collection/snapshots/$name" >/dev/null

echo "Done:"
du -sh "$out" "$out/documents.snapshot"
