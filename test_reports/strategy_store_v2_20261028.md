# Functionality Verification Report — Strategy Copilot Phase 1.1: the shared strategy store, v2

- **Branch:** feat/strategy-store-v2 (from dev be93f885), worktree /home/deploy/nivesh-strategy-copilot
- **Date:** 2026-10-28
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** unit + route tests in the staging backend image (`--network none`), DB-backed route tests against a throwaway `postgres:16-alpine` (same major as staging, 16.15); staging after merge
- **Changed areas:** backend routes/services: yes · frontend src: no

## Summary
The Strategy Lab wizard on `dev` (#393) already calls the v2 store routes of
`docs/strategy_copilot_review_20261028/PROPOSAL_strategy_store_v2.md` §4. Those routes do not exist yet, so the wizard keeps
Save version and Clone disabled ("Saving arrives with the shared strategy store"). This PR builds them in the existing
`/api/strategy-builder` module:
- one additive, re-runnable migration (`backend/migrations/026_strategy_store_v2.sql`);
- the v2 document validator (`services/strategy_store.py`), with the shape taken from what the wizard really sends
  (`instance-store.ts` `definitionOf`), not from the earlier proposal text;
- create / new version / clone / list-with-summary / list versions / read one version;
- an optional `strategy_ref` on the desk paper-trade POST, so a stored strategy can show PAPER LIVE.

Design rules:
- **v1 answers do not change.** v1 requests, including invalid ones, get the same answers as before.
- **Old screens see no new rows.** The legacy list returns only STOCK/MF.
- **Nothing new is ever backtested by the old engine.**
- **The code runs before and after the migration.** Before it, v2 routes answer 503 `store_not_migrated`.

Owner question Q4 is taken as recommended: unlimited-loss structures save as drafts with `blocking_for: ["backtest","paper"]`.

## Test Cases
> Authored UP FRONT (2026-10-28, before implementation). Files:
> - P = `tests/test_strategy_store_v2_model.py`: pure, runs in CI.
> - R = `tests/test_strategy_store_v2_routes.py`: real Postgres; skipped without `STRATEGY_STORE_TEST_PG`.
> - V = `tests/test_strategy_store_v1_parity.py`: CI.
> - D = `tests/test_desk_paper_trade_strategy_ref.py`: CI.
> - M = migration run by hand.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | P | The wizard's `definitionOf` output (NIFTY bull call spread, 2 option legs) validates | unit | no problems; stored as sent |PASS |
| TC-2 | P | Wizard cash leg (`shares`, lot size 1, no expiry/strike) and future leg (expiry, no strike) validate | unit | no problems |PASS |
| TC-3 | P | 5 legs | unit | problem `{field: "legs", code: "too_many_legs"}`; the limit is `MAX_STRATEGY_LEGS` |PASS |
| TC-4 | P | Unknown field at top level, in a leg, in `build_constraints` | unit | `unknown_field` with that field's path; never dropped |PASS |
| TC-5 | P | `build_constraints` over 4 KB of JSON | unit | `build_constraints_too_large` |PASS |
| TC-6 | P | Leg rules: lots vs shares by instrument, expiry required for CALL/PUT/FUTURE and absent for STOCK, strike only for CALL/PUT, entry price > 0, duplicate leg_id, `same_as` to a missing leg | unit | one problem each, with its field |PASS |
| TC-7 | P | Rule-based legs (Copilot form): `nearest_monthly` expiry, `atm_offset_points` strike | unit | valid |PASS |
| TC-8 | P | `template_id` not in the desk catalog; bad underlying symbol | unit | `invalid_template`, `invalid_underlying` |PASS |
| TC-9 | P | Checks (D2): naked short call, short straddle, short future only, mixed option expiries | unit | `blocking`, `blocking_for: ["backtest","paper"]` |PASS |
| TC-10 | P | Checks: bull call spread (none blocking), long future (warning `futures_exposure`), all-cash (info) | unit | as stated |PASS |
| TC-11 | P | Asset class derived from legs: options only → FNO, cash + option → MIXED, cash only → STOCK | unit | as stated |PASS |
| TC-12 | P | Diff: changed strike, added leg, removed leg, name change | unit | `[{path, before, after}]` with `legs[L1].strike.value`-style paths, deterministic order |PASS |
| TC-13 | V | Invalid v1 create bodies (missing name, `asset_class: "FNO"` on a v1 doc, a list body, an empty body) | api | 422 byte-identical to the pre-change route |PASS |
| TC-14 | R | v2 create | api | 201 `{strategy_id, version_id, version_no: 1, schema_version: "2", asset_class, checks}`; DB row has `source`, `template_id`, `underlying` |PASS |
| TC-15 | R | Same Idempotency-Key, same body → same ids, `replayed: true`, one row; same key, other body | api | 200 replay; 409 `idempotency_conflict` |PASS |
| TC-16 | R | New version: diff returned, version_no 2, parent set, previous inactive | api | 201 |PASS |
| TC-17 | R | Stale parent (two tabs) | api | 409 `stale_parent` with the active version id |PASS |
| TC-18 | R | Version with no change; a v2 version on a v1 strategy | api | 422 `no_change`; 422 `schema_mismatch` |PASS |
| TC-19 | R | Caps (200 strategies / 50 versions; the test lowers them) | api | 409 `strategy_limit` / `version_limit` |PASS |
| TC-20 | R | Trigger: `UPDATE strategy_versions SET definition = …` | data | refused by the database; `is_active` updates still work (v1 PATCH path) |PASS |
| TC-21 | R | Not owned → 404 on versions, list versions, one version, clone (private) | api | 404, never 403 |PASS |
| TC-22 | R | Clone own strategy and a public template (as another user) | api | 201; caller owns the clone; `source: "clone"`, `cloned_from` set; definition name changed |PASS |
| TC-23 | R | Unlimited-loss draft (naked short call) | api | saved 201 with `checks[].blocking_for` containing backtest and paper |PASS |
| TC-24 | R | `GET /strategies?include=summary`: DRAFT (no run), current OK run (BACKTESTED inputs), OK run on an older version (STALE inputs), FAILED latest, PAPER LIVE count | api | the fields the wizard's `storeStatus` needs, per row |PASS |
| TC-25 | R | Legacy `GET /strategies` (no include) with a v2 row present | api | v1 rows only, same keys as before |PASS |
| TC-26 | R | PATCH a v2 strategy; backtest a v2 strategy | api | 422 `use_versions_route`; 422 `backtest_not_available` and NO run row |PASS |
| TC-27 | R | v1 create → get → PATCH → list on the migrated DB | api | same keys and values as before the change |PASS |
| TC-28 | R | Before the migration: v1 create/list work; v2 create → 503 `store_not_migrated` | api | as stated |PASS |
| TC-29 | M | Migration applied twice; the 6 staging-shaped v1 rows still read | data | no error; one asset_class CHECK, one FK, one trigger |PASS |
| TC-30 | D | Paper trade with no `strategy_ref` | api | answer unchanged (no `strategy_ref` key) |PASS |
| TC-31 | D | `strategy_ref` malformed / unknown / not owned | api | 422 `invalid_strategy_ref`, field `strategy_ref`; nothing written |PASS |
| TC-32 | D | Valid `strategy_ref` | api | 201; trade stores and returns `{strategy_id, version_id, version_no}` |PASS |
| TC-33 | D | `POST /paper-trades/check` with `strategy_ref` | api | accepted; it changes no risk number |PASS |
| TC-34 | regression | Backend baseline suites + the new suites in the staging image | unit | same pass count as dev + new tests, 0 failures |PASS |
| TC-35 | staging | After merge + migration: create/version/clone/list on staging with a session; DB rows checked | api+data | as TC-14..24 |PENDING (needs merge + migration + session) |

## API / Endpoint Tests (staging)
**Not run yet (TC-35).** Staging runs `dev`. This branch is not merged, and a merge does not apply migration 026: it needs the
deploy workflow with `run_migrations=true`. The cross-user cases also need a second staging user. See
`test_reports/OVERRIDE_strategy_store_v2.md`.

## Tests run this session (real output, 2026-10-28, branch `feat/strategy-store-v2`)
Image `nivesh/backend:staging`, tree mounted read-only, `--network none`. The DB suite ran on an internal-only Docker
network with a throwaway `postgres:16-alpine` (PostgreSQL 16.15, the same major version as staging), removed afterwards.

- **Pure + v1 parity + desk `strategy_ref`:**
  `pytest tests/test_strategy_store_v2_model.py tests/test_strategy_store_v1_parity.py tests/test_desk_paper_trade_strategy_ref.py`
  → `79 passed, 2 warnings in 7.43s`. The roll case was added afterwards:
  `pytest tests/test_desk_paper_trade_strategy_ref.py tests/test_fno_roll.py` → `23 passed, 2 warnings in 7.74s`.
- **Real Postgres (TC-14…TC-29):** `STRATEGY_STORE_TEST_PG=… pytest tests/test_strategy_store_v2_routes.py -v` →
  `19 passed, 2 warnings in 9.41s`. All 19 cases PASSED by name, TC-14 through TC-29. Afterwards
  `select count(*) from pg_database where datname like 'ssv2_%'` → `0` (the fixture dropped its databases).
- **TC-13 found a real difference on the first run.** This FastAPI version keeps pydantic's `url` in 422 errors, and a
  list/string body is `model_attributes_type`, so the first implementation answered 22 refused v1 bodies differently.
  Fixed (`exc.errors()` and `from_attributes=True`); all 26 parity cases now pass.
- **TC-27 failed once because of a fault in the test fixture, not the product.** Two harnesses patched the same pool,
  causing an asyncpg cross-loop error. Fixed in the harness.
- **TC-34, regression: the whole CI allowlist, dev vs branch, same image:**
  - `dev` be93f885 (snapshot), 262 files → `3 failed, 6831 passed, 28 skipped, 15 warnings in 219.31s`;
  - branch, final tree, 265 files (+ the 3 new CI suites) → `3 failed, 6911 passed, 28 skipped, 15 warnings in 212.87s`.
  - The same 3 tests fail on both, so they predate this branch: `test_cas_api_client.py::test_sandbox_parse_and_map`,
    `::test_convenience_helper_returns_list`, `test_nidp_stamp_broadcast_at.py::test_run_commits_in_batches`.
  - +80 = 44 model + 26 parity + 10 desk. **No regression.**

## Data Correctness
- Staging today, read-only (2026-10-28):
  - 6 strategies (all STOCK), 6 versions, 4 runs;
  - constraint `strategies_asset_class_check` = `CHECK (asset_class = ANY (ARRAY['STOCK','MF']))`;
  - no triggers;
  - PostgreSQL 16.15.
- The migration was written against exactly that, and TC-29 reproduces the shape: 6 v1 rows seeded before 026, then 026
  applied twice. Result: one asset_class CHECK, one source CHECK, one parent FK, one trigger; the 6 rows read
  `source = 'user'`, `schema_version = '1'`, and GET answers them with the legacy keys.
- On staging after the migration (TC-35): **pending**.

## Inputs required from user
- Merge of the PR (per-PR approval).
- Running the migration on staging: the backend deploy workflow with `run_migrations=true`. Migrations are not applied by a merge.
- A session token for the staging checks (TC-35), and a second user for the cross-user cases.

## Verdict: BLOCKED
