# D7 — the two verified simulation defects, fixed and measured (2026-09-20)

**Owner decision (2026-09-20):** fix both defects found by the D3 reconciliation and rerun the frozen baseline.
**Code:** `26cbf024` (the fixes) and `21d88a00` (the reconciliation class below), run from a clean pinned checkout.
**Runs:** before `run_20260920T003043` · after `run_20260920T051346`. Same frozen inputs, same picks, same costs.

## What changed in the simulators

**1. A session is locked only when it never left the band.**
The old test — the open sitting at a circuit price — also fired on a bar that *opened* at the band and then traded
away from it, where a fill was genuinely available. The rule is now `high == low` at a band. A daily bar cannot say
*when* a stock unlocked, so a bar that traded is read as fillable at its open.

**2. A stop that could not be filled no longer keeps the old stop.**
The position is marked `must_exit` and leaves at the first price the market offers. Previously it kept its original
stop, so a position could escape a stop it had already hit.

Both changes are in `risk/execution.py`, `risk/engine.py` and `research/sim_diag/tradesim.py`, so the two independent
simulators still implement the same rule and remain a real cross-check of each other.

## The baseline, before and after

| | Trades | Net/trade | Gross/trade | Net ₹ | Win rate | Stop-hit | Liquidity exits |
|---|---|---|---|---|---|---|---|
| Before D7 | 1,206 | −0.78% | −0.25% | −4,66,282 | 27.5% | 68.2% | 7 |
| **After D7** | **1,209** | **−0.81%** | **−0.28%** | **−4,85,291** | 27.3% | 68.2% | 10 |

**Seven trades differ in total** — three that did not exist, and four that changed.

**Three picks that were wrongly skipped** (their s1 bar opened at the upper circuit and then traded, so they were
buyable). All three are losers, which is why skipping them flattered the baseline:

| Pick | Outcome now |
|---|---|
| TRIDENT 2022-04-01 | STOP_HIT, −2.43% |
| TEGA 2022-04-12 | STOP_HIT, −2.64% |
| STARHEALTH 2022-08-03 | STOP_HIT, −2.45% |

**Four trades that changed, every one for the worse:**

| Trade | Before | After | Difference |
|---|---|---|---|
| ADANIPOWER 2022-12-22 | TARGET_HIT | GAP_THROUGH_STOP | −11.80 pp |
| TTML 2022-01-28 | TARGET_HIT | LIQUIDITY_EXIT | −10.16 pp |
| SONACOMS 2022-02-10 | STOP_HIT | GAP_THROUGH_STOP | −8.02 pp |
| TRIDENT 2022-04-26 | STOP_HIT | GAP_THROUGH_STOP | −0.56 pp |

TTML 2022-01-28 is the trade D3 named: it had hit its stop during the January lower-circuit run, could not be sold,
and under the old rule kept that stop and finished **+9.4%**. It now leaves at the next open, as it would have.

RC-1 moves by two trades (WIN 332 → 330, DATA_FAILURE 61 → 66); nothing else shifts.

## The reconciliation against `labels.py`

| | Before D7 | After D7 |
|---|---|---|
| Unexplained differences | 0 | **0** |
| Simulator defects (`LOCKED_LOWER_HEURISTIC`) | 3 | **0** |
| Blocked stop then recovered | 4 | **0** |
| `labels.py` full-day-lock sales | 10 | 10 |
| `labels.py` upper-lock skips | — | 3 (new class) |
| Convention only (paisa rounding, quantity boundary) | 1,069 | 1,072 |

`labels.py` is frozen with the H#32 dataset and deliberately keeps the old lock test, so the three skipped entries
now show up as a difference on **its** side. They are classed `LOCKED_UPPER_LABELS_HEURISTIC`, and only when the s1
bar proves it traded — a full-day lock, or no bar at all, still counts as unexplained rather than being assumed away.

## Reading

Both fixes remove optimism, as D3 said they would. The baseline loss grows from **−0.78% to −0.81%** a trade
(−₹19,009 over the year). No conclusion in D4, D5 or D6 changes: every configuration still loses, and the selection
is still worse than random. The matrix results (`SIM_DIAG_D5_D6_RESULTS.md`) were produced on the pre-D7 code and are
therefore, if anything, **slightly too kind** to configuration A.

Verification: 65 risk-engine tests and 93 `sim_diag` tests pass; 5 deliberate breaks of the D7 rules and 3 of the new
reconciliation class were all caught.
