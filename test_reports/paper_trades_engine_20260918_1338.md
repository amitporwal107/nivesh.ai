# Functionality Verification Report — Ten-Percent Days Paper Trade Simulation Engine v1

- **Branch:** feat/paper-trades-page (page, migration, DaaS, app) · feat/paper-trade-engine (engine, off feat/tpd3-mvp)
- **Date:** 2026-09-18
- **Author:** Claude (full-stack + QA + domain + design engineering)
- **Environment:** staging (staging.niveshcopilot.com / nidp_staging)
- **Changed areas:** backend routes/services: yes · frontend src: yes
- **Commits:** rules `c3a9fc7e` (pre-registration, 13:37:49 IST) · engine `d7214b91`, `917cf327`, `b3305593` (feat/paper-trade-engine, local) · page `ee010831` (feat/paper-trades-page → pushed to `dev` 15:18:40 IST)

## Summary
Owner's PRD "Paper Trade Simulation Engine v1" + design "Paper Trade Engine standalone (1).html". Scope chosen by the
owner (2026-09-18 13:3x IST): engine + full page, forward + labelled historical replay, ATR-based target/stop.
Rules pre-registered before any outcome: rules_v1.json (sha256 ea4bf382…, commit c3a9fc7e, 2026-09-18T13:37:49+05:30).

## API / UI design (fixed before implementation)
DaaS (internal plan only):
- `GET /v1/paper-trades/portfolio?sample=forward|replay&portfolio=P5-NEXT|P10-NEXT[&prediction_date=]` — provenance,
  the five positions with entry/levels/latest observation/exits, the top of the ranked universe with outcome paths,
  exceptions, concentration, and the list of prediction dates.
- `GET /v1/paper-trades/trades/{trade_id}` — trade, six daily observations, lifecycle log, all exit modes.
- `GET /v1/paper-trades/evaluation?sample=&portfolio=` — the latest stored evaluation (metrics, buckets, benchmarks,
  cost sensitivity, caveats). Forward and replay are separate payloads; never pooled.
App (move_odds allowlist): `/api/paper-trades/{portfolio,trades/{id},evaluation}` (pass-through) and
`/api/paper-trades/live?portfolio=` (Yahoo live quotes → target/stop experiment status on the pre-registered levels).
V5: Research → "Paper" tab with the design's three screens (Today's portfolio · Trade path · Evaluation).

## Test Cases
> Authored UP FRONT — after API + UI design, before implementation. Results filled in 2026-09-18 15:3x IST.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-P1 | engine | eligibility filters exclude with their id; rank ties by symbol; top 5 reproducible | unit | excluded rows keep reason, rank NULL; same input → same 5 | PASS |
| TC-P2 | db | prediction snapshots immutable | data | UPDATE/DELETE raise | PASS (staging) |
| TC-P3 | engine | entry session = snapshot target_session across a holiday; model/panel disagreement aborts | unit | never weekday arithmetic | PASS |
| TC-P4 | engine | entry at official open; MISSING_OPEN, SUSPENDED, UPPER/LOWER_CIRCUIT_OPEN, GAP, ILLIQUID, thin session | unit | statuses/flags per rules | PASS |
| TC-P5 | engine | bonus ex-dated inside the window; gap on the adjusted previous close | unit | path continuous on the entry basis | PASS |
| TC-P6 | engine | running return, high watermark, drawdown, MFE/MAE | unit | hand values | PASS |
| TC-P7 | engine | EOD-1/3/5/FIXED/TARGET_STOP incl. tie → stop, gap fills, partial windows OPEN | unit | exit session and price per rules | PASS (found and fixed a bug: every EOD mode read OPEN) |
| TC-P8 | engine | Wilder ATR14, support, 8% cap, method, R/R | unit | reference numbers | PASS |
| TC-P9 | engine | costs 0.25/0.50/1.00 separate from gross | unit + data | net = gross − cost | PASS |
| TC-P10 | engine | benchmarks A_ALL, A_RANDOM5, B_MATCHED, C_MOVEMENT, D_NIFTY50 | unit | deterministic, rules-conformant | PASS |
| TC-P11 | engine | Newey–West, overlapping cohorts, buckets and calibration error | unit | reference computations | PASS |
| TC-P12 | engine | forward counting rule; counted-only evaluation; null when nothing counts | unit | pre-registration sessions excluded | PASS |
| TC-P13 | engine | post-date bars changed ×1.37 and a later bonus: snapshot, eligibility, levels unchanged | unit (mutation) | identical | PASS |
| TC-P14 | engine | idempotent re-run | unit + data | no duplicates; identical values | PASS (staging) |
| TC-P15 | db | migration 151 applied; selections recomputed independently | data | row in schema_migrations; 0 disagreements | PASS |
| TC-P16 | data | staging snapshot values = the frozen CSVs | data | exact to NUMERIC(8,5) | PASS (11,946 values; 4 at 5.005e-6 = double rounding, see Known issues) |
| TC-P17 | data | entry price = nidp.prices_eod official open | data | exact | PASS (1,645 / 1,645) |
| TC-P18 | data | replay sessions/trades; forward and replay separate | data | 165 sessions × 2 portfolios; never pooled | PASS |
| TC-P19 | data | Yahoo ^NSEI vs NSE Nifty 50 on every overlapping date | data | equal to the paisa | PASS (134 / 134 identical open and close) |
| TC-P20 | api | DaaS shapes, internal-plan gate, 404, bad params | api | as designed | PASS (unit + staging) |
| TC-P21 | api | app routes behind move_odds; pass-through; DaaS down → 502 | api | as designed | PASS (unit); staging: routes deployed (401 unauthenticated vs 404 unknown) — logged-in call BLOCKED on session |
| TC-P22 | api | live status: await entry, UC open, target, stop, both-touched, gap, stale-date bars, unavailable | unit + real Yahoo | per pre-registered levels | PASS (unit 9) + real Yahoo run below |
| TC-P23 | ui | Paper rail only with move_odds; frozen values; P5/P10; older date | e2e mocked | values equal fixture | PASS |
| TC-P24 | ui | sizing: loss limit binds at each leg's stop, equal legs, custom basket, fixed stop | e2e mocked | hand-computed rupees | PASS |
| TC-P25 | ui | trade path rows, lifecycle log, exit modes | e2e mocked | as payload | PASS |
| TC-P26 | ui | evaluation: forward/replay separate; not established below 60 | e2e mocked | as payload | PASS |
| TC-P27 | ui | 403 / error+retry / empty states; no NaN/undefined; wording scan | e2e mocked | clean | PASS |
| TC-P28 | ui | 390 px: neither the document nor the screen's scroll region scrolls sideways | e2e mocked | pass | PASS (found and fixed three overflows) |
| TC-P29 | staging | deployed endpoints answer real data | api (real) | 200 with real rows | PASS for DaaS (below); app leg BLOCKED on session |
| TC-P30 | staging | page renders real data; cells equal the payload | e2e (real) | pass | BLOCKED — needs the owner's staging session_token |

## Engine / unit tests (local, real commands)
- `venv/bin/python -m pytest nidp/tests/services/tpd_model/test_paper_engine.py -q` → `19 passed in 1.35s` (rc 0)
- whole `nidp/tests/services/tpd_model` → `280 passed in 65.61s` (rc 0)
- DaaS: `/opt/nidp/venv/bin/python -m pytest nidp/tests/services/test_daas_paper_trades.py nidp/tests/services/test_daas_move_odds.py nidp/tests/services/test_daas_move_odds_profile.py` → `31 passed` (rc 0)
- App: `pytest tests/test_paper_trades_routes.py tests/test_move_odds_routes.py tests/test_move_odds_live.py` → `33 passed in 1.21s` (rc 0)

## Data Correctness (staging, nidp_staging)
Forward applied 14:05:42 IST, replay applied 14:17:19 IST (one transaction each). Footprint 316 MB (PG volume free 3,848 → 3,532 MB).
```
 rule_sets 1 · snapshots 3,982 fwd + 327,002 replay · trades 20 + 1,650 · observations 9,820 · exits 8,225 · events 11,576
 universe outcomes 328,294 · benchmark rows 9,960 · index bars 424 (YAHOO_NSEI 290: 2025-01-01..2026-07-10, NSE_IND_CLOSE 134) · evaluations 4
second forward apply: counts unchanged 3982/20/70/50/2 (idempotent)
UPDATE snapshot → ERROR: tpd_paper_prediction_snapshots is immutable (UPDATE refused); insert a new prediction_version that supersedes it
DELETE snapshot → ERROR: tpd_paper_prediction_snapshots is immutable (DELETE refused); ...
selection recomputed (row_number by probability desc, symbol): forward P5/P10 10+10 agree, replay 825+825 agree, 0 disagreements
entry = NSE open: forward 10/10, replay 1,635/1,635; 0 entries without an NSE row; 0 moved entry dates
EOD-1/3/5/FIXED gross = NSE close / entry − 1 (no CA): 1,645 / 1,626 / 1,615 / 1,609 exact (max |diff| 5.0e-7)
net = gross − 0.25% (sens. 0.50/1.00): 8,120/8,121 (the rest differ by 1e-6: NUMERIC(12,6) rounding each column)
open == previous close on liquid bars (Aug–Sep): 6,645 rows, 0 outside the day's range → real traded opens, no flag needed
```

## API / Endpoint Tests (staging)
**Deploy:** `dev` ee010831 pushed 15:18:40 IST. GitHub runs: NIDP (DaaS) success, frontend success, Android success, **backend: failure** — the
script's 60-second health wait (30 × 2 s) expired; the container became healthy afterwards (15:28 `GET /api/healthz` → 200). Likely the concurrent
frontend image build on the same VM (UNVERIFIED). Staging DaaS container restarted 09:51:07Z and serves the new router:
```
portfolio forward P10 16-Sep: 200 [('PNCINFRA','ENTERED',132.48,121.8816,0.050867), ('DELTACORP','ENTERED',55.56,51.66,0.008119), ('RPEL',...,0.065479), ('KPEL',...,0.01124), ('AEROENTER',...,0.082105)]
portfolio replay P5 latest: 200 2025-08-28 165 dates; ['OLAELEC','KIOCL','HLEGLAS','GARUDA','RTNINDIA']
trade 531: 200 POCL ['PREDICTED','SELECTED','PENDING_ENTRY','ENTERED','MONITORING','EXITED','EVALUATED']
evaluation replay P10: 200 165 sessions; EOD-1 net -0.003574 edge 0.000217 | Not established: the 95% interval for the edge against every eligible stock includes zero.
no key: 401  bad key: 401
```
App routes on staging (no session): `/api/paper-trades/portfolio` 401, `/api/paper-trades/live` 401 "Not authenticated", `/api/paper-trades/no-such` 404,
`/api/no-such-route-xyz` 404 → the new routes are deployed. V5 bundle `index-B_9aCz-c.js` contains `paper-screen` and `/api/paper-trades/portfolio`.

**Live status, real Yahoo 5-minute bars (services/paper_trades_live.live_status on the real forward payload), 15:29 IST:**
```
P5-NEXT (predicted 17 Sep, entry 18 Sep, not counted): target 2 · holding 3
 SHAREINDIA entry 221.63 stop 203.90 target 232.71 → +5.0% touched 10:40 | RATNAVEER 306.20 / 281.70 / 321.51 → touched 09:55
 PNCINFRA 139.66 / 128.49 / 146.64 hold | TRIVENI 235.00 / 216.20 / 246.75 hold | TEGA 1907.10 / 1754.53 / 2002.45 hold
P10-NEXT: holding 5 (ALOKINDS, QUADFUTURE, PNCINFRA, MOTISONS, CAMLINFINE); every stop CAP_8PCT
```

## UI / Playwright Tests
- mocked `npx playwright test e2e/tests/research-paper-trades.spec.ts --project=desktop-chrome` → `10 passed (22.6s)` (rc 0)
- regression `research-move-odds.spec.ts research-access.spec.ts` → `53 passed (1.5m)` (rc 0)
- `npm run build` (tsc -b + vite build) → `✓ built in 20.06s` (rc 0)
- real staging (TC-P30): **not run — needs the owner's staging session_token** (the 12:07 IST session was deleted after the move-odds runs).
- screenshots for visual review: taken, not reviewed (the image viewer's hook timed out) — UNVERIFIED visually.

## Known issues / caveats
- Probabilities are pre-rounded to 8 dp before NUMERIC(8,5) (double rounding at exact halves, |err| ≤ 5.005e-6). Left as is: changing it would make the
  next run disagree with the immutable rows. The frozen CSV (hash in every row) is the record.
- The 8% risk cap sets almost every stop (volatile picks: ATR14 ≈ 7% of price), so P5 is +5% vs −8% (R:R 0.625) by construction.
- Replay: sector and names are today's; stocks delisted since 2025 are absent; the walk-forward ran in 2026.
- Not built: PRD §16 daily/5-session/weekly reports; SWING portfolios (no 5-session head); direction/expected-return fields are NULL (model has none).
- Engine code lives on local branch feat/paper-trade-engine (off feat/tpd3-mvp, which is not on dev); the nightly job runs from that worktree.

## Inputs required from user
- A fresh staging `session_token` for an allowlisted account (TC-P29 app leg, TC-P30 real UI run).

## Verdict: BLOCKED
Everything except the logged-in staging leg is verified above; TC-P29 (app route with a session) and TC-P30 are blocked on the session token.
