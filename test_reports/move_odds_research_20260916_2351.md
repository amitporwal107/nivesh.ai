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
| TC-1 | DaaS | latest for a published run | unit | rows sorted by p desc; no `rank` key; base_rate + run provenance present; field names contain no banned word  PASS (unit) + real staging DB: 994 rows sorted desc, no rank key |
| TC-2 | DaaS | unknown head or model | unit | 400 (DaaS validation convention; amended before first run)  PASS (unit) |
| TC-3 | DaaS | no run at all | unit | 200 status not_published, rows []  PASS (unit) |
| TC-4 | DaaS | latest run targets an earlier session than expected | edge | status not_published; the older run's rows are NOT returned  PASS (unit) + real staging DB at 16:00 clock: not_published, 0 rows |
| TC-5 | DaaS | refusal recorded for the expected session | failure | 503 withheld with reason; no rows  PASS (unit; later run outranks refusal) |
| TC-6 | DaaS | stock detail | unit | four estimates, inputs with data dates, events; media titles null  PASS (unit) + real staging DB: 4 estimates, 6 inputs, 1 event |
| TC-7 | DaaS | symbol not in the run | edge | 404  PASS (unit) + real staging DB: 404 |
| TC-8 | DaaS | non-internal key plan | edge | 403  PASS (unit) |
| TC-9 | App | non-allowlisted user, default flag | api | 403 feature_not_enabled on both routes  PASS (unit) |
| TC-10 | App | allowlisted non-admin | api | 200, DaaS payload passed through  PASS (unit) |
| TC-11 | App | set move_odds to everyone | edge | ValueError; mode unchanged  PASS (unit) |
| TC-12 | App | admin not on allowlist | edge | 403 (fail closed)  PASS (unit) |
| TC-13 | App | DaaS down / DaaS 503 withheld | failure | 502 upstream_unavailable / 503 passed through  PASS (unit) |
| TC-14 | App | flag flipped in the DB by another worker | edge | honoured within 30 s (TTL re-read)  PASS (unit) |
| TC-15 | Publisher | tampered snapshot | failure | refuses (hash mismatch), writes nothing  PASS (unit) |
| TC-16 | Publisher | same snapshot published twice | edge | one tpd_runs row (idempotent on snapshot_sha256)  PASS (unit) + staging: published twice → 1 run, 3,976 estimates |
| TC-17 | Publisher | inputs on record | unit | six inputs with values + data dates; delivery carries its own (lagged) date  PASS (unit) + staging: PNCINFRA delivery 47.88 @ 2026-09-15 |
| TC-18 | Publisher | media vs filing events | unit | media title NULL, filing title kept, max 3 per symbol, window 5 calendar days to the freeze  PASS (unit) + staging: media rows with a title = 0 |
| TC-19 | Publisher | rehearsal or preview snapshot | edge | refused unless it counts toward the verdict  PASS (unit) + real: 16 Sep preview snapshot refused |
| TC-20 | V5 | flag off vs on | e2e (mock) | rail item + mobile tab absent / present  PASS (Playwright, mocked) |
| TC-21 | V5 | final state | e2e (mock) | disclaimer above table; provenance strip; 4 tabs with base rates  PASS (Playwright, mocked) |
| TC-22 | V5 | table | e2e (mock) | sorted desc; no rank column; 50 per page; search filters  PASS (Playwright, mocked) |
| TC-23 | V5 | details expander | e2e (mock) | inputs with dates; events; media headline withheld text  PASS (Playwright, mocked) |
| TC-24 | V5 | not published / withheld | e2e (mock) | no percentages rendered; reason shown for withheld  PASS (Playwright, mocked) |
| TC-25 | V5 | 403 mid-session | e2e (mock) | access-not-enabled state; no percentages  PASS (Playwright, mocked) |
| TC-26 | V5 | D2 vocabulary | e2e (mock) | rendered text has no banned word (word boundaries; §8 disclaimer allowed)  PASS (Playwright, mocked) |
| TC-27 | V5 | C7 display precision | e2e (mock) | every shown % equals the API value at 1 decimal  PASS (Playwright, mocked) |
| TC-28 | Staging | DaaS latest with internal key | api | 200; row count = SQL count of tpd_run_estimates for the run and head  NOT RUN — DaaS router not deployed to staging |
| TC-29 | Staging | app routes with real sessions | api | non-allowlisted 403; allowlisted 200  NOT RUN — app not deployed; needs session tokens |
| TC-30 | Staging | real Playwright on /v5/research | e2e | allowlisted account sees the screen; top rows match SQL  NOT RUN — needs deploy + session token |

## API / Endpoint Tests (staging)
- **Deployed staging endpoints: NOT RUN.** The DaaS router and app routes are not on staging (deploy needs the user's go-ahead; the app deploys from `dev`, which also redeploys live login).
- **Router against the real staging database (local process, staging DaaS container's own DB settings, injected clock):**
  - Output:
    ```
    latest p_up5_1d: 200 final expected 2026-09-17 rows 994 base 0.0758
      first 3: [('PNCINFRA', 0.3655, 0.3102, 1), ('ANTELOPUS', 0.325, 0.4019, 1), ('RAYMOND', 0.2826, 0.4319, 3)]
      sorted desc: True | rank key present: False
      run: {'model': 'v4', 'data_as_of': '2026-09-16', 'target_session': '2026-09-17', 'frozen_at': '2026-09-16T15:20:22.247116+00:00', 'git_sha': '0dc20f9', 'scored': 994, 'train_end': '2026-08-31'}
      record: Jan–Aug 2025 165 0.3103 bands 8 | live: 0
    stock PNCINFRA: 200 {'p_down10_1d': 0.0246, 'p_down5_1d': 0.3102, 'p_up10_1d': 0.1039, 'p_up5_1d': 0.3655} | inputs 6 | events [('NSE filing', 'debarment', False)]
    stock NOSUCH: 404
    after close: not_published expected 2026-09-18 last published for 2026-09-17 rows 0
    ```
- **pytest** (`PYTHONPATH=.:/opt/ray-env/lib/python3.11/site-packages venv/bin/python -m pytest …`):
  - `nidp/tests/services/test_daas_move_odds.py nidp/tests/services/test_daas_api.py` → `49 passed, 7 warnings`
  - `tests/test_move_odds_routes.py tests/test_research_feature_flags.py` → `12 passed`
  - `nidp/tests/services/tpd_model nidp/tests/services/catalyst_intel` → `1 failed, 287 passed` (the failure is the live OpenAI smoke test: HTTP 429 insufficient_quota / credit_balance_exhausted on the account; unrelated to this feature)

## UI / Playwright Tests
- **Spec:** `frontend-v5/e2e/tests/research-move-odds.spec.ts` (mocked; fixtures labelled MOCK, values copied from the 17 Sep v4 snapshot)
  - Command: `npx playwright test e2e/tests/research-move-odds.spec.ts --project=desktop-chrome --reporter=list`
  - Output: `13 passed (21.4s)`
- **Regression:** `npx playwright test e2e/tests/research-access.spec.ts --project=desktop-chrome` → `7 passed`, `1 skipped` (pre-existing skip)
- **Build:** `npm run build` → `✓ built in 15.34s` (tsc -b clean)
- **Real-staging Playwright: NOT RUN** (needs the deploy and a session token).

## Data Correctness (staging)
- Migration `149_tpd_move_odds_publish.sql` applied to nidp_staging 2026-09-17 00:23 IST (additive; recorded in nidp.schema_migrations).
- Published the 2025 test record and the 17 Sep v4 run, then the run a second time:
  ```
  runs | 1
  run | 1 v4 2026-09-16->2026-09-17 scored 994 frozen 2026-09-16 20:50
  estimates | 3976
  estimates by head | p_down10_1d=994 p_down5_1d=994 p_up10_1d=994 p_up5_1d=994
  stocks | 994
  events | 641
  media rows with a title (must be 0) | 0
  model_record | 4
  band_record | 32
  top3 p_up5_1d | PNCINFRA 0.3655, ANTELOPUS 0.3250, RAYMOND 0.2826
  PNCINFRA delivery input | 47.88 @ 2026-09-15
  ```
- Result: PASS for the published data — counts equal the frozen snapshot (994 × 4), the second publish added nothing, top values equal snapshots_v4/2026-09-17.

## Inputs required from user
- Go-ahead for the staging deploys (DaaS, and the app via a push to dev, which also redeploys live login).
- Fresh staging session_tokens: one allowlisted non-admin, one non-allowlisted account.

## Verdict: BLOCKED
