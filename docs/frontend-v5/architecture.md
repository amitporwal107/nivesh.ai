# API Integration Layer — architecture

This file explains how `src/services/` is laid out and why.

## Layers

```
┌──────────────────────────────────────────────────────────────┐
│  Pages / components                                          │
│  (NEVER imports from contracts/, mappers/, http; only hooks) │
└──────────────────────────────────────────────────────────────┘
                          ↓ React Query
┌──────────────────────────────────────────────────────────────┐
│  hooks/use-*.ts        (useQuery / useMutation)              │
└──────────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────────┐
│  services/index.ts     (factory — picks real or mock)        │
└──────────────────────────────────────────────────────────────┘
                ↓                          ↓
┌─────────────────────────┐    ┌──────────────────────────────┐
│  adapters/*.adapter.ts  │    │  mock/*.mock.ts              │
│  http → contract → map  │    │  in-memory fixtures + delay  │
└─────────────────────────┘    └──────────────────────────────┘
        ↓
┌──────────────────────────────────────────────────────────────┐
│  contracts/*.contract.ts   Zod schemas — wire DTOs           │
│  mappers/*.mapper.ts       contract → domain ViewModel       │
│  api/http.ts               fetch wrapper · creds · timeout   │
│  api/errors.ts             ApiError taxonomy                 │
│  api/config.ts             env-driven                        │
└──────────────────────────────────────────────────────────────┘
```

## Rules

1. **Components import only from `services/index.ts` (via hooks).** Direct imports from `contracts/`, `mappers/`, or `http.ts` are not allowed.
2. **Contracts use snake_case** (mirror the wire). Mappers convert to the camelCase domain models in `types/`.
3. **Mock and real adapters share the exact same TypeScript interface.** If the real adapter grows a method, the mock must implement it or the factory won't compile.
4. **All responses are validated with Zod.** `passthrough()` is fine on objects with unknown future fields; strict typing where we depend on the shape. Drift surfaces as `ApiError({ kind: "contract_drift" })`.
5. **Money** is stored in **paise** (integer × 100) in domain models. Wire format is **rupees as number** (`_rs` suffix). Mappers multiply on ingress.
6. **Auth** is the `session` HTTP-only cookie. `credentials: "include"` is set globally in `http.ts` — components never touch it.
7. **Observability**: every request emits start / end / error events via `lib/observability.ts`. The console implementation is the default; swap with `setObserver(SentryObserver)` for prod.

## ApiError taxonomy

| Kind             | Maps from                          | UI behaviour |
|------------------|------------------------------------|--------------|
| `network`        | fetch threw, no response           | retry (transient), then ErrorState |
| `timeout`        | AbortController fired              | retry, then ErrorState |
| `auth` (401)     | session expired / not logged in    | redirect to `/login` |
| `forbidden` (403)| not entitled                       | block the action, show toast |
| `not_found` (404)| resource gone                      | EmptyState or 404 page |
| `validation` (400/422) | bad input                    | field-level errors via `error.fields` |
| `rate_limit` (429)| backend throttle                  | retry with backoff |
| `server` (5xx)   | backend bug / dependency down      | retry, then ErrorState |
| `contract_drift` | Zod schema mismatch                | ErrorState with correlation ID — alert Sentry |

## Mock ↔ real switch

Set `VITE_USE_MOCK_API=false` in `.env.local` to hit a real backend. The factory in `services/index.ts` is the only place that branches. No other code changes required.

## Adding a new endpoint

1. Add the Zod schema to `services/contracts/<resource>.contract.ts`.
2. Add a mapper in `services/mappers/<resource>.mapper.ts` (pure function — no fetch).
3. Add the method to `services/adapters/<resource>.adapter.ts` (uses `http(...)`).
4. Implement the same method in `services/mock/<resource>.mock.ts`.
5. Expose via `services/index.ts`.
6. Add a hook in `hooks/use-<resource>.ts` (React Query).
7. Document in `docs/integration/<screen>.integration.md`.

## Observability targets

To wire Sentry / Datadog, implement the `Observer` interface in `lib/observability.ts` and `setObserver(yourImpl)` once at boot:

```ts
import { setObserver } from "@/lib/observability";

setObserver({
  onRequestStart() {},
  onRequestEnd({ correlationId, durationMs, status, url }) {
    DD_RUM.addTiming(`api.${url}`, durationMs);
  },
  onRequestError({ error, correlationId, url }) {
    Sentry.captureException(error, { extra: { correlationId, url } });
  },
});
```
