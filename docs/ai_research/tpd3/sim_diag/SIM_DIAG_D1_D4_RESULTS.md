# Simulation framework — D1–D4 results (2026-09-20)

**Run:**
- Run: `run_20260920T003043` (data in `/app/research/sim_diag/`, not in git; manifest with sha256 in the run folder).
- Code: `e0b9a557` (branch `feat/paper-trade-engine`).
- PRD: `prd/Consecutive_Session_Simulation_Diagnostic_PRD_v1.0.md` (DRAFT).
- Scope: configuration A only — the frozen H#32 rule. No matrix run (D5) and no parameter from PRD §10–§11 was used.

**Development data only:** bars ≤ 2022-12-30, through the guarded loader. The sealed 2023–24 block was not read.

**Inputs, verified by sha256 before use:**

| Input | sha256 (prefix) |
|---|---|
| dataset | `7bb77e5a…` |
| out-of-fold predictions | `8763f064…` |
| M8 picks | `d05cccc2…` |
| isotonic calibration | `1f1b22c5…` |

**Consistency checks:**
- Bars re-read from the raw Kite files reproduce the dataset's close, value20 and s1 open on all 198,945 rows.
- The ranking rebuilt from the frozen predictions reproduces all 1,210 picks exactly.

## Run attempts (all kept)

| Attempt | Outcome | Cause and fix |
|---|---|---|
| 1 | Stopped at the pick-reproduction check | pandas' default CSV float parser read 455 tie-break values one ulp off (1.1e-16). Fixed by exact (`round_trip`) parsing (2f5ad3f9). |
| 2 | Crashed in the data-quality report (after the reconciliation) | `DataFrame.isin` / `DataFrame.flags` were used instead of the columns. Fixed and tested (e0b9a557). |
| 3 | Complete | Its reconciliation (below) also led to two diagnostic-layer changes (e0b9a557):<br>• locked positions are held until they can be sold;<br>• lower-circuit mismatches are split by cause. |

## D3 — configuration A vs `labels.py`, all 2022 trades

| | 2022 | Replay window |
|---|---|---|
| Picks / entry status agrees | 1,210 / 1,210 | 100 / 100 |
| Trades compared | 1,206 | 100 |
| Outcome · exit date · exit level (₹0.01) agree | 1,197 · 1,193 · 1,193 | 100 · 100 · 100 |
| Net within 1e-6 as simulated (fills rounded to the paisa) | 124 | 7 |
| Net within 1e-6 on the unrounded path | 1,193 | 100 (max diff 2e-16) |
| **Unexplained** | **0** | **0** |

Every difference is explained by a recomputation that removes one known cause:

| Class | Trades | Side at fault | What it is |
|---|---|---|---|
| NET_PAISA_ROUNDING | 1,059 | convention | The simulator rounds fills to the paisa; `labels.py` does not |
| NET_QTY_BOUNDARY | 10 | convention | The same, and the share count differs |
| LOCKED_LOWER_FULL_DAY | 10 | **`labels.py`** | Every blocked bar was locked all day (high = low). `labels.py` "sold" at a price where nothing traded |
| LOCKED_LOWER_HEURISTIC | 3 | **simulator** | The lock test in `execution.py` (open = low at a band) fired on bars that then traded away from the open (SONACOMS 2022-02-14, TRIDENT 2022-05-02, ADANIPOWER 2022-12-26) |

**Three defects found. None is fixed in the engine; changing engine behaviour needs owner approval (D7).**

**1. `labels.py` cannot model a lower-circuit lock.**
- M8 picked TTML on 10 consecutive decision days (14–28 Jan 2022) while it fell through daily −5% lower circuits.
- `labels.py` books each trade at −5.4%.
- Held until sellable, the losses were −37%, −34%, −31%, −27%, −23%, −19%, −15%, −10% and −6%, and one +9% (see defect 3).
- Across all trades this lowers mean net per trade from **−0.68%** (labels) to **−0.78%** (simulator).
- **The H#32 conclusion is unchanged, and the true loss is larger.**

**2. The circuit-lock test gives false positives, in both directions.**
- "Open equals the low (or high) at a band" also fires when the stock opens at the band and then trades away from it.
- Lower side: 3 trades where the simulator refused a sale at the open that was possible. Here the simulator is too optimistic, by up to 12 points on ADANIPOWER.
- Upper side: 3 of the 4 picks the H#32 dataset skipped as "locked upper at the open" were buyable (TRIDENT 2022-04-04, TEGA 2022-04-13, STARHEALTH 2022-08-04). Only TTML 2022-02-02 was locked all day.
- Both `labels.py` and the engine use this test.

**3. After a blocked stop, the engine keeps the old stop instead of selling at the next sellable open.**
- 4 trades escaped a blocked stop this way. For example, TTML 28 Jan ends +9.4% instead of a loss.
- This is optimistic, and `engine.py` behaves the same way (EXIT_BLOCKED, then the same stop the next day).

**Proposed fixes, for owner approval:**
- Treat a bar as locked only if high = low. A bar that opens at a band and then trades is fillable at the open.
- After a blocked stop, sell at the next bar's open.
- Then rerun D3 and record before/after (D7).

## D1 — data quality (242 decision sessions of 2022)

- **No session fails.**
  - 0 raw duplicate bars, 0 off-calendar bars.
  - One instrument per symbol; every symbol has an ISIN.
  - 0 invalid OHLC bars.
- **Every session is PASS_WITH_FLAGS.** The flags are review prompts on the universe (895 corporate-action heuristics over the year, plus circuit locks), not exclusions.
- **Feature cutoff (future-shock test):**
  - the 44 features of every symbol were recomputed from bars cut at D on 32 dates (the 20 replay sessions plus 12 seeded dates);
  - **0 violations**: no bar after D entered a stored feature.
- **Missing bars:** 71 symbol-days in the year; 0 in the replay window.
- **2022-10-24 (Diwali Muhurat)** is flagged, including on the 14 trades whose windows use it.
- **Flags on trade bars:**

  | Flag | Count |
  |---|---|
  | volume spike | 34 |
  | locked open down | 29 |
  | locked open up | 27 |
  | locked close up | 24 |
  | locked close down | 22 |
  | Muhurat | 14 |

## D4 — 20-session replay (2022-10-03 → 2022-11-01)

**Trades:** 100 trades from 40 symbols (21 of them overlap an open trade in the same symbol).
- All 100 match the label reference.
- All 100 pass the third check, a plain re-derivation from the raw bars.
- Over all of 2022 that check fails for exactly the 13 locked-lower trades, as expected.

**P&L:**

| | Total | Per trade |
|---|---|---|
| Gross | −₹9,846 | −0.20% |
| Slippage | ₹15,739 | |
| Charges | ₹12,595 | |
| **Net** | **−₹38,179** | −0.77% |

**Capital:** up to 14 trades open at once, needing ₹6.98 lakh.

**RC-1 primary cause (100 trades):**

| Cause | Trades |
|---|---|
| STOP_FAILURE | 51 |
| WIN | 27 |
| DATA_FAILURE (unreviewed flags, mainly Muhurat) | 13 |
| VOLATILITY_TRAP | 6 |
| TARGET_FAILURE | 1 |
| ENTRY_FAILURE | 1 |
| UNCLASSIFIED | 1 |

## What the verified simulation says about the loss (configuration A, 2022, 1,206 trades; descriptive)

**Money:**

| | Total | Per trade |
|---|---|---|
| Gross | −₹1,51,235 | −0.25% |
| Slippage | ₹1,63,367 | |
| Charges | ₹1,51,680 | |
| Costs (slippage + charges) | | 0.52% |
| **Net** | **−₹4,66,282** | −0.78% |

- Costs are about 2× the size of the gross loss.
- The fixed-notional run needed up to ₹8.98 lakh at once (18 trades). A "% of ₹5 lakh" figure would be wrong for it.

**Stops:**
- The −2% stop is **0.45 ATR** (median) for the stocks M8 picks. Every trade's stop is inside one ATR.
- 68% of trades are stopped, 40.5% of them on the entry day.
- 196 of the 823 stopped trades later reached +5% within the 5 sessions.

**Signal (Mode A, no execution rules, from the s1 open):**

| Group | Mean 5-session return | Up after 5 sessions |
|---|---|---|
| Top 5 | 0.00% | 47.1% |
| Ranks 6–10 | +0.53% | — |
| Ranks 11–20 | +0.05% | — |
| All eligible | −0.05% | — |

- **Against random picks:** random 5-a-day selections (200 seeds) average −0.04%. The top 5 sit at the 63rd percentile of that distribution, so they are indistinguishable from random.
- **The M8 score is mostly a volatility ranking:**
  - its mean daily Spearman correlation with ATR is 0.71;
  - the picks sit in ATR decile 8.3 on average;
  - against same-day stocks of the same ATR decile, the picks do −0.10%, and beat them 46.6% of the time.
- The ranks 6–10 figure is descriptive. Using it to choose a rule would reuse 2022 data (double use).

**Where the loss comes from, by RC-1 primary cause (2022):**

| Cause | Trades | Net |
|---|---|---|
| STOP_FAILURE | 555 | −₹6.96 lakh |
| VOLATILITY_TRAP | 172 | −₹2.15 lakh |
| DATA_FAILURE (unreviewed flags, including 9 of the 10 TTML lock trades; the tenth ends as a win) | 61 | −₹1.63 lakh |
| ENTRY_FAILURE (chased gap > 2%) | 36 | −₹0.44 lakh |
| WIN | 332 | +₹6.94 lakh |

The rest of the causes are small.

**Reading:**
- The loss is not a simulation artefact. The two simulators agree, and where they differ, the true loss is larger.
- The picks show no directional edge beyond their volatility.
- The fixed 2% stop sits inside normal daily noise for those picks.
- Costs then turn a near-zero gross into a clear loss.

These are descriptive findings on development data. Any rule change they suggest needs its own pre-registration.

## Corrections to the PRD draft (§2)

| Figure | PRD draft | This run | Why |
|---|---|---|---|
| Stop touched on the entry day | 49.8% | 40.5% | The draft figure came from an earlier ad-hoc script and was marked unverified. The run gets 40.5% from both the simulator's exits and the Mode A paths. |
| Mean net per trade | −0.68% | −0.78% | The label code understated the locked-circuit losses. |

## Not done / not verified

- The Lab page renders:
  - with no script errors;
  - in both themes;
  - at 390 px with no horizontal overflow;
  - with every tab and the trade detail working (headless Chromium).

  **UNVERIFIED:** visual polish. The screenshots could not be viewed this session.
- The page is a local file: `run_20260920T003043/SimulationLab.html`. It embeds Kite-derived prices (internal-only) and is not published.
- **Waiting for owner decisions:**
  - Target exits in the portfolio loop (`engine.py`) and D5–D7.
  - The matrix pre-registration: the parameters in §10–§11, controls G and H, the tax regime and a scorecard rubric.
  - The D7 engine fixes above.
- **Deliberate-break checks:**
  - All caught, except 2 equivalent mutants: DP on a buy is already ignored by `costs.py`; "first bar on the date" cannot be missing.
  - One bytecode-cache artefact in the mutation script was found and fixed. Every mutation was then rerun.
- **Stale bytecode, found and cleared.** After the run, `research/model_v5/__pycache__` still held a mutant from the
  Phase 4 C/D deliberate-break checks (19 Sep). Its cached `features_p4cd` had the 60-outcome minimum set to 30, with
  a header matching the restored source, so the C/D test failed against mutant code.
  - A code-object comparison of all 43 valid caches in the worktree found only that one stale file.
  - The Phase 4 A/B run is not affected. It ran `phase4.py` as a script (compiled from source), and the caches of the
    modules it imported are identical to their sources.
  - This run did not import `features_p4cd`.
  - Caches cleared; the model_v5 suite then passed 69 of 69.
  - C/D was never run.
  - The C/D and A/B deliberate-break results from 19 Sep used the older script and should be re-checked with the
    fixed one before C/D is run.

