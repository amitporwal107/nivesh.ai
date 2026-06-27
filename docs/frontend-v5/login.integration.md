# Login — API integration

## Endpoints

| Hook | Endpoint |
|---|---|
| `useGoogleClientId()` | `GET /api/auth/google-client-id` |
| `useGoogleSignIn()` | `POST /api/auth/google { credential }` |
| `useMagicLink()` | `POST /api/auth/magic-link { email }` — self-serve whitelist request; gated by domain check client-side too |
| (email link) | `GET /api/auth/magic-link/validate?token=…` — opened from the email, adds the address to the whitelist, redirects to `/login` |
| `useMe()` | `GET /api/auth/me` |
| `useLogout()` | `POST /api/auth/logout` |

## Flow

1. Mount → `useGoogleClientId()` fetches the OAuth client id (out of the bundle).
2. `useGoogleIdentity()` hook lazy-loads `https://accounts.google.com/gsi/client` and initialises the SDK with the client id.
3. User clicks "Continue with Google" → `gis.signIn()` resolves with `credential` (Google ID token).
4. `googleSignIn.mutateAsync(credential)` → `POST /api/auth/google` → backend sets `session` cookie (HTTP-only).
5. On success → `navigate("/onboarding")`.

## Cookie

The `session` cookie is HTTP-only. The frontend cannot read it. We rely on `useMe()` to confirm authentication — a 200 means logged in, a 401 means redirect to `/login` (handled by `RequireAuth`).

## Magic-link whitelist validation

Self-serve path behind "or a whitelisted email". Allowed domains are
`@gmail.com` / `@googlemail.com` (checked client-side *and* enforced by the
backend).

1. User submits an email → `POST /api/auth/magic-link { email }`.
   - Already whitelisted → no-op; backend returns a friendly "already approved"
     message (no link is sent, the address is **not** re-added).
   - Not whitelisted → backend creates a one-time token (valid **24h**) and
     emails a validation link via SMTP (`services/email_service.py`). The
     address is **not** added to the whitelist yet.
2. User opens the link → `GET /api/auth/magic-link/validate?token=…`:
   - valid → email is added to the whitelist (idempotent), token is burned,
     redirect to `/login?validated=1`.
   - expired/used/invalid → redirect to `/login?magic_error=<reason>`.
3. Back on `/login`, the page reads `?validated=1` / `?magic_error=` and toasts
   the outcome. The user then signs in (whitelist only gates access; auth itself
   is still Google OAuth).

**Email delivery** requires SMTP secrets (`SMTP_HOST`, `SMTP_USERNAME`,
`SMTP_PASSWORD`, optional `SMTP_PORT` / `SMTP_FROM` / `SMTP_STARTTLS`, and
`PUBLIC_APP_URL` for absolute links) configured in the admin secrets console.
When SMTP is unconfigured the endpoint fails loudly (`SYS-003`) rather than
pretending a link was sent.

## Mock mode

`apiConfig.useMock = true` returns a static `aarav.k@gmail.com` user. The Google SDK is **skipped** in mock mode (no network) and `signIn()` returns a `"mock-credential"` string.

## States

- Loading: GIS script + client id pending → "Loading…" label, button disabled.
- Error: GIS load failure → red mono line under the button.
- Mutation error: `googleSignIn` errors propagate through the global toaster.
