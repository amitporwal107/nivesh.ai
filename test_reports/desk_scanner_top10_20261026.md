# Functionality Verification Report — Desk Scanner: Top 10 ideas, market pulse, lab deep links, breadcrumb

- **Branch:** `feat/desk-scanner-top10` (tip `11b4138f`, off `origin/dev` 5109b3f8)
- **Date:** 2026-10-26
- **Author:** Claude (FULL_STACK_DEVELOPER + DESIGN_ENGINEER + QA_ENGINEER; SEBI wording reviewed as DOMAIN_EXPERT)
- **Environment:** local (container from `nivesh/backend:staging`; production frontend build, mocked API). **Not on staging yet.**
- **Changed areas:** backend routes/services: **yes** · frontend src: **yes**

## Summary

The user's ask (2026-10-25), on `/v5/app/trader/desk?tab=scanner`:
1. Top 10 stocks and Top 10 F&O (NIFTY / BANKNIFTY / stocks), each with its strategy, option chain link, paper trade and view trades.
2. A Top F&O idea opens the F&O lab Candidates page with futures / option OI build-up and paper trade.
3. A breadcrumb of the navigation path, every crumb clickable.
4. Snippets and indicators of the latest market events on the Scanner, linking to Market Intelligence and Smart Money.

User decisions: wording **"Top 10 ideas"** (never picks / recommended / suggested — SEBI RA rules); F&O list **one row per instrument**.

Built:
- **Backend** — `POST /api/desk/strategy/top` takes `distinct: true`: one idea per underlying (best by fit, then reward:risk),
  up to 2 alternatives under it; the stock F&O universe drops non-F&O scanner names before any chain read (reported in
  `universe.skipped`) and tries up to 12 F&O names; the requested classes are built concurrently. Without `distinct` the
  answer is unchanged (plus a `distinct: false` flag on the envelope).
- **Scanner** — Market pulse (latest filings, FII/DII last session, Smart Money 1M, sector moves; each opens Intel / Smart
  Money); Top 10 stock ideas (`POST /ideas {limit:10}`) and Top 10 F&O ideas (`POST /top {limit:10, classes:[index_options,
  stock_fno], distinct:true}`), each row linking to plan / chart / chain / OI build-up / lab, with payoff and paper trade.
- **F&O lab** — view, underlying and focus in the URL (`lab`, `lab_sym`, `lab_focus`); focus panel with the idea, payoff,
  paper trade, chain, futures OI build-up, view trades; Candidates opens the focused stock's category and outlines its card;
  each candidate card adds "Futures OI build-up ›" and "Strategy & paper trade ›".
- **Market Intelligence** — chip and event in the URL (`in_chip`, `in_ev`).
- **Breadcrumb** — `Trading desk › steps taken › here` under the tab row (phone: under the header); main tab resets; a crumb
  returns to that exact URL and scrolls to the board it left from; kept across a reload (sessionStorage).

## Test Cases

Authored up front: `test_reports/desk_scanner_top10_TESTCASES.md` (design + B-*, S-*, F-*, R-* cases).

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| B-1 | backend | `distinct` off: unchanged | unit | duplicates kept, no alternatives | PASS |
| B-2 | backend | one idea per underlying, ranks 1..n | unit | best by fit, R:R | PASS |
| B-3 | backend | alternatives ≤ 2, in order, not at top level | unit | as stated | PASS |
| B-4 | backend | limit counts underlyings | unit | 1→1, 10→≤10 | PASS |
| B-5 | backend | non-F&O names skipped before chain reads | unit | skipped + reason; known F&O first | PASS |
| B-6 | backend | body validation | unit | non-bool → 422; unknown → 422 | PASS |
| B-7 | backend | build_top distinct, both classes; no regime → nothing scored | unit | as stated | PASS |
| B-8 | backend | regression: regime-fit, plan, payoff, ideas suites | unit | pass | PASS |
| S-1…S-5 | backend | the real route on staging | api | see below | **NOT RUN — needs merge + restart + session token** |
| F-1 | UI | pulse, boards, then the list | e2e | order | PASS |
| F-2 | UI | stock board: `{limit:10}`, strategy that fits / route's reason | e2e | as stated | PASS |
| F-3 | UI | Strategy › opens the plan with inputs + `cand` | e2e | URL params | PASS |
| F-4 | UI | Option chain › only for F&O stocks → lab chain | e2e | as stated | PASS |
| F-5 | UI | stock paper trade at scanner levels, sized qty | e2e | exact POST body | PASS |
| F-6 | UI | View trades › → Portfolio & Risk | e2e | tab | PASS |
| F-7 | UI | F&O body + merge in the route's order, one row each | e2e | SB1, LB2, BANKNIFTY, NIFTY | PASS |
| F-8 | UI | All / Indices / Stocks | e2e | counts + filter | PASS |
| F-9 | UI | alternatives behind the row | e2e | as stated | PASS |
| F-10 | UI | payoff only when opened; strategy paper trade | e2e | 0→1 payoff call; body kind strategy | PASS |
| F-11 | UI | stock idea → Candidates, focus, category, outline | e2e | as stated | PASS |
| F-12 | UI | index idea → index workspace with focus | e2e | as stated | PASS |
| F-13 | UI | focus panel → chain / build-up / close; not-on-board note | e2e | as stated | PASS |
| F-14 | UI | candidate card → build-up, Strategy Builder | e2e | as stated | PASS |
| F-15 | UI | one board failing leaves the rest | e2e | Retry; others render | PASS |
| F-16/17 | UI | wording gate; caveats, dates, skipped names | e2e | no picks/suggested/recommend | PASS |
| F-20…F-27 | UI | breadcrumb: load, path, crumb return, reset, root, reload, anchor scroll, phone | e2e | as stated | PASS |
| F-30…F-35 | UI | pulse events, indicators, event → Intel, links, partial failure, chip in URL | e2e | as stated | PASS |
| R-1 | UI | every existing desk spec + trader spec | e2e | no new failures | PASS (see below) |
| R-2 | UI | typecheck | static | clean | PASS |

## API / Endpoint Tests (staging)

**NOT RUN.** The backend change is only on this unmerged branch; staging runs `dev`. Needed: merge to `dev`, the staging
backend process restarted (bind-mount; code on disk ≠ code in the process), and a staging `session_token` from the user.
To run then (S-1…S-5):

```
POST /api/desk/strategy/top {"limit":10,"classes":["index_options","stock_fno"],"distinct":true}   -> 200, one row per underlying, universe.skipped
POST /api/desk/strategy/top {}                                                                        -> 200, unchanged shape (limit 5)
POST /api/desk/strategy/top {"distinct":"yes"} -> 422 ;  no cookie -> 401 ;  latency recorded
```

- **pytest** (container from `nivesh/backend:staging`, tree mounted read-only, `--network none`), tip `11b4138f`:
  - Command: `python -m pytest tests/test_regime_fit_distinct.py tests/test_regime_fit.py tests/test_strategy_plan.py tests/test_strategy_payoff.py tests/test_strategy_ideas.py -q -p no:cacheprovider`
  - Output: `222 passed, 2 warnings in 10.26s` (of which `tests/test_regime_fit_distinct.py`: 16 PASSED)
  - Result: PASS (local)

## UI / Playwright Tests

Production build (`VITE_USE_MOCK_API=false VITE_BASE=/v5/ vite build`), `vite preview`, `pw.copilot-app.config.ts`,
`--network none`, every `/api` call mocked (MOCK — not real data). Playwright 1.60, Chromium build 1223.

- **New spec:** `frontend-v5/e2e/tests/copilot-app-desk-top10.spec.ts` — 27 cases, all pass (first run 25/27: the two
  failures were a real bug — the pulse's sector tile read Intel's "All" list, which has no sector moves — and a fixture
  company named "Test Pick", tripping the wording gate; both fixed).
- **Full desk regression** (`copilot-app-desk*.spec.ts` + `copilot-app-trader.spec.ts`, tsc first):
  - Output: `tsc: clean` · `32 failed · 16 skipped · 592 passed (7.6m)`
  - The 32 failures are all `copilot-app-desk-strategy-graphs.spec.ts`, which needs a `VITE_STRATEGY_HARNESS=1` build
    (its own header says so). The same 32 fail on a clean `origin/dev` worktree (baseline: `32 failed · 184 passed` over
    the same spec files); `comm` of the two failure lists: 0 failures on this branch that are not on the baseline.
  - With `VITE_STRATEGY_HARNESS=1`, that spec on this branch: `32 passed (17.3s)`.
- Two existing specs were changed for intended behaviour changes (reasons in the commit and in the code):
  `copilot-app-desk-scanner.spec.ts` (the write check no longer counts the read-only `POST /api/desk/strategy/ideas|top`
  the boards call) and `copilot-app-desk-market.spec.ts` (opens the All list by URL, since the chip now survives a reload).
- Result: PASS (local, mocked)

## Data Correctness (staging)

**NOT RUN** — needs the merge. To check then: the F&O board's underlyings against `fno_eligible` in the scan snapshot
(`GET /api/positional/scan-universe`), each idea's `price_source` date against the latest bhavcopy, and the pulse's FII/DII
figure against `GET /api/markets/fii-dii` for the same session.

## Inputs required from user

- A staging `session_token` (for S-1…S-5 and a live walk). Not reused from another session's scratch folder.
- The merge of the PR to `dev` (the user merges; a merge deploys staging).

## UNVERIFIED

- Nothing of this has run against real staging data. Latency of `distinct` with up to 12 + 2 chain reads is unmeasured;
  `/ideas` alone took 7.5 s on staging (2026-10-25 log), and earlier calls show 499s (browser gave up). The boards load
  on their own and are cached for 15 minutes so the Scanner list never waits.
- Paper trades will not be recorded on the user's staging account without the user's say-so.

## Verdict: BLOCKED
