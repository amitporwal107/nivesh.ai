# Keep and show the Kite closing quotes (2026-10-23): test cases, authored before implementation

Ask: when the market is closed, show the last Kite quotes if the end-of-day data is not built yet, and save the live
quotes at the close.

Today: the feed takes ONE final REST read after the close and publishes it as the `latest` snapshot (`final: true`).
That document is overwritten at the next open and expires after 72 hours; nothing keeps a copy per day. The shared
overlay (`useLiveOverlay`) already shows that closing quote labelled "Close · date · Kite" when it is from a session newer
than the screen's own end-of-day day (`eodDay`). Gaps: the futures hook accepts only a live feed; the Smart-money rail,
Reversal detail and F&O spot pass no `eodDay`, so they can never show a closing quote; Setups to watch only draws its
column while live.

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| TC-1 | backend | the final snapshot after the close is also saved as a per-day document (`kite_live_close`, id = the IST trading day) with every quote, futures included | unit | doc present, count equals the snapshot's |
| TC-2 | backend | a second final publish on the same day replaces that day's doc; a later day keeps the earlier one | unit | two docs after two days |
| TC-3 | backend | an intraday (non-final) publish never writes a close doc | unit | none |
| TC-4 | backend | a failing close write is logged, never raised, and the snapshot still publishes | failure | snapshot served |
| TC-5 | backend | GET /api/live/close returns the newest saved close (or ?date=) as mode closed, final true, with the day; 404-shaped empty answer when none; 400 on a bad date | api | body shape |
| TC-6 | backend | signed-out is 401 | api | 401 |
| TC-7 | backend | existing 77 kite tests still pass | regression | pass |
| TC-8 | e2e | futures hook: closed + final snapshot newer than the bhavcopy day shows "Close" figures with a Close header; older or equal day shows nothing | e2e | columns / none |
| TC-9 | e2e | F&O spot, Smart-money rail, Reversal detail: a closing snapshot newer than their end-of-day day shows the close labelled Close · Kite, not Live | e2e | labels |
| TC-10 | e2e | the same snapshot with a day equal to the end-of-day day shows the end-of-day figure only (warehouse caught up) | e2e | unchanged |
| TC-11 | e2e | Setups to watch draws the Live/Close column from a closing snapshot | e2e | column |
| TC-12 | static | tsc clean; existing desk, screener, workspace specs pass | regression | pass |
