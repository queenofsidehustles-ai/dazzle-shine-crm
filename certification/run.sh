#!/usr/bin/env bash
# Certify Nana's onboarding against a disposable business. Nothing here touches
# production: a throwaway SQLite database, a local server, and the Anthropic
# endpoint answered from a script.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
WORK="${WORK:-$(mktemp -d)}"

export DATABASE_URL="sqlite:///$WORK/akye.db"
export SECRET_KEY=certification-only
export ADMIN_USER=cert
export ADMIN_PASS=certpass
export ANTHROPIC_API_KEY=sk-ant-certification-stub
export WIRE_LOG="$WORK/wire.jsonl"
export SCRIPT_FILE="$WORK/script.json"
export MODE_FILE="$WORK/mode.txt"
export PORT="${PORT:-5055}"
export BASE="http://127.0.0.1:$PORT"

echo '[]' > "$SCRIPT_FILE"; echo ok > "$MODE_FILE"; : > "$WIRE_LOG"
SEED=1 python3 "$HERE/serve.py" > "$WORK/seed.log" 2>&1
python3 "$HERE/serve.py" > "$WORK/server.log" 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT

for _ in $(seq 1 40); do
  curl -fsS "$BASE/login" >/dev/null 2>&1 && break
  sleep 0.5
done

python3 "$HERE/certify.py"
