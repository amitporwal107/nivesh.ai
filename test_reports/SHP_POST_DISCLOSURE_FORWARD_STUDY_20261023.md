# NIDP-SHP-FWD-001 — Post-disclosure forward returns by institutional ownership change

**Date** 2026-10-23 · **Branch** `study/post-disclosure-forward-returns` (from `feat/provider-foundations`)
**Stage** exploratory · **Pre-registration SHA-256** `5452b0551ab57ff68ba365963eae4d0490ee250c0d4322c9f5218d0734ec7071`
**Environment** `nidp_staging` warehouse, read-only, via `~/.config/nivesh/nidp-psql.sh`

> **RESEARCH ARTIFACT. NOT A PRODUCT FEATURE.** Nothing in this report is promoted to any score.
> `nidp.v3_stock_scores_daily` is untouched. The frozen promotion criteria remain authoritative.

## Verdict: INCONCLUSIVE

**At the primary horizon (20 sessions), the increased-minus-reduced spread is +1.0749 pp with a
95% date-block CI of [−0.8673, +2.9054] pp against a +1.00 pp hurdle, over 10 formation quarters
against a review floor of 12.** The interval straddles zero and does not clear the hurdle.

Two independent reasons, either of which alone forces INCONCLUSIVE:

1. **The sample is below the review floor.** 10 quarterly disclosure dates against the floor of 12
   inherited from `NIDP-SM-VALIDATION-001`. This was declared in the pre-registration *before any
   result was computed*, so a POSITIVE verdict was unreachable by construction.
2. **The sign is not robust to the specification.** The same 20-session spread is **+1.07 pp** on
   Δ(FII+DII), **−0.47 pp** on ΔFII alone, and **+1.28 pp** on threshold-free terciles. Three
   reasonable readings of "institutional ownership change" produce two signs and a spread of
   movement comparable to the hurdle itself. That is the signature of noise, not of a small effect
   measured imprecisely.

A clean negative is *also* not available: no interval at the primary horizon excludes zero. The
honest statement is that **this warehouse cannot currently answer the question either way**, and
the binding constraint is the data, not the method.

---

## 1. The question, and why the obvious version of it is untradeable

Quarterly shareholding for Jul–Sep is disclosed in late October. By then the same-quarter price
move is history: it explains the past and cannot be traded. The only tradeable question is what
happens in the sessions **after** the disclosure becomes public. This study measures forward
returns at 5, 20 and 60 sessions from the first session on which the filing could have been acted
on, for stocks grouped by institutional ownership change (increased / flat / reduced).

## 2. The availability timestamp — the decision that governs everything else

### 2.1 What the warehouse actually has

`nidp.shareholding_pattern` carries three candidate timestamps. Real output:

```
 period_end |   source    | rows | fii_rows | bcast_rows |         min_bcast         |         max_bcast         |             min_ing              |             max_ing
------------+-------------+------+----------+------------+---------------------------+---------------------------+----------------------------------+----------------------------------
 2026-09-30 | NSE_SHP     | 1996 |     1740 |       1996 | 2026-10-01 18:15:18+05:30 | 2026-10-22 16:44:35+05:30 | 2026-10-13 22:00:40.855092+05:30 | 2026-10-23 01:04:03.397275+05:30
 2026-09-30 | screener_in |  160 |      155 |          0 |                           |                           | 2026-10-12 20:30:28.595452+05:30 | 2026-10-22 20:31:43.914619+05:30
 2026-06-30 | NSE_SHP     | 1117 |        0 |          0 |                           |                           | 2026-10-13 09:12:46.745315+05:30 | 2026-10-13 09:12:46.745315+05:30
 2026-06-30 | screener_in |  208 |      202 |          0 |                           |                           | 2026-10-12 20:30:08.030959+05:30 | 2026-10-22 20:31:43.911919+05:30
 2026-03-31 | NSE_SHP     |   22 |        0 |          0 |                           |                           | 2026-10-13 09:12:46.745315+05:30 | 2026-10-13 09:12:46.745315+05:30
 2026-03-31 | screener_in |  207 |      202 |          0 |                           |                           | 2026-10-12 20:30:08.028665+05:30 | 2026-10-22 20:31:43.906805+05:30
 2025-12-31 | screener_in |  204 |      199 |          0 |                           |                           | 2026-10-12 20:30:08.026366+05:30 | 2026-10-22 20:31:43.898444+05:30
 2025-09-30 | screener_in |  200 |      195 |          0 |                           |                           | 2026-10-12 20:30:08.023877+05:30 | 2026-10-22 20:31:43.892444+05:30
 ...
```
*(44 rows; the tail continues back to 2012 at 1–5 rows per quarter.)*

**`broadcast_at` is a genuine NSE publication timestamp — and it exists for exactly one quarter.**
Its authenticity is corroborated independently: the XBRL filename embeds the same instant.

```
   symbol   | period_end |       broadcast_at        |                                        url
------------+------------+---------------------------+------------------------------------------------------------------------------------
 CENTEXT    | 2026-09-30 | 2026-10-01 18:15:18+05:30 | https://nsearchives.nseindia.com/corporate/xbrl/SHP_1732295_01102026061509_WEB.xml
 MONEYVIEW  | 2026-09-30 | 2026-10-01 18:51:21+05:30 | https://nsearchives.nseindia.com/corporate/xbrl/SHP_1731922_01102026015706_WEB.xml
 CGCL       | 2026-09-30 | 2026-10-01 20:23:22+05:30 | https://nsearchives.nseindia.com/corporate/xbrl/SHP_1732514_01102026082308_WEB.xml
 CANBK      | 2026-09-30 | 2026-10-03 16:29:24+05:30 | https://nsearchives.nseindia.com/corporate/xbrl/SHP_1732749_03102026042915_WEB.xml
 ADANIGREEN | 2026-09-30 | 2026-10-03 17:47:01+05:30 | https://nsearchives.nseindia.com/corporate/xbrl/SHP_1732768_03102026054652_WEB.xml
```
`SHP_1732295_01102026061509` → 01/10/2026 06:15:09 PM, nine seconds before the recorded
`broadcast_at` of 18:15:18. This is NSE's own timestamp, not ours.

### 2.2 Why each candidate was accepted or rejected

| Candidate | Decision | Reason |
|---|---|---|
| `broadcast_at` | **Rejected — unusable, not untrustworthy** | The gold standard, but populated for `period_end = 2026-09-30` only. That quarter has **zero** forward trading sessions as of 2026-10-23 (see §3.2), so it cannot be studied at any horizon. |
| `ingested_at` | **Rejected** | For every earlier quarter it falls in 2026-10-12…2026-10-23 — an October-2026 backfill. It is a valid *upper* bound on availability (never earlier than real publication), so it is not a look-ahead risk; it is simply useless. Entry would land after the last available price session for every historical quarter, leaving no forward window at all. |
| `period_end` | **Rejected** | The measurement date, not the availability date. Using it is the exact bias this study exists to avoid. |
| **statutory deadline + margin** | **ADOPTED** | See below. |

### 2.3 The rule used, and its empirical justification

> **Availability = `period_end + 25` calendar days. Entry = `adj_open` of the first trading
> session STRICTLY AFTER that date.**

**Statutory basis.** SEBI (LODR) Regulations 2015, Reg 31(1)(b): the shareholding pattern must be
filed with the exchange within **21 days** of quarter end.

**Empirical validation** against the one quarter where real timestamps exist. Real output:

```
=== 2026-09-30 NSE_SHP broadcast lag distribution (days after period_end) ===
 lag_days | rows | with_fii
----------+------+----------
        1 |    3 |        3
        3 |    3 |        3
        5 |   11 |       10
        6 |   40 |       30
        7 |   62 |       53
        8 |   91 |       82
        9 |  114 |       95
       10 |   43 |       35
       11 |    3 |        3
       12 |  138 |      119
       13 |  128 |      109
       14 |  131 |      106
       15 |  237 |      217
       16 |  308 |      277
       17 |   56 |       43
       19 |  188 |      167
       20 |   88 |       76
       21 |  344 |      304
       22 |    8 |        8

 total | by_d21 | pct_by_d21 | by_d22 | max_lag | median_lag
-------+--------+------------+--------+---------+------------
  1740 |   1732 |      99.54 |   1740 |      22 |         16
```

Median lag **16 days**, **99.54% filed within 21 days**, maximum observed **22 days**. The 25-day
rule clears both the statutory deadline and the observed maximum.

**Why entry is the *next* session's open, not the filing day's.** Real output:

```
 rows | after_close | during_or_before
------+-------------+------------------
 1996 |         969 |             1027
```
**969 of 1,996 broadcasts (48.5%) are timestamped after the 15:30 IST close.** Nearly half of all
filings are therefore not actionable on the filing day at all. Entering at the next session's open
is the only rule that is safe for both halves of that distribution.

**Audit of the realised entry dates.** Real output:

```
 period_end | entry_date | after_avail_date | lag_days | is_real_session
------------+------------+------------------+----------+-----------------
 2024-03-31 | 2024-04-26 | t                |       26 | t
 2024-06-30 | 2024-07-26 | t                |       26 | t
 2024-09-30 | 2024-10-28 | t                |       28 | t
 2024-12-31 | 2025-01-27 | t                |       27 | t
 2025-03-31 | 2025-04-28 | t                |       28 | t
 2025-06-30 | 2025-07-28 | t                |       28 | t
 2025-09-30 | 2025-10-27 | t                |       27 | t
 2025-12-31 | 2026-01-27 | t                |       27 | t
 2026-03-31 | 2026-04-27 | t                |       27 | t
 2026-06-30 | 2026-07-27 | t                |       27 | t

 min_lag_days | max_lag_days | entries_inside_statutory_window
--------------+--------------+---------------------------------
           26 |           28 |                               0
```

Every entry is 26–28 calendar days after quarter end: past the 21-day statutory deadline, past the
22-day observed maximum, and **zero entries fall inside the statutory filing window.**

### 2.4 The residual look-ahead exposure, stated plainly

**For all 10 usable quarters the availability date is DERIVED, not OBSERVED.** The study is
look-ahead-safe *for any filer that complied with Reg 31(1)(b), and for any filer up to 4 days
late*. A filer later than 25 days would be entered before its disclosure was public.

This cannot be resolved from the warehouse: no table holds a filing timestamp for any quarter
before 2026-09-30. `nidp.corporate_announcements` begins 2025-10-01 and contains **no**
shareholding-pattern filings (`subject ILIKE '%shareholding pattern%'` → 0 rows), and
`nidp.scanx_shareholding` is a 5-symbol pilot. The 2026-09-30 lag distribution is additionally
**right-censored** at +22/+23 days by our own ingest date, so the true size of the late-filing tail
is unobservable even for that quarter.

This is the study's principal unresolved look-ahead exposure. It is not eliminated — it is bounded
and declared.

---

## 3. Pre-registered method

Frozen in `backend/nidp/analysis/shp_post_disclosure/preregistration.json`, hashed, and re-verified
by the script before any data is read. A mismatch aborts the run.

### 3.1 Design

| Term | Value |
|---|---|
| Universe | `nidp.shareholding_pattern`, deduped `DISTINCT ON (symbol, period_end) ORDER BY symbol, period_end, (fii_pct IS NOT NULL) DESC, ingested_at DESC` |
| Primary grouping variable | Δ_inst = (`fii_pct`+`dii_pct`)@Q − (`fii_pct`+`dii_pct`)@Q−1, in pp |
| Bands | increased ≥ +0.50 pp · reduced ≤ −0.50 pp · flat between |
| Robustness variables | ΔFII alone (same bands); within-quarter terciles of Δ_inst (threshold-free) |
| Prices | `nidp.prices_eod_adjusted.adj_open`, open-to-open |
| Calendar | `nidp.prices_eod` with **`series IN ('EQ','BE')`** |
| Horizons | 5, 20 (primary), 60 sessions |
| Primary estimand | SPREAD_20 = mean r20(increased) − mean r20(reduced), equal-weighted, per quarter, then averaged across quarters |
| Uncertainty | date-block bootstrap, 5,000 resamples of **whole quarters**, 95% percentile CI, seed 20261023 |
| Hurdle | +1.00 pp · review floor 12 independent blocks |
| Costs | 0.4937% round trip per leg (from `NIDP-SM-VALIDATION-001`); the spread carries two legs = 0.9874 pp |

**The 0.50 pp band was chosen a priori** as a round number representing a materially large
single-quarter institutional swing, before any outcome was computed. Terciles are reported as a
threshold-free check precisely so the band cannot be the result.

### 3.2 Why there is no benchmark

The spread is **market-neutral by construction**: both legs occupy the same quarter and the same
window, so the market factor cancels exactly. No index is needed, and none is usable anyway:

```
=== Nifty 500 index_eod session coverage vs trading calendar, by year ===
  yr  | cal_sessions | index_sessions | pct_covered
------+--------------+----------------+-------------
 2024 |          186 |            118 |        63.4
 2025 |          248 |             63 |        25.4
 2026 |          198 |            198 |       100.0

     mn     |     mx     | max_gap_days
------------+------------+--------------
 2024-04-01 | 2026-10-22 |          375
```

`nidp.index_eod` 'Nifty 500' covers only **25.4% of 2025 sessions** with a largest gap of **375
days**, and it is a **PRICE index, not the TRI**. An index-relative return is not computable across
most of this study's window. The quarter's all-eligible cross-sectional mean is reported instead as
the in-sample reference (the `all%` column in §4).

**Sector-relative returns are not available at all**: `nidp.index_constituents` holds 4 snapshots,
all dated after every formation date.

### 3.3 Why the usable window is 10 quarters

```
 period_end | avail_date | entry_date | sessions_after_entry |   exit_5   |  exit_20   |  exit_60
------------+------------+------------+----------------------+------------+------------+------------
 2024-03-31 | 2024-04-25 | 2024-04-26 |                  614 | 2024-05-06 | 2024-05-28 | 2024-07-25
 2024-06-30 | 2024-07-25 | 2024-07-26 |                  553 | 2024-08-02 | 2024-08-26 | 2024-10-22
 2024-09-30 | 2024-10-25 | 2024-10-28 |                  489 | 2024-11-04 | 2024-11-27 | 2025-01-23
 2024-12-31 | 2025-01-25 | 2025-01-27 |                  427 | 2025-02-03 | 2025-02-24 | 2025-04-29
 2025-03-31 | 2025-04-25 | 2025-04-28 |                  368 | 2025-05-06 | 2025-05-27 | 2025-07-22
 2025-06-30 | 2025-07-25 | 2025-07-28 |                  304 | 2025-08-04 | 2025-08-26 | 2025-10-24
 2025-09-30 | 2025-10-25 | 2025-10-27 |                  243 | 2025-11-03 | 2025-11-25 | 2026-01-22
 2025-12-31 | 2026-01-25 | 2026-01-27 |                  181 | 2026-02-03 | 2026-02-24 | 2026-04-28
 2026-03-31 | 2026-04-25 | 2026-04-27 |                  122 | 2026-05-05 | 2026-05-26 | 2026-07-23
 2026-06-30 | 2026-07-25 | 2026-07-27 |                   60 | 2026-08-03 | 2026-08-24 | 2026-10-22
 2026-09-30 | 2026-10-25 |            |                      |            |            |
```

- **2026-09-30 — the only quarter with a real publication timestamp — has no entry session at
  all.** No trading session exists after 2026-10-25. It is excluded, exactly as the brief predicted.
- 2026-06-30 has **exactly 60** sessions after entry; its 60-session exit is 2026-10-22, the last
  session in the warehouse. The window is complete, with nothing to spare.
- 2023-12-31 is excluded: only 61 names have a prior quarter.
- The floor is the price calendar: `nidp.prices_eod` begins **2024-04-01**.

Names carrying `fii_pct` with a prior quarter, per quarter:

```
 period_end | names_with_fii | names_with_prior | with_prior_dii
------------+----------------+------------------+----------------
 2023-12-31 |            178 |               61 |             55
 2024-03-31 |            181 |              178 |            165
 2024-06-30 |            182 |              180 |            167
 2024-09-30 |            185 |              182 |            169
 2024-12-31 |            188 |              184 |            171
 2025-03-31 |            189 |              188 |            175
 2025-06-30 |            188 |              187 |            175
 2025-09-30 |            195 |              188 |            176
 2025-12-31 |            199 |              194 |            182
 2026-03-31 |            202 |              199 |            187
 2026-06-30 |            202 |              201 |            189
 2026-09-30 |           1766 |              192 |            178
```

The 2026-09-30 jump to 1,766 names is the NSE_SHP ingest that finally populated institutional
columns — and it is the one quarter whose forward window has not elapsed. **The thin cross-section
and the usable window are disjoint.** That is the study's central structural problem.

---

## 4. Results — real output of the full run

Command, run this session from the warehouse (not a cached extract):

```
$ python3 backend/nidp/analysis/shp_post_disclosure/study.py --out <scratch>
preregistration hash verified: 5452b0551ab57ff68ba365963eae4d0490ee250c0d4322c9f5218d0734ec7071
panel fetched from the warehouse: 1881 rows

==============================================================================
NIDP-SHP-FWD-001  -  post-disclosure forward returns
==============================================================================

Raw (quarter, symbol) pairs with a prior quarter : 1881
Eligible after screens                           : 1255

Exclusion ledger
  S2_no_entry_price                         420
  S3_below_liquidity_floor                  143
  S4_below_min_price                         47
  S2_no_exit_price                           11
  S3_insufficient_liquidity_history           3
  S5_corporate_action_artefact                2

Formation quarters : 10  (2024-03-31 .. 2026-06-30)
Review floor       : 12 independent blocks
  -> BELOW FLOOR. A POSITIVE verdict is unreachable by construction, as the contract states.

Eligible with FII+DII pair (primary) : 1248
Eligible with FII pair (robustness)  : 1255
```

### 4.1 Primary — Δ(FII+DII), bands ±0.50 pp

```
Horizon 5 sessions
  quarter     entry          n n_inc n_flat n_red     inc%    flat%     red%     all%  spread_pp
  2024-03-31  2024-04-26   100    25     57    18    +1.54    +0.47    -0.12    +0.63     +1.655
  2024-06-30  2024-07-26   105    25     61    19    +1.82    +1.22    -0.89    +0.98     +2.709
  2024-09-30  2024-10-28   107    39     54    14    +4.10    +3.61    +7.56    +4.30     -3.465
  2024-12-31  2025-01-27   106    22     70    14    -0.24    +1.22    +0.94    +0.88     -1.181
  2025-03-31  2025-04-28   112    20     76    16    +0.46    +1.20    +1.39    +1.10     -0.932
  2025-06-30  2025-07-28   112    33     67    12    -2.27    -2.18    -2.94    -2.29     +0.665
  2025-09-30  2025-10-27   140    27     93    20    +0.66    +0.89    -0.92    +0.59     +1.583
  2025-12-31  2026-01-27   149    29     91    29    +5.74    +4.45    +4.51    +4.72     +1.227
  2026-03-31  2026-04-27   158    30    107    21    +0.17    +0.85    +2.42    +0.93     -2.249
  2026-06-30  2026-07-27   159    37     87    35    +1.24    +1.32    +1.26    +1.29     -0.020

  mean spread -0.0007 pp | 95% CI [-1.1932, +1.1074] pp | blocks 10 | positive quarters 5/10 | net of 0.9874 pp costs -0.9881 pp

Horizon 20 sessions
  quarter     entry          n n_inc n_flat n_red     inc%    flat%     red%     all%  spread_pp
  2024-03-31  2024-04-26   100    25     57    18    +0.84    +1.98    -2.53    +0.88     +3.373
  2024-06-30  2024-07-26   105    25     61    19    +6.16    +3.38    +0.93    +3.60     +5.232
  2024-09-30  2024-10-28   107    39     54    14    +5.43    +1.78    +3.51    +3.34     +1.923
  2024-12-31  2025-01-27   106    22     70    14    -6.97    -5.07    -4.73    -5.42     -2.241
  2025-03-31  2025-04-28   112    20     76    16    +7.10    +6.20   +10.78    +7.01     -3.680
  2025-06-30  2025-07-28   112    33     67    12    -2.52    -1.79    -1.83    -2.01     -0.688
  2025-09-30  2025-10-27   140    27     93    20    -2.45    -2.44    -8.13    -3.26     +5.679
  2025-12-31  2026-01-27   149    29     91    29    +3.29    +3.07    +1.32    +2.77     +1.973
  2026-03-31  2026-04-27   158    30    107    21    +2.04    +1.28    +4.60    +1.86     -2.560
  2026-06-30  2026-07-27   159    37     87    35    +2.66    +2.68    +0.92    +2.29     +1.739

  mean spread +1.0749 pp | 95% CI [-0.8673, +2.9054] pp | blocks 10 | positive quarters 6/10 | net of 0.9874 pp costs +0.0875 pp
  verdict at the primary horizon: INCONCLUSIVE  -  10 formation quarters against a review floor of 12; CI [-0.8673, +2.9054] pp does not clear +1.00 pp; the interval straddles zero

Horizon 60 sessions
  quarter     entry          n n_inc n_flat n_red     inc%    flat%     red%     all%  spread_pp
  2024-03-31  2024-04-26   100    25     57    18    +7.06   +11.96    +2.31    +9.00     +4.748
  2024-06-30  2024-07-26   105    25     61    19    +3.17    -0.51    -5.57    -0.55     +8.742
  2024-09-30  2024-10-28   107    39     54    14    -0.97    -4.44    -3.06    -2.99     +2.088
  2024-12-31  2025-01-27   106    22     70    14    -4.28    -1.17    +5.30    -0.96     -9.574
  2025-03-31  2025-04-28   112    20     76    16   +13.03   +11.07   +17.56   +12.35     -4.531
  2025-06-30  2025-07-28   112    33     67    12    +6.18    +0.78    +4.04    +2.72     +2.137
  2025-09-30  2025-10-27   140    27     93    20    -2.36    -7.32   -11.84    -7.01     +9.480
  2025-12-31  2026-01-27   149    29     91    29    +7.05    +4.67   +10.01    +6.17     -2.963
  2026-03-31  2026-04-27   158    30    107    21    +6.61    +5.34   +22.26    +7.83    -15.641
  2026-06-30  2026-07-27   159    37     87    35    -3.95    -5.61    -1.99    -4.43     -1.955

  mean spread -0.7468 pp | 95% CI [-5.6316, +3.6992] pp | blocks 10 | positive quarters 5/10 | net of 0.9874 pp costs -1.7342 pp
```

### 4.2 Robustness — ΔFII alone (bands ±0.50 pp)

```
Horizon 5 sessions
  mean spread -0.6604 pp | 95% CI [-1.6177, +0.2165] pp | blocks 10 | positive quarters 5/10 | net of 0.9874 pp costs -1.6478 pp

Horizon 20 sessions
  quarter     entry          n n_inc n_flat n_red     inc%    flat%     red%     all%  spread_pp
  2024-03-31  2024-04-26   100    19     57    24    +0.52    +0.64    +1.75    +0.88     -1.234
  2024-06-30  2024-07-26   105    26     56    23    +2.95    +3.45    +4.71    +3.60     -1.754
  2024-09-30  2024-10-28   107    22     63    22    +4.07    +3.15    +3.12    +3.34     +0.944
  2024-12-31  2025-01-27   106    14     63    29    -4.99    -6.10    -4.16    -5.42     -0.831
  2025-03-31  2025-04-28   112    21     61    30    +6.36    +6.18    +9.17    +7.01     -2.806
  2025-06-30  2025-07-28   113    22     70    21    -0.63    -2.48    -2.15    -2.06     +1.517
  2025-09-30  2025-10-27   142    18     87    37    -5.08    -2.65    -4.11    -3.34     -0.975
  2025-12-31  2026-01-27   150    25     84    41    +2.76    +3.44    +1.41    +2.77     +1.348
  2026-03-31  2026-04-27   159    22     96    41    +2.31    +2.11    +0.94    +1.84     +1.375
  2026-06-30  2026-07-27   161    30     83    48    -0.15    +3.39    +2.12    +2.35     -2.271

  mean spread -0.4687 pp | 95% CI [-1.4073, +0.5148] pp | blocks 10 | positive quarters 4/10 | net of 0.9874 pp costs -1.4561 pp
  verdict at the primary horizon: INCONCLUSIVE  -  10 formation quarters against a review floor of 12; CI [-1.4073, +0.5148] pp does not clear +1.00 pp; the interval straddles zero

Horizon 60 sessions
  mean spread -2.7087 pp | 95% CI [-5.3859, -0.2438] pp | blocks 10 | positive quarters 3/10 | net of 0.9874 pp costs -3.6961 pp
```

### 4.3 Robustness — Δ(FII+DII) terciles (threshold-free)

```
Horizon  5 sessions:  mean spread +0.0615 pp | 95% CI [-0.7111, +0.8567] pp | positive quarters 5/10
Horizon 20 sessions:  mean spread +1.2752 pp | 95% CI [-0.0964, +2.5984] pp | positive quarters 6/10
Horizon 60 sessions:  mean spread +0.8248 pp | 95% CI [-1.8492, +3.5341] pp | positive quarters 5/10
  verdict at the primary horizon: INCONCLUSIVE
```

### 4.4 The result that matters most: the sign is not robust

```
Sign of the 20-session mean spread by specification:
  PRIMARY  delta(FII+DII)            +1.0749 pp   CI [-0.8673, +2.9054]  pos 6/10
  ROBUST   delta(FII) only           -0.4687 pp   CI [-1.4073, +0.5148]  pos 4/10
  ROBUST   delta(FII+DII) terciles   +1.2752 pp   CI [-0.0964, +2.5984]  pos 6/10
```

Three defensible readings of "institutional ownership change", applied to the same 10 quarters and
the same prices, produce **+1.07, −0.47 and +1.28 pp** — two signs, and a range wider than the
hurdle. Adding DII to FII flips the sign. This is the strongest single piece of evidence in the
report, and it points at noise.

**On the one interval that excludes zero.** ΔFII at 60 sessions gives [−5.3859, −0.2438] pp, which
under the frozen rule would read NEGATIVE. **It must not be read as a finding.** It is a secondary
variable at a secondary horizon, one of **nine** (3 specifications × 3 horizons) intervals computed;
no multiplicity correction was pre-registered, and at 95% confidence roughly one spurious exclusion
of zero in nine is the expected outcome. The pre-registered decision rule binds on the **primary**
estimand only, and that one straddles zero.

### 4.5 Integrity check — the returns are real

One observation verified by hand against the warehouse, independently of the script:

```
=== HAND VERIFICATION: 360ONE, 2024-03-31 quarter. Entry 2024-04-26, +5/+20/+60 sessions. ===
 as_of_date | offset_sessions |  adj_open   | raw_open  | cumulative_adj_factor | pct_vs_entry
------------+-----------------+-------------+-----------+-----------------------+--------------
 2024-04-26 |               0 |  840.000000 |  840.0000 |            1.00000000 |       0.0000
 2024-05-06 |               5 |  799.950000 |  799.9500 |            1.00000000 |      -4.7679
 2024-05-28 |              20 |  821.100000 |  821.1000 |            1.00000000 |      -2.2500
 2024-07-25 |              60 | 1010.000000 | 1010.0000 |            1.00000000 |      20.2381
 symbol | period_end | fii_pct | dii_pct | inst_pct |   source
--------+------------+---------+---------+----------+-------------
 360ONE | 2023-12-31 | 62.4800 |  8.8700 |  71.3500 | screener_in
 360ONE | 2024-03-31 | 63.2200 |  8.3400 |  71.5600 | screener_in
```
Panel row: `2024-03-31,360ONE,f,63.2200,62.4800,8.3400,8.8700,2024-04-25,2024-04-26,840.000000,799.950000,821.100000,1010.000000,...`
Matches exactly. Δ_inst = 71.56 − 71.35 = **+0.21 pp** → `flat` band (|0.21| < 0.50). Correct.

**Reproducibility.** The live warehouse run and a re-analysis of the captured panel
(`--panel-csv`) are byte-identical except for the output path (`diff` → one line, the filename).

---

## 5. Data-quality defects found, and their effect on this study

### 5.1 `prices_eod_adjusted` coverage is strongly time-dependent — the largest exclusion

`S2_no_entry_price` removed **420 of 1,881 pairs (22.3%)**, and it is not evenly spread:

```
 period_end | pairs | no_adj_open | raw_present_adj_missing | no_price_at_all
------------+-------+-------------+-------------------------+-----------------
 2024-03-31 |   178 |          66 |                      46 |              20
 2024-06-30 |   180 |          64 |                      44 |              20
 2024-09-30 |   182 |          67 |                      50 |              17
 2024-12-31 |   184 |          63 |                      48 |              15
 2025-03-31 |   188 |          61 |                      51 |              10
 2025-06-30 |   187 |          59 |                      50 |               9
 2025-09-30 |   188 |          12 |                       7 |               5
 2025-12-31 |   194 |           6 |                       4 |               2
 2026-03-31 |   199 |           8 |                       7 |               1
 2026-06-30 |   201 |          15 |                      14 |               1
```

The six earliest quarters lose **33–37%** of their cross-section; the four latest lose **3–8%**. And
the dominant cause is **`raw_present_adj_missing`** — the raw price exists in `nidp.prices_eod` but
`nidp.prices_eod_adjusted` has no row for that symbol-date. This is an adjuster backfill gap, not
missing market data:

```
  yr  | raw_symbols | adj_symbols
------+-------------+-------------
 2024 |        2366 |        1312
 2025 |        2643 |        2503
 2026 |        3019 |        2959
```

**2024: the adjusted table covers 1,312 of 2,366 symbols (55.5%).** By 2026 it is 98.0%. So the
cross-section's composition changes systematically through the study — a time-varying selection
effect layered on top of the fixed-universe survivorship of §5.3. **This is a new finding and a
repairable one: it is the highest-value fix for any future version of this study.**

**POST-HOC sensitivity** (clearly labelled: *not* pre-registered, computed after the fact from the
per-quarter table above, and on 4 blocks it supports nothing):

```
20-session primary spread, split by prices_eod_adjusted coverage
  well-covered quarters (2025-09-30 onward, ~95% coverage): n=4 mean=+1.7075 pp  [5.679, 1.973, -2.56, 1.739]
  poorly covered quarters (<=2025-06-30, ~65% coverage):    n=6 mean=+0.6532 pp  [3.373, 5.232, 1.923, -2.241, -3.68, -0.688]
```
The better-covered quarters are not the ones producing the positive point estimate, so the coverage
gap does not obviously manufacture the +1.07 pp. That is reassurance about one mechanism, not
evidence of an effect.

### 5.2 Corporate-action artefacts — screened, and nearly absent here

Applying the `NIDP-SM-VALIDATION-001` lesson (a ≥35% single-session `adj_open` fall with
`cumulative_adj_factor = 1.0` is an unapplied corporate action, not a return), over the full study
window and the panel universe:

```
  symbol   | as_of_date | pct_move | cumulative_adj_factor
-----------+------------+----------+-----------------------
 TIGERLOGS | 2026-08-17 |   -39.37 |            1.00000000
 INDOTHAI  | 2026-08-04 |   -36.44 |            1.00000000

 artefact_days | artefact_symbols | unadjusted_days
---------------+------------------+-----------------
             2 |                2 |               2
```
Screen S5 fired **2 times**. VEDL and the other 17 names from the prior study's list are not in this
panel's universe. The known incompleteness of `prices_eod_adjusted` is therefore a coverage problem
here (§5.1), not a contamination problem.

### 5.3 Survivorship and single-source exposure

```
=== universe: name-set stability across the 11 quarters ===
 n_quarters | symbols
------------+---------
         11 |     177
         10 |       2
          9 |       2
          8 |       2
          7 |       4
          6 |       1
          5 |       2
          4 |       6
          3 |       5
          2 |       2
          1 |       1
```

**177 of 204 panel symbols appear in all 11 quarters.** The universe was assembled by an
October-2026 backfill of screener.in, so names delisted or dropped from coverage before then are
absent. This is a fixed, currently-covered ~190-name set — **not** point-in-time index membership,
which cannot be reconstructed (`nidp.index_constituents` has 4 snapshots, all later than every
formation date).

```
=== source composition of the historical fii panel (dedupe winner) ===
 period_end |   source    | with_fii
------------+-------------+----------
 2024-03-31 | NSE_SHP     |        0
 2024-03-31 | screener_in |      181
 2024-06-30 | screener_in |      182
 ...
 2026-06-30 | NSE_SHP     |        0
 2026-06-30 | screener_in |      202
```

**100% of the usable panel's `fii_pct` comes from `screener_in`.** NSE_SHP carries institutional
columns for 2026-09-30 only, so **no cross-source validation is possible on any study quarter**.
Screen S6 (sources disagreeing by >2.00 pp) consequently fired **0 times** — not because the data
agrees, but because there is only ever one source to agree with. The ICICIBANK-style 15.76 pp
disagreement cannot be detected in this panel.

Related and unverifiable: screener.in serves each quarter's figure **as it stands today**. A company
that restated a prior quarter shows the restated value, not what was disclosed at the time.

---

## 6. Honest accounting against the prior art

`NIDP-SM-VALIDATION-002` was criticised for testing 1 of 6 registered features over 27.8% of its
universe. What this study did differently, and where it is still exposed:

| Prior-art failure | This study |
|---|---|
| Registered 6 features, implemented 1 | Registered 1 grouping variable + 2 robustness variants; **all 3 implemented and all 3 reported**, including the one that flips the sign |
| Saw 27.8% of its universe ("never asked" reported as "no interest") | Every pair is screened explicitly; the exclusion ledger accounts for all 626 drops; coverage is 66.7% of pairs and the reason for every miss is named |
| Benchmark columns NULL in all 540 rows while the contract named a TRI | No benchmark is claimed. The estimand is market-neutral by construction and §3.2 shows why no index is usable |
| CI narrow because 6/9 differences were exactly 0 | No spread is exactly zero; the CI is wide because the effect is genuinely uncertain. **That is the honest failure mode** |
| Corporate actions entered as performance (KOTAKBANK −79.70%) | Screen S5 pre-registered and fired twice; returns hand-verified |
| 9 blocks against a floor of 12 | **10 blocks against a floor of 12 — still below it, and said so before computing anything** |

The sample problem is **worse** here than in the prior art in one respect and better in another: more
blocks (10 vs 9), but they are **quarterly**, so reaching 12 means waiting until ~Q1 2027 — two more
disclosure cycles — rather than two more months.

---

## 7. What would actually change the answer

In priority order. None of these may be chosen by re-running until a number improves.

1. **Backfill `nidp.prices_eod_adjusted` for 2024–mid-2025.** The adjuster covers 55.5% of 2024
   symbols. This alone would restore ~33% of the cross-section in six of ten quarters and remove the
   time-varying selection effect. Highest value, purely an engineering fix, and it benefits every
   other backtest in the repo.
2. **Backfill institutional columns in `NSE_SHP` for quarters before 2026-09-30.** The ingest proves
   the pipeline works: 1,740 names with `fii_pct` for 2026-09-30 against ~190 from screener.in. This
   would take the cross-section from ~190 to ~1,700 names **and** supply a real `broadcast_at` per
   name per quarter, retiring the statutory-deadline proxy and §2.4's residual exposure entirely.
   This is the single fix that would make the study properly look-ahead-safe rather than
   defensibly-bounded.
3. **Wait.** One usable quarter per three months. The review floor of 12 arrives ~Q1 2027.
4. **Do not** reach for the result by widening the bands, changing horizons, or dropping the
   robustness variant that disagrees. The hash guard exists to make that visible.

---

## 8. Scope, constraints honoured, and what remains unverified

**Honoured**
- Nothing promoted. `nidp.v3_stock_scores_daily` untouched; no score, no threshold, no feature.
- No product code modified: nothing under `frontend-v5/`, `daas_api/routers/`, `backend/routes/`.
  The entire deliverable is `backend/nidp/analysis/shp_post_disclosure/` plus this report.
- Warehouse access read-only; no DDL, no writes. No credential file was read or printed.
- `series IN ('EQ','BE')` applied to the trading calendar throughout.
- Dedupe applied exactly as specified in the brief.

**UNVERIFIED / limitations**
- **UNVERIFIED: that no filer in the 10 study quarters disclosed later than `period_end + 25`
  days.** No filing timestamp exists for any quarter before 2026-09-30 anywhere in this warehouse
  (§2.4). The entry rule clears the statutory deadline and the only observable lag distribution, but
  per-name compliance is unconfirmable. This is the study's principal unresolved look-ahead exposure.
- **UNVERIFIED: that screener.in's historical figures are the as-disclosed values** rather than
  later restatements. Not checkable without a second historical source.
- No total-return variant. Price return only; dividends are not added back. Largely cancels in the
  spread, not in the group levels in §4.
- 10 quarters spanning 2024-04 to 2026-10 — a single broad market regime. Stability across regimes
  is unknown.
- Staging warehouse only. Production untouched and unexamined.

---

## 9. Reproduce

```bash
# contract (hash is verified by the script before any data is read)
sha256sum backend/nidp/analysis/shp_post_disclosure/preregistration.json
# -> 5452b0551ab57ff68ba365963eae4d0490ee250c0d4322c9f5218d0734ec7071

# full run against the warehouse (~31 s)
python3 backend/nidp/analysis/shp_post_disclosure/study.py --out /tmp/shpfwd

# re-analyse a captured panel without warehouse access (bit-identical statistics)
python3 backend/nidp/analysis/shp_post_disclosure/study.py --panel-csv /tmp/shpfwd/panel.csv
```

Stdlib only; no new dependency. The panel SQL is `backend/nidp/analysis/shp_post_disclosure/panel.sql`
and is read-only.

## Verdict: INCONCLUSIVE

The method is look-ahead-safe to the limit the data permits, and it is reusable. The **data cannot
support a conclusion**: 10 quarterly blocks against a floor of 12, a ~190-name single-source
cross-section, 22% of pairs lost to an incomplete price adjuster concentrated in the early quarters,
and a 20-session spread whose **sign flips** between two equally defensible definitions of
institutional ownership. The one quarter with a genuine publication timestamp — the only one that
would need no proxy at all — has no forward window yet.

No promotion. No recommendation to build on this. Fix the two backfills in §7 and the same script
will answer the question properly.
