# Functionality Verification Report — Strategy config (table + endpoints + Bot details screen)

- **Branch:** feat/strategy-config (worktree, off origin/dev @ eb8add52)
- **Date:** 2026-10-21
- **Author:** Claude (FULL_STACK_DEVELOPER + DESIGN_ENGINEER + QA_ENGINEER)
- **Environment:** staging DB read-only (portfolio_ingestion @ 127.0.0.1:5532); migration applied to a THROWAWAY postgres, not staging
- **Changed areas:** backend routes/services: YES · frontend src: YES

## Summary

Builds the three fully-specified pieces of `docs/STRATEGY_BUILDER_CONFIG_SPEC.md` that had no
implementation: the persistence table, the config endpoints, and screen 1 ("Bot details") from the
mockup. `NiveshConfig` (backend/services/ai_trader/config.py) already existed and stays the single
source of truth for ranges — the endpoints and the served JSON Schema both derive from its constants,
so frontend and backend cannot drift (spec §4.4, test-checklist item 9).

Two deviations from the spec, both recorded in the design notes below:
1. The spec says `bot_config(bot_id uuid PK→bots)`. **There is no `bots` table.** The owning row is
   `public.strategies` (created by backend/nidp/migrations/020_strategy_builder_core.sql, present in
   the app DB `portfolio_ingestion`). Table is therefore `strategy_config(strategy_id → strategies)`.
2. The spec's paths are `/bots/{id}/config`. Real resource paths are
   `/api/strategy-builder/strategies/{id}/config`, matching the six existing `/strategies/{id}/…` routes.

Out of scope here (named so it is not mistaken for done): screen 2 (Code editor), screen 3 (Backtests
tab + drift panel), and engine enforcement of `pyramiding` / `short_margin_pct` — the backtester is
long-only and counts no same-direction entries, so `PYRAMIDING_LIMIT`, `SHORT_MARGIN_DEPLETED` and
`INSUFFICIENT_CAPITAL` remain unreachable. This change does NOT make those fields effective; it
stores them. `initial_capital` and `commission_pct` DO take effect (wired into the backtest call).

## Test Cases
> Authored UP FRONT — after API + UI design, before implementation.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | Migration | `024_strategy_config.sql` applies on an empty DB with `strategies` present | api (sql) | table + FK + index created, no error | |
| TC-2 | Migration | Re-applying the same file is a no-op (forward-only, `IF NOT EXISTS`) | edge | second run succeeds, no error | |
| TC-3 | Migration | Deleting a strategy cascades its config row away | edge | 0 rows left | |
| TC-4 | Migration | Column types/ranges match the spec §4.3 (numeric precisions, smallint) | unit | as specified | |
| TC-5 | Schema | `GET /config-schema` ranges equal `config.py`'s own constants | unit | derived, not duplicated | |
| TC-6 | GET | No stored row → returns AI_DEFAULTS with `stored: false` | api | 200, defaults | |
| TC-7 | GET | Stored row → returns stored values with `stored: true` | api | 200, stored | |
| TC-8 | GET | Unknown strategy id → 404 | failure | 404 | |
| TC-9 | GET | Another user's non-template strategy → 403 | failure | 403 | |
| TC-10 | GET | No auth → 401 | failure | 401 | |
| TC-11 | PUT | Valid body persists and the response echoes the stored row | api | 200, row in DB | |
| TC-12 | PUT | Second PUT updates in place (upsert, one row per strategy) | api | 1 row, new values | |
| TC-13 | PUT | `initial_capital = 0` / negative / > 1e10 → 422 naming the field | failure | 422 | |
| TC-14 | PUT | `commission_pct` = 5.0 accepted; 5.01 → 422 | edge | boundary holds | |
| TC-15 | PUT | `short_margin_pct` = 0 → 422; 100 accepted | edge | boundary holds | |
| TC-16 | PUT | `pyramiding` = -1 → 422; `true` (bool) → 422; 0 accepted | edge | bool rejected as non-int | |
| TC-17 | PUT | Unknown field in body → 422 `unknown_ui_config_field`, nothing stored | failure | refused, not dropped | |
| TC-18 | PUT | Non-owner → 403 even if the strategy is a public template | failure | 403 | |
| TC-19 | PUT | Writes one `strategy_audit` row with action `CONFIG_UPDATE` | api | 1 audit row | |
| TC-20 | Backtest | Body omits `starting_capital` → stored config's value is used | api | engine gets stored value | |
| TC-21 | Backtest | Body supplies `starting_capital` → body wins (back-compat) | api | engine gets body value | |
| TC-22 | Backtest | `commission_pct` 0.05 reaches the engine as `slippage_pct` 0.0005 | unit | /100 conversion | |
| TC-23 | Backtest | No stored config → AI_DEFAULTS used, run still succeeds | edge | 1,000,000 | |
| TC-24 | UI | Bot details step renders the four fields + symbol chips | e2e | visible | |
| TC-25 | UI | Invalid capital shows the spec §8b.2 message and disables Run backtest | e2e | disabled + message | |
| TC-26 | UI | Pyramiding stepper shows "N+1 allowed · next rejected" and floors at 0 | e2e | copy + floor | |
| TC-27 | UI | Resolved-config panel Fields/JSON toggle, source pill per field | e2e | both views | |
| TC-28 | UI | Saving with a strategy id PUTs; without an id holds local state only | e2e | no stray request | |
| TC-29 | UI | Help text recomputes as the user types (§8b.3 wording) | e2e | live | |
| TC-30 | Typecheck | `tsc --noEmit` clean | unit | 0 errors | |
| TC-31 | UI | Config PUT fails before a run → the run is abandoned, not started with a half-applied config | e2e | no POST /backtest, error toast | |
| TC-32 | UI | Save step with an invalid Bot-details field → warns, saves nothing, claims no success | e2e | warn toast, no PUT | |
| TC-33 | UI | Bot-details error count rides on the stepper tab, visible from another step (§8b.2) | e2e | badge persists | |
| TC-34 | UI | Form opens at the FETCHED schema's default, not the offline fallback copy | e2e | 500000 fixture | |
| TC-35 | UI | Resolved panel + its JSON mark `not_enforced_by_engine` keys as stored only | e2e | marker in both views | |

## API / Endpoint Tests (staging)
<!-- filled after implementation -->

## UI / Playwright Tests
<!-- filled after implementation -->

## Data Correctness
<!-- filled after implementation -->

## Verdict
<!-- pending -->
