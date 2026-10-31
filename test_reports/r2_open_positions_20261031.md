# Functionality Verification Report — Open Positions workspace (Release 2)

- **Branch:** feat/r2-open-positions (from origin/dev; origin/dev merged twice, last at #426)
- **Date:** 2026-10-31
- **Author:** Claude (FULL_STACK_DEVELOPER + DESIGN_ENGINEER + QA_ENGINEER)
- **Environment:** unit tests in `nivesh/backend:staging`; read-only in-process run inside `nivesh-staging-app-backend`; Playwright on a production build with mocked APIs. Not deployed.
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary
A workspace for what the user holds open today, separate from My Portfolio: broker positions (every connected account,
read live, net book) and the desk's open paper trades, labelled Broker / Paper, grouped by NSE underlying. Per group: legs,
the broker's own P&L, Greeks, payoff and breakevens, a scenario table (move × volatility × days), distance to the user's
stop, the loss at that stop, margin (Zerodha's calculator), warnings. `/app/page/positions`, a nav row, and an
"Open positions" tile on the portfolio ledger. Read-only: no route here can place, modify or cancel an order.

**Owner design.** There is no dedicated Open Positions design. The owner's Trader screen
(`frontend-v5/design/nivesh-copilot/NVTrader.dc.html`) has the table this follows exactly — "Open positions · broker,
read-only": Position · Qty · Avg · LTP · P&L · Stop · Target · Risk left, the headline sentence ("Two positions are near
their stops"), the tiles, and "Nivesh reads positions; it cannot place orders". Brief #3's wording (separate My Portfolio and
Open Positions workspaces) covers the rest. Where the design shows a stop and target per broker position, they are the
user's own (brokers send none).

## Test Cases
> Authored up front, from `docs/daily_trader_copilot/audits/D_portfolio_hub.md` §3, §5, §7 and brief #3.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| PS-1 | normalise | ICICI codes through ICICI's own security master (SONBLW→SONACOMS, CNXBAN→BANKNIFTY, RELIND→RELIANCE); an unlisted code | unit | NSE underlying + canonical key; unlisted code unmapped with the reason | PASS |
| PS-2 | normalise | Kite symbols: monthly/weekly options, futures, `M&M`, `NIFTYNXT50`, shares | unit | contract parsed; non-F&O symbol unmapped, not guessed | PASS |
| PS-3 | normalise | a monthly Kite contract's expiry day | unit | the listed futures expiry of that month; none listed → unmapped | PASS |
| PS-4 | normalise | no expiry / no strike from the broker | unit | unmapped with the reason, never valued | PASS |
| AN-1 | risk | long future with a stop | unit | loss at the stop; `max_loss` null, never a to-zero figure; no stop → no figure + warning | PASS |
| AN-2…4 | payoff | bull call spread; naked short call; future + long put | unit | max loss/profit and breakeven exact; unbounded loss has no max loss; hedged future is defined risk | PASS |
| AN-5 | stop/target | long and short, near / past / reached | unit | distance, direction-aware; warnings `near_stop`, `stop_breached`, `target_reached` | PASS |
| AN-6, 7 | today's value | repricing at the pricing spot; an option without implied volatility | unit | at the spot reproduces the mark (P&L at entry ≈ 0); no IV → no "today" column, never a guess | PASS |
| AN-8, 9 | Greeks / expiry | position Greeks; expiry-soon; delivery warning for stock F&O only | unit | sums by sign×units; delivery warning not shown for index contracts | PASS |
| ST-1…4 | store | level bodies validated; trail never loosens a stop; snapshots only on change; save/delete | unit | 9 bad bodies refused with a reason; 1 snapshot for 2 identical reads; `broker_as_of` null | PASS |
| SV-1…6 | service | grouping, stale chain, live quote beats bhavcopy, paper trades, per-account read failure, summary | unit | each account reported alone; a stale chain gives no figure and says why; day realised P&L null with a note | PASS |
| RT-1…4 | routes | every request body: PUT levels (8 bad bodies, 1 good), DELETE, scenario inputs (moves/iv/days/key) | contract | 422 with reason / 404 / 200 with the exact shape; no working fields leak | PASS |
| OP-1…14 | screen | headline/tiles/sources; both tables and columns; near-stop flag; loss at stop; no-stop shares; spread legs+Greeks+chart; scenario ask; save/refuse levels; delete; margin; labels + unmapped; ended session + Reconnect; empty and error states; ledger tile + 390 px | e2e | each value computed from the payload | PASS (14/14) |
| REG | regression | `copilot-app`, `copilot-app-desk`, `copilot-app-desk-decision-cards` | e2e | no new failure | PASS |
| CI | regression | full backend CI allowlist, FAILED names vs origin/dev | unit | no new failure | PASS |

## API / Endpoint Tests
No staging deploy exists, so the routes were exercised through FastAPI's test client with the real route code, and the service
in-process on real staging data (below).

- **pytest (new):** `python -m pytest tests/test_positions.py -q` (container `nivesh/backend:staging`, `--network none`)
  - Output: `43 passed, 2 warnings in 6.06s` (re-run after each merge of origin/dev)
- **App imports with the route:** `import server` → `True` for `/api/positions` registered.
- **Full CI allowlist, baseline re-measured on a clean `git archive origin/dev` (286 files):**
  - origin/dev: `20 failed, 7556 passed, 34 skipped in 206.72s`
  - this branch (287 files = dev's + `test_positions.py`): `20 failed, 7599 passed, 34 skipped in 213.10s`
  - FAILED names, sorted and compared: **identical lists** (`comm -13` and `comm -23` both empty). +43 passed = the new tests.

## UI / Playwright Tests
Production build (`VITE_USE_MOCK_API=false VITE_BASE=/v5/ vite build`) served by `vite preview`, `pw.copilot-app.config.ts`,
`--network none`.
- `tsc --noEmit -p tsconfig.json` → `TSC_EXIT=0`; `vite build` → `BUILD_EXIT=0`, `✓ built in 23.66s`.
- `copilot-app-positions` + `copilot-app-desk` + `copilot-app-desk-decision-cards` + `copilot-app` → **`82 passed (39.4s)`** (positions 14).
- **What the first runs found (fixed, not hidden):** (1) 13 of 14 failed: the screen's schema rejected the fixture — its two
  real paper groups predated the `risk_to_stop_rs` field I added to the analytics. The schema was right; the fixture was
  stale. Recaptured from staging with the current code (below) → 13 of 14 passed. (2) OP-11 searched for the Broker/Paper
  pill in the detail body, but it sits in the section header: a test-locator error; added a `positions-detail-title` testid.
- Fixture `e2e/fixtures/positions.mock.json` is **MOCK for the broker groups** and says so in its `about`: the two paper groups
  are the real staging response; the broker groups are the real `services/positions` code over constructed inputs, because the
  account's broker sessions had ended. Real trade ids were replaced by neutral ones.

## Data Correctness (staging, read-only, in-process)
Overlay of this branch's modules ahead of the deployed tree inside `nivesh-staging-app-backend`; auth stubbed to a real
staging user (shown as a hash); every Mongo write routed to a proxy that records and discards it. Output below is the run's,
aggregate only (no account numbers, tokens or personal data).

1. **ICICI code map vs the NSE bhavcopy.** 45 ICICI F&O codes (40 random + SONBLW, CNXBAN, NIFTY, RELIND, ICIBAN, NIFFIN, NIFSEL):
   `lot equal 45, lot differs 0, not current on NSE 0, not in map 0` — each mapped NSE symbol is current on the F&O bhavcopy and
   its futures lot size equals the lot size in ICICI's own master.
2. **Real contracts at their real settle** (NIFTY 3 Nov 2026 chain of 30 Oct; spot 23,053.10, forward 23,026.59, lot 65):
   a bull call spread 23050/23350 entered at the settle prices (103.90 / 17.45; IV 11.98% / 11.58%).
   `greeks {'delta': 22.34, 'gamma': 0.041233, 'theta': -462.02, 'vega': 298.26}`; breakeven 23,136.45; max loss −5,619.25; max
   profit 13,880.75 (basis expiry). **Check: today's P&L at the pricing spot = −0.27** (≈ 0 for a position entered at the mark,
   as it must be). SONACOMS future entered at its settle: today's P&L at the spot = 0.0; the loss at a stop 5% below is
   ₹54,965.80, i.e. ₹44.87 × 1,225, the future moving in proportion to the spot.
3. **The whole route for the real account.** Both broker accounts: `ok False error BROKER_SESSION_EXPIRED` (reported per account,
   the other source unaffected). Paper: `ok True`, 2 held trades + 1 waiting entry; `unrealised_pnl_rs 1101.62`;
   SONACOMS pnl 486.20, 7.4% from the stop, loss at stop ₹1,947.88; COFORGE pnl 615.42, 6.85%, ₹1,906.20 — the same P&L figures
   the desk's paper screen returned in the earlier Release 2 capture (486.20 and 615.42). `day_realised_pnl_rs: null` with a note.
4. **Writes:** only index creations were attempted and blocked (`desk_paper_trades`, `desk_price_alerts`, `position_levels`,
   `position_snapshots`). Result: PASS for what was readable.

## UNVERIFIED (see OVERRIDE_r2_open_positions.md)
- **No real broker position has been read by this code.** Both sessions had ended; the owner signs in daily. Normalisation,
  grouping and pricing are verified on real codes, real lot sizes and real settle prices, and the broker-row path with
  constructed rows only.
- **Kite monthly-contract expiry day** (`NIFTY26NOV23000CE` → listed futures expiry of the month) is unit-tested, not seen on a
  real Zerodha row.
- **The Kite live / saved-close price path** was not exercised on real data: the run found `why no_saved_close` (no saved Kite
  close for 30 Oct), so the underlying fell back to the NSE end-of-day price, as the rule requires. Seen in tests only.
- **`position_snapshots` / `position_levels` writes** are tested against a fake store; nothing was written to staging Mongo.
- **Margin** needs the platform's Kite login of the day; the screen's 503 path is tested, a real figure was not obtained.
- A live signed-in walk of the deployed screen.

## Decisions for the owner
1. **Broker day realised P&L is not shown** (the tile reads "—", with the reason): no position read separates it. A fix needs
   a trade-book read per broker (not built). Say if you want that next.
2. **Stops and targets on real positions are Nivesh-side only** (`position_levels`, per underlying). Nothing is sent to a
   broker; a trailing stop moves only when the page is read, not continuously.
3. **Paper trades' levels are read-only here** (change them on the desk), to avoid two places to edit one stop.
4. The positions book is read on page open and on "Refresh", never polled (brokers rate-limit).

## Not built (outside this item)
Broker order/trade history, a stored per-position history beyond change-only snapshots, intraday Greeks from a live option
chain (end-of-day / T-1 settle is used, labelled with its date), and the Hub fixes and holdings charts of the same release.

## Inputs required from user
- The owner's daily broker sign-in and a deploy, for the live walk (OVERRIDE).

## Cleanup
Test containers `r2pos-*` removed. The staging overlay `/tmp/ov_r2pos` was left in place when its removal was denied by the
safety check (I did not retry it another way); on the final check `/tmp/ov_r2pos` was no longer present in the container, so it
was probably reset by someone else. Nothing in the staging container, database or env was changed.

## Verdict: PASS
Scope: the backend (43 tests; the allowlist has the same 20 failures as origin/dev), the screen against a payload with MOCK
broker groups, and the read-only staging run on real codes, lot sizes, settle prices and paper trades. The real broker-position
check and the live walk are open and covered by `OVERRIDE_r2_open_positions.md`.
