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
