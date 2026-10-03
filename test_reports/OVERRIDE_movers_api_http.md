# OVERRIDE — Top Movers API: HTTP-layer verification not performed

REASON: The app backend has no local runtime in this workspace (no venv, no backend container —
only `nidp-daas-api-staging` runs here). The deployed staging API that would answer
`GET /api/movers` redeploys from `origin/dev`, so reaching it requires pushing to `dev`, which is
a **live deploy** that also redeploys the live login UI. Two things gate that and neither is mine
to decide:

1. **A live deploy needs the owner's go-ahead.** A `dev` push rebuilds on nivesh-app-vm, whose
   disk PROD shares; past deploys have crash-looped PROD mongo three times. It needs >=6 GB free
   checked first.
2. **The endpoints are behind `get_current_user`.** Verifying them over the wire needs a real
   `session_token` cookie for staging, which only the owner can issue. I did not fabricate one.

## What IS verified (see movers_api_20261003.md for the real output)

- The module imports and registers all three routes.
- Every endpoint's SQL ran verbatim against `nidp_staging` and returned real rows.
- The real functions in `backend/routes/movers.py` ran against 373 real `prices_eod` bars and 433
  real `index_eod` rows: attribution, β, rolling β, event metrics, CA flags and the three-state
  Move-odds badge all produced correct values, and three real defects were found and fixed.

## What is NOT verified

- HTTP status codes, auth rejection for an unauthenticated caller, JSON serialisation over the
  wire, and FastAPI query-param coercion/validation.
- `nidp.insider_sast` does not exist on staging yet, so the INSIDER / SAST lane has only been
  verified in its **degraded** path (`available: false`). Migration 157 must be applied and
  `insider_sast_to_pg.py` run before the populated path can be tested.

## To clear this override

1. Apply `backend/nidp/migrations/157_insider_sast.sql` to staging.
2. Load the lane: `python3 research/trendlyne/bin/insider_sast_to_pg.py --archive-only`, then COPY
   `research/trendlyne/ref/insider_sast.csv` into `nidp.insider_sast`.
3. Confirm >=6 GB free on nivesh-app-vm, then deploy and supply a staging `session_token`.
4. Run TC-03..07, TC-12 and TC-19 against `https://staging.niveshcopilot.com/api/movers`.


---

## Refreshed 2026-10-03 (Movers view session)

`backend/routes/movers.py` was edited again today: the event-lane assignment and the event-flag defects were
fixed, the bulk/block labels were changed to BOUGHT/SOLD for D2, and all three endpoints gained
`require_feature("move_odds")` **on top of** the existing session check.

REASON: the staging HTTP leg still cannot be exercised. Reaching the deployed API needs a push to `dev` — which
is a live deploy of both staging and the live login UI, and needs >=6 GB free on nivesh-app-vm — plus a staging
`session_token` that only the owner can issue. Neither is mine to do unprompted.

VERIFIED WITHOUT IT (see `movers_screen_20261003.md`): the lane and flag fixes, proven against the real module by
`scratchpad/lane_flags_check.py`; the D2 label rule; and the whole frontend contract, 63/63 Playwright cases.

STILL OPEN: TC-M01 (the 403 gate over HTTP), TC-M02..TC-M08 (window, CA withholding, three-state badge,
attribution identity and beta honesty against real staging rows).
