# Nivesh — frontend-v5

Standalone **sibling app** to `frontend/` in the `amitporwal107/nivesh.ai` monorepo. Own Vite dev server, own `package.json`, own build pipeline. Mounts at `/v5` via reverse-proxy (recommended) or as a separate subdomain.

## Why a sibling app

- Zero collision with v4 React / Tailwind / router versions
- Deletable in one PR when v5 graduates to be the new `frontend/`
- Independent dependency tree and lockfile

## Drop-in instructions

1. Drop this folder at the **repo root** of `amitporwal107/nivesh.ai`, sibling to `frontend/` and `backend/`:

   ```
   nivesh.ai/
   ├── backend/
   ├── frontend/          ← existing v4
   └── frontend-v5/       ← this app
   ```

2. Install + dev:

   ```bash
   cd frontend-v5
   cp .env.example .env.local
   npm install
   npm run dev               # http://localhost:5174
   ```

   Change the port in `vite.config.ts` if 5174 collides with v4's dev server.

3. Production deploy: build (`npm run build`) → static assets in `frontend-v5/dist/` → reverse-proxy `/v5/*` to that dist. Same nginx/CDN setup as v4, separate route.

## Routes

All routes are mounted at the v5 app root. If serving under `/v5/*`, configure the BrowserRouter `basename="/v5"` in `src/main.tsx`:

```tsx
<BrowserRouter basename="/v5">
  <App />
</BrowserRouter>
```

| Path              | Screen          |
|-------------------|-----------------|
| `/dashboard`      | Dashboard       |
| `/portfolio`      | Portfolio       |
| `/funds/:id`      | Fund Details    |
| `/concentration`  | Concentration   |
| `/diversification`| Diversification |
| `/risk`           | Risk Analysis   |
| `/recommendations`| Recommendations |
| `/chat`           | Chat            |
| `/settings`       | Settings        |
| `/login`          | Login (Google)  |
| `/onboarding`     | CAS / Gmail / CDSL onboarding |
| `/cas-callback`   | CAS Connect popup callback (TODO) |

## Mock ↔ real backend

```bash
# .env.local
VITE_USE_MOCK_API=false
VITE_API_BASE_URL=https://staging.niveshcopilot.com
```

Cookie name is `session` (HTTP-only); `credentials: "include"` is set globally in `services/api/http.ts`. For local dev with cookies cross-origin to staging, ensure staging CORS allows `http://localhost:5174` with `Access-Control-Allow-Credentials: true`.

## Stack

| Concern        | Choice |
|----------------|--------|
| Framework      | React 18 + TypeScript (strict) |
| Bundler        | Vite |
| Styling        | Tailwind (CSS-variable design tokens) |
| Routing        | React Router v6 |
| Data           | TanStack Query + Zod runtime contracts |
| UI state       | Zustand (persisted UI prefs, toast queue) |
| Charts         | Recharts (+ hand-rolled SVG for tight controls) |
| Component lib  | shadcn-style primitives in-tree |

## API integration

Every backend call goes through `src/services/`:

```
api/        http client (cookie creds, ETag, retry, observability)
contracts/  Zod schemas mirroring backend/docs/openapi/*.yaml (snake_case)
mappers/    contract → domain ViewModel
adapters/   real backend impls (one per OpenAPI tag)
mock/       parallel mock impls (signature-identical)
index.ts    factory — VITE_USE_MOCK_API picks real vs mock
```

13 adapters live: `auth`, `portfolio`, `plans`, `goals`, `analytics`, `insights`, `dashboards`, `advisor`, `mfd`, `chat`, `cas-upload`, `scenarios`, `intelligence`. Audit trail in `docs/integration/contract-audit-2026-05-28.md`. CAS Connect wiring in `docs/integration/cas-connect.md`.

## Production-readiness checklist

- [ ] `npm install` clean (add `@cas-parser/connect` + `@react-oauth/google` matching v4's pinned versions)
- [ ] `npm run build` clean
- [ ] Onboarding handlers swapped to `runCasIngestion(mode)` (see `docs/integration/cas-connect.md`)
- [ ] `/cas-callback` route added (mirror of v4's `CasCallback.jsx`)
- [ ] `RequireAuth` wired into router
- [ ] CORS / cookie attributes confirmed on staging for the v5 origin
- [ ] Sentry / Datadog observer plugged in via `setObserver()`

## File layout

```
frontend-v5/
├── package.json, tsconfig.json, vite.config.ts, tailwind.config.ts
├── index.html, postcss.config.js, .env.example
├── docs/
│   └── integration/{architecture,portfolio,contract-audit-2026-05-28,cas-connect,assumptions}.md
└── src/
    ├── App.tsx, main.tsx, routes.tsx, index.css
    ├── types/, mock-data/, services/, hooks/, stores/, lib/
    ├── components/{ui,layout,charts,shared}/
    └── pages/<Screen>/
```
