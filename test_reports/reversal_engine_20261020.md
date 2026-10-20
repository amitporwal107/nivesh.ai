# Functionality Verification Report — Sector-aware reversal candidates (reversal-rules.v1)

- **Branch:** feat/reversal-engine (worktree /home/deploy/nivesh-reversal-engine, from feat/trading-desk-backend f8e8f271)
- **Date:** 2026-10-20
- **Author:** Claude (Full-stack + QA + Domain analyst)
- **Environment:** staging (nidp_staging read-only for data checks)
- **Changed areas:** backend routes/services: yes · frontend src: yes
- **STATUS: IN PROGRESS** — deployed to staging 2026-10-20 (user-approved); authenticated external HTTP call and staging UI run still need a session token (OVERRIDE_reversal_engine.md). No PASS verdict is claimed.

## Scope (user decisions 2026-10-20)
Near-52-week-low reversal candidates: default 15 % of the rolling 252-session low, 20 % research threshold,
10/15/20 sensitivity. Proximity to the low is NOT a signal; a stock is a candidate only with stabilization evidence.
Unknown inputs are unknown, never neutral. Research / paper-trading scope only, no order execution.
Backtest: Nifty 500 primary, point-in-time, >= 5 yrs targeted, costs 0.25 % + 0.10 % round trip (higher case
0.40 % + 0.20 %), gross and net reported separately, walk-forward with an untouched final out-of-sample block.

## Test Cases
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| RV-1 | distance | (close/low252 - 1)*100 on a synthetic series; low exactly the 252-session minimum, window excludes older bars | unit | exact value; fewer than 252 bars -> None + `insufficient_history` | |
| RV-2 | threshold | 15.0 in / 15.01 out; configurable 20 and 10 | unit | boundary behaviour; threshold read from config, echoed in response | |
| RV-3 | not-a-signal | stock at 5 % above low with no stabilization evidence | unit | status `near_low_no_evidence`, not a candidate | |
| RV-4 | signals | higher low, low-not-new (>=5 sessions since low), RSI recovery, EMA20 reclaim, RS vs index, volume participation each true/false/unknown | unit | each signal reports value + threshold; missing input -> unknown, not false | |
| RV-5 | candidate gate | >=3 core signals true -> candidate; 2 true + 3 unknown -> not candidate, unknown listed | unit | exact counts in `evidence` | |
| RV-6 | trigger/invalidation | resistance = prior-20 high; trigger_ready within 3 %; confirmed on close > resistance with rvol; invalidation = prior-10 swing low - 0.5 ATR; close below -> `setup_invalidated` | unit | levels and status exact | |
| RV-7 | reward/risk | hypothetical target = 60-session high; R/R computed; R/R < min blocks `trigger_ready` | unit | value and gate | |
| RV-8 | gates | history < 252, illiquid (< 10 Cr), no traded value, ETF/series via setup_rules eligibility, pledge >= 50 % excluded, pledge 25-50 % warning, severe distress excluded | unit | first failing gate reported as `exclusion` | |
| RV-9 | score | six components, weights 20/25/15/20/10/10 sum to 100; all known -> weighted sum | unit | exact total | |
| RV-10 | unknowns | unknown component excluded and total renormalised; `coverage_pct`, `unknown_components` present; coverage < threshold caps status at watchlist | unit | never 0 or 50 substituted | |
| RV-11 | override | total 95 with a critical gate -> excluded/warning regardless | unit | gate wins | |
| RV-12 | sector-aware | financials: D/E not scored (unknown, with reason); non-financial: scored | unit | profile applied | |
| RV-13 | sector rotation | quadrant leading/improving/weakening/lagging from rs and slope; breadth; missing sector -> unknown | unit | exact quadrant | |
| RV-14 | catalyst | only announcements with filed_at <= as_of count; results within 7 days is a risk flag, not a score | unit | point-in-time | |
| RV-15 | explanation | every row has why/why_now/confirms/uncertain/invalidates; `uncertain` non-empty when anything unknown | unit | present | |
| RV-16 | purity | `evaluate` is a pure function of rows + as_of; identical output on repeat | unit | equal | |
| RV-17 | back-compat | scan-rules.v2 tests and the existing positional tests unchanged and green | unit | pass | |
| RV-18 | API | GET /api/positional/reversal-candidates: 200 shape, threshold param (10/15/20 only), 422 on bad, 502 upstream_unavailable (never empty list), auth required | api | per contract | |
| RV-19 | data | DaaS reversal snapshot on staging: row counts, sampled symbols' 52w low / dist match nidp.prices_eod recomputation | data | match | |
| RV-20 | UI | Reversal view in ScannerTab: threshold selector, sector context, fundamental quality, reversal status, catalyst, invalidation; unknown shown as "Unknown"; exclusion reasons visible; empty/error states | e2e | Playwright pass | |
| RV-21 | UI types | tsc --noEmit | build | clean | |
| BT-1 | backtest purity | decisions on date t use only data <= t; truncating future data does not change signals | unit | equal | |
| BT-2 | backtest costs | net = gross - round-trip cost; base and higher cases; not applied twice | unit | exact | |
| BT-3 | backtest metrics | horizons 5/10/20, +5/+10 hit, MAE, failed breakout, win rate on a synthetic panel with known answers | unit | exact | |
| BT-4 | walk-forward | chronological folds, final untouched OOS block never used for threshold choice | unit | enforced | |
| BT-5 | real run | run on the longest defensible real panel; coverage, universe method and survivorship caveat reported | data | report | |

## Results (real output, this session)
- pytest (staging image, tree read-only): `203 passed` for test_reversal_rules, test_reversal_candidates, test_reversal_backtest, test_scan_rules_v2, test_positional_scan_universe, test_positional_desk_fields, test_positional_engine, test_positional_calibration, test_positional_scenario. Backtest file after final edit: `19 passed`.
- tsc: `TSC_EXIT=0`.
- Playwright (vite build + preview, mocked APIs): reversal spec `11 passed (7.8s)`; full suite `485 passed (5.6m)`, 10 skipped, 0 failed.
- Data test: engine vs SQL on nidp.prices_eod_adjusted, 6 stocks, low/low date/close/distance identical (e.g. MSUMI 32.7, 2026-10-05, 35.38, 8.20).
- Real endpoint function replayed on staging rows: 407 returned of 1,377 within 23 %; 22 sectors.
- Not done: see 'Staging' below.

## Staging (real output, 2026-10-20 ~14:25 IST, branch feat/reversal-engine = origin/dev + 1 feature commit, merge b29cf81f)
Deployed with the user's explicit approval: NIDP VM `deploy/cloudpe/nidp/deploy.sh feat/reversal-engine` (DaaS, Query API, nginx all health OK), app VM `deploy/cloudpe/app/deploy.sh feat/reversal-engine` (`/api/healthz`, `/api/readyz`, `/v2/`, `/v5/` OK). Re-verified after merging 61 dev commits: pytest `203 passed`, `TSC_EXIT=0`, Playwright `550 passed`, 10 skipped, 0 failed.
- DaaS, called by the deployed app backend: `GET /v1/features/reversal-snapshot?max_dist_pct=25` -> `HTTP 200 in 2.9s as_of 2026-10-19 rows 457 prefilter {within_distance 1527, dropped_illiquid_or_no_traded_value 1070, returned 457} sectors 22`.
- Public route, no session: `GET https://staging.niveshcopilot.com/api/positional/reversal-candidates` -> `HTTP 401` (same as scan-universe). First attempt returned 404: the 4 uvicorn workers were stale after the deploy; `docker restart nivesh-staging-app-backend` fixed it (finding: the deploy script did not restart the workers on this run).
- Deployed route code in the staging container, full HTTP stack and real DaaS call, ONLY the login check stubbed: default -> 200 (as_of 2026-10-19, rows 100, status_counts trigger_ready 2 / early_reversal 115 / near_low_no_evidence 140 / excluded 76); near_pct=10 -> 200; near_pct=20&view=all&limit=5 -> 200 (5 rows); near_pct=4 -> 422; view=bogus -> 422. Row 0: MSUMI trigger_ready, 8.2 % above low, score 59.2, coverage 90 %, unknown [catalyst], invalidation "close below 32.27". Same rows as the local replay of the real snapshot.
- NOT done: an authenticated external HTTP call (needs a session cookie from the user) and a Playwright run against the live staging UI (needs login).
