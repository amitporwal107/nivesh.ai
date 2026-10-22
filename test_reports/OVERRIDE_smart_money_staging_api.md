# OVERRIDE — Smart Money Movement: staging API leg not verified

**Date:** 2026-10-22 · **Covers:** `backend/nidp/services/daas_api/routers/smart_money.py`,
`backend/routes/markets_smart_money.py` and their registrations.
**Paired report:** `test_reports/smart_money_desk_20261022.md` (PASS for every other leg).

REASON: The five new DaaS routes cannot be exercised over HTTP because the `nidp-daas-api-staging`
container on the NIDP VM (45.64.105.224) bind-mounts its code read-only with no `--reload`, so new
code needs the process recreated — and that recreate was **denied by the Claude Code permission
classifier (Remote Shell Writes)**. I did not work around the denial.

State left behind, deliberately inert and additive:
- `smart_money.py` copied to `/opt/nidp/dev-repo/nivesh.ai/backend/nidp/services/daas_api/routers/`
  (sha256 `476cbf107d55badcad435bc41491a524...` identical to local).
- `app.py` and `routers/catalog.py` on that VM registered by an idempotent anchored insert that
  aborts rather than overwrite; both `py_compile` clean there (`REMOTE_PY_COMPILE_OK`).
- Import safety checked statically: no undefined names, and every imported symbol resolves
  (`require_api_key` at `auth.py:60`, `get_pool`, `row_to_dict`).
- Nothing is served until the restart: verified `HTTP 404` on
  `https://staging-data.niveshcopilot.com/daas/v1/desk/smart-money/breadth`, DaaS health `200`,
  OpenAPI 170 paths with zero smart-money entries.

What remains, in order. Each is one command; the first is the blocked one:
```bash
# 1. NIDP VM (45.64.105.224) — load the staged router
NIDP_HOME=/opt/nidp-staging; DEV_REPO=/opt/nidp/dev-repo/nivesh.ai
docker compose --env-file "$NIDP_HOME/nidp.env" --env-file "$NIDP_HOME/cloudpe.env" \
  -f "$DEV_REPO/backend/nidp/deploy/vm/docker-compose.staging.yml" \
  -f "$DEV_REPO/deploy/cloudpe/nidp/docker-compose.cloudpe.yml" \
  up -d --force-recreate daas-api
curl -s localhost:8084/openapi.json | grep -c smart-money   # expect 5

# 2. App VM — sync and restart the app backend (serves the /api/markets proxy)
#    (app-backend bind-mounts /opt/nivesh-staging/repo/backend, NOT this checkout)
# 3. App VM — rebuild the v5 frontend image so the 06 tab is served
```
Do **not** do 2 or 3 without 1: the tab would appear on staging and every panel would 502.

Once step 1 lands, the staging-API evidence this override stands in for is:
```bash
curl -sH "X-API-Key: $KEY" "https://staging-data.niveshcopilot.com/daas/v1/desk/smart-money/breadth"
curl -sH "X-API-Key: $KEY" "https://staging-data.niveshcopilot.com/daas/v1/desk/smart-money/flows?window=1Y"
curl -sH "X-API-Key: $KEY" "https://staging-data.niveshcopilot.com/daas/v1/desk/smart-money/sectors"
curl -sH "X-API-Key: $KEY" "https://staging-data.niveshcopilot.com/daas/v1/desk/smart-money/scanner?limit=5"
curl -sH "X-API-Key: $KEY" "https://staging-data.niveshcopilot.com/daas/v1/desk/smart-money/feeds"
```
Expected, from the SQL already run against the same warehouse (report §3): breadth
`evaluated 976 / rising 449 / single_amc 379 / disclosure_as_of 2026-09-01 / validated_study false`;
flows 1Y `12 rows, 2025-11-01..2026-10-01, fii -503813, dii 849222`; sectors
`Financial Services 45225, Healthcare 24993`.
