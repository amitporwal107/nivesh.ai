# Functionality Verification Report — NIDP data gaps for the 10%-move model

- **Branch:** fix/nidp-prediction-data-gaps (pushed to `dev`: 22629785 → f296c69b)
- **Date:** 2026-09-11 / 2026-09-12 (IST)
- **Author:** Claude (orchestrator: full-stack + QA + domain), workspace `.claude/workspace/nidp-prediction-data-gaps/`
- **Environment:** staging — `nidp_staging` on nidp-stack-vm (prod DaaS also reads this DB)
- **Changed areas:** backend routes/services: yes (`backend/nidp/**` only) · frontend src: no

## Summary
Fixes for the NIDP inputs to the 10%-move model, lowest effort first: missing NSE sessions and
BSE gap-fill days, technical indicators on unadjusted prices, a frozen `v_feed_status`, pb /
Altman / Piotroski defects, options aggregates dropped by migration 091, announcements
completeness and healing, a point-in-time results calendar, and a daily price-band / F&O / ETF
snapshot. Every touched table was backed up first (`/opt/nidp-staging/backups/pred_gaps_20260911_1743`).

## Test Cases
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | Prices | Every NSE session since 2025-01-01 present as NSE_BHAVCOPY; no BSE rows on NSE dates; no duplicate bars | data | 421/421, 0, 0 | PASS |
| TC-2 | Prices | Delivery filled on repaired dates | data | 100% | PASS |
| TC-3 | Technicals | Split/bonus adjustment in `_to_arrays` (1:1 bonus, event after last bar, none) | unit | adjusted to last-bar basis, no look-ahead | PASS |
| TC-4 | Technicals | Range recompute rewrites history (ANANDRATHI 2026-06-08 return_20d in [−5, 1]; ret60 parity ≥99%) | data | after recompute | PENDING — re-running since 00:09 IST (first run hit a 120 s timeout, fixed in f296c69b) |
| TC-5 | Adjuster | Symbols with a new action get full-history rewrite | unit | `(as_of_date >= $1 OR symbol = ANY($2))` | PASS |
| TC-6 | Feed status | Runs exit 0 and `source_registry` moves; one row per ingester | data | fresh timestamps, 0 duplicates | PASS |
| TC-7 | Fundamentals | pb > 0 where equity > 0; Altman \|Z\| < 100; Piotroski can exceed 2 | unit + data | unit PASS; data after fundamental_engine | PENDING (data) |
| TC-8 | Options | options_pcr filled for F&O names | data | ≥95% of 210 | PENDING — needs recompute + F&O backfill |
| TC-9 | Announcements | NIDP NSE_ANN per day vs NSE API, 2026-08-11..09-10 | data | ≥98%/day | PASS 30/31 days; total 99.2% (Sun 09-06 95.8%) |
| TC-10 | Announcements | Classification within 24 h | data | ≥95% | FAIL for now — 16,627 of 18,632 unclassified; provider returns 429 rate limit |
| TC-11 | Calendar | Upcoming meetings carry intimated_at; history 2024-06..2026-05 vs NSE per month | data | ≥95%; ±2% | PASS — 27/27 upcoming; 100% every month 2024-06..2026-04, 98.7% 2026-05 |
| TC-12 | Calendar | first_seen_at insert-only; backfill never overwrites live fields; repeat listings collapsed | unit | SQL shape + collapse | PASS |
| TC-13 | Reference | price band / F&O / ETF snapshot | data | 350 ETF, F&O unbanded | PASS — 3,537 symbols, 350 ETF, 210 F&O, 0 F&O with a band |
| TC-14 | NFS | Mount + containers survive a reboot | ops | no manual step | PENDING — config applied and unit ordering verified; reboot needs a window |

## API / Endpoint Tests (staging)
No HTTP route changed. Services run on staging via `/opt/nidp-staging/run_service.sh`.
- **pytest** (`cd backend && python3 -m pytest nidp/tests/services/test_indicator_range_timeouts.py … nidp/tests/test_backfill.py -q`):
  `57 passed in 24.74s`

## Data Correctness (staging)
- Sessions: `SELECT count(DISTINCT as_of_date) … source='NSE_BHAVCOPY' AND series='EQ' AND as_of_date BETWEEN '2025-01-01' AND '2026-09-10'` → `421` (NSE archive: 421 incl. 2025-02-01, 2026-02-01); BSE rows on NSE dates `0`; duplicate EQ bars `0`.
- Feed status: `delivery exit=0`; `source_registry` NSE_DELIVERY `2026-09-11 22:44:30 OK`, NSE_BHAVCOPY `22:38:38 OK` (frozen at 2026-08-20/21 before); `v_feed_status` ingesters with >1 row: `0`.
- Announcements: NIDP `19,831` vs NSE API `20,001` = `99.2%` for 2026-08-11..09-10 (was 7,070 = 36%).
- Calendar: quarterly_results rows = distinct meetings every month; e.g. `2026-02:1626/1626` vs NSE 1,626.
- Reference: `2026-09-11 | 3537 | etf 350 | fno 210 | banded 2997 | fno_with_band 0`.
- F&O holes being refilled: `08-25:36112 08-26:31187 08-27:17500 (running)`.
- Piotroski root cause: every quarterly row has `period_type = 'quarterly'` (NSE_FIN 118, company_ir 19, nse_xbrl_backfill 1,922, screener_in 3,993, screener_in_annual 312); the prior-year query matched `'QUARTERLY'`.
- Migrations applied on staging by psql (not `nidp.cli migrate`, which would also apply unrelated 129–131): 105 (re-created view, 2,452 names), 136, 137, 138, 139.

## Inputs required from user
- GCP access-token refreshes (1-hour life) for every VM/DB step.
- A maintenance window for the NFS reboot test (a reboot also restarts prod Postgres).

## Verdict: BLOCKED
Pending with real output: TC-4, TC-7 (data), TC-8, TC-10 (rate-limited), TC-14.
