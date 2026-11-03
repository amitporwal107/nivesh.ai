# Functionality Verification Report — Copilot open trades on the user's BROKER book (+ the 5 s live design)

- **Branch:** feat/copilot-broker-book (PR to dev; stacked on nothing: #430/#431 are merged)
- **Date:** 2026-10-31 / 2026-11-01
- **Author:** Claude (full-stack developer + QA)
- **Environment:** unit tests in `nivesh/backend:staging` (`--network none`, CI env); read-only in-process runs inside `nivesh-staging-app-backend` over the owner's REAL broker sessions and staging data (nothing written); Playwright on a production build with mocked APIs. Not deployed.
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary
The owner's screenshot of "What are my open trades doing?" showed only 3 PAPER trades. The answer now reads the user's BROKER book: by their broker
configuration it asks them to connect a broker (none), asks them to sign in again and shows the LAST STORED read dated, never as live (session ended),
or shows the live positions of every account with the broker's own P&L, the user's stop/target (or the plan they recorded), distance to the stop, the loss
at the stop (never the stock at zero), expiry, margin required (Zerodha's calculator) and each account's available cash / collateral / used margin. The paper
trades stay beside it, labelled Paper. The platform computes every figure and the written commentary explains the deterministic checks list (no model arithmetic).
The page keeps the answer live every 5 seconds while the market is open (design below) without ever polling a broker faster than once per 15 s per account.
**Not in this PR:** broker trades in the daily review (PR 2, `feat/copilot-broker-trades`).

## Design decision: "live data refreshed every 5 seconds" and broker rate limits
Asked: refresh every 5 s. A broker is NOT asked every 5 s. What each tick does and why:

| Layer | Cadence | Source | Calls a broker? |
|---|---|---|---|
| The page | every 5 s (`refresh.interval_s`, never faster; only while the tab is visible, the answer is on screen, built today, and the server has not said stop) | `GET /api/positions/book/live` | no |
| Share prices and the distance to the stop | every tick | the platform's Kite feed (Redis per-symbol cache, at most ~1 s old) through `day_quote.day_quotes`; only while the feed is live | no (the platform feed; no per-user call) |
| A share's P&L | every tick | the broker's own P&L of its last read moved by quantity x (live price - the price in that read); labelled "live" | no |
| Futures and options prices, quantities, the broker's P&L | at most once per 15 s per ACCOUNT | the broker's own positions read; the newest `position_snapshots.last_seen_at` in Mongo is the cache, so four uvicorn workers and any number of tabs share it; one in-process lock coalesces concurrent requests | yes, <= 4/min/account |
| Account funds | at most once per 60 s per account per worker | `read_account_funds` | yes, <= 1/min/account/worker |
| Analysis (chains, payoff, loss at the stop) and margin | at most once per 90 s / 120 s per worker, and again when the holdings change | the positions service; Zerodha's calculator | margin: Zerodha calculator (not a position read) |

Alternatives considered and why not: (1) poll the brokers every 5 s: 12 reads/min/account; ICICI Breeze documents 100 calls/min and 5,000/day per API key, so a 6 h 15 m
session of 5 s polling is 4,500 position reads alone: no. (2) Server-sent events from the backend: the Kite feed already publishes on its own cadence and a per-user broker book is not a
broadcast; polling a cache is simpler and survives the four-worker setup. (3) An in-process per-worker cache: four workers would each call the broker; the Mongo snapshot is shared.
(4) Kite REST `quote()` for stock options every 5 s: Kite allows 1 request/s on the platform key shared by all users; a per-user 5 s poll does not scale. NOT built: so futures and options
prices update with each broker read (<= 15 s), not every 5 s, and each row says when it was read (hover). A shared batched quote cache would close that gap if the owner wants it.
Degradation: a failed ask keeps the blocks already shown, the chip says "Live feed lost - showing the read of hh:mm:ss IST", backs off (10 s, 20 s ...) and stops after three failures.
Stop rules: after the close the server answers `refresh.active=false` and the chip says "Updates stopped: the market is closed - as of hh:mm:ss IST".
Snapshot volume: a polled read refreshes the latest `position_snapshots` document in place when what the account HOLDS is unchanged (prices and P&L moved) and adds a document only when the
holdings change (`store.record_book_snapshot`), so a day of polling leaves one document per change, not one per tick.

## Test Cases
> Authored before the implementation (backend `tests/test_open_book.py`, frontend `e2e/tests/copilot-app-open-book.spec.ts`).

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| OB-1 | state | no broker connected | unit | one notice with the Connect action, paper trades kept and labelled, no refresh | PASS |
| OB-2 | state | broker hub switched off for the user | unit | notice without an action, paper kept | PASS |
| OB-3 | state | session ended, a stored read exists | unit | "sign in again" action; rows badged "As of <time>", never "Live"; funds "Not available" with the reason; no broker call; no refresh | PASS |
| OB-3b | state | stored read older than the previous session | unit | the stale banner and notice name its date | PASS |
| OB-4 | state | session ended, nothing stored | unit | says there is no stored read; no positions block | PASS |
| OB-5 | live | live book | unit | broker P&L is the broker's; ICICI F&O rows with `pnl: null` are marked at the last price and say so; shares move with the live price; unmapped rows kept | PASS |
| OB-6 | names | ICICI's own stock codes (invented rows in the tests) | unit | labelled with NSE names | PASS |
| OB-7 | levels | the user's stop/target, distance, loss at the stop, expiry; a protective put does not flip the stop's direction | unit | numbers equal the analytics; no to-zero loss anywhere | PASS |
| OB-8 | failure | one account fails / a broker refuses the session mid-read | unit | reported alone; the other account unaffected; stored read shown dated | PASS |
| OB-9 | plans | recorded plan agrees / conflicts / only the system built it | unit | levels borrowed only when it agrees; conflict reported; a system plan is never "your plan" | PASS |
| OB-10 | margin | calculator present / absent | unit | F&O legs only, shares "None (shares)"; absent -> "Needs Kite login" + kite_login/connect_broker | PASS |
| OB-11 | funds | available, collateral, used margin; a funds failure | unit | each account's own figures; failure on that account only | PASS |
| OB-12 | rate | two tabs / six concurrent requests / a minute at 5 s ticks | unit | one broker read inside 15 s; <= 5 reads and <= 2 funds reads in 60 s of 5 s ticks | PASS |
| OB-13 | store | quote ticks vs a changed holding | unit | one snapshot document while holdings are unchanged; a new one when quantity changes; tenant-scoped | PASS |
| OB-14 | marks | live overlay | unit | shares only, from the read not cumulative, never over a stored read or a closed-market close; distance to stop and warnings follow | PASS |
| OB-15 | pnl | broker_pnl rules incl. shorts | unit | broker figure kept; marked only when the broker sent none | PASS |
| OB-16 | route | GET /api/positions/book/live | contract | 401 unauthenticated; blocks validate; active false after the close; another user sees none of it; 502 on a fault | PASS |
| OB-17 | contract | refresh envelope | unit | absent when the market is closed or nothing is live; validate rejects interval < 5 and a non-/api path | PASS |
| OB-18 | secrets | payload scan (live and sign-in-again) | unit | no account id, token or key | PASS |
| OB-19 | facts | commentary reaches the model, nothing cut, no advice words | unit | all items in `facts()`, under the size cap | PASS |
| OB-20 | read-only | source scan | unit | no place/modify/cancel call in the book, builder or hub reads | PASS |
| OB-21..25 | intents, headline, unmapped, funds subs | | unit | see the test names | PASS |
| FO-1..12 | UI | connect prompt; sign-in again with dated rows; live book; 5 s asks (never sooner); hidden tab pauses and resumes; market closed stops; failure degrades and gives up after 3; yesterday's answer is a record; bad block ignored; phone width; wide; no order button | e2e | see the spec | PASS |

## API / Endpoint Tests (staging)
- **pytest** (`WT=/home/deploy/nivesh-wt-broker pt.sh tests/test_open_book.py -q`): `38 passed` (final head; run again after the last edit).
- **CI allowlist on a full layout** (PR 1 head `44e2a39d`): `13 failed, 7709 passed, 34 skipped` against the baseline of 13 failures on origin/dev: the failing NAMES are identical (`comm` of the failing names = 0 differences; the 13 are cron-line / schedule tests that read files outside the repo layout).
- **Real staging, read-only**, deployed code (dev f30c7019) BEFORE, the owner's own user (his screenshot reproduced):
```
validate: [] | headline: 3 open paper trades, unrealised ₹1,101.62.
-- kpis summary | Your open paper trades
-- ranked trades | 3 open paper trades
     ROW SONACOMS ... ROW COFORGE ... ROW ICICIBANK ...   (paper only)
```
- **AFTER**, this branch over the same staging data, 1 Nov 2026 03:09 IST, unedited (ICICI Direct's session ended at midnight, so this is the SESSION-ENDED state on the real stored read of 31 Oct; Zerodha's session is live with no positions):
```
(redacted copy: the committed report carries no figure or holding of the owner's; the unedited output is in the session transcript)
validate: [] | as_of 2026-11-01 | mode eod | stale False | refresh None
headline: {'text': '5 open broker positions in 3 underlyings, unrealised <amount> (a stored read, not live); 3 open paper trades, unrealised <amount>.', 'tone': 'down'}
-- notice ended-icicidirect-0 | Your ICICI Direct session has ended, so live positions, funds and margin are not available. Sign in to ICICI D | actions ['connect_broker']
-- kpis book | Your broker book | actions 
     KPI Broker positions = <figure> | ICICI Direct 5, Zerodha 0
     KPI Unrealised P&L = <figure> | the brokers' own figures; 2 marked at the last price
     KPI Margin required = <figure> | Zerodha's calculator, F&O legs (2 of 2 underlyings)
     KPI Available cash = <figure> | the brokers' own figures
     KPI Used margin = <figure> | the brokers' own figures
-- ranked positions | Broker positions · 5 | actions 
     ROW badge=As of 31 Oct 11:01 cells=<redacted: the owner's real position> | tips ['ltp', 'pnl', 'qty']
     ROW badge=As of 31 Oct 11:01 cells=<redacted: the owner's real position> | tips ['ltp', 'pnl']
     ROW badge=As of 31 Oct 11:01 cells=<redacted: the owner's real position> | tips ['ltp', 'pnl']
     ROW badge=As of 31 Oct 11:01 cells=<redacted: the owner's real position> | tips ['ltp', 'pnl', 'qty']
     ROW badge=Not mapped cells=<redacted: the owner's real position> | tips ['symbol']
-- ranked levels | Stops, loss at the stop and margin, by underlying | actions 
     ROW badge=None cells=<redacted: the owner's real position> | tips ['symbol', 'spot', 'stop', 'risk', 'margin']
     ROW badge=None cells=<redacted: the owner's real position> | tips ['symbol', 'spot', 'risk', 'margin']
     ROW badge=None cells=<redacted: the owner's real position> | tips ['symbol', 'spot', 'risk', 'margin']
-- ranked accounts | Your broker accounts | actions 
     ROW badge=None cells=<redacted: the owner's real position> | tips ['avail', 'collateral', 'used']
     ROW badge=None cells=<redacted: the owner's real position> | tips []
-- list commentary | Checks against your stops and plans | actions 
     - warn <commentary item: redacted, names the owner's holdings>
     - warn <commentary item: redacted, names the owner's holdings>
     - warn <commentary item: redacted, names the owner's holdings>
     - warn <commentary item: redacted, names the owner's holdings>
     - warn <commentary item: redacted, names the owner's holdings>
     - warn <commentary item: redacted, names the owner's holdings>
     - None <commentary item: redacted, names the owner's holdings>
     - None <commentary item: redacted, names the owner's holdings>
     - None <commentary item: redacted, names the owner's holdings>
     - None <commentary item: redacted, names the owner's holdings>
     - None <commentary item: redacted, names the owner's holdings>
-- kpis summary | Your open paper trades | actions 
     KPI Open = <figure> | None
     KPI Unrealised P&L = <figure> | net of estimated costs
     KPI Not yet triggered = <figure> | waiting for its entry condition
-- ranked trades | 3 open paper trades | actions 
     ROW badge=None cells=<redacted: the owner's real position> | tips []
     ROW badge=None cells=<redacted: the owner's real position> | tips []
     ROW badge=None cells=<redacted: the owner's real position> | tips []
-- notice read-only | Nivesh reads your broker positions; it cannot place, modify or cancel an order. These are checks to review, no | actions 
sources: [('Your broker positions (read from the broker)', '2026-11-01', 'fresh'), ('Your broker positions (last stored read) · ICICI', '2026-10-31', 'fresh'), ("Your broker accounts' funds (read from the broke", '2026-11-01', 'fr
missing: []
facts chars: 5294 complete
secrets check: []
```
- **AFTER while ICICI Direct's session was live** (31 Oct ~22:26 IST, Saturday, market closed; an earlier revision of the code, same data; figures withheld from the committed report): five broker rows (two shares, one future, one option, one gold-bond row ICICI's master does not list, shown as unmapped), named through ICICI's own security master; the shares' P&L was the broker's own figure; ICICI sent `pnl: null` for both F&O rows (the old service showed 0.0 as "the broker's own figure"; now marked at the last price and said so); margin came from Zerodha's calculator through the user's own session (a bought put's margin equalled its premium: correct); the future's underlying borrowed the plan the user had recorded; funds came from ICICI `/funds` (the figures are in the owner's decision 1 below).
  Real-data findings this run caught that mocks hid: (1) ICICI F&O rows carry `pnl: null` (shown 0.0 before); (2) my first group-direction rule called a share position with a put under it "short" and "past your stop" (net delta): fixed, a stop faces the underlying legs; (3) a negative cash balance printed "₹-…" and a nonsense percentage of it: fixed;
  (4) notice ids carried the account id: fixed; (5) the overlay probe's own symbol-map path mapped nothing (probe artefact, fixed in the probe).
- **Live tick on the same data:** `TICK refresh {'active': False, 'interval_s': 5, 'why': 'the market is closed'} mode eod blocks ['book','positions','levels','accounts','commentary']`.

## UI / Playwright Tests
Production build `BUILD_EXIT=0`; `tsc --noEmit` `TSC_EXIT=0`.
- `copilot-app-open-book.spec.ts` (13 tests, fake clock) with the visual-answer regression set from `copilot_batch2_20261031.md` (fno-detail, risk-profile, fno-board, sector-rotation, visual-answer, app, desk, desk-decision-cards, positions, daily-trader, desk-copilot-window, desk-risk-phase1, desk-risk-desk, desk-smart-money): **`236 passed, 4 skipped`** (the 4 skips are the opt-in screenshot tests).
- Screenshots looked at (OB_SHOTS/FNO_SHOTS=1): phone cards for positions (Live badge, minus signs true, nothing sideways), wide tables; the harness's forced 1100 px box clips the right-hand columns of the wide shot (harness artefact, as in FE-10).

## Data Correctness (staging)
- The positions shown equal what ICICI Direct's `portfoliopositions` returned (raw fields compared in this run; codes mapped through ICICI's own security master (every code but one gold-bond row resolved)).
- Funds: ICICI `/funds` returned `allocated_*`, `block_by_trade_*` and `unallocated_balance`; the adapter's definition (allocated - blocked; `unallocated_balance` not counted) gave a small negative "available" on this account while `unallocated_balance` was about 10,000 times larger: whether that is what the owner wants called "available cash" is a DECISION (below).
- No secret in any payload (checked in this run: `secrets check: []`).

## Not verified (see OVERRIDE_copilot_broker_book.md)
Market-hours behaviour on a live session (Kite prices over real positions, the 5 s page), the first Zerodha rows, the funds meaning, the deployed browser.

## Decisions for the owner
1. ICICI "available cash": the adapter's allocated - blocked gave a tiny negative figure here while `unallocated_balance` was thousands of rupees: which figure should the answer call available?
2. Futures/options prices tick every <= 15 s (broker's own read), shares every 5 s. A shared batched Kite quote cache would make options 5 s too: build it?
3. A plan counts as "yours" only when your id is in its owners (you built or opened it); the AI watchlist's system plans never become your levels.

## Verdict: PASS
(For everything verified above; the live-market items are an explicit OVERRIDE, not a pass.)
