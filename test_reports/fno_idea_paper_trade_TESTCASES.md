# Test cases — F&O idea "Paper trade" request (Phase 0 item 0.1, release gate 7) + display-only idea levels (owner decision D4)

- **Branch:** `fix/fno-idea-paper-trade` (off `origin/dev` 5b6b3cfd)
- **Authored:** 2026-10-27, before implementation, after the API and UI design below.
- **Sources:** `docs/NIVESH_AI_LAB_GUIDELINES_GAP_STUDY.md` §4 N3, §6 item 0.1 and Phase 3, §9 items 4–5;
  `docs/ai_research/guidelines_gap_study_20261027/B_plan_lifecycle_exits.md` B1, §8, §9; probe `probe/strat_body.py`.

## Bug (verified before any change)

`strategy/top-actions.ts paperTradeBodyFor` sends no `signal`. `services/desk_strategy_trades.new_strategy_trade` calls
`clean_signal(body.get("signal"), moment)`, which raises `invalid_signal` (HTTP 422) on `None`. Every F&O idea "Paper
trade" button (Top by regime, desk Top 10 F&O rows, lab focus, AI watchlist F&O rows) is refused. The e2e mocked the POST
as 201, so it passed.

## Design

**Request.** `paperTradeBodyFor(idea, { rulesVersion, levels })` adds
`signal = { signal_at: idea.data_as_of.chain, rule_version: <board rules_version>, source_refs: [...], evidence_summary: <fit
score + the fit reasons> }`. When the levels engine answered for this idea (valid, engine view = the idea's direction,
bullish/bearish) it also sends `stop_underlying` = the engine's underlying stop and `target_underlying` = its target 1, each
only when it is on the side of the reference price the route requires. Otherwise no level is sent (exits: expiry or
manual, as before). No data date or no rules version → no body (button disabled with the reason).

**Levels on rows (display only).** `POST /api/desk/strategy/levels` (services/strategy_levels, the lab's engine) on the idea's
own payoff request, refs `{put_wall: null, call_wall: null, expected_move: <the board's expected move for the underlying>}`.
Shown: entry (net debit/credit), stop, target 1 and 2 with the underlying levels, max loss, the label "Provisional ·
research levels", the chain date, and a "Full plan" toggle that opens the lab's full levels card. No new entry control.
AI watchlist: the levels stored with that day's list (`strategy_levels` on each F&O entry, written by the nightly job by
calling `strategy_levels.compute` in-process); a day without them says "not stored with this day's list" and nothing is
recomputed. Desk Top 10 stock rows: the scanner's entry/stop/target in the row, same label, scan date.

**Contract.** One shared fixture `frontend-v5/e2e/fixtures/contract-fno-idea-paper-trade.json` holds the levels request and
the two bodies the browser sends for the fixture idea (BANKNIFTY bear put spread from the real 2026-10-21 staging capture
`desk-strategy-top.json`). Playwright asserts the browser sends exactly those; pytest pushes the same bodies through the
real route and validator. The mocked levels reply `desk-strategy-levels-banknifty.json` is asserted by pytest to be exactly
what `strategy_levels.compute` returns for that request.

## Test cases

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| B-1 | backend contract | `body_with_levels` from the shared fixture → `POST /api/desk/paper-trades` (real route, repo fakes, clock 2026-10-22) | api | 201; stored doc kind strategy, open; `signal.signal_at` 2026-10-21, `rule_version` = the board's, source refs and evidence stored; stop/target = fixture |
| B-2 | backend contract | `body_without_levels` → same route | api | 201; stop and target null; signal stored |
| B-3 | regression | the pre-fix body (fixture minus `signal`) | api | 422 `invalid_signal`; nothing stored, no cash reserved |
| B-4 | contract | fixture levels reply == `strategy_levels.compute(fixture levels request)` | unit | equal (the e2e's mocked reply is the real engine's output) |
| B-5 | contract | `body_with_levels` stop/target == the levels reply's underlying stop / target 1 | unit | equal (the trade records the levels the row shows) |
| B-6 | parity | `ai_watchlist_build.payoff_request_for(idea)` + `levels_refs_for(top, underlying)` == fixture levels request | unit | equal (nightly stored levels = the live row's levels for the same idea) |
| B-7 | job | `shape_day` stores `strategy_levels {as_of, computed_at, refs, result}` per F&O entry = `compute(...)` | unit | equal; `sent_to_broker` stays False |
| B-8 | job failure | an idea with no reference price/legs → `result: null` + reason; an engine exception → `error` stored, warning logged, the day still builds | edge/failure | as stated |
| B-9 | regression | `test_desk_strategy_trades`, `test_desk_trading`, `test_ai_watchlist`, `test_strategy_levels`, `test_regime_fit`, `test_regime_fit_distinct` | unit/api | all pass |
| F-1 | Top by regime | levels request sent for the BANKNIFTY card | e2e | body == fixture `levels_request` |
| F-2 | Top by regime | Paper trade with levels answered | e2e | POST body == fixture `body_with_levels` |
| F-3 | Top by regime | Paper trade when the levels route fails | e2e | POST body == fixture `body_without_levels` |
| F-4 | Top by regime | the levels block | e2e | "Provisional · research levels", "21 Oct 2026", entry net debit, stop + underlying, targets, max loss = fixture reply; "Full plan" opens the full card; no button in the block except the plan toggle; one Paper trade button per card |
| F-5 | Top by regime | levels still loading | e2e | Paper trade disabled until the levels answer, then the body carries them |
| F-6 | Top by regime | a neutral idea (view flat) with levels answered | e2e | no stop/target sent |
| F-7 | desk Top 10 F&O | BANKNIFTY row | e2e | levels block with label/date/plan toggle; Paper trade POST == fixture `body_with_levels` |
| F-8 | desk Top 10 stock | ICICIBANK row, before expanding Paper trade | e2e | entry ₹1,200.00 · stop ₹1,160.00 · target ₹1,280.00, the label and "scan of 19 Oct 2026" |
| F-9 | AI watchlist F&O | BANKNIFTY with stored levels | e2e | stored levels shown with label and "worked out on the list day"; Paper trade POST == fixture `body_with_levels` |
| F-10 | AI watchlist F&O | MPHASIS without stored levels | e2e | "not stored with this day's list"; no `/api/desk/strategy/levels` request from the watchlist; Paper trade sends no stop/target |
| F-11 | wording | the new blocks | e2e | no picks / suggested / recommended (existing F-16, F-9 cover the whole text) |
| F-12 | phone | 390px | e2e | no sideways scroll (existing F-26, F-10) |
| F-13 | lab focus | `copilot-app-desk-lab` | e2e | still passes (IdeaCard change) |
| S-1 | staging, read only | newest stored watchlist F&O ideas on staging: levels from the deployed engine; a body built by the same rule passes `new_strategy_trade` in-process (pure, no write) | data | every idea priced; levels valid; bodies accepted |
| S-2 | staging, signed in | click Paper trade on a staging F&O idea | e2e (manual) | 201 — **UNVERIFIED until the owner provides a session token** (writes a paper trade) |
