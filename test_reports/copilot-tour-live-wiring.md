# Functionality Verification — Copilot tour "make the demo live"

**Change:** Turn the static `/v5/copilot` marketing tour into a live front door to the
real copilot. Every mockup control (Ask composers, quick chips, workflow cards, advisor
cards, in-flow action buttons) now routes into the real copilot at `/chat`, carrying the
question as a `?q=` deep-link — which the chat page auto-sends. Signed-in visitors get a
real answer on their own portfolio; logged-out visitors are funneled through `/login` by
the existing `RequireAuth` guard. Also fixes the ~28px mobile horizontal-overflow.
No new backend.

**Area:** frontend `frontend-v5/src` (product code) → verified with Playwright.

**Files changed**
- `src/pages/Copilot/useEnterCopilot.ts` (new) — shared `useEnterCopilot()` / `useAskProps()` / `askText()`.
- `src/pages/Copilot/sections/AdvisoryFlow.tsx` — real `Composer` input, clickable `Chip`, `CtaBtn` for in-flow actions + shell CTAs.
- `src/pages/Copilot/sections/Workflows.tsx` — cards open `?q=<prompt>`.
- `src/pages/Copilot/sections/Advisor.tsx` — workflow cards + "who to call first" rows open `?q=`.
- `src/pages/Copilot/sections/AllFlows.tsx` — delegated open on `.ct-pb`/`.ct-pbtn`/`.ct-chip`.
- `src/pages/Copilot/sections/Mobile.tsx` — real composers, clickable chips, live `ct-mbtn` CTAs.
- `src/pages/Copilot/copilot.css` — `.ct-ask-input` styling, pointer on interactive classes, `overflow-x: clip` on the tour root (mobile overflow fix).
- `pw.copilot.config.ts` — `baseURL` now honors `PW_BASE_URL` env (test harness only).
- `e2e/tests/copilot-live.spec.ts` (new) — the test cases below.

## Test cases (authored before implementation)

| # | Case | Expected |
|---|------|----------|
| 1 | Tour still renders | hero + sticky sub-nav visible (no regression) |
| 2 | Desktop Ask composer (real input) | type + send → `/chat?q=<typed>` |
| 3 | Intake quick-chip "Grow wealth" | `/chat?q=Grow wealth` (tick stripped) |
| 4 | Investor workflow card | `/chat?q=What's the one thing I should fix first?` |
| 5 | Advisor workflow card | `/chat?q=How's my book doing this quarter?` |
| 6 | All-flows ASK bubble | `/chat?q=What's the one thing I should fix first?` |
| 7 | Mobile Ask composer | type + Enter → `/chat?q=<typed>` |
| 8 | Mobile primary CTA "Review & apply" | opens `/chat` (q="Review and apply my top 3 actions") |
| 9 | Mobile horizontal overflow | `scrollWidth - clientWidth ≤ 2px` |

**Auth model verified:** logged-out visitor → click a control → SPA navigates to
`/chat?q=...` → `RequireAuth` (401) redirects to `/login`. History instrumentation
captured the transient `/chat?q=...` target, e.g.:
`["/v5/copilot","/v5/chat?q=What%27s%20the%20one%20thing%20I%20should%20fix%20first%3F","/v5/login"]`.

## How run (real commands)

Build (base `/v5/` to match staging) + serve + drive with Playwright against the
production build:

```
$ npx tsc --noEmit            # EXIT 0 (typecheck)
$ VITE_BASE=/v5/ npx vite build   # ✓ built in 48.98s  (EXIT 0)
$ VITE_BASE=/v5/ npx vite preview --port 5191 --strictPort
$ PW_BASE_URL=http://localhost:5191 npx playwright test e2e/tests/copilot-live.spec.ts --config pw.copilot.config.ts
```

## Real output — new live-wiring suite

```
Running 9 tests using 1 worker

  ✓  1 › 1 · tour still renders (hero + sub-nav) (2.0s)
  ✓  2 › 2 · desktop composer routes typed question into /chat (2.4s)
  ✓  3 › 3 · intake quick-chip opens copilot with the chip text (2.1s)
  ✓  4 › 4 · investor workflow card opens copilot with its prompt (1.9s)
  ✓  5 › 5 · advisor workflow card opens copilot with its prompt (2.2s)
  ✓  6 › 6 · all-flows ASK bubble opens copilot with its question (2.1s)
  ✓  7 › 8 · mobile primary CTA enters the real copilot (2.2s)
  ✓  8 › 9 · mobile viewport has no horizontal body overflow (2.1s)
  ✓  9 › 7 · mobile composer routes typed question into /chat (2.3s)

  9 passed (23.1s)
```

## Real output — regression: existing tour spec (unchanged)

```
$ PW_BASE_URL=http://localhost:5191 npx playwright test e2e/tests/copilot-tour-unauth.spec.ts --config pw.copilot.config.ts

  ✓  1 › renders hero headline (2.1s)
  ✓  2 › renders the sticky section sub-nav with every section (4.7s)
  ✓  3 › all 8 section anchors exist in the DOM (1.3s)
  ✓  4 › overview: pipeline + two audiences (1.6s)
  ✓  5 › design principles are listed (1.8s)
  ✓  6 › advisory flow shows the six stages (1.7s)
  ✓  7 › workflow library shows the 10 workflows (2.7s)
  ✓  8 › all-flows filmstrip renders Ask→Analyze→Decide→Act (2.7s)
  ✓  9 › advisor book shows AUM + who-to-call table (2.9s)
  ✓ 10 › mobile rail renders phone frames (2.8s)
  ✓ 11 › tour is forced dark (3.0s)
  ✓ 12 › Homepage → Copilot tour link navigates to /copilot (3.7s)

  12 passed (34.2s)
```

## Visual check

Post-change desktop (Screens) and mobile (390px) screenshots compared against the
pre-change design: pixel-identical layout — the Ask composers now render as real inputs
with the same styling, all buttons/chips/cards unchanged, dark palette intact.

## Notes / limits

- **UNVERIFIED (by design):** the real end-to-end answer from `/api/copilot/ask` on a
  signed-in user's live portfolio was not exercised here — that path is auth-gated and
  needs a real session token. This change only wires the tour *into* that existing,
  already-shipped endpoint; the `?q=` deep-link + auto-send mechanism (`pages/Chat`) is
  pre-existing and unchanged. On staging, a signed-in user clicking a control will land
  in `/chat` with the question auto-sent.
- Tests run against a **production build** served by `vite preview` (base `/v5/`), the
  same surface that deploys to staging.

## Verdict: PASS
