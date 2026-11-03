# DQ foundation (PR-1) — verification report, 29 Oct 2026

Branch `feat/dq-foundation` from origin/dev 783d7095. Test cases written first: `test_reports/dq_foundation_TESTCASES.md`.

## Scope
The owner asked for data quality first, and only for the data the trading product needs ("not for all the feeds").
This PR therefore makes the existing NIDP quality checks honest for **equity market data**. Mutual-fund scoring keeps its
earlier behaviour exactly (`quality_score.is_scored_domain`; tests `test_scope_mf_*`).

It changes no screen and no API answer. Nothing yet reads the certification. Enforcement is a later PR, after a week of
shadow verdicts.

## What changed
| Area | Change | File |
|---|---|---|
| Shareholding rule | Checked by each source's own definition of "public". NSE_SHP: promoter + public ≤ 100.5. screener_in: promoter + FII + DII + govt + public = 100 ± 0.5. Only the latest filing per symbol and source counts. | `shared/validation/consistency_rules/equity.py` |
| Price-move rule | Measured against the row's own NSE `prev_close`. Corporate actions are matched by ex-date. Rights entitlements (`-RE`, `-RE1`) and listing days are excluded. | same |
| New rule `equity.prev_close_continuity` | NSE prev_close vs our last stored close (any of EQ/BE/BZ, within 30 days). No finding when a price-base corporate action falls on the ex-date. | same |
| Score | The domain's ingester list replaces `LIKE 'equity%'`, which matched nothing, so accuracy was always 100. Consistency is weighted by severity (CRITICAL 1, ERROR 0.5, WARN 0.1); a crashed rule costs 1. Freshness is each feed's first arrival against its own deadline (delivery is due D+1 11:30). A dry-run input path is added. | `shared/validation/quality_score.py` |
| Gate BLOCK count | Counted from equity's own ingesters | `shared/quality_gate.py` |
| Gate 1 | `is_backfill` comes from the invocation (`run_context.backfill_context()`, set by `nidp.backfill`; or `NIDP_BACKFILL=1`), so G1-UNIV-004 can fire on a live run | `shared/run_context.py`, `shared/ingester_base.py`, `backfill.py` |
| Gate 1 floors | Seeded in `dq.feed_sla` and checked against every real run since Apr 2024: bhavcopy 1,500 (lowest real 2,697); delivery 1,500 (2,531); fno_bhavcopy 25,000 (29,088); index_close 20 (111) | `migrations/184_dq_foundation.sql` |
| F&O validator | Floor lowered from 30,000 to 25,000. Real post-expiry sessions (27–28 Aug, 30 Jul) had fewer than 30,000 contracts and were wrongly BLOCKed. | `services/fno_bhavcopy/validators.py` |
| Great Expectations findings | The insert names every NOT NULL column and `sample_rows`, and passes a real date. Before, every insert failed into a log warning. | `services/quality_gate/great_expectations_runner.py` |
| Feed DQ status | The runner writes `asset`; `v_feed_dq` reads rows without an asset as the ingester. `v_feed_status.last_dq_status` was NONE for all 59 feeds. | `shared/validation/runner.py`, migration 184 |
| Dry-run tool | `python -m nidp.quality.dryrun_rescore`: rules and score inside a READ ONLY transaction, printed beside the stored verdict | `quality/dryrun_rescore.py` |
| CI | Both new suites added to the backend allowlist | `.github/workflows/backend-tests.yml` |

## Results

### Unit and integration tests
```
nidp/tests/shared/test_dq_foundation_unit.py                    25 passed
nidp/tests/shared/test_dq_foundation_pg.py (throwaway Postgres)  5 passed   (skipped in CI: no NIDP_DQ_PG_DSN)
together with backend suites, as CI runs them: 125 passed, 5 skipped
```
Regression (existing NIDP validation, quality-gate, DLQ, reconciler and backfill suites), before vs after:
```
origin/dev baseline:  91 passed, 8 failed (all 8 in test_replay_engine.py: the image has no pytest-asyncio)
this branch:          98 passed (same suites without test_replay_engine.py, plus the 25 new unit cases)
                      test_replay_engine.py: the same 8 environment failures, unchanged
```

### Staging dry run (read only, real data, 12–28 Oct)
Run on the NIDP VM with the job runner's own Python and environment, against the staging warehouse, inside
`conn.transaction(readonly=True)`. The scratch code copy in `/tmp/dqdry` was removed afterwards. Nothing was written.

| Date | Stored verdict (old code) | Dry run (this branch) | Why |
|---|---|---|---|
| 12 Oct | 90.59 REVIEW / REJECT | 96.25 SILVER, REVIEW | CEREBRAINT prev_close break (NSE 2.86 vs ours 2.66) |
| 13–16 Oct | 90.59–94.88 REJECT | 98.13 GOLD, PASS | — |
| 19 Oct | 90.59 REJECT | 96.25 SILVER, REVIEW | CCAVENUE break (NSE 138.30 vs ours 13.83, 10×); CEREBRAINT |
| 21–28 Oct (7 sessions) | 90.59–94.88 REJECT | 98.13 GOLD, PASS | — |

- Equity goes from 13 of 13 days rejected to 11 PASS. The two REVIEW days are the two days with real price breaks.
- The shareholding rule still fires every day: 29 screener_in filings genuinely don't add up. It costs 0.5 of 8 rules
  (6.25 consistency points). It is ownership data, not trading data, and will move out of the price certification in
  the per-dataset certification PR.
- In the same run the MF rows show freshness 0. **That is not a change.** The MF code path is the earlier one
  unchanged (tests `test_scope_mf_*`). The old formula takes the newest run of any ingester for the date, which after
  the fact includes the next morning's delivery run. At the real 22:30 run that run had not happened yet, so the
  stored MF scores were never affected. The equity fix removes exactly this flaw.

## UNVERIFIED (needs the merge, then an owner-approved step)
- **Migration 184 is not applied to the staging warehouse.** It is a shared write: the owner approves it, then it is
  run.
- **The scheduled quality gate runs code from `/opt/nidp/dev-repo` (dev).** The new scoring takes effect only after the
  merge and a refresh of that checkout.
- **Old stored scores are not re-scored.** Re-scoring 12–28 Oct in `nidp.quality_scores` is a shared write and needs
  owner approval; the dry-run table above is what it would show.
- **Great Expectations findings will start being recorded** once merged, because the quality gate already calls the
  GE runner. Expect new FIX-class rows in `nidp.validation_findings`.

## Verdict: PASS
