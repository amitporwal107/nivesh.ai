# Settings — API integration

## Endpoints

| Action | Endpoint | Status |
|---|---|---|
| Read profile | `GET /api/user/profile` | wired via `useMe()` |
| Logout | `POST /api/auth/logout` | wired via `useLogout()` |
| Export user data | `GET /api/compliance/export` | adapter not yet exposed |
| Delete account | `POST /api/compliance/delete` | adapter not yet exposed |
| Save consent | `POST /api/compliance/consent` | adapter not yet exposed |

## Local-only

- **Theme** (light / dark) — Zustand `ui.store.ts`, persisted to `localStorage` under key `nivesh.ui`.
- **Notification toggles** — UI-only; backend doesn't expose a notification-preference endpoint yet.

## States

Page never blocks — UI store is sync. The "Sign out" button awaits the `useLogout()` mutation, then routes to `/login`. On error it surfaces via the global toaster (the auth cookie may or may not be cleared depending on backend response; the `useLogout` hook calls `qc.clear()` regardless).

## Open

- Compliance adapter: thin wrapper around the three `/api/compliance/*` endpoints. Trivial to add — same pattern as `auth.adapter.ts`.
- Notification prefs: hook + backend endpoint TBD.
- Theme: consider sync'ing to a server-side preference once the backend ships `PATCH /api/user/preferences`.
