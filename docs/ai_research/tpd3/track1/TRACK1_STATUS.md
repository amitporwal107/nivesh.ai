# Track 1 — build status (2026-09-19, overnight)

**Built, tested and dry-run; not yet used on a live session.** First live session: Mon 2026-09-21 (watchlist ready).
Code: `research/track1/` · 19 unit tests · outputs per session in `/app/research/reports/<session>/`.

| Plan item | Deliverable | Status |
|---|---|---|
| Days 1–3 | Evening watchlist from `nidp.prices_eod` (no Kite needed), write-once, run manifest with scope SHA-256, data freshness | Done; 2026-09-21 watchlist: 1,243 symbols, CERTIFIED |
| Days 4–5 | Append-only, hash-chained signal ledger: WATCHLIST → TRIGGER_APPROACHING → ENTRY_CONFIRMED → CLOSED / EXPIRED / INVALIDATED; manual fills as separate events; tamper detection | Done; 4 tests incl. tampering |
| Days 6–7 | Post-close outcome job: official prices, 5-minute bars (Kite → local store → UNRESOLVED), H-A and H-B under spec v2 with the 5-position cap, exception report | Done; exit rules shared and tested on every branch |
| Days 8–10 | Operational dry run + HTML report | Done on 10 past sessions (below) |

## Operational dry run (historical sessions, local 5-minute store)
| session | watchlist s | outcome s | signals | at band | H-B unresolved | open mismatch | status |
|---|---|---|---|---|---|---|---|
| 2026-04-13 | — | — | 154 | 9 | 91 | 4 | DEGRADED |
| 2026-09-07 | 1.6 | 20.9 | 3 | 2 | 0 | 1 | DEGRADED |
| 2026-09-08 | 1.4 | 1.0 | 0 | 0 | 0 | 0 | UNRESOLVED → now NO_SIGNALS (fixed) |
| 2026-09-09 | 1.5 | 22.0 | 4 | 1 | 2 | 0 | DEGRADED |
| 2026-09-10 | 1.4 | 21.4 | 4 | 2 | 2 | 0 | DEGRADED |
| 2026-09-11 | 1.4 | 21.3 | 20 | 3 | 12 | 0 | DEGRADED |
| 2026-09-15 | 1.4 | 22.1 | 7 | 5 | 2 | 0 | DEGRADED |
| 2026-09-16 | 1.4 | 21.7 | 6 | 4 | 2 | 0 | DEGRADED |
| 2026-09-17 | 1.4 | 22.5 | 9 | 4 | 5 | 0 | DEGRADED |
| 2026-09-18 | — | — | 7 | 5 | 1 | 0 | DEGRADED |
All runs completed; ledgers verify. DEGRADED = some H-B outcomes UNRESOLVED because the local 5-minute store is still
being filled (live runs fetch the day's bars from Kite after the close).

## Known limitations found by the dry run
1. **The frozen at-band exclusion is broader than a circuit lock.** It excludes any open within 0.25pp of −5/−10/−20%,
   including ordinary −5.1% opens in 20%-band stocks (only ~31% of those excluded in discovery were locked all day).
   Registered in spec v1/v2, so unchanged; a future spec should use NSE's per-stock price band.
2. **Historical 5-minute bars carry later corporate-action adjustments**, so a few historical opens mismatch raw bhavcopy
   (flagged DATA_ERROR, never used). Live same-day bars are unaffected.
3. **ETFs are flagged, not excluded** (spec v2 includes them). Their opening prints broke the sealed H-A test; excluding
   them needs a spec change approved by the owner.
4. **No live alerting yet**: v0 relies on the owner watching the open in his own Kite app; alerts via Kite WebSocket are v1.

## Monday 2026-09-21 routine
Evening before: watchlist (done). Morning: owner logs in to Kite (token for the day's bars). After the close, once
`nidp.prices_eod` has the session: `python research/track1/outcomes.py --session 2026-09-21 --bars kite`, then open
`/app/research/reports/2026-09-21/daily_signal_report.html`. Manual fills: add `manual_fills.csv` before the run.

## Spec v3 in the outcome job (2026-09-19 08:40 IST)
`outcomes.py` now runs under `TRACK1_SCOPE_v3.md`: ETFs excluded via `nidp.security_reference_daily.is_etf`; band exclusion
uses each stock's own band (No Band / F&O never excluded); missing band row -> BAND_UNKNOWN, not traded; historical
sessions without band rows fall back to the locked-09:15-bar rule. 23 unit tests. Live-band check (separate dry-run
folder): 2026-09-18 — 7 signals, 5 excluded as OPEN_AT_OWN_BAND (ATALREAL, RHETAN, INDOTHAI, ONIXSOLAR, ELITECON: 5%/10%
band stocks opening at the band price to the paisa), TATACHEM and TATAINVEST (20% bands) correctly kept; CERTIFIED.
**Bug caught by that check and fixed:** psql CSV writes booleans as 't'/'f', and bool("f") is True, which briefly marked
every stock an ETF.

