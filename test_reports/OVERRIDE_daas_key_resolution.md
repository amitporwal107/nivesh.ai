# OVERRIDE — DaaS API-key resolution fix (copilot_widgets + mf_intelligence)

- **Branch:** feat/research-qa-exercise
- **Date:** 2026-08-18
- **Author:** Claude (FULL_STACK_DEVELOPER)
- **Changed areas:** backend routes/services: **yes** · frontend src: no
- **Files:** `backend/routes/copilot_widgets.py`, `backend/services/copilot_tools/mf_intelligence.py`, `backend/tests/test_daas_key_resolution.py` (new)

REASON: End-to-end staging verification of the CHANGED code is not possible without deploying it,
and this app's staging deploys from `origin/dev` (`git reset --hard origin/dev`), which is also the
branch feeding the live login surface. Pushing to `dev` is a live deploy that the user has NOT
authorized in this session. The fix is therefore committed to a feature branch and verified as far as
it can honestly be verified without that deploy. Everything below is real, unedited output.

## What was wrong (measured on staging, not inferred)

`nivesh-staging-app-backend` environment, values redacted to length + sha256 prefix:

```
   NIDP_DAAS_BASE_URL         https://staging-data.niveshcopilot.com/daas
   NIDP_DAAS_INTERNAL_TOKEN   SET(len=36,sha=7e4aedd7)
   NIDP_DAAS_API_KEY          EMPTY
```

`copilot_widgets.py:62` and `mf_intelligence.py:119` read `NIDP_DAAS_API_KEY` **only**, so the key
resolved to `""` and `_daas_get` returned `None` on every call before reaching the network
(`if not _DAAS_KEY: return None`). Meanwhile `stock_intelligence.py:78` accepts either variable and
works — which is why the failure was silent and surface-specific rather than a visible outage.

## The credential the fixed code will use IS accepted by the staging DaaS

Run from inside the staging app container, using the same env var the fix now falls back to:

```
$ docker exec nivesh-staging-app-backend sh -lc \
    'curl -sS -o /tmp/o.json -w "%{http_code}" -H "X-API-Key: $NIDP_DAAS_INTERNAL_TOKEN" \
       "$NIDP_DAAS_BASE_URL/v1/stocks/screener?limit=1"'
200
{"data":[{"symbol":"3MINDIA","as_of_date":"2026-08-12","sector":"Diversified","industry":"Diversified",
"market_cap_bucket":"MID_CAP","market_cap_cr":39528.5,"roe_pct":29.5249,"debt_to_equity":0.0962,...
```

Key record backing it (staging `daas_api_keys`):

```
  key_prefix  |          name          |   plan   | rate_limit_rpm | daily_quota | status | expires
--------------+------------------------+----------+----------------+-------------+--------+---------
 nvd_id5o87h- | nivesh-staging-backend | internal |           6000 |             | active |
```

So the only unproven link in the chain is "the deployed process picks up the new code" — i.e. the deploy itself.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | drift guard | every DaaS caller references BOTH env vars | unit | assertion holds for all 3 callers | **PASS** |
| TC-2 | copilot_widgets | only `NIDP_DAAS_INTERNAL_TOKEN` set → key resolves to it | unit | `_DAAS_KEY == "tok-internal"` | SKIPPED (no fastapi in this env) |
| TC-3 | copilot_widgets | both set → `NIDP_DAAS_API_KEY` wins | unit | `_DAAS_KEY == "tok-api"` | SKIPPED (no fastapi in this env) |
| TC-4 | copilot_widgets | neither set → empty (degrade path preserved) | unit | `_DAAS_KEY == ""` | SKIPPED (no fastapi in this env) |
| TC-5 | staging precondition | `NIDP_DAAS_API_KEY` empty on the staging backend | api | EMPTY → old code dead | **PASS** (output above) |
| TC-6 | staging credential | the fallback credential authenticates to the staging DaaS | api | HTTP 200 + real rows | **PASS** (output above) |
| TC-7 | guard is not vacuous | pre-fix source would fail TC-1 | unit | 0 refs at HEAD | **PASS** (output below) |

## Unit test output (real, unedited)

```
$ cd /app/backend && python3 -m pytest tests/test_daas_key_resolution.py -q -rs
...sss                                                                   [100%]
=========================== short test summary info ============================
SKIPPED [1] tests/test_daas_key_resolution.py:67: app deps not installed in this environment
SKIPPED [1] tests/test_daas_key_resolution.py:76: app deps not installed in this environment
SKIPPED [1] tests/test_daas_key_resolution.py:86: app deps not installed in this environment
3 passed, 3 skipped in 0.04s
```

TC-2..TC-4 skip here because `fastapi` is not installed in this sandbox (`/opt/ray-env` has fastapi
but no pytest). They are NOT disabled — they execute wherever app deps exist (CI, the container).
TC-1 is source-level and environment-independent, which is why it carries the drift protection.

## TC-7 — the guard would have caught this

```
$ git show HEAD:backend/routes/copilot_widgets.py | grep -c NIDP_DAAS_INTERNAL_TOKEN
0
$ git show HEAD:backend/services/copilot_tools/mf_intelligence.py | grep -c NIDP_DAAS_INTERNAL_TOKEN
0
$ grep -c NIDP_DAAS_INTERNAL_TOKEN backend/routes/copilot_widgets.py
2
$ grep -c NIDP_DAAS_INTERNAL_TOKEN backend/services/copilot_tools/mf_intelligence.py
2
```

0 pre-fix = TC-1 would have failed before the change. The guard is real.

## NOT verified (explicitly)

- **The fixed code running on staging.** Requires a `dev` deploy — see REASON.
- **That `copilot_widgets` / `mf_intelligence` widgets now return data end to end.** Follows from TC-5
  + TC-6 + the code change, but is INFERRED, not observed. It must be re-run after deploy.
- **Prod.** Untouched and unverified. Prod DaaS is a separate process (`127.0.0.1:8083`, host uvicorn,
  `/opt/nidp/nidp.env`) from staging (`127.0.0.1:8084`, container, `/opt/nidp-staging/nidp.env`).
  Whether prod sets `NIDP_DAAS_API_KEY` or `NIDP_DAAS_INTERNAL_TOKEN` was NOT checked; the fix accepts
  either, so it is safe in both cases, but that is reasoning, not measurement.

## To close this override

Deploy the branch to staging, then re-run inside `nivesh-staging-app-backend`:
a real widget call through `copilot_widgets._daas_get` returning data instead of `None`, and one
`mf_intelligence` path returning rows. Replace this file with a functionality report ending
`## Verdict: PASS`.
