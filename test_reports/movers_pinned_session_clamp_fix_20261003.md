# Functionality Verification Report — pinned filing view: clamp session to the real latest trading day

- **Branch:** `feat/movers-monday-candidates`
- **Date:** 2026-10-03
- **Author:** Claude (full-stack developer)
- **Environment:** mocked API (frontend Playwright) + **real staging HTTP, confirmed with the owner's
  session token**. This is the first of the two pinned-filing bugs that's actually confirmed against real
  data, not just reasoned from source.
- **Changed areas:** frontend src only: `MoversView.tsx`, `e2e/tests/research-movers-candidates.spec.ts`.

## The report (second one)

Owner clicked "Knack Packaging Limited" on the live feed and got "No price history on record for KNACK
on the EQ series" — a harder failure than Sobha's empty log: a straight 404, despite a real, current
filing.

## Root cause — confirmed this time, with real data

```
-- staging, via nidp-stack-vm, psql:
SELECT max(as_of_date) FROM nidp.prices_eod WHERE series='EQ';           → 2026-10-01
SELECT symbol, max(as_of_date) FROM nidp.prices_eod WHERE symbol='SOBHA' → SOBHA|2026-10-01
SELECT symbol, series, min/max(as_of_date), count(*) FROM nidp.prices_eod
  WHERE symbol='KNACK' GROUP BY symbol, series                            → KNACK|EQ|2026-07-08|2026-10-01|61

-- the real feed row, via curl with the owner's session token:
GET /api/filings/feed?q=Knack  → {"ticker":"KNACK","code":"KNACK",...,"date":"2026-10-02T12:15:26+00:00",...}
```

Staging's price feed lags the filings feed by a day: every symbol's `nidp.prices_eod` stops at
**2026-10-01**, but filings land same-day (the Knack order win is dated **2026-10-02**). The pinned flow
was sending the filing's own date straight through as `session`. `mover_detail` centres the chart on
`session` and looks for a bar at or after it (`backend/.../movers.py`):

```python
ti = next((k for k, b in enumerate(bars) if b["t"] >= session.isoformat()), None)
if ti is None:
    raise HTTPException(404, f"{symbol} has no session on or after {session}")
```

No bar exists at or after Oct 2 (anywhere — this isn't KNACK-specific), so this always 404s. Confirmed
directly:
```
curl .../api/movers/KNACK?session=2026-10-02&range=1Y  → 404 {"error":"NOT_FOUND",...}
curl .../api/movers/KNACK?session=2026-10-01&range=1M  → 200, real bars (open 181.58, close 180.67, ...)
```

**This also explains why Sobha half-worked and Knack didn't**, and retroactively tells me my earlier "1M
window" fix (the broadcast_at/filed_at theory) was addressing a real but secondary gap, not this one —
Sobha's raw `filed_at` timestamp happened to UTC-slice to a date that still had a price bar (lucky), so
its chart rendered; Knack's didn't. Confirmed with real data that the SAME mechanism (clamped session +
wide-enough window) fixes both:
```
curl .../api/movers/SOBHA?session=2026-10-01&range=1M
  → bars: 22, events: 2, including "2026-10-02 General Updates" — the real filing, now found.
```

## The fix

`MoversView.tsx`'s pinned-candidate effect now makes one extra (TTL-cached, 300s) call to
`fetchMoverCandidates({limit:1})` purely to learn the real latest EQ session, and uses
`min(filing's own date, that session)` as the chart's `session` — never later than what the price feed
actually has. The filing's own date is never pushed forward, only pulled back when it's ahead of the
feed. If that lookup itself fails, falls back to the filing's raw date (previous behaviour, not worse).

## Test Cases

| ID | Scenario | Type | Result |
|----|----------|------|--------|
| TC-X1 | A filing dated after the latest priced session clamps the detail fetch to that session, not the filing's own date | e2e (mocked) | PASS |
| TC-X2 | No `mv-detail-error` ("no price history") state renders for that scenario | e2e (mocked) | PASS |
| TC-X3 | Real staging: `GET /api/movers/KNACK?session=2026-10-01` (the clamped value) returns 200 with real bars | api (live) | PASS |
| TC-X4 | Real staging: `GET /api/movers/SOBHA?session=2026-10-01&range=1M` returns the real 2026-10-02 event | api (live) | PASS |
| TC-X5 | Regression: all 77 pre-existing + prior-session cases still pass | e2e (mocked) | PASS |

## Frontend build + tests
```
cd frontend-v5 && npx tsc -b                                    → exit 0, clean
cd frontend-v5 && npx playwright test e2e/tests/research-movers-candidates.spec.ts \
  e2e/tests/research-movers-v4.spec.ts e2e/tests/research-movers-v4-ui.spec.ts \
  e2e/tests/research-movers.spec.ts e2e/tests/filings-intelligence.spec.ts e2e/tests/research-qa.spec.ts
  → 77 passed (2.0m)
```

## API Tests (staging, real, with the owner's session token)
```
curl -b "session_token=..." https://staging.niveshcopilot.com/api/movers/KNACK?session=2026-10-02&range=1Y
  → 404 NOT_FOUND (reproduces the reported bug exactly)
curl -b "session_token=..." https://staging.niveshcopilot.com/api/movers/KNACK?session=2026-10-01&range=1M
  → 200, real OHLC (proves the fix's target behaviour works once deployed)
curl -b "session_token=..." https://staging.niveshcopilot.com/api/movers/SOBHA?session=2026-10-01&range=1M
  → 200, 22 bars, 2 events incl. "2026-10-02 General Updates" (the real filing, now found)
```

## What's left

The fix itself is verified both ways (mocked UI behaviour + real staging data proving the target call
works) — stronger evidence than the previous increment. What's not yet verified is the actual deployed
**frontend** making this exact clamped call end-to-end (I confirmed the backend behaves correctly when
called correctly; I haven't re-clicked Knack/Sobha in a real browser since this fix was built). Needs
this to deploy and a re-click.

## Verdict: BLOCKED
<!-- TC-X1-X5 are real PASSes, including two live API calls against real staging data proving the fix's
     target behaviour. Only the end-to-end "click it in a real browser after deploy" step remains. -->
