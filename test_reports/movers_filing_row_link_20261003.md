# Functionality Verification Report — Filing row → stock chart (pinned Candidates)

- **Branch:** `feat/movers-monday-candidates`
- **Date:** 2026-10-03
- **Author:** Claude (full-stack developer)
- **Environment:** mocked API (frontend Playwright). Not yet deployed — see "What's left."
- **Changed areas:** frontend src only: `pages/Research/index.tsx`, `MoveOddsScreen.tsx`, `MoversView.tsx`,
  plus `e2e/tests/research-movers-candidates.spec.ts`. No backend changes this increment.

## Summary

On the Research feed (`/v5/research`), a filing row's company name is now a button (only when
`features.move_odds` is on) that opens the Movers Candidates view pinned to that one filing — the real
candle chart and event timeline for that symbol, centred on that filing's own date, regardless of whether
the filing was "material" enough to appear in the day's `/api/movers/candidates` list. No new backend
endpoint: the one-row "list" is built client-side from data the feed already has (symbol, name, filing
date, one-liner), and the chart/timeline still come from the real `GET /api/movers/{symbol}` call, same as
every other candidate. A "← Back to filings" button (shown only on this pinned path) returns to the feed.

## Test Cases

| ID | Scenario | Type | Result |
|----|----------|------|--------|
| TC-F1 | Clicking a filing's company name opens Candidates mode pinned to that symbol/session; hero, chart, log, and the "opened from one filing" disclaimer all render | e2e (mocked) | PASS |
| TC-F2 | The back button returns to the filings feed (`mv-view` unmounts, `filings-list` reappears) | e2e (mocked) | PASS |
| TC-F3 | Without `features.move_odds`, a filing row has no stock link at all (no 403, no dead click target) | e2e (mocked) | PASS |
| TC-F4 | Regression: all 72 pre-existing cases across `research-movers-candidates`, `research-movers-v4`, `research-movers-v4-ui`, `research-movers`, `filings-intelligence`, `research-qa` still pass unmodified | e2e (mocked) | PASS |
| TC-F5 | Regression: 69 backend pytest (no backend change this increment, sanity-checked) | unit | PASS |

## Frontend build + tests

```
cd frontend-v5 && npx tsc -b
```
Output: (empty — exit 0, clean compile)

```
cd frontend-v5 && npx playwright test e2e/tests/research-movers-candidates.spec.ts \
  e2e/tests/research-movers-v4.spec.ts e2e/tests/research-movers-v4-ui.spec.ts \
  e2e/tests/research-movers.spec.ts e2e/tests/filings-intelligence.spec.ts e2e/tests/research-qa.spec.ts \
  --reporter=list
```
Output (tail):
```
  ✓  23 … clicking a filing's company name opens its chart, pinned to that filing (2.2s)
  ✓  24 … the back button returns to the filings feed (2.2s)
  ✓  25 … without move_odds, a filing row has no stock link (1.7s)
  … [72 other cases, all ✓, unmodified]
  75 passed (2.0m)
```

```
cd backend && python -m pytest tests/test_movers_v4.py tests/test_movers_proxy.py -q
```
Output: `69 passed in 0.49s` (unchanged — no backend edits this increment)

## API / Endpoint Tests (staging) — not applicable

Frontend-only change; no new backend route to curl. The existing `GET /api/movers/{symbol}` this reuses
was already confirmed live in `movers_candidates_20261003.md`.

## Data Correctness (staging) — not applicable

No new data path; the chart/timeline data comes from the already-verified `/api/movers/{symbol}` call.

## What's left

Not deployed yet (this increment, on top of the already-deployed Candidates mode). Same open item as
before: an authenticated live look confirms the click target and the back button on the real page — the
owner looking themselves, or a session token handed to this session.

## Verdict: BLOCKED
<!-- TC-F1-F5 (wiring, UI, regression) are real PASSes with real command output above. The one open item
     is the live authenticated look, which is a human-session gap, not a credential/logic gap. -->
