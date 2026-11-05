#!/usr/bin/env bash
# Run the Autonomous Trading Desk tests in a throwaway container from the staging backend image, against a throwaway
# Postgres on a private docker network. Nothing shared is touched.
#   usage: sudo bash backend/scripts/run_autodesk_tests.sh <worktree> [pytest args...]
set -euo pipefail
WT="${1:?worktree path}"; shift
NET=autodesk-test; PG=autodesk-test-pg
docker network inspect "$NET" >/dev/null 2>&1 || docker network create "$NET" >/dev/null
if ! docker ps --format '{{.Names}}' | grep -qx "$PG"; then
  docker run -d --rm --name "$PG" --network "$NET" -e POSTGRES_PASSWORD=test -e POSTGRES_DB=adtest postgres:16-alpine >/dev/null
  for i in $(seq 1 30); do docker exec "$PG" pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done
fi
ARGS=("$@"); [ ${#ARGS[@]} -eq 0 ] && ARGS=(tests/autodesk)
docker run --rm --network "$NET" -v "$WT":/work:ro -w /work/backend \
  -e PYTHONDONTWRITEBYTECODE=1 -e AUTODESK_TEST_PG_URL="postgresql://postgres:test@$PG:5432/adtest" \
  nivesh/backend:staging python -m pytest "${ARGS[@]}" -q -p no:cacheprovider
