# Smart Money — paired B-vs-C gate decision report

**Run date** 2026-10-22 · **stage** exploratory · **code commit** `b4d521e5`
**Decision: INCONCLUSIVE — do not promote. Separately, a ≥ +1.0 pp increment can already be ruled out.**

> Supersedes the first pass of this report. Forward returns are now computed from
> `nidp.prices_eod_adjusted.adj_open` (split/bonus-adjusted). The earlier version measured raw
> `prices_eod` opens and worked around the resulting corporate-action artefacts by *excluding*
> affected symbol-days; that workaround has been removed. See §4.5.

---

## 1. The two frozen contracts

| | Study B (baseline + holdings tilt) | Study C (adds deal intelligence) |
|---|---|---|
| Study id | `NIDP-SM-VALIDATION-001` | `NIDP-SM-VALIDATION-002` |
| Preregistered SHA-256 | `6bcd0fe4d048b8cd018d68c85ad4b1751146cfca6b4b0ce17b6018a93d0e024b` | `1a4b7d6f20a55494ee53c6b3394d4121435c019d13a90a962157e11c6e777838` |
| Hash re-verified this run | ✅ `6bcd0fe4d048b8cd…` | ✅ `1a4b7d6f20a55494…` |
| Run id | `4faf3eaa-2b3f-4bbc-af4b-2fca627830bf` | `9c0eb9f6-be16-41e9-bbcd-b83ba7e0f82f` |

Both configs were re-hashed from the stored JSON and compared with the registered digest before
any data was read. A mismatch aborts the run; neither mismatched.

The two run rows are mutually discoverable: the summary persisted on **both** rows carries
`study_b` / `run_id_b` and `study_c` / `run_id_c`, so either row identifies the pair. (Each study
needs its own `run_id` because `smart_money_shadow_predictions` is keyed
`(run_id, scoring_date, symbol)` — one model per run. The frozen schema was not altered.)

Shared terms taken from the contracts, not from code defaults: primary horizon **20 sessions**,
hurdle **+1.00 pp**, round-trip cost **0.4937%**, open-to-open execution.
`portfolio_n = 30`, `deal_lookback_days = 90` and `max_deal_tilt = 4.0` are **implementation
parameters, not contract terms** — they are recorded on both run rows as such.

## 2. B versus C

Paired by construction: both models are scored on exactly the same eligible (date, symbol) pairs,
and every symbol considered is persisted — 45,218 prediction rows including the ineligible ones
with a reason, 540 outcome rows.

Verified rather than assumed: B eligible **6,873**, C eligible **6,873**, inner join on
`(scoring_date, symbol)` **6,873**, rows only-in-B **0**, rows only-in-C **0**.

| Formation date | Eligible | B net | C net | Paired diff | Names changed /30 |
|---|---|---|---|---|---|
| 2026-01-12 | 650 | +2.13% | +2.13% | 0.000 pp | 0 |
| 2026-02-12 | 704 | −4.09% | −4.09% | 0.000 pp | 0 |
| 2026-03-12 | 681 | +1.02% | +2.09% | **+1.070 pp** | 1 |
| 2026-04-13 | 784 | +3.38% | +4.19% | **+0.818 pp** | 1 |
| 2026-05-12 | 797 | +5.16% | +5.16% | 0.000 pp | 0 |
| 2026-06-12 | 801 | +1.28% | +1.28% | 0.000 pp | 0 |
| 2026-07-13 | 827 | +0.56% | +0.56% | 0.000 pp | 0 |
| 2026-08-12 | 798 | +1.70% | +1.78% | **+0.082 pp** | 2 |
| 2026-09-15 | 831 | +1.42% | +1.42% | 0.000 pp | 0 |

- **Mean paired difference: +0.2189 pp**
- **95% date-block bootstrap CI: [+0.0000, +0.5104] pp** (5,000 resamples of whole formation
  dates, seed 20261022 — dates are the dependence unit, not symbol-days)
- Hurdle: **+1.00 pp**
- Portfolio names changed by the deal feature: **4 of 270 picks (1.5%)**

The paired difference is **unchanged** by the switch to adjusted prices, to four decimal places.
That is expected, not a coincidence: the difference depends only on the handful of names where B
and C disagree, and none of the four corporate-action symbol-days was one of them. Absolute B and
C levels *did* move (2026-01-12 +1.44% → +2.13%; 2026-05-12 +6.12% → +5.16%), which is why the
levels in this table differ from the superseded version.

## 3. Statistical uncertainty — and what it does and does not license

Under the frozen decision rule (PASS = CI lower bound above the hurdle; FAIL = CI upper bound
below zero) this is neither. **INCONCLUSIVE.**

Two separate things are true and must not be collapsed:

1. **The sample cannot support a promotion decision.** 9 formation dates against study 001's
   review floor of 12 effectively independent blocks. With ~0.87 month-over-month persistence in
   the holdings signal, the effective number of independent observations is materially below 9.
2. **A ≥ +1.0 pp increment can nonetheless be ruled out at 95%,** because the whole interval
   ([0.00, +0.51]) sits below the hurdle. That is an informative negative, not a null result.

**The interval is narrow for the wrong reason.** Six of nine paired differences are *exactly*
zero, because the deal feature did not change portfolio membership on those dates. The CI is tight
because the estimator is mostly measuring zero, not because we have precision about a real effect.
Do not read [0.00, 0.51] as a confident small-positive estimate.

**Why the feature is near-inert at this configuration** — measured by differencing the C overlay
against the B overlay on the same symbol-day:

| Measurement | Value |
|---|---|
| Eligible symbol-days | 6,873 |
| Deal overlay non-zero | **183 (2.66%)** |
| Mean \|deal tilt\| where present | 1.313 points (max 3.653, bound 4.0) |
| Rows where the overlay changes *any* rank | 4,094 |
| Names it pushes **out of** the top 30 | **4** |
| Names it pushes **into** the top 30 | **4** |
| Names unaffected in the top 30 | 266 of 270 |

So the overlay perturbs ranks widely but crosses the top-30 boundary only 4 times in 270 slots.
A 1–4 point nudge on a 0–100 score rarely clears into the top 30 of a 650–831 name universe.

Three paths, in order of preference: raise `portfolio_n` so marginal rank changes matter; widen
the deal window beyond 90 days; or accept that bulk/block deals are too sparse at Nifty-500
liquidity to act as a portfolio-selection feature and use them only as per-stock evidence on the
screen. **None of these may be chosen by looking at this result** — that is contract-fitting.

## 4. Data-quality diagnostics

### 4.1 Formation-date availability is structurally capped at 9
| Excluded date | Reason |
|---|---|
| 2025-12-12 | no baseline — `stock_features_daily` begins **2025-12-29** |
| 2026-04-12, 2026-07-12, 2026-09-12 | no baseline scores at the snapped date |
| 2026-10-12 | only 6 sessions forward of 20 |
| 2026-10-21 | 0 sessions forward |

The ceiling is a hard one: the baseline feature history starts 2025-12-29 and the forward window
must close on or before 2026-10-21, so a monthly PIT series can yield **at most 9** usable dates
today. **The 12-block floor cannot be reached by re-running anything.** It is reached by waiting:
one new usable date per month, so ~Jan 2027 for 12 — or by backfilling `stock_features_daily`
earlier than 2025-12-29, which would also let the series extend backwards.

### 4.2 Smart-money coverage of the eligible population
| Date | Eligible | With an MF score | Coverage | High confidence | Single-AMC signal |
|---|---|---|---|---|---|
| 2026-01-12 | 650 | 498 | 76.6% | 351 | 64 |
| 2026-02-12 | 704 | 535 | 76.0% | 356 | 84 |
| 2026-03-12 | 681 | 523 | 76.8% | 377 | 79 |
| 2026-04-13 | 784 | 584 | 74.5% | 444 | 92 |
| 2026-05-12 | 797 | 589 | 73.9% | 436 | 102 |
| 2026-06-12 | 801 | 591 | 73.8% | 431 | 119 |
| 2026-07-13 | 827 | 618 | 74.7% | 439 | 138 |
| 2026-08-12 | 798 | 617 | 77.3% | 472 | 135 |
| 2026-09-15 | 831 | 634 | 76.3% | 466 | 150 |

Coverage clears the 50% representativeness floor on every date, but ~24% of the eligible universe
carries **no tilt at all** in either model. Those names compete for the top 30 on the untilted
baseline score. Single-AMC signals rise steadily (64 → 150) as coverage widens — concentration
risk in the signal is growing, not shrinking.

### 4.3 Exclusion ledger (all 9 dates, both studies)
| Reason | Symbol-days |
|---|---|
| below_liquidity_floor | 13,862 |
| below_min_price | 1,072 |
| no_price_on_date | 555 |
| no_baseline_score | 168 |
| no_forward_window | 40 |
| insufficient_history | 39 |

`corporate_action_in_window` no longer appears: those 32 symbol-days are now *included* and priced
correctly off the adjusted series (§4.5).

### 4.4 Look-ahead control
`nidp.v_smart_money_lookahead_gap` on the nine formation dates: score correlation between the
reporting-date series and the point-in-time series runs **0.831–0.875**, mean absolute score
difference **6.72–8.20 points**. The two series are materially different, which is the point —
the PIT series is the one used here, and the gap is the size of the look-ahead that would have
been harvested by using reporting dates. It is not small.

### 4.5 Corporate actions — fixed at the source, not worked around
The first pass of this evaluator read raw opens from `nidp.prices_eod` and produced KOTAKBANK at
**−79.70%** over 20 sessions (entry ₹2,126.90 → exit ₹431.70): a 5:1 face-value split, ex
2026-01-14, inside the 2026-01-13 → 2026-02-11 window. That is a corporate action reported as a
return.

The first fix excluded affected symbol-days. **That was the wrong fix** —
`nidp.prices_eod_adjusted` already carries a corrected series, so the data was being discarded
rather than used. Forward returns now read `adj_open` from that table. `prices_eod` is still used
for the trading calendar (it defines session dates), which needs no adjustment.

Verified on the stored outcomes:

| Check | Result |
|---|---|
| Entry prices matching `adj_open` | **270 / 270** |
| Rows where `adj_open` ≠ `raw_open` (the discriminating cases) | 4 |
| On those 4 rows, value stored | the **adjusted** one |
| Outcome rows ≤ −50% over 20 sessions (artefact signature) | **0 of 540** |
| Full return range across both runs | −26.30% … +39.38% |

KOTAKBANK 2026-01-12 now reads **+1.49%** (₹425.38 → ₹431.70) instead of −79.70%.

**New data-quality finding, logged not fixed:** the three ANANDRATHI adjustment rows carry
`last_event_type = 'DIVIDEND'` with an adjustment factor of exactly 2.0 (raw ₹3,129.80 →
adj ₹1,564.90). A dividend does not halve a price; the factor looks right but the **event label is
probably wrong** (a split or bonus mislabelled). This does not affect returns here — the factor is
what matters — but anything that *filters* on `last_event_type` would misclassify these rows.

**The adjusted series is not complete, and this run was clean by luck of the calendar.**
Switching to `prices_eod_adjusted` is necessary but not sufficient. Inside the study window
(2026-01-12 → 2026-10-21), **19 symbols** have a single-session `adj_open` fall of 35% or more
with `cumulative_adj_factor = 1.0` — i.e. the adjuster did not adjust them:

| Symbol | Date | Move | CA row present? |
|---|---|---|---|
| RNBDENIMS | 2026-05-19 | −82.13% | no |
| INDIAGLYCO | 2026-09-17 | −77.79% | no |
| SADHNANIQ | 2026-02-18 | −71.62% | **yes** |
| **VEDL** | **2026-04-30** | **−61.14%** | **yes** |
| MAHAPEXLTD | 2026-03-20 | −55.44% | **yes** |
| … 14 more to −38% | | | mostly no |

Two distinct failures: 14 of 19 have **no** `corporate_actions` row at all, and 5 — including
Vedanta, a liquid large-cap — **have a row that the adjuster did not apply**. So the gap is in the
price adjuster as well as in corporate-action coverage. (For the record, `corporate_actions` is
*not* "nearly empty" as two in-repo comments still claim: it holds 71 SPLIT, 62 BONUS, 59 RIGHTS
and 1,856 DIVIDEND rows back to 2025-10-03. Those comments are stale. Coverage is incomplete, not
absent.)

**Is this run contaminated? No — verified exhaustively, not assumed.** Of those 19 symbols, 132
symbol-days appear in the predictions, 26 were eligible, and **2 were actually picked**. Both are
VEDL on 2026-01-12, whose holding window is 2026-01-13 → 2026-02-11; its unadjusted move is
2026-04-30, outside it. Realised +10.13%. The decisive query — every outcome row joined to every
unadjusted move falling strictly inside its own holding window — returns:

```
 contaminated_outcome_rows
---------------------------
                         0
```

So the +0.2189 pp result and its CI are sound. But **VEDL ranked 23 on 2026-01-12, inside the
top 30.** Had its ex-date fallen a quarter earlier, the study would have ingested a −61% artefact
and the mean would be meaningless. This is a latent hole in the method, not a cleared risk: the
evaluator should assert that no picked symbol has an unexplained ≥35% single-session move inside
its holding window, and fail loudly if one does, rather than relying on the adjusted table being
right.

**Still unverified:** other backtests in this repo that read `prices_eod` open/close across
multi-week windows have the same original bug. An audit found **9 affected sites in 6 files**
(worst: `intelligence/confirmation.py` 20-session highs and ranges, three separate copies of a
52-week high/low block, `intelligence_layer/service.py` correlations, and
`daas_api/routers/movers.py:_bars_for` feeding ATR and leak detection). None is fixed.

## 5. Known biases, stated rather than buried

- **Price return, not total return.** Dividends are not added back. Across 20 sessions this
  understates both models equally, so the paired difference is largely unaffected; absolute
  levels are not. `prices_eod_adjusted.tret_close` carries a total-return series, so a
  total-return variant is now a small change rather than a missing capability — it is simply not
  what the frozen contracts specify (open-to-open execution).
- **No benchmark or sector-relative column is populated.** `benchmark_return_pct` and
  `sector_return_pct` are NULL in **all 540** outcome rows (verified, not assumed). Study 001
  names Nifty 500 TRI and a sector-relative benchmark; **neither is computed yet**, so every
  return above is absolute. Gates requiring benchmark-relative performance are untested.
- **Deals are read strictly before the scoring date,** because the Trendlyne deal feed carries no
  publication timestamp. If disclosure genuinely lags the trade date, this is conservative; it
  cannot be verified from the feed.
- **Exploratory stage.** This run is labelled `exploratory` on both run rows. It is not a
  confirmatory evaluation and must not be cited as one.

## 6. Gate decision

**INCONCLUSIVE. Study C is not promoted. Shadow mode continues.**

What would change the answer, in the order it should be done:

1. **Backfill `stock_features_daily` before 2025-12-29.** This is the single binding constraint;
   it unlocks both more formation dates and a longer series. Without it, the 12-block floor is a
   calendar problem, not an engineering one.
2. **Compute the two benchmarks** (Nifty 500 TRI, sector-relative) into
   `smart_money_study_outcomes`. Until then no benchmark-relative gate can be evaluated at all.
3. **Audit every other `prices_eod` consumer** that spans a multi-week window and repoint it at
   `prices_eod_adjusted`. The bug is fixed here and nowhere else.
4. **Decide the deal feature's role on priors, not on this output.** It fires on 2.66% of
   symbol-days and moves 1.5% of picks. Either it is a portfolio-selection feature at a larger
   `portfolio_n`, or it is per-stock evidence for the Smart Money Movement screen. Choosing by
   re-running until a number improves is contract-fitting and the frozen hashes exist to prevent
   it.
