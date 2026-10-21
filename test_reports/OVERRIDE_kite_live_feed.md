# OVERRIDE: kite_live_feed

REASON: Product code changed (backend/routes/live_quotes.py, backend/services/kite_live_feed/*, frontend-v5 CopilotApp). The staging API and a real-browser Playwright run against staging cannot be produced from this session: staging is read-only for me, the Kite feed needs the platform Kite session and a leader process on staging that this branch has not been deployed to, and the Playwright suite runs against route mocks (no network). Live Kite behaviour on staging is UNVERIFIED.

## Real command output (this session, 2026-10-21)

Backend (staging backend image, working tree mounted read-only, no network):
    tests/test_kite_live_feed.py tests/test_research_providers.py tests/test_desk_market_routes.py nidp/tests/services/kite_bars -q
    157 passed, 1 warning
    (34 of them are tests/test_kite_live_feed.py: lease takeover, cadence clamp 2-30, token missing/expired/changed, rate-limit backoff,
    ws -> rest fallback, REST batches <= 500 spaced >= 1.1 s, final post-close snapshot, no order methods, token/key absent from logs,
    staleness, the four routes incl. SSE.)

Frontend: `tsc --noEmit` -> TSC CLEAN.

Playwright (production build + vite preview, every /api call mocked; MOCK - not real data):
    copilot-app-live-quotes.spec.ts (new): 6 passed
    copilot-app desk*, screener, sector-heatmap, research, trader, markets and copilot-app specs: 449 passed, 19 skipped (468 tests, 6.6m)

## Real Kite smoke tests (read-only, platform token; token and key never printed)
1. kite.profile() -> ok (broker ZERODHA); kite.quote(['NSE:RELIANCE','NSE:NIFTY 50']) -> real last prices; instruments('NSE') 10363 rows, 136 INDICES.
2. LiveFeed against real Kite (in-memory Mongo fake, Nifty 500 list unavailable offline so universe = 119 indices + 213 F&O underlyings + 5 requested):
   - REST mode: state live, source rest, 332 quotes read per pass (RELIANCE, TCS, NIFTY 50, NIFTY BANK with ltp and change_pct).
   - WebSocket mode: pass 0 source rest (socket connecting), passes 1-3 source ws, quotes updated from KiteTicker 'quote' ticks.
   Quote-mode ticks carry no exchange timestamp, so a ws quote's `ts` is the receive time.

## UNVERIFIED
- Staging deployment: nothing was deployed; /api/live/* on staging, the lease across two real containers, nginx passing SSE unbuffered (X-Accel-Buffering: no is sent), and the Nifty 500 + holiday reads through the data platform were not exercised with real services.
- The full 3000-instrument load over a whole session, and behaviour at the 06:00 IST token expiry, ws reconnect after a network drop, and the 15:30 close with real data.
- Native/WebView clients (bearer token, no cookie): EventSource cannot send Authorization, so they rely on the polling fallback; not exercised.

## Addendum: daily platform token lifecycle + morning alert (2026-10-21)

Real command output (this session):
- Backend (staging image, tree read-only, no network): test_kite_platform_login.py + test_kite_live_feed.py + test_broker_native_routes.py +
  test_broker_connect_native_routes.py + test_research_providers.py + test_desk_market_routes.py + nidp/tests/services/kite_bars:
  see the final run in the hand-off (all passed; the per-user broker_native tests are green and unchanged).
- tsc --noEmit: TSC CLEAN.
- Playwright (mocked API): copilot-app-live-quotes.spec.ts 7 passed (new: admin-only "Log in to Kite" link); the wider desk / screener /
  heatmap / research / trader / markets / screens / threads / workspace / watchlists set: 530 passed, 19 skipped, 549 tests, 8.9m.

Behaviour covered by tests with fakes (MOCK): callback happy path, wrong Zerodha user rejected, replayed / expired / forged state rejected, per-user
flow unchanged, token encrypted at rest and never logged or returned, default_token() precedence, feed recovery without restart (not_connected
and expired), alert cadence / link per reminder / countdown / one confirmation / silent on weekends, holidays, before 08:30 and after close /
two containers send once / a failing notifier never breaks the feed.

No auto-login: Kite offers none (Zerodha 2FA). A test fails the build if TOTP / headless-browser code appears in the package.

Staging environment check (names only, values never read), backend container nivesh-staging-app-backend, 2026-10-21:
- present: BROKER_ZERODHA_API_KEY, BROKER_ZERODHA_API_SECRET, KITE_API_KEY, KITE_ACCESS_TOKEN, PII_ENCRYPTION_KEY
- absent: KITE_PLATFORM_USER_ID (the running container predates the env-file edit; it needs a restart/recreate), KITE_API_SECRET (falls back to
  BROKER_ZERODHA_API_SECRET), NIDP_ALERT_SMTP_HOST, NIDP_ALERT_EMAIL_TO, NIDP_TELEGRAM_BOT_TOKEN, NIDP_TELEGRAM_CHAT_ID, KITE_TOKEN_ALERT_EMAIL_TO
- so NO alert channel is configured on staging today; the app mailer's SMTP_* secrets live in the secrets store, which I could not read.
  An alert would currently be logged as "NOT delivered".

UNVERIFIED (addendum):
- Zerodha's real redirect to /api/broker/native/callback?broker=zerodha with our redirect_params state (the registered redirect URL, and that
  Kite echoes `state` back, is as documented but was not exercised).
- A real generate_session exchange for the platform account and the WVX837 match.
- Real alert delivery over email or Telegram (no channel configured on staging; none was sent).
- The login link and callback through the staging nginx host, and the /dashboard?kite=connected landing page (no dashboard screen reads `kite=` yet).
