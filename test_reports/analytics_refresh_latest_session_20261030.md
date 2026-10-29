# Functionality Verification Report — analytics_refresh refreshes the latest session (the analytics layer was frozen at 12 Oct)

- **Branch:** fix/analytics-refresh-latest-session (from origin/dev a4294830)
- **Date:** 2026-10-30
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER + DOMAIN_EXPERT_ANALYST)
- **Changed areas:** backend/nidp/services/analytics_refresh/service.py (+ a new test). No route, no frontend.

## Summary
Found by the Daily Trader Copilot data audit, 30 Oct.
- **Symptom:** on staging the analytics layer has stayed on 12 Oct. That layer is `analytics.stock_card`, `sector_snapshot`,
  `mv_top_momentum`, `mv_delivery_surge` and `mv_sector_heatmap`. It feeds Market Overview's top movers, the sector heatmap,
  delivery surge and stock cards, so they all show 12 Oct.
- **Cause:** the cron runs at 00:10 IST (Tue–Sat), and `run()` defaulted to `date.today()`. At that hour that is the next
  calendar day, which has no prices. Every run from 13 Oct wrote 0 rows and still logged OK.
- **Fix, part 1:** the default date is now the latest session in `nidp.stock_daily_snapshot` that is not in the future.
  That is the table `analytics.refresh_stock_card` reads.
- **Fix, part 2:** a run that writes 0 stock cards now raises, so `nidp.job_log` and `v_feed_status` show FAILED instead of
  a silent OK.

## Test Cases
| ID | Scenario | Expected | Result |
|----|----------|----------|--------|
| AR-1 | No date given | It asks `nidp.stock_daily_snapshot` for the latest session ≤ today and refreshes that date | PASS |
| AR-2 | An explicit date | Used as given; no latest-session query | PASS |
| AR-3 | `refresh_all` writes 0 stock cards | RuntimeError, so the job log reads FAILED | PASS |
| AR-4 | No snapshot at all | RuntimeError "no session to refresh" | PASS |
| AR-5 | Staging data (read only) | The latest snapshot session is 2026-10-29 with rows; `analytics.stock_card` stops at 2026-10-12 | PASS |
| AR-6 | Staging after merge | The next 00:10 run refreshes the latest session; stock_card / movers move past 12 Oct | PENDING (after merge) |

## Tests run (real output, 2026-10-30)
- `pytest nidp/tests/services/test_analytics_refresh_date.py` (backend image, no network) → `4 passed in 0.08s`.
- **Staging warehouse, read only** (`BEGIN READ ONLY … ROLLBACK` through nidp-psql.sh):
  - `SELECT max(as_of_date) FROM nidp.stock_daily_snapshot WHERE as_of_date <= CURRENT_DATE` → `2026-10-29`
  - snapshot rows: 2026-10-27 3,344 · 2026-10-28 3,327 · 2026-10-29 3,339
  - `analytics.stock_card` latest → `2026-10-12` (2,696 rows)
- **Job log** (from the 30 Oct freshness audit): `analytics_refresh` at 00:10 on 10-21 … 10-30 → status OK, 0 rows,
  every run.

## Not verified
- **AR-6:** a real run. `refresh_all` deletes and re-inserts rows in the shared staging warehouse, so I did not run it. It
  runs by itself at the next 00:10 IST cron after the merge and deploy; a one-off manual run now needs the owner's go-ahead.

## Verdict: BLOCKED
