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
- **The material-gap census is unfinished.** The 44/80/123 counts are
  `IS DISTINCT FROM`, which includes ±0.01 rounding. The query separating rounding
  noise from real conflicts was denied by the classifier before it ran. Two known
  material cases from an earlier sample: `ANTGRAPHIC` (NSE promoter 96.00% vs
  screener 0.96% — the NSE row also has `public_pct = 9904`, a 100x scale error) and
  `SUPREMEINF` (47.32% vs 46.95%).

## To clear this override

1. Open the permission gate for `gcloud compute ssh/scp` to nidp-stack-vm.
2. Supply a fresh GCP access token for `/app/.gcp-token`.
3. Apply 133 on staging, re-run the row/symbol count, and replace this file with a
   normal report ending `## Verdict: PASS`.
