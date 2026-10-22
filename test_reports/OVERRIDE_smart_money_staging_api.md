# OVERRIDE — Smart Money Movement: staging API leg not verified

**Date:** 2026-10-22 · **Covers:** `backend/nidp/services/daas_api/routers/smart_money.py`,
`backend/routes/markets_smart_money.py` and their registrations.
**Paired report:** `test_reports/smart_money_desk_20261022.md` (PASS for every other leg).

REASON: The DaaS routes cannot be exercised over HTTP. The `nidp-daas-api-staging` container on the
NIDP VM (45.64.105.224) bind-mounts its code read-only with no `--reload`, so new code needs the
process recreated — and that recreate was **denied by the Claude Code permission classifier
(Remote Shell Writes)**. I did not work around the denial.

Verified not live: `HTTP 404` on
`https://staging-data.niveshcopilot.com/daas/v1/desk/smart-money/breadth`, DaaS health `200`,
OpenAPI 170 paths with zero smart-money entries.

## The file staged on that VM is now CURRENT (refreshed 2026-10-22)

`/opt/nidp/dev-repo/nivesh.ai/backend/nidp/services/daas_api/routers/smart_money.py` was briefly
stale — it predated the design rebuild, and SSH to the host was refused for a while
(`kex_exchange_identification: Connection reset by peer`, most likely fail2ban reacting to earlier
failed key-auth probes from the app VM). The ban has since expired and the file was refreshed:

```
local (committed) sha256: 6513d8c8d97930087f5260c30c944e8b
remote sha256:            6513d8c8d97930087f5260c30c944e8b
REMOTE_PY_COMPILE_OK
registrations still in place: app.py=2 catalog.py=2
routes in the staged file:    5
```

So a restart now loads the correct router. Deploying from git is still the better route, because it
also brings `app.py`, `routers/catalog.py` and migration 181 under version control rather than
trusting hand-placed files:

```bash
# 1. NIDP VM (45.64.105.224) — take the committed code
cd /opt/nidp/dev-repo/nivesh.ai
git fetch origin feat/provider-foundations
git checkout origin/feat/provider-foundations -- \
  backend/nidp/services/daas_api/routers/smart_money.py \
  backend/nidp/services/daas_api/app.py \
  backend/nidp/services/daas_api/routers/catalog.py \
  backend/nidp/migrations/181_trendlyne_deal_fetch_log.sql
python3 -m py_compile backend/nidp/services/daas_api/routers/smart_money.py

NIDP_HOME=/opt/nidp-staging; DEV_REPO=/opt/nidp/dev-repo/nivesh.ai
docker compose --env-file "$NIDP_HOME/nidp.env" --env-file "$NIDP_HOME/cloudpe.env" \
  -f "$DEV_REPO/backend/nidp/deploy/vm/docker-compose.staging.yml" \
  -f "$DEV_REPO/deploy/cloudpe/nidp/docker-compose.cloudpe.yml" \
  up -d --force-recreate daas-api
curl -s localhost:8084/openapi.json | grep -c smart-money     # expect 5

# 2. App VM — sync and restart the app backend (serves the /api/markets/smart-money proxy)
#    app-backend bind-mounts /opt/nivesh-staging/repo/backend, NOT the /home/deploy checkout
# 3. App VM — rebuild the v5 frontend image so the 06 tab is served
```
Do **not** do 2 or 3 before 1: the tab would appear on staging and every panel would 502.

Once step 1 lands, the staging-API evidence this override stands in for is:
```bash
K="X-API-Key: $KEY"; B=https://staging-data.niveshcopilot.com/daas/v1/desk/smart-money
curl -sH "$K" "$B/breadth"
curl -sH "$K" "$B/flows?window=1Y"
curl -sH "$K" "$B/sectors?window=3M&universe=nifty500"
curl -sH "$K" "$B/scanner?window=3M&universe=total&lane=proxy&limit=5"
curl -sH "$K" "$B/feeds"
```
Expected, from the SQL already run against the same warehouse (report §3):
- breadth `evaluated 976 · disclosed_rising 449 · single_amc 379 · disclosure_as_of 2026-09-01 · validated_study false`
- flows 1Y `12 rows · 2025-11-01..2026-10-01 · fii -503813 · dii 849222`
- sectors `Financial Services 45225 · Healthcare 24993`, `mf_window {requested 3, actual 1, exact false}`
- scanner on `universe=total`, `lane=proxy` → 114 rows; `classes {A 569, B 7, C 114, D 60}`
- scanner on `universe=nifty500` → `classes {A 458, B 0, C 0, D 42}`, `lanes.proxy 0`
