# Pattern registry — seed: every hypothesis tested so far (2026-09-11 .. 2026-09-19)

Purpose: the multiple-testing count must start honest. Every family below was examined on the **2024-08..2026-09
bhavcopy panel**, which is therefore the DISCOVERY period — no result from it counts as validation.
Sealed data: **2021-01..2022-12 has been used twice** (H-A, H-B; 2026-09-19) and must not validate a hypothesis designed
after those results. **2023-01..2024-07 is still sealed and unread** (the final test, one use).
When the `pattern_registry` / `pattern_validation` tables are built, these become the first rows (status as below).
Every entry is judged against `SUCCESS_CRITERIA.md` (five gates, three stages).

| # | Hypothesis family | Target | Status | Evidence | Source |
|---|---|---|---|---|---|
| 1 | TPD v4 movement-probability ranking, next-open entry | net return | **FAILED** (replay: no edge) | movement ≠ direction; 8% cap set almost every stop | paper-trade-engine memory |
| 2 | Owner entry setups A–D | pre-registered backtest | **FAILED** 2026-09-17 | all four | ten-percent-days-3 plan |
| 3 | Hourly entry signal | pre-registered test | **FAILED** (shown on page by owner decision) | — | ten-percent-days-3 plan |
| 4 | v5 net-return model (walk-forward, pre-registered) | net return | **FAILED** 63 sessions; **FAILED** 511 sessions | −0.1944%/session, CI [−0.4203, +0.0315]; selection edge +0.2128pp (t 2.31) mostly beta 1.48; alpha +0.41%/session (t 4.58) | v5_net_return/FULL_HISTORY_RESULT.md |
| 5 | Overnight-entry variant | net return | **REJECTED** (artefact) | bid-ask bounce: t 18.4 in sub-Rs10L names, t 0.56 in liquid | v5_net_return/OVERNIGHT_VARIANT.md |
| 6 | Single-feature lifts (circuit lock, new 20-day high, pivot breakout, Fibonacci zone, …) | P(+5%) vs net | **Movement only** | e.g. circuit lock 6.9× lift / −0.89% net; 20-day high 4.1× / −0.80%; pivot breakout 2.5× / −0.54% | FEATURE_STUDY_FINDINGS.md |
| 7 | Resistance headroom caps moves | P(+5%) | **REVERSED** (my misreading) | above-resistance performed best (62.5% vs 57.3%) | session record |
| 8 | Fixed stops −1/−2/−3% and target/stop combos on model picks | net return | **FAILED** | losses gap through; every variant negative | session record |
| 9 | Inverse-ATR (risk-parity) sizing, ATR ≥ 5% cohort | net return | **FAILED** | −0.5627% → −0.5508%/session | session record |
| 10 | Skip gap-ups > +2% / +3% | net return | **Less bad, still negative** | −0.56% → −0.47% | session record |
| 11 | +3% / +5% intraday limit exit, high-ATR cohort | net return | **Less bad, still negative** | −0.465% → −0.391% | session record |
| 12 | **Gap-down ≤ −3%, open → close, no stop (G1 close-only / H-A)** | net return | **CLOSED by the owner 2026-09-19** after the SEALED TEST was found INVALID (gate 1): registered PASS (+1.328%/session) but 50.9% of P&L from unexecutable ETF opening prints; stocks only +0.543% (t 3.34), 2× costs t 1.24, > Rs 25 cr t 1.44 — recommend closing (`sealed/HA_VALIDATION_RESULT.md`) (Priority 1: +0.498%/session t 2.79; 2× costs t 0.98; top-10 sessions 58% of P&L; > Rs 25 cr t 1.66) | on Kite real gaps: **+0.8909%/session, CI [+0.5899, +1.1919], t 5.80**, positive every year, >Rs5cr +0.697% (t 3.94). Earlier +0.4735% was diluted by 11.5% phantom gaps. **5 market-wide gap days hold 36% of rows** | gapdown/PREREGISTRATION.md, PHASE1 |
| 13 | G1 pre-registered target/stop grid | net return | **ABANDONED (condition 3)** — primary passed (MODERATE +0.3349%, t 4.67) but the effect is only in Rs 50L–5cr (t 7.38), not > Rs 5cr (t 0.72) | runs 1–2 invalid; run 3 on validated real-gap bars | gapdown/G1_RESULT.md |
| 14 | Multi-horizon move odds (opportunity board v3) | expected return | **Volatility only** | odds ≈ volatility, no expected-return edge | opportunity-board-v3 memory |
| 15 | Weekday effect (Thursday −0.364% in 2025) | daily return | **Not tested — likely noise** | flagged as a multiple-testing artefact | session record |
| 16 | Gap-up continuation over 5 days (Phase 1: −1.207% day 1, +0.457% over 5 days) | net5d | **Candidate only** | descriptive, discovery period | PHASE1_BASE_RATES.md |
| 17 | Breadth regime (weak breadth → better 5-day net) | net5d | **Candidate only, non-monotonic** | descriptive | PHASE1_BASE_RATES.md |

**Count so far: 34 families (#32 closed at development; #33 dropped, #34 kept at development, 2026-09-19), several with multiple variants.** Any new discovery-period result should be judged
against this many looks: a single t ≈ 2 is expected by chance.
| 18 | Delayed stop ("give it room, it recovers") | close return | **Contradicted descriptively** | median low 2 min after open; drawdown by 10:00 < −5% → close −4.95%, > −0.5% → +3.60% | gapdown/G1_RESULT.md |
| 19 | Early-confirmation entry (G2–G5); **H-B = 09:45 confirmation (price ≥ 99.5% of open and > VWAP)** | net return from the later entry | **H-B FAILED SEALED VALIDATION 2026-09-19 (accepted after audit)** | 2021–22: −0.402%/session, CI [−0.567, −0.236], t −4.76; both years and both liquidity buckets negative; ETFs dropped −0.435%; no cap −0.412%; hold-to-close −0.616%. Confirmed signals made +2.32% open→close but −0.55% 09:45→close: the rebound is over by the confirmation | sealed/HB_VALIDATION_RESULT.md |
| 20 | Early intraday strength continuation (enter after early strength, hold to close) | net return from the later entry | **FAILED (discovery)** | 528 sessions: up ≥ +3% at 09:45 → −0.469%/session (t −10.05), every threshold/cap/liquidity variant negative in every year; the 18-Sep list was winners-only | pattern_engine/SCREENER_CHECK_2026-09-18.md |
| 21 | 52-week-high breakout with volume in an uptrend (evening signal, enter next open) | net return | **Candidate only — not tested** | suggested by the APARINDS case; one-day profile check 18 Sep: 6 of 16 (includes an ETF) vs 5.3% base — one session, hindsight | APARINDS_CASE_2026-09-18.md |
| 22 | Post-results drift (results jump + positive reaction) | net return | **Candidate only — blocked by data** | results reach `nse_financials_quarterly` a median 36 days after filing (Jun-26 quarter: 3.7% within 1 day), so no point-in-time test is possible yet | APARINDS_CASE_2026-09-18.md |
| 23 | A — Volatility expansion (ATR above own median, RVOL ≥ 1.5, compressed 10-day range, TR expansion) | L5_1/L10_1/L5_5/L10_5 + net | **CLOSED 2026-09-19 (discovery)** | no information beyond volatility (O/E 1.18 [0.94, 1.42]); net −0.278%/session (t −2.79) | | phase1/PHASE1_RESULTS.md |
| 24 | B — Breakout with confirmation (close > 20-day high [B55: 55-day], RVOL ≥ 1.5, close near high, above EMA20/50, RS20 > 0) | same | **Monitoring / feature only 2026-09-19** | movement beyond volatility: +5% O/E 1.55 [1.38, 1.72], +10% 2.27; B55 1.64 / 2.58; but net next-open −0.47% (B) / −0.50% (B55) per session, every split negative | | phase1/PHASE1_RESULTS.md |
| 25 | H-C — Gap-down recovery after the initial low (1% off the low + above VWAP, 09:20–10:25; stop at the low) | net trade | **CLOSED 2026-09-19 (discovery)** | −0.029%/session, CI [−0.239, +0.181]; fires on 90% of gap-downs (= H-A with a later entry) | | phase1/PHASE1_RESULTS.md |
| 26 | H-D — Gap-down continuation (H-B's rejected set, short at 09:45, stop +2%) | net trade | **CLOSED 2026-09-19 (discovery)** | −0.002%/session, CI [−0.270, +0.266]; 318 trades | | phase1/PHASE1_RESULTS.md |
| 27 | E1 — Pre-breakout buy-stop (close within 3% of the 55-day high, tight 10-day range; buy-stop 0.1% over the high, 3 sessions) | positional net return, RISK-POS-1 | **CLOSED 2026-09-19 (single pre-registered run, audit clean)** | net −11.03%, mean R −0.10, 83rd pct of 200 random, alpha t −1.77; every arm negative before costs, random entries under identical rules also lose | positional/PREREGISTRATION.md |
| 28 | E2 — Pullback in an uptrend (3 of 4 down closes into EMA20 ± 1 ATR on light volume; next open after the first up day) | same | **CLOSED 2026-09-19 (single pre-registered run, audit clean)** | net −13.75%, mean R −0.12, 76th pct, alpha t −1.69; every arm negative before costs, random entries under identical rules also lose | positional/PREREGISTRATION.md |
| 29 | E3 — B55 breakout with risk management (stops, breakeven/trailing, sizing) instead of a plain hold | same | **CLOSED 2026-09-19 (single pre-registered run, audit clean)** | net −14.40%, mean R −0.11, 56th pct, alpha t −2.56; every arm negative before costs, random entries under identical rules also lose | positional/PREREGISTRATION.md |
| 30 | C — close-entry variants of E2/E3 (15:15 snapshot, filled at the official close; 469 names with 5-minute bars) | same | **CLOSED 2026-09-19 (single pre-registered run, audit clean)** | C-E2 net −12.29% (77.5th pct); C-E3 net −14.86% (8th pct); every arm negative before costs, random entries under identical rules also lose | positional/PREREGISTRATION.md |
| 31 | D1 — Results-reaction drift (reaction session +4% vs Nifty 500 on 2x volume; next open) — first direction arm; uses R-NSE-RES-1 | same | **CLOSED 2026-09-19 (single pre-registered run, audit clean)** | net −7.98%, mean R −0.09, 52.5th pct; stops worsened it (−2.84% without); every arm negative before costs, random entries under identical rules also lose | positional/PREREGISTRATION.md |
| 32 | Trade-outcome model (roadmap v2 P2–P3): HistGradientBoosting on 44 v4 price/volume features, label +5%/−2%/5 sessions, top-5 daily vs random / momentum / movement-only | net expectancy on the locked test 2023-01..2024-07 | **CLOSED 2026-09-19 at development** (owner decision B): development walk-forward fails every criterion (M8 −0.68%/trade [−0.89, −0.46], below random); locked test not spent, block still sealed | 2021-22 dev only | model_v5/PREREGISTRATION_P2_P3.md, model_v5/DEV_RESULTS.md |
| 33 | Phase 4 group A: market regime (16 features: NIFTY 500 trend/vol/ADX/gap, INDIA VIX, breadth, size rotation) added to the H#32 baseline | keep/drop on 2021-22 development (K1 Holm AUC gain, K2 trading not worse, K3 fold stability) | **DROPPED 2026-09-19** (K1 ✗ p 0.028/0.427, K3 ✗ Q2 −0.029); note largest trading gain +0.40%/trade [+0.20, +0.61] — re-test only via new pre-reg | 2021-22 dev only | model_v5/PREREGISTRATION_P4_AB.md, model_v5/P4_AB_RESULTS.md |
| 34 | Phase 4 group B: sector-relative strength + stock-relative momentum (14 features) added to the H#32 baseline | same | **KEPT 2026-09-19** (tbs_5_2 PR-AUC +0.0075 [+0.0015, +0.0134], Holm p 0.0055; trading +0.19%/trade; all folds stable); still −0.49%/trade, not a sealed-test candidate | 2021-22 dev only | model_v5/PREREGISTRATION_P4_AB.md, model_v5/P4_AB_RESULTS.md |
| 35 | Event direction from `event_category` (11 categories, cross-sectional abnormal return vs size decile) | direction | **CLOSED 2026-09-25 — ARTEFACT.** Benchmark choice flipped every sign: decile MEDIAN → all 11 positive; decile MEAN → all 11 negative, both t > 6. Placebo on RANDOM dates reached t 10.8 where the null is ~0. Only real-minus-placebo was stable, and it showed no direction. | 92,644 events, 2,657 stocks | app-28, event_direction/RESULT.md |
| 36 | Order filings after the close reprice at the next open | direction / tradeability | **CLOSED 2026-09-25 — REAL BUT UNTRADEABLE.** +1.28%, t 7.8, entirely inside the open gap. | as above | app-28 |
| 37 | Run-up followed by positive news | direction | **CLOSED 2026-09-25 — REVERSED.** −1.07% over 5 sessions; the label is informative with the sign inverted. | as above | app-28 |
| 38 | Cleaning the sentiment label (50% of "negative" filings were resignations) improves direction | direction | **CLOSED 2026-09-25 — WORSE after cleaning.** | as above | app-28 |
| 39–41 | H#39–H#41 remainder of the event-direction series | direction | **CLOSED 2026-09-25** — no tradeable survivors across the ~410 tests in the series. | as above | app-28 |
| 42 | Chart pattern predicts DIRECTION (symmetric ±10% race, `first_exit_event` TARGET vs STOP, H=20) | direction | **CLOSED 2026-09-25 — NO DIRECTION.** 49.2% TARGET on 15,089 decided cases: a coin flip. Asymmetric targets (pct_2 77.2%) are NOT direction tests — a small target against a wider stop. | pre_sealed 2021-01..2022-12, 31,790 rows / 400 symbols | app-af, this session |

---

## Declared looks that are NOT hypothesis tests (but still count as looks)

Design inputs. Recorded because the multiple-testing count must include every look at the data, not
only the ones dressed as hypotheses.

| # | Look | Result | Date |
|---|---|---|---|
| L1 | ATR-only baseline for P(+5%/+10%/−5%) at H=20 — establishes the bar any model must clear | AUC 0.586 / 0.610 / 0.599. Base rates 72.0% / 48.6% / 61.6%. Decile lift 1.52× | 2026-09-25 |
| L2 | Base-rate check on the `up_5` label itself | **Label demoted.** 72% touch +5% AND 62% touch −5% in the same 20 sessions — most rows hit both, so the label barely discriminates. Primary label replaced by the race. | 2026-09-25 |
| L3 | P(TARGET\|decided) by pattern_type at pct_10 | RECTANGLE 50.1% (n 9,839) · SUPPORT_RESISTANCE 45.5% (n 4,726) · **HH_HL 66.8% (n 524)** | 2026-09-25 |

**L3 carries an open flag, not a finding.** HH_HL at 66.8% is z ≈ 7.7 and clears both the ~41-family
Bonferroni bar (|t| ≥ 3.3) and a correction over the 24 cells displayed in that single look
(|z| ≥ 2.81). It is still only the largest number on a screen of 24, on the smallest n of the three
families. **It must not be claimed until it survives an out-of-sample look.** Recorded here so that
if it is ever tested, the fact that it was found by scanning is on the record.

---

## Ownership and counting rules (app-af, 2026-09-25, by owner assignment)

1. **This file on `dev` is canonical.** Seven identical copies previously existed in worktrees and
   none on `dev`; they under-counted by 7 families (H#35–H#41 absent). Worktree copies are stale by
   definition.
2. **The count is 42 families + 3 declared looks.** Bonferroni over 42 → two-sided α = 0.05/42 →
   **|t| ≳ 3.3** for a discovery claim, rising with every entry added.
3. **Every DISPLAYED correlation is a look**, including product UI cells and anything never written
   up. Under the independent-signals design the look count is driven by what we display, not by what
   we formally test. A ledger that counts only written-up hypotheses looks rigorous and is not.
4. **Real-minus-placebo on the same symbols, always.** H#35 is the standing argument: two defensible
   estimators produced opposite signs with t > 6 each, and a random-date placebo reached t 10.8.
5. **The arbiter is the one-shot holdout, not the correction.** Chart-only signals use the sealed
   block 2023-01-01..2024-07-31. Event-conditioned signals cannot use it — the only event data
   inside is 28,168 rows at 0% classified — and need a forward-only pre-registered holdout instead.
6. app-28 appends event-side entries; app-af maintains the file and the count.
