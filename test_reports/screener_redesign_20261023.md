# Functionality Verification Report — Screener redesign

- **Branch:** feat/provider-foundations (uncommitted)
- **Date:** 2026-10-23
- **Author:** Claude (full-stack developer + QA)
- **Environment:** LOCAL ONLY (staging image container for pytest; Playwright image against a production build with mocked /api). Not staging.
- **Changed areas:** backend routes: yes (`backend/routes/screeners.py`) · frontend src: yes

## Summary
POST /api/screeners/run gains four mutual-fund metrics (`mfChange`, `amcsUp`, `amcsDn`, `amcsHolding`) joined by symbol from the smart-money scanner (Nifty 500 only) and an `include_funds` flag. The Screener screen shows the matches as one sortable table with four lenses (Overview, Fundamentals, Technicals, Ownership & funds), Kite LTP/Day columns while the feed has a quote, and a row opens Research's own `StockResearch` (price chart, figures, shareholding, filings) in a slide-over. Ready-made (strategy builder) rows open the same panel. Test cases: `screener_redesign_TESTCASES.md`.

## Test results (real output this session)
- Backend: `python -m pytest tests/test_screeners_run.py tests/test_screener_contract.py -q` (staging image, `--network none`) → `65 passed, 1 skipped, 1 warning in 7.38s` (covers TC-1..TC-6).
- Typecheck: `npx tsc --noEmit -p tsconfig.json; echo tsc_exit=$?` → `tsc_exit=0` (TC-17).
- Playwright (production build, mocked /api): `copilot-app-screener copilot-app-workspace copilot-app-research` → `66 passed (51.6s)`, `2 skipped` (the two Research screenshot specs, skipped before this change). Covers TC-8..TC-16 (new spec `copilot-app-screener-chart.spec.ts`) and TC-13 (existing screener + workspace specs, updated only where the behaviour changed on purpose: a result row now opens the chart instead of asking the Copilot; request bodies carry `include_funds: true`).

## UNVERIFIED (not run, and why)
- TC-7 / staging API: no real call to the new run behaviour. Staging does not have this code, and the signed-in route needs the user's session token (NEEDS-INPUT).
- Staging Playwright and the real data: all Playwright data is invented fixtures. The live Kite columns were exercised with a mocked snapshot only.
- Whether the scanner join returns sensible figures on the real warehouse (e.g. how many of the Nifty 500 have fund-house deltas for the latest month).

## Inputs required from user
- A staging `session_token` for the signed-in API check, and a merge to dev to deploy (the redeploy is not something this session can do).
