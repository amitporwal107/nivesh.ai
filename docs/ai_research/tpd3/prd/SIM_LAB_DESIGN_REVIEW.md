# Simulation Lab design review (2026-09-19)

**Reviewed:** "Simulation Lab (standalone).html", the owner's Nivesh V5 design, received inline on 2026-09-19 (not in the repo).

**Reviewed against:**
- the framework PRD, `Consecutive_Session_Simulation_Diagnostic_PRD_v1.0.md` (DRAFT);
- the risk engine code (`tpd_model/risk/`);
- the frozen H#32 development files.

**Verdict:** the layout covers every PRD output and can be built. The sample numbers must not survive into the built page:
- several of them contradict the frozen cost model and each other;
- three panels ask for data we don't have for 2022.

What follows is what the built Lab does differently, and why.

## Layout

Keep all nine tabs, the theme toggle and the session picker. Each tab is populated from the ledgers in `research/sim_diag/`, never from literals.

| Tab | What the built Lab shows |
|---|---|
| Run · frozen inputs | Filled from real data |
| Data quality | Filled from real data |
| Candidate ledger | Filled from real data |
| Trade audit · RC-1 | Filled from real data |
| Reconciliation | Filled from real data |
| Deliverables | Filled from real data |
| Matrix A–H · scorecard | Placeholder: "not run — the matrix pre-registration (D5) is not frozen". The scorecard's data and signal sections can be filled from configuration A |
| Run comparison | Same placeholder as the Matrix tab |
| Permutations | Same placeholder as the Matrix tab |

## Findings

### Numbers and costs

**1. The sample P&L is internally inconsistent.**
- Run A: gross −₹1,81,000 and costs −₹3,20,000, but net −₹8,21,000.
- The cost panel for the same run ends at −₹5,01,000.
- "−16.4%" is quoted against ₹5,00,000.

For comparison, the real configuration A (1,206 trades of ₹50,000) is:
- gross ≈ −0.15% × 1,206 × ₹50,000 ≈ −₹0.9 lakh;
- net ≈ −0.68% ≈ −₹4.1 lakh;
- costs and slippage ≈ ₹3.2 lakh.

**2. A return "% on ₹5,00,000" is wrong for the fixed-notional runs (A, B, C, E, G, H).**
- In those runs, up to 18 trades of ₹50,000 are open at once in 2022, so ₹9 lakh is needed.
- 286 of the 1,206 trades (23.7%) overlap an open trade in the same symbol.

**Built:** those runs show per-trade % and ₹ totals only. Portfolio % appears only for the risk-engine runs (D, F).

**3. The cost panel contradicts the frozen cost model `zerodha-equity-v1`.**

| Item | Design | Frozen model |
|---|---|---|
| Delivery brokerage | "₹20 or 0.03%" = −₹48,240 | ₹0 |
| NSE transaction charge | 0.00325% | 0.00307% |
| DP charge | ₹15.93 | ₹15.34 |

**Built:** the Lab reads every rate and every ₹ figure from the per-fill cost ledger. Nothing is typed in.

**4. Tax: an owner decision is needed.**
- The design applies STCG at 15%. That was the 2022 rate.
- Since 23 Jul 2024 the rate is 20%, plus 4% cess and any surcharge.
- The cost model is the 2026 schedule applied retroactively. Pairing it with 2022 tax mixes two dates.
- Every run so far is a net loss, so STCG is ₹0 either way. Only the loss carried forward changes.

**Built:** a separate "after tax" line, labelled with the regime used. Pre-tax net stays the headline.

### Data the design shows that we don't have

**5. The session list is wrong.**
- The design omits 2022-10-25 and adds 2022-11-02.
- The real 20 decision sessions (NIFTY 500 calendar, `index_dev.csv`) run 2022-10-03 to 2022-11-01, including the 2022-10-24 Muhurat session.

**Built:** the list is loaded, not typed.

**6. Stock detail and correlation panels.**

| Panel | Problem | Built |
|---|---|---|
| Fundamentals (P/E, ROE, promoter holding) | Point-in-time values for 2022 are **not available**. Trendlyne has no as-of query and shows the latest revised figures (PIT audit, 0aebc4c6). NIDP fundamentals are excluded until fixed. Trendlyne data is also internal-only. | Hidden |
| Events and news (results, broker target cuts) | The announcement corpus starts in 2026 and the NSE results archive in Oct 2024. | Hidden |
| Technicals | The 44 frozen features at D are available. | Shown |
| Pairwise correlation heatmap (60-day returns of the day's picks) | Computable from bars | Shown |
| Indicator ↔ outcome correlations | Using them to choose features would reuse the 2022 data that produced the loss (double use). | Shown only as a labelled descriptive panel. Any idea it suggests needs a new pre-registration and data not yet used. |

**7. Permutations.**
- The design's grid is 2 × 2 × 5 × 5 × 13 = **1,300 configurations**.
- Running and ranking them all on 2022 is a forking-paths search. The best of 1,300 will look good by chance.
- 240 of them are invalid: stop "NONE" with engine sizing. Risk-based sizing needs a stop distance.
- OPEN_WITH_SLIPPAGE equals NEXT_OPEN whenever costs are on, because slippage is already part of the cost model.

**Built:** placeholder. The permutation tab needs:
- a trials ledger (every configuration run is recorded, winners and losers);
- a multiple-comparison adjustment;
- the owner's approval of the grid.

The mandatory matrix A–H is the pre-registered subset.

### Ledgers and reconciliation

**8. The candidate ledger's status is per configuration.**
- A candidate can be NOT_SELECTED in one configuration and SELECTED in another. For example, a sector cap exists in F but not in A.
- The sample shows CANBK as NOT_SELECTED and traded at the same time.

**Built:** a configuration selector. Status and reason are shown for the selected configuration.

**9. The reconciliation sample.**
- It says "2 open mismatches" but lists 3.
- Its "engine GAP_THROUGH_STOP vs labels STOP" row is not a mismatch. `labels.py` already exits a gap-through at the open and calls it STOP.

**Built:** comparison is by outcome and exit level:
- a STOP exit at the bar's open is a gap-through;
- a STOP exit at the stop level is a normal stop.

**10. Scorecard letter grades (A / D / B) have no pre-defined rubric.**
- A grade picked after seeing the results is a judgement presented as a measurement.

**Built:** metrics only, per PRD §13. Grades would need a rubric frozen with the matrix pre-registration.

**11. The data-quality tab mixes flags with exclusions.**

**Built:** they are kept apart, per PRD §8:
- **FAIL** = integrity, duplicate or feature-cutoff violations;
- **PASS-with-flag** = corporate action, circuit, special session;
- **Excluded** = each exclusion with its reason and its effect on the picks.

**12. Duplicate bars must be counted from a raw read.** The shared loader `dataset.load_bars` drops duplicate (symbol, date) rows silently. A duplicate check run after it always reports zero.

**13. Differences the reconciliation must classify, not hide under a tolerance.**

| Difference | Cause |
|---|---|
| Paisa rounding | The engine rounds fills to the paisa; `labels.py` does not. Net return then differs by about 1e-5, above the PRD's 1e-6 tolerance. |
| Lower-circuit-locked exits | The engine cannot sell a bar locked at the lower circuit; the labels exit at its open. |
| Slippage basis | H#32 uses the decision day's 20-day traded value; the engine uses the fill day's. |
| Quantity boundaries | The share count is computed from the rounded vs the unrounded fill price. |
| Exact vs tolerant comparisons | Decimal exact vs float with a 1e-9 tolerance. |

Each is identified by a test that recomputes the trade without that one difference and checks that the trades then agree.

## Built in this step, and not

**Built in this step:**
- D1 ledgers and the data-quality module;
- D2 additions to `execution.py`: target exit, same-bar ambiguity flag, limit and typical-price entries;
- the trade-isolated simulator;
- D3 reconciliation on all 2022 configuration-A trades;
- D4 replay of the 20 sessions with the trade audit and RC-1;
- the Lab page from those files.

**Not built in this step:**
- Target exits in the portfolio loop (`engine.py`), which configurations D and F need. They wait for D5.
- The matrix runs themselves (D5). They need the owner to freeze the matrix pre-registration: entry and stop/target parameters, G and H, and the tax regime.

**Configuration A cannot run through the portfolio loop, which holds one position per symbol.** 23.7% of H#32 trades overlap an open trade in the same symbol.

So the independent simulator runs each trade in isolation, built on the engine's own fill, stop and cost functions (`execution.py`, `costs.py`). That code is independent of `labels.py`:
- it uses Decimal with exact comparisons;
- it applies circuit rules;
- it rounds to the paisa.

This separation is what the reconciliation needs.
