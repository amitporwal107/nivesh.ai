# API_DOCUMENTATION.md — Nivesh.ai / NIDP

> Canonical detail: `TECHNICAL_ARCHITECTURE.md` §9 (DaaS), §10 (Nivesh App).
> Live specs (the real contract): Nivesh `https://niveshcopilot.com/api/docs`,
> DaaS `https://data.niveshcopilot.com/daas/docs` (OpenAPI 3.1). If code and this doc
> disagree, the OpenAPI/code wins — fix the doc.

## Two APIs
| API | Base | Auth | Scale |
|---|---|---|---|
| Nivesh App | `https://niveshcopilot.com/api` | Google OAuth 2.0 + session cookie; admin `Bearer <ADMIN_TOKEN>` | 180+ endpoints |
| NIDP DaaS | `https://data.niveshcopilot.com/daas` | `X-API-Key: nvd_…` or `Bearer nvd_…`; admin `Bearer <NIDP_DAAS_INTERNAL_TOKEN>` | external, key-gated |
| NIDP Query | `https://data.niveshcopilot.com/query` | internal Bearer | ops/feeds |

## DaaS conventions (§9)
- **Plans:** `free`, `standard`, `pro`, `internal`. Key format `nvd_` + 32-char hex.
- **Rate limit headers:** `X-RateLimit-*`, `X-Daily-*`; `429` + `Retry-After` on exceed.
- **Pagination:** `limit` (1–5000, default 100) + `offset`; `pagination.next_offset`.
- **Envelope:** `{ "data": [...], "pagination": {...}, "meta": { "as_of", "source":"nidp" } }`.
- **DQ envelope (Gate 6, partial):** responses may include `data_quality.dq_status`
  GREEN/AMBER/RED + `degraded_feeds[]` — check it when asserting data is fresh.
- **Endpoint groups:** health, admin(keys), me, catalog, prices, corporate_actions, indices,
  reference, financials, fno, flows, announcements, macro, snapshots, features, mutual_funds,
  mf_performance, events, intelligence, dq_ai, replay, backfill (+ Query API: feeds, validation,
  quality, vm_ops, archive).

## Nivesh App route groups (§10)
`/api/auth`,`/oauth` · `/user` · `/portfolio` (holdings, CAS upload, time-machine) · `/plans`
(V2 action plans) · `/goals` (Monte Carlo) · `/intelligence` · `/insights` · `/chat`,`/copilot`
(LangGraph + SSE) · `/market` · `/broker` (9 brokers) · `/compliance` (DPDP) · `/mfd` · admin
groups `/api/admin/{datastores,nidp,users,rules,secrets,flags}` · `/portfolio-remediation` ·
`/portfolio-exposure`.

## Broker hub (`/api/broker`, read-only)
A user connects one or more brokers, and one or more accounts per broker. Sign-in happens on the
broker's own page; Nivesh stores only the session token (encrypted) and never a password, PIN or
TOTP. Nothing here can place, modify or cancel an order. Status: built on `feat/broker-hub`,
unit-tested with stubbed HTTP; **not yet verified against a live broker or on staging**.

| Route | Returns |
|---|---|
| `GET /native/supported` | `brokers[]`: `slug, name, auth_style, implemented, configured, connectable` |
| `GET /native/start/{slug}?return_to=<same-site path>` | 302 to the broker. 404 unknown, 400 not connectable, 503 app keys not set |
| `GET /native/callback?broker={slug}` or `/native/callback/{slug}` | 302 to `return_to` (default `/dashboard`) with `broker_connected=<slug>&account_id=<id>` or `broker_error=<code>` |
| `POST /native/callback/{slug}` | for brokers that return by a cross-site form POST (ICICI Direct): 303 to the same path as a GET with the posted value in the query. Does no sign-in work itself; 405 for other brokers |
| `GET /accounts` | existing keys + `native, broker_user_masked, session_expires_at, session_ended_reason, needs_reconnect`; `status` may be `expired` |
| `POST /accounts/{id}/sync` | `{ok, count, holdings[]}`; replaces only that account's holdings. A redirect-connected account also returns `snapshot_id` (null if the snapshot could not be written) and `duplicates{repeated_in_broker_reply, same_instrument_lines, broker_file_rows_replaced, statement_rows_replaced, also_in_other_accounts}` |
| `GET /accounts/{id}/snapshots?limit=30` (1–90) | `{account_id, broker, snapshots[]}`, newest first: `snapshot_id, synced_at, trigger (connect\|manual\|daily), count, total_value_rs, total_invested_rs, priced, duplicates`. 404 for an account that is not the caller's |
| `GET /snapshots/{snapshot_id}` | one snapshot in full: the list fields plus `broker_account_id, broker, broker_display, broker_user_masked, holdings[]` (`name, ticker, isin, asset_type, quantity, buy_price, current_price, sector, source_id`). 404 unless it is the caller's |
| `GET /accounts/{id}/positions?kind=net\|day&segment=all\|fno\|intraday` | `{account_id, broker, kind, segment, as_of, positions[], counts{total,fno,intraday}}`; live, not stored |
| `GET /positions?kind=&segment=` | the same per connected account: `accounts[]` with `ok`, `error{code,message}`, `as_of` |
| `GET /accounts/{id}/contract-chart?symbol=&exchange=&instrument_type=FUT\|CE\|PE&expiry=YYYY-MM-DD&strike=&interval=5m\|30m` | `{account_id, broker, broker_display, contract{symbol,exchange,instrument_type,expiry,strike}, interval, as_of, candles[], quote}` — the price of the futures or options contract itself; live, not stored |
| `DELETE /accounts/{id}` | removes the account, its token, its holdings and its sync snapshots |

- `broker_error` codes: `denied, missing_params, unknown_broker, invalid_state, state_expired, token_exchange_failed, server_error` (the broker signed the user in but Nivesh could not save the session).
- The server must have `PII_ENCRYPTION_KEY` to store a session token. Without it `supported` reports nothing as `configured` or `connectable`, and `start` answers 503.
- Position fields: `symbol, exchange, quantity (signed), avg_price, last_price, pnl, product, product_raw, segment (equity|fno|commodity|currency), is_intraday, instrument_type (FUT|CE|PE), expiry, strike, kind, name`. A field the broker does not return is null.
- Read errors carry a stable `code`: `BROKER_SESSION_EXPIRED` (409, reconnect needed), `BROKER_READ_NOT_SUPPORTED` (400), `BROKER_READ_FAILED` (502).
- Contract chart: the contract is named by its position row's own `symbol`, `exchange`, `instrument_type`, `expiry` and
  `strike` (omit `strike` for a future); anything else is a 422. `candles[]` are oldest first:
  `time` (ISO, exchange offset), `open, high, low, close, volume, open_interest` (the last two may be null).
  `quote` is null when the broker's quote could not be read, else `last_price, last_traded_at, open, high, low,
  previous_close, change_pct, spot_price, volume`, each null when not sent. Views: `5m` (about 7 days) and `30m`
  (about 45 days); there is no daily view. ICICI Direct only today — any other broker answers
  `BROKER_READ_NOT_SUPPORTED`. Same `broker_hub` flag as positions.
- Feature flag `broker_hub` (default everyone): off gives 403 `feature_not_enabled` on start, native sync and positions. Listing and disconnecting are not gated.
- A session ends at the broker's expiry, when the broker rejects the token, or when the user logs out of Nivesh on their last device. The account stays listed with `needs_reconnect`.
- Holdings sync runs on connect, on demand, and daily at 17:30 IST for live sessions (`BROKER_DAILY_SYNC_ENABLED=0` switches the job off).
- Overlapping sources: the broker wins. See `backend/helpers/holdings_reconcile.py`.
- A holdings sync stores only rows with a quantity above zero, and fills a missing company name, price
  and sector from masterdata by ISIN; ticker, quantity and cost are always the broker's.
- Every successful holdings sync of a redirect-connected account leaves an immutable snapshot
  (`broker_sync_snapshots`): the broker, the masked login, what started the sync, the rows as stored and
  the duplicate check. The newest 90 per account are kept; older ones are pruned. Snapshots go when the
  account is disconnected or the user's account is erased. The two snapshot routes need a signed-in
  user but not the `broker_hub` flag. `total_value_rs` covers only the `priced` rows.
- Duplicate check of a sync (`duplicates`): `repeated_in_broker_reply` — a line the broker sent again
  (same instrument, quantity and average price), stored once; `same_instrument_lines` — further lines
  for an instrument already in the reply with another quantity or cost, all stored;
  `broker_file_rows_replaced` — rows of an uploaded export of the same broker that the sync superseded
  (same ISIN, or the same ticker when either row has no ISIN); `statement_rows_replaced` — CAS /
  statement rows superseded (same ISIN only); `also_in_other_accounts` — instruments the user also
  holds in another connected account of the same broker (counted, never removed). An instrument is
  its ISIN, else exchange + symbol, else ticker. The last three are `null` when that check could not
  run (the number is not known; it is not zero).
- `GET /api/onboarding/state` also returns `broker_accounts`, `broker_accounts_live`, `holdings_count`.
- `POST /api/portfolio/upload` (and `/upload-raw`) read broker holdings exports (.xlsx / .xls / .csv) from
  Zerodha, Groww, Upstox, Angel One, ICICI Direct, HDFC Securities, Kotak, Dhan, 5paisa and MF Central;
  see `backend/helpers/statement_exports.py`. The response keeps `message, count, holdings` and adds
  `broker` (slug or null), `broker_name`, `format` (`<slug>` | `generic` | `unidentified`). A file with
  no recognisable holdings table is a 400 naming the columns looked for. A recognised export replaces
  that broker's earlier export; a generic file is appended, as before.
- Read errors use the handlers' envelope `{timestamp, status, error, code, message, details[], correlationId, path}`;
  clients should key on `code`. `details` carries `{broker, account_id}`.

Broker sign-in as of 2026-10-14 (from each broker's official documentation):

| Broker | Sign-in | Reads through | State |
|---|---|---|---|
| Zerodha | redirect (Kite Connect) | Fenix when installed, else adapter | connected live on staging (empty account); needs Nivesh app keys |
| Upstox | redirect (OAuth) | Fenix when installed, else adapter | needs Nivesh app keys |
| Angel One | redirect (SmartAPI publisher login) | adapter | built; Angel One has not confirmed one app may sign in other clients |
| Groww | none by redirect; a daily access token the user generates on Groww | adapter | not connectable (needs a product decision and a token form) |
| ICICI Direct | redirect (Breeze login page; returns by form POST, no `state`) | adapter | built, not tested live. Breeze keys are created per customer and ICICI's FAQ prohibits third-party integration; whether one app signs in other customers is untested |
| Motilal Oswal | redirect (MOFSL "Login through Portal"; returns `authtoken`, no `state`) | adapter | built, not tested live. Whether one key signs in any client is not stated by MOFSL |

- Redirect URLs to register: Zerodha `/api/broker/native/callback/zerodha`, Angel One `/callback/angel`,
  ICICI Direct `/api/b/icici`, Motilal Oswal `/callback/motilal`, Upstox `/callback?broker=upstox`
  (Upstox compares it with what Nivesh sends). `/api/b/<slug or alias>` is a short address of the same
  callback (GET and POST), for app forms that cap the URL's length or refuse a port; ICICI's alias is `icici`.
- ICICI Direct and Motilal Oswal echo no `state`, so the returning user is identified by their Nivesh
  session cookie. That needs the cookie to be `SameSite=Lax` (staging) — with `SameSite=None` the CSRF
  middleware rejects ICICI's POST before the route runs.
- ICICI Direct and Motilal Oswal both require the server's static IP to be registered on the app.

## Copilot chat (`POST /api/chat/stream`)
Server-sent events. Body: `message` (required), `session_id`, `page`, `agent`, `persona`.

- `agent` pins one specialist; only `stocks_insights` may be pinned (400 for anything else).
- `persona` is the Copilot app's mode: `investor`, `trader` or `advisor`. It matters only for a caller
  who owns an advisory workspace and is at its root (not viewing a client). In `investor` and `trader`
  that caller is answered from their **own** holdings and positions by the investor engine and its
  tools. With `advisor`, no value or any other value they are answered from the cross-client book, as
  before. For every other caller the field changes nothing, and no value can reach a client book the
  caller does not own.
- `position` (optional) says the question was asked from a broker futures / options position:
  `{account_id, symbol, exchange, instrument_type, expiry, strike, quantity, avg_price}`. When the account is
  the caller's own redirect-connected account and its broker can serve a contract chart, the answer's card is
  `broker_contract_chart` — sent as the first `widget` frame and saved with the answer — and the engine's own
  card (for the underlying share) is not sent. Its `data` is the reference only
  (`account_id, broker, broker_display, symbol, exchange, instrument_type, expiry, strike, quantity, avg_price`);
  the card reads prices itself from `GET /api/broker/accounts/{id}/contract-chart`. A missing, malformed or
  foreign reference is ignored and the question is answered as usual.
  With such a card the server also reads the contract's quote once and gives the engine, with the question,
  the facts of the position (contract, holding, last traded price, day range, previous close, underlying,
  worked-out P&L and breakeven), and sends the question to the stock analyst so the answer keeps the
  underlying's chart levels. The facts never name the broker (a broker's name is also a listed company's and
  would be read as the stock). The thread stores the question as the user asked it.
- `POST /api/chat/send` (the older dock) takes no `persona` or `position` and is unchanged.

## Live quotes (`/api/live`, read-only, signed-in)

Platform-level Kite feed (`backend/services/kite_live_feed`): one leader process (Mongo lease `kite_live_lease`) keeps a quote cache from
KiteTicker (REST `quote()` fallback) and publishes a snapshot every cadence to `kite_live_snapshot` (TTL 72 h). The API never calls Kite.
The universe is indices, Nifty 500, F&O underlyings, the near-month futures and a window of index options (the nearest expiries of
`LIVE_OPTION_UNDERLYINGS`, ATM ± `LIVE_OPTION_STRIKES_EACH_SIDE` strikes, CE and PE, re-centred on each 15-minute rebuild; futures and options
in full mode). Every second the leader also writes the quotes that changed to Redis (`nivesh:quote:<NSE|NFO>:<SYMBOL>`, plus the hash
`nivesh:quote:chain:<UNDERLYING>:<YYYY-MM-DD>` of `strike|CE/PE` -> key, TTL `LIVE_QUOTE_CACHE_TTL_S`), and at each minute of the open
session one replay document to Mongo `kite_live_minute` (`_id` `YYYY-MM-DDTHH:MM` IST, compact rows `s p b a bq aq o v t` + `u x k ot` for
derivatives, first write wins, TTL `LIVE_MINUTE_TTL_DAYS`). Redis is optional: when it is unset or down, reads fall back to the snapshot.

| Endpoint | Purpose |
|---|---|
| `GET /api/live/status` | `mode` (live / delayed / closed / expired / not_connected / disabled), `state`, `source` (ws / rest), `instrument_count`, `last_tick_age_seconds`, `session`, `cadence_seconds` |
| `GET /api/live/quotes?symbols=A,B` | up to 600 symbols; also registers them with the leader (kept 30 min). Read from the Redis cache first (when at least as recent), the snapshot for the rest |
| `GET /api/live/option-chain?underlying=NIFTY&expiry=YYYY-MM-DD` | the cached option window grouped by strike: `rows[{strike, CE, PE}]`, each side with `received_at`, `age_seconds`, `stale` (older than 2 cadences) or null; `cache` = ok / empty / unavailable (Redis down: 200 with `rows: []`) |
| `GET /api/live/snapshot?universe=indices\|nifty500\|fno\|all` | a whole set |
| `GET /api/live/stream?symbols=&universe=` | server-sent events: an immediate `snapshot` event, then one per cadence (`X-Accel-Buffering: no`) |

Body: `as_of`, `data_at`, `age_seconds`, `stale` (market open and data older than 2.5 cadences, or not connected), `mode`, `session`, `source`, `final`,
`quotes{SYMBOL:{ltp,change,change_pct,open,high,low,close,volume,oi,ts,bid,ask,bid_qty,ask_qty,exchange_ts,received_at,source}}` (top of book
from Kite's depth, null without one; futures and options add `instrument`, `underlying`, `expiry`, `lot_size`, options `strike`, `option_type`), `missing[]`. A price is a number or absent, never 0. Symbols are NSE
tradingsymbols, upper case (`NIFTY BANK`, `RELIANCE`); `NSE:` prefixes and NSE index spellings (`Nifty Financial Services`) are folded.
Env: `KITE_LIVE_FEED_ENABLED` (default on; `0` stops the loop), `KITE_LIVE_FEED_CADENCE_SECONDS` (2-120, default 30; `stale` = newest data older than 2.5 cadences, so 75 s by default; clients follow `cadence_seconds`), `KITE_LIVE_FEED_FORCE_REST`,
`KITE_ACCESS_TOKEN` / `KITE_ACCESS_TOKEN_FILE`, `KITE_API_KEY` / `KITE_API_KEY_FILE` (line 1 only; the API secret is never read),
`LIVE_OPTION_UNDERLYINGS` (default `NIFTY,BANKNIFTY`; empty turns options off), `LIVE_OPTION_EXPIRIES` (0-4, default 2), `LIVE_OPTION_STRIKES_EACH_SIDE`
(0-50, default 15), `LIVE_QUOTE_CACHE_TTL_S` (30-86400, default 600), `LIVE_MINUTE_TTL_DAYS` (1-400, default 90), `REDIS_URL`.

### Daily platform Kite login (admin, one human tap per day)

Kite has no supported way to log in without a human (Zerodha 2FA); no headless/TOTP automation exists here. Flow:

1. `POST /api/live/kite/login-url` (admin only) returns `login_url` = `https://kite.zerodha.com/connect/login?v=3&api_key=<key>&redirect_params=state%3Dkp.<nonce>.<sig>`. The `kp.` state is signed, single use and short lived (`KITE_LOGIN_STATE_TTL_MIN`, default 30); only its hash is kept, in Mongo `kite_platform_login_states`.
2. Zerodha redirects to `GET /api/broker/native/callback?broker=zerodha&request_token=...&state=kp...` (the app's registered redirect URL). A `kp.` state is handled by `services/kite_live_feed/platform_token.py`; every other state keeps the per-user broker flow unchanged.
3. The request_token is exchanged with the API key and secret (`KITE_API_KEY`/`KITE_API_SECRET`, else `BROKER_ZERODHA_API_KEY`/`SECRET`). The returned Kite user id MUST equal env `KITE_PLATFORM_USER_ID`, otherwise nothing is stored. The access token is stored AES-256-GCM encrypted (`services/pii_security`) in `kite_platform_token` with `expires_at` = next 06:00 IST, and is never returned by any API.
4. The browser lands on `/v5/app/trader?kite=connected` (path from `KITE_LOGIN_RETURN_PATH`; the legacy `/dashboard` is a different app that reads no `kite=`), or `?kite=error&reason=<code>`; the Copilot shell shows a toast and, for admins, a Log in to Kite banner while the session is missing (`invalid_state`, `state_expired`, `state_used`, `denied`, `missing_params`, `platform_user_not_configured`, `credentials_missing`, `token_exchange_failed`, `wrong_account`, `server_error`).
5. `default_token()` prefers that stored token while unexpired, then `KITE_ACCESS_TOKEN`, `KITE_ACCESS_TOKEN_FILE`, the kite_bars file. The feed reloads it every pass (any container) and recovers without a restart.

Morning alert (`services/kite_live_feed/token_alert.py`): on NSE trading days from 08:30 IST until the 15:30 close, while the platform token is missing, expired or refused, an alert goes out every `KITE_TOKEN_ALERT_INTERVAL_MIN` minutes (default 30, 5-240) with a fresh login link and the time to the 09:15 open; when Kite connects, one "Kite connected" message is sent and reminders stop. Channels: `nidp/shared/notify.py` (email via `NIDP_ALERT_SMTP_*` + `NIDP_ALERT_EMAIL_TO`; Telegram via `NIDP_TELEGRAM_BOT_TOKEN` + `NIDP_TELEGRAM_CHAT_ID`), else the app mailer (`SMTP_*` secrets) to `KITE_TOKEN_ALERT_EMAIL_TO`. The channels that fired are logged; a failing channel never affects the feed. One Mongo doc (`kite_live_snapshot/token_alert`) makes it idempotent across containers. `GET /api/live/status` carries `alert_state` (`TOKEN_ALERT` or null), `token_alert{}` and `platform_token{stored, valid_until, expired}`.

## F&O IV history and regime history (read-only, signed-in)

| Endpoint | Returns |
|---|---|
| `GET /api/fno/{symbol}/iv-history?days=1..1000 (252)&bucket=near_month\|next_month` | `series[]` (oldest first: `date, atm_iv, call_iv, put_iv, expiry, days_to_expiry, atm_strike, spot, future_settle, forward, forward_basis, rate_pct, calc_version, method, reason`), `sessions` (recorded sessions with an IV), `sessions_without_iv`, `current` (the latest recorded session, IV possibly null), `iv_rank`, `iv_percentile`, `window{sessions,from,to,min,max,calendar_days}`, `reason`, `methods{recorded,backfill}` |
| `GET /api/macro/regime-history?days=1..260 (60)` | `points[]` (oldest first: `date, rule_version, key, label, inputs{…}, skipped[{check,reason}], reason`), `sessions, complete, partial, unclassified, missing[]` (what the stored inputs lack, in sentences), `non_session_rows`, `rule`, `basis` |

- IV history: the chain route's own ATM IV (Black-76 on the forward) per session, recorded from the NSE F&O bhavcopy
  (`nidp.fno_bhavcopy` via DaaS `/v1/fno/{symbol}?on=<day>`) by `scripts/record_iv_history.py` into Mongo `fno_iv_history`.
  `near_month` / `next_month` = the 1st / 2nd futures expiry strictly after the session. `iv_rank` = (current − min) ÷
  (max − min) × 100 and `iv_percentile` = share of the earlier sessions below the current × 100, both over the latest 252
  sessions with an IV; null with a `reason` (how many sessions exist) until 252 exist. Sessions not recorded are absent,
  never estimated. Nothing recorded is 200 with `sessions: 0`; an unreadable store is 502 `upstream_unavailable`.
- Regime history: `desk-regime-v1` (the same rule and notes as `/api/macro/today`) recomputed per stored session from
  `macro_daily` (Nifty 50 close, India VIX), `macro_features` (50-session average, else the warehouse Nifty 50 closes) and
  `stock_ohlcv` breadth. Not a record of what the desk showed that day. A missing input skips its check and says so; no
  trend inputs means `key: null`. An unreadable store is 502 `macro_unavailable`.

## Standard error shape
`{ "error": { "code", "message", "details": {} } }` — `400/401/403/404/409/422/429/500`.

## Validation source of truth
Request/response shapes are defined in code (Pydantic v2 backend; Zod on frontend) and the
OpenAPI specs above — those are authoritative. Document only endpoints that exist; mark
`PLANNED` otherwise.
