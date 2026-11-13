#!/usr/bin/env bash
# Start Qdrant (localhost only) restoring the baked-in snapshot, wait until it is ready,
# then run docs-mcp in the foreground on the one public port.
# Hosts like Cloud Run pass the port in $PORT; otherwise 7860 (image default).
set -euo pipefail

export DOCS_MCP_PORT="${PORT:-${DOCS_MCP_PORT:-7860}}"

mkdir -p /tmp/qdrant
started=$(date +%s)
qdrant --snapshot /data/documents.snapshot:documents >/tmp/qdrant/qdrant.log 2>&1 &
qdrant_pid=$!

ready=0
for _ in $(seq 1 120); do
  if python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:6333/readyz', timeout=1)" 2>/dev/null; then
    echo "{\"message\": \"qdrant ready\", \"seconds\": $(( $(date +%s) - started ))}"
    ready=1
    break
  fi
  if ! kill -0 "$qdrant_pid" 2>/dev/null; then
    echo "qdrant exited; last log lines:" >&2
    tail -n 30 /tmp/qdrant/qdrant.log >&2
    exit 1
  fi
  sleep 1
done

if [ "$ready" -ne 1 ]; then
  echo "qdrant not ready after 120 s; last log lines:" >&2
  tail -n 30 /tmp/qdrant/qdrant.log >&2
  exit 1
fi

# Documents whose licence doesn't allow sharing (see data/SOURCES.md) must not be served by a
# container that may be reachable from outside (e.g. through a tunnel): delete them first.
for doc_id in ${DEMO_EXCLUDE_DOC_IDS:-}; do
  python - "$doc_id" <<'PY'
import json, sys, urllib.request
body = {"filter": {"must": [{"key": "doc_id", "match": {"value": sys.argv[1]}}]}}
req = urllib.request.Request(
    "http://127.0.0.1:6333/collections/documents/points/delete?wait=true",
    data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
urllib.request.urlopen(req, timeout=10)
print(json.dumps({"message": "excluded document", "doc_id": sys.argv[1]}))
PY
done

exec docs-mcp
