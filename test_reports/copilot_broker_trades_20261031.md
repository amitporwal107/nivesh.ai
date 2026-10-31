# Functionality Verification Report — Broker trades in the Copilot's daily review

- **Branch:** feat/copilot-broker-trades (PR to dev; contains PR #435's commits: merge #435 first)
- **Date:** 2026-11-01
- **Author:** Claude (full-stack developer + QA)
- **Environment:** unit tests in `nivesh/backend:staging` (`--network none`, CI env); read-only in-process runs inside `nivesh-staging-app-backend` over the owner's REAL broker sessions (writes stubbed); no frontend change (the review uses the existing block types), so no new Playwright spec. Not deployed.
- **Changed areas:** backend routes/services: yes · frontend src: no

## Summary
The owner (31 Oct 2026): the daily review ("What did I learn from today's trades?", "Did I follow my entry, stop-loss and exit rules?") "should also consider broker trades".
No broker adapter had a trade-book read, so this adds read-only readers (Zerodha `trades()`, ICICI Direct `/trades`; every other broker is "not supported" with its reason),
a kept day per account (brokers return only the current day), FIFO matching into round trips, and a labelled BROKER section in `daily_review`. The paper review is unchanged.
Plan adherence is assessed only where the user's own stop (set before the trade closed) or a plan they recorded (before it opened) existed; otherwise "no plan recorded".

## Design notes
- `broker_trade_days`: one document per account and IST day, change-only (an identical read only moves `last_seen_at`; a longer list replaces `trades`, `version` + 1), tenant-scoped on `user_id` AND `account_id`, trade fields only (no token, key or account number). Kept by the existing 17:30 IST broker daily sync (while the day's session is live; a failure never fails the holdings sync) and by any review that asks (60 s cache). A quiet weekday is kept ("looked, nothing traded"); a quiet weekend day is not.
- Matching: per account and contract, FIFO across the days kept; a partial fill closes part of a lot; partial fills of one order are one round trip; quantity in UNITS as the broker sends it (an F&O lot's units); a sell with no buy on record is an UNMATCHED leg shown as open, never assumed to be a short; realised P&L = the broker's own fill prices, gross (no charge is estimated; `fees_rs` only when every fill of both sides carries the broker's own figure).
- Adherence (deterministic, from the user's own levels and plans): a stop set after the trade closed, or a plan recorded after it opened, is not used and says so; price levels apply to shares and futures; an option's premium is compared with a plan's direction only.

## Test Cases
> Authored before the implementation (`backend/tests/test_broker_trades.py`).

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| BT-1 | reader | Zerodha `trades()` | unit | only `trades()` is called (a fake Kite fails any other call); buy/sell, quantity, price, time, product; a zero-quantity row skipped | PASS |
| BT-2 | reader | ICICI `/trades` (recorded-shape MOCK rows) | unit | endpoint "trades", one call per exchange (NSE, NFO), body keys exchange_code/from_date/to_date; cash, option (Put -> PE, strike, expiry), future; a "Hold" row is not a fill | PASS |
| BT-3 | hub | no reader / session ended / refused token | unit | "<Broker> has no trade-book reader" (not an empty list); no broker call without a live session; a refused token ends the session; only Zerodha and ICICI Direct support it | PASS |
| BT-4 | store | change-only, cache, quiet days, tenant, secrets | unit | one doc per day; identical read -> last_seen only; growth -> version 2; 60 s cache; quiet weekday kept, weekend not; another user sees nothing; no secret in the document | PASS |
| BT-4b | sync | daily sync | unit | keeps the book; a capture failure never fails the sync | PASS |
| BT-5 | match | long round trip with two partial entries | unit | one trip, 2 fills, weighted entry, P&L from the broker's prices | PASS |
| BT-5b | match | short | unit | sell first then buy back gains when the price falls | PASS |
| BT-5c | match | F&O future and stock option in units, partial exits, ICICI code named as NSE | unit | quantity 1225 units, P&L = units x price difference per partial exit; "SONACOMS 24 Nov 2026 FUT"; option kind/instrument | PASS |
| BT-5d | match | a sell with no buy on record | unit | an unmatched leg with the note; never a short | PASS |
| BT-5e | match | carry across days; `through_day` | unit | entry day kept on the trip; open lots stop at the asked day | PASS |
| BT-5f | match | fees; accounts | unit | fees only when every fill has one; a buy in one account is not closed by a sell in another | PASS |
| BT-6 | states | live / ended with kept days / no reader / non-native / hub off | unit | each account's state with its reason; stored days named | PASS |
| BT-7 | adherence | stop honoured or not, short stops, target, no plan | unit | assessed only with a stop or plan in force; "No plan recorded" otherwise | PASS |
| BT-7b | adherence | stop set after the close; plan after the open | unit | not used, said so | PASS |
| BT-7c | adherence | plan entry offset, conflict, options by direction | unit | "2.00% above the plan's entry"; "against a bearish plan"; a long put is bearish | PASS |
| BT-8 | review | no broker data | unit | block ids and headline identical to the paper-only review | PASS |
| BT-8b | review | one stopped-out round trip and one unmatched sell | unit | broker blocks labelled Broker; every paper block unchanged and in order; "Stop not honoured"; headline = the paper sentence + "Broker: 1 round trip closed (0 wins, 1 loss), realised −₹50.00 gross"; the source listed; the facts reach the model | PASS |
| BT-8c | review | trip with no stop or plan | unit | "No plan recorded"; "not assessed" | PASS |
| BT-8d | review | Angel One (no reader), Zerodha ended with 2 kept days | unit | a notice each, with the reason and the Sign-in action | PASS |
| BT-8e | review | the week; a failed trade-book read | unit | realised from days 27 and 29 Oct; a missing source, no broker block | PASS |
| BT-9 | read-only | source scan | unit | no place/modify/cancel call in the trade-book code or the two readers | PASS |

## API / Endpoint Tests (staging)
- **pytest** (`WT=/home/deploy/nivesh-wt-broker pt.sh tests/test_broker_trades.py -q`): `21 passed`; with the neighbouring suites (copilot_visual, chat, open_book, positions, suggestions, every test_broker_* file): `997 passed, 2 skipped` (before the weekend-skip edit; `tests/test_broker_trades.py` rerun after it: 21 passed).
- **CI allowlist on a full layout:** see the final section (run on this branch's head).
- **Real staging, read-only**, this branch over the owner's real accounts, 1 Nov 2026 (Sunday), `daily_review` day and week, unedited (stores stubbed):
```
KEEP would store 0 fills for 2026-11-01          <- Zerodha's live session: kite.trades() answered, 0 fills (market shut)
== day: validate [] | as_of 2026-10-30 | stale False
headline: Nothing was recorded on 1 Nov 2026; the latest session with activity is 30 Oct 2026. No paper trade closed; the risk checks refused 3 of 3 entry requests.
  NOTICE broker-icicidirect-0-ended | Your ICICI Direct session has ended, so today's trades could not be read. Sign in to ICICI Direct again to include them. No day of its trade book has been kept. | actions ['connect_broker']
== week: validate [] | as_of 2026-11-01 | stale False
headline: No paper trade closed this week; the risk checks refused 19 of 25 entry requests.
  NOTICE broker-icicidirect-0-ended | (same)
```
  So: the Zerodha live read path runs against the real Kite session (the call is `trades()`, read-only); ICICI's ended session gives the Sign-in action; with no day kept yet, no broker section appears and the paper review is the same as before (BEFORE = this output without the notice).

## UI / Playwright Tests
No frontend change: the section uses `kpis`, `ranked`, `list` and `notice` blocks the app already draws (the open-book spec and the visual-answer regression set of PR #435 cover those components).

## Data Correctness (staging)
No real broker FILL has been read yet (Zerodha had none; ICICI's session had ended; it is a weekend), so matching and the field mapping were verified only on recorded-shape MOCK fixtures. See the OVERRIDE.

## Decisions for the owner
1. Open the broker daily capture to your account only after you sign in each day: the 17:30 IST daily sync keeps the day only while a session is live; a day with no sign-in is simply not kept (the answer names the days it has). Is that acceptable, or should a missing day prompt a reminder?
2. Fees: neither Kite's `trades()` nor ICICI's documented row carries charges, so the review's P&L is gross and says so. A contract-note import would give net.

## Verdict: PASS
(For the mocked and read-only parts above; the live-fill items are an explicit OVERRIDE, not a pass.)
