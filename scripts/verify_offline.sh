#!/usr/bin/env bash
# Prove the ISR offline image works with ZERO network access.
#
# Boots a THROWAWAY container from the image with --network none (no NIC at
# all — DNS, LAN, internet: nothing), seeds it, then walks every API route
# from inside: signup, login, all role workspaces, judging, the static AI
# analyzer, results, trust, exports, and the single-container UI.
#
# Network is only ever needed for (a) optional LLM judging via Groq and
# (b) the optional `git clone` in judge "add repo by URL" — everything else
# in this script must pass with the cable unplugged.
#
# Usage: bash scripts/verify_offline.sh [IMAGE]   (default isr-offline:latest)
#        fixture mount: FIXTURE=/path/to/fixtures.json (optional)
set -eu
IMAGE="${1:-isr-offline:latest}"
NAME=isr-offline-verify
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

docker rm -f "$NAME" >/dev/null 2>&1 || true

MOUNT_ARGS=()
if [ -n "${FIXTURE:-}" ] && [ -f "$FIXTURE" ]; then
  MOUNT_ARGS=(-v "$(cd "$(dirname "$FIXTURE")" && pwd)/$(basename "$FIXTURE"):/app/fixtures.json:ro")
fi

docker run -d --rm --name "$NAME" --network none \
  -e SEED_DEMO=1 -e ISR_SERVE_UI=1 -e ISR_UI_DIST=/app/ui/dist \
  -e DATABASE_URL=sqlite+pysqlite:////data/isr.db \
  "${MOUNT_ARGS[@]}" \
  "$IMAGE" >/dev/null

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

# Wait for boot (seeding included) — probed from INSIDE, so this works
# precisely because the container has no network to expose.
echo "booting $IMAGE with --network none ..."
ready=0
for _ in $(seq 1 60); do
  if docker exec "$NAME" python3 -c \
    "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=1)" \
    >/dev/null 2>&1; then
    ready=1; break
  fi
  sleep 1
done
if [ "$ready" -ne 1 ]; then
  echo "FAIL  container never became healthy inside the isolated network"
  docker logs --tail 20 "$NAME" || true
  exit 1
fi

RC=0
docker exec -i "$NAME" python3 - < "$SCRIPT_DIR/verify_offline.py" || RC=$?
if [ "$RC" -eq 0 ]; then
  echo "OFFLINE GUARANTEE VERIFIED: every route works with zero network."
  echo "Only optional extras touch the internet: Groq LLM judging (falls back to"
  echo "the offline static analyzer) and judge 'add repo by URL' (git clone)."
else
  echo "OFFLINE WALK FOUND GAPS — see FAIL lines above."
fi
exit "$RC"
