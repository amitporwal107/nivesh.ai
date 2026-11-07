# Functionality Verification Report — Simulation studio (/autodesk/studio), desk web app

- **Branch:** feat/autodesk-sim-studio (worktree /home/deploy/nivesh-wt-autodesk), commits 0cab6998 + 0984c244, stacked on
  feat/autodesk-ui (PR #493, e9ea1f8a)
- **Date:** 2026-11-05 17:15 IST
- **Author:** Claude (full-stack developer + QA + design engineer)
- **Environment:** Playwright on the production build (`vite preview`, Docker, no network) with API route mocks; request
  contracts and backend suite on a throwaway Postgres
- **Changed areas:** backend routes/services: no (backend test only) · frontend src: yes (`frontend-v5/src/autodesk/studio/**`,
  `App.tsx` routes)

## Summary
The owner's design pack ("Screen design specifications.zip", 5 Nov) adds a Simulation studio beside the desk; its 12 desk
screens and shell are identical to the ones PR #493 builds. The studio is a page of its own at /autodesk/studio, as
designed: header with the "Simulated · isolated · no broker route" pill, tabs Trading day / New simulation / Scenario
library / Run history / Agent trace, theme switch, link back to the desk; the viewed run travels as `?sim=`.
Real data from the desk's simulator API: phase clock, per-agent lanes and event stream; create / start / run / pause /
resume; measures from /results; a comparison of two runs computed from their signals, plans and decisions; a proposal
chain replayed task by task. The Scenario library is an honest Phase 3 page (the API refuses scenario runs; planned shock
kinds from the PRD are listed as planned; nothing is sent). P&L, fills, positions, speed multipliers and checkpoints keep
their place with Phase 2/3 notes. No prototype sample data is shown.

## Test Cases
Written before the code: frame AD-UI-100..107 in docs/autodesk/TESTCASES.md ("Simulation studio — frame"); views in
docs/autodesk/ui_testcases/studio-day.md (AD-UI-110..119, 113b), studio-setup.md (120..129), studio-scenarios.md
(130..137), studio-runs.md (140..148), studio-trace.md (150..159).

| IDs | View | Layers | Result |
|---|---|---|---|
| AD-UI-100..107 | Frame: header, tabs + `?sim=`, sign-in, theme, deep link, phone, desk routes unchanged | E | PASS (7) |
| AD-UI-110..119 | Trading day | E + C | PASS (11) |
| AD-UI-120..129 | New simulation (create and start, accelerated, 422, Phase 3/4 modes) | E + C | PASS (10) |
| AD-UI-130..137 | Scenario library (Phase 3, nothing sent, no sample catalogue) | E | PASS (8) |
| AD-UI-140..148 | Run history (measures, two-run comparison, one-run state) | E | PASS (9) |
| AD-UI-150..159 | Agent trace (step, restart, autoplay, picker, phone) | E | PASS (9) |
| C | Studio request bodies posted to the real FastAPI app | C | PASS (9 of 35) |

## API / Endpoint Tests
- **Request contracts** — `sudo -n bash backend/scripts/run_autodesk_tests.sh <wt> tests/autodesk/test_ui_request_contracts.py -rA`
  - Output (excerpt): `PASSED test_ui_request_contract[studio-day.start]` `[studio-day.run]` `[studio-day.pause]`
    `[studio-day.resume]` `[studio-setup.create]` `[studio-setup.create_accelerated]` `[studio-setup.create_default_policy]`
    `[studio-setup.start]` `[studio-setup.run]` … `35 passed, 2 warnings in 6.09s`
  - After making the cleanup wait for a background replay to stop, three runs: `35 passed … | pool-closing lines: 0` ×3
  - Result: PASS
- **Desk backend suite** — `run_autodesk_tests.sh <wt> tests/autodesk tests/test_order_path_guard.py` → `134 passed, 3 warnings in 39.23s` — PASS
- **Staging desk API** (unchanged by this branch; checked 16:26 IST for #493): health 200, signed-out calls 401.

## UI / Playwright Tests
- **Specs:** all `frontend-v5/e2e/tests/autodesk-*.spec.ts` (desk + studio), config `frontend-v5/pw.autodesk.config.ts`
- **Command:** Docker `mcr.microsoft.com/playwright:v1.47.0-jammy`, no network: `npx tsc --noEmit -p tsconfig.json`;
  `npx vite build --config vite.autodesk.config.ts --outDir /tmp/ad-dist`; `npx vite preview … --port 5175 &`;
  `npx playwright test --config pw.autodesk.config.ts --output /tmp/pw-out`
- **Output (final run, after the last code change):**
  ```
  tsc exit=0 lines=0
  playwright exit=0
    ✓  137 [autodesk] › e2e/tests/autodesk-studio-trace.spec.ts:124:1 › AD-UI-153 autoplay plays to the end; Pause stops it (12.0s)
    149 passed (1.1m)
  shell 21 · overview 12 · agents 12 · scanner 14 · approvals 12 · simulator 10 · policies 14 ·
  studio 7 · studio-day 11 · studio-scenarios 8 · studio-setup 10 · studio-runs 9 · studio-trace 9
  ```
- **Scans of src/autodesk/studio:** no prototype sample ids (SIM-04xx, SCN-0xx, APR-31xx …); write calls only
  create/start/run (New simulation) and start/run/pause/resume (Trading day), all covered by contracts; no
  console/TODO/empty catch.
- **Visual:** desktop and phone screenshots compared with the design (scratchpad/shots: runs, setup, trace, trace-phone).
- **Result:** PASS

## Findings (backend gaps, not fixed here)
- No per-session summary: Trading day counts are derived from paging the whole event timeline (25 × 2,000 events cap).
- `seed` is stored but unused; `speed` / ACCELERATED_REPLAY change nothing; no checkpoints or restart.
- No run-comparison endpoint (computed in the browser; signals read up to 2,000 per run, the view says so at the cap).
- No sessions endpoint: weekday chips in New simulation can include NSE holidays (the API's 422 is shown).
- Simulation EOD is 18:00 in the schedule; the design's track runs to 18:30.

## Not verified (UNVERIFIED) and why
- Signed-in use on staging: needs a session token from the owner and #493 + this branch deployed.
- Design deviations to confirm (listed in the PR): New simulation adds a run name, a date range and an account-mode row
  (the API needs them); the eyebrow says "id given on create"; Trading day merges "Entry cutoff" into Intraday (no cutoff
  rule exists), adds a session select and an "All day" chip, one dot per agent per phase; Play replays the rest of the
  run in the background; Scenario library lists planned kinds instead of the sample catalogue.

## Verdict: PASS
