# Smart Money — paired B-vs-C gate decision report

**Run date** 2026-10-22 · **stage** exploratory · **code commit** `b4d521e5`
**Decision: INCONCLUSIVE — do not promote. Separately, a ≥ +1.0 pp increment can already be ruled out.**

---

## 1. The two frozen contracts

| | Study B (baseline + holdings tilt) | Study C (adds deal intelligence) |
|---|---|---|
| Study id | `NIDP-SM-VALIDATION-001` | `NIDP-SM-VALIDATION-002` |
| Preregistered SHA-256 | `6bcd0fe4d048b8cd018d68c85ad4b1751146cfca6b4b0ce17b6018a93d0e024b` | `1a4b7d6f20a55494ee53c6b3394d4121435c019d13a90a962157e11c6e777838` |
| Hash re-verified this run | ✅ `6bcd0fe4d048b8cd…` | ✅ `1a4b7d6f20a55494…` |
| Run id | `6b248ae0-dd4f-43d2-bbbb-a6a3455fa043` | `0be817ea-f99c-48b0-a0d2-6779d989ec72` |

Both configs were re-hashed from the stored JSON and compared with the registered digest before
any data was read. A mismatch aborts the run; neither mismatched.

Shared terms taken from the contracts, not from code defaults: primary horizon **20 sessions**,
hurdle **+1.00 pp**, round-trip cost **0.4937%**, open-to-open execution.
`portfolio_n = 30`, `deal_lookback_days = 90` and `max_deal_tilt = 4.0` are **implementation
parameters, not contract terms** — they are recorded on both run rows as such.

## 2. B versus C

Paired by construction: both models are scored on exactly the same eligible (date, symbol) pairs,
and every symbol considered is persisted — 45,218 prediction rows including the ineligible ones
with a reason, 540 outcome rows.

| Formation date | Eligible | B net | C net | Paired diff | Names changed /30 |
|---|---|---|---|---|---|
| 2026-01-12 | 648 | +1.44% | +1.44% | 0.000 pp | 0 |
| 2026-02-12 | 697 | −4.09% | −4.09% | 0.000 pp | 0 |
| 2026-03-12 | 678 | +1.02% | +2.09% | **+1.070 pp** | 1 |
| 2026-04-13 | 783 | +3.38% | +4.19% | **+0.818 pp** | 1 |
| 2026-05-12 | 794 | +6.12% | +6.12% | 0.000 pp | 0 |
| 2026-06-12 | 797 | +1.28% | +1.28% | 0.000 pp | 0 |
| 2026-07-13 | 822 | +0.56% | +0.56% | 0.000 pp | 0 |
| 2026-08-12 | 794 | +1.70% | +1.78% | **+0.082 pp** | 2 |
| 2026-09-15 | 828 | +1.42% | +1.42% | 0.000 pp | 0 |

- **Mean paired difference: +0.2189 pp**
- **95% date-block bootstrap CI: [+0.0000, +0.5104] pp** (5,000 resamples of whole formation
  dates, seed 20261022 — dates are the dependence unit, not symbol-days)
- Hurdle: **+1.00 pp**
- Portfolio names changed by the deal feature: **4 of 270 picks (1.5%)**

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
because the feature is largely inert, not because we have precision about a real effect. Do not
read [0.00, 0.51] as a confident small-positive estimate.

**Why the feature is inert at this configuration:** of 6,841 eligible symbol-days, the deal tilt
was non-zero on **183 (2.68%)**, mean |tilt| 1.313 points where present (max 3.653, bound 4.0).
A 1–4 point nudge on a 0–100 score rarely crosses into the top 30 of a 648–828 name universe.
Three paths, in order of preference: raise `portfolio_n` so marginal rank changes matter; widen
the deal window beyond 90 days; or accept that bulk/block deals are too sparse at Nifty-500
liquidity to act as a portfolio-selection feature and use them only as per-stock evidence on the
screen. **None of these may be chosen by looking at this result** — that is contract-fitting.

## 4. Data-quality diagnostics

### 4.1 Formation-date availability is structurally capped at 9
| Excluded date | Reason |
|---|---|
| 2025-12-12 | no baseline — `stock_features_daily` begins **2025-12-29** |
| 2026-04-12, 2026-07-12, 2026-09-12 | not trading sessions (PIT dates now snap forward; these are the unsnapped originals) |
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
| 2026-01-12 | 648 | 498 | 76.9% | 351 | 64 |
| 2026-02-12 | 697 | 533 | 76.5% | 356 | 83 |
| 2026-03-12 | 678 | 522 | 77.0% | 376 | 79 |
| 2026-04-13 | 783 | 583 | 74.5% | 443 | 92 |
| 2026-05-12 | 794 | 586 | 73.8% | 433 | 102 |
| 2026-06-12 | 797 | 589 | 73.9% | 429 | 119 |
| 2026-07-13 | 822 | 618 | 75.2% | 439 | 138 |
| 2026-08-12 | 794 | 617 | 77.7% | 472 | 135 |
| 2026-09-15 | 828 | 632 | 76.3% | 464 | 150 |

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
| corporate_action_in_window | 32 |

### 4.4 Look-ahead control
`nidp.v_smart_money_lookahead_gap` on the formation dates: score correlation between the
reporting-date series and the point-in-time series runs **0.819–0.917**, mean absolute score
difference **5.45–8.94 points**. The two series are materially different, which is the point —
the PIT series is the one used here, and the gap is the size of the look-ahead that would have
been harvested by using reporting dates. It is not small.

### 4.5 Corporate actions — a bug found and fixed in this run
`nidp.prices_eod` has **no adjusted price column**. The first run produced KOTAKBANK at −79.7%
over 20 sessions: a 5:1 face-value split, ex 2026-01-14, inside the 2026-01-13 → 2026-02-11
window. Unadjusted raw opens turned a corporate action into a return and contaminated two dates
(2026-01-12 read −0.58% instead of +1.44%; 2026-05-12 read +3.53% instead of +6.12%).

The evaluator now excludes any symbol with a SPLIT / BONUS / DEMERGER / RIGHTS / DISTRIBUTION /
CONSOLIDATION ex-date inside the holding window, with the reason recorded per symbol-day (32
cases). Dividends and interest payments are deliberately **kept**: this is a price-return
convention, and that is a stated bias, not an oversight. **Any other backtest in this repo that
reads `prices_eod` open/close across a multi-week window has the same bug and has not been
checked.**

## 5. Known biases, stated rather than buried

- **Price return, not total return.** Dividends are not added back. Across 20 sessions this
  understates both models equally, so the paired difference is largely unaffected; absolute
  levels are not.
- **No benchmark or sector-relative column is populated.** `benchmark_return_pct` and
  `sector_return_pct` are NULL in all 540 outcome rows. Study 001 names Nifty 500 TRI and a
  sector-relative benchmark; **neither is computed yet**, so every return above is absolute.
  Gates requiring benchmark-relative performance are untested.
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
3. **Fix forward returns properly** — either adjust `prices_eod` for corporate actions or add an
   adjusted-price column — rather than relying on exclusion.
4. **Decide the deal feature's role on priors, not on this output.** It moved 2.68% of symbol-days
   and 1.5% of picks. Either it is a portfolio-selection feature at a larger `portfolio_n`, or it
   is per-stock evidence for the Smart Money Movement screen. Choosing by re-running until a
   number improves is contract-fitting and the frozen hashes exist to prevent it.
