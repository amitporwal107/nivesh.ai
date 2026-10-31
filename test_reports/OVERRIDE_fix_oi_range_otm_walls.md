# OVERRIDE: fix_oi_range_otm_walls (branch fix/oi-range-otm-walls)

REASON: Staging HTTP/UI evidence needs the user's staging session_token cookie, which I do not have; the backend part is inert on staging until the backend process is restarted. The frontend falls back to the old range if the new fields are absent, so it is safe to deploy in either order.

Evidence (this session, real output):
- pytest (staging image): tests/test_fno_routes.py + tests/test_fno_candidates.py `125 passed` (3 new wall tests; the worked-example summary now includes the walls).
- `tsc --noEmit` exit 0; build exit 0; Playwright lab + portfolio-fno specs `92 passed, 2 skipped` (4 new wall tests TC-4..TC-7).
- Warehouse (read-only), GODFRYPHLP 23 Oct 2026, expiry 27 Oct: cash close 1669.00 (Kite's closing quote 1669.00; future 1661.40); put OI peaks at the in-the-money 1900 strike (36,575, close 240.35), call OI at 2100 (76,450); the stock fell from 1807.5 on 19 Oct.
- Test cases: test_reports/fix_oi_range_otm_walls_TESTCASES.md.

Not changed (stated): the paper-strategy builder still reads the all-strike heaviest strikes; its level rule already replaces a wall on the wrong side of the price with the edge of the expected move. The chain view's "Highest call/put OI" still shows the raw heaviest strikes (it says exactly that).
UNVERIFIED: the Lab on the deployed build.
