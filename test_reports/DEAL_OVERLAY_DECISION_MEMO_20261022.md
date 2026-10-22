# Smart Money deal overlay — decision memo for the study owner

**Date:** 2026-10-22 · **Studies:** `NIDP-SM-VALIDATION-001` (B, baseline) vs `NIDP-SM-VALIDATION-002` (C, baseline + bulk/block deal overlay) · **Status: Study C remains in SHADOW MODE.**

This memo exists to separate what we now *know* from what someone must *decide*. Every number
below is measured and attributed. Nothing here promotes Study C, and nothing here changes a frozen
contract.

---

## 1. The headline: what the INCONCLUSIVE verdict can and cannot be claimed to mean

The reported result is unchanged and remains correct as a number: **mean paired increment
+0.2189 pp, 95% CI [0.0000, +0.5104] pp against a +1.00 pp hurdle, over 9 formation dates against
a review floor of 12 → INCONCLUSIVE.** A re-run after adding integrity screening reproduced it to
six decimals on every date.

What changed is what that number is *about*. Two defects, both measured today, mean the study did
not test the thing its name implies:

- **It saw 27.8% of its universe.** The deal table had been queried for only 1,910 of 6,873
  eligible symbol-dates. For the other 4,963 the overlay contributed nothing, and the honest
  statement is **"never asked"**, not "no institutional interest".
- **It implemented 1 of 6 registered features**, by effect on the score (see §3).

So the defensible phrasing is: *a one-of-six subset of the registered overlay, measured over
roughly a quarter of the intended universe, did not add measurable value.* It is **not** evidence
that bulk/block deal data lacks value — and it is equally **not** evidence that the overlay works.
The experiment was uninformative, in a specific and now-understood way.

One thing the result does still support, because it is arithmetic rather than inference: within
what *was* measured, a ≥+1.0 pp increment is ruled out at 95%. But the CI is narrow because the
estimator mostly measured zero — **6 of 9 paired differences are exactly 0.000** — not because it
was precise.

---

## 2. What was a defect versus what was a design choice

This distinction governs what needs a preregistration ruling and what does not.

### Defects — repairs need no preregistration

| Defect | Evidence | Status |
|---|---|---|
| **Deal ingest walked A–G forever.** `_symbols()` ordered alphabetically; `run()` breaks on call-budget exhaustion, so every re-run re-walked the same prefix. 643 of 984 candidates (65%) never fetched once. | Table held 19,787 legs across 328 symbols, **every one** starting with a digit or A–G. All 4 promoted names begin A–E; all 4 displaced begin H–P with tilt exactly 0.0. | **FIXED** (`5f7e83c4`). Durable resume cursor. Now **561 symbols / 33,290 legs**, with **229 symbols / 13,240 legs past 'G'** where the count was 0. Range 360ONE…ZYDUSWELL. **Ingest not yet complete** — stopped deliberately to avoid starving the shared daily job. |
| **Corporate actions could enter returns as performance.** | 52 detections on the real run; VEDL −64.90% with a DEMERGER row and `cumulative_adj_factor` still 1.0. | **FIXED** (`a2cf18b8`). Fail-closed screen, 51 excluded / 1 kept. Verdict unchanged. |
| **Raw prices used where the maths spans a corporate action.** | `volume_spike_ratio` read 4.27x raw vs 1.53x adjusted — clearing the 3.0 threshold and awarding +25 score. ATR-14 overstated 3.80x. 3,077 correlation sign flips. | **FIXED** (`bc3bb2bf`), 7 expressions across 6 files; 3 legs deliberately left raw with reasons recorded. |
| **Feature 2 computed then discarded.** Net disclosed flow excluding transfers is produced twice — in the view and in `_DEALS_SQL` — loaded into the deals dict, and **never read**. Its only reader, `_deal_tilt`, touches client counts only. Not persisted either. | Repo-wide grep for `gross_value_inr`/`qty_bought`/`qty_sold`/`had_block`/`had_bulk` over `backend/` returns **zero** Python matches. | **OPEN.** A wiring gap, not a data gap. |

### Design questions — these may need a ruling

- **Confidence asymmetry.** `confidence = 1.0 if buying_clients >= 3 else (0.6 if == 2 else 0.3)`
  keys only on the buy side, so a sell-only name is damped *because it has no buyers*. All 46
  `buying_clients = 0` symbol-dates received exactly **−1.2**, against a realised positive reach of
  **+3.653** — the negative side reaches 30% of the positive side under a symmetric ±4.0 bound.
- **Counterparty classification is absent entirely.** No category column exists anywhere in the
  deal path, so every `client_name` counts equally. ~30.4% of surviving legs belong to 19
  prop/market-making names (**a lower bound** — derived from name-pattern matching, since no
  classification exists). 38.5% of surviving client-symbol-days have the **same client on both
  sides**, which zeroes roughly half the surviving evidence (`buying_clients == selling_clients` in
  180 of 363 cases).
- **The ±4.0 tilt bound is uncalibrated and probably too hot.** Score gaps at the rank-30 boundary
  are **0.003–0.270 points**. Observed tilts moved ANTHEM from rank 64→19 and EMCURE 52→13. One
  disclosed deal can reorder ~100 names. This risk is currently masked only by the 2.7% fire rate —
  **and completing the ingest removes that mask.**

---

## 3. The registered-vs-implemented gap, and why the hash guard missed it

Of the six features registered in `002.deal_feature_rules.features`:

| # | Registered feature | Status |
|---|---|---|
| 1 | Deal intensity vs turnover and free float | **ABSENT** — and *not* a data gap: `stock_features_daily.free_float_pct` is populated (269,424 of 462,378 rows, 1,492 symbols) across all 9 formation dates |
| 2 | Net disclosed flow excluding transfers | **COMPUTED THEN DISCARDED** — contributes exactly zero |
| 3 | Repeat buying by same/independent clients | **ABSENT** — the view aggregates `client_name` away into distinct counts; unreachable from `_DEALS_SQL` |
| 4 | Deal price vs market price | **ABSENT** — the view exposes no price column at all (13 columns, none a price) |
| 5 | Block vs bulk split | **ABSENT** — `had_block`/`had_bulk` are materialised by the view and never selected |
| 6 | *(the sole survivor)* | **IMPLEMENTED, DEGRADED** — a sum of per-day distinct counts rather than a window distinct count |

**By effect on the result the subset is 1-of-6, not 2-of-6.** Consequently the six registered
`reporting_breakdowns` are not producible by any code in the repo.

**Is this a contract violation?** The audit's ruling: **yes, a defect against the registered
design.** The contract contains no scope, phasing or partial-implementation permission — a
search for `phase|partial|subset|initial|minimum|scope|defer|later|future` across both contracts
returns exactly one hit each, and in both cases it is inside `failure_policy`, where "subset" is a
**prohibition, not a permission**. The `features` list sits inside `deal_feature_rules`, the block
that *defines the model*, with no qualifier.

Corroboration from the implementation itself: the code enumerates exactly what it claims as
out-of-contract latitude and writes that enumeration onto every run — *"portfolio_n and deal tilt
bounds are implementation parameters, not part of either frozen contract"*. Three items are
claimed: `portfolio_n`, `deal_lookback_days`, `max_deal_tilt`. **The feature subset is not among
them**, and no run record declares a reduced feature set. The author's own contract/implementation
boundary therefore places the features list on the contract side.

**The governance finding worth carrying beyond this study:** `load_study()` re-hashes the stored
config and aborts on mismatch — and it **passes**. Canonical sha256
`1a4b7d6f20a55494ee53c6b3394d4121435c019d13a90a962157e11c6e777838` matches the registered
`prereg_sha256` exactly. That proves the contract **text** was unaltered. It performs **no check
that the implementation implements the registered features**, so a 1-of-6 build sails through the
guard untouched. *A clean contract hash on a run record is not evidence of design fidelity.*

**Mitigating, recorded without ruling on it:** both runs are stamped `stage = exploratory`, not
confirmatory, and the features list is prose rather than an executable spec — so the gap is at
least as consistent with an incomplete build as with a post-hoc narrowing.

---

## 4. A second, independent bias that affects any plan to add blocks

This one matters for sequencing and is easy to miss.

`data_confidence = high` requires `months_observed >= 3 AND amcs_increasing >= 3`, which is
**arithmetically unreachable on a front block**. Measured: **0 `high` at 2025-12-12 versus 535 at
2026-10-12**. Because contract 001 freezes tilt scaling at high 1.0 / medium 0.6 / low 0.25, the
mean multiplier is **0.4679 at the front versus 0.6820 at the back** — the overlay is damped to
roughly **69%** on a new front block, and the scored universe there is 20% smaller (769 vs 967
symbols).

So **adding earlier blocks adds blocks where Study C is attenuated by construction**, biasing the
paired difference toward zero. It would look like more evidence while being weaker evidence, and it
sits against the study's own "held constant: tilt scaling" premise.

Separately, the sample ceiling is now understood: **blocks 10 and 11 need no new data at all** —
only a feature/v3 re-run plus a PIT sweep at 2025-11-12 and 2025-12-12, once the price hole is
closed. **Only block 12 needs an MF-disclosure backfill** (`nidp.mf_holdings_monthly`, via
AdvisorKhoj, 2025-08 — obtainable, 12 AMCs resolve, 7 credibly dated, ~12 downloads / ~40 MB).

---

## 5. The decisions that are the owner's to make

**(a) Does a re-run on repaired data continue this exploratory study, or need a fresh confirmatory holdout?**
Outcomes have already been inspected at `stage = exploratory`. Arguments both ways are real: the
frozen contracts specify *rules, not dates*, and adding data is not the "horizon, benchmark,
threshold or subset" change the failure policy forbids — so a re-run is defensible. Against that,
the implemented feature set has been seen to under-perform, and widening it after inspection is
precisely what preregistration guards against. **Not my call.**

**(b) Should the missing registered features be implemented before any re-run?**
Re-running the 1-of-6 subset on repaired data would reproduce the same interpretive problem at
greater cost. But implementing features 1–5 changes the implemented design, which under 002's own
`failure_policy` points to a new `study_id` with a fresh holdout. Note feature 2 is a pure wiring
fix (the value is already computed), and feature 1 needs no new data (`free_float_pct` is
populated) — so these are cheaper than they look, which does not by itself make them permissible.

**(c) How should the `data_confidence` front-block attenuation be handled?**
Options: accept and report it; exclude blocks where `high` is structurally unreachable; or treat
the blocks as non-comparable and preregister anew. Doing nothing silently biases toward zero.

**(d) Is ±4.0 acceptable once the fire rate rises?**
Completing the ingest removes the masking. At rank-30 gaps of 0.003–0.270 points, this is a live
reordering risk, not a theoretical one.

---

## 6. What must not happen

Stated plainly, because the pressure to do these grows when a result is inconclusive:

- **Do not lower the +1.00 pp hurdle.**
- **Do not change the estimator** or the bootstrap configuration to obtain a narrower interval.
- **Do not drop inconvenient formation dates.**
- **Do not promote Study C out of shadow mode** on the current evidence.
- **Do not describe the result as "deal data has no value."** It does not support that.

An inconclusive result reported honestly is a success. A manufactured pass is a failure that would
propagate into live recommendations.

---

## 7. Evidence table

| Claim | Measured value | Source |
|---|---|---|
| Paired increment / CI / hurdle / dates | +0.2189 pp · [0.0000, +0.5104] pp · +1.00 pp · 9 of 12 | DB, re-verified post-rerun |
| Paired diffs exactly zero | 6 of 9 | DB |
| Deal attrition funnel | 6,873 eligible → 1,910 queried → 498 with deal → 363 netted → 183 tilted → 13 reachable → 4 changed | diagnosis report |
| Deal table before → after repair | 328 symbols / 19,787 legs → **561 / 33,290** | DB, verified independently |
| Symbols past 'G' | 0 → **229** (13,240 legs) | DB, verified independently |
| Registered features implemented | **1 of 6** by effect | contract audit |
| Contract hash | matches `prereg_sha256` exactly; guard checks text only | reproduced |
| Front-block tilt multiplier | 0.4679 (2025-12-12) vs 0.6820 (2026-10-12) | MF probe |
| `data_confidence = high` counts | 0 at 2025-12-12 vs 535 at 2026-10-12 | MF probe |
| Integrity screen | 52 detections, 51 excluded, 1 kept, `picked_contaminated: 0` | DB + report |
| Benchmark / sector | 540/540 populated (proxy) / NULL, marked UNAVAILABLE | DB, verified |
| pytest | 51 failed / 1318 passed / 5 skipped; 51 failures identical to baseline | run this session |

### Unverified

- **No AdvisorKhoj disclosure file body was downloaded or parsed.** All depth verdicts rest on HTTP
  status, `Last-Modified` and the repo's URL matcher. A file can return 200 with a credible header
  and parse to zero holdings. **Row counts for a backfilled month are unmeasured.**
- The prop/market-maker share (~30.4%) is name-pattern derived and is a **lower bound**; 68.6% of
  legs are unclassified.
- Tilt thresholds (5pp / 0.7–1.3 / 0.3 / ±4.0) are **uncalibrated** — no labelled set exists to fit
  them against.
- The price backfill is **incomplete**: 2025-03 … 2025-09 was still a hole at last measurement
  (2025-04 … 2025-08 at zero sessions), and the agent stopped at 2025-04-08 on a session limit.
- `code_commit` on the re-run records a commit predating the evaluator change (now committed as
  `a2cf18b8`); config hashes are exact, the code hash was not.

---

## 8. Next actions, in order

| # | Action | Preregistration |
|---|---|---|
| 1 | Close the price hole 2025-03 … 2025-09 and verify session-by-session continuity against the NSE calendar | **not needed** |
| 2 | Finish the deal ingest from the resume cursor (budget-aware, across days) | **not needed** |
| 3 | One rebuild of the **whole** window on a single consistent 280-bar basis, then re-run v3 and the PIT sweep | **not needed** — but do not start until 1 is confirmed closed |
| 4 | Backfill `mf_holdings_monthly` 2025-08 from AdvisorKhoj to unlock block 12 | **not needed** |
| 5 | Wire up feature 2 (already computed, discarded unread) | **needs a ruling** (b) |
| 6 | Implement features 1, 3, 4, 5 | **needs a ruling** (b) |
| 7 | Symmetric confidence; entity classification; ±4.0 recalibration | **needs a ruling** (b), (d) |
| 8 | Any re-run intended as evidence | **needs a ruling** (a), (c) |

**A hazard attached to action 3:** 213 sessions exist before 2025-11-12 *even with the hole open*,
so a 60-bar warm-up will succeed numerically while spanning a 10-month jump — producing, for
example, a `return_60d_pct` comparing Nov 2025 against Dec 2024. **Nothing errors and the columns
populate.** Do not re-run features until the hole is confirmed closed.
