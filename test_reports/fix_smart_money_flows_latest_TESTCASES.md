# Smart Money FII/DII chart ends two days early: test cases (authored before implementation)

Ask (user, 2026-10-23): the FII/DII chart on Smart Money still ends on 21 Oct; load the latest snapshot.
Cause (verified): GET /api/markets/smart-money/flows -> DaaS reads source SENSIBULL only, whose last day is 21 Oct (last ingest 22 Oct 08:05). The NSE provisional feed (NSE_FII_DII)
has 22 and 23 Oct and matches Sensibull to within 0.0011 crore on all 16 overlapping rows. Fix in the app route: for the daily windows (1M/3M/6M) continue the series with the days
NEWER than the last Sensibull day from the market-pulse FII/DII read (days only the NSE feed has, so none is double counted), recomputing the cumulative from the last cumulative.
Separate finding (reported, not fixed in the app): the market-pulse series sums every source, so days present in both (9-21 Oct) are doubled.

| ID | Scenario | Type | Expected |
|----|----------|------|----------|
| TC-1 | daily window: rows newer than the last row are appended, with net from the NSE read and cumulative continuing from the last cumulative; as_of becomes the newest day; the source line names the NSE tail | pytest | rows |
| TC-2 | days already in the series (older or equal to its last day) are never appended or changed (no double counting) | pytest | rows |
| TC-3 | 1Y (monthly grain) is returned unchanged | pytest | unchanged |
| TC-4 | the NSE read failing or returning nothing leaves the answer exactly as the data platform sent it (no error) | pytest | unchanged |
| TC-5 | a pulse day with a missing FII or DII net is skipped, never zero-filled | pytest | rows |
| TC-6 | the existing smart-money route tests still pass | pytest | pass |
