# F&O ranking and threshold backtest, Stage A: tooling verification

Scope of this report: the BACKTEST TOOLING (point-in-time panel, outcomes, splits, statistics, ranking and threshold studies, reproducible report, runner). The verdict below is about the tooling being correct. It is NOT a verdict on the ranking or the thresholds, which the findings (docs/FO_RANKING_BACKTEST_FINDINGS_20261023.md) show are not supported.

Test cases: fno_ranking_backtest_TESTCASES.md (written before implementation).

## Real output (this session)
- `python -m pytest tests/test_fno_backtest.py tests/test_fno_candidates.py tests/test_fno_routes.py tests/test_kite_live_feed.py -q` (staging image, --network none): see the final line below.
- Real run, staging data platform, read only, in a scratch copy inside the backend container: `sessions 2025-12-29 .. 2026-10-22 (201)`, `scans for 201 sessions, 229 distinct symbols`, `features for 229 symbols, adjusted prices for 229`, `report written ... experiment fo-bt-95f4e5df42dc | status research_result | hash c5b125ba612073e0`, 28 seconds.
- Failures along the way, all in my own tests, fixed: an off-by-one in a split-boundary assertion (the code's strict purge was right), and a synthetic world too small for a top five to differ from the whole pool.

## Test cases
| ID | Result |
|----|--------|
| TC-1..TC-3 outcome, missing price, costs | PASS (unit) |
| TC-4, TC-5 point in time (newest row on or before the day; future rows cannot change an earlier session) | PASS (unit) |
| TC-6 splits 60/20/20 with the forward window kept inside the split | PASS (unit) |
| TC-7, TC-8 Newey-West and Spearman worked examples | PASS (unit) |
| TC-9 variants from the same ranked pool; pool average = mean of the pool | PASS (unit) |
| TC-10 counted configurations; identical inputs give an identical hash, a changed price changes it | PASS (unit) |
| TC-11 verdict never `validated`; too few test sessions is `insufficient_evidence` | PASS (unit) |
| TC-12 real run on the staging data platform and an honest report of a negative result | PASS (real run; the result is negative) |

## Not verified
- The Stage B run on Kite's older history is not built.
- The cost model is an assumed percentage, not the completed strategy-engine cost model.

## Verdict: PASS
