# H-A sealed validation (2021-01 → 2022-12) — result

**Registered verdict: PASS. Accepted verdict: INVALID (gate 1 — trade simulation).** Half the profit came from fills at
ETF opening-auction prints that could not realistically be traded. On stocks alone the effect is weak and fails the
registered abandon condition 3 in a diagnostic reading.

Run once, 2026-09-19 05:19 IST · runner `research/sealed/run_ha_validation.py` @ `ece73957` (committed before running) ·
spec `TRACK1_SCOPE_v2.md` sha256 `46b174ca…` · cost model v1 accepted as-is by the owner · 2023+ rows dropped at load ·
result file `HA_validation_2021_2022.json` · universe conditional on the available Kite historical universe.

## Registered result (as run)
| metric | value |
|---|---|
| trades / sessions | 1,267 / 407 (of 496 sessions) |
| mean net per session | **+1.328%**, 95% NW CI [+0.938, +1.719], t 6.67; bootstrap [+0.990, +1.683] |
| 2× costs | +0.983% (t 4.95) |
| 2021 / 2022 | +1.514% (t 5.09) / +1.154% (t 4.44) |
| Rs 5–25 cr / > Rs 25 cr | +1.595% (t 6.33) / +0.568% (t 2.42) |
| top 5 / top 10 sessions' share of P&L | 14.5% / 25.0% |
| median entries per session (all sessions) | 2 (82% of sessions had entries) |
| abandon conditions 1–5 | none triggered |

## Why it is not accepted
- The best trades include ETFs: NIFTYBEES, JUNIORBEES, MON100, ITIETF, bank/gold/silver/IT ETFs.
- **NIFTYBEES 2021-04-20**: open 132.00 (−14.3% vs 154.09) and day low 132.00, then 151–156 all day, close 153.29 — while
  the **Nifty 50 opened +1.2%** (14,526.70 vs 14,359.45). A stray auction print, not an executable price.
- ETFs (Kite instrument name contains "ETF"; 368 instruments): **84 of 1,267 trades (6.6%) but 50.9% of total net P&L**;
  ETF trades averaged +9.25% gross vs +0.98% for stocks.
- The frozen universe ("EQ series") included ETFs because NSE lists them in EQ — a known trap (memory: "ETFs in EQ")
  that the spec failed to exclude. Assuming fills at those prints fails gate 1.

## Diagnostic: stocks only (post-hoc; NOT a registered test, NOT a rerun)
| | mean per session | 95% CI | t | 2× costs | 2021 / 2022 | > Rs 25 cr |
|---|---|---|---|---|---|---|
| ETF trades dropped | **+0.543%** | [+0.225, +0.861] | 3.34 | **+0.201% (t 1.24)** | +0.611% / +0.481% | **+0.319% (t 1.44)** |
| discovery 2024–26, ETFs excluded before the cap | +0.478% | — | 2.91 | +0.159% (t 0.97) | — | — |
In both periods the stock-only effect is not robust to 2× costs and is not significant in names above Rs 25 crore —
the pattern the registered abandon condition 3 was written to catch.

## Recommendation
1. **Do not spend the sealed final-test slice (2023-01 → 2024-07) on H-A.** The owner's rule: if it does not survive,
   close the family rather than rescue it by tuning.
2. **Close H-A as "failed validation (execution artefact; stock-only effect fragile)"** — owner decision.
3. **H-B (the registered primary) is still untested.** It enters at 09:45 at a traded price, so ETF opening prints cannot
   inflate it (they can only occupy cap slots). Run it exactly as registered at the next Kite login (5-minute bars for
   ≈ 3,600 signal-days in 2021–22), with the stock-only view as a labelled diagnostic.
4. **Any future spec excludes instruments whose Kite name contains "ETF"** (v3), and every sealed run gets an
   extreme-trade audit before its verdict is accepted.
