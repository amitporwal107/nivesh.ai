# Functionality Verification Report — Market Desk › Market Recovery (recovery-radar-v1)

- **Branch:** feat/market-recovery (worktree /home/deploy/nivesh-wt-market-recovery, from origin/dev 5152e19d)
- **Date:** 2026-11-04 (IST)
- **Author:** Claude (Domain Expert Analyst + Full Stack Developer + QA)
- **Environment:** staging (nivesh-staging-app-backend container, NIDP staging warehouse via DaaS) — pre-merge; branch head after merging origin/dev db9e0001
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary
The owner's pasted "Market Recovery Stock Selection Engine" proposal, built as a new view under 03 Market Desk named
"Market Recovery" (owner, 3 Nov: placement, name, and the standard plan words Entry zone · Stop loss · Target 1 · Target 2
on this page only). `GET /api/market-recovery` (flag `market_recovery`, owner allow-list) returns the recovery check (5
checks, 30-session breadth series, cap participation), an NSE-industry sector table with the top 5 leaders, the top 10
Nifty 500 candidates inside the leading sectors plus the top 10 outside them (score /100 in 5 components, recovery
acceleration, setup, plan, reasons, cautions, data gaps), and the high scorers excluded as false signals. Rules and test
cases: docs/market_recovery/DESIGN.md. Verified here: unit rules, real-data run and data cross-check on staging, the route
over HTTP with the owner's real session pre-merge, and the UI with Playwright (mocked API). NOT verified: the deployed URL
(needs merge + backend restart) and a live browser check of the deployed page.

## Test Cases
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-U1 | regime | each status path | unit | confirmed / underway / early / fragile / none | PASS |
| TC-U2 | breadth | % above SMA20/50, % advancers on a small panel | unit | equals a hand count | PASS |
| TC-U3 | sectors | median RS, rs_change, state, rank, leaders, < 5 members left out | unit | as DESIGN §2 | PASS |
| TC-U4 | score | full marks = 100; ramps; cash-flow gap rescales; < half data scores 0; financials profile | unit | as §3 | PASS |
| TC-U5 | traps | dead-cat; short covering (1-day, 2-day, OI noise); extended; low-base volume | unit | as §6, §3 | PASS |
| TC-U6 | setups | breakout / ema_reclaim / pullback / accumulation / relative_strength | unit | first match | PASS |
| TC-U7 | plan | 1–3 ATR risk; T1 both branches; T2 ≥ T1 + 1R; entry zone | unit | as §7 | PASS |
| TC-U8 | acceleration | 6 rows, improving ≤ of, score 0–100, pct ranks | unit | as §4 | PASS |
| TC-U9 | gates | no bar / history / liquidity / market cap counted | unit | as gates | PASS |
| TC-U10 | stale | prices 6 days old | unit | StaleData | PASS |
| TC-R1 | route | flag default owner-only (403 other), 200 owner, typed 503 data_unavailable / stale_data | unit (TestClient, real gate) | as API | PASS |
| TC-W | wording | every API string passes the 3 Nov lint except the four plan words | unit | no hits | PASS |
| TC-A1 | real data | engine on staging DaaS + price panel | api | as_of latest, ≥ 400 scored, 5 checks, ≤ 10 candidates with 5 components + plan | PASS |
| TC-A2 | data check | engine vs `nidp` SQL | data | Nifty/VIX/SMA20 exact; breadth within 2 pp; RSI within 1.5; r20 within 0.5 pp | PASS |
| TC-A3a | route over HTTP, pre-merge | branch router + real gate + real cookie sign-in, in the staging backend container | api | 401 without cookie; 200 with the owner's session | PASS |
| TC-E1 | UI | flag on: Market Recovery last in the switcher; check, breadth, sectors, candidates render | e2e | visible | PASS |
| TC-E2 | UI | a candidate's detail: 5 components, 5-session table, plan with Entry zone · Stop loss · Target 1 · Target 2, reasons | e2e | visible | PASS |
| TC-E3 | UI | flag off: five views in the switcher; the URL says not enabled without calling the API | e2e | as stated | PASS |
| TC-E4 | UI | 503 shows the server's message; 403 reads as not enabled; no candidates = empty state | e2e | as stated | PASS |
| TC-E5 | wording | page lint with a detail open, only the four plan labels removed | e2e | no banned word | PASS |
| TC-E6 | UI | 390 px: no sideways page scroll; tables scroll in their own box | e2e | scrollWidth ≤ width | PASS |
| TC-E7 | UI, real answer | the real 3 Nov API answer rendered at 1280 and 390 px (scratch spec, transport mocked) | e2e | no overflow, no page error | PASS |

Post-merge checks, NOT part of this verdict (they cannot run before the merge): the deployed URL
`GET https://staging.niveshcopilot.com/api/market-recovery` (200 owner / 401 anonymous) after the backend restart, and a look
at the deployed page with the owner's session. Status: UNVERIFIED until then.

## API / Endpoint Tests (staging)

**pytest** (throwaway container from `nivesh/backend:staging`, branch tree mounted read-only, `--network none`):

```
$ sudo docker run --rm --network none -v /home/deploy/nivesh-wt-market-recovery:/work:ro -w /work/backend ... nivesh/backend:staging \
    python -m pytest tests/test_market_recovery.py tests/test_compliance_wording_lint.py -q -p no:cacheprovider
109 passed, 2 warnings in 10.00s
$ ... python -m pytest tests/test_market_recovery.py tests/test_scan_builder_routes.py nidp/tests/services/test_daas_fundamentals_source.py -q
58 passed, 4 warnings in 7.44s
```
(The first run found one failure — a pullback fixture sitting exactly on the 5% boundary, 5.00000000000004% in floating point;
the fixture was moved inside the band, the rule is unchanged.)

**TC-A1 — real data** (branch package copied to /tmp/mr in `nivesh-staging-app-backend`, the running server untouched;
scratchpad `mr_run.py`). Real output, 3 Nov close:

```
computed in 6.2s  as_of=2026-11-03  method=recovery-radar-v1
universe: {"name": "Nifty 500", "members": 501, "members_as_of": "2026-11-01", "scored": 490, "left_out": {"no_bar": 0, "history": 2, "liquidity": 3, "market_cap": 0}}
regime: underway / Recovery under way / 5 of 5
  line: Nifty 50 is above its 20-day average and participation is widening: 48% of Nifty 500 stocks are above their own 20-day average, against 25% 5 sessions ago.
  [PASS] Nifty 50 above its 20-day average: 23,810.8 vs 22,820.7 (+4.3%)
  [PASS] Nifty 50's 20-day average rising: 22,820.7 now vs 22,678.4 5 sessions ago
  [PASS] At least 60% of Nifty 500 stocks rose on the day: 62.8% rose (5-session average 56.8%)
  [PASS] More Nifty 500 stocks above their 20-day average than a week ago: 48.3% now vs 25.4% 5 sessions ago
  [PASS] India VIX falling: 15.72 vs 16.40 5 sessions ago
  breadth: {"counted": 493, "advancers_pct": 62.8, "advancers_pct_5d_avg": 56.8, "above20_pct": 48.3, "above20_pct_5ago": 25.4, "above50_pct": 28.9, "above50_pct_5ago": 17.7}
  cap: {"key": "large", "label": "Nifty 100", "members": 100, "above20_pct": 78.0, "above20_pct_5ago": 37.0, "above50_pct": 42.0}
  cap: {"key": "mid", "label": "Nifty Midcap 150", "members": 149, "above20_pct": 50.7, "above20_pct_5ago": 20.3, "above50_pct": 27.0}
  cap: {"key": "small", "label": "Nifty Smallcap 250", "members": 246, "above20_pct": 34.7, "above20_pct_5ago": 23.7, "above50_pct": 24.6}
breadth_series: 30 rows 2026-09-21 .. 2026-11-03
sectors (rank, sector, n, rs20, rs_change, above20, above50, deliv_up, state):
   1 Construction Materials              11    1.2    1.7  81.8  45.5  63.6 recovery *
   2 Textiles                             5    5.7    9.0  60.0  60.0  20.0 leadership *
   3 Automobile and Auto Components      40   -2.4    0.9  65.0  35.0  47.5 recovery *
   4 Healthcare                          44   -2.2   -0.7  75.0  47.7  34.1 neutral *
   5 Fast Moving Consumer Goods          27   -1.7    1.7  55.6  40.7  51.9 emerging *
   ...
  18 Capital Goods                       67   -9.8   -5.1  22.4  11.9  49.3 weak
candidates:
   1 LAURUSLABS   Healthcare             score= 82.7 [25.0/25 20.0/25 13.0/20 19.7/20 5.0/10] acc=62 (5/6) setup=relative_strength close=2323.0 entry=2285.27-2323.0 SL=2096.64 T1=2775.72 T2=3002.08 rr1=2.0
   2 BOSCHLTD     Automobile and Auto Co score= 81.9 [22.4/25 25.0/25 11.1/20 20.0/20 3.3/10] acc=88 (6/6) setup=breakout ...
   3 MSUMI        Automobile and Auto Co score= 80.9 [25.0/25 22.5/25 13.0/20 15.4/20 5.0/10] acc=90 (6/6) setup=ema_reclaim ...
excluded:
  ACUTAAS       89.0 extended        11.0% above its 20-day average: chasing risk is high.
  INDHOTEL      84.0 short_covering  Futures price +0.9% with open interest -4.6% on the latest F&O session: ...
warnings: ["6 Nifty 500 member(s) have no end-of-day series in the price panel (e.g. trade-for-trade series) and are not scored.",
           "Cash flow (CFO / PAT) is not served by the data platform yet; fundamental quality is scored on the other parts."]
```
The first run also excluded LT for "short covering" on a −0.1% OI change: the two-session rule now needs ≥ 1% OI falls
(TC-U5 case added); LT and PERSISTENT dropped out on the re-run.

**TC-A3a — the route over HTTP, pre-merge** (scratchpad `mr_http.py`: the branch router in a FastAPI app inside the staging
backend container, the real `require_feature` gate on staging Mongo flags, the real cookie sign-in with the owner's staging
session; httpx ASGITransport; token never printed, file removed after):

```
no cookie      -> HTTP 401 {"detail":"Not authenticated"}
owner cookie #1 -> HTTP 200 in 3.24s, 98,810 bytes; as_of=2026-11-03 method=recovery-radar-v1 regime=underway (5/5) scored=490 sectors=18 leaders=['Construction Materials', 'Textiles', 'Automobile and Auto Components', 'Healthcare', 'Fast Moving Consumer Goods'] candidates=10 others=10 excluded=10 top=[('LAURUSLABS', 82.7), ('BOSCHLTD', 81.9), ('MSUMI', 80.9)]
owner cookie #2 -> HTTP 200 in 0.01s, 98,810 bytes; ... (cached)
```

## Data Correctness (staging)

`~/.config/nivesh/nidp-psql.sh` (read-only SELECTs on `nidp`), 3 Nov:

```
 nifty50 close                    | 23810.8500      (engine 23,810.85)
 vix close                        | 15.7200         (engine 15.72)
 vix close 5 sessions ago (10-27) | 16.4000         (engine 16.40)
 nifty50 sma20                    | 22820.71        (engine 22,820.71)
  n  | above20_pct | above50_pct
 493 |        48.1 |        28.8                     (engine 48.3 / 28.9 — adjusted-panel SMA vs the feature store's)
   symbol   |  rsi14  | return_20d_pct              engine rsi / r20 (= RS 20D + Nifty 500 r20 2.50)
 BOSCHLTD   | 68.5090 |        10.4204              68.5 / 10.4
 BSOFT      | 57.9278 |        16.7391              57.9 / 16.7
 LAURUSLABS | 68.9223 |        17.8350              68.9 / 17.8
 MSUMI      | 70.7048 |        18.3642              70.7 / 18.4
 TVSMOTOR   | 63.9555 |         6.7527              64.0 / 6.8
 n500_r20 = 2.50
```
Freshness: prices_eod_adjusted, stock_features_daily, index_eod all 2026-11-03; delivery 2026-11-02 (lags one session, by
design). Coverage on 3 Nov for Nifty 500 (493 rows): ROCE 492, D/E 487, PAT growth 305, eps growth 0 (empty column — not
used), FII change 238, CFO/PAT 465 in the table but not served by DaaS until the features change is live.

## UI / Playwright Tests

Playwright container `mcr.microsoft.com/playwright:v1.47.0-jammy` (repo node_modules volume, Chromium 1223), the branch's
frontend-v5 mounted, `--network none`; every /api call route-mocked with hand-made MOCK fixtures.

Run 1, branch before merging dev:
```
TSC_EXIT=0
BUILD_EXIT=0
✓ built in 24.29s
/tmp/cp-dist/assets/MarketDesk-DsFEOGhg.js
/tmp/cp-dist/assets/MarketRecovery-qJp48V4F.js
PREVIEW_READY_AFTER=2s
[84/89] … copilot-app-market-recovery.spec.ts:168:3 › … TC-E1 with the flag on the switcher offers Market Recovery last; the view shows the check, breadth, sectors and candidates
[85/89] … TC-E2 a candidate opens its detail: five components, the 5-session table, the plan with its standard labels, reasons
[86/89] … TC-E3 with the flag off the switcher has five views, and the URL says the view is not enabled without asking the API
[87/89] … TC-E4 a 503 shows the server's own message; a 403 reads as not enabled; no candidates shows the empty state
[88/89] … TC-E5 wording: with a detail open, the page shows no trading-call word beyond the owner's four plan labels
[89/89] … TC-E6 at 390 px the page does not scroll sideways; the tables scroll inside their own box
  89 passed (1.0m)
PW_EXIT=0
```

Run 2, after merging origin/dev db9e0001 (#471, #472) into the branch (merge c14abc87), same five specs
(market-recovery, compliance-wording, desk-market-desk, desk-shell, desk-scan-dashboard):
```
$ npx playwright test --config pw.copilot-app.config.ts e2e/tests/copilot-app-market-recovery.spec.ts e2e/tests/copilot-app-compliance-wording.spec.ts e2e/tests/copilot-app-desk-market-desk.spec.ts e2e/tests/copilot-app-desk-shell.spec.ts e2e/tests/copilot-app-desk-scan-dashboard.spec.ts --reporter=list
TSC_EXIT=0
BUILD_EXIT=0
✓ built in 24.94s
PW_EXIT=0
  ✓  92 … copilot-app-market-recovery.spec.ts:168:3 › … TC-E1 … (1.2s)
  ✓  93 … TC-E2 … (1.3s)
  ✓  94 … TC-E3 … (1.3s)
  ✓  96 … TC-E5 … (956ms)
  ✓  97 … TC-E6 … (731ms)
  ✓  95 … TC-E4 … (2.8s)
  97 passed (1.1m)
```
Backend on the merged tree: `126 passed, 4 warnings in 8.28s` (test_market_recovery, test_compliance_wording_lint,
test_scan_builder_routes, test_daas_fundamentals_source).

TC-E7, the real answer of 3 Nov (regenerated with the final engine; 0 occurrences of "buying") rendered through a scratch
spec (scratchpad mr-shot/, not in the repo):
```
W1280 overflow=0 pageerrors=0
W390 overflow=0 pageerrors=0
  2 passed (4.2s)
```
Screenshots: scratchpad mr-shot/out/page-1280.png, page-390.png (reviewed: switcher shows Market Recovery last; warnings
banner; 5 checks; cap table; breadth chart; 18 sectors with the top 5 marked; 10 + 10 candidates; 10 left out; sources).
An earlier agent render found the candidates table scrolling sideways at 1280 px and the detail clipped; fixed before run 1.

## Inputs required from user
- none for this report (the owner's staging session token on this VM was still valid). The deployed check needs the PR merged.

## Verdict: PASS
