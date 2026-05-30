# Checklist — SKILL: Design Engineer

**Use when:** any user-facing UI / component / styling / accessibility change.
**Target env:** ☐ Staging   ☐ Prod *(prod = V2 only)*
**Status:** `NOT STARTED` → `IN PROGRESS` → `DONE` | `🔴 BLOCKED`

## 0. INTAKE
- [ ] Restated the task; which surface (V2 prod / V5 staging-only) confirmed.
- [ ] Loaded `.claude/roles/DESIGN_ENGINEER.md`.
- [ ] Read canonical `docs/` / design tokens — did not guess.
- [ ] Design intent unclear → asked PRODUCT (`NEEDS-INPUT`), not assumed.

## 1. PRE-FLIGHT
- [ ] Confirmed breakpoints + design source (tokens / Radix / mock).
- [ ] Will reuse existing tokens/components; any new primitive justified in one line.

## 2. EXECUTE
- [ ] Built with system primitives; handled loading / empty / error / long-text / overflow states.
- [ ] Accessibility: keyboard reachable, visible focus, contrast, labels, semantics.

## 3. VERIFY — STAGING  (staging.niveshcopilot.com — V5 `/v5/`, V2 `/v2/`)
- [ ] `yarn build` clean — shown.
- [ ] Component **rendered** on staging — confirmed visually (screenshot/running app) — shown.
- [ ] Real states exercised with real staging data (not mock).
- [ ] Responsive at real breakpoints; a11y checks done.
- [ ] No placeholder content left (unless explicitly labeled).

## 4. VERIFY — PROD  (niveshcopilot.com — V2 only)
- [ ] Verified on staging first (evidence linked).
- [ ] Targets V2 (V5 does NOT go to prod yet — else `NEEDS-INPUT`).
- [ ] Rendered on `https://niveshcopilot.com/v2/` post-deploy — confirmed visually, shown.
- [ ] No new frontend errors in Grafana Sentry panel — checked.

## DONE-GATE
- [ ] Every box for the target env green AND evidence shown (render confirmed, not "should look").
- [ ] No unlabeled mock content; no claim beyond evidence.
- [ ] All true → **DONE**; else → **IN PROGRESS**.
- [ ] Blocked → `🔴 REAL BLOCKER:` what / why / needed. No workaround or guess.
