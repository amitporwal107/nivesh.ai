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
| `GET /accounts` | existing keys + `native, broker_user_masked, session_expires_at, session_ended_reason, needs_reconnect`; `status` may be `expired` |
| `POST /accounts/{id}/sync` | `{ok, count, holdings[]}`; replaces only that account's holdings |
| `GET /accounts/{id}/positions?kind=net\|day&segment=all\|fno\|intraday` | `{account_id, broker, kind, segment, as_of, positions[], counts{total,fno,intraday}}`; live, not stored |
| `GET /positions?kind=&segment=` | the same per connected account: `accounts[]` with `ok`, `error{code,message}`, `as_of` |
| `DELETE /accounts/{id}` | removes the account, its token and its holdings |

- `broker_error` codes: `denied, missing_params, unknown_broker, invalid_state, state_expired, token_exchange_failed, server_error` (the broker signed the user in but Nivesh could not save the session).
- The server must have `PII_ENCRYPTION_KEY` to store a session token. Without it `supported` reports nothing as `configured` or `connectable`, and `start` answers 503.
- Position fields: `symbol, exchange, quantity (signed), avg_price, last_price, pnl, product, product_raw, segment (equity|fno|commodity|currency), is_intraday, instrument_type (FUT|CE|PE), expiry, strike, kind, name`. A field the broker does not return is null.
- Read errors carry a stable `code`: `BROKER_SESSION_EXPIRED` (409, reconnect needed), `BROKER_READ_NOT_SUPPORTED` (400), `BROKER_READ_FAILED` (502).
- Feature flag `broker_hub` (default everyone): off gives 403 `feature_not_enabled` on start, native sync and positions. Listing and disconnecting are not gated.
- A session ends at the broker's expiry, when the broker rejects the token, or when the user logs out of Nivesh on their last device. The account stays listed with `needs_reconnect`.
- Holdings sync runs on connect, on demand, and daily at 17:30 IST for live sessions (`BROKER_DAILY_SYNC_ENABLED=0` switches the job off).
- Overlapping sources: the broker wins. See `backend/helpers/holdings_reconcile.py`.
- `GET /api/onboarding/state` also returns `broker_accounts`, `broker_accounts_live`, `holdings_count`.
- `POST /api/portfolio/upload` (and `/upload-raw`) read broker holdings exports (.xlsx / .xls / .csv) from
  Zerodha, Groww, Upstox, Angel One, ICICI Direct, HDFC Securities, Kotak, Dhan, 5paisa and MF Central;
  see `backend/helpers/statement_exports.py`. The response keeps `message, count, holdings` and adds
  `broker` (slug or null), `broker_name`, `format` (`<slug>` | `generic` | `unidentified`). A file with
  no recognisable holdings table is a 400 naming the columns looked for. A recognised export replaces
  that broker's earlier export; a generic file is appended, as before.
- Read errors use the handlers' envelope `{timestamp, status, error, code, message, details[], correlationId, path}`;
  clients should key on `code`. `details` carries `{broker, account_id}`.

Broker sign-in as of 2026-10-13 (from each broker's official documentation):

| Broker | Sign-in | Reads through | State |
|---|---|---|---|
| Zerodha | redirect (Kite Connect) | Fenix when installed, else adapter | needs Nivesh app keys |
| Upstox | redirect (OAuth) | Fenix when installed, else adapter | needs Nivesh app keys |
| Angel One | redirect (SmartAPI publisher login) | adapter | built; Angel One has not confirmed one app may sign in other clients |
| Groww | none by redirect; a daily access token the user generates on Groww | adapter | not connectable (needs a product decision and a token form) |
| ICICI Direct | Breeze keys are personal and third-party use is prohibited | adapter | sign-in switched off; use file upload |

## Standard error shape
`{ "error": { "code", "message", "details": {} } }` — `400/401/403/404/409/422/429/500`.

## Validation source of truth
Request/response shapes are defined in code (Pydantic v2 backend; Zod on frontend) and the
OpenAPI specs above — those are authoritative. Document only endpoints that exist; mark
`PLANNED` otherwise.
