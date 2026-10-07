# Functionality Verification Report — pinned filing view: widen the default window

- **Branch:** `feat/movers-monday-candidates`
- **Date:** 2026-10-03
- **Author:** Claude (full-stack developer)
- **Environment:** mocked API (frontend Playwright). Root cause reasoned from source, **not confirmed
  against real staging data** — GCP credentials expired again mid-session; see "What's left."
- **Changed areas:** frontend src only: `MoversView.tsx`, `e2e/tests/research-movers-candidates.spec.ts`.

## The report

Owner clicked "Sobha Limited" on the live `/v5/research` feed (the filing-row link shipped this session)
and got the Movers chart with an empty event/deal log — "0 EVENTS" — despite the feed showing a real,
current, high-impact Sobha filing.

## Root cause (reasoned from source, not yet confirmed live)

Two backend paths disagree about which timestamp dates a filing:
- The Research feed (`backend/routes/markets.py::_row`, both the DaaS `market_pulse.py` primary path and
  the Postgres `_articles()` fallback) sets the row's `date` from **`filed_at`** only.
- The Movers event log (`.../movers.py::_events_for`) filters `nidp.corporate_announcements` by
  **`COALESCE(broadcast_at, filed_at)`** — `broadcast_at` wins when present.

The pinned-filing flow I shipped derives its chart `session` from the feed row's `date` (i.e. `filed_at`)
and previously defaulted to the **T7** range (±7 days). If an announcement's `broadcast_at` sits more than
~7 days from its `filed_at` — plausible for exchange filings, where filing and broadcast aren't always
same-day — the event genuinely falls outside that window and `_events_for` correctly returns nothing for
it. The log isn't broken; it's asking the right question over too narrow a window.

I did **not** confirm this is actually what happened for this specific Sobha filing (would need a real
query against `nidp.corporate_announcements` for its `filed_at` vs `broadcast_at`) — GCP access was gone
again when I went to check. The fix below is robust regardless of the exact skew, which is why I'm
shipping it without that confirmation rather than blocking on it.

## The fix

`MoversView.tsx`: the pinned flow now defaults `range` to **1M** (±30 days) instead of T7, specifically
when arriving via a filing's deep link (`?symbol=&session=`). Everywhere else (MOVERS/FLAGGED/FORWARD/the
general Candidates list) is untouched — still T7. The reader can still widen further (3M/1Y) from the
existing range buttons if even that isn't enough.

## Test Cases

| ID | Scenario | Type | Result |
|----|----------|------|--------|
| TC-W1 | The pinned detail fetch requests `range=1M`, never `T7` | e2e (mocked) | PASS |
| TC-W2 | The 1M range button shows pressed/active on arrival | e2e (mocked) | PASS |
| TC-W3 | Regression: all 76 pre-existing + prior-session cases across the movers/filings/research-qa specs still pass | e2e (mocked) | PASS |

## Frontend build + tests

```
cd frontend-v5 && npx tsc -b
```
Output: (empty — exit 0)

```
cd frontend-v5 && npx playwright test e2e/tests/research-movers-candidates.spec.ts \
  e2e/tests/research-movers-v4.spec.ts e2e/tests/research-movers-v4-ui.spec.ts \
  e2e/tests/research-movers.spec.ts e2e/tests/filings-intelligence.spec.ts e2e/tests/research-qa.spec.ts \
  --reporter=list
```
Output (tail): `76 passed (2.0m)`

## What's left

Not confirmed against real data: whether Sobha's specific filing now shows up with a 1M window, and
whether `broadcast_at` vs `filed_at` skew is really the mechanism (vs., say, a narrower but still-real
gap this doesn't fully cover). Needs either a refreshed GCP token (to query `nidp.corporate_announcements`
directly and/or re-check via SSH) or the owner re-testing the live Sobha link after this deploys. If it's
still empty after this fix, that's a stronger signal the real cause is something else (e.g. a genuine
symbol mismatch) and the diagnosis above was wrong — worth saying plainly if it recurs.

## Verdict: BLOCKED
<!-- TC-W1-W3 (the fix's own behavior + regression) are real PASSes. Whether this actually fixes Sobha is
     unconfirmed against real data — a live re-test or a refreshed credential is what closes this out. -->
