# Pattern registry — seed: every hypothesis tested so far (2026-09-11 .. 2026-09-19)

Purpose: the multiple-testing count must start honest. Every family below was examined on the **2024-08..2026-09
bhavcopy panel**, which is therefore the DISCOVERY period — no result from it counts as validation.
The untouched validation period is **2021-01..2024-07** (Kite daily, pulled 2026-09-19, not yet read).
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
| 12 | **Gap-down ≤ −3%, open → close, no stop (G1 close-only)** | net return | **OPEN — strongest discovery result** | on Kite real gaps: **+0.8909%/session, CI [+0.5899, +1.1919], t 5.80**, positive every year, >Rs5cr +0.697% (t 3.94). Earlier +0.4735% was diluted by 11.5% phantom gaps. **5 market-wide gap days hold 36% of rows** | gapdown/PREREGISTRATION.md, PHASE1 |
| 13 | G1 pre-registered target/stop grid | net return | **UNTESTED** — run 1 invalid (look-ahead), run 2 invalid (wrong session) | correct-session refetch in progress | INTRADAY_SOURCE_EVALUATION.md Add. 5 |
| 14 | Multi-horizon move odds (opportunity board v3) | expected return | **Volatility only** | odds ≈ volatility, no expected-return edge | opportunity-board-v3 memory |
| 15 | Weekday effect (Thursday −0.364% in 2025) | daily return | **Not tested — likely noise** | flagged as a multiple-testing artefact | session record |
| 16 | Gap-up continuation over 5 days (Phase 1: −1.207% day 1, +0.457% over 5 days) | net5d | **Candidate only** | descriptive, discovery period | PHASE1_BASE_RATES.md |
| 17 | Breadth regime (weak breadth → better 5-day net) | net5d | **Candidate only, non-monotonic** | descriptive | PHASE1_BASE_RATES.md |

**Count so far: 17 families, several with multiple variants.** Any new discovery-period result should be judged
against this many looks: a single t ≈ 2 is expected by chance.
