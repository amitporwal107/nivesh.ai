# Test cases — Desk Scanner: Top 10 ideas, market pulse, lab deep links, breadcrumb trail

- **Date:** 2026-10-25 · **Branch:** `feat/desk-scanner-top10` (worktree `/home/deploy/nivesh-desk-top10`, off `origin/dev` 5109b3f8)
- **Roles:** FULL_STACK_DEVELOPER + DESIGN_ENGINEER + QA_ENGINEER (+ DOMAIN_EXPERT for the SEBI wording)
- **Authored before implementation**, after the API and UI design below.

## The ask (user, 2026-10-25)

On `/v5/app/trader/desk?tab=scanner`:
1. Top 10 stocks and Top 10 F&O (NIFTY / BANKNIFTY / stocks), each with its strategy, a link to the option chain,
   add to paper trades, and view the trades.
2. Smooth navigation: a Top F&O idea opens the F&O lab Candidates page, with futures / option OI build-up and paper trade.
3. A breadcrumb of the navigation path; every crumb clickable.
4. Snippets and indicators of the latest market events / news on the Scanner, linking to Market Intelligence and Smart Money.

## Decisions the user made (2026-10-25)

- **Wording:** "Top 10 ideas" / "strategy that fits", never "picks", "recommended" or "suggested" (SEBI RA rules; the
  desk's established wording).
- **F&O list:** one row per instrument (NIFTY, BANKNIFTY, F&O stocks), each with its best-fitting structure and the
  others as alternatives. Needs a backend change.

## Design

### Backend — `POST /api/desk/strategy/top`, new optional body field `distinct` (bool, default false)

- `distinct: true` → in each option class, one idea per underlying: the best by the existing order (fit desc, then
  reward:risk desc). The next ≤ 2 structures for the same underlying ride along as `alternatives` (full idea objects).
  Ranks are 1..n over underlyings. The class carries `distinct: true`.
- `distinct: true` + `stock_fno` → the universe is the scanner's merged eligible list with names the scan snapshot marks
  `fno_eligible: false` dropped **before any chain read** (listed in `universe.skipped` with the reason), known-F&O names
  first, unknown after, up to `STOCK_FNO_SCAN_DISTINCT` names.
- `distinct` absent / false → behaviour and shape unchanged.
- The requested classes are built concurrently (same output, shorter wait).

### Frontend

- **Scanner** (`?tab=scanner`): three stacked desk widgets — *Market pulse* · *Top 10 ideas* (two boards) · the existing scanner list.
- **Top 10 stock ideas** — `POST /api/desk/strategy/ideas {limit:10}`. Row: rank, icon + symbol, setup + score, plan
  status, the strategy that fits (the route's `preferred`). Actions: Strategy › (Strategy Builder with the plan),
  Chart ›, Option chain › (F&O-eligible only), Paper trade (scanner levels, POST /api/desk/paper-trades), View trades ›.
- **Top 10 F&O ideas** — `POST /api/desk/strategy/top {limit:10, classes:[index_options, stock_fno], distinct:true}`,
  the two classes merged by the route's own order and cut to 10. Chips All · Indices · Stocks. Row: rank, underlying,
  structure, expiry, fit, reward:risk, max loss, alternatives. Actions: Open in lab › (Candidates for a stock, NIFTY &
  BANKNIFTY for an index, with a focus panel), Payoff, Paper trade, Option chain ›, OI build-up ›, View trades ›.
- **Lab URL state** — `?tab=fno&lab=<buildup|candidates|indices|chain|strategies>&lab_sym=<SYM>&lab_focus=<SYM>`.
- **Lab focus panel** — the focused Top 10 idea with Payoff, Paper trade, Option chain, Futures OI build-up, View trades, Close.
- **Candidates** — each card adds "Futures OI build-up ›" and "Strategy & paper trade ›"; the focused card is highlighted.
- **Market Intelligence URL state** — `?tab=intel&in_chip=<chip>&in_ev=<event id>`.
- **Breadcrumb trail** — under the tab row: `Trading desk › <steps taken> › <here>`. A main-tab click resets it; a crumb
  click returns to that exact URL and drops the steps after it; kept in sessionStorage for a reload.
- **Market pulse** — FII/DII last session (`/api/markets/fii-dii`), Smart money 1M (`/api/markets/smart-money/summary`),
  sector movers (`/api/markets/sector-returns`), the latest events (`useIntelEvents("all")`). Each opens Intel (with
  chip / event) or Smart Money.

## Backend cases (pytest, unit)

| ID | Case | Expected |
|----|------|----------|
| B-1 | `distinct` false: pool with repeated underlyings | duplicates kept, order and ranks as today, no `alternatives` key |
| B-2 | `distinct` true | ≤ 1 idea per underlying, the best by (fit desc, R:R desc); ranks 1..n contiguous |
| B-3 | alternatives | the next ≤ 2 structures of that underlying in order; none also appears at top level |
| B-4 | limit over distinct underlyings | limit 10 → ≤ 10 rows; limit 1 → 1 row |
| B-5 | F&O universe ordering | `fno_eligible` False skipped before any chain read and listed with a reason; True first, then unknown; capped |
| B-6 | body validation | `distinct: "yes"` → 422 naming `distinct`; unknown keys still 422; `distinct: true` accepted |
| B-7 | build_top with both option classes, distinct | both classes present, each distinct, `distinct: true` on the envelope |
| B-8 | regression | `tests/test_regime_fit.py` + strategy suites still pass |

## Backend cases (staging, real output — after merge + backend restart)

| ID | Case | Expected |
|----|------|----------|
| S-1 | `POST /top {limit:10, classes:[index_options,stock_fno], distinct:true}` | 200; each underlying at most once per class; NIFTY / BANKNIFTY present when priced |
| S-2 | stock universe | no "No F&O data" for names the snapshot marks non-F&O; `universe.skipped` lists them |
| S-3 | default body | unchanged shape (limit 5, duplicates allowed) |
| S-4 | no auth / bad `distinct` | 401 / 422 |
| S-5 | latency | recorded (no target set; reported) |

## Frontend cases (Playwright, mocked API, production build)

| ID | Case | Expected |
|----|------|----------|
| F-1 | Scanner layout | Market pulse, both Top 10 boards, then the existing scanner list (`desk-scanner`) |
| F-2 | Stock board | POST /ideas body `limit: 10`; ≤ 10 rows; rank, symbol, setup, score, strategy that fits (or the reason none passed) |
| F-3 | Stock "Strategy ›" | Strategy Builder with sym, direction, plan inputs, `mode=stock`, `build=1`, `cand=<preferred>`, `src_kind=ideas` |
| F-4 | Stock "Option chain ›" | only for F&O-eligible rows; opens `tab=fno&lab=chain&lab_sym=SYM`, lab shows that chain tab |
| F-5 | Stock paper trade | exact body (symbol, quantity, entry, stop, target, `source.kind: "scanner"`), success line |
| F-6 | View trades › | `tab=portfolio` |
| F-7 | F&O board | POST /top body `{limit:10, classes:["index_options","stock_fno"], distinct:true}`; merged by fit desc then R:R desc; one row per underlying; ≤ 10 |
| F-8 | F&O chips | All / Indices / Stocks counts and filtering |
| F-9 | Alternatives | "+N other structures" lists them |
| F-10 | F&O Payoff / Paper trade | payoff POST only once opened; paper trade body kind "strategy" with the idea's legs |
| F-11 | Stock idea → lab | `lab=candidates&lab_focus=SYM`; focus panel shows the idea; SYM's candidate card highlighted |
| F-12 | Index idea → lab | `lab=indices&lab_sym=NIFTY&lab_focus=NIFTY`; focus panel |
| F-13 | Focus panel actions | Option chain → `lab=chain`; Futures OI build-up → `lab=buildup` with SYM; Close drops `lab_focus` |
| F-14 | Candidate card actions | "Futures OI build-up ›" and "Strategy & paper trade ›" go to the right views |
| F-15 | Failure isolation | one board's error (Retry shown) leaves the other board and the scanner list intact |
| F-16 | Wording gate | no "pick", "recommend", "suggested" in the new boards and pulse |
| F-17 | Honesty | end-of-day labels, as-of dates and the route's ranking note visible |
| F-20 | Breadcrumb on load | `Trading desk › AI Scanner` |
| F-21 | Path recorded | Scanner → F&O idea → Candidates → OI build-up gives four crumbs, last `aria-current="page"` |
| F-22 | Crumb click | returns to that crumb's exact URL (incl. `lab_focus`) and drops the later steps |
| F-23 | Main tab click | resets the trail to `Trading desk › <tab>` |
| F-24 | Root crumb | "Trading desk" opens Overview |
| F-25 | Reload | trail kept (sessionStorage) |
| F-26 | Phone 390px | breadcrumb, pulse and boards render; no sideways page scroll |
| F-27 | Crumb anchor | "AI Scanner · Top 10 F&O ideas" scrolls back to the F&O board |
| F-30 | Pulse events | latest events newest first: type, symbol, title, time |
| F-31 | Pulse indicators | FII/DII last session, Smart money 1M, sector movers — from the named routes, with dates |
| F-32 | Event click | Intel opens with `in_ev` and that event in the detail |
| F-33 | Pulse links | "Market Intelligence ›" → intel; FII/DII tile → intel `in_chip=flows`; "Smart Money ›" → smartmoney |
| F-34 | Pulse partial failure | a failed source shows its own "didn't load"; others still render |
| F-35 | Intel chip in URL | a chip click writes `in_chip`; reload keeps it |

## Regression

| ID | Case | Expected |
|----|------|----------|
| R-1 | Existing desk specs | `copilot-app-desk*.spec.ts` and `copilot-app-trader.spec.ts` pass as before |
| R-2 | Typecheck | `tsc -b` clean |
