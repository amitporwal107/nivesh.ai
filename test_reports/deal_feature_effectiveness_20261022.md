# Deal-feature effectiveness diagnosis — why the Study C overlay changed 4 of 270 slots

**Date:** 2026-10-22
**Scope:** read-only diagnosis of the paired runs B = `4faf3eaa-2b3f-4bbc-af4b-2fca627830bf`
(`NIDP-SM-VALIDATION-001`) vs C = `9c0eb9f6-be16-41e9-bbcd-b83ba7e0f82f`
(`NIDP-SM-VALIDATION-002`), both at commit `b4d521e555a468fe2ffa1b7f8cc18f3516fbba9d`,
stage `exploratory`, data_cutoff 2026-10-22.
**Nothing was changed.** No repo file other than this report, no DB write, no re-run, no change to
either frozen contract.
**Database:** `nidp_staging` via `~/.config/nivesh/nidp-psql.sh`. All numbers below are real query
output obtained this session.

---

## 0. The result being explained (reproduced from the DB, not from the brief)

```
 scoring_date | n_b | n_c | b_net_pct | c_net_pct | diff_pp
--------------+-----+-----+-----------+-----------+---------
 2026-01-12   |  30 |  30 |    2.1285 |    2.1285 |  0.0000
 2026-02-12   |  30 |  30 |   -4.0916 |   -4.0916 |  0.0000
 2026-03-12   |  30 |  30 |    1.0193 |    2.0895 |  1.0702
 2026-04-13   |  30 |  30 |    3.3758 |    4.1936 |  0.8177
 2026-05-12   |  30 |  30 |    5.1645 |    5.1645 |  0.0000
 2026-06-12   |  30 |  30 |    1.2815 |    1.2815 |  0.0000
 2026-07-13   |  30 |  30 |    0.5619 |    0.5619 |  0.0000
 2026-08-12   |  30 |  30 |    1.6978 |    1.7802 |  0.0824
 2026-09-15   |  30 |  30 |    1.4181 |    1.4181 |  0.0000
```

Six of nine differences are exactly `0.0000` because on those six dates the top-30 membership of B
and C is **identical** — not because the returns coincided. `(1.0702 + 0.8177 + 0.0824) / 9 =
0.21892` pp, which reconciles with the established headline of +0.2189 pp.

The four slots that changed, with both sides of each swap:

```
 scoring_date |  symbol   | score_b | rank_b | dtilt  | score_c | rank_c |   direction
--------------+-----------+---------+--------+--------+---------+--------+----------------
 2026-03-12   | BAJAJCON  |  56.013 |     38 | 0.8000 |  56.813 |     29 | ENTERED C
 2026-03-12   | PETRONET  |  56.758 |     30 | 0.0000 |  56.758 |     31 | DROPPED from B
 2026-04-13   | CPPLUS    |  58.302 |     31 | 1.3340 |  59.636 |     22 | ENTERED C
 2026-04-13   | POWERGRID |  58.572 |     30 | 0.0000 |  58.572 |     31 | DROPPED from B
 2026-08-12   | ANTHEM    |  59.754 |     64 | 3.6520 |  63.406 |     19 | ENTERED C
 2026-08-12   | EMCURE    |  60.531 |     52 | 3.2000 |  63.731 |     13 | ENTERED C
 2026-08-12   | HAL       |  62.054 |     29 | 0.0000 |  62.054 |     31 | DROPPED from B
 2026-08-12   | PETRONET  |  62.019 |     30 | 0.0000 |  62.019 |     32 | DROPPED from B
```

Note immediately: **every promoted name begins A–E; every displaced name begins H–P and received a
tilt of exactly zero.** The displaced names were not judged worse by the overlay — they were pushed
out passively. Section 1 explains why that pattern is structural rather than coincidental.

---

## 1. The funnel — where the signal dies

A slot can only change if **all** of these hold for some symbol: the feed was queried for it → a
deal row exists in the lookback window → the row survives transfer netting → the net direction is
non-zero → the resulting tilt is big enough to cross the rank-30 cut.

### 1a. Aggregate over all 9 formation dates

| Stage | n | % of eligible | attrition at this stage |
|---|---|---|---|
| **S0** eligible symbol-dates (B ∩ C, identical by construction) | **6,873** | 100 % | — |
| **S1** symbol was *ever queried* for deals by the ingest | **1,910** | 27.8 % | **−72.2 pp** |
| **S2** has ≥1 deal row in the 90-day window `[d−90, d)` | **498** | 7.2 % | −20.5 pp |
| **S3** survives transfer netting (`buying_clients + selling_clients > 0`) | **363** | 5.3 % | −2.0 pp |
| **S4** net direction non-zero (`buying_clients ≠ selling_clients`) | **183** | 2.7 % | −2.6 pp |
| **S5** non-zero deal tilt actually applied | **183** | 2.7 % | 0 |
| **S6** symbol's own tilt ≥ its distance to the rank-30 cut | **13** | 0.19 % | −2.5 pp |
| **S7** top-30 slots that actually changed | **4** | 0.058 % | — |

S4 ≡ S5 exactly: every symbol-date with a non-zero direction got a non-zero tilt, and no other did.
The tilt function is faithful to its inputs; the inputs are what is missing.

### 1b. Per formation date

| Formation date | S0 eligible | S1 feed queried | S2 any deal row | S3 survives netting | S5 non-zero tilt | S6 reachable | S7 slots changed | paired diff (pp) |
|---|---|---|---|---|---|---|---|---|
| 2026-01-12 | 650 | 187 | 71 | 46 | 27 | 1 | 0 | 0.0000 |
| 2026-02-12 | 704 | 196 | 55 | 38 | 22 | 1 | 0 | 0.0000 |
| 2026-03-12 | 681 | 194 | 40 | 28 | 11 | 1 | 1 | +1.0702 |
| 2026-04-13 | 784 | 223 | 56 | 38 | 18 | 2 | 1 | +0.8177 |
| 2026-05-12 | 797 | 219 | 58 | 41 | 16 | 1 | 0 | 0.0000 |
| 2026-06-12 | 801 | 217 | 49 | 38 | 15 | 1 | 0 | 0.0000 |
| 2026-07-13 | 827 | 226 | 55 | 44 | 19 | 0 | 0 | 0.0000 |
| 2026-08-12 | 798 | 219 | 50 | 36 | 19 | 3 | 2 | +0.0824 |
| 2026-09-15 | 831 | 229 | 64 | 54 | 36 | 3 | 0 | 0.0000 |

"Reachable" (S6) = `abs(score_b − score_at_rank_30) ≤ abs(own deal tilt)`. S7 is
`count(*) FILTER (WHERE (rank_b<=30) <> (rank_c<=30)) / 2` — each change counts one entrant and one
exit, so the raw flip count was 8 and the slot count is 4.

### 1c. The bottleneck

**S1 is the bottleneck, by a wide margin, and it is an ingest-coverage defect, not a market fact.**

`nidp.trendlyne_deals` holds 19,787 legs across **328 symbols**. Every one of them begins with a
digit or **A–G**:

```
 first_char | symbols | legs
------------+---------+------
 3          |       2 |   98
 6          |       1 |  197
 A          |      97 | 5562
 B          |      48 | 3587
 C          |      63 | 3660
 D          |      26 | 1738
 E          |      31 | 1550
 F          |      15 |  870
 G          |      45 | 2525
(9 rows)

 symbols_outside_a_to_g
------------------------
                      0
```

The cause is in `backend/nidp/services/trendlyne_ownership/deals.py`. `_symbols()` returns the
candidate list `ORDER BY 1` — alphabetically — and `run()` breaks when the `CallBudget` is spent,
logging "re-run to continue (progress is resumable)". It was never re-run. The candidate list is
984 symbols; the job log shows the entire history was pulled in three short runs on 2026-10-22 and
consumed **341 calls**:

```
ingester      | trendlyne_deals     status | OK
metadata_head | {"errors": 0, "calls_used": 40,  "budget_limit": 45,  "rows_written": 2022,  "symbols_attempted": 40,  "symbols_with_deals": 38}
ingester      | trendlyne_deals     status | OK
metadata_head | {"errors": 0, "calls_used": 300, "budget_limit": 310, "rows_written": 18786, "symbols_attempted": 300, "symbols_with_deals": 290}
```

(plus one 1-call run that found nothing, and one earlier run that failed with a vendor 403 before
writing anything).

Confirmed against the candidate ordering:

```
 candidates | fetched | first_unfetched_position | last_fetched_position
------------+---------+--------------------------+-----------------------
        984 |     328 |                       16 |                   338
```

So **643 of 984 candidate symbols (65 %) were never queried once.** At formation-date level that is
71–73 % of the eligible universe. Spot check of candidate positions 495–512 — `KPITTECH`,
`KTKBANK`, `LALPATHLAB`, `LATENTVIEW`, … — all `fetched = f`.

**This is precisely the "missing evidence is not a zero signal" trap, and it is the heart of the
answer.** For 4,963 of the 6,873 eligible symbol-dates, `deals.get(sym, {})` returns `{}`,
`_deal_tilt` returns `0.0`, and the overlay is silent — but the correct statement about those names
is *"unknown: never asked"*, not *"no institutional interest"*. The evaluator cannot tell the two
apart, and nothing in the persisted prediction rows records the difference. Within the 28 % that
*was* queried, the hit rate is 3–4× higher than the headline coverage suggests:

| Formation date | queried universe | non-zero tilt | % of **queried** | % of **eligible** |
|---|---|---|---|---|
| 2026-01-12 | 187 | 27 | 14.4 | 4.2 |
| 2026-02-12 | 196 | 22 | 11.2 | 3.1 |
| 2026-03-12 | 194 | 11 | 5.7 | 1.6 |
| 2026-04-13 | 223 | 18 | 8.1 | 2.3 |
| 2026-05-12 | 219 | 16 | 7.3 | 2.0 |
| 2026-06-12 | 217 | 15 | 6.9 | 1.9 |
| 2026-07-13 | 226 | 19 | 8.4 | 2.3 |
| 2026-08-12 | 219 | 19 | 8.7 | 2.4 |
| 2026-09-15 | 229 | 36 | 15.7 | 4.3 |

The brief's "only ~42 Nifty-500 names have any deal in a 3-month window" is therefore **a measure of
how far the ingest got, not of how many Indian large/mid-caps had a bulk or block deal.** It is a
coverage statistic wearing a conviction statistic's clothes.

**Secondary bottleneck: S6.** Even for the 183 symbol-dates that do receive a tilt, the median
baseline rank is deep in the tail, so the tilt lands nowhere near the cut:

```
 scoring_date | deepest_rank_liftable_by_1p2 | by_2p4 | by_4p0 | best_tilted_rank | median_tilted_rank | tilted_in_top60
--------------+------------------------------+--------+--------+------------------+--------------------+-----------------
 2026-01-12   |                           46 |     69 |    105 |               20 |                256 |               3
 2026-02-12   |                           44 |     62 |    102 |               27 |                265 |               2
 2026-03-12   |                           42 |     61 |    112 |               38 |                170 |               1
 2026-04-13   |                           43 |     68 |    116 |               25 |                296 |               4
 2026-05-12   |                           45 |     76 |    144 |                5 |                304 |               2
 2026-06-12   |                           64 |     82 |    121 |               11 |                231 |               3
 2026-07-13   |                           44 |     77 |    130 |                4 |                220 |               3
 2026-08-12   |                           45 |     67 |    114 |                2 |                432 |               3
 2026-09-15   |                           51 |     82 |    125 |                1 |                325 |               5
```

Only **1–5 tilted symbols per date sit inside the baseline top 60 at all.** With 11–36 tilted names
drawn from a 650–831 universe, the chance that one lands in the ~100-name contestable band is small
— and the draw is not random, it is confined to the A–G alphabetical block.

---

## 2. Input-validity checks

### 2.1 Point-in-time availability — **CORRECT, and conservative. No defect.**

`_DEALS_SQL` filters `deal_date < $1 AND deal_date >= $1 - $2::int`. Strict `<`, so a deal traded on
the formation date is never used.

`deal_date` is the **trade** date. `backend/nidp/migrations/176_trendlyne_deals.sql` declares it
(`deal_date DATE NOT NULL, -- trade date`) and documents the rule under a `POINT-IN-TIME` heading:
*"Exchanges publish these after the close, so a strategy scoring on date D may only use deals with
deal_date < D — never deal_date = D. The feed gives no publication timestamp, so that strict
inequality is the conservative rule and it is enforced in the feature view rather than left to each
caller."*

Measured corroboration that the field follows the trading calendar (so it is a trade date, not a
disclosure/filing date): restricted to the span `nidp.prices_eod` actually covers (2025-09-30 →
2026-10-21, 260 sessions),

```
 deal_symbol_days_in_price_coverage | on_a_trading_session | not_a_trading_session | on_a_weekend
------------------------------------+----------------------+-----------------------+--------------
                                623 |                  619 |                     4 |            4
```

619 of 623 land exactly on a session, and the only 4 misses are the 4 weekend dates. Across the
whole 2006-2026 feed, 10 of 6,109 symbol-days fall on a weekend (0.16 %) — vendor noise, not a
systematic date-field problem.

And no leak is present in what was consumed:

```
 deal_rows_in_any_study_window | rows_on_or_after_formation_date
-------------------------------+---------------------------------
                          1212 |                               0
```

Two caveats, neither of which suppresses the overlay:

- **Backfill provenance.** `min(retrieved_at) = 2026-10-22 04:05:57`, `max = 2026-10-22 04:10:01` —
  the whole history arrived in one 4-minute window. There is no as-known-at capture; the PIT claim
  rests on the exchange disclosure convention rather than on our own observation log. Defensible
  for this feed (exchange bulk/block disclosures are not revised), but it is an assumption, not a
  measurement.
- **The vendor's 200-row cap is a retrospective filter**, so for a heavily dealt symbol the
  *earliest* formation dates could in principle have had deals truncated away by later ones. It
  barely binds: 9 of 328 symbols hold ≥200 rows, `max = 201`. Immaterial.

### 2.2 Transfer netting — **behaving as intended. Minor over-reach, not the cause.**

`v_trendlyne_deals_net` flags a leg `offsetting_pair` when an `EXISTS` subquery finds any leg with
the same `(symbol, deal_date, quantity, price)` and the opposite `action`. Because it is `EXISTS`
rather than a 1:1 assignment, an unbalanced N:M group has *all* its legs zeroed, including the
genuine excess. Measured:

```
 groups_with_both_actions | balanced_1to1 | unbalanced_overcancelled | excess_legs_wrongly_zeroed
--------------------------+---------------+--------------------------+----------------------------
                     3394 |          3322 |                       72 |                        145
```

97.9 % of pairing groups are exactly balanced (true transfers). The over-cancellation touches 72
groups and 145 excess legs — **0.7 % of 19,787 legs.** Not a driver.

Exchange double-reporting is also immaterial: 18 of 19,769 distinct legs appear on both NSE and BSE.

What netting *does* remove at scale is intended: of the 498 window-symbol-dates with a deal row,
**135 (27 %) are entirely pure-transfer days** and correctly contribute nothing. That is the
documented HAL/Goldman ODI case working as designed.

### 2.3 Direction and sign — **sign is correct. Magnitude is asymmetric, and quantity is discarded.**

Sign, verified end-to-end against the realised tilts:

```
       side       |  n  | tilt_pos | tilt_neg | tilt_zero | netqty_pos | netqty_neg
------------------+-----+----------+----------+-----------+------------+------------
 balanced         | 180 |        0 |        0 |       180 |         52 |         72
 net_buy_clients  | 120 |      120 |        0 |         0 |         62 |         26
 net_sell_clients |  63 |        0 |       63 |         0 |          2 |         59
```

120/120 net-buy → positive tilt, 63/63 net-sell → negative tilt. **No sign inversion.** The tilt is
added as `b_score + mf_tilt + d_tilt`, right way round.

Three real problems in the magnitude, all in `_deal_tilt`:

**(i) The confidence multiplier keys only on the buy side.**
```python
confidence = 1.0 if buy >= 3 else (0.6 if buy == 2 else 0.3)
```
A sell-only symbol has `buy = 0`, so confidence is forced to 0.3 *because it has no buyers*, which
is the very fact that makes the signal bearish. The only way to reach `|direction| = 1` on the sell
side is `buy_cl = 0`, which caps the tilt at −1.2. Measured over the whole study:

```
             cohort              |  n  | min_tilt | max_tilt
---------------------------------+-----+----------+----------
 buy_cl = 0 (conf forced to 0.3) |  46 |  -1.2000 |  -1.2000
 buy_cl >= 1                     | 317 |  -0.8000 |   3.6522
```

All 46 of those symbol-dates got **exactly −1.2**. Across all 9 dates and 6,873 symbol-dates, the
realised tilt range is **[−1.2000, +3.6530]** against a configured bound of ±4.0 — the negative
side is effectively capped at 30 % of the positive side. Study 002's contract asks for damping of a
"single-client signal"; the code damps a *single-buyer* signal, which is not the same thing. This is
an implementation defect, though it is not what caused the 4-of-270 (it biases the overlay long, it
does not silence it).

**(ii) Equal client counts zero the signal, and market makers make them equal.** 180 of the 363
symbol-dates that survive netting have `buying_clients == selling_clients`, so
`direction = (buy − sell)/(buy + sell) = 0`. That is **49.6 % of all surviving deal evidence
discarded.** In 124 of those 180 cases `net_qty` was non-zero (52 positive, 72 negative) — a
directional signal that was present in the loaded row and thrown away.

**(iii) `_DEALS_SQL` loads `net_qty` and `active_days`, and `_deal_tilt` never reads either.** Only
`buying_clients` / `selling_clients` are used. Measured against `deal_feature_rules.features` in the
frozen 002 contract, **4 of the 6 registered features are unimplemented**: "deal intensity vs
turnover and free float", "net disclosed flow excluding transfers", "repeat buying by the same
client and by independent clients over fixed lookbacks", "deal price vs market price", and "block vs
bulk split". Only "distinct buying clients" and (as a sign) net direction are live. The overlay as
run is a *breadth-of-counterparty-count* feature, materially narrower than the feature that was
preregistered.

### 2.4 Entity classification — **absent. Nothing classifies a counterparty, and it is material.**

`nidp.trendlyne_deals` columns: `symbol, deal_date, client_name, deal_type, action, quantity, price,
traded_percent, exchange, source, retrieved_at, source_run_id`. There is **no category / class /
entity-type column anywhere in the deal path**, and `_deal_tilt` counts every one of the 4,048
distinct `client_name` values identically. A promoter exiting, an index ETF rebalancing, and a
long-only FPI building a position are the same "1 client" to this feature.

That is not a theoretical concern here. The top counterparties by leg count are overwhelmingly
proprietary / market-making desks and index vehicles, not investors:

```
                client_name                 |  n
--------------------------------------------+------
 GRAVITON RESEARCH CAPITAL LLP              | 1510
 ISHARES CORE MSCI EMERGING MARKETS ETF     |  674
 ISHARES CORE EMERGING MARKETS MAURITIUS CO |  672
 HRTI PRIVATE LIMITED                       |  502
 NK SECURITIES RESEARCH PRIVATE LIMITED     |  386
 ISHARES INDIA SC MAURITIUS COMPANY         |  364
 ISHARES MSCI INDIA SMALL-CAP ETF           |  364
 JUNOMONETA FINSOL PRIVATE LIMITED          |  274
 QE SECURITIES LLP                          |  274
 SOCIETE GENERALE                           |  199
 IRAGE BROKING SERVICES LLP                 |  188
 MICROCURVES TRADING PRIVATE LIMITED        |  188
```

Bucketing by a conservative name pattern:

```
      bucket       | legs_total | legs_surviving_netting | distinct_names | pct_of_surviving
-------------------+------------+------------------------+----------------+------------------
 other             |      12741 |                   8805 |           3962 |             68.6
 prop_market_maker |       3914 |                   3903 |             19 |             30.4
 index_etf         |       3132 |                    136 |             67 |              1.1
```

**30.4 % of the one-sided flow the feature counts comes from 19 prop/market-making names**, and
99.7 % of their legs survive netting (they do not leave exact qty+price mirrors, so the transfer
filter does not catch them). Index-ETF legs, by contrast, net out almost completely (136 of 3,132
survive) — the transfer filter handles them well.

And this is the mechanism behind §2.3(ii): **3,390 of 8,815 surviving client-symbol-days (38.5 %)
have the same client on both the buy and the sell side**, incrementing `buying_clients` *and*
`selling_clients` and driving `direction` to zero. Market-maker round-tripping is cancelling the
feature out from the inside.

The repo already contains a counterparty classifier
(`backend/nidp/services/daas_api/flow_ledger.py`, FPI-house list and
`_is_fpi_portfolio_investor`) and `nidp.insider_sast` carries a `client_category`. Neither is wired
into the deal feature — grep for `flow_ledger|_is_fpi` across `smart_money_study/` and
`trendlyne_ownership/` returns nothing.

### 2.5 Join integrity (not asked, checked anyway) — **clean.**

```
 feed_symbols | matched_in_study_universe | feed_symbols_not_in_universe
--------------+---------------------------+------------------------------
          328 |                       325 |                            3
```

The three misses are `ARCIL`, `ELEVATE`, `GSPLTRANS` — names that never entered the study's
considered set. The symbol join is not losing signal. `backend/nidp/services/smart_money_scores/service.py`
contains no reference to deals/bulk/block, so the MF-holdings component and the deal overlay are
cleanly separated and there is no double counting.

---

## 3. Is the tilt too small? No — it is very large relative to the score spread

This is the arithmetic the question asks for. Baseline-B score gaps around the rank-30 boundary:

| Formation date | score @1 | score @30 | score @31 | gap 30→31 | gap 30→35 | gap 30→40 | gap 30→50 | names within ±4.0 of cut | …of which tilted |
|---|---|---|---|---|---|---|---|---|---|
| 2026-01-12 | 66.94 | 57.96 | 57.92 | **0.035** | 0.395 | 0.725 | 1.517 | 98 | 5 |
| 2026-02-12 | 70.22 | 58.12 | 58.11 | **0.013** | 0.326 | 0.740 | 1.498 | 96 | 4 |
| 2026-03-12 | 66.56 | 56.76 | 56.74 | **0.018** | 0.616 | 0.911 | 1.676 | 105 | 1 |
| 2026-04-13 | 67.23 | 58.57 | 58.30 | **0.270** | 0.969 | 1.010 | 1.742 | 110 | 5 |
| 2026-05-12 | 65.97 | 58.12 | 58.06 | **0.060** | 0.297 | 0.690 | 1.344 | 140 | 4 |
| 2026-06-12 | 65.99 | 58.68 | 58.68 | **0.003** | 0.218 | 0.376 | 0.742 | 116 | 6 |
| 2026-07-13 | 68.98 | 59.10 | 59.03 | **0.069** | 0.469 | 0.828 | 1.432 | 128 | 5 |
| 2026-08-12 | 68.99 | 62.02 | 61.81 | **0.206** | 0.505 | 0.841 | 1.372 | 110 | 3 |
| 2026-09-15 | 66.63 | 60.58 | 60.44 | **0.144** | 0.449 | 0.560 | 1.130 | 122 | 6 |

The entire rank-30-to-rank-50 score gap is **0.74 to 1.74 points**. The rank-30-to-31 gap is
**0.003 to 0.270 points**. The configured `max_deal_tilt` is **4.0**.

- `+1.2` — the single most common non-zero tilt (32 symbol-dates) — is **4.4× to 400× the 30/31
  gap**, and lifts a name from as deep as **rank 42–64** into the top 30.
- `+2.4` reaches from **rank 61–82**.
- `+4.0` reaches from **rank 102–144** — i.e. a full-confidence tilt would promote almost any name
  in the top sixth of the universe.

Observed, not hypothetical: `ANTHEM` moved **rank 64 → 19** on a +3.652 tilt (45 places);
`EMCURE` **52 → 13** on +3.200; `CPPLUS` **31 → 22** on +1.334; `BAJAJCON` **38 → 29** on +0.800.

**Explanation (b) — "the tilt magnitude is too small" — is decisively ruled out.** If anything the
calibration runs the other way: a ±4.0 tilt against a 0.003–0.27 point boundary gap means a single
disclosed deal with three distinct buyers overwhelms the baseline score's entire ordering of ~100
names. That is a live calibration risk for any future promotion decision, and it is masked today
only because the feature almost never fires. Of the 96–140 names sitting in the ±4.0 contestable
band each month, only **1–6** had a non-zero tilt — and that ratio, not the tilt size, is what
produced 4 of 270.

---

## 4. Conclusion

**The overlay is inert because of (c) an implementation defect — specifically an ingest-coverage
defect — compounded by (a) sparsity within the part of the universe that was measured. (b) is ruled
out. (d) is untested: this study contains no evidence either way about whether the signal exists.**

In order of contribution:

1. **Coverage defect (dominant, ~72 pp of the attrition).** `trendlyne_deals.run()` walks an
   alphabetically-ordered 984-symbol candidate list and stops when its `CallBudget` is spent. It
   consumed 341 calls on 2026-10-22 and was never resumed. The resulting table holds only symbols
   beginning `0-9` or `A-G` — **zero symbols outside A-G, verified.** For 4,963 of 6,873 eligible
   symbol-dates the deal feature is structurally silent, and the evaluator records that silence as
   identical to "no deal occurred". All four names the overlay promoted begin A–E; all four it
   displaced begin H–P and were incapable of receiving a tilt. **This is exactly the
   missing-evidence-as-zero-signal failure the question warned about: the feature as run is
   measuring alphabetical ingest progress at least as much as it is measuring institutional
   conviction.**
2. **Signal destruction inside the implemented feature (~5 pp).** Of the 498 window-symbol-dates
   that do have evidence, 135 are pure transfers (intended) and a further 180 have
   `buying_clients == selling_clients` and score exactly zero — 49.6 % of surviving evidence
   discarded, driven by the 38.5 % of client-symbol-days where the same counterparty is on both
   sides. Because no counterparty classification exists, 30.4 % of the surviving flow is
   prop/market-making activity that carries no directional conviction and is doing most of that
   cancelling. `net_qty` is loaded and never used.
3. **Placement (~2.5 pp).** The 183 tilted symbol-dates sit at median baseline rank 170–432; only
   1–5 per date are inside the baseline top 60.

**Defect verdicts on the four input checks:**

| Check | Verdict |
|---|---|
| Point-in-time | **Not defective.** `deal_date` is the trade date, confirmed against the trading calendar (619/623, the 4 misses being the 4 weekend dates); `deal_date < d` is strict; 0 of 1,212 consumed rows fall on/after a formation date. Conservative, no leak. Caveat: single-shot backfill, so provenance is assumed rather than logged. |
| Netting | **Not defective in substance.** 97.9 % of pairing groups are true 1:1 transfers; `EXISTS`-based over-cancellation touches 145 of 19,787 legs (0.7 %). Working as designed. |
| Direction / sign | **Sign correct (183/183). Magnitude defective.** `confidence` keys only on `buy`, so the realised range is [−1.2, +3.65] against a ±4.0 bound — all 46 sell-only symbol-dates pinned at exactly −1.2. Also, 4 of the 6 preregistered features are unimplemented and `net_qty` is discarded. |
| Entity classification | **Absent.** No category column, no classifier applied; 30.4 % of surviving flow is prop/market-making names counted as equals to long-only investors. The repo's own FPI classifier is not wired in. |

**What I cannot separate, and what would discriminate it.** (a) and (d) are not distinguishable from
this run. 183 non-zero tilts producing 3 effective paired events is not a sample about market
efficiency; it is a sample about ingest completeness. The one thing that would separate them is
**finishing the data collection and re-running the identical frozen configuration** — 643 more
symbol calls against the same candidate list, no parameter change, no feature change. If coverage
reaches ~100 % and the per-date tilted count rises from 11–36 to a projected ~40–130 (scaling the
8–16 % queried-cohort hit rate to the full 650–831 universe — **an estimate, not a measurement**),
then slots will change on most dates and the paired difference becomes an actual test of (d). If the
difference remains ~0 with full coverage, (d) is supported.

**No configuration change is proposed and none should be made here.** Fixing items 2 and 3 above
(entity classification, quantity weighting, symmetric confidence, the four unimplemented features)
would change the registered feature's design and therefore requires a **new `study_id` with a fresh
holdout** before any outcome is inspected — 002's own `failure_policy` says so, and outcomes have
already been inspected.

**What a human should decide next** (three distinct decisions, in order):

1. **Resume the ingest** — `python -m nidp.services.trendlyne_ownership.deals` for the remaining
   643 candidate symbols, and put it on a schedule. This is a data-completeness repair, not a study
   change. Separately, change `_symbols()` ordering or add a progress marker so a budget break
   cannot again produce an alphabetically-biased universe; that is a code fix needing its own
   review.
2. **Rule on the re-run's status.** Re-running the same frozen config on completed data is the only
   way to learn anything, but the 4-of-270 outcome has been seen. Whether that re-run is reported
   as a continuation of this `exploratory` run or requires a fresh `confirmatory` holdout is a
   preregistration call the study owner must make — I am not making it.
3. **Treat the ±4.0 tilt calibration as an open risk,** not a settled parameter. The arithmetic in
   §3 shows it can reorder ~100 names on one disclosed deal. It never mattered at 2.7 % coverage;
   it will matter a lot at 100 %.

---

## 5. Honesty ledger

- **VERIFIED this session** against `nidp_staging`: every table and figure above, including the
  funnel, the score gaps, the per-date diffs, the netting and exchange counts, the client
  distribution, the job log, and the symbol-join integrity. All are real `psql` output.
- **VERIFIED by reading source:** the PIT filter, `_deal_tilt`, `_DEALS_SQL`, the view definition
  (both the live `pg_get_viewdef` and migration 176), the ingest's `_symbols()`/budget logic, both
  frozen contracts. Nothing was modified.
- **UNVERIFIED — exchange disclosure timing.** I confirmed `deal_date` follows the trading calendar
  and that the code treats it as a trade date usable only from D+1, but I did not independently
  verify from an exchange source that bulk/block disclosures are published on the evening of the
  trade date. The PIT rule is conservative either way: if disclosure lagged further, the overlay
  would be *optimistic*, not inert.
- **UNVERIFIED — counterparty buckets.** The prop/market-maker and index-ETF splits in §2.4 come
  from my own name-pattern match over `client_name`, not from any classification in the data (there
  is none). The 19 matched names are well-known proprietary/market-making firms, but the 68.6 %
  "other" bucket is unclassified and certainly contains further prop desks, so 30.4 % is a **lower
  bound** on the non-conviction share.
- **ESTIMATE, clearly labelled:** the projected ~40–130 tilted names per date under full coverage
  in §4. It extrapolates the measured queried-cohort hit rate; it is not a measurement and must not
  be quoted as one.
- **Not done, deliberately:** no re-run, no parameter sweep, no edit to the evaluator or either
  frozen JSON, no DB write.
- **Concurrent edit noted.** Another session modified
  `backend/nidp/services/smart_money_study/evaluator.py` (+226/−6) while this diagnosis was in
  progress, adding `_UNEXPLAINED_MOVE_SQL` return-integrity checks and `_BENCHMARK_SQL`. Verified
  by diff that it touches **no** line of `_DEALS_SQL`, `_deal_tilt`, `buying_clients`,
  `selling_clients`, `confidence`, `max_deal_tilt` or `deal_date`; the deal path analysed above is
  byte-identical to the working tree. The two runs analysed here were produced at commit
  `b4d521e5`, before that edit, so the run results are unaffected by it.

---

*Gate line below refers to this diagnosis being complete and fully evidenced against the live
staging warehouse. It is **not** a verdict on the overlay, which is diagnosed above as inert for
implementation reasons.*

## Verdict: PASS
