#!/usr/bin/env bash
# Corporate-event AI analysis, end to end: collect filings -> filter + analyse with Claude
# (tools off) -> post to the backend. Runs on the app VM as the user whose Claude Code login the
# model calls use. Safe to re-run: every stage skips what it has already done.
#
#   DAYS=3 MAX_FILINGS=250 MAX_FILTER=250 MAX_ANALYSES=40 ./pipeline.sh
#   REOCR_SINCE=2026-10-20 ./pipeline.sh   # also OCR filings collected before OCR existed (see ocr.py)
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

# FROM/TO (YYYY-MM-DD) reach past the data API feed's 30 days by listing filings straight from the
# filings table, newest first. Needs EVENT_AI_PSQL.
LIST_ARGS=()
if [ -n "${FROM:-}" ] && [ -n "${TO:-}" ]; then
  [[ "$FROM" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ && "$TO" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || { echo "FROM/TO must be YYYY-MM-DD"; exit 2; }
  [ -n "${EVENT_AI_PSQL:-}" ] || { echo "FROM/TO need EVENT_AI_PSQL"; exit 2; }
  printf '%s\n' '\pset tuples_only on' '\pset format unaligned' \
    "SELECT json_build_object('id', announcement_id, 'symbol', ticker_symbol, 'company', company_name, 'title', subject, 'summary', description, 'source', source, 'when', filed_at, 'url', attachment_url) FROM nidp.corporate_announcements WHERE filed_at::date BETWEEN '$FROM' AND '$TO' ORDER BY filed_at DESC;" \
    | "$EVENT_AI_PSQL" > "$WORK/list.jsonl"
  echo "== list: $(wc -l < "$WORK/list.jsonl") filings from $FROM to $TO"
  LIST_ARGS=(--list /work/list.jsonl)
fi

echo "== collect"
sudo docker run --rm --user "$(id -u):$(id -g)" --env-file "$ENVF" -e PYTHONDONTWRITEBYTECODE=1 -e HOME=/tmp \
  -v "$HERE":/pipeline:ro -v "$WORK":/work --entrypoint python "$IMAGE" \
  /pipeline/collect.py --out /work --days "${DAYS:-3}" --max "${MAX_FILINGS:-250}" "${LIST_ARGS[@]}" \
  --max-ocr "${MAX_OCR:-30}" ${REOCR_SINCE:+--reocr-since "$REOCR_SINCE"}

echo "== analyse"
python3 "$HERE/analyse.py" --work "$WORK" --max-filter "${MAX_FILTER:-250}" --max-analyses "${MAX_ANALYSES:-40}"

echo "== ingest"
KEY_FILE="${EVENT_AI_KEY_FILE:-$HOME/.config/nivesh/event-ai-ingest-key}"
EVENT_AI_INGEST_KEY="${EVENT_AI_INGEST_KEY:-$(cat "$KEY_FILE" 2>/dev/null || true)}" \
  python3 "$HERE/ingest.py" --work "$WORK"

# Category, impact and sentiment for the filings table (what the Research page's chips and
# "material" order read). EVENT_AI_PSQL is a command that runs SQL from stdin against the NIDP
# database; without it this stage is skipped and says so.
if [ -n "${EVENT_AI_PSQL:-}" ]; then
  echo "== scores"
  python3 "$HERE/to_pg_scores.py" --work "$WORK" --days "${SCORE_DAYS:-35}" | "$EVENT_AI_PSQL" | tail -8
else
  echo "== scores: skipped (EVENT_AI_PSQL not set)"
fi
