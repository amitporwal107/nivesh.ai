# Desk redesign, step 5: Market Desk tab (+ the Idea scorecard component): verification report

- **Branch:** `feat/desk-market-desk` (merged with `origin/dev` 0f076b9b: shell #369, Risk Desk #370), commit a8bfd045.
- **Date:** 2026-10-27. **Test cases:** `test_reports/desk_market_desk_TESTCASES.md` (written before the code; revised
  for the owner's 19:40 IST correction, PLAN.md "1-REVISED").
- **Spec:** `frontend-v5/e2e/tests/copilot-app-desk-market-desk.spec.ts`. MOCK — not real data: every API is mocked; the
  scorecard fixture `e2e/fixtures/desk-idea-scorecard.json` is a copy of staging's real `GET /api/desk/idea-scorecard`
  body.
- **Runner:** `run-fe.sh` (Docker Playwright 1.47, tsc, `vite build`, `vite preview`, mocked API, `--workers=2`).

## What changed
- **Market Desk = Market Intelligence · Smart Money · Sector Rotation · Stock Research · Screener** (`desk-nav.ts`
  `market` entry). `tradingdesk/tabs/market-desk/MarketDesk.tsx` gives every view one frame: the view head (eyebrow
  "Market Desk · <view>", one sentence, jump links to the view's parts, where related data lives).
  - Market Intelligence: IntelTab, a **sector-rotation readout** (`SectorReadout.tsx`, the heatmap route's NIFTY50 data:
    three strongest and three weakest sectors by 1M vs the index, 1D, % that rose, a state by a stated rule) and the
    Events calendar.
  - Smart Money: SmartMoneyTab, plus the F&O section (build-up board, candidates, indices, option chain). The chain lives
    here only.
  - Sector Rotation: SectorHeatmap (heatmap and rotation matrix).
  - Stock Research: a symbol strip (the stock shown, its option chain in Smart Money › F&O, the full chart workspace) over
    ChartTab.
  - Screener: Screener plus the Chartink sources.
- **Watchlists and the Idea scorecard moved to Trade Desk** (owner, 19:40 IST): `?tab=market&view=watchlists|scorecard`
  open Trade Desk (`MOVED_TO_TRADE` in `desk-nav.ts`). The scorecard component is in
  `screens/tradingdesk/scorecard/` (`IdeaScorecard.tsx`, `scorecard-data.ts`) for the Trade Desk tab to mount.
- `TradingDesk.tsx`: only the Market Desk mount (and its now-unused lazy imports).
- The hosted screens (IntelTab, EventsTab, SmartMoneyTab, FnoTab, SectorHeatmap, ChartTab, Screener, ChartinkSettings)
  are not edited.

## Results

### 1. tsc, build and the Market Desk spec (committed code)
```
== tsc
tsc: clean
== build
✓ built in 31.28s
== playwright
  9 skipped
  13 passed (14.7s)
exit 0
```
The 9 skipped are the SC-* scorecard cases: no URL mounts the component in this PR (`SCORECARD_URL` is null until Trade
Desk mounts it).

### 2. The scorecard cases, on a temporary mount (NOT committed)
For this run only, a 3-line local patch mounted `IdeaScorecard` at `?tab=market&view=scorecard` and set `SCORECARD_URL`.
The patch was reverted with `git checkout` straight after the run, and the working tree was clean.
```
== tsc
tsc: clean
== build
✓ built in 45.24s
== playwright
✓  2 [copilot-app] › e2e/tests/copilot-app-desk-market-desk.spec.ts:259:3 › MOCK — not real data: Idea scorecard (fixture = staging's real body) › SC-4 / SC-5 three splits, four arms each; B
✓  1 [copilot-app] › e2e/tests/copilot-app-desk-market-desk.spec.ts:244:3 › MOCK — not real data: Idea scorecard (fixture = staging's real body) › SC-1 / SC-2 / SC-3 / SC-13 the verdict, the
✓  4 [copilot-app] › e2e/tests/copilot-app-desk-market-desk.spec.ts:313:5 › MOCK — not real data: Idea scorecard (fixture = staging's real body) › SC-9 / SC-10 a 503 scorecard_unavailable sh
✓  3 [copilot-app] › e2e/tests/copilot-app-desk-market-desk.spec.ts:285:3 › MOCK — not real data: Idea scorecard (fixture = staging's real body) › SC-6 / SC-7 / SC-8 RS63, the per-arm checks
✓  5 [copilot-app] › e2e/tests/copilot-app-desk-market-desk.spec.ts:313:5 › MOCK — not real data: Idea scorecard (fixture = staging's real body) › SC-9 / SC-10 a 503 scorecard_out_of_date sh
✓  6 [copilot-app] › e2e/tests/copilot-app-desk-market-desk.spec.ts:328:3 › MOCK — not real data: Idea scorecard (fixture = staging's real body) › SC-11 a 500 says it didn't load, offers Ret
✓  7 [copilot-app] › e2e/tests/copilot-app-desk-market-desk.spec.ts:340:3 › MOCK — not real data: Idea scorecard (fixture = staging's real body) › SC-12 a body without splits or a verdict is
✓  8 [copilot-app] › e2e/tests/copilot-app-desk-market-desk.spec.ts:368:3 › MOCK — not real data: Market Desk · wording › W-1 (scorecard) no pick / recommended / suggest in the scorecard (2
✓  9 [copilot-app] › e2e/tests/copilot-app-desk-market-desk.spec.ts:391:3 › MOCK — not real data: Market Desk · phone 390px › P-1 (scorecard) no sideways page scroll; the split tables scrol
9 passed (17.9s)
exit 0
```

### 3. Regression: my spec + desk-shell, desk-market, desk-smart-money, sector-heatmap, screener, desk-lab (committed code)
```
== tsc
tsc: clean
== build
✓ built in 30.65s
== playwright
  ✓   13 [copilot-app] › e2e/tests/copilot-app-desk-lab.spec.ts:791:3 › Smart trading desk — Options & futures lab › TC-33 OI build-up: a failed scan shows an error with retry; the keyboard opens a row (4.5s)
  ✓   43 [copilot-app] › e2e/tests/copilot-app-desk-lab.spec.ts:1408:3 › Smart trading desk — Options & futures lab · Candidates › TC-12 a failed route shows a notice with retry, and no cards (4.1s)
  ✓   50 [copilot-app] › e2e/tests/copilot-app-desk-lab.spec.ts:1489:3 › Smart trading desk — Options & futures lab · index workspaces › TC-7 a failed futures read shows the panel's notice and leaves the card usable (2.0s)
  ✓   59 [copilot-app] › e2e/tests/copilot-app-desk-lab.spec.ts:1577:3 › Options & futures lab · latest quotes on Candidates and the index card › TC-7 a failed snapshot read leaves the cards as they were (2.5s)
  ✓   70 [copilot-app] › e2e/tests/copilot-app-desk-lab.spec.ts:1800:3 › Smart trading desk — Options & futures lab · paper strategy builder › TC-9 a structure the engine rejects shows no levels; a failed read shows the notice and leaves the payoff (1.2s)
  ✓   78 [copilot-app] › e2e/tests/copilot-app-desk-lab.spec.ts:1886:3 › Smart trading desk — Options & futures lab · paper strategy builder › TC-5 a failed payoff shows the notice with a retry, never an empty chart (1.8s)
  ✓   86 [copilot-app] › e2e/tests/copilot-app-desk-lab.spec.ts:1995:3 › Smart trading desk — Options & futures lab · index history and OI bars › TC-6 a failed history read shows the panel's notice and leaves the card and the other panels (2.4s)
  ✓  126 [copilot-app] › e2e/tests/copilot-app-desk-market.spec.ts:526:3 › Smart trading desk — Overview › TC-10 (OV-003): sector leadership, important events and risks beside the regime; a skipped check is said, not guessed (1.3s)
  ✓  130 [copilot-app] › e2e/tests/copilot-app-desk-market.spec.ts:662:3 › Smart trading desk — Overview › TC-11: sector returns — a failed read shows an error with retry, 403 says not enabled, an empty list says so; a failed leader read only drops the leaders (9.1s)
  ✓  133 [copilot-app] › e2e/tests/copilot-app-desk-market.spec.ts:783:3 › Smart trading desk — Overview › OV-005: no setups in the scan is an honest empty state; a failed live check says so on each pick (4.6s)
  ✓  137 [copilot-app] › e2e/tests/copilot-app-desk-market.spec.ts:913:3 › Smart trading desk — Overview › TC-12: a failed market overview shows an error with retry while the regime and sectors still render (4.1s)
  ✓  147 [copilot-app] › e2e/tests/copilot-app-desk-market.spec.ts:1477:3 › Smart trading desk — Market intelligence › states: an empty chip, a failed chip with retry, a 403, a partial All, and a failed provenance read said in words (8.3s)
  ✓  257 [copilot-app] › e2e/tests/copilot-app-sector-heatmap.spec.ts:358:3 › Sector heatmap — desktop › a failed read shows an error with Retry, and Retry loads the map (4.3s)
  16 skipped
  255 passed (5.1m)
exit 0

-   20 [copilot-app] › e2e/tests/copilot-app-desk-lab.spec.ts:1088:5 › Options & futures lab — screenshots › screenshots desktop
-   21 [copilot-app] › e2e/tests/copilot-app-desk-lab.spec.ts:1088:5 › Options & futures lab — screenshots › screenshots mobile
-  112 [copilot-app] › e2e/tests/copilot-app-desk-market-desk.spec.ts:244:3 › MOCK — not real data: Idea scorecard (fixture = staging's real body) › SC-1 / SC-2 /
-  113 [copilot-app] › e2e/tests/copilot-app-desk-market-desk.spec.ts:259:3 › MOCK — not real data: Idea scorecard (fixture = staging's real body) › SC-4 / SC-5 t
-  114 [copilot-app] › e2e/tests/copilot-app-desk-market-desk.spec.ts:285:3 › MOCK — not real data: Idea scorecard (fixture = staging's real body) › SC-6 / SC-7 /
-  115 [copilot-app] › e2e/tests/copilot-app-desk-market-desk.spec.ts:313:5 › MOCK — not real data: Idea scorecard (fixture = staging's real body) › SC-9 / SC-10 
-  116 [copilot-app] › e2e/tests/copilot-app-desk-market-desk.spec.ts:313:5 › MOCK — not real data: Idea scorecard (fixture = staging's real body) › SC-9 / SC-10 
-  117 [copilot-app] › e2e/tests/copilot-app-desk-market-desk.spec.ts:328:3 › MOCK — not real data: Idea scorecard (fixture = staging's real body) › SC-11 a 500 s
-  118 [copilot-app] › e2e/tests/copilot-app-desk-market-desk.spec.ts:340:3 › MOCK — not real data: Idea scorecard (fixture = staging's real body) › SC-12 a body 
-  120 [copilot-app] › e2e/tests/copilot-app-desk-market-desk.spec.ts:368:3 › MOCK — not real data: Market Desk · wording › W-1 (scorecard) no pick / recommended
-  122 [copilot-app] › e2e/tests/copilot-app-desk-market-desk.spec.ts:391:3 › MOCK — not real data: Market Desk · phone 390px › P-1 (scorecard) no sideways page 
-  135 [copilot-app] › e2e/tests/copilot-app-desk-market.spec.ts:837:8 › Smart trading desk — Overview › OV-007 / OV-008: portfolio snapshot and risk summary from
-  190 [copilot-app] › e2e/tests/copilot-app-desk-smart-money.spec.ts:228:8 › Smart trading desk · 06 Smart Money Movement › TC-F1: it is the sixth primary tab and
-  209 [copilot-app] › e2e/tests/copilot-app-desk-smart-money.spec.ts:484:8 › Smart trading desk · 06 Smart Money Movement › TC-F20: on a phone it is in the bottom
-  266 [copilot-app] › e2e/tests/copilot-app-sector-heatmap.spec.ts:427:8 › Sector heatmap — entry points › it is a Trader rail item named Sector rotation and ope
-  271 [copilot-app] › e2e/tests/copilot-app-sector-heatmap.spec.ts:520:3 › Sector heatmap — screenshots › desktop 1440, zoomed, and phone 390
```
The other 7 skips are static `test.skip` lines in specs this branch does not change (screenshot runs, a removed Flows tab, an old rail entry, OV-007/008).

### 4. Staging, read-only (the data the tab reads)
```
GET /api/desk/idea-scorecard -> 200
  study p4_adx_rs 4.3 2026-10-27 registration 4c408401
  verdict: keep B0; the current ranking shows no measurable skill | adopted: None
  rs63: promising, awaiting its pre-registered confirmation | adopted: False
  discovery  2025-02-17..2026-02-11 B0 IC 0.0085 t 0.43 net 0.0023 hit 0.4959
  validation 2026-02-12..2026-06-15 B0 IC 0.0011 t 0.03 net 0.00263 hit 0.4761
  test       2026-06-16..2026-10-09 B0 IC 0.0075 t 0.41 net -0.00992 hit 0.4494
  source research/p4_adx_rs/results_20261027/result.json present True 4b3eff97d09f
  source docs/ai_research/P4_ADX_RS_PREREGISTRATION.md present False -
  source docs/ai_research/P4_ADX_RS_RESULTS.md present False -
  source docs/ai_research/P4_RS63_CONFIRMATION_PREREGISTRATION.md present False -
GET /api/markets/sector-heatmap?index=NIFTY50 -> 200
  as_of 2026-10-26 mode end_of_day sectors 15 stocks 50 weighted_change {'d': 0.671, 'w': -1.708, 'm': -3.594}
  strongest by 1M vs index: [('Information Technology', 20.79, 0.3), ('Telecommunication', 8.19, 1.34), ('Construction Materials', 0.7, 1.47)]
  weakest by 1M vs index: [('Capital Goods', -4.75, 0.28), ('Consumer Durables', -5.73, 0.58), ('Metals & Mining', -7.4, 2.7)]
```
- The scorecard route serves the study as committed: the verdict and RS63 text match the fixture, and the three
  write-up documents read `present: false` on staging (the server mounts `research/`, not `docs/`), which the scorecard
  shows as "no" with the route's reason.
- The heatmap route has `weighted_change.m` and 15 sectors for 26 Oct, so the readout will draw six rows on staging.

## Unverified
- The tab is not on staging until this PR merges and the frontend image is rebuilt: no case ran against the deployed UI.
- The scorecard component runs in this PR only through the temporary mount above; it is unreachable until Trade Desk
  mounts it.
- No screenshot review against the owner's design was done; layout was checked by the 390px no-side-scroll cases only.
- Market Overview's "Scorecard →" link (step 2's code) still opens Market Desk; it should open Trade Desk's scorecard
  once that exists.
- The FII / DII event rows inside IntelTab and the AI daily list inside the Watchlist page repeat data shown elsewhere.
  They belong to those screens and were left as they are.

## Verdict: PASS
