# OVERRIDE — F&O contract chart read live from the broker (branch `feat/broker-contract-chart`)

REASON: Not on staging until the PR is merged into `dev`, and the end-to-end check — clicking an F&O position on the Trader desk and seeing its chart in the thread — needs the user's own signed-in session, which I do not have. Everything short of that is verified below: unit tests, typecheck, mocked Playwright, this branch's backend run read-only against ICICI Direct with the staging account, and the app's card drawn from those real responses. To finish: merge the PR, then click the COLPAL put and the COLPAL future on the Trader desk on staging.

- **Date:** 2026-10-14
- **Author:** Claude (full-stack developer + QA + design); the app-side card was built by a sub-agent to a written contract and re-verified by me.
- **Status of the work:** IN PROGRESS — code complete and tested off staging; staging check owed after merge.
- **Changed areas:** backend routes/services: yes · frontend src: yes

## What was asked (user, 2026-10-14 ~07:15 IST)
"Looks like we are looking at the stock rather than its F/O positions and hence we need to get the actual F/O chart live with icicidirect". The answer to a question asked from an F&O position showed the underlying share's card.

## What was built
- `GET /api/broker/accounts/{id}/contract-chart` — the price history (5-minute or 30-minute bars) and latest quote of one futures or options contract, read live from the broker, never stored. ICICI Direct only; any other broker answers `BROKER_READ_NOT_SUPPORTED`.
- `POST /api/chat/stream` accepts an optional `position`. For the caller's own redirect-connected account whose broker can serve a chart, the answer's card is `broker_contract_chart` (sent first, saved with the answer) and the engine's card for the underlying share is not sent.
- The app sends the position reference for F&O rows only, and draws the card: contract, broker, read time, last price, worked-out P&L, average, quantity, day high/low, previous close, underlying price, open interest, candles with volume and a line at the user's average, two views, "Read again".
- Read-only throughout: two GET reads at the broker; nothing is ordered, nothing is stored.

## Test cases
| ID | Area | Scenario | Type | Result |
|----|------|----------|------|--------|
| TC-1 | adapter | contract → Breeze's own words for a put, a call (fractional strike) and a future; GET only | unit | PASS |
| TC-2 | adapter | each view's Breeze interval name and window; candles oldest first, numbers, IST offset | unit | PASS |
| TC-3 | adapter | a bar with no time or price is dropped; missing volume / quote field stays null, never 0 | unit | PASS |
| TC-4 | adapter | quote 503 is tried once more; still failing → chart without a quote; other quote failures not retried | unit | PASS |
| TC-5 | adapter | failed candles fail the read without quoting the broker; a refused session on either call is session-expired | unit | PASS |
| TC-6 | adapter | unknown view (incl. `1d`), a share, an option with no strike, a bad expiry: refused before any call | unit | PASS |
| TC-7 | hub | `parse_contract` accepts a position row's values and refuses 22 malformed ones | unit | PASS |
| TC-8 | hub | chart read dispatch; nothing stored; not-supported; session ended by a refusal; no broker text in errors or logs | unit | PASS |
| TC-9 | route | 200 body; future without strike; default view; 422s; 404 for another user's account; 401; 400/409/502 codes; 403 when the flag is off | route (fakes) | PASS |
| TC-10 | chat | card built for the caller's ICICI account; none for a missing, malformed, foreign, OpenAlgo or unsupported-broker reference; never raises | unit | PASS |
| TC-11 | chat | stream: the contract card is the only card, is sent before the text, and is what is saved; without a position the engine's card is unchanged | route (fake engine) | PASS |
| TC-12 | app | F&O row click posts `position`; share rows do not; a retry keeps it | e2e (mocked) | PASS |
| TC-13 | app | card on a streamed and on a saved answer; figures; P&L sign for long and short; request query; view switch and "Read again" refetch | e2e (mocked) | PASS |
| TC-14 | app | states: no candles, no quote, field not sent, session ended, not supported, failed + retry, wrong shape; no trade control; IST in another time zone; 390 px | e2e (mocked) | PASS |
| TC-15 | live backend | this branch's hub and route against ICICI Direct, staging account, read-only | live | PASS |
| TC-16 | integration | the app's card drawn from the real responses of TC-15 | e2e on real data | PASS |
| TC-17 | staging | click the F&O position on the Trader desk | live UI | NOT RUN — needs merge + the user's session |

## Evidence (real output from this session)
- Backend, staging image: `python -m pytest <20 broker and chat test files> -q` → `1082 passed, 1 skipped, 1 warning in 15.08s`; `import server` works and `/api/broker/accounts/{account_id}/contract-chart` is registered.
- New-code mutation checks (`tests/test_broker_contract_chart.py`): engine card allowed to overwrite → `1 failed`; owner check removed → `2 failed`; card not sent first → `1 failed`; "every broker supports charts" → `2 failed`.
- Typecheck `npx tsc --noEmit -p tsconfig.json` → `TSC_OK`. Whole Copilot app Playwright suite → `336 passed (3.5m)`, `25 skipped`, 0 failed (was 316 / 23 before this branch).
- TC-15, hub (nothing stored — holdings count, snapshots, account status and last sync unchanged: `True`):
  - `1,760 put  5m  -> 312 candles | first 2026-10-07T09:35:00+05:30 | last 2026-10-13T15:35:00+05:30 close 21.85 | quote last 21.85 at 2026-10-13T15:38:34+05:30 spot 1801.0`
  - `1,760 put  30m -> 222 candles | first 2026-09-03T12:15:00+05:30 | last 2026-10-13T15:15:00+05:30 close 21.85`
  - `future     5m  -> 385 candles | … close 1805.0 | quote last 1805.0 at 2026-10-13T15:39:59+05:30 spot 1801.0`
  - `future     30m -> 379 candles | first 2026-08-31T09:15:00+05:30 | …`
- TC-15, route (signed-in user replaced by the staging account's owner; everything else real): four reads `HTTP 200`; `interval=1d` → `HTTP 422`; option without strike → `HTTP 422 | an option needs its strike price`; an unknown account → `HTTP 404 | Broker account not found`. The chat card built from the live position rows: `COLPAL 1,760 put · 27 Oct 2026 | qty 550.0 avg 35.88` and `COLPAL future · 27 Oct 2026 | qty 275.0 avg 1863.2`.
- TC-16: `title=COLPAL 1,760 put · 27 Oct 2026 | last=₹21.85 | avg=₹35.88 | qty=550 | pnl=−₹7,717 | spot=₹1,801.00 | prev=₹22.05 | caption=312 candles · 5 min each · 7 Oct, 9:35 am to 13 Oct, 3:35 pm` and `title=COLPAL future · 27 Oct 2026 | last=₹1,805.00 | avg=₹1,863.20 | qty=275 | pnl=−₹16,005`; request sent by the card: `?symbol=COLPAL&exchange=NFO&instrument_type=PE&expiry=2026-10-27&strike=1760&interval=5m`. `2 passed`. (P&L check: (21.85 − 35.88) × 550 = −7,716.5; (1805 − 1863.2) × 275 = −16,005.)

## Found in ICICI's data
- **Daily rows are not candles.** Their `close` is the previous day's close (13 Oct: 35.15, while that day's last trade and the quote were 21.85; three days × two contracts agree). The documented `1day` and `1minute` answer API status 500. So there is no daily view.
- **Bars can miss a brief extreme.** On 12 Oct ICICI's own day low for the put was 7.65; its 30-minute bars bottom at 14.15. Bars are drawn as ICICI sends them.
- **The quote call answers HTTP 503 under bursts** (two in a row answered, the next three did not). It is tried once more after 0.5 s; the card says when it is showing the last bar's close instead.

## Not verified / limits
- TC-17. Nothing here is on staging.
- The answer's text still comes from the stock analyst and discusses the underlying; it does not know the contract's live price that the card shows.
- No broker other than ICICI Direct can serve a contract chart (Zerodha rows carry a trading symbol, not the underlying; no reader exists).
- "Live" is a read when the card opens and on "Read again"; nothing ticks by itself.
- The card on the older `/chat` page and in the dock (both use the same widget switch) and the light theme are untested.
- ICICI allows 100 calls a minute and 5,000 a day per app key; each read of the card is two or three calls.

- **This is not a pass.** Resolve before merge to `main`.
