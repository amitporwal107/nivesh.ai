# scan-rules.v2 — Momentum RSI band + matched_filters / why_matched / risk_flags / data_status

Worktree: /home/deploy/nivesh-trading-desk (branch feat/trading-desk-backend), UNCOMMITTED as of this report.
Files: backend/services/positional_engine/setup_rules.py, backend/tests/test_scan_rules_v2.py (new),
backend/tests/fixtures/scan_snapshot_20261019.json (new, real staging rows), backend/tests/test_positional_scan_universe.py,
frontend-v5/.../tradingdesk/ScannerTab.tsx (rule text), frontend-v5/e2e/tests/copilot-app-desk-scanner.spec.ts (fixture + text).

## Test cases (authored before the code)
1. Momentum v2 qualifier passes and why_matched lists 5 conditions with observed values and thresholds.
2. Boundaries: RSI 55.0 in / 54.99 out; 75.0 in / 75.01 out; 20d return 5.0 in / 4.99 out; close == SMA50 out; slope 0 out.
3. Extended stock (RSI 82, +65 %) leaves Momentum and is flagged extended_price.
4. Missing RSI with longer indicators present = "missing", not insufficient history; counted in `missing`.
5. SMA50 present, slope + SMA200 absent = "insufficient_history"; counted in `insufficient_history`; flag raised; nothing claimed in why_matched.
6. No indicator present at all cannot be called insufficient history.
7. A definite failure (RSI 80) beats an unknown figure (slope absent): status no_match.
8. Overlapping filters: momentum + unusual_volume + fno each with its own explanation.
9. Results-day explanation carries the results date.
10. Clean stock: no flags; stock in no filter: empty matched_filters / why_matched.
11. Risk flags: gap up/down at ±5 %, event window edge (7 / 8 days, today's results not "upcoming"), low liquidity.
12. Back-compat: v1 row keys, category keys and top-level keys unchanged; route rows carry the new keys.
13. evaluate() is a pure function of rows + as-of date (no look-ahead source).
14. Real staging rows, session 2026-10-19 (65 rows) and the full 2,480-row snapshot.
15. UI: Momentum rule text includes the RSI band (Playwright SP-2); typecheck.

## Real output (this session)
Backend, in nivesh/backend:staging image, tree mounted read-only:
    tests/test_scan_rules_v2.py test_positional_scan_universe.py test_positional_desk_fields.py
    test_positional_engine.py test_positional_calibration.py test_positional_scenario.py
    134 passed, 1 warning in 8.20s

Frontend: `npx tsc --noEmit -p tsconfig.json` → TSC_OK.
Playwright (vite build + preview, VITE_BASE=/v5/, repo mocks, --grep-invert SHOT): `52 passed (1.2m)`
(includes the auth-setup project; the SHOT screenshot tests were excluded).

Data test — full staging snapshot, 2026-10-19 (scan-snapshot SQL run on the NIDP VM, rules applied in the container):
    as_of 2026-10-19 rows 2480 eligible 901
    momentum v1 total 101  v2 total 56  v2 shown 50
    v2 subset of v1: True  dropped by RSI band: 45
    top dropped: SHANTIGOLD (20d 65.0217, RSI 79.3523), ONWARDTEC (57.85, 89.65), SHRINGARMS (51.51, 78.56), PCJEWELLER (42.53, 77.58), ADVANCE (41.94, 77.20)
    momentum missing 7 insufficient_history 7
    members with a non-passing why_matched condition: 0
v1 reproduces the desk screenshot's "101 match; 7 could not be judged".

## NOT verified
- The deployed staging API: v2 is not deployed (the staging backend bind-mounts /opt/nivesh-staging/repo/backend, not this tree), so
  GET /api/positional/scan-universe has not been called on staging. The route was tested with the fixture snapshot only.
- The signed-in UI against real data; Playwright ran on route mocks.
- Setup-bucket membership (breakout_confirmed etc.) is not in matched_filters: evaluate() only sees setup symbols, not buckets.
- No historical precision / forward-return validation of the v2 thresholds.

## Verdict: BLOCKED (staging deploy + session token not available; see OVERRIDE_scan_rules_v2.md)
