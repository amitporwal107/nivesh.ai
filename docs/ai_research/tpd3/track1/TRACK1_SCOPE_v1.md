# Track 1 — frozen scope v1: liquid gap-down, H-A (open) vs H-B (09:45 confirmation)

**Status: FROZEN** at the commit that adds this file (owner D10 approval with conditions, 2026-09-19). Any change
creates `TRACK1_SCOPE_v2.md`; results are always reported against the version they ran under.
**The sealed Track 2 test uses exactly these definitions** (section 9).

> **H-B candidate confirmation rule — operational test, not validated edge.**
> **H-A — exploratory on 2024–26 discovery data, not validated edge.**

All times are IST. A 5-minute bar is labelled by its start: the `09:40` bar covers 09:40:00–09:44:59.

## 1. Signal universe (decided from end-of-day data, no Kite dependency)
| Item | Definition |
|---|---|
| Series | **EQ only.** `BE` (trade-for-trade) cannot be squared off intraday |
| Liquidity | 20-session average traded value ≥ **Rs 5 crore**, over the 20 sessions ending on the previous session (bhavcopy) |
| Previous close `P0` | Official close of the previous session, adjusted by the corporate-action factor if an ex-date falls on the trade day |
| Watchlist | Every liquid EQ symbol, with its trigger price `P0 × 0.97` (a −3% gap), published after the previous close |

## 2. The signal (knowable at 09:15)
| Item | Definition |
|---|---|
| Open `O` | Official opening price = open of the `09:15` 5-minute bar (must equal Kite's daily open for the session; otherwise the day is a data error for that symbol) |
| Gap | `g = O / P0 − 1`. **Signal if g ≤ −3.00%** |
| Exclusion (knowable at 09:15) | Open **at a lower circuit band**: `O / P0_raw − 1` within 0.25pp of −5%, −10% or −20% (raw, unadjusted previous close, as NSE sets bands). Recorded as `EXCLUDED_AT_BAND`, never traded, still reported |
| No other filter | No model score, no ATR rule, no sector rule |

## 3. Arm H-A — enter at the open
- Entry `E_A = O + slippage` (section 6).
- Exits evaluated from the `09:15` bar onward (the entry bar's own high/low count).

## 4. Arm H-B — 09:45 confirmation (candidate rule)
| Item | Definition |
|---|---|
| Observation window | Bars `09:15` … `09:40` (six completed bars) |
| Reference price `P945` | **Close of the `09:40` bar** (the last completed bar at 09:45) |
| VWAP at 09:45 | Cumulative session VWAP over the six completed bars only: `Σ(TP_i × V_i) / Σ V_i`, `TP = (H + L + C) / 3`. **Never the full-day VWAP** |
| Confirmation | `P945 ≥ O × 0.995` **and** `P945 > VWAP945` |
| Entry `E_B` | Open of the `09:45` bar **+ slippage** |
| Not confirmed | `H-B NO_ENTRY` with reason `DRAWDOWN`, `BELOW_VWAP`, `BOTH` or `MISSING_BARS` — the H-A outcome for the same signal is still recorded (opportunity cost) |

## 5. Exits — identical rules for both arms, from the arm's **own entry price**
`STOP = E × 0.98`, `TARGET = E × 1.03`. Bars are evaluated in time order from the arm's entry bar:
1. Bar **opens** at or below `STOP` → exit at that bar's open (`STOP_GAP`, the achievable price — not the stop).
2. Bar opens at or above `TARGET` → exit at that bar's open (`TARGET_GAP`).
3. Bar touches **both** `STOP` and `TARGET` → **`STOP` at the stop price** (conservative; the favourable order is
   never assumed).
4. Bar low ≤ `STOP` → `STOP` at the stop price.
5. Bar high ≥ `TARGET` → `TARGET` at the target price.
6. Neither by the `15:25` bar → `TIME` exit at the **official closing price** (bhavcopy / Kite daily close).
7. 5-minute bars missing for the day → **`UNRESOLVED`**. Never inferred. A daily-OHLC conservative bound (both touched
   → stop) may be shown **separately** and is never mixed into the primary statistics.
**Every trade has exactly one exit reason.** A target hit is never also a close exit.

## 6. Costs (cost model v1, versioned)
| Component | Value |
|---|---|
| Charges (brokerage, STT, exchange, SEBI, stamp, GST), intraday round trip | **0.10%** — ⚠️ UNVERIFIED: to be confirmed against one of the owner's actual contract notes |
| Slippage per side, by 20-day traded value | > Rs 100 cr **0.05%** · Rs 25–100 cr **0.10%** · Rs 5–25 cr **0.15%** |
| Round-trip total | 0.20% / 0.30% / 0.40% by bucket |
| Sensitivity | Every result also at **2× costs** |

## 7. What is recorded per signal
Identity and data: date, symbol, `P0`, `O`, gap, liquidity bucket, `EXCLUDED_AT_BAND`, data-quality flags, run ID.
**H-B selection fields (owner):** opening gap · `P945` · recovery from the 09:15–09:45 low (`P945 / low − 1`) · MAE before
confirmation (`low / O − 1`) · VWAP distance (`P945 / VWAP945 − 1`) · distance from `P945` to the H-B target and stop ·
entry slippage · the H-A outcome for the same signal.
Per arm: entry time and price, exit reason, exit time and price, gross and net return, MFE, MAE.
**Owner's manual fills** (`manual_fills.csv`: time, price, quantity, arm) reconciled against the theoretical entry.

## 8. How H-A and H-B are compared (never by average return alone)
| Question | Measure |
|---|---|
| Eligibility | Number of H-A signals; **% of H-A signals that become H-B entries** |
| Conditional trade quality | H-B outcomes on the trades that qualify (from `E_B`): target/stop/time rates, net return, MFE/MAE |
| Opportunity cost | **H-A outcomes of the signals H-B rejected** (the trades confirmation skipped) |
| Delay cost | For confirmed signals: H-A return vs H-B return on the same trade |
| Pre-confirmation risk | MAE before 09:45 |

**Metric separation in every report:** operational metrics → Track 1 · historical edge evidence → Track 2 · live
economic performance → longer paper/live record. Track 1 can reveal where live conditions, friction, alert load and
missing data differ from the historical assumptions; it is never used to claim statistical confirmation of an edge
(30 sessions give a ±1.34pp CI).

## 9. Track 2 sealed test — registered with these same definitions
| Item | Registration |
|---|---|
| Data | Validation slice of the sealed period (owner D1; recommended 2021-01 → 2022-12); Kite daily + 5-minute bars for gap-down sessions (one login). Labelled **survivorship-limited** |
| Primary endpoint | **H-B**: mean per-session net return (cost model v1) over sessions with ≥ 1 H-B entry; success = mean > 0 and 95% Newey-West lower bound > 0 |
| Co-primary (reported, Bonferroni α 0.025 each) | **H-A** with the section 5 exits; H-A close-only as reference |
| Required report | Section 8 comparisons; year split; liquidity split (Rs 5–25 cr vs > Rs 25 cr); whole-market-day bootstrap; 2× costs; outlier dependence (drop 5/10 best sessions) |
| Abandon conditions | (1) primary CI includes 0; (2) 2021 and 2022 disagree in sign; (3) effect only in Rs 5–25 cr and not > Rs 25 cr; (4) median H-B entries per session < 1; (5) primary turns ≤ 0 at 2× costs |

## 10. Discovery-period reference (2024-08 → 2026-09; NOT evidence)
H-A close-only, liquid, EQ, open-at-band excluded (the section 1–2 rules): **+0.665%/session, CI [+0.310, +1.020],
t 3.67** (2,057 pairs, 437 sessions), flat 0.25% cost. H-B has not been computed on any data before this freeze.

## 11. Output (owner D11)
Per trading day, on nidp-stack-vm: `/app/research/reports/YYYY-MM-DD/` —
`daily_signal_report.html` · `signals.csv` · `outcomes.csv` · `data_quality.json` · `run_manifest.json`
(run ID, git SHA, this scope file's SHA-256, cost-model version, data snapshot IDs).
Report sections: data freshness and completeness · market-day summary · H-A signals · H-B signals · side-by-side
comparison · target/stop/timeout outcomes · unresolved intraday outcomes · manual execution notes · cost assumptions ·
run ID and code version. **No product UI** until the app-vm disk decision (D5).
