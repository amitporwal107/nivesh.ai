# Build your own multi-leg strategy in the Copilot chat, and back-test it

Date: 31 Oct 2026, facts refreshed 1 Nov 2026 · Status: PLAN. Nothing below is built. · Basis: code on `origin/dev` (read at `0e73741f`,
re-checked at `13f4ac9d`); data read from the staging warehouse, Mongo and the deployed backend on 31 Oct 2026, **read-only** (SELECTs and
imports with every storage write stubbed; nothing was left in the container: `ls /tmp/ov_*` there finds nothing).

Owner asks: "build up his own multi-legged strategies on NIFTY / BANKNIFTY / cash stocks / F&O stocks and back test it using Copilot chat";
the reference is an "AI strategy assistant" box ("I think NIFTY will be bullish over the next two days. Suggest strategies?", chips "NIFTY
price to stay range-bound", "Big move expected, unsure direction"; that image is not in the repo, so only those texts are known to me); and
"Plan a bearish trade for UNIONBANK instead" (UNIONBANK was a bullish scanner idea, so the one-direction-per-day rule applies).

## 1. In plain words

The pieces for **suggesting and editing** a strategy exist and are good: the desk already prices defined-risk option structures from the
real end-of-day chain, with payoff, breakevens, costs and Zerodha margin. What is missing is the chat front door and a place to keep a
draft while you change it. **Back-testing options is the hard part and it is thin**: the warehouse holds option prices for **13 months**
(1 Oct 2025 to 30 Oct 2026, end of day only). That is 56 completed NIFTY weekly cycles, 13 BANKNIFTY monthly cycles and 13 monthly cycles
per stock, all in one market regime. A replay of that is a useful "how would this structure have behaved in past expiries", not evidence that
a strategy works. Cash-stock back-tests already exist (an engine with costs and slippage) but are not reachable from chat.

**Recommendation.** Ship in three releases, each useful alone: **(A)** chat suggests and edits strategies from your view, and saves or
records them as paper trades (no back-test, all data real, no history limit); **(B)** add cash-stock back-tests through the engine that
exists; **(C)** add the options replay on the 13 months, labelled "replay on past expiries" with the number of cycles on screen. Buy no data
now. The model only turns your words into a short list of allowed edits; every number comes from the desk's engines.

## 2. Inventory (VERIFIED by reading code or running read-only, unless marked)

| Piece | Where | What it does today |
|---|---|---|
| Regime-fit board | `services/strategy_plan/regime_fit.py` | `ideas_for_underlying(request, symbol, regime, expiry, limit)` prices every defined-risk structure on the underlying's chain: 7 families (long call/put, bull call/bear put spread, bull put/bear call spread, iron condor), scored 0-100 on direction, volatility, breadth, positioning against the **desk's** regime; `build_top` per class (index options, stock F&O, cash); expiry rule: at least 1 session after the chain day; EOD chain only |
| Templates | `services/strategy_plan/templates.py` `CATALOG` | 13: the 7 above + covered call, protective put, collar (these hold shares), long/short future, cash long. **No long straddle or strangle** |
| Payoff | `strategy_plan/engine.py` `compute_payoff`, `POST /api/desk/strategy/payoff` | payoff at expiry and today, breakevens, `loss_unbounded` / `profit_unbounded`, Greeks, costs `desk-cost-v2`, capital at risk; takes up to 8 legs (the store, paper trade and risk gate take 4: `services/strategy_limits.py`) |
| Plan builder | `strategy_plan/plan.py`, `POST /api/desk/strategy/plan` | one deeply evidenced plan for a stock and a direction (cash, futures, options, combination), with reasons when there is no trade; TradePlans stored insert-once in Mongo `trade_plans` (779 docs on staging) |
| Chat trade idea | `services/copilot_trade_idea.py` | pre-step in `routes/chat.py`: for a trading question about a stock it runs the plan builder; `direction_of()` reads bullish/bearish/neutral from the words (VERIFIED: the owner's sentence gives `bearish`, stated); card only when status is `plan` or `wait` |
| Chat visual answers | `services/copilot_visual/*` | 16 intents incl. `fno_setups` (the F&O board with lots, live premiums, Zerodha margin); **no strategy-building intent**; `resolve_intent` returns None for all of: "Plan a bearish trade for UNIONBANK instead", "Suggest strategies for NIFTY bullish next two days", and the owner's full box sentence (run on the deployed backend) |
| Chart Analysis v2 basket | `tradingdesk/tabs/trade-desk/analysis/*` (`basket.tsx` 4 legs, `presets.ts`, `RecoStrategies.tsx`, `OptionChain.tsx`, `BasketPanel.tsx`) | the user picks legs on the chain, sees payoff/Greeks/margin, PLACE = `POST /api/desk/paper-trades` (kind `strategy`, Idempotency-Key). Presets include Long straddle and Short strangle; the paper route refuses undefined risk |
| Risk gate | `services/risk_gate/*`, `policy.py` | every paper entry is judged: defined risk only (naked short options and futures-only refused), exchange lots, listed expiry, the account's limits; the caps of 4 legs, 10 lots per leg, ₹2,00,000 capital at risk per structure and 10 open structures sit behind the `fno_risk_gate` rollout flag. Nothing places an order (`sent_to_broker: false`) |
| Strategy store v2 | `services/strategy_store.py`, `routes/strategy_builder.py`, migration 026 (dev, #398/#399) | the saved-strategy document: underlying, 1-4 legs with rule-based expiry (`nearest_weekly`, `nearest_monthly`, `next_monthly`) and strike (`atm`, `atm_offset_points`, `atm_offset_strikes`), `exit` fields (`profit_target_pct_of_net_debit`, `stop_loss_pct_of_net_debit`, `time_exit_sessions`, `close_before_expiry_sessions`), `source` user/ai/template, `blocking_for` for undefined risk. **Entry type is `manual` only and a v2 back-test answers 422 `backtest_not_available`** |
| Saved plans | `POST/GET /api/desk/strategy/plans` | `desk_strategy_plans`, immutable, 200 per user (0 docs on staging) |
| Option replay of a trade | `services/desk_strategy_trades.simulate_strategy` | replays 1-4 legs on real bhavcopy prices for an **open paper trade** (stop-first, premium stop/target, expiry settlement at intrinsic, option marks at close not settle). No loop over history |
| Equity builder + back-test | `routes/strategy_builder.py`, `services/strategy_engine/*`, UI `trader/strategy` (still mounted) and the legacy chat widget `strategy_lab` | v1 DSL screen → back-test → save; adjusted prices, liquid universe `liquid-eq-v1`, costs `desk-cost-v2`, slippage, exits `exit-rules-v1`; long only; runs inside the web request |
| Earlier research | `docs/FO_RANKING_BACKTEST_FINDINGS_20261023.md`, `services/fno_backtest`, `fno_forward` | pre-registered studies found **no ordering skill** in the F&O ranking; the forward test shows no mean or t before 30 judged signals |
| PRDs | `docs/Nivesh_AI_Strategy_Copilot_Complete_PRD_v1.0.docx`, `..._Paper_Trading_Strategy_Lab_PRD_V5.docx`, review `docs/strategy_copilot_review_20261028/` | chat-first create → validate → back-test → refine; the review's decisions D1-D5 still stand (one Postgres store, naked shorts blocked, app LLM setting, daily only) |

## 3. The UNIONBANK case, measured (staging, data day 30 Oct 2026, read-only, storage writes stubbed)

1. Visual intents: `resolve_intent("Plan a bearish trade for UNIONBANK instead")` → **None**. The sentence is the button text of the chat's
   own trade card (`TradePlanChatCard.tsx`: "Plan a {other} trade instead" sends `Plan a ${other} trade for ${symbol} instead`).
2. Legacy trade-idea path does run: direction `bearish` (stated), symbol `UNIONBANK`, plan status **`no_trade`**, no card. Reasons: conflicting
   evidence (5 against, 3 for); cash plans are long only; "long unwinding" is not fresh selling; reward:risk 1.18 below the 1.5 minimum; no
   combination strategy for a bearish view. The LLM then words this from context. (I called `copilot_trade_idea.build` directly with storage stubbed; the chat route's pre-step order end to end was not exercised: UNVERIFIED.)
3. The regime-fit board for the same stock (regime `bearish`, VIX 15.3 low, breadth down, as of 30 Oct): 8 structures priced, 0 dropped,
   expiry 23 Nov, spot ₹186.00, lot 4,425. Bearish ones: **Bear put spread 175/185** fit 92.5, max loss ₹13,452, max profit ₹30,798, breakeven
   181.96; Long put 185 max loss ₹20,178, breakeven 180.44; Long put 182.5 max loss ₹15,576, breakeven 178.98; Bear call spread 190/192.5 fit 70,
   max loss ₹7,434, max profit ₹3,628.50. (A long put's "max profit" of ₹7.98 lakh is the stock at zero; the desk shows it as "Not capped", per
   the owner's rule.)
4. UNIONBANK is **#3 of the bullish cash ideas** on the AI scanner list of 2026-10-30 (`ai_watchlist_days`).
5. Two engines disagree (plan builder: no trade; board: fit 92.5). **The board's fit is the market regime's, not the stock's.**
6. Code finding: `flag_cash_conflicts` (`regime_fit.py`) marks **every** bearish stock idea as conflicting with a "bullish cash setup", because
   it assumes every stock on the board is a bullish scanner name. That holds on the board (its stock names come from the scanner's list) but not for a chat path that prices any stock the user names. And the rule
   "cannot be recorded as a paper trade" is enforced only in the UI helper `paperTradeProblem` (`strategy/top-actions.ts`) and as a TradePlan
   `risk_flag`; `risk_gate` and `routes/desk_trading.py` have no such check (grep found none), so a chat "record it" would not be stopped by the server.

**Answer the chat should give (deterministic, new intent `strategy_ideas`, params `view`, `underlying`):**
(i) headline: "No bearish setup for UNIONBANK today, and the AI scanner holds it as a bullish idea"; (ii) notice: the conflict text ("shown for
information and cannot be recorded as a paper trade today"), only when the scanner's own stance for **that** stock is the opposite;
(iii) list: the plan builder's reasons above; (iv) `ranked`: the bearish structures that price on today's chain, one lot, expiry, max loss,
profit ("Not capped" for bought options), breakeven, Zerodha margin or the Kite-login prompt, labelled "for information"; (v) list: what would
change it; (vi) no paper-trade button while the conflict stands; sources and data days shown. A stock the scanner does not hold gets (iii)-(v) and,
if the plan builder finds a setup, its normal card.

## 4. Can options be back-tested honestly? Measured feasibility

Commands: read-only `SELECT`s through `~/.config/nivesh/nidp-psql.sh` on `nidp.fno_bhavcopy` (columns `ticker_symbol`, `instrument_type`
IDO/STO/IDF/STF, `expiry_date`, `strike_price`, `option_type`, close/settle, `traded_volume`, `open_interest`, `new_board_lot_qty`).

| Measure (31 Oct 2026) | NIFTY | BANKNIFTY | RELIANCE | UNIONBANK |
|---|---|---|---|---|
| First / last session, sessions | 2025-10-01 / 2026-10-30, 266 | same | same | same |
| Option expiries listed / already expired | 75 / 57 (weekly) | 20 / 14 (monthly only) | 16 / 13 | 16 / 13 |
| Lot size over the period | 75 then 65 | 35 then 30 | 500 | 4,425 |
| Strikes on the last session, nearest expiries | 104, 104, 88, 122 (20,050-25,200; spot 23,053) | 154, 148, 121, 14 (46,500-65,500; spot 54,687) | n/m | 25 strikes, 3 expiries |
| Contracts within ±3% of spot and ≤35 days to expiry that traded | 86.5% of 79,368 | 98.3% of 21,806 | 99.9% of 5,244 | 97.6% of 2,602 |
| Median volume / open interest in that band (as stored) | 1,530 / 57,105 | 9,338 / 79,650 | 5,295 / 1,317,750 | 454 / 1,517,775 |
| **Usable cycles**: entry on the 3rd session before expiry, call and put both traded at each of 5 listed strikes (ATM, ±2, ±4 positions) that day | **56 of 57** | **13 of 14** | **13 of 13** | **10 of 13** |

(For NIFTY and BANKNIFTY one expiry each has its entry day before the data starts; every other cycle had a full ladder, except 3 UNIONBANK cycles with an untraded wing.) Whole table overall: 10,482,567 rows (index options 1,367,229; stock options 8,945,225; index futures 4,155; stock futures 165,958), 244
tickers, 218 stocks with options on the last session. Equity and index prices run longer: `nidp.prices_eod_adjusted` 2024-04-01 to 2026-10-30,
638 sessions, 3,033 symbols; NIFTY 50 index 638 rows. Not re-measured today, from the 28 Oct audit
(`docs/strategy_copilot_review_20261028/C_data_coverage.md`): no bid or ask, no per-contract historical Greeks, no historical margin, no
intraday bars (`nidp.intraday_bars` does not exist), implied-volatility history only for NIFTY and BANKNIFTY at the money, adjusted equity
prices thin before 2025-10-01 (about 1,200 symbols a session) and demergers unadjusted, charges are today's rates (`desk-cost-v2`; F&O rates
copied from Zerodha on 27 Oct, effective date UNVERIFIED in the code).

**What the replay can honestly be ("replay on past expiries", end of day only):**
entries by calendar ("N sessions before expiry") or by a daily signal on the underlying; expiry and strikes chosen by rule from **that day's** chain only
(`atm`, offsets in listed strikes; no delta rules, there is no IV history to compute them); fills at the close ± 0.05% slippage per side and **only
if the contract traded that session**, else the cycle is skipped and counted with the reason; exits by the underlying levels, premium targets or time
(the store's `exit` fields), settlement at expiry at intrinsic against the underlying's close; lots from the contract's own `new_board_lot_qty` on that
day; charges from `desk-cost-v2` per leg per side; defined-risk structures only, so capital at risk is the maximum loss and margin is not modelled.
Output: every cycle, the count of cycles run and skipped, win rate, average and worst, drawdown of the sequence; **fewer than 30 cycles is shown as
"inconclusive"** (the rule `fno_forward` already uses). Tests must include a look-ahead test (append poisoned future rows, require identical
trades; the Stage A study did this) and a carried-forward-close test.

**What it cannot be:** intraday or tick; bid/ask or spread; stress on liquidity; margin history; assignment of stock options (settled as intrinsic cash
P&L here); anything before 1 Oct 2025; a statistical test. One year in one drifting regime (the Stage A write-up calls its test split exactly
that) means the same structure can look good or bad because of the market, not the structure.

**Where more history could come from (none bought, none verified by me today):** Kite: the platform reads only unexpired contracts from Kite's
instrument list (`kite_live_feed/intraday.py`, `fno_options_intraday.py`); daily continuous **futures** with OI reach back to Oct 2021 (Stage A doc,
verified 23 Oct); whether Kite serves expired option contracts is UNVERIFIED and no platform code asks. TrueData (memory `truedata-vendor-decision`, trial
finding of 29 Oct, not re-run): expired F&O 1-minute data to April 2024, daily from 2008, bid/ask; **its licence says it does not provide data for
simulation or virtual trading without SEBI/exchange approval**, and a back-test shown to users is that. NSE's own older F&O bhavcopy archive:
availability and the old file format are UNVERIFIED (the platform's ingester starts at 2025-10-01).

## 5. Chat flow (what the model may and may not do)

1. **Intent and slots, deterministic first.** Patterns for "suggest/plan/build ... strategy/trade ... <underlying> ... bullish/bearish/range-bound/big move",
   plus the two chips: "NIFTY price to stay range-bound" → view `flat`; "Big move expected, unsure direction" → `big_move`. Slots: underlying (NIFTY,
   BANKNIFTY, FINNIFTY, MIDCPNIFTY, or an F&O stock from the symbol resolver), view, horizon in sessions (an expiry that is at least that many sessions
   away, else the next), lots. A missing slot becomes a chip question, never a guess. The LLM (provider chosen by `llm_provider()`; staging chat now
   Groq per the coordinator, UNVERIFIED by me) is used only when patterns fail, through a forced tool call returning slots.
2. **Candidates.** view `up` → long call, bull call spread, bull put spread; `down` → long put, bear put spread, bear call spread; `flat` → iron condor;
   `big_move` → long straddle, long strangle (**new templates**, defined risk, debit). Listed from `regime_fit` pricing; ranked by reward:risk and cost
   within the view; the desk regime's agreement is shown as its own column ("desk trend: down, your view: up, fit 37.5"), so your view selects and the
   regime informs. Index → options only (no cash leg); stock → options, plus covered call / protective put / collar only when you say you hold the shares.
3. **Draft.** One structure is the working draft: a v2 strategy document plus the chain day, kept server-side (Mongo `strategy_drafts`, owner-scoped,
   expires in 7 days). Answer shows legs, net premium, max loss/profit ("Not capped" where bought options or the payoff says unbounded), breakevens,
   capital at risk, charges, Zerodha margin (or the Kite-login prompt), and a new `payoff` block (curve at expiry and today; the desk's `PayoffChart`
   data from `/api/desk/strategy/payoff`).
4. **Edit by chat.** The model may return only operations from a closed set: `set_lots`, `set_strike(leg, strike)`, `set_expiry`, `add_leg`, `remove_leg`,
   `swap_template`, `set_underlying_stop/target`. The server checks each against the chain (strike listed and traded, expiry listed, ≤4 legs, 1-10 lots,
   defined risk), applies, re-prices with the same engine and prints a diff line ("Short strike 23,300 → 23,350; max loss ₹5,171 → ₹6,020").
5. **Refusals (always with the reason and what is allowed):** naked short option, short future, ratio spread, any unbounded-loss structure → the payoff may be
   drawn, max loss reads "Not capped", **no save, no paper, no back-test** (decision D2 of 28 Oct); more than 4 legs; calendars/diagonals; intraday;
   strike not listed or not traded; stock not in the F&O list; chain older than the previous session (stale rule); lots over the cap.
6. **Back-test.** Cash-stock rules: translate to the v1 DSL from a closed template set, run the existing engine. Options: validate, run the replay (section 4),
   show KPIs, equity curve, cycle table, assumptions and "inconclusive" when n < 30. Nothing is tuned: no search for the best strike.
7. **Save / record.** "Save" creates a v2 document through `POST /api/strategy-builder/strategies` (source `ai`, Idempotency-Key). "Record as paper trade"
   opens the existing ticket with the legs filled (first release) or shows a confirmation card that calls `POST /api/desk/paper-trades` (later). Either way
   the risk gate decides; the one-direction rule is added **on the server** for the record step. Nothing places an order.

**Wording (SEBI, owner rule 25 Oct):** "structures that fit the view you stated", "ideas", never "recommended", "best" or "picks"; results are
"how this structure would have behaved in past expiries; not a forecast"; the model never states a probability or a return.

## 6. Slices

| # | Slice | Acceptance criteria | Depends on | Size | Who verifies what |
|---|---|---|---|---|---|
| SB1 | `strategy_ideas` intent, read only: suggest by view for index and stock; the UNIONBANK answer; per-stock conflict check against that day's `ai_watchlist_days` (replaces the blanket flag) | The three sentences of section 1 and 3 resolve; the UNIONBANK answer has the six parts above on real data and no paper button; a stock the scanner does not hold is not flagged; the card's "Plan a {other} trade instead" button resolves | none | M | Eng: `test_copilot_visual.py` (+ `test_c2` capture, `test_sg_t1b` template, spec INTENTS), `test_regime_fit.py`. QA: probe over staging data for NIFTY up/down/flat and UNIONBANK |
| SB2 | Long straddle and long strangle templates | Payoff, breakevens, costs tie to a hand calculation; risk gate accepts; `big_move` chip answers | SB1 | S | Eng: `test_strategy_plan_templates_route.py`. QA: one real chain |
| SB3 | Draft store, edit operations, payoff block, margin line | Each op accepted or refused with a reason; diff line correct; another user's draft 404; draft expires; model output outside the op set is dropped | SB1 | L | Eng: unit per op, contract fixture. QA: 10 real edits on staging |
| SB4 | Save and record | Save creates a v2 strategy (source `ai`) once per Idempotency-Key; record goes through the risk gate; **server-side** one-direction check refuses an opposite-stance record with its reason; no order anywhere | SB3, decision 4 | M | Eng: route tests incl. a backend contract test per request body (memory: a mocked e2e once hid a 422). QA: real record then close on a test account |
| SB5 | Cash-stock back-test from chat | Closed template set → v1 DSL → existing engine; result shows window, universe basis, costs, slippage, n; unsupported rule gets the refusal text | decision 1 | M | Eng: DSL translator golden set. QA: one run compared with the Strategy Builder page for the same rules |
| SB6 | Options replay engine v0 + job | Section 4 rules; look-ahead and carried-forward tests pass; skipped cycles counted; cycle table reconciles with `simulate_strategy` on the same legs; run under the web timeout or as a job | SB3 | L | Eng: engine tests. QA: NIFTY weekly condor, 56 cycles, hand-check 3 |
| SB7 | Chat back-test of an options draft | Results block (KPIs, curve, cycles, assumptions, "inconclusive" under 30); stale or missing data states; save the run with the version | SB6 | M | Eng + QA as above; owner: reads the wording |
| SB8 | Later: signal entries, version compare, sensitivity | not scoped | SB7 | — | — |

## 7. Decisions needed from the owner

1. **First release scope.** (a) A only: suggest, edit, save, paper (recommended first); (b) A + cash-stock back-test; (c) A + options replay. Order recommended A → B → C as separate releases. Cost of going straight to C: about two weeks of engine work (the 28 Oct review's estimate) for 56 NIFTY cycles and 13 per stock.
2. **Buy or license history?** Recommended: no purchase now. Ask TrueData in writing whether a user-visible back-test counts as "simulation" under its licence before any use. Cost of waiting: stay at 13 months. Cost of buying: about ₹10k a month budget you named, plus licence risk.
3. **The one-direction rule.** (a) Keep as "information only", enforce on the server for records, apply only when the scanner holds the **opposite** stance on that stock (recommended); (b) drop it; (c) keep today's blanket flag. Cost of (c): in the new chat path a stock the scanner never named would be wrongly blocked.
4. **Your view or the desk's regime?** Recommended: your stated view picks the structures, the regime's fit is shown beside them. The alternative (only regime-fitting ideas) hides the structure you asked for.
5. **Naked and unbounded structures.** Recommended: show the payoff with "Not capped", no save/paper/back-test (your 28 Oct decision). Alternative: not even draw them.
6. **Where saved strategies live** now that Strategy Lab is removed. Recommended: the Copilot "Saved" page gets a Strategies section; keep `trader/strategy` for the equity builder until SB5 replaces it. You have not decided what happens to the legacy `strategy_lab` chat widget and that rail item.
7. **Name and minimum of a back-test.** Recommended: "Replay on past expiries", below 30 cycles shown as "inconclusive". Alternative: allow any n with a warning.
8. **Model for edits.** Recommended: keep the closed operation set so a small model is enough; enable free-text edits only after a golden set passes; chips otherwise. English first; Hinglish after you give sample sentences.
9. **Underlyings in release A.** Recommended: NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY and the 218 F&O stocks (same code). "Cash stocks" means stock+option combos (shares you hold) and, in release B, rule-based cash strategies.

## 8. Risks

- **SEBI wording / advice.** Turning a stated view into specific contracts is close to personalised advice; the same compliance question was raised for hedge ideas on 31 Oct. Keep "ideas that fit your stated view", show the regime and data dates, state that results are not forecasts, and get a compliance position before release A reaches users.
- **Data freshness.** Chain from the latest completed session or the one before only; stale → refuse with the date. Live premiums only while the Kite feed is live and every leg is live, else all end-of-day (existing `fno_board` rule).
- **Statistical misuse.** 13 months, one regime, 13-56 cycles: no Sharpe, no "win probability", no parameter search (an optimiser over 56 cycles overfits; the Stage A study found no ordering skill).
- **Cost.** LLM only for slots and edit ops (small, closed outputs); provider quota applies. Replay compute is small at this size (UNVERIFIED: latency, to be measured in SB6).
- **Security.** Drafts and strategies owner-scoped (404 otherwise); writes from the user's session with the Origin check and Idempotency-Key; model output is data, never executed; no endpoint places orders; server re-validates every edit.
- **Two engines disagree** (plan builder vs board) as in section 3: the answer must show both and say which is which.

## 9. What I would NOT build

Intraday or tick strategies; more than four legs; calendars, diagonals, ratio spreads; back-tests of naked shorts; delta-targeted strikes (no IV history); a "best strategy" ranking by past performance; an optimiser that searches strikes for the best replay; probability-of-profit numbers; live execution; sharing or publishing strategies; a second payoff engine for chat.

## 10. Not verified

Latency of a replay and of a chat suggestion; whether Kite serves expired option contracts; NSE older bhavcopy availability and format; TrueData trial claims (memory note, not re-run); the content of the owner's reference image beyond the two chips; how the staging Groq model handles forced tool calls; the effective date of the F&O charge rates; stock-option settlement mechanics (modelled as intrinsic cash P&L).
