# Nivesh AI Lab trading guidelines: implementation gap study and recommendation

**Date:** 2026-10-27
**PRD studied:** `docs/NIVESH_AI_LAB_TRADING_DECISION_GUIDELINES.md` (all 14 sections)
**Acceptance standard:** `docs/NIVESH_AI_LAB_PHASE_SUCCESS_CRITERIA.md`, the owner's success criteria per phase (2026-10-27). A phase is reported complete only against that file.
**Code basis:** origin/dev `5b6b3cfd`. Staging runs the same commit.
**Evidence:** three detailed studies with file:line citations and real query and test output, plus their probe scripts, in
`docs/ai_research/guidelines_gap_study_20261027/`:
- `A_risk_controls.md`
- `B_plan_lifecycle_exits.md`
- `C_research_and_data.md`

This study replaces two earlier inputs: the quick review given in chat on 2026-10-27, and the outside review that the user
pasted. That outside review states it "is not an independent inspection of the repository". This one is.

---

## 1. Final recommendation

**Keep the outside review's order: risk, then lifecycle and exits, then decision cards, then research. But put a short
Phase 0, "make paper results honest", in front of it.**

The study found that today's paper-trade results and the AI scanner's inputs are wrong in ways that would make every later
control meaningless. A risk governor that sizes trades from corrupt bars, or books fills the market never offered, still
produces wrong numbers. All of the following are verified:

1. **The AI scanner's price history is corrupt.** It contains 14 NSE-holiday sessions whose bars are exact copies of the day
   before. On 2 Oct, 2,908 of 2,908 rows match 1 Oct; on 26 Jan, 2,501 of 2,501 match 23 Jan. It is also missing the real
   sessions of 21 and 22 Oct. On top of that, it uses unadjusted prices, and 91 symbols had a split or bonus inside its window.
2. **One-click paper trades are booked at the scanner's entry price, even when the market never traded there.** Example:
   FEDERALBNK on 26 Oct was booked at 316.89 against a close of 344.40. It showed ₹3,861 of profit where a real buyer would
   have made ₹1,110.
3. **Closed-trade P&L uses the reference entry price, not the simulated fill.** A trade that gapped in books ₹1,000 instead of
   ₹600.
4. **Every F&O idea's "Paper trade" button fails.** The backend rejects it with 422 `invalid_signal`. This is a bug in work
   shipped in #349 and #352; the e2e tests mocked a success response.
5. **The journal skips the kill switch whenever the F&O gate is off**, which it is on staging. A ₹1 crore fill was accepted
   with the kill switch on.
6. **Duplicate trades are accepted.** Staging has HAL opened three times and ICICIBANK twice, at identical levels. The three
   HAL trades stopped out together for −₹15,412.
7. **The evening exit job is not installed on staging.** Open trades close only when someone opens the paper-trade list.

**Phase 0** is nine small code fixes and four staging operations that need your approval. It is about 1–1.5 weeks with tests.
After it come:
- **Phase 1:** one risk-decision service on every entry path.
- **Phase 2:** one canonical trade plan, a lifecycle, and real paper-trade exits.

Phases 1 and 2 together are about 4–6 weeks; all effort figures are estimates. Once the canonical plan exists, decision cards
(Phase 3) mostly follow from it. Research hardening (Phase 4) can start as soon as the price history is fixed. Intraday
strategies and new bearish strategy families come last.

**Agreed with the outside review:** do not add indicators and do not change the scanner's score weights now. There is no
calibration evidence: every outcome and calibration table on staging has 0 rows.

---

## 2. How the study was done

- Three read-only studies ran in parallel: (A) risk controls and execution safety; (B) trade plan, lifecycle, exits and
  decision card; (C) research validation and data.
- Each one read the code at `5b6b3cfd`, ran the existing tests and queried staging read-only. Mongo was read through the
  backend's own client with allow-list projections; the NIDP warehouse was read with SELECT only.
- Behaviour that would need a write was tested with the repository's own test fakes, in a throwaway container with no
  network. Nothing on staging, and nothing in the code, was changed.
- Existing tests, all passing:
  - A: 817 passed across 20 suites.
  - B: 327 passed.
  - C: 361 + 449 passed.
- **They pass because they test what exists. None of them covers the defects below.**
- I re-checked the most consequential claims myself, against code and staging:
  - the journal kill-switch bypass (`routes/positional_journal.py:315`);
  - the kill switch on the desk;
  - the ₹10 lakh constant (`services/paper_account.py:37`);
  - the flag's default;
  - short futures stamped as defined risk (`services/desk_strategy_trades.py:209-210`);
  - the F&O button 422 (`top-actions.ts:65-87` against `desk_strategy_trades.py:318`);
  - P&L from the reference price (`services/desk_trading.py:697-699`);
  - `at_once` entries assumed filled (`:554-563`);
  - the missing cron files (`/etc/cron.d`);
  - the phantom and missing scanner sessions (SQL);
  - `fno_iv_history` = 0 docs.

  **All confirmed.**

---

## 3. What the earlier reviews got right, wrong, or missed

| Earlier claim | Verdict | Evidence |
|---|---|---|
| Desk paper trades check only the kill switch | **Mostly true.** The desk also reserves cash atomically (quantity × entry must fit) and caps open trades at 100. It runs no risk-governor limit. | A §0, `routes/desk_trading.py:103-155` |
| Governor limits apply only to AI Trader | **True, and the governor has never run on staging.** No screen calls `/api/ai-trader/*`, and there are 0 AI-trader tickets. | A Q1, Q9 |
| `fno_risk_gate` is off by default | **True; also off on staging.** It was on for about 80 seconds in a test on 24 Oct. | A Q4 |
| Capital is a hard-coded ₹10 lakh | **True for the paper account.** The governor instead uses each AI strategy's user-chosen `initial_capital`, up to ₹1,000 crore. At ₹10 crore it approved 2,857 shares unchanged. | A Q2 |
| No ATR trailing in paper trades | **True.** Trailing exists only in the DSL backtest, and its exits are recorded as "STOPLOSS". | B §0 |
| No time exit in paper trades | **Wrong in code, true in practice.** `max_hold_sessions` exists, but only the Strategy Builder's F&O path sends it. On staging, 0 of 9 trades have it, and the AI Trader drops `max_hold_days`. | B §0 |
| No unified lifecycle | **True.** Six stores with six sets of status words. Only the AI Trader and the Builder's F&O path link a trade back to its source. | B §4 |
| Top 10 and watchlist rows show no entry, stop or target | **Partly wrong.** Watchlist cash rows show them. Top 10 stock rows show them only after "Paper trade" is expanded. F&O rows on both boards show none. | B §8 |
| R multiples, stop method, % of portfolio, costs and exit plan are missing from the card | **Mostly true.** No screen labels R anywhere, and nothing computes % of portfolio. | B §8 |
| No ADX/+DI/−DI | **Wrong as stated.** ADX exists in Top Movers, the chart and the AI Trader trend. It is absent from everything that ranks or decides. | C §0 |
| Staging `adj_close` is null | **Fixed since.** All 1,098,819 warehouse rows are adjusted. The scanner just doesn't use them. | C §0 |
| Worked examples A–H are not tests | **True, but the code reproduces every figure exactly.** The gaps are cost-free sizing, gap fills at the stop, no intraday or short-cash path, and an untested trailing stop. | C §2 |
| IV history is empty | **True:** 0 docs, recorder cron not installed, not read by regime-fit. | C Q4 |
| Backtests lack Sharpe/Sortino, exposure, turnover, rejected-signal coverage | **True for every engine.** The F&O studies and the AI Trader do have cost stress, data splits, permutation tests, walk-forward folds and a sealed holdout. | C Q5 |
| Live execution | **Separated today.** No order call exists (enforced by an AST test), `LIVE_EXECUTION_AVAILABLE=False`, and no OpenAlgo or order route is mounted. The only barrier is that test. | A Q7 |

---

## 4. New findings not in either review (ranked)

| # | Finding | Evidence | Severity | Fix |
|---|---|---|---|---|
| N1 | The scanner's price history (`stock_ohlcv`) has 14 phantom holiday sessions copied from the day before and is missing 21–22 Oct. Every feature window, RSI, volume baseline and the market-breadth series is affected. | C Q1; my SQL check; `positional_engine/bhavcopy_ingester.py:69` stamps the *requested* date | **Critical** | Phase 0.8 |
| N2 | The scanner uses unadjusted prices (91 symbols had a split or bonus in its window; KOTAKBANK goes 2133 → 421). | C Q1 | High | Phase 4.2 |
| N3 | Every F&O idea "Paper trade" button returns 422. | B1; `top-actions.ts:65-87`, `desk_strategy_trades.py:318` | High | 0.1 |
| N4 | One-click trades (Top 10, watchlist, scanner) are booked `at_once` at the scanner entry, including pullback limit levels 8–11% below the market. | B3; `ScannerTop10.tsx:84` sends no `entry_rule`; `desk_trading.py:554-563` | High | 0.3 |
| N5 | Closed-trade P&L and costs are computed from the reference entry, not the simulated fill, so a trade's P&L jumps when it closes. | B2; `desk_trading.py:697-699, 714-715` against `:860-862` | High | 0.2 |
| N6 | A journal ENTRY fill skips the kill switch when the gate is off. The flag's own description says "Off = the kill-switch check only", and an existing test locks the bypass in. | A R24; `positional_journal.py:315` | High | 0.4 |
| N7 | No idempotency key and no same-symbol check on the desk. Staging has HAL ×3 and ICICIBANK ×2 at identical levels. | A R17, B §4a | High | 0.5 |
| N8 | With the gate off, the desk stamps futures-only structures, short futures included, as `defined_risk: True`. It also accepts any lot size: NIFTY at lot size 1 reserved ₹25,000. | A R15; `desk_strategy_trades.py:209-210` | High | 0.6 |
| N9 | Exit job, IV recorder and F&O forward-test cron are in the repo but not installed on staging. | B6, C Q4; `/etc/cron.d` | Medium | 0.7 (ops) |
| N10 | The paper account is misstated. One open ICICIBANK trade holds no reservation, so available cash is overstated by ₹1,24,618. A NIFTY spread closed with P&L `None`, which never reached cash. | A Q9 | Medium | 0.9 |
| N11 | The governor passes when its inputs are unknown. Drawdown is unknown whenever an F&O structure is open, sector and ADV are never supplied, the event blackout is never set, and the daily loss limit counts realised P&L only. | A Q3 | High | Phase 1 |
| N12 | Neither the governor nor the gate counts costs or gap stress. On Example A, the loss at the stop after costs is ₹3,098.94 against a ₹3,000 budget. The gate's per-trade cap is ₹2 lakh of *notional* for cash, not stop risk. | A R5/R8, C §2 | Medium | Phase 1 |
| N13 | The same stock and day get opposite directions: on 26 Oct, five names were bullish cash ideas and bearish F&O ideas. The plan labels the scanner's stop "2×ATR" when it is 1.5×ATR. | B5, B4 | Medium | Phase 2.1 |
| N14 | Missing data is hidden: missing scanner inputs score 0.5, a missing macro state becomes ×1.0, and the benchmark close is carried forward with no age limit. The 26 Oct list used a regime from 23 Oct, and a trade was opened on a 9-month-old signal (NORTHARC, signal 2026-01-22). | C Q4, B9 | Medium | Phase 4.3 |
| N15 | AI Trader paper trades drop the strategy's `max_hold_days`, so the paper result is not the backtested strategy. | B7; `ai_trader/execution.py:266-280` | High (when used) | Phase 2.3 |
| N16 | The backtest is optimistic: it fills a gap at the stop, raises the trailing stop with a bar's high before testing that bar's low, enters at the signal bar's close, and counts calendar days. | B §6, C §2 | Medium | Phase 2.4, 4.5 |
| N17 | Scanner signals are overwritten on re-run (`ON CONFLICT DO UPDATE`), so a paper trade can cite levels that no longer exist. | B8 | Low–Med | Phase 2.1 |
| N18 | `backend/tests/conftest.py` hard-codes default test tokens and account emails, which breaks the "secrets never in code" rule. The values were not copied anywhere. | A cross-area | Low (hygiene) | separate ticket |

---

## 5. PRD scorecard, section by section

Status: ✅ implemented, 🟡 partial, ❌ missing, ⛔ contradicts.

| PRD § | Item | Status | Note |
|---|---|---|---|
| 1 | Gate 1 market regime | 🟡 | Exists, but a stale regime is only warned about (it was 23 Oct on the 26 Oct list). |
| 1 | Gate 2 instrument selection | 🟡 | ₹10 Cr/day liquidity gate and an OI/volume proxy; no spread check. |
| 1 | Gate 3 entry setup | 🟡 | Long setups only; one-click trades ignore the trigger (N4). |
| 1 | Gate 4 risk validation | 🟡 | AI Trader only, and fails open on unknowns (N11). |
| 1 | Gate 5 execution validation | ❌ | No spread, margin, event or depth check on any entry path. |
| 2 | Indicators | 🟡 | EMA, RSI, ATR, RVOL, S/R, VIX and breadth exist. ADX and true sector RS are not in decisions; the scanner's "sector" score is stock RS against NIFTYBEES. |
| 3 | Setup score | ⛔/🟡 | Different weights; regime is a multiplier; not calibrated (0 outcome rows). |
| 4 | Entry rules | 🟡 | Breakout, pullback and momentum exist as scanner stages; breakdown is missing; one-click booking bypasses triggers. |
| 5 | Stops | 🟡 | Structural, ATR and capital-risk logic exist, but five different ATR multipliers are in use, the method is not stored, the label is wrong (N13), and costs are left out of sizing. |
| 6 | Sizing and portfolio risk | 🟡/❌ | Per-trade (AI only); total open risk ❌; correlation ❌; weekly loss ❌; gap stress ❌. |
| 7 | Exits | 🟡 | Stop, target and time exist (time unused); trailing ❌ (paper); trend ❌; no-averaging-down guard ❌. |
| 8 | Examples A–H | 🟡 | Arithmetic exact; no tests; C and D have no workflow; H is backtest-only. |
| 9 | Options checks | 🟡 | Payoff, max loss, breakeven, Greeks and expected move ✅. IV rank ❌ (no data). Bid/ask only from the user's ICICI session. No depth or legging check. The combined premium stop is display-only. |
| 10 | Lifecycle | ❌ | No state machine, no trade id across stores; partial events on strategy trades only. |
| 11 | `evaluate_trade` | 🟡 | Two engines (governor and gate) with different limits; neither runs on every path. |
| 12 | Backtesting | 🟡 | F&O and AI-Trader validation designs are good. The DSL engine lacks Sharpe/Sortino, exposure and turnover, fills gaps optimistically, and has survivorship bias (latest constituents; 4 snapshots exist). |
| 13 | MVP families | 🟡 | Families 1–3 ✅; family 4 only through regime-driven F&O; tested trailing ❌. |
| 14 | Decision card | 🟡 | The full card exists only in the Strategy Builder. Rows lack order type, stop method, R, % of portfolio, costs and an exit plan (matrix in B §8). |

---

## 6. Implementation plan

Effort: **S** ≤ 1 day, **M** 2–5 days, **L** more than a week, each including tests. Anything marked *approval* writes to
shared staging and needs your explicit OK first.

### Phase 0: make paper results honest (≈ 1–1.5 weeks)

| ID | Change | Effort | Acceptance |
|---|---|---|---|
| 0.1 | The F&O idea "Paper trade" sends a `signal` (data date, rules version, sources, evidence) and the `strategy_levels` stop/target on the underlying. The mocked e2e is replaced by a backend contract test. | S | A board idea opens a trade (201). The contract test fails if the body and the validator drift apart. |
| 0.2 | Book gross P&L and costs from `sim_entry_price` on close. | S | Probe B2 becomes a unit test: ₹600, not ₹1,000. |
| 0.3 | Send `entry_rule` per scanner stage (ACCUMULATION → `pullback_to`, EARLY_BREAKOUT → `break_above`, BREAKOUT → `at_once`). Refuse `at_once` when the entry is outside the last session's range. | S–M | Probe B3 becomes a test: FEDERALBNK at 316.89 waits or is refused. |
| 0.4 | The kill switch always runs on journal ENTRY fills; flip the test that locks the bypass in. | S | With the kill switch on, a fill returns 409 with the gate on or off. |
| 0.5 | An idempotency key on `POST /api/desk/paper-trades` (unique per user and key), plus a same-symbol refusal unless the add is explicit. | S | The same key twice gives one trade. A second HAL is refused with a reason. |
| 0.6 | The desk validator treats futures-only and short-futures structures as unbounded (refused unless the risk service allows them) and checks the exchange lot even with the gate off. | S | Probes D1 and D2 become tests that refuse. |
| 0.7 | *Approval:* install `desk-alerts.cron`. Also `record_iv_history` and `fno-forward` once 4.4 starts. | S (ops) | The morning after, every open trade's `checked_through` equals the latest bhavcopy date. |
| 0.8 | Scanner price history: read the trade date from the bhavcopy file, refuse a file whose date differs from the one requested, check against the warehouse calendar, back-fill missed sessions. *Approval:* delete the 14 phantom sessions, back-fill 21–22 Oct, recompute features. | S code + M data | Scanner sessions minus warehouse sessions = 0 rows, both ways, since 2025-10-20. |
| 0.9 | *Approval:* reconcile the paper account: reserve for the open ICICIBANK trade and post the NIFTY spread's P&L. A daily reconciliation check is added. | S | Cash + blocked equals the ledger; every open trade has a reservation. |

### Phase 1: one risk decision on every entry path (≈ 2–3 weeks)

Grow `services/risk_gate` into the single decision service and make `risk_governor.evaluate` one of its checks. Do not build
a third engine. Details are in A Q10.

| ID | Change | Effort |
|---|---|---|
| 1.1 | Move the book reader out of `routes/ai_trader.py` into a shared `risk_book`. All six entry paths call the service: desk cash, desk strategy, journal create and fill, AI signals and confirm. | M |
| 1.2 | Reserve risk atomically on `paper_accounts` with one conditional update: open risk, positions, held symbols and sector exposure. Release on close. | M |
| 1.3 | Estimated risk = gross + round-trip costs + gap stress. Add total-open-risk and weekly-loss limits; the daily loss limit includes unrealised loss, net of costs. | S–M |
| 1.4 | Fail closed on unknown inputs (drawdown, sector, liquidity, stale data), with "reduce" where the policy says so. Mark open F&O structures to market first, or every F&O holder gets blocked. | M |
| 1.5 | A per-user risk profile with an audited setter (decision D1). The AI Trader's `initial_capital` is capped at account equity. | M |
| 1.6 | Record every decision: allow, reduce and block, including validator, funding and cap refusals, with policy version and correlation id. | S |
| 1.7 | A route-inventory test that fails if any route writing a position does not call the service. Add a real-Mongo concurrency test. | S–M |

**Acceptance:** no entry can bypass the policy, and every refusal is stored with its reason. The six real staging desk entries,
replayed, are reduced or rejected as in the counterfactual (A Q9).

### Phase 2: canonical trade plan, lifecycle and exits (≈ 3–4 weeks, overlapping Phase 1)

| ID | Change | Effort |
|---|---|---|
| 2.1 | **TradePlan**: one backend object with a content-hashed `plan_id`, built by extending `strategy_plan/candidates.py`. The scanner becomes a setup source, not a second level generator; `strategy_levels` supplies the options exit plan. The object carries: entry and order type, stop with its method as data, R, targets in R, size and % of capital, costs, exit plan, evidence references, and data timestamps. One direction per instrument per day, with a conflict flag (N13). Scanner signals are versioned, not overwritten (N17). Schema in B Q8a. | L |
| 2.2 | **Lifecycle**: `plan_ref`, a `state` field and append-only transition events on `desk_paper_trades` and `ai_trader_tickets`, each written in the same conditional update that changes status. A refused open records REJECTED. The plan's `lifecycle.status` is derived from its trades. | M |
| 2.3 | **Time exits everywhere**: every screen sends `max_hold_sessions`, the AI Trader passes `max_hold_days`, and the backtest counts sessions. | S |
| 2.4 | **One shared bar-step function** for the backtest and paper trades. Within each bar, in order: gap test at the open against the previous close's stop, then intrabar touch, then trail update after the bar. The stop never loosens, ATR is as of that bar, stop history is versioned, and the exit reason `trailing_stop` is distinct from `stop`. The backtest then fills gaps at the open. | M |
| 2.5 | Trend exit (close below EMA-N, filled at the next open) as an opt-in, versioned rule. | M |
| 2.6 | Options: store the `strategy_levels` premium stop and T1/T2 on strategy trades and evaluate them on the whole structure's settle marks. | M |

**Acceptance:**
- Every transition is auditable, idempotent and linked to one id.
- For one `plan_id`, the ideas, Top 10, watchlist, Builder and paper trade carry identical levels (cross-screen contract
  test).
- PRD Example H is a golden test (1,040), and a bar with a high of 1,080 and a low of 1,035 does not exit at the raised stop.

### Phase 3: decision cards (≈ 1 week after 2.1)

Every row (Top 10 stock and F&O, watchlist cash and F&O, Builder, paper-trade detail) shows one line from the TradePlan:
`Entry ₹x (order type) · Stop ₹y (method) · Targets ₹t1 (2R) ₹t2 (3R) · Size n · Risk ₹r (p% of capital) · Est. costs ₹c ·
Horizon a–b sessions · signal age · plan id`.

Each row also gets:
- a "not tradable at this price" warning when the entry is outside the last range;
- a badge when the F&O view conflicts with the cash setup.

The paused `feat/idea-levels` branch (F&O rows showing the `strategy_levels` entry, stop and targets) can ship earlier as an
interim, but **only together with 0.1**, so the trade it records carries the same levels it displays. Otherwise fold it into
this phase.

### Phase 4: research and data validation (parallel, from 0.8)

| ID | Change | Effort |
|---|---|---|
| 4.1 | `tests/test_prd_worked_examples.py`: A–H as golden tests, plus divergence tests pinned to the PRD clause they break (cost-free sizing, gap fill at the stop, intraday refused, short cash refused). The first trailing-stop tests. | S |
| 4.2 | Scanner on adjusted prices (`prices_eod_adjusted`, or truncate at an adjustment break). | M |
| 4.3 | **One freshness rule.** One helper returns `{source, as_of, age, budget, ok}` for bars, benchmark, regime, VIX, breadth, chain, IV, quotes and event-calendar coverage. The scanner, ideas, regime-fit and the risk gate all use it. A stale required input blocks; a defaulted sub-score is recorded; the carry-forward of the benchmark close is capped. Also back-fill the 2024–25 holes in `index_eod` (Nifty 50 has 63 of about 248 sessions in 2025). | M |
| 4.4 | *Approval:* **IV-history backfill.** Dry run NIFTY/BANKNIFTY (≤ 524 docs), then stocks in groups (≤ 56,181 docs; 196 underlyings get an IV rank). Validate it, install the recorder cron, then wire IV percentile into regime-fit as an A/B against VIX. Validation queries are in C Q8b. | M |
| 4.5 | Backtest diagnostics: expectancy in ₹ and R per trade and per session, payoff ratio, Sharpe/Sortino, exposure, turnover, capital deployed, signals seen vs taken, a slippage sweep at 0/5/10/20 bps, the full cost card, optional next-open entry, and a data watermark plus code SHA on each run. | M |
| 4.6 | Point-in-time constituents: install the monthly job and import NSE's historical index files. | M–L |
| 4.7 | ADX and RS as pre-registered experiments against today's weights on 2.5 years of adjusted warehouse prices: 60/20/20 split, permutation null, net of costs. Adopt only if validation **and** test both improve. | M |

### Phase 5: expansion (after Phases 1–2 pass)

- **Bearish families** as separately gated strategies (decision D2).
- **Intraday: NO-GO today.** Staging has 0 minute bars, and migration 152 (`nidp.intraday_bars`) is not applied. Preconditions
  are in C Q8e.

---

## 7. The six decisions: recommendation

| # | Decision | Recommendation | Grounding |
|---|---|---|---|
| D1 | Capital basis for desk paper trades | One **per-user risk profile** on `paper_accounts`. The capital basis is **paper equity** (cash + net unrealised); the ₹10 lakh start stays, labelled a *simulation default*. Each limit is a separate, versioned value with an audited setter: users may tighten, only an admin may loosen. The AI Trader's `initial_capital` is capped at that equity. **NEEDS-INPUT, proposed defaults:** 1% per trade, 6% total open risk, 10% per position, 30% per sector, 3% daily loss, 6% weekly loss, 15% drawdown halt, minimum reward:risk 1.5. These are research defaults, not proven optimal values. | A Q2, Q10 |
| D2 | Bearish setups: futures shorts or puts | **Defined-risk options first** (long put, bear put spread), triggered by an instrument breakdown rather than only the market regime, which is how bearish F&O ideas are chosen today. **Stock-futures shorts second**, and only after the risk service treats futures as unbounded, with margin and gap stress. **No short-selling of cash shares.** | B §0, A R15 |
| D3 | Intraday setups now | **Defer.** There is no minute-bar data at all (0 rows), and the collector is unscheduled. | C Q6 |
| D4 | Default exits | **Labelled, versioned research defaults:** the setup's own initial stop with its method recorded; 2R/3R targets labelled as R; a time exit at the setup's maximum horizon in sessions. ATR trailing (k = 2, ATR as of the close, updated at the close and effective the next session) and the EMA20 close exit are **opt-in** rules. Neither becomes a default until the fixed backtest (2.4) has tested it. | B Q8c, C §2 |
| D5 | IV backfill and F&O gate on staging | **Approve the IV backfill now.** It is additive and idempotent, and its validation queries are written. **Enable the gate on staging for an allowlist (admin) only after Phase 0.** Do not enable it for everyone until Phase 1 replaces its notional-based cash cap with stop risk and per-user limits; turning it on as it stands does not deliver the PRD's sizing. The flag cannot enable live execution: that is a separate code constant plus an admin grant. | A Q4, Q7; C Q8b |
| D6 | Scanner score weights | **Keep them.** Fix the price history and move to adjusted prices first (0.8, 4.2), then run the pre-registered study (4.7). | C Q2 |

---

## 8. The outside review's "additional gaps", checked

| Item | Finding |
|---|---|
| Risk reservation for concurrent entries | Only cash is reserved atomically. The governor and the gate's budgets are read and then written separately → 1.2. |
| Position reconciliation | One open trade has no reservation, and one closed P&L never reached cash (N10) → 0.9 plus a daily check. |
| Data freshness | Mixed. The plan blocks stale prices, but the scanner and regime-fit hide or only warn (N14) → 4.3. |
| Corporate actions and symbol lifecycle | The warehouse is adjusted; the scanner is not (N2). Symbol changes (LTIM → LTM) are not handled in joins → 4.2. |
| Operational recovery | Exit writes are guarded by status and do not double-close. Opening a trade is not idempotent (N7). The exit cron is missing (N9). |
| Rule versioning | Partial. Scanner signals are overwritten and the engine version is a constant; backtest runs have no data watermark → 2.1, 4.5. |
| Candidate coverage | Not measured anywhere, although every scored name is stored daily → 4.5 (signals seen vs taken) and 4.7. |
| Live-readiness separation | In place today; the only barrier is the AST test. Keep paper and live certification separate. The decided live route is Kite Connect in the user's own session, behind the risk engine (`docs/AI_TRADING_BOT_PRD_GAP_ANALYSIS.md` §12). |

---

## 9. Decisions recorded (owner, 2026-10-27)

1. **Phase 0 approved.** Each fix group ships as its own PR with:
   - a problem statement and root cause;
   - data effects;
   - regression tests that reproduce the original failure;
   - before-and-after evidence;
   - staging verification and rollback steps;
   - an explicit statement that live broker execution is unchanged.

   Two items move into Phase 0 because the release gates below require them: the scanner on **adjusted prices** (was 4.2),
   and **costs in sizing and risk reporting** (part of 1.3).
2. **Staging changes are approved for preparation, not execution.** Before each data mutation, cron install or flag change,
   present the exact change for a go-ahead:
   - a snapshot;
   - the exact affected-record counts;
   - a reconciliation plan;
   - the validation queries;
   - rollback steps.

   No batch is run unreviewed. Order:
   1. snapshot;
   2. scanner history repair (only the verified copied holiday bars; 21–22 Oct from an authoritative source; recompute);
   3. paper-account reconciliation, adding compensating entries rather than overwriting, with the audit history kept;
   4. code defects;
   5. IV backfill, with its cron installed only after validation;
   6. evening exit job (schedule, holiday behaviour, duplicate-run protection, failure visibility, tested on a staging-only
      position);
   7. F&O gate for admins only after Phase 0, and for everyone only after Phase 1.
3. **Paper-risk defaults for Phase 1:**
   - 0.5% planned risk per trade;
   - 3% total open risk;
   - 10% position exposure;
   - 25% sector exposure;
   - 2% daily loss halt (from start-of-day equity);
   - 4% weekly loss halt (from start-of-week equity);
   - 10% drawdown halt (from the configured equity peak);
   - minimum reward:risk 1.5, after estimated costs where feasible.

   The engineering proposal (1/6/10/30/3/6/15/1.5) stays available as a comparison profile. Accompanying rules:
   - capital is each account's explicitly configured equity, with an audited setter and an effective date;
   - risk includes costs, slippage and a gap stress;
   - risk is reserved atomically;
   - exposure and loss-at-stop are separate limits;
   - the drawdown halt blocks new entries and does not liquidate positions unless a documented rule says so;
   - a missing, stale or invalid input rejects the entry with a reason;
   - daily and weekly resets follow the IST market calendar, and drawdown never resets daily.
4. **F&O row levels (interim, before Phase 3).** They are display-only, labelled provisional/research, with the data
   timestamp and a link to the plan. They come from the same engine the plan uses (`strategy_levels`) and add no new entry
   action. Fixing the existing F&O "Paper trade" request is fix 0.1, tested against the real backend rather than a mocked
   reply.
5. **Phase 0 release gates** (all required before Phase 0 is reported complete):
   1. no paper trade while the kill switch is on;
   2. a repeated submission creates neither a second trade nor a second reservation;
   3. realistic simulated fills for entry and exit P&L, including gaps;
   4. costs consistent across sizing, risk reporting and realised P&L;
   5. holiday sessions cannot be filled with copied prices;
   6. missing sessions and corporate actions are handled and validated;
   7. every F&O idea-to-paper-trade request is tested against the real backend;
   8. every open paper trade has a working, observable exit path;
   9. reconciliation keeps the audit trail and cannot create or destroy cash;
   10. the exit and IV-history jobs are installed, observable, retry-safe and tested.
6. **Scanner weights stay unchanged** until the corrected, pre-registered out-of-sample research says otherwise. The study
   goes in its own documentation PR, separate from the code and data changes.

### 9.1 Owner decisions on PR #355, the scanner price history (2026-10-27)

1. **Staging repair: approved as a controlled run, subject to a preflight.**
   - The snapshot is on persistent storage and verified as readable, complete and non-empty.
   - Row counts match the reviewed dry run.
   - The snapshot covers every affected table (bars, technical features, signals).
   - The apply runs in **one transaction**, and the quality check is rerun afterwards.
   - A second apply changes nothing, and a restore returns the exact prior state.
2. **Recompute only the latest date (26 Oct 2026).**
   - The 189 older scored dates are not rescored with today's macro regime.
   - Disclose that those older dates were calculated on the previously stored price basis.
3. **The scanner stays fail-closed** when the NSE calendar or the adjustment factors cannot be read.
   - Add a calendar-readiness check that validates next year's NSE Capital Market holidays before the first session that
     needs them.
   - Make the failure visible and alertable. Do not wait for 1 Jan 2027 to find out.
4. **Adjusted prices are accepted:** warehouse factors plus the residual-break guard. Report the exceptions explicitly:
   symbols scored on raw prices and symbols not scored after history truncation.
5. **The ranking change is a material release change.**
   - Record the before and after rankings and signals.
   - Publish the engine version, price basis and data-quality status with the results.
   - Keep the effect of the code change separate from the effect of the data repair.
   - Do not claim the new ranking is more predictive: that needs separate validation.
6. **PR #355 stays unmerged** until review confirms these safeguards. Code merge and data repair are separate decisions.
   No production repair and no stricter cron gate (`--require-clean`) until the staging evidence has been reviewed.
   Phase 0 stays open until the other fix groups are integrated and the release checks pass.

## 10. What was asked of the owner (now answered in §9)

1. **Approve Phase 0** (code: 0.1–0.6, 0.8 code). It will go to PRs against `dev`.
2. **Staging operations**, each with its exact effect stated before it runs:
   - (a) install the desk exit cron;
   - (b) repair the scanner price history (delete 14 phantom sessions, back-fill 21–22 Oct, recompute);
   - (c) reconcile the paper account;
   - (d) run the IV-history backfill and install its cron.
3. **The D1 numbers.** Confirm or change the proposed risk-profile defaults.
4. **The paused F&O row levels.** Ship them with 0.1 as an interim, or wait for Phase 3?
