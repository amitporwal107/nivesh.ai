#!/usr/bin/env bash
# Corporate-event AI analysis, end to end: collect filings -> filter + analyse with Claude
# (tools off) -> post to the backend. Runs on the app VM as the user whose Claude Code login the
# model calls use. Safe to re-run: every stage skips what it has already done.
#
#   DAYS=3 MAX_FILINGS=250 MAX_FILTER=250 MAX_ANALYSES=40 ./pipeline.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="${EVENT_AI_WORK:-$HERE/work}"
BACKEND="${EVENT_AI_BACKEND_CONTAINER:-nivesh-staging-app-backend}"
mkdir -p "$WORK"

# The data API credentials live in the backend's environment and are copied into a private file
# for the collector. The ingest key (the value of the backend's EVENT_AI_INGEST_KEY secret) is read
# from an owner-only file. Neither is ever printed.
ENVF="$(mktemp)"; chmod 600 "$ENVF"; trap 'rm -f "$ENVF"' EXIT
sudo docker exec "$BACKEND" sh -c \
  'printenv | grep -E "^(NIDP_DAAS_BASE_URL|NIDP_DAAS_INTERNAL_TOKEN|NIDP_DAAS_API_KEY)="' > "$ENVF"
IMAGE="$(sudo docker inspect -f '{{.Config.Image}}' "$BACKEND")"

echo "== collect"
sudo docker run --rm --user "$(id -u):$(id -g)" --env-file "$ENVF" -e PYTHONDONTWRITEBYTECODE=1 -e HOME=/tmp \
  -v "$HERE":/pipeline:ro -v "$WORK":/work --entrypoint python "$IMAGE" \
  /pipeline/collect.py --out /work --days "${DAYS:-3}" --max "${MAX_FILINGS:-250}"

echo "== analyse"
python3 "$HERE/analyse.py" --work "$WORK" --max-filter "${MAX_FILTER:-250}" --max-analyses "${MAX_ANALYSES:-40}"

echo "== ingest"
KEY_FILE="${EVENT_AI_KEY_FILE:-$HOME/.config/nivesh/event-ai-ingest-key}"
EVENT_AI_INGEST_KEY="${EVENT_AI_INGEST_KEY:-$(cat "$KEY_FILE" 2>/dev/null || true)}" \
  python3 "$HERE/ingest.py" --work "$WORK"
