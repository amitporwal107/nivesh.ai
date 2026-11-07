# Functionality Verification Report — Shadow scores in the desk web app (package 5 part B)

- **Branch:** feat/autodesk-shadow-scores-ui (from feat/autodesk-scoring-v21, with origin/dev incl. #499 merged in)
- **Date:** 2026-11-07
- **Author:** Claude (full-stack developer + QA), Account 2
- **Environment:** Playwright against route mocks (`// MOCK — not real data`); backend tests on a throwaway Postgres. Not deployed.
- **Changed areas:** backend routes/services: no · frontend src: yes (Scanner.tsx, studio/views/trace/model.ts, new screens/scanner/shadow.tsx)

## Summary
The Opportunity scanner shows one shadow chip per scoring version (`v2 67.5 · Developing`, `v2.1 77.5 · Strong`) beside the unchanged v1 score, and the expanded row gains a "Shadow scoring — not used for selection" section (score, band, tier, signals, context-only signals, warnings, and each component with points of weight and reason; a version that could not score shows its reason). The Studio Agent trace lists each shadow score in the AI Trader signal step's payload. Studio Trading day shows no per-signal score, so nothing was added there (AD-SC-42). Ranking, v1 scores and selection are untouched. Test cases: docs/autodesk/testcases_scoring_v21.md Part B (committed before the code).

## Test Cases
| ID | Scenario | Result |
|----|----------|--------|
| AD-SC-37 | row chips per version; order and v1 scores unchanged; none drawn without shadow data | PASS |
| AD-SC-38 | expanded section: components, v2.1 has no bearish penalty row but still lists the warning, not-scored reason | PASS |
| AD-SC-39 | older rows: "No shadow score stored with this signal.", v1 breakdown still shown | PASS |
| AD-SC-40 | phone 390×844, no horizontal overflow | PASS |
| AD-SC-41 | Studio trace payload rows; absent when the signal has no shadow scores | PASS |
| AD-SC-42 | Trading day: no per-signal score shown there → nothing to add | PASS (recorded, no change) |
| AD-SC-43 | all existing specs unchanged | PASS |

## API / Endpoint Tests
- `sudo -n bash backend/scripts/run_autodesk_tests.sh /home/deploy/nivesh-wt-account2 tests/autodesk tests/test_order_path_guard.py -p no:warnings` → `185 passed in 41.33s`. No backend code changed in this part; run to confirm the merge of origin/dev + part A.

## UI / Playwright Tests
- Docker `tsc --noEmit && vite build && npx playwright test --config pw.autodesk.config.ts` (package 5 brief command)
  - `autodesk-shadow` alone: `5 passed (3.9s)`
  - full desk suite: `168 passed (1.2m)` (160 from #499 + 3 universe specs + 5 shadow specs)
  - Result: PASS

## Data Correctness
Not applicable to this part (display only). The real-data numbers for the shadow scores themselves are in autodesk_scoring_v21_universe_20261107.md. UNVERIFIED: the screens were not checked against a live API response containing `shadow_scores` (needs a deployed build and a fresh session cycle; rows created before package 5 correctly show "No shadow score stored").

## Inputs required from user
none

## Verdict: PASS
