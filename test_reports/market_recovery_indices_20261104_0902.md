# Functionality Verification Report — Market Recovery › 2 · Nifty and Bank Nifty, every expiry separately

- **Branch:** feat/market-recovery-indices (from origin/dev 50a53a8b; commits dc582bec backend, ce87b13c frontend)
- **Date:** 2026-11-04 (IST)
- **Author:** Claude (Domain Expert Analyst + Full Stack Developer + QA)
- **Environment:** staging (nivesh-staging-app-backend container, NIDP staging warehouse, NSE F&O bhavcopy of 3 Nov) — pre-merge
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary
Owner, 4 Nov: "Please also put this nifty analysis here in the dashboard" (the per-expiry Nifty / Bank Nifty analysis given in
chat that morning) and "nifty analysis should be done on each of the expiry dates". Built `GET /api/market-recovery/indices`
(services/market_recovery/indices.py, DESIGN.md §9) and part "2 · Nifty and Bank Nifty" of the Market Recovery page
(RecoveryIndices.tsx), computed from our data every day: technicals, pivots, futures build-up, levels, and each live expiry's
PCR, max pain, straddle range, walls, fresh writing, cuts, read and rule-based setups (bull call / bear put spreads, iron
condor, hedge put spread), plus VIX, Bank Nifty's relative strength, FII / DII and what Nifty's expiries say together.
NOT verified: the deployed URL / page of this branch (needs merge + backend restart).

## Test Cases
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-I1 | technicals | EMA / RSI / ATR equal the scan-builder functions; pivots by formula; up / down streaks | unit | exact | PASS |
| TC-I2 | futures | build-up label for the 4 quadrants and the unknown cases | unit | as §9 | PASS |
| TC-I3 | expiries | weekly / monthly (last of month), Bank Nifty monthly-only, liquidity classes on 3 Nov's shapes | unit | as §9 | PASS |
| TC-I4 | one expiry | straddle range, top OI, adds, cuts, read; thin / too-thin reads | unit | hand-made chain values | PASS |
| TC-I5 | setups | strikes by rule, figures vs formula, credit check, illiquid leg fails, too-thin → none, wings skip untraded strikes | unit | as §9 | PASS |
| TC-I6 | levels / together | sorted, merged within 0.05%, capped; common floor, near ceiling, monthly max pain | unit | exact text | PASS |
| TC-I7 | route + wording | 200, 503 typed; every string passes the 3 Nov lint (Buy / Sell legs only) | unit | as stated | PASS |
| TC-I8 | real data | the endpoint on staging data with the owner's session vs the 4 Nov chat analysis and nidp SQL | api | 401 anon / 200 owner; figures equal | PASS |
| TC-I9 | UI | both indices, each expiry on its own row, setups by expiry with Buy / Sell legs, failing with reason, levels / futures / flows, 503 message, 390 px | e2e | as stated | PASS |
| TC-I10 | UI, real answer | the real answer rendered at 1280 / 390 px | e2e | no overflow, no page error, lint 0 | PASS |

## API / Endpoint Tests (staging)
pytest (throwaway `nivesh/backend:staging` container, branch tree read-only, `--network none`):
```
$ … python -m pytest tests/test_market_recovery_indices.py tests/test_market_recovery_strategies.py tests/test_market_recovery.py tests/test_compliance_wording_lint.py -q -p no:cacheprovider
145 passed, 2 warnings in 7.99s
```
TC-I8 (scratchpad `mr_idx_check.py`: the branch router and services loaded ahead of the deployed copy in the staging backend
container, the real flag gate, the owner's session cookie, real routes/fno chains; token never printed, removed after):
```
no cookie -> HTTP 401
owner -> HTTP 200 in 2.0s, 37,718 bytes
as_of 2026-11-03 vix {'close': 15.72, 'change_pct': 1.42, 'close_5ago': 16.4, 'change_5d_pct': -4.15, 'up_streak': 3, …} relative {'bank_minus_nifty_1d': -0.6, 'bank_minus_nifty_5d': -1.76, 'bank_minus_nifty_20d': -4.05}
flows {'as_of': '2026-11-03', 'fii_5d': 13478.26, 'fii_buy_days_5': 4} [{'date': '2026-11-03', 'fii': 6836.81, 'dii': -3678.85}, …]
Nifty 50 23810.85 +1.58% streak 4 5d 4.66 20d 5.56 | ema20 22988.99 ema50 23195.79 ema200 23907.99 rsi 66.59 (46.0) macd_hist 139.45 atr 299.92 | pivots {'p': 23701.5, 'r1': 23920.2, 'r2': 24029.55, …}
   fut {'expiry': '2026-11-23', 'close': 23780.5, 'change_pct': 1.59, 'oi_change_pct': -8.6, 'basis': -30.35, 'buildup': 'short_covering'}
   2026-11-09 weekly   6d active   pcr 1.14 mp 23600.0 atm 23800.0 straddle 374.65 ±1.57% 23436-24186 cw 24000.0 pw 23000.0
   2026-11-17 weekly  14d thin     pcr 1.11 mp 23500.0 atm 23800.0 straddle 518.65 ±2.18% 23292-24330 cw 24500.0 pw 23500.0
   2026-11-23 monthly 20d active   pcr 1.3 mp 23500.0 atm 23800.0 straddle 602.5 ±2.53% 23208-24413 cw 24000.0 pw 23000.0
   2026-12-01 weekly  28d too_thin pcr 1.22 mp 23400.0 …
   2026-12-29 monthly 56d thin     pcr 1.2 mp 24000.0 atm 23800.0 straddle 992.7 ±4.17% 22818-24804 cw 25000.0 pw 22000.0
   SETUP 2026-11-09 Bull Call Spread  passes net -4494.75 gain 8505.25 loss -4494.75 rr 1.89 be [23869.15] | Buy 23800 Call @149.9; Sell 24000 Call @80.75
   SETUP 2026-11-23 Iron Condor       passes net 7322.25 gain 7322.25 loss -8927.75 … | Sell 23000 Put @97.25; Buy 22750 Put @68.45; Sell 24000 Call @193.2; Buy 24250 Call @109.35
Bank Nifty 55540.05 +0.98% streak 2 … ema50 55617.62 ema200 56303.36 rsi 53.84 (35.66) …
   2026-11-23 monthly 20d active   pcr 0.97 mp 55600.0 atm 55500.0 straddle 1493.65 ±2.69% 54046-57034 cw 58000.0 pw 55000.0
together: ['Common floor: 23,500 — put writers added there in 4 of 4 series (62.2L in all).', 'Near ceiling: 24,000, the heaviest call strike of the weekly 9 Nov.', "The 29 Dec monthly's max pain is 24,000, above the close."]
token files left: 0
```
Bugs found on real data and fixed before this run: the chain summary sends a wall as {strike, oi} (walls were empty; the test
chain now uses that shape); a 1%-out iron-condor wing landed on untraded contracts priced at settlement (the Dec 25,250 call,
the Bank Nifty 58,600 call) → wings and hedge legs now come only from strikes that traded with open interest.

## Data Correctness (staging)
Every figure above equals the 4 Nov fact sheet built from read-only `nidp` SQL (scratchpad `index_analysis/facts.md`,
`queries.sql`): closes, EMA20/50/200, RSI 66.6 / 53.8, ATR, pivots, per-expiry PCR / max pain / straddles (9 Nov 1.14 / 23,600
/ 374.65; 23 Nov 1.30 / 23,500 / 602.50; Bank Nifty 0.97 / 55,600 / 1,493.65), futures short covering (−8.61% / −0.57% OI),
FII +6,836.81 / DII −3,678.85 and FII buyers on 4 of 5 sessions. Live Nifty expiries from `nidp.fno_bhavcopy` (IDO,
expiry > 3 Nov): 9, 17, 23 Nov, 1, 29 Dec; Bank Nifty 23 Nov, 29 Dec.

## UI / Playwright Tests
```
TSC_EXIT=0
BUILD_EXIT=0
✓ built in 24.34s
PREVIEW_READY_AFTER=2s
PW_EXIT=0
  ✓  102 … copilot-app-market-recovery.spec.ts:695:3 › … 2 · Nifty and Bank Nifty (§9) › TC-I9 each expiry on its own row, setups grouped by expiry with Buy / Sell legs, levels, futures and flows; Bank Nifty on its tab (1.2s)
  ✓  104 … :791:3 › … phone 390px › TC-I9 at 390 px part 2 stays inside the screen: its tables scroll in their own box, the setups stack (872ms)
  ✓  103 … :776:3 › … TC-I9 a failed index read shows the server's message inside part 2; the rest of the page stays (2.3s)
  104 passed (1.1m)
```
(specs: market-recovery incl. TC-E1..E6, TC-S8 ×5, TC-I9 ×3; compliance-wording; desk-market-desk; desk-shell; desk-scan-dashboard)

TC-I10 — the real answer rendered (scratch spec, scratchpad `mr-idx-real/`, frontend agent's run):
```
W1280 NIFTY rows=["2026-11-09:weekly:active","2026-11-17:weekly:thin","2026-11-23:monthly:active","2026-12-01:weekly:too_thin","2026-12-29:monthly:thin"] groups=["2026-11-09x4","2026-11-17x4","2026-11-23x4","2026-12-29x4"] overflow=0 lint=0
W1280 BANKNIFTY rows=["2026-11-23:monthly:active","2026-12-29:monthly:thin"] … overflow=0 lint=0   W1280 pageerrors=0
W390 NIFTY … overflow=0 lint=0   W390 BANKNIFTY … overflow=0 lint=0   W390 pageerrors=0
  2 passed (3.5s)
```

## Inputs required from user
- none.

## Verdict: PASS
