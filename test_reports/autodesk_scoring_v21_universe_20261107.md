# Functionality Verification Report — Scoring v2.1 (shadow) + wider scan universes (package 5, parts A + C)

- **Branch:** feat/autodesk-scoring-v21 (based on origin/dev c2e161eb)
- **Date:** 2026-11-07
- **Author:** Claude (full-stack developer + QA), Account 2
- **Environment:** throwaway Postgres + stub market data for tests; READ-ONLY real data (data platform via the staging DaaS) for AD-SC-35. Nothing deployed, no shared database written.
- **Changed areas:** backend routes/services: yes (agents/ai_trader.py, scoring/*, additive `index_members` on the market view; no router change) · frontend src: yes (studio Setup.tsx + setup/model.ts)

## Summary
`v21-positional` is a second SHADOW scoring version (v2 with setup A as context only and no bearish −10); v1 stays the only active version. The AI Trader records both shadow scores on each stock signal and the scan report gains `shadow.versions`. New scan universes `NIFTY500` and `TOTAL_MARKET` (today's index members; non-F&O members scan as cash only) are enabled in the Studio New simulation form with a survivorship note. Part B (shadow scores in Scanner / Trace / Day) is deferred by the brief. Test cases: docs/autodesk/testcases_scoring_v21.md (committed before the code, 996ca260).

## Test Cases
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| AD-SC-16..20 | scoring | registry, setup A → context, no bearish penalty, version pins, no look-ahead | unit | see testcases_scoring_v21.md | PASS (tests/autodesk/test_scoring_v21.py) |
| AD-SC-21..25 | AI Trader | both scores per signal, v1 identical with 0/1/2 shadows, report blocks, per-version failure isolation, features built once | integration | | PASS |
| AD-SC-26..32 | universe | members scanned, cash-only non-F&O, FNO unchanged, unknown/unavailable fail visibly, cap only for named universes, survivorship caveat | integration | | PASS (tests/autodesk/test_universe_v21.py) |
| AD-SC-33/34 | Studio UI | chips enabled, caveat shown for index universes only, POST body matches contracts studio-setup.create_nifty500 / create_total_market | e2e + contract | | PASS (autodesk-universe.spec.ts; backend test_ui_request_contracts posts the same bodies) |
| AD-SC-35 | real data | FNO / NIFTY500 / TOTAL_MARKET scan, both shadow versions, time | study | | PASS (below) |
| AD-SC-36 | vocabulary | no banned words in new agent narrative | grep | | PASS — the added diff lines contain none except the word "entry signals" in an internal docstring (v2's existing signal-tier term), not agent narrative |

## API / Endpoint Tests
- **pytest:** `sudo -n bash backend/scripts/run_autodesk_tests.sh /home/deploy/nivesh-wt-account2 tests/autodesk tests/test_order_path_guard.py -p no:warnings`
  - Output: `169 passed in 41.97s` (dev baseline 150). An earlier run of the same command during development printed `167 passed`; I did not investigate the difference of 2 (no test was added between the runs).
  - Result: PASS
- `python3 -m py_compile` on all changed backend files and the scan script: `compiled`.

## UI / Playwright Tests
- Command: Docker `tsc --noEmit && vite build && npx playwright test --config pw.autodesk.config.ts` (the package 5 brief's command)
  - Output: `152 passed (1.2m)` (dev baseline 149; +3 = AD-SC-33, AD-SC-34 ×2). The existing AD-UI-121 now expects 3 disabled universe chips (Nifty 50, Nifty 200, Index options). Not re-run after the last two commits, which touch only a backend script and this report.
  - Result: PASS

## Data Correctness (real data, read-only)
Command: `sudo -n bash -c '… docker run --rm --network <staging net> --env-file <(NIDP_DAAS_* only) -v worktree:/work:ro nivesh/backend:staging python scripts/autodesk_universe_scan.py FNO NIFTY500 TOTAL_MARKET'` — real AITrader over PitMarketView, session_date 2026-11-09. Real output (trimmed to the numbers; full JSON lines were printed by the run):

| universe | scan s | universe_size | scanned | signals | FUTURES / CASH | both shadow scores | shadow errors | failed reads |
|---|---|---|---|---|---|---|---|---|
| FNO | 20.7 | 224 | 222 | 203 | 158 / 45 | 203 | 0 / 0 | 0 |
| NIFTY500 | 40.1 | 501 | 494 | 220 | 158 / 62 | 220 | 0 / 0 | 0 |
| TOTAL_MARKET | 64.6 | 754 | 742 | 230 | 158 / 72 | 230 | 0 / 0 | 0 |

- "Nifty Total Market" resolves on the data platform to 754 members; Nifty 500 to 501.
- TOTAL_MARKET scan time is 3.1× the F&O scan (expected ≈3×) and well inside the 600 s scan deadline. The F&O run was first (cold cache); the larger universes reuse cached index/benchmark reads, so the ratio is approximate.
- The 203 F&O-eligible signals are the same in all three universes (futures segments unchanged); the extra signals are CASH only (45 → 62 → 72).
- Shadow, TOTAL_MARKET: v2 scored 729, 160 with an entry signal, bands Exceptional 3 / Strong 4 / Developing 17 / Weak 36 / Avoid 100; v2.1 scored 729, 160, bands 3 / 4 / 17 / 38 / 98 (two names move Avoid → Weak because the −10 is gone). Top of both: SOUTHBANK 88.0, LUMAXTECH 86.5, BSOFT 86.0.
- 7 TOTAL_MARKET members had 0 bars and were listed in `suppressed`, not silently dropped.
- Result: PASS

## Inputs required from user
Permission to run the throwaway container with the DaaS env (first attempts were denied by the auto-mode classifier; it ran after the user confirmed and auto mode was exited).

## UNVERIFIED
- Not deployed; the Studio form was exercised against route mocks (`// MOCK — not real data`), not the live API.
- A full multi-session TOTAL_MARKET *replay* (orchestrator + simulator + Postgres) was not run; the real-data check is the AI Trader scan only. Proposal/approval stages on 230 signals are untested at that scale.
- Index membership is today's, so any historical replay carries survivorship bias (stated in results and the UI).

## Verdict: PASS
