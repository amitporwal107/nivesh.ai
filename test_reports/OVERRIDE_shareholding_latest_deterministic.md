# OVERRIDE — migration 133 (v_shareholding_latest determinism) NOT APPLIED

REASON: Blocked on two things only the user can supply. (1) The auto-mode permission
classifier denied the DDL apply and the `gcloud compute scp` of the migration file to
nidp-stack-vm — the user's chat approval does not open that gate, it has to be opened
in their client. (2) The GCP access token in `/app/.gcp-token` expired mid-turn
(`Request had invalid authentication credentials`), so no further staging access was
possible. Nothing was applied to any database.

- **Branch:** feat/research-qa-exercise
- **Date:** 2026-08-19
- **Changed areas:** `backend/nidp/migrations/133_shareholding_latest_deterministic.sql` (new),
  `backend/nidp/services/quality_gate/dq_suites.py` (comment only)

## What IS verified (real output, this session)

The migration's SELECT body was run **read-only** against the live `nidp_staging`
table — the whole view definition as a plain query, no DDL:

```
 view_rows | symbols | surplus
-----------+---------+---------
      2325 |    2325 |       0
```

Exactly one row per symbol, against 3,342 / 2,325 / **1,017 surplus** for the view as
it stands today.

QoQ deltas survive the change:

```
 symbols | with_fii_qoq | with_dii_qoq | with_promoter_qoq | with_pledge_qoq
---------+--------------+--------------+-------------------+-----------------
    2325 |         1938 |         1914 |              2219 |               0
```

(`with_pledge_qoq = 0` is correct: only one quarter carries pledge so far, so there is
no prior quarter to difference against.)

`CREATE OR REPLACE VIEW` requires an identical output column list. Compared the
migration's final SELECT against `pg_get_viewdef('nidp.v_shareholding_latest')`
captured from staging:

```
live columns : 18
new  columns : 18
IDENTICAL    : True
order: symbol, period_end, promoter_pct, promoter_pledged_pct,
       promoter_pledged_to_total_pct, fii_pct, dii_pct, mf_pct, insurance_pct,
       public_pct, individual_pct, promoter_pct_change_qoq, fii_pct_change_qoq,
       dii_pct_change_qoq, mf_pct_change_qoq, pledge_pct_change_qoq, broadcast_at,
       source_run_id
```

Evidence for the source precedence the migration encodes — every row must satisfy
`promoter_pct + public_pct = 100`:

```
   source    | rows_checked | violations | pct
-------------+--------------+------------+------
 NSE_SHP     |         4482 |         20 |  0.4
 screener_in |         4236 |       2756 | 65.1
```

And the disagreement the coin-flip was hiding, across the 329 symbols carrying both
sources at their latest quarter:

```
 overlapping_symbols | promoter_differs | fii_differs | dii_differs
---------------------+------------------+-------------+-------------
                 329 |               44 |          80 |         123
```

Tests: `77 passed` (`quality_gate` suites + both `nse_pledge_csv` modules).

## What is NOT verified

- **The migration has not been applied anywhere.** `nidp_staging` still serves the old
  view (3,342 rows / 2,325 symbols). Nothing was written.
## Material-gap census — COMPLETED 2026-08-19 (was outstanding, now done)

The 44/80/123 counts use `IS DISTINCT FROM` and so include ±0.01 rounding. Filtering
to gaps above 0.05 percentage points, out of the same 329 overlapping symbols:

```
 overlapping | promoter_material | fii_material | dii_material
-------------+-------------------+--------------+--------------
         329 |                 2 |            8 |           18
```

So most of the disagreement is rounding. 23 symbols have a real gap on at least one
of the three, and the `sums_to` columns show which source is wrong (`promoter_pct +
public_pct` must equal 100):

```
   symbol   | period_end | n_prom  | s_prom  |  n_fii  |  s_fii  |  n_dii  |  s_dii  | nse_sums_to | scr_sums_to
------------+------------+---------+---------+---------+---------+---------+---------+-------------+-------------
 ANTGRAPHIC | 2026-03-31 | 96.0000 |  0.9600 | 46.0000 |  0.4600 | 21.0000 |  0.2100 |    10000.00 |       99.30
 ICICIBANK  | 2026-06-30 |         |         | 49.8200 | 33.7900 | 42.3100 | 42.3200 |             |
 AXISBANK   | 2026-06-30 |  7.8700 |  7.8700 | 43.0000 | 39.9100 | 42.6900 | 42.6900 |      100.00 |       17.39
 WIPRO      | 2026-06-30 | 72.5900 | 72.5900 | 11.1400 |  8.8500 |  5.2200 |  5.2200 |       99.88 |       85.80
 KESORAMIND | 2026-06-30 | 43.3400 | 43.3400 |  2.4100 |  0.1400 |  3.9900 |  3.9900 |      100.00 |       95.85
 ANANDRATHI | 2026-06-30 | 41.3700 | 41.3700 |  6.3700 |  6.7800 | 10.3900 |  9.4000 |      100.00 |       83.81
 ABCAPITAL  | 2026-06-30 | 68.8100 | 68.8100 |  8.6000 |  7.9400 | 13.4800 | 13.3600 |      100.00 |       78.58
 ASTRAL     | 2026-06-30 | 54.2200 | 54.2200 | 13.8900 | 13.8900 | 21.3100 | 20.9300 |      100.00 |       64.81
 SUPREMEINF | 2026-03-31 | 47.3200 | 46.9500 |  3.0200 |  3.0000 |  5.9900 |  5.9500 |      100.00 |       91.07
 HAVELLS    | 2026-06-30 | 59.3500 | 59.3500 | 15.9100 | 15.9100 | 18.2600 | 18.0400 |      100.00 |       65.82
 AMBUJACEM  | 2026-06-30 | 67.3300 | 67.3300 |  5.6300 |  5.6300 | 19.6500 | 19.4400 |      100.00 |       74.71
 TRENT      | 2026-06-30 | 37.0100 | 37.0100 | 15.1400 | 15.1400 | 23.2700 | 23.0700 |      100.00 |       61.58
 HDFCBANK   | 2026-06-30 |         |         | 41.8300 | 41.8200 | 41.9200 | 41.7500 |             |
 BHARATFORG | 2026-06-30 | 44.0700 | 44.0700 | 15.0400 | 15.0400 | 32.3400 | 32.1800 |      100.00 |       52.61
 GABRIEL    | 2026-06-30 | 63.5500 | 63.5500 |  6.3600 |  6.5100 | 12.9200 | 12.8000 |      100.00 |       80.69
 RBLBANK    | 2026-06-30 | 60.0000 | 60.0000 |  8.7700 |  8.7700 | 17.0500 | 16.9200 |      100.00 |       74.16
 GAIL       | 2026-06-30 | 51.7900 | 51.7900 | 14.9900 | 15.0000 | 19.2000 | 19.0900 |      100.00 |       58.31
 BAJFINANCE | 2026-06-30 | 54.6700 | 54.6800 | 20.2100 | 20.2000 | 16.4000 | 16.3000 |       99.91 |       63.32
 DCMSRIND   | 2026-06-30 | 50.1100 | 50.1100 |  1.1200 |  1.1200 | 12.8000 | 12.7000 |      100.00 |       86.08
 BANKBARODA | 2026-06-30 | 63.9700 | 63.9700 | 10.1400 | 10.1400 | 18.4200 | 18.3300 |      100.00 |       71.44
 DIVISLAB   | 2026-06-30 | 51.8800 | 51.8800 | 20.2000 | 20.1900 | 19.3800 | 19.2900 |      100.00 |       60.41
 RELIANCE   | 2026-06-30 | 50.4800 | 50.4800 | 17.2000 | 17.1900 | 21.1900 | 21.1000 |      100.00 |       61.53
 HINDUNILVR | 2026-06-30 | 61.9000 | 61.9000 |  9.5000 |  9.5000 | 16.9900 | 16.9200 |      100.00 |       73.50
```

The biggest is **ICICIBANK**: FII 49.82% (NSE) vs 33.79% (screener), a 16-point gap
the coin flip was choosing between. `scr_sums_to` is far from 100 on essentially every
row here (17.39 for AXISBANK, 61.53 for RELIANCE), which is the arithmetic case for
the NSE_SHP precedence this migration encodes.

**One known casualty:** `ANTGRAPHIC` is the sole row where NSE is the wrong one —
`nse_sums_to = 10000.00` is a 100x scale error, against screener's coherent 99.30.
After 133 the view will read the corrupt NSE row for that symbol. It is not silent:
the DQ rule `columns_sum_to(["promoter_pct","public_pct"], target=100, tol=3.0,
severity="fail")` already fires on it. A per-row correction is a separate fix from a
view's tiebreak and is not folded in here.

## To clear this override

1. Open the permission gate for `gcloud compute ssh/scp` to nidp-stack-vm.
2. Supply a fresh GCP access token for `/app/.gcp-token`.
3. Apply 133 on staging, re-run the row/symbol count, and replace this file with a
   normal report ending `## Verdict: PASS`.
