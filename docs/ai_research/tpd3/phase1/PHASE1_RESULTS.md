# Phase 1 screeners — results (discovery period, run once)

Pre-registration `PHASE1_PREREGISTRATION.md` (frozen at 6818f078); evaluation code committed before the run (7cc924a3);
run 2026-09-19 10:30–10:36 IST. Data: Kite daily (498 current Nifty 500 members, 2024-08-01 → 2026-09-18, 469
sessions; first eligible signal 2024-10-28) and Kite 5-minute bars. Nothing before 2024-08-01 was read. Results files:
`/app/research/phase1/phase1_{daily,intraday}_results.json`, per-signal CSVs alongside.

**Verdict: no screener has an economic edge. Breakouts (B, B55) carry real movement information beyond volatility and
are kept as monitoring / feature screeners; A, H-C and H-D are closed.**

## Base rates (eligible stock-days)
+5% next-day high touch 5.31% · +10% 0.61% · +5% within 5 sessions 28.1% · +10% within 5 sessions 7.5% · −5% next-day
low touch 3.44%.

## Daily screeners — movement information beyond a volatility-only baseline (O/E, 95% session-bootstrap CI)
| Screener | signals (sessions) | +5% next day | +10% next day | +5% in 5 days | +10% in 5 days | −5% next day |
|---|---|---|---|---|---|---|
| A volatility expansion | 1,023 (332) | 10.4%, O/E 1.18 [0.94, 1.42] | 0.97 [0.46, 1.58] | 0.95 [0.84, 1.08] | 1.02 [0.79, 1.27] | 1.01 [0.73, 1.35] |
| B 20-day breakout | 3,425 (442) | 9.9%, **O/E 1.55 [1.38, 1.72]** | **2.27 [1.72, 2.87]** | 1.06 [0.99, 1.12] | **1.24 [1.09, 1.37]** | 0.90 [0.75, 1.07] |
| B55 55-day breakout | 2,108 (413) | 10.4%, **O/E 1.64 [1.42, 1.87]** | **2.58 [1.76, 3.44]** | **1.09 [1.02, 1.17]** | **1.32 [1.16, 1.50]** | 0.93 [0.75, 1.12] |
Raw hit rates of A look high (10.4% vs 5.3%) only because A picks volatile stocks; against the volatility baseline
it adds nothing. Breakouts raise the upside-touch odds without raising the downside-touch odds.

## Daily screeners — economics (buy the next open; net of cost model v1; per session, equal weight)
| Screener | net 1-day | NW 95% CI | 2× costs | net 5-day | halves | liquidity buckets | regimes |
|---|---|---|---|---|---|---|---|
| A | −0.278% (t −2.79) | [−0.473, −0.082] | −0.546% | −0.556% (t −1.71) | both < 0 | all < 0 | up −0.54%, down +0.01% |
| B | −0.466% (t −4.97) | [−0.650, −0.282] | −0.720% | −0.810% (t −3.40) | both < 0 | all < 0 | both < 0 |
| B55 | −0.499% (t −5.38) | [−0.680, −0.317] | −0.744% | −0.618% (t −2.62) | both < 0 | all < 0 | both < 0 |
MFE / MAE from the next open are symmetric (about +2.0% / −2.0%): the extra movement does not arrive in a tradable
direction for an open entry. Capacity: B median 6.5 signals per session (max 36), B55 4 (max 25), A 2 (max 33).

## Intraday gap-down screeners (5-minute bars; 2,243 gap-down candidates, 2,138 with certified bars)
| Screener | trades | net per session | NW 95% CI | 2× costs | exits | MFE / MAE |
|---|---|---|---|---|---|---|
| H-C recovery after the low (long) | 1,915 (90% of candidates) | −0.029% (t −0.27) | [−0.239, +0.181] | −0.291% | time 76%, stop 24% | +2.35% / −1.80% |
| H-D continuation (short) | 318 (15%) | −0.002% (t −0.01) | [−0.270, +0.266] | −0.253% | time 62%, stop 38% | +2.05% / −2.25% |
H-C fires on almost every gap-down, so it is H-A with a later entry — and, as with H-B, the later entry leaves nothing.

## Decisions under the pre-registered rules
| Family | Movement info | Economic | Status |
|---|---|---|---|
| #23 A | fails (CI includes 1) | fails | **CLOSED** |
| #24 B | passes (O/E 1.55; +10% 2.27) | fails | **Monitoring / feature screener** |
| #24 B55 | passes (O/E 1.64; +10% 2.58) | fails | **Monitoring / feature screener** |
| #25 H-C | n/a | CI includes 0 | **CLOSED** |
| #26 H-D | n/a | CI includes 0 | **CLOSED** |

Clarification recorded, not a change: the baseline needs a month of prior labels, so O/E starts with December 2024
signals; the economic results use every signal from 2024-10-28. Top-5/10 session shares are undefined because total
P&L is negative. Survivorship: current Nifty 500 members only.

## Next step (needs its own pre-registration before running)
The owner's key question is incremental value over **the existing model**. A replay of v4-early exists for 165 sessions
(2025-01-01 → 2025-08-29, discovery period). Proposed Phase 1b: within v4-early probability deciles, compare the
+5% / +10% hit rates of breakout-flagged (B, B55) versus unflagged stocks (stratified test), and test whether adding the
flag to a time-ordered recalibration of v4-early lowers the Brier score out of sample.
