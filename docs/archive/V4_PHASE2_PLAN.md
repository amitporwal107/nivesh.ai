# V4 Phase 2 — build plan

## Decisions captured (locked)

1. **Drop the broker connect onboarding card.** Backend has no native broker OAuth.
2. **Portfolio Dashboard** — design spec pending from user. Skip this screen for now.
3. **React Router under basename="/v4"** — mirror the V3 pattern; no breaking changes to V2 or V3.
4. **Same bundle as V2/V3.** V4 lives at `frontend/src/v4/` and is lazy-loaded by `App.js` when `pathname.startsWith("/v4")`. Same React build, same Tailwind, same Radix, same deploy artefact. New nginx `/v4/` location mirrors the existing `/v3/` block.

## Why same-bundle (not a separate Vite app)

The existing infra deliberately serves V2 + V3 from one React build at `/usr/share/nginx/html/`. `BrowserRouter basename` picks the SPA, asset URLs already carry `/v2/static/` so they work from any basename. Adding V4 the same way costs ~100 lines (one `App.js` branch + one nginx block) and inherits the existing build pipeline + dep set. A separate Vite app would duplicate `node_modules`, fragment auth handling, and require a parallel deploy story for zero meaningful benefit.

V4 still gets:
- React Router 6 (already used; V4 owns its own `<Routes>` under its basename)
- A dedicated API client + adapter layer (`frontend/src/v4/api/`)
- Its own Tailwind theme tokens (`frontend/src/v4/theme/`) so V4's design language doesn't bleed into V2

## Scope (8 of 9 P0 screens — Portfolio Dashboard pending)

| # | Screen | V4 mockup id | V2 reuse | Build order |
|---|---|---|---|---|
| 1 | Homepage (public) | s-home | `pages/Landing.js` | 1 — shakedown |
| 2 | Onboarding (CAS) | s-onboard | `OnboardingCopilotWrapped.jsx` | 2 |
| 3 | AI Copilot Landing | s-landing | `ChatView.js` | 3 |
| 4 | Plan Board | s-plan | `v2/PlanBoardView.js` | 4 |
| 5 | Concentration | s-d_conc | `insights/ConcentrationAnalyticsTab.jsx` | 5 |
| 6 | Diversification | s-d_div | `InsightsView.js` (sub-section) | 6 |
| 7 | Risk | s-d_risk | `InsightsView.js` (sub-section) | 7 |
| 8 | Goals | s-d_goals | `goals/GoalsView.jsx` | 8 |
| 9 | Portfolio Dashboard | (pending) | `v2app/screens/V2HomeScreen.jsx` (likely) | Wait for spec |

## Directory layout (new)

```
frontend/src/v4/
├── index.js                          # exports V4App (mirrors v3/index.js)
├── App.jsx                           # top-level layout + nav shell
├── navigation/
│   └── V4Router.jsx                  # React Router routes for the 9 screens
├── theme/
│   ├── tokens.css                    # V4 design tokens (.v4 scope)
│   ├── reset.css
│   └── fonts.css
├── api/
│   ├── client.js                     # single fetch wrapper + error envelope
│   └── adapters/                     # per-screen response reshapers
│       ├── landing.js
│       ├── concentration.js
│       ├── diversification.js
│       ├── risk.js
│       ├── plan.js
│       ├── goals.js
│       └── onboarding.js
├── hooks/                            # V4-specific hooks (data + UI state)
│   ├── useV4Auth.js                  # thin re-export of V2 useAuth
│   ├── useHealthScore.js
│   ├── useActionPlan.js
│   └── ...
├── components/                       # shared V4 components (cards, badges)
│   ├── HealthScoreCard.jsx
│   ├── RecommendationMatrix.jsx
│   ├── ApplyFooter.jsx
│   └── ...
└── screens/
    ├── Homepage.jsx
    ├── Onboarding.jsx
    ├── CopilotLanding.jsx
    ├── PlanBoard.jsx
    ├── Concentration.jsx
    ├── Diversification.jsx
    ├── Risk.jsx
    └── Goals.jsx
```

## Wiring changes (additive, V2/V3 untouched)

### `frontend/src/App.js`
- Add `const V4App = React.lazy(() => import("@/v4"));`
- Update `detectAppMode()` to recognise `/v4` prefix → return `"v4"`.
- Update basename selector: `mode === "v4" ? "/v4" : mode === "v3" ? "/v3" : "/v2"`.
- Update `AppInner` to mount `<V4App />` when `mode === "v4"`.

### `deploy/nivesh-app/nginx.conf` (prod) + `deploy/nivesh-staging/app-frontend-nginx.conf` (staging)
- Add a `location /v4/ { alias /usr/share/nginx/html/; try_files $uri $uri/ /v4/index.html; … }` block, mirroring the existing `/v3/` block exactly.

No changes to V2 routes, V2 components, V2 hooks, or any backend code.

## Build approach

- **Per screen workflow**: implement V2 fetch logic in the adapter → render V4 mockup components with the adapter's shape → manual smoke test → mark screen ready.
- **Adapter layer is the bridge**: every backend call goes through `frontend/src/v4/api/client.js`. Every component consumes V4-shaped data only. If a 🔴 GAP card appears, the adapter substitutes a static fallback or hides the affordance — never invents data.
- **Reuse V2 hooks where direct**: `useAuth()` from `frontend/src/context/AuthContext.js`, `useNumberFormat()` from `frontend/src/context/NumberFormatContext.js`. V4 wraps them in `useV4Auth` / `useV4Format` for ergonomics but doesn't reimplement.
- **No Capacitor.** V4 is web-only. Mobile renders via responsive Tailwind from the same components, or via dedicated mobile components keyed off `useMediaQuery` — TBD per screen.

## Phase 2 milestones

1. **M1 — Scaffold + Homepage** (~½ day) — V4 routing wired, `/v4/` returns a working Homepage matching the V4 mockup. V2/V3 unchanged. → **DONE = the user can hit `/v4/` on staging and see the new landing.**
2. **M2 — Auth + Onboarding** (~1 day) — Google sign-in routes back into V4, onboarding wizard with Gmail/CAS upload paths (no broker card).
3. **M3 — Copilot Landing + Plan Board** (~1 day) — chat-first surface, action plan view.
4. **M4 — Concentration + Diversification + Risk dashboards** (~2 days) — share the 2-3 `Insights`-equivalent fetches.
5. **M5 — Goals** (~½ day).
6. **M6 — Portfolio Dashboard** (after user provides spec).

Total estimated ~5-6 dev days for the 8 in-scope screens, excluding Portfolio Dashboard.

## Verification gates per milestone

- **No V2/V3 breakage**: at every commit, manually hit `/v2/app` and `/v3/` on staging; both must render exactly as before.
- **Bundle size delta**: V4 is lazy-loaded, so V2 first-paint is unaffected. Check chunk sizes after each milestone.
- **Adapter contract test**: each adapter has a small fixture in `frontend/src/v4/api/adapters/__tests__/` that pins the input → output transform. When the backend changes shape, the test fails before the screen does.

## What's out of scope for Phase 2

- Phase 2 does NOT modify any backend route, schema, or migration.
- Phase 2 does NOT touch the V2 or V3 frontend code paths.
- Phase 2 does NOT introduce a new build tool, package manager, or deploy story.
- Phase 2 does NOT include the deferred screens (s-builder, s-alloc, s-d_tax, s-d_perf, s-recs, s-adv_*).
