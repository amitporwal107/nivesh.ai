# Functionality Verification Report — Move odds screen on /research

- **Branch:** feat/tpd3-mvp
- **Date:** 2026-09-16 (test cases authored 23:51 IST, before any implementation commit)
- **Author:** Claude (full-stack developer + design engineer + QA)
- **Environment:** local unit + mocked Playwright first; staging (staging.niveshcopilot.com / nidp_staging) after deploy go-ahead
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary
Builds the approved prototype (docs/ai_research/designs/Nivesh Move Odds (standalone).html) as a third screen of the V5
Research page. Frozen v4 snapshots are published insert-only into nidp_staging, served by an internal-plan DaaS router,
proxied by the app behind a fail-closed `move_odds` allowlist flag (default: allowlist, empty), and rendered in
/research. v4 is the model shown; the v4d nightly-refit challenger is not served (thresholds_lock_v4d_forward.json).

## Contract (W6a)
**Tables (migration 149, insert-only):** `nidp.tpd_runs` (one row per published snapshot: model, data_as_of,
target_session, frozen_at, snapshot_sha256 UNIQUE, lock/git sha, universe/scored counts, train rows/end, skipped
holidays, counts_toward_verdict), `nidp.tpd_run_estimates` (run_id, symbol, head, p, p_base_rate), `nidp.tpd_run_inputs`
(run_id, symbol, inputs jsonb with a data date per input), `nidp.tpd_run_events` (run_id, symbol, ord, event_time,
source_label, event_type, event_subtype, direction, title NULL for media sources, url, method), `nidp.tpd_band_record`
(model, head, source test_2025|live, band_lo, band_hi, rows, realised), `nidp.tpd_run_refusals` (model, target_session,
reason, detail jsonb, recorded_at).

**DaaS (internal plan keys only; any other plan → 403):**
- `GET /v1/move-odds/latest?head=p_up5_1d&model=v4` → `{data: {status: final|not_published, head, base_rate, run{...},
  rows[{symbol, company_name, sector, p, p_opposite, events_on_record}], band_record[], limits{...}, live_record{...}}}`.
  Rows sorted by p desc, no rank field. No run for the expected session → `status: not_published`, `rows: []`.
  A recorded refusal for the expected session → HTTP 503 `{status: withheld, reason, detail, target_session}` and no rows.
  Unknown head or model → 400 (the DaaS app's validation handler).
- `GET /v1/move-odds/stocks/{symbol}?model=v4` → `{data: {symbol, company_name, run{...}, estimates{head: p},
  inputs{...}, events[]}}`; symbol not in the run → 404.

**App (session cookie + `require_feature("move_odds")`):** `GET /api/move-odds/latest`, `GET /api/move-odds/stocks/{symbol}`.
Not allowlisted (admins included, UX-2 default) → 403 `feature_not_enabled`. DaaS unreachable → 502 `upstream_unavailable`.
DaaS 503 withheld passes through. Flag mode `everyone` is rejected for this flag. Flag state is re-read at most 30 s old.

**V5:** /research gains a "Move odds" rail item and mobile tab, rendered only when `me.features.move_odds`. States: final,
loading, not published, withheld, access not enabled (403 mid-session clears cached estimates), error.

## Test Cases
> Authored UP FRONT — after API + UI design, before implementation. One row per case.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | DaaS | latest for a published run | unit | rows sorted by p desc; no `rank` key; base_rate + run provenance present; field names contain no banned word | |
| TC-2 | DaaS | unknown head or model | unit | 400 (DaaS validation convention; amended before first run) | |
| TC-3 | DaaS | no run at all | unit | 200 status not_published, rows [] | |
| TC-4 | DaaS | latest run targets an earlier session than expected | edge | status not_published; the older run's rows are NOT returned | |
| TC-5 | DaaS | refusal recorded for the expected session | failure | 503 withheld with reason; no rows | |
| TC-6 | DaaS | stock detail | unit | four estimates, inputs with data dates, events; media titles null | |
| TC-7 | DaaS | symbol not in the run | edge | 404 | |
| TC-8 | DaaS | non-internal key plan | edge | 403 | |
| TC-9 | App | non-allowlisted user, default flag | api | 403 feature_not_enabled on both routes | |
| TC-10 | App | allowlisted non-admin | api | 200, DaaS payload passed through | |
| TC-11 | App | set move_odds to everyone | edge | ValueError; mode unchanged | |
| TC-12 | App | admin not on allowlist | edge | 403 (fail closed) | |
| TC-13 | App | DaaS down / DaaS 503 withheld | failure | 502 upstream_unavailable / 503 passed through | |
| TC-14 | App | flag flipped in the DB by another worker | edge | honoured within 30 s (TTL re-read) | |
| TC-15 | Publisher | tampered snapshot | failure | refuses (hash mismatch), writes nothing | |
| TC-16 | Publisher | same snapshot published twice | edge | one tpd_runs row (idempotent on snapshot_sha256) | |
| TC-17 | Publisher | inputs on record | unit | six inputs with values + data dates; delivery carries its own (lagged) date | |
| TC-18 | Publisher | media vs filing events | unit | media title NULL, filing title kept, max 3 per symbol, window 5 calendar days to the freeze | |
| TC-19 | Publisher | rehearsal or preview snapshot | edge | refused unless it counts toward the verdict | |
| TC-20 | V5 | flag off vs on | e2e (mock) | rail item + mobile tab absent / present | |
| TC-21 | V5 | final state | e2e (mock) | disclaimer above table; provenance strip; 4 tabs with base rates | |
| TC-22 | V5 | table | e2e (mock) | sorted desc; no rank column; 50 per page; search filters | |
| TC-23 | V5 | details expander | e2e (mock) | inputs with dates; events; media headline withheld text | |
| TC-24 | V5 | not published / withheld | e2e (mock) | no percentages rendered; reason shown for withheld | |
| TC-25 | V5 | 403 mid-session | e2e (mock) | access-not-enabled state; no percentages | |
| TC-26 | V5 | D2 vocabulary | e2e (mock) | rendered text has no banned word (word boundaries; §8 disclaimer allowed) | |
| TC-27 | V5 | C7 display precision | e2e (mock) | every shown % equals the API value at 1 decimal | |
| TC-28 | Staging | DaaS latest with internal key | api | 200; row count = SQL count of tpd_run_estimates for the run and head | |
| TC-29 | Staging | app routes with real sessions | api | non-allowlisted 403; allowlisted 200 | |
| TC-30 | Staging | real Playwright on /v5/research | e2e | allowlisted account sees the screen; top rows match SQL | |

## API / Endpoint Tests (staging)
_pending_

## UI / Playwright Tests
_pending_

## Data Correctness (staging)
_pending_

## Inputs required from user
- Go-ahead to apply migration 149 and publish snapshots into nidp_staging (additive, insert-only).
- Go-ahead for the staging deploys (DaaS, and the app via a push to dev, which also redeploys live login).
- Fresh staging session_tokens: one allowlisted non-admin, one non-allowlisted account.

## Verdict: BLOCKED
