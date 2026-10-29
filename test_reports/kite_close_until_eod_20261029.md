# Functionality Verification Report — Kite close until EOD (stocks: Live chart + Portfolio), PR 1

- Date: 2026-10-29, 17:06 IST (after the 15:30 close, before the 19:00 cash bhavcopy)
- Branch: fix/kite-close-until-eod (from origin/dev f5c299b9)
- Environment: staging data, code run IN-PROCESS in `nivesh-staging-app-backend` from an overlay of the changed files
  (read only, nothing deployed, nothing written); UI by Playwright against a local build with mocked API
- Test cases: test_reports/kite_close_until_eod_TESTCASES.md

## Summary
Owner rule (29 Oct): while the market is live show live data; after the close show the Kite closing data until the EOD jobs
load the exchange's prices. The Trade Desk › Live chart (daily fallback when 15m candles are unavailable) ended on the
previous session (ADANIPORTS 28 Oct, 1,761.3) although the saved Kite close of 29 Oct (1,872.0, +6.3 %, above the 1,823.8
entry) existed. Fixed with one shared backend rule (`services/kite_live_feed/day_quote.py`) used by the live-chart route, and
the Portfolio position chip now shows the move at Kite's close after the session (it showed nothing).

Scope of THIS PR (no silent cuts):
- Covered: Live chart daily candles, LAST, headline, conditions (server-side); Portfolio "today's move" chip.
- Already followed the rule before this PR (frontend `pick()` with the screen's EOD day): Market Desk chart (ChartTab
  `withLiveBar`), Stock Research blocks, Risk desk, sector heatmap, screener, scanner, reversal, setups, AI watchlist, personal
  and research watchlists, market strip, MarketTab cells, F&O build-up scanner and candidates (`useLiveFutures`).
- NOT covered (PR 2): F&O option chains, futures by month, expiries, strategy ideas/plan (these read the evening bhavcopy and
  show the previous session until it lands). The saved Kite close holds only near-month futures and NIFTY/BANKNIFTY options
  (±15 strikes, 2 expiries): stock options and next/far futures are not saved, so the feed must save them first.
- Deliberately NOT changed: paper fills, exits, marks, risk gate, alerts, plan sizing (decision paths stay on exchange data).
- Reverted during the work: a backend Kite bar in /api/research/chart-live. The frontend already appends and LABELS the Kite
  close there; a backend bar would have shown it as an end-of-day close without the "Kite" label.

## Test Cases
| ID | Case | Result |
|---|---|---|
| U1–U10 + 4 | shared rule: joins, EOD wins, does_not_join (split), not traded today, gap/holidays, candle range, live vs close, feed not live, no saved close, last-close day, read failure | PASS (pytest) |
| R1, R1b, R2 | live-chart route: Kite close appended / left out when it does not join / EOD wins | PASS (pytest) |
| S1, S3 | staging: ADANIPORTS, RELIANCE end on the 29 Oct Kite close; bar == kite_live_close doc | PASS |
| S1b | staging: NIFTYBEES (not in the Kite feed) stays on the 28 Oct exchange bar, today_why no_quote | PASS |
| P1 (KC-1), P2 (KC-2), TC-18 | Live chart labels: "Kite close", provisional note, headline, source line; old wording without a Kite bar | PASS (Playwright) |
| KC-3 | Portfolio chip after the close: "+2.1%", data-kind close, "Close · 29 Oct · Kite, provisional" title | PASS (Playwright) |
| S4 | after the 19:00 bhavcopy the exchange bar wins on staging | UNVERIFIED (needs the merge + deploy; covered by R2/U2) |

## API / Endpoint Tests (staging)
Command: `docker exec -w /app/backend nivesh-staging-app-backend python /tmp/probe_final.py` (overlay of day_quote.py and
desk_live_chart.py, calls `live_chart(symbol=..., interval="15m", sessions=2)`), run at 17:06 IST. Real output:
```
S1 ADANIPORTS: interval=1d today={"used": true, "source": "kite_close", "day": "2026-10-29", "provisional": true, "at": "2026-10-29T15:30:57+05:30", "price": 1872.0, "text": "2026-10-29: Kite close, provisional until the exchange's end-of-day file"} today_why=None
   last={'price': 1872.0, 'at': '2026-10-29', 'bar_complete': True, 'source': 'kite_close'} prev_bar=['2026-10-28', 1747.0, 1781.8, 1727.6, 1761.3] last_bar=['2026-10-29', 1797.0, 1872.0, 1775.1, 1872.0, 7792103.0]
   S3 bar == kite_live_close doc: True; Kite prev close 1761.3 == EOD 28 Oct close 1761.3: True
S1 RELIANCE: interval=1d today={"used": true, "source": "kite_close", "day": "2026-10-29", "provisional": true, "at": "2026-10-29T15:30:57+05:30", "price": 1167.4, "text": "2026-10-29: Kite close, provisional until the exchange's end-of-day file"} today_why=None
   last={'price': 1167.4, 'at': '2026-10-29', 'bar_complete': True, 'source': 'kite_close'} prev_bar=['2026-10-28', 1194.5, 1204.3, 1156.4, 1158.0] last_bar=['2026-10-29', 1159.0, 1182.1, 1155.6, 1167.4, 20750193.0]
   S3 bar == kite_live_close doc: True; Kite prev close 1158.0 == EOD 28 Oct close 1158.0: True
S1 NIFTYBEES: interval=1d today=null today_why=no_quote
   last={'price': 259.59, 'at': '2026-10-28', 'bar_complete': True, 'source': 'eod'} prev_bar=['2026-10-27', 259.4, 260.61, 258.25, 259.49] last_bar=['2026-10-28', 259.28, 260.0, 256.83, 259.59, 8085305.0]
```
Before the fix (same container, deployed code, 16:5x IST): `last: {'price': 1761.3, 'at': '2026-10-28', ...}`, last bar 2026-10-28,
trigger "waiting".

Backend tests: `pytest tests/test_kite_day_quote.py tests/test_desk_live_chart.py tests/test_research_chart_live.py
tests/test_kite_live_feed.py tests/test_live_quote_cache.py` → `155 passed, 2 warnings in 8.78s`.

## UI / Playwright Tests
Build `vite build` + `vite preview` in mcr.microsoft.com/playwright:v1.47.0-jammy, `--network none`, API route-mocked
(MOCK — not real data). Typecheck `npx tsc --noEmit` → `TSC_EXIT=0`.
- `copilot-app-desk-live-chart.spec.ts` + `copilot-app-desk-portfolio-fno.spec.ts` (whole files): `11 skipped, 45 passed (42.1s)`
  (the 11 skips are tests already marked skip in those specs).
- New cases, list reporter:
```
  ✓  3 … Live chart › KC-1 after the close, before the exchange's end of day: the last daily candle is the Kite close, labelled provisional (1.6s)
  ✓  1 … Live chart › KC-2 without a Kite candle the daily fallback keeps the end-of-day wording and no Kite label (2.2s)
  ✓  2 … Live chart › TC-18 no Kite session: daily candles labelled, the bhavcopy day for the OI, the signal's levels; a pending order (2.4s)
  ✓  4 … Portfolio & risk › KC-3 after the close a position shows the session's move at Kite's close, labelled close (not live) (995ms)
  4 passed (10.1s)
```

## Data Correctness (staging)
- `kite_live_close` 2026-10-29: saved 10:01:02 UTC (15:31 IST), 1,087 quotes, source rest.
- ADANIPORTS quote in it: ltp 1872.0, open 1797.0, high 1872.0, low 1775.1, prev close 1761.3, volume 7,792,103,
  exchange_ts 15:30:57 IST. The appended bar equals it field by field (S3 True).
- Join check: Kite's previous close equals the exchange's adjusted 28 Oct close for ADANIPORTS and RELIANCE.
- Caveat (labelled on screen): the Kite figure is the last traded price read at ~15:31; the exchange's official close
  (bhavcopy, evening) can differ slightly. It is shown as "provisional until the exchange's end-of-day file".

## Inputs required from user
- Merge of this PR (a merge to dev deploys staging; backend needs its restart, frontend its image rebuild).
- Separate, not in this PR: the "Kite login needed for 15m candles: session expired" message appears although the platform
  Kite token is valid until 06:00 IST (obtained 09:41 IST today): non-leader workers keep the stale env token. The fix is on
  the unpushed branch fix/kite-token-all-workers (96ba7098); its push was refused earlier and needs the owner.

## Verdict: PASS
