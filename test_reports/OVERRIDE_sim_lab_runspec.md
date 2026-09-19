# OVERRIDE — Simulation Lab → "Run spec template" tab

- **Branch:** detached at `96a29393` (worktree `/app/.claude/worktrees/ui-runspec`)
- **Date:** 2026-09-20
- **Scope of the skip:** the **staging / Playwright** half of `.claude/VERIFICATION_PROTOCOL.md` only.
- **Companion report (not a skip):** `test_reports/sim_lab_runspec.md` — the test cases, and real output for the
  eight cases that could be proven locally (`tsc --noEmit`, `npm run build`, YAML parse, value-by-value trace of the
  filled example back to the pre-registration, file/page parity, no-API-call check).

REASON: browser verification needs the page deployed, and app staging redeploys from `origin/dev`, which also feeds
the live login — a `dev` push is a live deploy and this task explicitly withheld that authorization ("Do NOT deploy
or push to dev", "Do NOT run git commit/push/stash"). The screen also sits behind `RequireAuth` plus the `sim_lab`
feature flag and needs a `session_token` I do not have, and `frontend-v5` has no component-test runner
(`package.json` scripts are dev / build / preview / typecheck only), so there is no local substitute. Rather than
fabricate a Playwright transcript or a screenshot, the work stops at the compiler and the data checks and says so.

## What is therefore UNVERIFIED (TC-8 … TC-14)

- That the `RUN SPEC TEMPLATE` tab appears in the strip and switches the panel (`sl-tab-runspec`).
- That the **Blank skeleton / Filled example · Run A** toggle swaps the YAML block and clears the copied state.
- That **Copy to clipboard** puts the shown YAML on the clipboard and shows the "Copied" state, and that the
  fallback message appears instead when the Clipboard API is missing or denied (insecure origin, denied permission).
  Both paths were reviewed in code; neither was exercised in a browser.
- That the tab renders when `/api/sim-lab/run` answers 503 or errors — the "renders with no snapshot" requirement.
  The code path exists (`STATIC_TABS` early return, plus the tab strip kept in the unavailable/error states) but has
  not been run.
- That a 403 account still cannot reach it (the access gate returns above the static-tab branch).
- No horizontal page scroll at 390 px, and correct reading in light and dark.

## What unblocks it

1. Owner authorization for a `dev` push, or a local dev stack (backend + `vite dev`).
2. `sim_lab` on for the verifying account, and a fresh `session_token` cookie.
3. Then, from `frontend-v5/`: `npx playwright test` driving `sl-tab-runspec`, `sl-runspec-variant-skeleton`,
   `sl-runspec-variant-example`, `sl-runspec-copy`, `sl-runspec-copy-state`, `sl-runspec-yaml`,
   `sl-runspec-step-04`, `sl-runspec-caveat-04`, `sl-runspec-rule-*` — at 390 px and at desktop width, in both
   themes. (No spec file was added: this task's file list does not include `frontend-v5/e2e/`.)
