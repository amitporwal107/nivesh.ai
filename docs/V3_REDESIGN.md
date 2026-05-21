# V3 Mobile + Web Redesign — Architecture & Integration Guide

**Branch:** `feature/v3-mobile-web-redesign`
**Mount path:** `/v3` (full URL `/v2/v3/...` because the SPA basename is `/v2`)
**Status:** Foundation shipped — all primitives, layouts, adapters, and 14 screens render under both mobile and desktop shells. Backend untouched. V2 routes unaffected.

## 1 · Why V3 lives alongside V2

V2 is the production experience and ships continuously. V3 is the persona-driven redesign per the attached Figma spec (`nivesh_copilot_figma_spec.md`, `nivesh_copilot_design.html`, `nivesh_copilot_figma.svg`). To roll it out without risking V2 we:

- Built every V3 file inside one isolated directory: [frontend/src/v3/](../frontend/src/v3/).
- Scoped every style under a single `.v3` CSS class so V2 sees zero global side-effects.
- Lazy-loaded the V3 entry into a single `Suspense` boundary in [frontend/src/App.js](../frontend/src/App.js) — V2 bundle size is unchanged.
- Re-used existing auth via `ProtectedRoute`; no new auth code.
- Did **not** modify the backend, API contracts, DB schema, or `package.json` (only Google Fonts CDN added).

V3 routes are reachable at `/v2/v3/home`, `/v2/v3/portfolio`, etc. To open V3 from V2 link to `/v2/v3` directly — when V3 is ready for full rollout, the basename can be flipped and V2 stays untouched.

## 2 · Directory map

```
frontend/src/v3/
├── theme/                  Design tokens (tokens.css), fonts.css, reset.css
├── components/             Spec §2 primitives (PersonaStrip, HeroCard, CompactCard, …)
│   ├── viz/                Micro-vizzes (FundCountHistogram, OverlapDonut, …)
│   ├── layout/             Shells (MobileShell, DesktopShell, Sidebar, BottomNav, …)
│   └── pickers/            AgentPicker, ModelPicker, generic Sheet
├── screens/                14 screens — home, chat, onboarding, dashboard, portfolio
│                           (and diversification/concentration), risk (+ stress),
│                           tax, performance, advisor, market, settings, profile
├── adapters/               View-model adapters (personas, promptCatalog, portfolio)
├── navigation/             V3Router, route registry, ResponsiveLayout
├── hooks/                  useBreakpoint, useSheet
├── lib/                    cn(), inr/inrCompact/pct/count/dateLabel
├── assets/                 Placeholder slots for Figma SVG exports
└── index.js                V3App root (mounts <V3Router> under .v3 scope)
```

## 3 · Design tokens (strict to spec §1)

All tokens are CSS variables on `.v3` — see [v3/theme/tokens.css](../frontend/src/v3/theme/tokens.css). The palette is hard-coded saffron + indigo + warm paper-black; you do not theme V3 with the V2 ThemeContext — light/dark is a future enhancement.

Key choices to preserve:

- **Warm paper-black** background `#0A0908` with saffron/indigo radial atmosphere on body.
- **Fraunces** (display) + **Geist** (body) + **Geist Mono** (eyebrows, data) — loaded once in [public/index.html](../frontend/public/index.html).
- **Spacing scale** 4·6·8·10·12·14·16·18·20·24·28·36·48·64 — no off-scale values.
- **Radii** 8·14·20·22·999 only.

## 4 · Components (spec §2)

Every primitive is a thin React component with explicit props and zero coupling to V2. Two primitives accept a `layout` prop ("mobile"/"desktop") that triggers spec-exact layout differences:

| Component | Where used | Notes |
|---|---|---|
| `BrandMark` | TopBar, Sidebar | The Devanagari "न" mark — never replace |
| `PersonaStrip` | Home, Dashboard, Profile | 11 persona variants from `adapters/personas.js` |
| `CategoryChip` | Home, Portfolio, Stress, Performance | 6 categories × 2 states |
| `HeroCard` | Every screen's first card | Two layouts: mobile vertical, desktop 2-col |
| `CompactCard` | Quick-analyses grids everywhere | Variable micro-viz via `viz` prop |
| `TinyChip` / `MoreQuestions` | Home, Chat | Collapsible chip cloud |
| `Composer` + `AgentPicker` + `ModelPicker` | Home, Chat | Bottom-sheet on mobile, popover on desktop |
| `Pill` · `IconButton` · `SectionHead` · `CategoryBadge` · `HeroVizPanel` | Re-used everywhere | Match spec §2.x exactly |

Micro-vizzes are deliberately inline SVG (not recharts) — they preview real data and need to scale crisp at any size: `FundCountHistogram`, `OverlapDonut`, `PerformanceLine`, `GoalBars`, `TaxPyramid`, `HealthGauge`.

## 4.5 · URL contract (nginx + SPA)

There are two valid entry-point URLs for V3 — they resolve to the same screens:

| URL typed | What happens | Final URL bar |
|---|---|---|
| `https://app/v3` | nginx 301 → `/v2/v3/` → SPA boots, V3Router runs first-run guard | `/v2/v3/home` (or `/v2/v3/onboarding`) |
| `https://app/v3/portfolio?x=1` | nginx 301 → `/v2/v3/portfolio?x=1` (path + query preserved) | `/v2/v3/portfolio?x=1` |
| `https://app/v2/v3/home` | direct hit, no redirect | `/v2/v3/home` |

The nginx rules live in [deploy/nivesh-app/nginx.conf](../deploy/nivesh-app/nginx.conf):

```nginx
location = /v3       { return 301 /v2/v3/; }
location = /v3/      { return 301 /v2/v3/; }
location /v3/        { return 301 /v2$request_uri; }
```

Why a 301 and not an alias: the SPA build uses `PUBLIC_URL=/v2/`, so the JS/CSS bundles inside `index.html` are baked with `/v2/static/...` paths. Serving `index.html` under `/v3/` directly would 404 the bundle requests. The redirect is the safest contract.

The client-side `<script>` guard in [public/index.html](../frontend/public/index.html) handles preview/dev environments where nginx isn't in front — it does the same `/v2`-prefix prepend at the document level. When nginx is in front, the 301 wins first and the guard is a no-op.

When V3 becomes the primary experience (GA), the path forward is:
1. Add a second build target with `PUBLIC_URL=/v3/`, or
2. Make the React Router basename dynamic (read from `<base href>` set by nginx based on location).

Either way, the URL contract above is the public-facing surface — no app code needs to change to flip the marketing entry point.

## 5 · Routing & layout

[`v3/navigation/V3Router.jsx`](../frontend/src/v3/navigation/V3Router.jsx) is a single nested `<Routes>` with `ResponsiveLayout` as the layout route. Every screen is lazy-loaded; each gets a spec-color skeleton.

[`navigation/routes.js`](../frontend/src/v3/navigation/routes.js) is the **single registry** that drives:

- The `<Route>` mounts (paths)
- Mobile `BottomNav` (entries with `bottomNav: true`)
- Desktop `Sidebar` groups (`workspace` · `analytics` · `you`)
- Page titles / breadcrumbs

Add a screen by appending one entry there and one lazy import in `V3Router.jsx`.

`ResponsiveLayout.jsx` reads `useBreakpoint()`:

- `< 768px` → `MobileShell` (BottomNav, sticky composer slot)
- `768–1023px` → `DesktopShell` with collapsed sidebar (icon rail)
- `≥ 1024px` → `DesktopShell` full

## 6 · Adapter pattern (zero backend change)

V3 screens never call APIs directly. They consume **adapter hooks** in [`v3/adapters/`](../frontend/src/v3/adapters/). Each hook returns a stable view-model:

```js
const { data, loading, error, refetch } = usePortfolioSummary();
```

### Live wiring (current)

Adapters now hit the same backend endpoints V2 uses, through a shared
[apiClient](../frontend/src/v3/adapters/apiClient.js):

| Adapter hook | Endpoints called | Maps to |
|---|---|---|
| `usePortfolioSummary` | `GET /api/portfolio/analytics`<br>`GET /api/portfolio/holdings-enriched`<br>`GET /api/insights/v3-portfolio`<br>`GET /api/intelligence/portfolio`<br>`GET /api/user/profile`<br>`POST /api/copilot/widgets/portfolio_var`<br>`POST /api/copilot/widgets/tax_harvest` | `summary` · `allocation` · `topHoldings` · `funds` · `risk` · `tax` · `user` (name from profile) |
| `useUserProfile` | `GET /api/user/profile` | `name` · `email` · `riskProfile` · `journeyType` · `features` |
| `useStressTest(scenario)` | `POST /api/copilot/widgets/stress_test` | `dropPct` · `portfolioImpact` · `recoveryMonths` · `breakdown` |
| `useMarketBrief` | `POST /api/copilot/widgets/market_brief` | `nifty` · `sensex` · `sectors` · `flows` · `narrative` |
| `useRiskSuitability` | `POST /api/copilot/widgets/risk_suitability` | `equityActual/Target` · `debtActual/Target` · `suggestions` |
| `useFundOverlap(schemeCodes?)` | `POST /api/copilot/widgets/overlap_reveal` | `funds` · `matrix[][]` · `maxPct` · `pairs` |
| `useSuggestedPrompts(personaId)` | `GET /api/copilot/suggested-prompts?persona=…` | `{ primary, secondary, advanced }` — merged with local catalog |
| `askCopilot({ question, history, model })` | `POST /api/copilot/ask` | `{ ok, text, chartCount, mode }` — used directly by Chat screen |
| `uploadPortfolioFile(file)` + `pollUploadStatus(taskId)` | `POST /api/portfolio/upload`, `GET /api/portfolio/upload-status/{id}` | `{ ok, holdings, count }` — used by Onboarding's CAS upload path |

Each adapter:

1. Returns a **placeholder view-model on mount** (`{ initialData }` on `useAsync`) so screens never flicker through null.
2. Fires the real backend calls in parallel via `apiClient` (`withCredentials: true`).
3. Merges live response into the same view-model shape (key for key).
4. Sets `_source: "live"` on success, `"placeholder"` on error, so screens render a `SourceBanner` if any.
5. Exposes a `refetch` callback wired to the banner's Retry button.

Auth failures (401) and total backend outage degrade to the placeholder — never a crash, never a white screen.

`adapters/personas.js` + `adapters/promptCatalog.js` are derived directly from [docs/COPILOT_PROMPT_CATALOG.md](./COPILOT_PROMPT_CATALOG.md) — keep them in sync.

### Adding a new adapter

```js
// v3/adapters/myThing.js
import { apiGet } from "./apiClient";
import { useAsync } from "../hooks/useAsync";

export function useMyThing(arg) {
  return useAsync(
    async () => {
      const { data, error } = await apiGet("/my/endpoint", { arg });
      if (error || !data) return { data: null, error };
      return { data: { /* shape that screens expect */ }, error: null };
    },
    [arg],
    { initialData: /* placeholder */ }
  );
}
```

Then export from `adapters/index.js`.

## 7 · Mobile vs Desktop strategy (spec §3)

Spec §3 mandates **two distinct layouts, not scaling**. Concretely:

- Mobile: vertical card stack, sticky composer at the bottom that becomes part of the BottomNav-aware shell, 1-col (`compact-grid`) or 2-col compacts, full-bleed gutters of 20px.
- Desktop: 240px sidebar + 1200px main, hero is 2-col, compacts are 3-col. Composer is sticky at the column bottom.
- Tablet: same `DesktopShell` but with `collapsedSidebar = true` (72px icon rail).

Screens write themselves once using `viewport` from `useOutletContext()` and adjust three things only: grid columns, hero layout prop, font size of headers. The primitives carry all the rest.

## 8 · Personas (spec §5 + docs/COPILOT_PROMPT_CATALOG.md)

11 personas (10 + `universal`) are defined in `adapters/personas.js`. Selection persists to `localStorage` under `v3.persona`. Each persona maps to:

- Avatar icon (`adapters/personas.js`)
- Accent color (saffron / indigo / moss / gold / crimson)
- Tagline with highlight span
- Primary hero question + category
- Full prompt catalog (`adapters/promptCatalog.js`) → drives Home, Chat suggestions

Switching is a one-tap action from `PersonaStrip` (anywhere it's shown) → Profile screen → grid picker.

## 9 · How to add a Figma SVG asset

The architecture is asset-agnostic. To wire in a Figma export:

1. Drop the SVG into `v3/assets/illustrations/your-asset.svg`.
2. Import in a screen: `import bgArt from "../../assets/illustrations/your-asset.svg";`
3. Use as `<img src={bgArt} />` or as a CSS `background-image` inside the screen container.

No component code needs changing. The same applies for custom persona avatars: replace the Lucide icons in `PersonaAvatar.jsx` with `<img>` tags pointing at `assets/avatars/{id}.svg`.

## 10 · Performance & a11y

- Every screen is `React.lazy` — V3 only loads when the user opens `/v3/*`.
- Skeleton during Suspense uses tokens directly so it doesn't flash white.
- All interactive elements are real `<button>` with `aria-label`; pickers use `role="dialog"` + `aria-modal`.
- Focus rings: 2px saffron outline at 2px offset (spec).
- `prefers-reduced-motion` respected — animation duration drops to ~0ms.
- Mono fonts are bound to numerals/eyebrows only; screen readers consume the sans body text without letter-spacing noise.
- Bundle size — V3 is code-split: each screen is its own chunk; the initial `/v3` entry only loads home + shared primitives.

## 11 · Verifying V2 is unaffected

After any V3 change, run:

```bash
cd frontend && yarn build
```

If `src/v3/**` or `src/App.js` introduces new warnings/errors, they will surface specifically and tagged. Pre-existing V2 lint warnings (e.g. `useEffect deps` in `ActionablePortfolioView.js`) are unrelated and pre-date V3.

For a runtime smoke check:

1. `/v2/dashboard`, `/v2/chat`, `/v2/app`, `/v2/nidp` — all V2 routes render unchanged.
2. `/v2/v3` — redirects to `/v2/v3/home` and renders Copilot home.
3. Resize 390 → 1024 — shell flips cleanly, composer remains accessible.
4. Switch persona in Profile → home re-renders with new hero question and prompts.

## 12 · Where the Figma spec maps to code

| Spec section | Lives at |
|---|---|
| §1 Tokens | [v3/theme/tokens.css](../frontend/src/v3/theme/tokens.css) |
| §2.1 PersonaStrip | [v3/components/PersonaStrip.jsx](../frontend/src/v3/components/PersonaStrip.jsx) |
| §2.2 CategoryChip | [v3/components/CategoryChip.jsx](../frontend/src/v3/components/CategoryChip.jsx) |
| §2.3 HeroCard | [v3/components/HeroCard.jsx](../frontend/src/v3/components/HeroCard.jsx) + [v3/components/HeroVizPanel.jsx](../frontend/src/v3/components/HeroVizPanel.jsx) |
| §2.4 CompactCard | [v3/components/CompactCard.jsx](../frontend/src/v3/components/CompactCard.jsx) |
| §2.5 TinyChip | [v3/components/TinyChip.jsx](../frontend/src/v3/components/TinyChip.jsx) + [v3/components/MoreQuestions.jsx](../frontend/src/v3/components/MoreQuestions.jsx) |
| §2.6 Composer | [v3/components/Composer.jsx](../frontend/src/v3/components/Composer.jsx) |
| §2.7 Pickers | [v3/components/pickers/](../frontend/src/v3/components/pickers/) |
| §3 Layout grids | [v3/components/layout/](../frontend/src/v3/components/layout/) |
| §4 Component states | implemented inline as `:hover` / `aria-pressed` |
| §5 Persona variations | [v3/adapters/personas.js](../frontend/src/v3/adapters/personas.js) + [v3/adapters/promptCatalog.js](../frontend/src/v3/adapters/promptCatalog.js) |
| §6 Aesthetic guardrails | [v3/theme/tokens.css](../frontend/src/v3/theme/tokens.css) + [v3/components/BrandMark.jsx](../frontend/src/v3/components/BrandMark.jsx) |

## 13 · What's next (post-foundation)

The foundation is production-ready. Subsequent passes will:

1. Wire each adapter to the real existing endpoint (`@/api/strategyBuilder.js`).
2. Replace Lucide persona avatars with Figma-exported SVGs once delivered.
3. Add E2E smoke (Playwright) — one path per screen + one persona switch.
4. Add a feature-flag in `index.js` to enable V3 from V2 user prefs.
5. Push tablet polish (currently inherits desktop with collapsed sidebar).

No architectural changes required for any of the above.
