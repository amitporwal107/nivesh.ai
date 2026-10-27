# Desk redesign, step 5 (Market Desk tab + Idea scorecard): test cases

- **Plan:** `docs/desk_redesign_20261027/PLAN.md` §1 (tab 03 Market Desk) and §2a (P4 scorecard row);
  `REVIEW_workspace_vs_phases.md` §A "3 Market Desk", "What makes navigation harder", §2 Phase 4, the wording rules.
- **Branch:** `feat/desk-market-desk`, from `origin/feat/desk-redesign-shell` (PR #369, not merged yet).
- **Written:** 2026-10-27, before the implementation. Spec: `frontend-v5/e2e/tests/copilot-app-desk-market-desk.spec.ts`.
  Every API is mocked (`MOCK — not real data`). The scorecard fixture is a copy of the real body of staging's
  `GET /api/desk/idea-scorecard` (read once, read-only, on 2026-10-27; the route serves the committed
  `research/p4_adx_rs/results_20261027/result.json`, so its numbers are the study's, not synthetic).
- **Scope:** `screens/tradingdesk/tabs/market-desk/*` (new), the Market Desk mount in `TradingDesk.tsx`, the `market`
  entry of `desk-nav.ts`. The hosted screens (IntelTab, EventsTab, SmartMoneyTab, the F&O lab, SectorHeatmap, ChartTab,
  Screener, ChartinkSettings, Watchlist) are re-hosted unchanged.

## Views (`/v5/app/trader/desk?tab=market&view=<view>`)

`intel` Market Intelligence (default) · `smartmoney` Smart Money · `sectors` Sector Rotation · `research` Stock Research ·
`screener` Screener · `watchlists` Watchlists & alerts · **`scorecard` Idea scorecard (new)**.

## Test cases

| ID | Area | Scenario | Type | Expected |
|---|---|---|---|---|
| MD-1 | Frame | Open `tab=market` | e2e | The view switcher lists the seven views in order, ending "Idea scorecard"; `view=intel` is pressed. |
| MD-2 | Frame | Open each view by URL | e2e | Each shows the same frame: `md-head` with the eyebrow "Market Desk · <view label>", a one-sentence headline, and the hosted screen's panel (`desk-panel-<id>`). |
| MD-3 | Frame | Each view's "where things live" line | e2e | Smart Money says the option chain and OI live here (F&O section); Stock Research says the option chain is in Smart Money › F&O and links there; no view hosts a data set another view hosts (the option chain panel `desk-panel-fno` exists only under Smart Money). |
| MD-4 | Market Intelligence | Open `view=intel` | e2e | `desk-panel-intel` and the "Events calendar" section `desk-panel-events`; a jump link "Events calendar" sets `section=events`. |
| MD-5 | Smart Money | Open `view=smartmoney` | e2e | `desk-panel-smartmoney` and the F&O section `desk-panel-fno` ("F&O · build-up, indices and option chain"); the jump link sets `section=fno`. |
| MD-6 | Sector Rotation | Open `view=sectors` | e2e | `desk-panel-sectors` hosts the heatmap (`screen-tool-sector-heatmap`). |
| MD-7 | Stock Research | Open `view=research&sym=INFY` | e2e | The symbol strip names INFY; "Option chain & OI" opens `tab=market&view=smartmoney&section=fno&lab_sym=INFY`; the "Full chart workspace" link points to `/v5/research?screen=charts&symbol=INFY`. |
| MD-8 | Stock Research | Open `view=research` with no `sym` | e2e | The symbol strip says no stock is chosen yet and how to choose one (search, or an idea / watchlist row). No made-up symbol. |
| MD-9 | Screener | Open `view=screener` | e2e | `desk-panel-screener` (`screen-tool-screener`) and the "Chartink sources" section `desk-panel-chartink`. |
| MD-10 | Watchlists | Open `view=watchlists` | e2e | `desk-panel-watchlists` hosts `screen-page-watchlist`. |
| SC-1 | Scorecard | `tab=market&view=scorecard`, 200 with the real staging body | e2e | URL stays on `view=scorecard`; the switcher has "Idea scorecard" pressed; the scorecard renders. |
| SC-2 | Scorecard | The study block | e2e | Title, phase 4.3, run date 27 Oct 2026, registration commit `4c408401`, code sha, 385 signal dates, the outcome definition. |
| SC-3 | Scorecard | The verdict | e2e | Exactly "keep B0; the current ranking shows no measurable skill" (from `decision.verdict`), plus the study's own verdict string. No "beats the baseline", no precision@10. |
| SC-4 | Scorecard | Per split | e2e | Three split tables (discovery / validation / test) with their date ranges; each has four arm rows (B0, A1, A2, A3) with rank IC mean and its NW t, Δ vs B0 and its permutation p, top-decile net return and hit rate. |
| SC-5 | Scorecard | Nulls and negatives as they are | e2e | B0's Δ vs B0 and p are shown as "—" (baseline), not hidden or 0. Test-split B0 top-decile net is "−0.99%" (negative, danger tone); A3 discovery rank IC "−0.0039". Every arm row is present even when worse than B0. |
| SC-6 | Scorecard | RS63 | e2e | "RS63 vs Nifty 50 replaces the sector term (A2): promising, awaiting its pre-registered confirmation"; "not adopted"; the confirmation document path. |
| SC-7 | Scorecard | Sources | e2e | Four rows: path, role, sha256 (first 12 shown, full in title), present yes/no. result.json present "yes"; the three docs "no" with the route's reason ("not readable here (FileNotFoundError)"). |
| SC-8 | Scorecard | Per-arm pre-registered checks | e2e | A1, A2, A3 each listed with their four checks (pass / fail) and "not adopted". |
| SC-9 | Scorecard | 503 `scorecard_unavailable` | e2e | An error card shows the route's own `reason` and code; no numbers drawn. |
| SC-10 | Scorecard | 503 `scorecard_out_of_date` | e2e | Same, with that code and reason. |
| SC-11 | Scorecard | Other failure (500 / network) | e2e | "The scorecard didn't load" with a Retry button; no numbers. |
| SC-12 | Scorecard | Body missing `splits` / `decision` | e2e | A contract error ("the answer had no …"), never an empty table presented as results. |
| SC-13 | Scorecard | Disclaimer | e2e | The route's `disclaimer` is shown ("Ideas, not recommendations…"). |
| W-1 | Wording | Every Market Desk view's frame text and the scorecard | e2e | No "pick", "recommended", "suggested" or "suggestion" in the frame or the scorecard. |
| P-1 | Phone 390px | Each of the seven views | e2e | No horizontal page scroll (`scrollWidth <= clientWidth`); the scorecard tables scroll inside their own box. |
| R-1 | Regression | `copilot-app-desk-shell`, `-desk-market`, `-desk-smart-money`, `-sector-heatmap`, `-screener`, `-watchlists`, `-ai-watchlist` | e2e | Pass as on the shell branch (the shell spec's Market Desk view list gains "Idea scorecard"). |
| B-1 | Build | `tsc --noEmit`, `vite build` | build | Clean. |
| ST-1 | Staging | `GET /api/desk/idea-scorecard` on staging, read-only | api | 200 with study / splits / decision / rs63 / sources (the data the fixture copies). The tab itself is not on staging until the PR merges and deploys: UNVERIFIED there. |
