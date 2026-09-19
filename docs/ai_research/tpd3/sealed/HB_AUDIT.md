# H-B sealed run — extreme-trade audit

Registered verdict: **FAIL** · primary -0.402%/session (CI [-0.5670637839663407, -0.23634409665073114], t -4.76) · candidates 3609 · statuses {'CONFIRMED': 1680, 'NO_ENTRY_BELOW_VWAP': 942, 'NO_ENTRY_BOTH': 690, 'NO_ENTRY_DRAWDOWN': 146, 'UNRESOLVED_MISSING_BARS': 126, 'DATA_ERROR_OPEN': 25}

## 10 best trades
| date | symbol | etf | gap | O | p945 | E | exit_reason | hb_ret | hb_close_only |
|---|---|---|---|---|---|---|---|---|---|
| 2021-02-09 | ASTRAZEN | False | -3.62 | 3750.0 | 3748.0 | 3748.0 | TARGET | 3.0 | 0.01 |
| 2021-02-11 | VIKASLIFE | False | -3.39 | 2.85 | 2.95 | 2.95 | TARGET | 3.0 | 3.39 |
| 2022-12-27 | MOREPENLAB | False | -5.76 | 36.8 | 37.6 | 37.5 | TARGET | 3.0 | -1.33 |
| 2021-02-12 | ASHOKLEY | False | -6.38 | 60.9 | 62.0 | 62.0 | TARGET | 3.0 | -0.56 |
| 2022-02-28 | NATCOPHARM | False | -4.47 | 760.2 | 778.25 | 778.25 | TARGET | 3.0 | 11.73 |
| 2022-02-28 | JKLAKSHMI | False | -4.15 | 428.55 | 439.0 | 439.0 | TARGET | 3.0 | 2.23 |
| 2022-02-28 | OLECTRA | False | -4.07 | 581.0 | 592.95 | 593.0 | TARGET | 3.0 | 6.91 |
| 2022-02-15 | BANKNIFTY1 | True | -6.02 | 35.13 | 37.2 | 37.2 | TARGET | 3.0 | 3.55 |
| 2022-02-16 | STEELXIND | False | -4.06 | 21.25 | 21.7 | 21.7 | TARGET | 3.0 | 4.61 |
| 2022-02-18 | BUTTERFLY | False | -6.97 | 1092.05 | 1133.0 | 1133.0 | TARGET | 3.0 | 13.36 |

## 10 worst trades
| date | symbol | etf | gap | O | p945 | E | exit_reason | hb_ret | hb_close_only |
|---|---|---|---|---|---|---|---|---|---|
| 2021-10-19 | CANTABIL | False | -3.19 | 118.5 | 121.4 | 121.4 | STOP_GAP | -2.39 | -0.33 |
| 2021-04-12 | BECTORFOOD | False | -5.28 | 68.2 | 69.1 | 69.1 | STOP | -2.0 | 0.43 |
| 2022-01-14 | AUROPHARMA | False | -4.4 | 686.0 | 704.5 | 704.2 | STOP | -2.0 | -1.29 |
| 2022-05-30 | CHENNPETRO | False | -3.72 | 258.5 | 264.0 | 263.4 | STOP | -2.0 | -2.54 |
| 2021-04-13 | JISLJALEQS | False | -4.11 | 17.5 | 18.1 | 18.1 | STOP | -2.0 | -1.1 |
| 2022-05-13 | LLOYDSENGG | False | -4.2 | 10.04 | 10.61 | 10.61 | STOP | -2.0 | -2.07 |
| 2022-11-09 | UGARSUGAR | False | -3.92 | 77.15 | 77.75 | 77.6 | STOP | -2.0 | -0.26 |
| 2022-08-10 | DELHIVERY | False | -7.05 | 597.0 | 616.0 | 616.0 | STOP | -2.0 | -2.63 |
| 2022-01-06 | WEBELSOLAR | False | -4.73 | 14.1 | 14.8 | 14.8 | STOP | -2.0 | -4.05 |
| 2021-06-03 | PNBGILTS | True | -3.7 | 83.4 | 91.45 | 91.45 | STOP | -2.0 | -1.69 |

ETF entries: 87 of 772 (11.3%); ETF share of total net P&L: 8.5%
Implausible rows: |return| > 25%: 0; duplicate symbol-days: 0
Exit reasons: {'TIME': 317, 'STOP': 277, 'TARGET': 177, 'STOP_GAP': 1}

- registered (as run): -0.402%/session CI [-0.567, -0.236] t -4.76 · 2x costs -0.750% (t -8.87) · >Rs25cr -0.430% (t -3.39) · Rs5-25cr -0.349% (t -3.31)
- DIAGNOSTIC: ETF entries dropped: -0.435%/session CI [-0.621, -0.249] t -4.58 · 2x costs -0.777% (t -8.16) · >Rs25cr -0.402% (t -2.95) · Rs5-25cr -0.405% (t -3.50)
Executability: entries outside the daily [low, high]: 0; exits outside it: 0; daily bar missing: 0; 09:45 entry bars with zero volume: 2; missing 09:45 bar: 0

- DIAGNOSTIC 09:45 entry held to close, no stop/target (cap as registered): -0.616%/session CI [-0.855, -0.377] t -5.06
- DIAGNOSTIC all confirmed entries, NO 5-position cap: 1680 trades, 314 sessions, -0.412%/session CI [-0.573, -0.250] t -5.01
- DIAGNOSTIC all confirmed, no cap, ETFs dropped: 1587 trades, 286 sessions, -0.446%/session CI [-0.626, -0.266] t -4.84
- Confirmed signals: exit mix {'TIME': 0.418, 'STOP': 0.359, 'TARGET': 0.22, 'STOP_GAP': 0.002, 'TARGET_GAP': 0.001}; mean gross -0.041%, mean MFE +2.116%, mean MAE -1.985%
- H-A open->close (gross): confirmed +2.661% vs rejected -0.927% (n 1680 / 1778)


Section 8 (H-A vs H-B on the same signals): {"ha_signals_resolved": 3458, "confirmed_pct_of_signals": 48.582995951417004, "ha_close_only_on_rejected_signals_pct": -1.2667237770621897, "ha_close_only_on_confirmed_signals_pct": 2.317842162029524, "hb_close_only_on_entries_pct": -0.5497142808512051, "mean_mae_before_confirmation_pct": -0.7393905198593154}

**The verdict is accepted only if the best trades are real, executable prices and the result does not depend on ETFs.**
