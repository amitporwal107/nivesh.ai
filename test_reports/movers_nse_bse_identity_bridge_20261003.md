# Functionality Verification Report — NSE/BSE identity bridge in the Movers event log

- **Branch:** `feat/movers-monday-candidates`
- **Date:** 2026-10-03
- **Author:** Claude (full-stack developer)
- **Environment:** mocked unit tests (backend pytest) + **real staging data, confirmed by direct SQL**
  (via `gcloud compute ssh` to `nidp-stack-vm`, never printing the connection string).
- **Changed areas:** backend only: `backend/nidp/services/daas_api/routers/movers.py` (`_events_for`,
  shared by every Movers mode — MOVERS/FLAGGED/FORWARD/CANDIDATES, old and new), `backend/tests/test_movers_v4.py`.

## The report (third one, same feature)

Owner, after the session-clamp fix deployed: "still not complete deals and events data is coming... We
switched to the same source for events in research and odds moves page so looks like we are missing
something here." Correct instinct — same table, not the same WHERE clause.

## Root cause — confirmed with real data

Both the Research feed and `_events_for` read `nidp.corporate_announcements`, but a company's BSE-sourced
filings carry `company_name` with **`ticker_symbol` NULL** — a gap already discovered and partially fixed
elsewhere in this codebase (`documents.py`'s `_resolve_scrips`, "NSE/BSE identity split", 1,460 companies
affected per that investigation). `_events_for` was never updated to use that bridge; it still filters
`WHERE ticker_symbol = $1`, which structurally cannot match a NULL.

Confirmed for Knack specifically — all of its real announcements in the pinned view's window:
```
-- real query, nidp-stack-vm:
ticker | company_name            | subject                                              | date
KNACK  | Knack Packaging Limited | Trading Window                                       | 2026-09-25
(null) | Knack Packaging Ltd     | ...Closure of Trading Window...                      | 2026-09-25
(null) | Knack Packaging Ltd     | ...Schedule of Analyst / Investor Conference         | 2026-09-26
KNACK  | Knack Packaging Limited | Bagging/Receiving of orders/contracts (the order win)| 2026-10-02
(null) | Knack Packaging Ltd     | ...Received New Order and Renewal of Contract (dup.) | 2026-10-02
```
3 of 5 in-window rows were invisible to `_events_for` before this fix — including a BSE-sourced near-
duplicate of the very order-win filing the owner clicked.

## The fix

Ported the same normalized-company-name bridge `documents.py::_resolve_scrips`/`_norm` already uses
(measured there at zero cross-company collisions) into `_events_for`: resolve the ticker's own normalized
name(s) first (cheap — scoped by ticker, not a full scan), then also match `ticker_symbol IS NULL AND
norm(company_name) = ANY(names)`. **Strictly additive** — the existing `ticker_symbol = $1` branch is
untouched, so this can only add previously-missing rows, never remove or change an existing match. Shared
by every Movers mode, so MOVERS/FLAGGED/FORWARD get the same completeness improvement, not just Candidates.

**Known, bounded, pre-existing-pattern risk:** ran the same collision check the original bridge author
ran, against `nidp.corporate_announcements` specifically (the original was only measured against
`nidp.documents`): **9 of 2,481** normalized company names map to more than one ticker. All 9 are the
*same issuer's* different share-class tickers (DVR/partly-paid pairs: `TATAMTRDVR`/`TMCV`,
`JISLDVREQS`/`JISLJALEQS`, `LLOYDPP`/`LLOYDSENT`, etc.) — exactly the collision category the original
author already documented and accepted for the sibling bridge, not a cross-company leak. Worst case: a
DVR/demerged-sibling ticker's chart occasionally picks up an extra event that technically belongs to its
twin. Knack itself has zero collision.

## Test Cases

| ID | Scenario | Type | Result |
|----|----------|------|--------|
| TC-B1 | `_events_for` resolves the ticker's normalized name(s) via a ticker-scoped (not date-scoped) query, then threads them into the main query's 4th bind | unit (mocked conn) | PASS |
| TC-B2 | A symbol with zero ticker-tagged history resolves an empty name list; the main query still runs correctly, matching nothing extra (not a crash, not match-everything) | unit (mocked conn) | PASS |
| TC-B3 | `_norm_company` is byte-for-byte identical to `documents.py::_norm` | unit | PASS |
| TC-B4 | Regression: all 69 pre-existing `test_movers_v4.py`/`test_movers_proxy.py` cases pass unmodified | unit | PASS |
| TC-B5 | Real staging: the hand-run bridge SQL for KNACK returns all 5 real in-window announcements (2 ticker-tagged + 3 bridged), not just the 2 the old query found | data (live) | PASS |
| TC-B6 | Real staging: collision check on `nidp.corporate_announcements` — 9/2,481 names affected, all same-issuer share-class variants, none involving KNACK | data (live) | PASS (bounded, documented risk) |
| TC-B7 | Regression: all 77 frontend Playwright cases pass unmodified (mocked — unaffected by a backend-only change, run for confidence) | e2e (mocked) | PASS |

## Backend tests
```
cd backend && python -m pytest tests/test_movers_v4.py tests/test_movers_proxy.py -q
→ 72 passed in 0.58s   (69 pre-existing + 3 new)
```

## Data Correctness (staging, real, direct SQL — connection string never printed)
```
-- bridge query for KNACK, window [2026-09-01, 2026-10-31]: 5 rows (was 2 before this fix)
5f9326a... | KNACK  | Knack Packaging Limited | Trading Window                          | 2026-09-25
2d26752... | (null) | Knack Packaging Ltd     | ...Closure of Trading Window...          | 2026-09-25
3f22cf4... | (null) | Knack Packaging Ltd     | ...Investor Conference                   | 2026-09-26
7edccd1... | KNACK  | Knack Packaging Limited | Bagging/Receiving of orders/contracts    | 2026-10-02
40c1955... | (null) | Knack Packaging Ltd     | Received New Order and Renewal (dup.)    | 2026-10-02

-- collision check across nidp.corporate_announcements
colliding_names | total_names
9               | 2481
```

## What's left

Not deployed yet. Same remaining step as the last two increments: push to `dev`, let it auto-deploy, and
re-click Knack/Sobha in a real browser to confirm the richer event log actually renders end-to-end.

## Verdict: BLOCKED
<!-- TC-B1-B7 are real PASSes, including real staging SQL proving the fix's target behavior and a real
     collision measurement bounding its known risk. Only the end-to-end post-deploy click remains. -->
