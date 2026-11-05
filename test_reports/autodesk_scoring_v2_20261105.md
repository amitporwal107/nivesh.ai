# Functionality Verification Report — Desk scoring v2 (versioned, v2-positional in shadow)

- **Branch:** feat/signal-tier-hierarchy (worktree /home/deploy/nivesh-wt-autodesk), commits a943d96e, 9b017c69, e19f9afc,
  5d533e45 on origin/dev ea951dcb — not pushed yet
- **Date:** 2026-11-05 ~23:00 IST
- **Author:** Claude (full-stack developer + QA + domain analyst)
- **Owner decision:** pasted approval, 5 Nov: build the revised hierarchy as a versioned, configurable framework; keep v1; v2 in
  shadow; bearish signals as risk / exit warnings only; intraday off; attribution; walk-forward validation before promotion.
- **Changed areas:** backend: `autodesk/scoring/{registry,v2_positional}.py` (new), `autodesk/agents/ai_trader.py` (shadow hook;
  v1 inputs unchanged), `autodesk/contracts.py` (optional `Signal.shadow_scores`, `ScanReport.shadow`),
  `autodesk/routers/api.py` (`GET /api/v1/scoring/versions`). Frontend: none. Spec:
  docs/signal_intelligence/SIGNAL_TIER_HIERARCHY.md §10–§11.

## Test Cases
Written before the code: docs/autodesk/TESTCASES.md "Scoring v2 — versioned signal hierarchy" (AD-SC-01..15, commit e19f9afc).

| ID | Case | Layer | Result |
|---|---|---|---|
| AD-SC-01 | registry: v1 ACTIVE, v2 SHADOW, v3 DISABLED; v2 weights 45/30/15/10; env switch | U | PASS |
| AD-SC-02 | only v1 may be active | U | PASS |
| AD-SC-03 | RS breakout fires above the prior 250-session RS high; not with < 251 sessions | U | PASS |
| AD-SC-04 | HH-HL / LH-LL; swing points used two bars later (cut-series check, 79 bars) | U | PASS |
| AD-SC-05 | no look-ahead: score at t from the full series = score from the series cut at t (6 bars) | U | PASS |
| AD-SC-06 | overlap: HH-HL primary → trend does not re-score it; RS primary → RS halves; one family counts once; cap 45 | U | PASS |
| AD-SC-07 | bearish signals are warnings only, −10, never an entry tier | U | PASS |
| AD-SC-08 | no chasing penalty (4 ATR above EMA20); RSI 77 → 4, RSI 85 → 2 | U | PASS |
| AD-SC-09 | volume 10× = 1.6× (1 point), 1.2× → 0 | U | PASS |
| AD-SC-10 | bands, attribution per component, score = clamped sum; not-scored reasons (history, ₹5 Cr) | U | PASS |
| AD-SC-11 | AI Trader: v1 scores, breakdowns, zones, levels and order identical with shadow on/off; shadow on each stock signal | I | PASS |
| AD-SC-12 | scan report `shadow` block (candidates never published); shadow failure recorded, v1 unchanged | I | PASS |
| AD-SC-13 | GET /api/v1/scoring/versions: 401 signed out; v1 active, v2 shadow, v3 disabled | A | PASS |
| AD-SC-14 | stored bodies without the new fields still parse | U | PASS |
| AD-SC-15 | walk-forward shadow check of the real v2 module on 2.6 years of history | S (study) | DONE — mixed: ranks in test, not in fit (below) |

## API / Endpoint Tests
- **Desk backend suite** — `sudo -n bash backend/scripts/run_autodesk_tests.sh /home/deploy/nivesh-wt-autodesk tests/autodesk tests/test_order_path_guard.py -p no:warnings`
  - Output: `150 passed in 38.41s` (was 134 before this branch: +15 in test_scoring_v2.py, +1 AD-SC-13 in test_api.py)
- **Scoring tests alone** — `docker run … nivesh/backend:staging python -m pytest tests/autodesk/test_scoring_v2.py -p no:cacheprovider -p no:warnings -q`
  - Output: `15 passed in 1.56s`
- **Compile** — `python3 -m py_compile autodesk/scoring/registry.py autodesk/scoring/v2_positional.py autodesk/agents/ai_trader.py autodesk/contracts.py autodesk/routers/api.py tests/autodesk/test_scoring_v2.py tests/autodesk/test_api.py`
  - Output: `py_compile OK (7 files)`
- **Staging** — `curl https://staging.niveshcopilot.com/api/healthz` → `HTTP 200` (staging still runs dev ea951dcb; this branch is
  not deployed).
- Result: PASS (code); staging behaviour UNVERIFIED until merge.

## UI / Playwright Tests
None — no frontend change.

## Data Correctness
- v1 unchanged: AD-SC-11 compares every v1 signal field that drives selection with shadow on and off (identical).
- v2 inputs are point-in-time: AD-SC-05 proves the score at a bar does not change when later bars are added.

## Not verified (UNVERIFIED) and why
- Staging: after merge, the next desk cycle / simulation should show `shadow_scores` on signals and a `shadow` block in the
  scan task result; `GET /autodesk/api/v1/scoring/versions` signed in. Needs the owner's merge.
- Scan time with 500 bars per stock in historical replays (v2 needs the longer history): to measure on staging after merge.
- Promotion evidence: AD-SC-15 is encouraging in the test period only; live shadow data must confirm before any promotion.

## AD-SC-15 — walk-forward shadow check of the real v2 module (study, 5 Nov ~23:10 IST)
Command: `docker run --rm --network none -v <worktree>:/work:ro -v <scratchpad>/study:/study nivesh/backend:staging python /study/validate_v2.py`
(the shipped `autodesk.scoring.v2_positional`, scored on every bar of 739 stocks, DaaS adjusted daily data 16 Apr 2024 – 4 Nov
2026; entry next open; 20-session excess vs the Nifty; t over per-day means). Output `rows 383674`, excerpts (unedited):

| | Fit (≤ Sep 2025) | Test (Oct 2025 – Nov 2026) |
|---|---|---|
| all scored stock-days (baseline) | `excess 0.074, t 0.36` | `excess 0.905, t 3.8` |
| band Exceptional (entry signal) | `0.428, t 1.45` | `1.25, t 4.54` |
| band Strong | `0.124, t 0.16` | `1.699, t 5.7` |
| band Developing | `-0.026` | `0.998` |
| band Weak | `0.069` | `1.099` |
| band Avoid | `0.309` | `0.148` |
| primary RS_BREAKOUT | `0.34, t 1.35` | `1.575, t 6.66` |
| primary SETUP_B_PULLBACK | `-0.16` | `1.194, t 3.09` |
| primary HH_HL_CONFIRMED | `0.229` | `0.739, t 3.23` |
| primary SETUP_A_ACCUMULATION | `0.022` | `0.035` |
| entry + bearish warning / no warning | `0.237` / `0.139` | `0.934` / `0.942` |
| rank IC, v2 score vs 20-session excess (candidates) | `mean -0.0044, t -0.6` | `mean 0.0547, t 7.04` |

Read: in the test period v2 ranks candidates (IC +0.055, t 7.0; v1's IC on its own replay was −0.028) and Strong / Exceptional
beat the universe baseline by +0.8 / +0.35 points per 20 sessions, Avoid trails it by −0.76. In the fit period v2 has no ranking
power (IC −0.004). The universe baseline itself beats the Nifty in the test period (+0.9: equal-weight mid/small caps and
survivorship — today's index members), so bands are judged against the baseline, not against zero. The tier choices were made
after seeing both periods' calibration tables, so the test period is not fully unseen. Setup A and the bearish-warning penalty
add nothing. **Conclusion: keep v2 in shadow; collect live shadow scores; no promotion on this evidence.**

## Verdict: PASS
