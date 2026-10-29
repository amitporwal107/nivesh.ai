# DQ foundation (PR-1) — test cases, written before the code

Branch `feat/dq-foundation` from origin/dev 783d7095. Owner ask (28 Oct): "first work on the data quality aspects, make
sure we have the highest quality of data". Scope: make the existing NIDP quality checks honest. This PR does not change
what any screen or API serves. Enforcement comes in a later PR.

Evidence these cases are built on (staging warehouse, 28–29 Oct):
- `nidp.quality_scores`: equity is REVIEW/REJECT on every day since 12 Oct.
- Shareholding: screener_in rows violate 84.8% (median promoter + public = 86.66). With FII + DII + govt added, 424 of
  453 sum to 100. NSE_SHP rows have 0 sums over 100.5.
- Price-move flags compare against months-old rows (GSLSU prior 23 Feb). Against NSE's own prev_close, the move is
  small.
- NSE prev_close vs our prior close, 12–27 Oct: 3 mismatches in 11 sessions (CCAVENUE 13.83 vs 138.30; CEREBRAINT ×2).
- Accuracy and BLOCK-count filters use `ingester LIKE 'equity%'`, which matches no ingester.
- Great Expectations inserts omit NOT NULL columns, so every insert fails.
- `validation_runs.asset` is never set, so `v_feed_status.last_dq_status` = NONE for all 59 feeds.
- Gate 1: `is_backfill` is derived from the date's age, so G1-UNIV-004 can never fire.

## Rules (SQL, against a throwaway Postgres: `tests/test_dq_foundation_pg.py`)
| ID | Case | Expected |
|---|---|---|
| SH-1 | NSE_SHP row, promoter 60 + public 38 (2 = non-promoter non-public, e.g. DR/ESOP trust) | no finding |
| SH-2 | NSE_SHP row, promoter 60 + public 41 (sum 101) | finding (sum above 100.5 is impossible) |
| SH-3 | screener_in row, promoter 50, fii 20, dii 15, govt 0, public 15 | no finding |
| SH-4 | screener_in row, promoter 50, fii 20, dii 15, public 5 (sum 90) | finding |
| SH-5 | old filing (period_end > 95 days before target) that violates | not counted |
| PM-1 | EQ close 130 with NSE prev_close 128, last stored row 13.8 a week earlier | no price-move finding (NSE base used) |
| PM-2 | EQ close 160 with NSE prev_close 100 and no corporate action | price-move finding (+60%) |
| PM-3 | symbol `XYZ-RE` (rights entitlement) moving 40% | no finding |
| PM-4 | SPLIT with ex_date = target date, close 50 vs prev 100 | no finding |
| PC-1 | NSE prev_close 138.30, our last close 13.83 (within 30 days) | continuity finding for that symbol |
| PC-2 | NSE prev_close equals our last close | no finding |
| PC-3 | SPLIT ex_date = target date, prev_close differs | no finding (NSE adjusts the base) |
| PC-4 | no stored row in the last 30 days (new listing) | no finding |
| PC-5 | series switch EQ→BE: last row in EQ yesterday, today BE, prev_close equal | no finding |

## Score (unit: `tests/shared/test_quality_score_dq_foundation.py`)
| ID | Case | Expected |
|---|---|---|
| QS-1 | domain map: equity ingesters include bhavcopy, delivery, index_close, corporate_actions, nse_equity_master, nse_shareholding, bulk_deals, block_deals | accuracy and BLOCK queries receive that list (no LIKE) |
| QS-2 | 8 rules run, findings only from one WARN rule | consistency = 100 × (1 − 0.1/8) = 98.75 |
| QS-3 | 8 rules, one ERROR + one CRITICAL rule | 100 × (1 − 1.5/8) = 81.25 |
| QS-4 | rules_failed counts a crashed rule with no findings | it weighs 1.0 (unknown is never a pass) |
| QS-5 | no consistency run | 95.0 kept (unchanged behaviour), cross_source_agreement None |
| QS-6 | freshness query receives the domain's ingester list | yes |
| QS-7 | in-memory consistency input (dry run) gives the same number as the DB path for the same findings | equal |
| QS-8 | mf domain: unchanged rules, ter_direct_lt_regular CRITICAL fires | consistency drops by the full rule weight (1.0), as today |

## Gate 1 (unit: `tests/shared/test_gate1_backfill_flag.py`)
| ID | Case | Expected |
|---|---|---|
| G1-1 | live run (no backfill context) for a date 10 days old | G1-UNIV-004 runs and fails (P1, AMBER), the run still persists |
| G1-2 | run inside `backfill_context()` for the same date | G1-UNIV-004 skipped |
| G1-3 | env `NIDP_BACKFILL=1` | skipped |
| G1-4 | `backfill._run_one` wraps the ingester call in the backfill context | yes (the flag is set during the call and reset after) |
| G1-5 | migration seeds `dq.feed_sla` gate-1 floors: bhavcopy 1500, fno_bhavcopy 25000 (lowest real day 29,088; old 30000 blocked real post-expiry sessions), delivery 1500, index_close 20 | rows present; re-runnable |

## Findings persistence (unit + PG)
| ID | Case | Expected |
|---|---|---|
| GE-1 | Great Expectations finding insert | includes finding_id, validation_id, failure_class; writes `sample_rows`; the insert succeeds against the 006 schema (PG test) |
| AS-1 | `run_validation` inserts `validation_runs.asset` = the ingester's primary table | set |
| AS-2 | `v_feed_dq` counts rows with a NULL asset as the ingester itself | a feed with validation runs is no longer NONE (PG test) |

## Staging dry run (no writes) — `scripts/dq_dryrun_rescore.py`, run inside the NIDP container on a scratch copy
| ID | Case | Expected |
|---|---|---|
| DR-1 | re-score equity and mf for 12–27 Oct with the new rules and score, compute only | before/after table per date; no INSERT/UPDATE issued (the connection is read-only: `SET TRANSACTION READ ONLY`) |
| DR-2 | CCAVENUE 19 Oct | continuity finding |
| DR-3 | equity verdict per date | explained by the remaining findings, date by date |

## Regression
- Existing NIDP validation and quality tests keep passing: `tests/parsers/test_validation_framework.py`,
  `services/quality_gate/tests/*`, `tests/quality/test_replay_engine.py`, `tests/services/test_dlq_redrive.py`,
  `tests/services/test_feed_reconciler.py`, `tests/test_backfill.py`.
- The same suite on origin/dev is the baseline.
