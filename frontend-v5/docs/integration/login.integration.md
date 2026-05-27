# Login — API integration

## Endpoints

| Hook | Endpoint |
|---|---|
| `useGoogleClientId()` | `GET /api/auth/google-client-id` |
| `useGoogleSignIn()` | `POST /api/auth/google { credential }` |
| `useMagicLink()` | hypothetical — current backend doesn't ship this; gated by domain check client-side |
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

## Magic-link fallback

The whitelist check is **client-side only** (`@gmail.com`, `@googlemail.com`, + 14 org domains). Backend doesn't ship a magic-link endpoint today. Treat this UI path as decorative until backend lands `POST /api/auth/email-magic` or similar — surface error toast if the user clicks Send.

## Mock mode

`apiConfig.useMock = true` returns a static `aarav.k@gmail.com` user. The Google SDK is **skipped** in mock mode (no network) and `signIn()` returns a `"mock-credential"` string.

## States

- Loading: GIS script + client id pending → "Loading…" label, button disabled.
- Error: GIS load failure → red mono line under the button.
- Mutation error: `googleSignIn` errors propagate through the global toaster.
