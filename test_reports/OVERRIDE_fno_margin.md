# OVERRIDE: fno_margin (branch feat/fno-margin)

REASON: The new route is not deployed to staging yet and I have no session token on hand, so POST /api/fno/margin has not been called through the app. The calculator itself WAS exercised for real on staging (read-only) before the code was written.

Evidence (this session, real output):
- Real Kite call from the staging container (platform session, 2026-10-24 03:56 IST): basket_order_margins for a GODFRYPHLP 27 Oct bear put spread (buy 1700 PE, sell 1600 PE, 275 lot, NRML, consider_positions=False) returned initial 78,908.0625, final 77,519.3125 and per-order charges (brokerage 20, exchange 4.65, SEBI 0.01, GST 4.44...).
- pytest (staging image): tests/test_fno_margin.py (5) + tests/test_fno_routes.py + tests/test_kite_live_feed.py `157 passed`.
- `tsc --noEmit` exit 0; build exit 0; Playwright lab spec `75 passed, 2 skipped` (2 new margin tests).
- Test cases: test_reports/fno_margin_TESTCASES.md.

Stated limits: the figure is Zerodha's calculator for the platform account's rules (not an exchange-published number, not a quote); it needs the platform's daily Kite login (503 -> "Unavailable" with the reason); the calculator places, modifies and cancels nothing (a test pins the wrapper's two methods). Margin is for the legs at market order type with consider_positions=False (a standalone basket, not the user's account). Probability of profit and return % remain unavailable. The existing live-feed guard test that bans order_margins in the kite_live_feed package is untouched: this code lives in services/fno_margin.py.
UNVERIFIED: the route and the strip on the deployed build.
