# Functionality Verification Report — Strategy Lab wizard ⇄ the shared strategy store (Save version, Clone, Open, PAPER LIVE)

- **Branch:** feat/strategy-store-wiring (stacked on feat/strategy-store-v2, PR #398), worktree /home/deploy/nivesh-strategy-copilot
- **Date:** 2026-10-28
- **Author:** Claude (FULL_STACK_DEVELOPER + DESIGN_ENGINEER + QA_ENGINEER)
- **Environment:** mocked Playwright on a production build (`vite build`, `/v5/`), `tsc --noEmit`; staging after #398 + this PR are merged and migration 026 runs
- **Changed areas:** backend routes/services: no (the routes are #398) · frontend src: yes

## Summary
The wizard (#393) had Save version and Clone disabled ("Saving arrives with the shared strategy store"). Its
`strategy/instance-store.ts` now calls #398's routes, and step 4 uses them:
- the first save creates the strategy (version 1);
- each later save is a new version from the one loaded, answered with the server's diff and the store's checks;
- a stale parent (another tab saved first) offers "save on top of version N";
- Clone copies the saved version and switches to the copy;
- a server without the store says so, and the legs stay on the page.

Saved structures appear under Existing strategies with the store's status words, and Open loads them on step 3 as that
version. A simulated trade of exactly a saved version sends `strategy_ref` (PAPER LIVE).

## Test Cases
> Authored UP FRONT (before the spec was changed). Spec: `frontend-v5/e2e/tests/copilot-app-desk-strategy-wizard.spec.ts`.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| WZ-13 | save | First save of the bull call spread | e2e | POST /api/strategy-builder/strategies with an Idempotency-Key. The body has the contract fixture's shape (same keys at every level), schema_version "2", NIFTY index, template bull_call_spread, 2 CALL legs with lot 75 and concrete strike/expiry. Answer "Saved as version 1"; strip `version 1`; Save disabled until something changes; Clone enabled || PASS |
| WZ-20 | version | Edit a strike, then save | e2e | `version 1 · unsaved changes` shown, then POST …/{id}/versions with parent_version_id = v1. The diff line is shown and the strip reads `version 2` || PASS |
| WZ-21 | stale | The server answers 409 stale_parent | e2e | Amber note with the server's words, then "Save these legs on top of version 2". Clicking it re-posts with parent = that version || PASS |
| WZ-22 | clone | Clone after a save | e2e | POST …/{id}/clone {name: "<name> (copy)", version_id}. The name field changes, the strip reads `version 1`, and the note says you are editing the copy || PASS |
| WZ-23 | not available | The server answers 503 store_not_migrated, and separately an older backend's 422 list | e2e | The note reads NOT_YET. Legs and step unchanged, nothing else posted || PASS |
| WZ-24 | paper link | Start a trade right after a save; edit, then start again | e2e | The first POST carries `strategy_ref {strategy_id, version_id}`; after an edit (unsaved changes) the body has no strategy_ref || PASS |
| WZ-25 | list + open | include=summary returns a v2 row: an open desk trade cites it, and a second row has a STALE run | e2e | Rows `store:…` show PAPER LIVE with the trade's P/L, then STALE, with v<latest>; the citing trade is not listed twice. Open → step 3 with its legs and settings, strip `version N`, Save disabled (no change) || PASS |
| WZ-13…19 | regression | The existing wizard cases | e2e | Unchanged except WZ-13 (rewritten above); all pass || PASS |
| TSC | types | `tsc --noEmit` | unit | 0 errors || PASS |
| REG | regression | The desk / Strategy Lab specs vs the dev baseline (`baseline_frontend_20261028.md`: 252 passed, 3 known failures, 16 skipped) | e2e | No new failure || RUNNING |
| LIVE | staging | After merge + migration: save, version, clone and open a structure on staging with a session; rows in `strategy_versions` | api+data | as above || PENDING (needs #398 merge + migration 026 + this PR + a session) |

## UI / Playwright Tests (real output, 2026-10-28)
Image `mcr.microsoft.com/playwright:v1.47.0-jammy`, `@playwright/test` 1.60 (volume `wl-fe-node-modules`), Chromium from
`pw-browsers-1223`, `--network none`. Production build `VITE_USE_MOCK_API=false VITE_BASE=/v5/ npx vite build`, served by
`vite preview` on :5174, then `npx playwright test --config pw.copilot-app.config.ts`.
- `tsc --noEmit -p tsconfig.json` → exit 0, no output, run twice.
- `e2e/tests/copilot-app-desk-strategy-wizard.spec.ts` → `29 passed (26.7s)`: WZ-1 … WZ-19 (WZ-13 rewritten), WZ-20,
  WZ-21, WZ-22, WZ-23, WZ-24, WZ-24b, WZ-25. All passed on the first run.
- **Found while writing WZ-25, fixed before the run.** Postgres JSONB hands a stored document back in its own key order, so
  a plain `JSON.stringify` comparison would have marked every opened structure "unsaved changes". `contentKey` now
  compares canonical JSON (keys sorted). WZ-25 serves the stored definition with every object's keys reversed and checks
  that Save stays disabled.
- **Found by checking the wizard's values against #398's validator.** A cash template's `sizing.lots` is shares (up to
  100,000), and the backend capped it at 1,000. Fixed in #398 (commit 1aedbac7, with a test).
- **REG: every `copilot-app-desk-*`, `copilot-app-builder*` and `copilot-app-backtest-universe` spec (36 files) on this branch,
  same recipe:** `35 failed, 55 skipped, 1224 passed (14.2m)`. The failures are 32 + 3:
  - 32 in `copilot-app-desk-strategy-graphs.spec.ts`. That spec "fails there by design" under this recipe (its header): it
    needs the `VITE_STRATEGY_HARNESS=1` build. Run with its own `e2e/fe-run-stgraph.sh` on a copy of this branch's
    `frontend-v5`: `32 passed (15.1s)`.
  - 3 in `copilot-app-desk-strategy-ideas.spec.ts`: SI-6, SI-7, SI-7b. These are the three known failures of the baseline.
    Re-run on the `dev` snapshot be93f885 (same recipe): `3 failed`, the same SI-6 / SI-7 / SI-7b, and `16 passed`.
  - **No new failure.**

## Inputs required from user
- Merge #398, run migration 026 (deploy with `run_migrations=true`), then merge this PR. Merging this PR first is safe:
  the wizard then reads NOT_YET.
- A session token for the live check.

## Verdict: BLOCKED
