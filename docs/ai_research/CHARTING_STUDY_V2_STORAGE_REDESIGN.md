# Study-run / storage redesign for pre-registration v2

**Status: SCOPE FOR REVIEW — no code changed, nothing aggregated, nothing deleted.**
Date: 2026-09-23 · Covers steps 1–3 of the agreed sequence (audit v1 output → map v2 requirements →
design the accumulator). Steps 4–9 (prove equivalence → small test → 200 → verify disk → 1,000 →
sealed run) follow this document's approval.

**The constraint this respects, stated first:** V-3 stays at **1,000 seeds**. Reducing it to fit a
disk would silently change an approved study parameter, and V-3's own rationale is that 200 seeds
give a smallest empirical p of ~0.005, too coarse for 380 cells. This redesign is what *makes* 1,000
seeds affordable; it is not a negotiation with the seed count.

---

## 1. The problem, measured

TC-113 (`test_reports/charting_study_parallel_ab.md`), measured on 8 symbols / 10 seeds and scaled to
the pre-registered universe of 2,132 symbols:

| Artefact tree | v1 scale (200 seeds) | Per row |
|---|---|---|
| `random_control/events.jsonl` | **≈ 6.4 TB** | ≈ 143 KB |
| `buy_next_open/events.jsonl` | ≈ 54 GB | ≈ 148 KB |
| pattern `events.jsonl` | ≈ 24 GB | ≈ 67 KB |
| `atr_decile_control/events.jsonl` | ≤ pattern-event scale | ≈ 143 KB |

Free disk on this host, checked today: **9.3 GB** (`df -h /` → `79G / 69G used / 9.3G avail`).

Two things follow that a "just delete the random control" answer would miss:

1. **V-3 multiplies the largest tree by five** → ≈ 32 TB at v1's three families. v2 covers ~40
   reporting units (16 families × direction × two scales), so the real figure is larger again.
2. **Even at zero random control, ~78 GB of row-level artefacts remain** against 9.3 GB free. The
   redesign has to cover **all four** artefact trees, not just `random_control/`.

## 2. The finding that makes this safe

**The persisted control artefacts are write-only.** Nothing in the repo reads `events.jsonl` back.
`execute.py` builds the report from the **in-memory** `comparison_groups` object
(`study/execute.py:561-570`), never from disk. Independently corroborated by a structural detail:
`report._horizon_cost_scenario` keys horizons by **int** (`report.py:82-88`), and a JSONL round-trip
makes them strings — the persisted file could not be fed back to `report.py` unchanged even if
something tried.

So changing **what is persisted** cannot change **any reported number**. That is not an assumption to
be careful around; it is a property we can prove by test (step 4, §6 below).

### What the report actually consumes from control rows — the complete list

`comparison_block` (`report.py:326-383`) is the **only** function in the whole report that sees a
control row. Verified by reading it: `hit_rate_table`, `mfe_mae_stats`, `cost_sensitivity_table`,
`segmentation_report`, `move_direction_auc_report`, `bearish_directional_report` and
`exclusion_table` are all called on pattern rows only.

| Group | What is read | Shape needed |
|---|---|---|
| **Random control** | per seed: `n` and mean `net_before_tax` (base scenario) — **nothing else** | 2 numbers per (segment, unit, horizon, seed) |
| **ATR-decile** | full `return_stats`, **plus the per-ROW `net_before_tax` vector** for the percentile | a scalar vector, not rows |
| **Buy-next-open** | full `return_stats` | accumulators (+ ordering for `max_drawdown`) |
| **NIFTY 500** | one float, already stored as a compact summary | unchanged |

The entire 6.4 TB random-control tree collapses to **two numbers per seed**. At v2/V-3 scale
(~40 units × 5 horizons × 1,000 seeds × 2 segments) that is a few MB.

## 3. Design principle

> **Persist sufficient statistics and digests, never rows — and only statistics that trace to a v1
> §7 item or a v2 §6/§7/§8 requirement.**

No invented metrics. Every field in §4 cites the report line it reproduces. Two supports:

- **Reproducibility is preserved without rows.** Every draw is deterministic and exactly regenerable:
  `_random_control_picks` (`controls.py:494-501`) is `sorted(set(eligible))` → `random.Random(seed)` →
  `rng.sample` → `sorted`; the ATR-decile draw uses a SHA-256-derived `_seeded_rng(seed, event_id)`;
  buy-next-open is RNG-free. So persisting, per seed, the **sha256 of the bytes `write_run` would have
  produced** (`writer._dump_jsonl`, computed streaming and discarded) plus `row_count` preserves the
  §8 kill-switch property at ~64 bytes per seed instead of ~15 MB per symbol per seed. An auditor
  regenerates any seed on demand and checks the digest.
- **Exactness where a mean would not do.** Medians, `max_drawdown` and holding periods are computed
  **in memory, per seed, while that seed's rows exist**, and only the resulting scalar is persisted.
  Holding period is a bounded small integer (0..20), so a 21-bin histogram is an *exact* sufficient
  statistic, not an approximation.

## 4. The accumulator — one record per (segment, unit, horizon, scenario, seed)

Every field traces to an existing consumer. Nothing here is new analysis.

| Field | Reproduces | Source line |
|---|---|---|
| `n`, `insufficient_n` | item 3 `n`; the `n < 30` flag | `report.py:42, 62-66` |
| `sum_gross`, `sum_net`, `sum_cost`, `sum_slippage` | mean gross/net, `avg_cost`, `avg_slippage`, `net_expectancy` | `report.py:227-231, 243-246` |
| `n_wins`, `sum_wins`, `n_losses`, `sum_losses` | `win_rate`, `avg_win`, `avg_loss`, `profit_factor` (incl. its `inf`/`None` cases) | `report.py:247-252` |
| `median_gross`, `median_net` | item 3 medians — quantiles, so computed per seed in memory | `report.py:260-261` |
| `max_drawdown` | item 3 — order-dependent path statistic over rows sorted by `(signal_date, event_id)`; computed in memory, persisted as a scalar | `report.py:217, 254-257` |
| `n_unavailable_by_reason` | item 1 exclusion tallies, applied to the comparison groups | `extraction.py:131-133` |
| `net_quantile_grid[21]` *(insurance, ~3.4 MB/unit)* | approximately reconstructs a pooled cross-seed row-level distribution, should one ever be wanted | — |
| `rows_sha256`, `row_count`, `picks_sha256` | §8 kill-switch equivalence and on-demand regeneration | `integrity.py:41-46` |

Plus, per `(…, target)` — 8 targets × 5 horizons × 4 scenarios:

| Field | Reproduces |
|---|---|
| `n`, `target_first`, `stop_first`, `ambiguous`, `neither`, `net_hits` | item 2 hit-rate cells (`report.py:150-199`) |
| `holding_period_histogram[0..20]` | item 4 `median_holding_period`, exactly |

**All four cost scenarios, not just `base`.** v1 reads controls at `base` only
(`report.py:332, 578-584`), but v1 item 9 / v2 §7 require cost sensitivity for every headline net
number. Widening the accumulator ×4 is cheap now and **irreversible if omitted**, so the design does
it from the start.

**For the ATR-decile and buy-next-open groups:** keep the **per-row `net_before_tax` scalar vector**
(8 bytes per row per horizon per scenario, tens of MB) rather than rows. This is what V-2's
"95th percentile of the ATR-decile control" needs, and it keeps every quantile available rather than
freezing one.

**Projected volume at v2 / V-3 scale:** 2 segments × ~40 units × 5 horizons × 4 scenarios × 1,000
seeds ≈ 1.6 M records ≈ a few hundred MB as JSONL, tens of MB as Parquet — against 9.3 GB free.
**32 TB → well under 1 GB, with V-3 at its approved 1,000 seeds.**

## 5. Reversibility — what the design deliberately protects

Ten things would become unrecoverable if rows were aggregated naively. Each is handled above:
pooled cross-seed row distributions (quantile grid), `max_drawdown` (per-seed scalar), medians
(per-seed scalar), holding period (exact histogram), per-target hit-rate cells (counters), all four
cost scenarios (×4 width), segmentation bucket edges, control exclusion tallies, which pairs each
seed drew (`picks_sha256` + regenerability), and the `as_if_target`/`as_if_stop` legs.

**The last one is the only accepted loss.** Nothing reads those legs today; if a future analysis wants
to price ambiguity both ways they are gone. Say so now if that should be two more counters.

**One §8 gate must move, or it silently weakens.** `assert_no_sealed_rows_in_dataset` is the *only*
probe that touches control rows today (`execute.py:399-410`) and reads just `signal_date`. If control
rows are generated per seed and discarded, this check must move **inside** the generation loop and
keep reporting `n_rows_checked` — otherwise its coverage shrinks from "every row" to "pattern rows"
with nothing failing. The kill switch and `recompute_sample` are unaffected: both already run on
in-memory **pattern** rows only, and `execute.py:374-377` documents that comparison-group
reproducibility is deliberately out of §8's scope.

**The ATR-decile percentile is not an open question.** `comparison_block`'s docstring freezes the
reading deliberately: the random control's distribution is per-seed "a sampling distribution of the
comparison", while the ATR-decile's is per-row "since it is already matched 1:1 … not resampled".
The per-row scalar vector preserves that reading exactly, and if the ATR-decile control were ever
made multi-seed, the per-seed record shape in §4 already covers it. No decision is forced.

## 6. Proving equivalence before anything is thrown away (step 4)

The test is the whole safety argument, so it is written before the accumulator is:

1. Run the existing v1 pipeline end to end at small scale (8 symbols, 10 seeds) — the TC-113 configuration.
2. Build the report the current way, from rows.
3. Build the report the new way, from accumulators.
4. **Assert the two `report.json` files are byte-identical.**

Only when that passes is row persistence switched off, and it stays switchable by flag so the
comparison can be re-run on demand. Then: 200 seeds → verify disk → 1,000 seeds → sealed run.

## 7. Decisions needed from the owner before step 3 becomes step 4

These change **what v2 computes**, not how it is stored, and the fields live only in the rows — so
they must be settled before generation, not after.

| # | Question | Why it cannot wait | If unanswered |
|---|---|---|---|
| **S-1** | v2 §7 says the measures are "v1 §7 items 1–10, **including every comparison group**". Does that literally extend items **2 (hit rates)**, **7 (segmentation)** and **9 (cost sensitivity)** to the control groups? v1 computes all three for pattern rows only. | Determines the accumulator's width. Adding a counter later means regenerating every seed. | I build the **wider** accumulator (all counters, all four scenarios). It costs little and cannot be added retroactively. |
| **S-2** | Should the comparison groups be **segmented** by trend class and regime (item 7)? | **Impossible today at any storage level:** control rows have no `context` block — `attach_context` runs inside `build_segment` on pattern rows only (`study/run.py:300-307`), and controls are built afterwards (`execute.py:536-540`). This is a *pipeline* gap, not a storage one, and closing it is separate work. | Liquidity and ATR-bucket segmentation of controls only (both derivable from control rows); trend/regime segmentation of controls is **reported as not available**, never silently omitted. |
| **S-3** | The `as_if_target` / `as_if_stop` legs of AMBIGUOUS outcomes are the one accepted data loss. | Two more counters if wanted; unrecoverable once rows stop being written. | Accepted as lost, recorded here. |

## 8. Scope boundary

This document covers **storage and run shape only**. It does not approve, amend or reinterpret any
pre-registered choice: V-1..V-5 stand exactly as drafted, V-3 stays at 1,000 seeds, and the sealed
block 2023-01-01..2024-07-31 remains untouched. It also does not flip
`CHARTING_PREREGISTRATION_V2.md` from DRAFT — that is a separate owner step, and Amendment E gates on
v2 having **reported**, not on it having been approved.

Nothing in v2 §8 requires persisted control rows. Confirmed rule by rule.
