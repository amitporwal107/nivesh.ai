# Functionality Verification Report — Google OAuth branding fixes (crawlable landing + Limited Use)

- **Branch:** fix/oauth-branding-crawlable (PR → main / prod)
- **Date:** 2026-07-12
- **Author:** Claude (Full-Stack Developer)
- **Environment:** local build + Playwright (vite test server, base `/v5/`), re-verified on a
  worktree cut from `origin/main`. NOT yet deployed to live — takes effect on prod deploy.
  Re-run on this main-based branch: `tsc --noEmit` exit 0 · `vite build` `✓ built in 26.35s`
  exit 0 · Playwright `3 passed (10.8s)` · `dist/index.html` carries `name="description"` (1)
  and `<noscript>` (1) with purpose + read-only Gmail/CAS + `/v5/privacy` + `/v5/terms`.
- **Changed areas:** backend routes/services: no · frontend src: yes (`frontend-v5/index.html`, `frontend-v5/src/pages/Privacy/index.tsx`)

## Summary
Google's OAuth branding verification rejected the app with three issues: (1) home page behind a
login page, (2) home page does not explain the app's purpose, (3) consent-screen app name
`nivesh.ai` ≠ homepage name `Nivesh`. Root cause of (1)+(2): `niveshcopilot.com/v5` is a
client-side React SPA whose served HTML is an empty shell (`<div id="root">`), so Google's
non-JS branding crawler sees no public content. This change makes the raw `/v5/` HTML
crawlable — a purpose-bearing `<meta name="description">`, a descriptive `<noscript>` fallback
covering the app's purpose + read-only Gmail/CAS use + public privacy/terms links — so a
server-side fetch returns readable, login-free content. It also adds the required Google API
Services **Limited Use** disclosure to the Privacy page (needed for the restricted
`gmail.readonly` scope review). Issues (3) app-name and the Terms-link fix are Google Cloud
Console changes (out of code scope) and are handed to the user.

## Test Cases
> Authored up front from the 3 rejection reasons + the restricted-scope Limited Use requirement.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | index.html | Production build compiles with the edits (tsc + vite) | build | exit 0, dist emitted | PASS |
| TC-2 | index.html | Built `dist/index.html` carries a purpose-bearing meta description | e2e (raw HTML) | `name="description"` + purpose text present | PASS |
| TC-3 | index.html | Non-JS fetch of `/v5/` (as Google's crawler) exposes purpose, Gmail use, privacy/terms links | e2e (request, no JS) | `<noscript>` w/ purpose + read-only Gmail + `/v5/privacy` + `/v5/terms` | PASS |
| TC-4 | Privacy | Privacy page renders the Google Limited Use disclosure + policy link | e2e (rendered) | "Limited Use requirements" visible; link → user-data-policy URL | PASS |

## API / Endpoint Tests (staging)
N/A — no backend routes/services changed.

## UI / Playwright Tests
> Real runner output.

- **Spec:** `frontend-v5/e2e/tests/oauth-branding.spec.ts`
  - Command: `npx playwright test oauth-branding --project=desktop-chrome --reporter=list`
  - Output:
    ```
    Running 3 tests using 2 workers
      ✓  2 [desktop-chrome] › oauth-branding.spec.ts:14:3 › crawlable landing shell (non-JS fetch) › raw /v5/ HTML carries a purpose-bearing meta description (2.4s)
      ✓  1 [desktop-chrome] › oauth-branding.spec.ts:22:3 › crawlable landing shell (non-JS fetch) › raw /v5/ HTML has a <noscript> fallback describing the app + legal links (2.5s)
      ✓  3 [desktop-chrome] › oauth-branding.spec.ts:38:3 › Privacy Limited Use disclosure › privacy page renders the Google API Services Limited Use text + link (3.1s)
      3 passed (10.2s)
    ```
  - Result: PASS

## Build evidence (production artifact — what Google's non-JS fetch receives)
- Command: `npm run build`  → `✓ built in 47.61s` (exit 0; `tsc -b` clean)
- Command: `grep -oE "reads every|read-only|Gmail|CAS statements|/v5/privacy|/v5/terms" dist/index.html | sort | uniq -c`
  - Output:
    ```
          1 /v5/privacy
          1 /v5/terms
          2 CAS statements
          3 Gmail
          2 read-only
          2 reads every
    ```
- Built `<title>`: `Nivesh — portfolio-intelligence copilot for Indian investors`
- `dist/index.html` contains `name="description"` (count 1) and one `<noscript>` block.

## Data Correctness
N/A — no data read/written; changes are static HTML + a legal-copy section.

## Scope NOT covered here (handed to user — cannot be done from code)
- **Fix 3 (app name):** rename OAuth consent app `nivesh.ai` → `Nivesh` in Google Cloud Console
  (`/auth/overview`). Console-only.
- **Fix 4 (terms link):** change Branding "Terms of service" from `…/v5/privacy` → `…/v5/terms`.
  Console-only.
- **Live effect:** these code fixes only affect Google's crawler once **deployed to `dev`** (the
  live branch). Current verification is local build + Playwright, not the live `niveshcopilot.com`.

## Inputs required from user
- none (public pages; no session token needed).

## Verdict: PASS
