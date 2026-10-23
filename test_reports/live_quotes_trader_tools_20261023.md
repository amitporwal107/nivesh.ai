# Live Kite quotes across the trader tools

- Branch: feat/screener-live-futures (on origin/dev) · Date: 2026-10-23 · Environment: local, production build, every /api call mocked
- Test cases: live_quotes_trader_tools_TESTCASES.md (written after the audit and the first edit, before the other four)
- Changed (frontend only): Risk desk range bar, Smart-money evidence rail, Setups to watch, Reversal detail, F&O lab spot

## Audit
Already live before this change: desk Overview, Chart, Scanner and Portfolio tabs, the Trader screen, the F&O build-up (added earlier today), the Watchlist.
Closed here: the Risk desk price marker (was the last close), the Smart-money rail price and day change, a Live column on Setups to watch, the live price beside the Reversal levels, the F&O lab headline spot (Nifty 50 / Nifty Bank by their tape names, a stock by its symbol).
Left alone on purpose: entry / stop / target (plans), historical deal and event prices, broker positions (the broker's own LTP), Paper desk P&L (recorded on end-of-day marks server-side), the chain, walls and model figures in the F&O lab (bhavcopy; the label says so), FINNIFTY / MIDCPNIFTY / NIFTYNXT50 spot (no index-name mapping in the app).
Rule everywhere: a live price shows only while the feed's mode is "live"; otherwise the end-of-day figure stays, and a stock with no quote keeps its end-of-day figure.

## Real output (this session)
- `npx tsc --noEmit -p tsconfig.json; echo tsc_exit=$?` -> `tsc_exit=0`
- Playwright, production build, copilot-app-desk-reversal + desk-smart-money + workspace + desk-scanner + desk-lab -> `168 passed (2.4m)`, `2 skipped` (screenshot specs), `1 failed`
- The one failure: `copilot-app-desk-smart-money.spec.ts:243 TC-F3` expects "Disclosed 1 Sept 2026 · 51d ago"; the page says "52d ago" because today is 23 Oct. It depends on the date, is in code this change does not touch, and fails the same way without it. Not fixed here (no drive-by changes).
- New cases, all passing: Risk desk live / closed, Smart-money rail live / closed, Setups to watch Live column / no column when closed, Reversal live / closed, F&O spot live / closed.

## UNVERIFIED
- Everything against the real Kite feed in the deployed UI: these edits are not on staging, and the feed needs a restart after the PR from earlier (futures subscription) is merged. Live prices in these panels use the existing shared live store, which was already working on the cash-stock surfaces.
- Phone layout of the added Live column and labels was not checked.
