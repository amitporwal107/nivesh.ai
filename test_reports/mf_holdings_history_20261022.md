# Functionality Verification Report — MF Holdings History + Delta Layer

- **Branch:** feat/provider-foundations (commits 996ad4c4, 02ae25cf)
- **Date:** 2026-10-22
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER + DOMAIN_EXPERT_ANALYST)
- **Environment:** staging — `nidp_staging` on the CloudPe NIDP VM (45.64.105.224)
- **Changed areas:** backend NIDP services + migration: yes · backend/routes or backend/services: no · frontend src: no

## Summary
`nidp.mf_holdings_monthly` held exactly one month (2026-09-01, 41,820 rows, 674 schemes, 4 AMCs),
so zero mutual-fund holdings deltas were computable and the Smart Money "disclosed holdings
change" evidence class (§17 class A) had no data. Diagnosis: the pipeline was **not** broken —
discovery, download, parse and scheme resolution all worked. The defect was operational: one cron
attempt per month against sources that publish days after the SEBI M+10 deadline, with no record
of which `(amc, month)` pairs were held, so a missed month was unrecoverable.

Delivered: a per-`(amc, month)` coverage ledger, a resumable month-range backfill with
`--trailing` catch-up, a shared per-AMC ingest unit used by both the daily run and the backfill,
and the §20.1/§20.2 delta + breadth layer. Backfilled 13 months; computed 1,071,308 delta rows.

## Test Cases (authored up front in test_reports/mf_holdings_history_TESTCASES.md)

| ID | Scenario | Expected | Result |
|----|----------|----------|--------|
| TC-1 | Migration objects exist, idempotent | 3 objects + ledger row | **PASS** |
| TC-2 | 13-month backfill | ≥12 months each with rows | **PASS** — 13 months, 1,040,120 rows |
| TC-3 | Coverage row per attempted pair, counts reconcile | exact match | **PASS** — exact, per source |
| TC-4 | Re-run with `--only-missing` skips OK pairs | no refetch | **PASS** — dry-run over the 5 fully-covered AMCs: "65 pair(s); 65 already OK → 0 to attempt" |
| TC-5 | `shares_delta` = current − previous | 0 mismatches | **PASS** — 931,871 rows, 0 mismatches |
| TC-6 | Value up, shares flat | `unchanged`, not increase | **PASS** — 236,662 rows all `unchanged` |
| TC-7 | Prior shares not > 0 | `shares_pct_change` NULL | **PASS** — 0 violations both directions |
| TC-8 | New position only if scheme seen earlier | no `new` without prior observation | **PASS** — 56,864 new, 0 bad |
| TC-9 | Scheme unseen in comparison month | `unknown`/`coverage_gap` | **PASS** — 139,437 rows, 0 leaks |
| TC-10 | Breadth counts sum to total | 0 mismatches | **PASS** — 34,528 ISIN-months, 0 |
| TC-11 | Single-AMC signal flagged | flags populated | **PASS** — 3,147 of 3,833 single-AMC |
| TC-12 | NULL-ISIN holdings excluded and counted | reported, not silent | **PASS** — 8,391 reported |
| TC-13 | Daily run still works | writes coverage | **PASS** — 19 unit tests pass |

## Unit tests + compile (staging venv)
```
$ /opt/nidp-staging/venv/bin/python -m pytest nidp/services/mf_holdings/tests/ -q
...................                                                      [100%]
19 passed in 0.47s
$ ... -m py_compile service.py ingest.py coverage.py backfill.py mf_holdings_deltas/service.py cli.py
py_compile: all 6 modules OK
```

## Backfill run (real output, NIDP VM)
```
coverage ledger: 74 OK, 8 EMPTY, 13 months, 1,040,120 rows written
mf_holdings_deltas --all: fetched=1071308 inserted=1071308 status=OK duration=61095ms
```
Per-month delta classes (2026-09): unchanged 62,358 · unknown 35,041 · increase 19,146 ·
decrease 13,592 · possible_exit 9,607 · new 8,170. The earliest month (2025-09) is 100%
`unknown` — correct, there is nothing before it to compare against.

The 8 EMPTY pairs are Axis 2025-09..2026-04: AdvisorKhoj exposes only 5 months for Axis.
Recorded as retryable-empty in the ledger, not silently skipped.

## Data correctness (staging)
**Month-labelling integrity.** Every OK pair's `source_url` was checked against its `as_of_month`.
74/74 correct. Nine URLs do not spell the month name but encode the month-END date numerically
(`30092026`, `30_09_2026`, `30.09.2026`) and resolve to the right month; UTI's `Oct-26`
*publication* folder was correctly ignored in favour of the filename's `30.09.2026`.

**Headline query now answerable** (§16 "stocks where MF holdings increased across disclosures"),
Sep 2026, ISINs with ≥3 independent AMCs increasing:
```
 INE040A01034 HDFCBANK   inc=210 red=137 amcs=6 net_shares=-8,335,553
 INE238A01034 AXISBANK   inc=185 red=68  amcs=6 net_shares=-9,647,317
 INE062A01020 SBIN       inc=162 red=103 amcs=6 net_shares=+16,181,610
```
Note HDFCBANK: 210 schemes increasing yet net shares negative — many small adds against fewer
large reductions. Reporting both sides plus `net_shares_delta` is what makes that visible instead
of publishing "210 funds are buying".

## UNVERIFIED / limitations
- **UNVERIFIED on prod.** All of the above is staging only. Prod was not touched.
- **History is AMC-skewed.** 13 months exist for ICICI Pru, Kotak, ABSL, Franklin, PPFAS; 5 for
  Axis; 1 for SBI, Quant, UTI, Nippon (current month only — their adapters have no history path).
  HDFC, Tata and Mirae are unreached. 12-month lookbacks are therefore not AMC-representative,
  and HDFC's absence (a top-3 AMC) is a material breadth gap. Remediation assessed separately.
- **No publication date on `mf_holdings_monthly`.** Only `as_of_month` and `ingested_at` exist, so
  §39's "do not treat a holding as known before it was published" cannot yet be enforced. This
  should be added before the data is used for any point-in-time backtest.
- Migration was applied by piping the file + its `schema_migrations` row through psql (equivalent
  to the CLI runner). Renumbered 159 → **165** after discovering 159 was already taken on `dev`
  and the DB was at 164.
- `/opt/nidp/mf-backfill` on the NIDP VM is a scratch checkout created for this run; the VM's
  `/opt/nidp/dev-repo` (`dev`) was not modified.

## Verdict: PASS
