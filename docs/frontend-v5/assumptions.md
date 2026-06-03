# Open assumptions

This file lists decisions I made while the user was asleep that may need verification.

## 1. Cookie name

OpenAPI says `session`. The Postman v4 collection uses `session_token` (set by `/api/auth/dev-set-cookie`). I assumed:
- **Prod / staging**: `session` cookie set by `POST /api/auth/google` (real OAuth).
- **Dev only**: `session_token` cookie set by `/api/auth/dev-set-cookie` for testing.

The frontend's HTTP client uses `credentials: "include"` so the browser ships whichever cookie was set. **No code change needed if my read is wrong** — the backend still gets the cookie.

## 2. Money unit

Wire format is rupees as a number with `_rs` suffix (`book_aum_rs`, `target_amount_rs`). I kept the domain model in **paise** (integer × 100) for arithmetic safety; mappers multiply on ingress, formatters divide on display.

Trade-off: an extra arithmetic op at the boundary, but no float drift in P&L deltas.

## 3. Portfolio summary

OpenAPI doesn't expose a single "portfolio summary" endpoint. I compose one client-side from:
- `/api/portfolio/holdings` → totalValue, totalCost, yearChange
- `/api/insights/v3-portfolio` → healthScore, grade

When a real composite endpoint ships (likely `/api/v3/portfolio/summary` or `/api/dashboards/overview`), swap the one method `realPortfolioAdapter.getSummary` to call it directly. No UI changes.

## 4. v4 dashboard endpoints

The Postman collection describes them; the OpenAPI YAML (truncated at the cutoff) didn't. I built `services/adapters/dashboards.adapter.ts` from the Postman shape and validate with Zod `.passthrough()` so unknown fields survive. First real call will surface any drift loudly.

## 5. Plan action → recommendation mapping

Plan actions have `verb` (string) + many optional fields. I bucket into Keep / Reduce / Add via regex on `verb`:
- `keep|hold|continue` → keep
- `reduce|trim|sell|exit|switch` → reduce
- `add|buy|increase|start|topup` → add
- everything else defaults to **add** (least destructive label)

If your backend uses different verbs, update `mapActionToRecommendation` in `services/adapters/plans.adapter.ts`.

## 6. Error envelope

Confirmed FastAPI standard `{ detail: string | Array<{ msg, loc, type }> }`. The `ApiError.fromResponse` extracts both `detail` (top-level message) and field-level errors (when `detail` is an array of validation errors).

## 7. Streaming chat

`/api/chat` supports streaming per the spec; current adapter only does the JSON response (single round-trip). Streaming is a follow-on — wrap with `EventSource` or a manual `ReadableStream` reader.

## 8. Impersonation context

`/api/intelligence/portfolio/360` requires `POST /api/mfd/profiles/{id}/activate` first. The `useActivateProfile` hook invalidates **all queries** on success because impersonation changes the meaning of nearly every endpoint's response. If you have specific queries that should NOT be invalidated (e.g. advisor-scoped lists), tag them with an `["advisor"]` prefix and filter the invalidate call.

## 9. Multipart uploads bypass http()

`services/api/http.ts` serialises JSON; multipart needs raw FormData. The CAS upload adapter uses direct fetch + the same correlation-id / observer hooks. If you swap to axios or another transport later, this is the second integration point (besides `http.ts`) that needs updating.

## 10. Sentry / Datadog observability

`lib/observability.ts` exposes a pluggable `Observer` interface with a console-only default. Wire your production observability stack at boot in `main.tsx` via `setObserver(myImpl)`.

## 11. Component tests

I authored one mapper test (`portfolio.mapper.test.ts`) as a scaffold. Vitest isn't installed yet; once you `npm i -D vitest @testing-library/react`, that file becomes runnable as-is.
