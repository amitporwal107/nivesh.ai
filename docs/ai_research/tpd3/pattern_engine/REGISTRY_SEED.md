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

**Count so far: 26 families, several with multiple variants.** Any new discovery-period result should be judged
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

