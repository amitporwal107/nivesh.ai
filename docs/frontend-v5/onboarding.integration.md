# Onboarding — API integration

See [cas-connect.md](./cas-connect.md) for the full CAS Connect SDK flow.

## Endpoints

| Action | Endpoint |
|---|---|
| Mint widget token | `POST /api/casparser/access-token` |
| Submit widget output | `POST /api/cas/sdk-callback` |
| Active portfolio check | `GET /api/portfolio/me` |
| CSV / Excel import | `POST /api/portfolio/upload` (multipart) |
| Resume legacy PDF parse | `GET /api/portfolio/upload-status/{task_id}` |
| Mark onboarding complete | `POST /api/user/complete-onboarding` |
| Set journey type | `POST /api/user/journey { journey_type }` |
| Save risk profile | `POST /api/user/risk-profile { answers[] }` |

## Three import modes — one widget

All three modes (`cas` PDF · `gmail` inbox · `cdsl` OTP) go through the same `@cas-parser/connect` widget and ship parsed JSON to `POST /api/cas/sdk-callback`. The frontend service is `runCasIngestion({ mode, onStatus, portfolioId? })` exported from `src/services/cas-ingestion.service.ts`.

## Stepper

Current 4-step UX: **Sign in · Connect investments · Goals · Review**. Connect is step 2; everything else is local form state.

## Already-set-up routing

On mount (post-auth) the page calls `getActivePortfolio()`. If a fresh snapshot exists, it switches to "your portfolio is ready — open the cockpit" instead of showing the 3 import cards. Stale snapshot (statement month older than current month) → soft warning above the import cards.

## States

- `idle` — show the 3 mode cards
- `importing` — overlay with status messages bubbled via `onStatus` callback
- `done` — success card with parsed totals
- `error` — banner with retry; falls back to `idle`
- `cancelled` — silently back to `idle` when user closes the widget

## CSV / Excel direct upload

`uploadFile(file, portfolioId?)` is wired but only the CAS flow has UI today. To re-enable CSV: add a 4th tab on the onboarding page that calls `casUploadService.uploadFile()` directly — synchronous response with parsed holdings.

## States to wire next

- Resume after reload: call `latestTask()` on mount; if `status === "processing"`, hydrate the importing overlay with the task and poll via `usePolling`.
- DPDP consent: `POST /api/compliance/consent` should fire alongside `complete-onboarding`.
