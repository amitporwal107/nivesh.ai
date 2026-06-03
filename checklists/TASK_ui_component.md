# Checklist — TASK: UI Component

**Use when:** building/changing a React component or screen.
**Target env:** ☐ Staging   ☐ Prod *(V2 only)*
**Status:** `NOT STARTED` → `IN PROGRESS` → `DONE` | `🔴 BLOCKED`
**Roles:** DESIGN_ENGINEER (+ FULL_STACK_DEV for data)  ·  Surfaces: V2 (prod, CRA), V5 (staging, Vite)

## 0. INTAKE
- [ ] Restated the component + which surface (V2/V5).
- [ ] Loaded `.claude/roles/DESIGN_ENGINEER.md`.
- [ ] Read design tokens / neighboring components — did not guess.
- [ ] Design intent / data shape unclear → `NEEDS-INPUT`, not assumed.

## 1. PRE-FLIGHT
- [ ] Breakpoints + data source confirmed; will reuse Tailwind tokens + Radix.
- [ ] On `dev`/`feat/*`.

## 2. EXECUTE
- [ ] Built with system primitives; handled loading / empty / error / long-text / overflow.
- [ ] A11y: keyboard, visible focus, contrast, labels, semantic markup.
- [ ] Wired to real data (no unlabeled mock) — or mock clearly labeled `// MOCK`.

## 3. VERIFY — STAGING (V5 `/v5/` or V2 `/v2/`)
- [ ] `yarn build` clean — shown.
- [ ] **Rendered** on staging — confirmed visually (screenshot/app) — shown.
- [ ] All real states exercised with real staging data — shown.
- [ ] Responsive + a11y verified.

## 4. VERIFY — PROD (niveshcopilot.com/v2/ — V2 only)
- [ ] Verified on staging first; targets V2 (V5 not in prod yet → else `NEEDS-INPUT`).
- [ ] Rendered on prod post-deploy — confirmed visually, shown.
- [ ] No new frontend errors in Grafana Sentry panel — checked.

## DONE-GATE
- [ ] Component rendered AND confirmed visually on the target env (not "should look").
- [ ] States real, no unlabeled mock; no claim beyond evidence.
- [ ] All true → **DONE**; else → **IN PROGRESS**.
- [ ] Blocked → `🔴 REAL BLOCKER:` what / why / needed.
