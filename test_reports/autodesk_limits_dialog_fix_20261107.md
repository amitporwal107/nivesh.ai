# Functionality Verification Report — Policies: the limits dialog reopened after a save

- **Branch:** fix/autodesk-limits-dialog-close, from dev 8d0b5449
- **Date:** 2026-11-07 ~14:00 IST
- **Author:** Claude (full-stack developer + QA)
- **Environment:** Playwright on the production build (Docker, no network), API route mocks. Not deployed.
- **Changed areas:** frontend src: `frontend-v5/src/autodesk/screens/policies/data.ts` (one line + comment). Backend: none.

## Summary
After saving limits, the dialog could reopen offering "version 3" instead of closing, though the save had worked. The save counted as finished only after all desk data had refreshed. The refreshed list could arrive first and move the version-keyed policy query to v2, leaving it empty for a moment; the screen renders the dialog only with a policy, so the dialog unmounted and TanStack Query dropped its close callback. When v2 loaded, the dialog came back as a fresh form. A second save from it would create another version. Now the save finishes when the API accepts it and the refresh runs in the background.

## Test Cases
| ID | Case | Result |
|---|---|---|
| AD-UI-74b (new, docs/autodesk/ui_testcases/policies.md) | The refreshed list arrives before the save has finished: the dialog closes, stays closed, exactly one POST | PASS |

## UI / Playwright Tests
Command: Docker `mcr.microsoft.com/playwright:v1.47.0-jammy`, no network, on the production build (`pw.autodesk.config.ts`).
- AD-UI-74b before the fix, 5 repeats: `5 failed`
- AD-UI-74b after the fix, 5 repeats: `5 passed (14.5s)`
- `autodesk-policies.spec.ts` × 8 after the fix: `120 passed (1.4m)`
- All desk specs: `161 passed (1.7m)`; `tsc exit=0`; `build exit=0`
- How it was found: on dev merged with PR #500, `autodesk-policies.spec.ts` × 8 gave `2 failed, 110 passed` (AD-UI-74, AD-UI-76); the page snapshot showed "Saving creates version 3" and "Save new version" disabled.

## API / Endpoint Tests
None: no backend change and no request body changed.

## Not verified (UNVERIFIED) and why
- Browser behaviour is on route mocks. On staging the data refreshes over a real network, not checked until this is deployed.
- This fix merged with PR #500 has not been run together yet.

## Verdict: PASS
