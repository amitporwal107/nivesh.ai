# Live near-month futures (Kite websocket) on the F&O OI build-up tab

- Branch: feat/provider-foundations (uncommitted) · Date: 2026-10-23 · Environment: local + a read-only scratch run in the staging backend container against real Kite
- Changed: backend (kite_live_feed universe/feed/gateway, routes/live_quotes.py) and frontend (tradingdesk/live-futures.ts, FnoBuildup.tsx)

## What changed
The platform feed also subscribes the nearest unexpired futures contract of every F&O underlying (219), in Kite websocket `full` mode (the only mode with open interest); cash stocks stay in `quote` mode. New API universe `futures`: GET /api/live/snapshot?universe=futures. The F&O tab shows "Live fut" and "Live OI" columns only while the feed mode is live. The end-of-day OI-change column is all-expiry; the live OI is near-month: never subtracted.

## Real output (this session)
- Kite websocket, 214 stock futures, full mode, 12 s: `connected True err None | ticks received for 214 of 214 | with OI 214 | with depth 214`
- Changed code (copied to a scratch dir, nothing in the running service touched): `near_month_futures: 219 | first 360ONE26OCTFUT 2026-10-27 | expiries ['2026-10-27']` and `ticker connected True healthy True | ticks 60 | with oi 60 | with oi_day_high 60`; sample `360ONE26OCTFUT ltp 1009.5 oi 3190500 oi_hi 3538500 oi_lo 3164000`
- Backend: `python -m pytest tests/test_kite_live_feed.py tests/test_kite_intraday.py tests/test_kite_platform_login.py -q` -> `77 passed` (new: nearest expiry, full vs quote mode, NFO: prefix on the REST fallback, OI and underlying on the quote, futures universe on the API, no-futures feed unchanged)
- Typecheck: `tsc_exit=0`
- Playwright (production build, mocked /api): copilot-app-desk-lab -> `24 passed, 2 skipped` (the two screenshot specs); new cases: live columns while live, "—" for a contract Kite sent nothing for, end-of-day columns untouched, no live columns when closed / delayed / expired / not_connected, a failing live read leaves the table as it was.

## UNVERIFIED
- The deployed path: restart of the feed leader with the new code, the snapshot size with ~220 more quotes, the real /api/live/snapshot?universe=futures body through the app, and the live columns in the deployed UI.
- Behaviour across the 27 Oct expiry (the code picks the next contract; covered by a unit test only).
