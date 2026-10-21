# OVERRIDE — scanner F&O line on every F&O-eligible row

REASON: the change is on branch feat/trading-desk-backend (worktree /home/deploy/nivesh-trading-desk), uncommitted and not deployed to staging, so the real-data check (GET /api/fno/scan/buildup on staging, and the scanner on staging) has not been run. Only mocked-API Playwright was run.

## What changed
- frontend-v5/src/pages/CopilotApp/screens/tradingdesk/ScannerTab.tsx: `FnoLine` under every scanner row (table and cards) whose stock is F&O-eligible (universe `fno_eligible`, or the build-up scan's own flag). Reads `useBuildup` (GET /api/fno/scan/buildup); no backend change.
- frontend-v5/e2e/tests/copilot-app-desk-scanner.spec.ts: two new tests (line shown on exactly the eligible rows; "scan didn't load" state).

## Run this turn (mocked /api, production build, docker playwright:v1.47.0-jammy)
- `npx tsc --noEmit -p tsconfig.json` -> exit 0
- `npx playwright test --config pw.copilot-app.config.ts e2e/tests/copilot-app-desk-scanner.spec.ts` -> `64 passed (42.9s)`, including
  "F&O analysis shows on every F&O-eligible row, and only on those" and
  "F&O analysis says so when the futures scan does not load, on eligible rows only", and the 390px no-sideways-scroll cases.

## UNVERIFIED
- Real staging /api/fno/scan/buildup output and row coverage vs the scanner's rows (the nidp.fno_bhavcopy table on rebuilt staging may be sparse).
- Visual check of the line at desktop width on staging data.
