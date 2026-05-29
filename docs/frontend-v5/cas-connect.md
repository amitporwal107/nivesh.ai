# CAS Connect SDK — frontend wiring

Mirrors the pattern from `amitporwal107/nivesh.ai@dev` `frontend/src/v4/screens/onboarding/Onboarding.jsx` + `api/portfolioIngestion.js`.

## Endpoints (corrected this pass)

| Endpoint | Purpose |
|---|---|
| `POST /api/casparser/access-token` | Mint short-lived widget token |
| `POST /api/cas/sdk-callback` | Ingest widget output (**canonical** — the path V4 actually uses) |
| `POST /api/portfolio/import-connect` | Legacy raw-JSON ingest. Kept for compat; new code should call `/sdk-callback`. |
| `POST /api/portfolio/upload` | CSV / Excel synchronous import only. PDF returns 410. |
| `GET /api/portfolio/me` | Active portfolio + snapshot (drives "already set up" routing) |
| `GET /api/portfolio/upload-status/{task_id}` | Poll in-flight PDF parse (legacy) |
| `GET /api/portfolio/upload-latest-task` | Resume after reload |

## Three modes

`cas` (PDF upload) · `gmail` (inbox scan) · `cdsl` (OTP demat fetch). Same widget, different mode flag.

## Service surface

`src/services/cas-ingestion.service.ts` exposes `runCasIngestion({ mode, portfolioId?, onStatus? })` returning:

```ts
{ ok: true, response, mode }       // success
{ ok: false, error }               // any failure
{ cancelled: true }                // user closed widget
```

The service lazy-loads `@cas-parser/connect`, mints a token via `casUploadService.getConnectToken()`, opens the widget, and on success POSTs the payload to `/api/cas/sdk-callback` via `casUploadService.sdkCallback()`.

## Popup callback route

The Gmail inbox flow uses an OAuth popup that redirects to a static page in the SPA. Path: `/cas-callback`. V4 implementation: tiny component that pings `window.opener` then closes itself; the SDK handles the actual token exchange. Add to the router as a public route (no auth wrapper).

## Onboarding component change

Replace the current Onboarding upload-tab handler with:

```tsx
import { runCasIngestion } from "@/services/cas-ingestion.service";
// ...
const out = await runCasIngestion({ mode, onStatus: setStatusMessage });
if (out.cancelled) return setStatus("idle");
if (!out.ok)      return setStatus("error");        // err in out.error
setStatus("done");                                  // result in out.response
```

The existing 3-tab Onboarding UI in `production/src/pages/Onboarding/index.tsx` already covers the three modes — only the click handlers need to call `runCasIngestion(mode)`.

## Dependencies

Add to `package.json`:

```json
"@cas-parser/connect": "^x.y.z",
"@react-oauth/google": "^0.12.x"
```

Exact versions: match whichever the V4 codebase pins (`frontend/package.json`).

## Still to wire (frontend follow-on)

1. Replace `Onboarding/index.tsx` upload-tab handler with `runCasIngestion("cas" | "gmail" | "cdsl")`.
2. Add `/cas-callback` route → minimal component that closes the popup (same as V4's `CasCallback.jsx`).
3. Surface `getActivePortfolio()` in the Onboarding page to handle "already set up" / stale-snapshot routing.
