# Positional study — pre-registration (FROZEN)

**Status: FROZEN.** Approved by the owner on 2026-09-19 at 20:21 IST, "approve as drafted", including the §5 loss controls. The runner follows this document exactly. After the runner is committed there is **one** run on the discovery data, with no retuning. Nothing described here had been run, and no price data had been loaded for it, at the time of approval.

**Bound to:**

| Item | Value |
|---|---|
| RISK-POS-1 v1 hash | `2289cfcf89598c31175d247e95a1bf22bb0193eeaf881c379d494173a5cf58f0` |
| Cost model | `zerodha-equity-v1` (page sha256 `3f7b26f6…42af0`) |
| Engine | commit fcb7f6db, plus the `stops_active` flag (§6.2) added before the run |

**R-NSE-RES-1** was approved by the owner at the same time (`research/pit_audit/config/policy.json`), so arm D1 runs.

| Item | Value |
|---|---|
| Date drafted | 2026-09-19 |
| Owner decisions | memory `positional-phase2-decisions`; plan `/root/.claude/plans/cryptic-sleeping-flask.md` rev 1 |
| Engine | `backend/nidp/services/tpd_model/risk/` (commit fcb7f6db) |
| Risk config | `RISK-POS-1` v1 (hash recorded at freeze) |
| Cost model | `zerodha-equity-v1` |
| Success policy | `pattern_engine/SUCCESS_CRITERIA.md` (five gates) |
| Registry | families **#27–#31** added to `pattern_engine/REGISTRY_SEED.md` (count becomes 31) |

## 1. Question

Every earlier test bought at the next open and held with no stops, sizing or portfolio limits, and every one lost after costs. This study tests the owner's hypothesis that **early entry plus proper risk management and allocation** can turn our movement signals into a net profit over a hold of up to 5 sessions. The result is decomposed into:
- **selection skill:** the arm vs random entries under identical rules;
- **risk-management effect:** the arm with stops vs the same entries held without stops;
- **costs:** gross vs net;
- **market beta:** regression on the Nifty 500.

## 2. Data (discovery period only)

| Data | Source | Period | Notes |
|---|---|---|---|
| Daily OHLCV (split/bonus/dividend-adjusted) | Kite, `/app/research/kite_history/day_2021/` via Phase 1's `load_daily` | 2024-08-01 → 2026-09-18 | The loader drops and **asserts** that no row predates 2024-08-01. |
| 5-minute bars (arm C only) | Kite, `/app/research/kite_history/five_min_2024/` | 2024-08-01 → 2026-09-18 | Cover 469 of the 501 current Nifty 500 names; arm C tests those 469 only. |
| Results broadcast times (arm D1 only) | NSE results listings archived by the PIT audit (`/app/research/pit_audit/nse`, `filings`) | Broadcasts 2024-10-08 → 2026-08-15 | 3,857 symbol-quarters, 497 companies. |
| Nifty 500 index | Kite (`/app/research/phase1/nifty500_index_daily.csv`) | Same as daily bars | Used for the benchmark and relative strength. |
| Universe and sector | `/app/research/screener/ref/ind_nifty500list.csv` (current members; `Industry` = sector for the 20% sector cap) | — | **Survivorship bias:** current members only. |

- **Untouched:** 2023-01 → 2024-07 remains sealed (used once, later, only for an arm that passes §7). The 2021–22 data is spent (used twice) and is not read.
- **Warm-up:** indicators use discovery bars only, so the first signal can occur after 60 sessions of history (≈ 2024-10-28, as in Phase 1).

## 3. Common definitions (known at the decision time only)

- **Eligible stock on session t:**
  - at least 60 sessions of history;
  - 20-day average traded value (`value20`) ≥ ₹5 crore;
  - close ≥ ₹50;
  - a bar on t.
- **Indicators on t:** ATR14 (Wilder), EMA20, EMA50, `hi55` (highest high of the 55 sessions **before** t), 20-day relative strength (stock minus Nifty 500), and 20-day average volume (the 20 sessions before t). These are the Phase 1 panel definitions.
- **Stop clamp** (every arm): stop = min(max(structural stop, ref × 0.92), ref × 0.99), where ref = the reference entry price. The risk never exceeds 8% of the entry and is never under 1%. The engine rejects anything outside RISK-POS-1's bounds anyway.
- **Ranking** when signals exceed free capacity: 20-day relative strength, descending, then symbol ascending (deterministic).

## 4. Arms (families #27–#31)

| Arm | Signal (all conditions on session t) | Entry | Initial structural stop |
|---|---|---|---|
| **E1 — pre-breakout buy-stop** (#27) | eligible; close ≥ 0.97 × `hi55` and close < `hi55`; 10-day range in the lowest 30% of the stock's own history (Phase 1 `range10_pct` ≤ 0.30); close > EMA50; relative strength > 0 | BUY_STOP at `hi55` × 1.001, valid sessions t+1…t+3; fills at max(open, trigger) | lowest low of the 10 sessions ending t |
| **E2 — pullback in an uptrend** (#28) | eligible; close > EMA50; the 55-session high (to t) set within the last 15 sessions; ≥ 3 down closes among t−4…t−1; lowest low of t−4…t−1 within EMA20(t−1) ± 1 × ATR14; average volume of t−4…t−1 below the 20-day average; **t is the first up day** (close > previous close and close > open) | MOO at t+1 | lowest low of t−4…t − 0.5 × ATR14 |
| **E3 — 55-day breakout** (#29) | the Phase 1 B55 screen unchanged: eligible; volume ≥ 1.5 × 20-day average; close in the top 25% of the day's range; close > EMA20 and > EMA50; relative strength > 0; close > `hi55` | MOO at t+1 | reference close − 2 × ATR14 |
| **C — close-entry variants** of E2 and E3 (#30, reported as C-E2 and C-E3) | the E2 / E3 conditions evaluated on a **15:15 snapshot** of t from 5-minute bars. That day's open, high, low and last price and its volume use bars through 15:15 only. The volume test compares volume-to-15:15 with the 20-day average of volume-to-15:15. | MOC: the official close of t | as E2 / E3, from the 15:15 price |
| **D1 — results-reaction drift** (#31, direction arm) | **Reaction session r** = the first full session after a company's earliest results broadcast for a quarter (t itself if broadcast before 09:15 on a session day, else the next session). Trigger: stock return on r minus Nifty 500 return on r ≥ +4%, and volume on r ≥ 2 × its 20-day average. **The signal passes `is_feature_eligible` with rule R-NSE-RES-1** (available_at = the NSE broadcast, the conservative choice). | MOO at r+1 | reference close − 2 × ATR14 |

**D1 status:** its rule R-NSE-RES-1 was **approved** on 2026-09-19 (audit decision DEL-06, results only), so D1 runs. Filings the rule excludes (AV-1 contradictions, revisions without a broadcast time) produce no D1 signal.

## 5. Risk, sizing, exits and costs (identical for every arm and control)

| Setting | Value |
|---|---|
| Risk config | **RISK-POS-1**: fixed ₹5,00,000 capital; 0.5% risk per trade; 8 open positions (pending orders included); 20% stock cap; 20% sector cap; 80% deployment; 20% cash reserve; 5% portfolio open risk; 5% volume participation; stops 1–8% |
| Loss controls (research settings in RISK-POS-1, subject to this approval) | daily loss ≥ 2% → no new entries for 1 session; weekly loss ≥ 4% → none until next week; drawdown ≥ 8% → risk halved until the drawdown is back to 4%; drawdown ≥ 15% → kill switch (no new entries for the rest of the run) |
| Sizing cost estimate | 0.30% of the reference price per share (sizing only; actual charges come from the cost model) |
| Exits | Stops are checked from the entry bar (stop-first on the entry bar). After a close ≥ entry + 1R the stop moves to breakeven; after a close ≥ entry + 2R it trails at the highest close − 2 × ATR14 (effective next session). Gap-through fills at the open. **Time exit at the close of the 5th session** (s1 = entry session). No profit target. |
| Costs | Zerodha delivery schedule `zerodha-equity-v1`, **applied retroactively** to 2024–26: the rates retrieved 2026-09-19 are used for every date; every result carries the flag. |
| Slippage | 0.05% / 0.10% / 0.20% per side for `value20` ≥ ₹100 cr / ≥ ₹25 cr / below; the stress run uses 2× |

## 6. Controls and decomposition (reported for every arm)

1. **Random-entry control (selection skill).**
   - 200 runs with seeds 1–200.
   - Each run enters, on each session where the arm had filled entries, the same number of randomly chosen eligible stocks not already held, by the same entry mechanism. For E1 the control uses MOO on the arm's fill session.
   - Random entries get the arm's own structural-stop formula, the same exits, sizing and risk config, and the same engine.
2. **Risk-management ablation.** The arm's own entries and quantities with stops disabled (engine flag `stops_active=False`, added and tested before the run), exiting at the close of session 5. The difference shows what the stops and trailing contributed.
3. **Costs.** Gross vs net P&L, and the 2× slippage stress.
4. **Market.**
   - Daily portfolio net returns (Δequity ÷ ₹5,00,000) regressed on Nifty 500 daily returns: beta, daily alpha, Newey-West (5 lags) t.
   - A buy-the-index benchmark over the arm's holding windows.

## 7. Decision rule (applied once, no retuning)

Six tests (E1, E2, E3, C-E2, C-E3, D1), so each uses a one-sided α ≈ 0.05 ÷ 6 ≈ 0.0083. An arm is a **validation candidate** (eligible for the single sealed-data test, Jan 2023 – Jul 2024, which needs separate owner approval) only if **all** hold:

| # | Criterion |
|---|---|
| 1 | Total net return after costs > 0, with the Newey-West t of mean daily net return ≥ 2.4 |
| 2 | Mean net R per trade **above every one of the 200 random-entry runs** (p ≤ 1/201) |
| 3 | Beta-adjusted daily alpha with a Newey-West t ≥ 2.4 |
| 4 | Net return > 0 in both halves of the period (split at the median session) |
| 5 | Net return > 0 at 2× slippage |
| 6 | At least 100 closed trades |

- **Selection skill but no profit:** an arm meeting criterion 2 but failing 1 or 5 is kept as **monitoring / feature only**.
- **Otherwise:** the arm is **CLOSED**.
- **No sealed test before review:** before any verdict, the 10 best and 10 worst trades of each arm are audited against the raw bars (the owner's rule after H-A). A data artefact voids the arm's result, which is reported as INVALID, not re-run with fixes.

## 8. Reporting (`positional/RESULTS.md` + JSON)

- **Per arm:** everything in PRD §15.4 (net return after costs, maximum drawdown, Sharpe, profit factor, win rate, average win and loss, largest loss, longest losing streak, turnover, transaction costs, exposure utilisation).
- **Also per arm:** R-multiple expectancy, gap-through-stop frequency, binding-constraint counts, rejected signals by reason, risk-state events, and the retroactive-cost flag.
- **Decomposition (§6):** a table per arm.
- **Survivorship and data coverage:** stated with every table.

## 9. What is fixed before the run (so nothing is chosen after seeing results)

All thresholds in §3–§7, the seeds, the config and cost-model versions, and the metric definitions.

Code that is written after this document is approved, but before the run:
- the signal builder;
- the 15:15 snapshot;
- the D1 reaction mapping;
- the random-entry control;
- the `stops_active` flag.

It must carry leakage tests:
- a signal at t uses bars ≤ t, or ≤ 15:15 on t for C;
- D1 uses no broadcast after its decision time;
- the sealed-period assert fires on a pre-2024-08-01 row.
