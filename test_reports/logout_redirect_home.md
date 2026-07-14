# Functionality Verification Report — Logout redirects to public homepage

- **Branch:** fix/logout-to-homepage (PR → main / prod)
- **Date:** 2026-07-12
- **Author:** Claude (Full-Stack Developer)
- **Environment:** local Playwright (vite test server, base `/v5/`, mocked API), on a
  worktree cut from `origin/main`. Takes effect on prod deploy.
- **Changed areas:** backend routes/services: no · frontend src: yes
  (`frontend-v5/src/hooks/use-auth.ts`, test `frontend-v5/e2e/tests/workspace.spec.ts`)

## Summary
On sign-out, `useLogout` navigated to `/login` (→ `https://niveshcopilot.com/v5/login`),
dropping the user on the login wall. Changed both the `onSuccess` and `onError` paths to
`navigate("/")` — with the router's `/v5` basename this lands on the public homepage
`https://niveshcopilot.com/v5/`, the crawlable, purpose-explaining public surface (same
surface the Google OAuth branding fix targets). Updated the existing workspace test that
asserted the old `/login` behavior.

## Test Cases
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | use-auth | Compile after edit | type | `tsc --noEmit` exit 0 | PASS |
| TC-2 | logout | Signed-in user clicks "Sign out" in Settings → lands on homepage, not login | e2e | URL matches `/\/v5\/?$/` (i.e. `/v5/`), NOT `/v5/login` | PASS |

## UI / Playwright Tests
- **Spec:** `frontend-v5/e2e/tests/workspace.spec.ts` (`'Sign out' navigates to the public homepage`)
  - Command: `npx playwright test workspace.spec.ts -g "Sign out" --project=desktop-chrome --reporter=list`
  - Output (real, unedited):
    ```
    Running 1 test using 1 worker
      ✓  1 [desktop-chrome] › workspace.spec.ts:125:3 › Settings (mocked) › 'Sign out' navigates to the public homepage (/v5/), not the login wall (8.1s)
      1 passed (11.7s)
    ```
  - Result: PASS
- **Typecheck:** `npx tsc --noEmit` → exit 0 — PASS

## API / Endpoint Tests (staging)
N/A — no backend changed. Logout endpoint contract (`POST /api/auth/logout`) unchanged;
only the post-logout client redirect target changed.

## Data Correctness
N/A — no data read/written.

## Inputs required from user
- none (mocked API; no session token needed).

## Verdict: PASS
