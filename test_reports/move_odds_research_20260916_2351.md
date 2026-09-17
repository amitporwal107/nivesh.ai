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
| TC-31 | App | GET /api/move-odds/live gated; symbols validated (1–60, NSE symbol chars); payload passed through | unit | 403 not allowlisted; 422 bad symbols; 200 with quotes and entry_signal_validated=false | PASS (unit) + real Yahoo call: 50/50 quotes, unknown symbol → unavailable |
| TC-32 | Live | breakout checks on completed hourly bars only, first bar where all five hold, missing inputs → none; quote levels/touches | unit | matches the pre-registered rule exactly | PASS (unit, 8 cases) |
| TC-33 | V5 | Live column: last price, change, touch marker per row, equal to the live API; unavailable → "—"; refresh every 60 s while visible | e2e (mock) | values shown = fixture values | PASS (Playwright, fake clock) |
| TC-34 | V5 | Breakout checks panel in details: five checks, first-met bar, the failed 2025 test stated; no "entry"/"signal" wording | e2e (mock) | wording passes the D2 scan with "signal" added | PASS (Playwright) |
| TC-35 | Staging | live prices on the real page during market hours | e2e | shown values equal the live API at the same minute | PASS (real staging 10:15 IST: 20 cells = the payload the page received; prices move by the minute, so the check is against the page's own response) |
| TC-36 | Live + V5 | Entry signal (owner's decision 2026-09-17): ON only while all five checks hold at the latest completed hourly bar; row pill + Details state; failed 2025 test stated beside it; "entry signal" allowed, other D2 words still banned | unit + e2e (mock) + staging | pill and state equal the live payload's entry_signal | PASS (unit 19; mocked Playwright 15; real staging 10:57 before-11:15 state and 11:17 with real ON signals for MOREPENLAB and KMEW) |

## API / Endpoint Tests (staging)
- **Deploy (user-approved 2026-09-17):** commit eaa64d19 on `dev` (page files only). GitHub Actions: Deploy → nidp-stack-vm [staging] success; Deploy backend → nivesh-app-vm [staging] success; Deploy frontend → nivesh-app-vm [staging] success; Android APK success.
- **Deployed staging DaaS** (`nidp-daas-api-staging`, restarted 19:30:57Z, called inside the container with its internal key):
  ```
  internal token present: True
  p_up5_1d 200 final expected 2026-09-17 rows 994 base 0.0758 first [('PNCINFRA', 0.3655), ('ANTELOPUS', 0.325)] sorted True rank key False
  p_down5_1d 200 final expected 2026-09-17 rows 994 base 0.0402 first [('RAYMOND', 0.4319), ('ANTELOPUS', 0.4019)] sorted True rank key False
  p_up10_1d 200 final expected 2026-09-17 rows 994 base 0.0107 first [('PNCINFRA', 0.1039), ('DELTACORP', 0.0669)] sorted True rank key False
  p_down10_1d 200 final expected 2026-09-17 rows 994 base 0.0034 first [('ANTELOPUS', 0.0547), ('TBZ', 0.038)] sorted True rank key False
  stock PNCINFRA 200 {'p_down10_1d': 0.0246, 'p_down5_1d': 0.3102, 'p_up10_1d': 0.1039, 'p_up5_1d': 0.3655} inputs 6 events 1
  no key: 401 | bad key: 401
  ```
  SQL on nidp_staging for the same run: `p_down10_1d|994|0.0547`, `p_down5_1d|994|0.4319`, `p_up10_1d|994|0.1039`, `p_up5_1d|994|0.3655` → counts and maxima equal.
- **Deployed staging app, no session:**
  ```
  /api/healthz                                  HTTP 200 {"status":"ok","service":"portfolio_ingestion","version":"0.1.0","env":"staging"}
  /api/move-odds/latest?head=p_up5_1d           HTTP 401 ... "code":"AUTH-001","message":"Not authenticated"
  /api/move-odds/stocks/PNCINFRA                HTTP 401 ... "code":"AUTH-001","message":"Not authenticated"
  /api/move-odds-does-not-exist                 HTTP 404 ... "code":"RES-001","message":"Not Found"
  ```
  Served V5 bundle `assets/index-BkEb2CQV.js` contains `api/move-odds`. The saved staging session (June) answered `401 Session expired`.
- **Signed-in staging checks** (owner's session supplied 2026-09-17; token kept in a private file, never printed):
  - Before allowlisting: `auth/me HTTP 200 {'email': 'aporwal107@gmail.com', 'role': None, 'is_admin': True} | move_odds: False` and `move-odds/latest HTTP 403 ... "code":"AUTHZ-001","message":"feature_not_enabled"`.
  - Admin API: `POST add user HTTP 200`; `PUT mode=everyone HTTP 400 ... "Mode 'everyone' is not allowed for move_odds; allowed: off, allowlist"`; flag `('move_odds', 'allowlist', ['aporwal107@gmail.com'])` (temporary, for verification).
  - Allowlisted: `latest HTTP 200` on 8/8 calls; `latest: final expected 2026-09-17 rows 994 base 0.0758 first3 [('PNCINFRA', 0.3655), ('ANTELOPUS', 0.325), ('RAYMOND', 0.2826)] sorted True`; `stocks/PNCINFRA HTTP 200` with the four estimates equal to SQL.
  - **Bug found and fixed:** /auth/me answered `move_odds=True` on 5 calls and `False` on 3 (per-worker startup copies of the flags). Fix d87674f5 on dev (profile map refreshes on the gate's 30 s rule; new regression test; 13 passed). After its deploy (success 19:55:25Z): `1:200/True … 10:200/True`.
  - Removal: `DELETE user HTTP 200`, flag back to `('move_odds', 'allowlist', [])` at 19:56:26Z; at 19:56:38Z `403/False` on 10/10 calls.
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


### Live prices and breakout checks (added 2026-09-17)
- **Pre-registered test** (`.claude/workspace/ten-percent-days-3/evidence/entry_signal/PREREGISTRATION.md`, written 09:55 IST before any intraday data was fetched; `entry_signal_result.json`):
  ```
  primary_top10: candidates 1650, simulated 1592, first_hour_touch_rate 0.203
    signal:            trades 84, sessions 66, touch_rate 0.238, mean_net -0.0061, median -0.0049, win_rate 0.298, ci95 [-0.0098, -0.0022]
    unconditional_1015: trades 1269, sessions 164, touch_rate 0.109, mean_net -0.0029, win_rate 0.429, ci95 [-0.0053, -0.0006]
  secondary_p20: signal trades 380, touch_rate 0.274, mean_net -0.0012, ci95 [-0.0032, +0.0007]
  decision: trades_ge_100 false, ci_lower_gt_0 false, touch_not_below_baseline true → show_entry_signal false
  ```
- **Unit:** `tests/test_move_odds_routes.py tests/test_move_odds_live.py` → `18 passed`.
- **Real Yahoo call through the service** (09:57 IST, first hour still in progress so no checks yet):
  ```
  PNCINFRA   last   135.25  +0.6%  hi  +2.8% lo  -1.7%  touched []  bars None
  ANTELOPUS  last  1165.95  -0.4%  hi  +2.3% lo  -2.4%  touched []  bars None
  RAYMOND    last   978.00  -1.6%  hi  +0.4% lo  -2.8%  touched []  bars None
  NOSUCHSYM -> unavailable
  ```
- **Playwright (mocked):** `research-move-odds.spec.ts` → `15 passed (27.8s)`; `npm run build` → `✓ built in 16.73s`.
- **Deploy:** dev 18b08479 (files only). Staging TC-35 below once the workflows complete.

- **Deploy:** dev 18b08479 — Deploy backend, Deploy frontend and Android APK all `success` (04:37–04:43Z). Lowest free disk during the build: 877 MB.
- **Real-staging Playwright** (owner session; no mocks): `staging-move-odds-live.spec.cjs` →
  ```
  page received 50 live quotes (source Yahoo Finance, validated=false, fetched_at 2026-09-17T10:15:35.489147+05:30); cells equal the payload for 20, unavailable 0
    ✓  1 staging-move-odds-live.spec.cjs:13:1 › TC-35 live prices on the real page equal the payload the page received (4.0s)
    1 passed (4.8s)
  ```
  A first version compared cells against a separate API call and failed by design: prices move between calls. Screenshot reviewed: Live column renders (PNCINFRA ₹137.56 +2.3%); the wider table overflowed its region at 1280 px and shifted when a row opened → CSS fix with a fit assertion added to TC-33 (mocked spec re-run).

- **Entry signal deploy:** dev 826578c2 — Deploy frontend, Android APK, Deploy backend all `success` (05:17–05:25Z); lowest free disk during the build 20.7 GB (after the disk fix d595553d).
- **Real-staging Playwright at 10:57 IST** (owner session; no mocks), all three staging checks:
  ```
  payload 2026-09-17T10:56:57.078062+05:30: 50 quotes, 50 with checks (0 past the second bar), entry signal ON for 0: none
  page received 50 live quotes (source Yahoo Finance, validated=false, fetched_at 2026-09-17T10:56:56.959649+05:30); cells equal the payload for 20, unavailable 0
    ✓  1 staging-move-odds-live.spec.cjs:13:1 › TC-35 live prices on the real page equal the payload the page received (2.5s)
  details for PNCINFRA: Entry signal OFF. | table overflow 0px
    ✓  2 staging-move-odds-signal.spec.cjs:11:1 › TC-36 entry signal on the real page equals the live payload (2.7s)
    ✓  3 staging-move-odds.spec.cjs:13:1 › TC-30 allowlisted account sees Move odds on staging and every shown value equals the API (2.4s)
    3 passed (6.1s)
  ```
  The first TC-36 run failed on a test assumption (a check count before 11:15, when only the first bar has closed); the older TC-30/TC-35 staging specs still banned "entry"/"signal" and were updated to the owner's decision. A rerun after 11:15 IST covers the state with real check counts.

- **Real-staging rerun at 11:17 IST** (after the 10:15–11:15 bar closed):
  ```
  payload 2026-09-17T11:17:16.059891+05:30: 50 quotes, 50 with checks (50 past the second bar), entry signal ON for 2: MOREPENLAB since 10:15-11:15, KMEW since 10:15-11:15
  details for MOREPENLAB: Entry signal ON since the 10:15-11:15 bar (close ₹118.88). | table overflow 0px
    ✓  1 staging-move-odds-signal.spec.cjs:11:1 › TC-36 entry signal on the real page equals the live payload (3.1s)
    1 passed (4.0s)
  ```
  Screenshot reviewed: amber pill on MOREPENLAB's row; Details ON with all five checks and the failed 2025 test stated; RATNAVEER shows "+5% reached".

## UI / Playwright Tests
- **Spec:** `frontend-v5/e2e/tests/research-move-odds.spec.ts` (mocked; fixtures labelled MOCK, values copied from the 17 Sep v4 snapshot)
  - Command: `npx playwright test e2e/tests/research-move-odds.spec.ts --project=desktop-chrome --reporter=list`
  - Output: `13 passed (21.4s)`
- **Regression:** `npx playwright test e2e/tests/research-access.spec.ts --project=desktop-chrome` → `7 passed`, `1 skipped` (pre-existing skip)
- **Build:** `npm run build` → `✓ built in 15.34s` (tsc -b clean)
- **Real-staging Playwright** (no mocks; owner session, temporarily allowlisted): `playwright test -c playwright.config.cjs` →
  ```
  API: status=final expected=2026-09-17 rows=994 top=PNCINFRA 36.6%, ANTELOPUS 32.5%, RAYMOND 28.3%
  UI: 50 values equal the API; disclaimer above table; details for PNCINFRA open; no banned words
    ✓  1 staging-move-odds.spec.cjs:13:1 › TC-30 allowlisted account sees Move odds on staging and every shown value equals the API (3.7s)
    1 passed (5.0s)
  ```
  Screenshot reviewed: layout as designed. Cosmetic follow-up: "1 on record" and the "LOW ≤ −5%" header wrap to two lines at 1280 px.

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
- A staging session token (supplied by the user 2026-09-17). Allowlist membership remains the user's decision; the list is empty after verification.

## Verdict: PASS
