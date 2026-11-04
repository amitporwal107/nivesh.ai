# Functionality Verification Report — Market Recovery › strategies with protection against a fall

- **Branch:** feat/market-recovery-strategies (worktree /home/deploy/nivesh-wt-market-recovery; merged with origin/dev e16fe80c, which includes #473)
- **Date:** 2026-11-04 (IST)
- **Author:** Claude (Domain Expert Analyst + Full Stack Developer + QA)
- **Environment:** staging (nivesh-staging-app-backend container, NIDP staging warehouse, NSE F&O bhavcopy of 3 Nov) — pre-merge
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary
Owner, 4 Nov ~01:30 IST: "For each of the scored stocks please provide trading strategies, we need to hedge the risk as
well", with five strategies pasted. Decisions (AskUserQuestion): leg words Buy / Sell on this page; all five shown, failing
ones greyed with the reason; a Nifty put hedge sized by beta for stocks without stock options; end-of-day premiums.
Built: `GET /api/market-recovery/strategies/{symbol}` (services/market_recovery/strategies.py, DESIGN.md §8) and the panel
"Strategies with protection against a fall" inside each candidate's open detail (RecoveryStrategies.tsx). Verified here:
rules and payoffs against hand-worked values, the route (flag, 404 not_scored, 503 chain_unavailable), the real endpoint on
staging data with the owner's session (pre-merge, in the backend container), Playwright (mocked API) and the real answers
rendered at 1280 / 390 px. NOT verified: the deployed URL and page for THIS branch (needs merge + backend restart).

Also recorded (PR #473, merged by the owner 06:59 IST): the deployed `GET /api/market-recovery` answers 401 without a
session and 200 with the owner's (2.30 s, as_of 2026-11-03, 490 scored), and the deployed page loads at 1440 / 390 px with
the owner's session (Playwright against https://staging.niveshcopilot.com: api 200, 5 checks, 18 sectors, 10 + 10
candidates, 10 excluded, no overflow, no page errors).

## Test Cases
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-S1 | strikes | each strategy's strikes from the plan; wrong-side fallbacks; missing strike | unit | DESIGN §8 table | PASS |
| TC-S2 | payoff | protective put, bull call spread, collar, bull put spread, put ratio backspread vs hand-worked max loss / profit / breakevens / R:R | unit | exact | PASS |
| TC-S3 | checks | R:R ≥ 1.5; credit ≥ ⅓ width; illiquid leg; missing price / strike → unavailable; settlement price when untraded | unit | fails / unavailable with reasons | PASS |
| TC-S4 | expiry | ≥ 14 days preferred, else ≥ 5, none | unit | as §8 | PASS |
| TC-S5 | Nifty hedge | strike via pick_put_strike, 5% cap, hedged value, cost %, −5/−10/−15% scenarios; no beta; illiquid put; Indian digit grouping; cap wording | unit | as §8 | PASS |
| TC-S5b | cap note | Target 1 above the highest listed call → one warning naming the strategies | unit | exact text | PASS |
| TC-S6 | route | 200; 404 not_scored; 503 chain_unavailable with the message; 422 bad symbol | unit (TestClient, real gate) | as API | PASS |
| TC-SW | wording | every string of both answer kinds + labels, notes, cap note passes the 3 Nov lint except Buy / Sell as leg actions and the four plan words | unit | no hits | PASS |
| TC-S7 | real data | the endpoint on staging data with the owner's session: LAURUSLABS (options), SYNGENE / MSUMI (Nifty hedge), an unscored symbol, no session | api | 200 / 200 / 404 / 401, figures sane | PASS |
| TC-S8 | UI | a detail fetches its stock once; five cards with Buy / Sell legs, failing greyed with reason; Nifty hedge card + caveat; 503 message; 390 px one column; backspread "Not applied" | e2e | as stated | PASS |
| TC-S9 | UI, real answers | the three real answers rendered at 1280 and 390 px | e2e | no overflow, no page error, lint 0 | PASS |
| TC-E1..E6 | regression | the Market Recovery view's own cases | e2e | unchanged | PASS |

## API / Endpoint Tests (staging)

**pytest** (throwaway container from `nivesh/backend:staging`, branch tree read-only, `--network none`), final tree:
```
$ ... python -m pytest tests/test_market_recovery_strategies.py tests/test_market_recovery.py tests/test_compliance_wording_lint.py tests/test_scan_builder_routes.py nidp/tests/services/test_daas_fundamentals_source.py -q -p no:cacheprovider
145 passed, 4 warnings in 8.21s
```
(First runs found harness mistakes only: tuple keyword arguments, no pytest-asyncio in the image, and one expected value
miscomputed by me — 75 × 24,000 = ₹18,00,000; fixed in the tests, code unchanged.)

**TC-S7 — the endpoint on real data, pre-merge** (scratchpad `mr_strat_check.py`: the branch router + services loaded
ahead of the deployed #473 copy, the real `require_feature` gate, the owner's staging session cookie, real `routes/fno`
chains; token never printed and removed after each run):
```
no cookie -> HTTP 401
LAURUSLABS -> HTTP 200 in 3.3s kind=options as_of=2026-11-03 expiry=2026-11-23 (20d) lot=425 spot=2322.99 plan={'close': 2323.0, 'entry_low': 2285.27, 'stop_loss': 2096.64, 'target_1': 2775.72, 'target_2': 3002.08}
  Protective Put         passes      net=-27327.5 maxP=unl maxL=-28602.5 BE=[2387.3] RR=5.77
      legs: Buy 1x Shares  @2323.0(c) oi=None vol=None; Buy 1x Put 2320.0 @64.3(c) oi=192525 vol=2139
  Bull Call Spread       passes      net=-25925.0 maxP=127075.0 maxL=-25925.0 BE=[2381.0] RR=4.9
      legs: Buy 1x Call 2320.0 @63.65(c) oi=242675 vol=3182; Sell 1x Call 2680.0 @2.65(c) oi=222275 vol=1167
  Collar                 passes      net=-3421.25 maxP=148303.75 maxL=-98196.25 BE=[2331.05] RR=1.51
  Bull Put Credit Spread fails       net=15151.25 maxP=15151.25 maxL=-61348.75 BE=[2244.35] RR=0.25
      why: Reward : risk at least 1.5: 0.25 : 1; Credit at least a third of the strike width: credit ₹15,151 vs width ₹76,500
  Put Ratio Backspread   passes      net=18232.5 maxP=817232.5 maxL=-75267.5 BE=[1922.9, 2277.1] RR=None
  warnings: ['Target 1 (2,775.72) is above the highest listed call (2,680): the Bull Call Spread and the Collar write the 2,680 call, so their gains are capped there.']
SYNGENE -> HTTP 200 in 0.5s kind=index_hedge as_of=2026-11-03 expiry=2026-11-17 (14d) lot=65 spot=23810.85
  index hedge: passes  put 22650.0 @37.25 cost/lot=2421.25 hedged=2188807.0 beta=0.71 cost%=0.11 fall=5.0% oi=32955 vol=756
      One Nifty lot (65 × 23,811) hedges about ₹21,88,807 of SYNGENE at a beta of 0.71; the put strike is the lowest within 5.0% of Nifty (the stock's 12.1% distance to its Stop loss ÷ beta 0.71 = 17.1%, capped at 5%).
      {'label': 'Nifty -5%', 'nifty_move_pct': -5, 'put_pnl': -491.24, 'stock_loss': -77385.26}
      {'label': 'Nifty -10%', 'nifty_move_pct': -10, 'put_pnl': 76894.03, 'stock_loss': -154770.52}
      {'label': 'Nifty -15%', 'nifty_move_pct': -15, 'put_pnl': 154279.29, 'stock_loss': -232155.79}
MSUMI -> HTTP 200 in 0.5s kind=index_hedge ... hedges about ₹14,20,565 of MSUMI at a beta of 1.09 ...
NOTASTOCK -> HTTP 404 {"detail":{"code":"not_scored","message":"NOTASTOCK is not among the stocks scored on this page (2026-11-03)."}, ...}
token files left: 0
```
Review findings acted on (from the first real runs): the backspread's "max profit" needs the stock to collapse → its R:R is
now null ("Not applied"); a 10% Nifty cap picked a ~8% OTM put for SYNGENE (nothing at −5%, ~15% of the loss at −10%) → cap
5% (now ~50% at −10%, ~66% at −15%); LAURUSLABS / BOSCHLTD list calls only up to 2,680 / 55,000, below Target 1 → a note.

## Data Correctness (staging)
```
-- nidp.fno_bhavcopy, 3 Nov, expiry 23 Nov: listed strikes
 LAURUSLABS | CE | 48 | 1680 | 2680        (Target 1 2,775.72 is beyond the highest listed call: the cap note is right)
 LAURUSLABS | PE | 50 | 1600 | 2680
 BOSCHLTD   | CE | 27 | 40000 | 55000
-- 20 listed candidates with stock options on 3 Nov: 12 (LAURUSLABS, DRREDDY, HEROMOTOCO, DIVISLAB, SONACOMS, TECHM, BOSCHLTD,
   WIPRO, BSE, TVSMOTOR, UNIONBANK, TRENT); none for BSOFT, CHENNPETRO, FSL, LTTS, MSUMI, PPLPHARMA, SYNGENE, ZENSARTECH
```
Leg premiums are the bhavcopy close of 3 Nov (all five LAURUSLABS legs traded: volumes 1,167–3,512, OI 1.7–9.3 L); the
Nifty 22,650 PE (17 Nov) traded 756 with OI 32,955. Payoff maths is services/strategy_plan/payoff.py, cross-checked by the
hand-worked TC-S2 cases.

## UI / Playwright Tests
Playwright container (`mcr.microsoft.com/playwright:v1.47.0-jammy`, repo node_modules volume, Chromium 1223), final merged
tree, `--network none`, every /api call mocked with MOCK fixtures:
```
TSC_EXIT=0
BUILD_EXIT=0
✓ built in 24.07s
PREVIEW_READY_AFTER=2s
PW_EXIT=0
  ✓   97 … copilot-app-market-recovery.spec.ts:440:3 › … TC-S8 a detail asks for its stock's strategies once: five strategies, Buy / Sell legs, failing ones greyed with the reason (1.2s)
  ✓   98 … :513:3 › … TC-S8 a stock without stock options shows the Nifty put hedge, its sizing and the caveat (1.1s)
  ✓  101 … :567:3 › … TC-S8 at 390 px the strategies stack in one column and the page does not scroll sideways (879ms)
  ✓   99 … :534:3 › … TC-S8 a failed strategies answer shows the server's message inside the detail; the rest of the detail stays (2.4s)
  101 passed (1.1m)
```
(specs: market-recovery incl. TC-E1..E6 and TC-S8 ×5, compliance-wording, desk-market-desk, desk-shell, desk-scan-dashboard)

TC-S9 — the real answers (TC-S7 output) rendered through a scratch spec (scratchpad `mr-strat-real/`, not in the repo):
```
W1280 LAURUSLABS cards=["protective_put:passes","bull_call_spread:passes","collar:passes","bull_put_spread:fails","put_ratio_backspread:passes"] hedge=0 overflow=0 pageerrors=0 section=307..1225 lint=0
W390 LAURUSLABS cards=[…same…] hedge=0 overflow=0 pageerrors=0 section=43..347 lint=0
W1280 SYNGENE cards=[] hedge=1 overflow=0 pageerrors=0 … covers="One lot hedges about ₹21,88,807 of SYNGENE (beta 0.71)" rows=3 lint=0
W390 SYNGENE / W1280 + W390 MSUMI: overflow=0 pageerrors=0 lint=0
  6 passed (6.5s)
```
The run before showed `lint=1` on LAURUSLABS: my cap note said "gains stop there" ("stop" is a banned word) → reworded to
"capped there" and the note added to the backend wording test.

## Inputs required from user
- none (the owner's staging session token on this VM was valid).

## Verdict: PASS
