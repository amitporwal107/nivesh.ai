# Functionality Verification Report — W2-LAYOUTS (saved chart layouts API)

- **Branch:** fix/charting-symbols-contract (worktree `charting`)
- **Date:** 2026-09-23
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** local pytest only (dummy `MONGO_URL`, no real Mongo) — staging needs a deploy + session token, see OVERRIDE
- **Changed areas:** backend routes/services: yes (new `backend/routes/research_chart_layouts.py` + 2 registration
  lines in `backend/server.py`) · frontend src: no

## Summary
Saved chart layouts CRUD (`GET|POST|PATCH|DELETE /api/research/chart-layouts[/{layout_id}]`), per docs/charting.md
§38.8 and §38.11, copying `backend/routes/research_drawings.py`'s patterns exactly: `require_feature("charting")`
allowlist gate, per-user Mongo scoping (`research_chart_layouts`, another user's row is 404 never 403), and the
`"<field>: <reason>"` / single-token error-shape convention. CSRF on the mutating verbs is the existing global
`middleware.CsrfProtectMiddleware` (origin check keyed on session cookie + method + `/api` prefix) — nothing
route-specific was needed for it, but it is exercised directly in the test file since no existing test in the repo
covers it. Test cases below were authored UP FRONT, before `backend/tests/test_research_chart_layouts.py` was written.

## Test Cases
> Authored UP FRONT — after API design (matching research_drawings.py), before implementation. One row per case.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-140 | Gate | GET/POST/PATCH/DELETE, account NOT on `charting` allowlist | api/failure | 403 `feature_not_enabled` on every verb; nothing stored | PASS |
| TC-141 | Create | `POST` with only `symbol` | api | 201; `layout_id` is a real UUID; `user_id` = caller; `created_at == updated_at`; `name == "Unnamed"` | PASS |
| TC-142 | List | `GET`, two layouts for A (different `created_at`) + one for B | api | A sees only A's 2, newest first; B sees only B's 1 | PASS |
| TC-143 | Rename | `PATCH {name}` | api | `name` changes; `updated_at` bumps; `symbol`/`chart_type`/etc unchanged | PASS |
| TC-144 | Round trip (AC9) | `POST` full payload (symbol, timeframe, chart_type, indicators, panes, visible_range, drawing_visibility, sidebar_state), then `PATCH` a subset | api/data | every field equals what was sent, asserted on the stored Mongo document, both after create and after patch | PASS |
| TC-145 | Delete | `DELETE` then `DELETE` again | api | first: 200 `{status: deleted, layout_id}`, row gone; second: 404 `not_found` | PASS |
| TC-146 | Ownership | user B `PATCH`/`DELETE` on user A's `layout_id`; unknown id from A | failure | both 404 `not_found`, identical body (no existence leak); A's row untouched; A can still PATCH/DELETE her own | PASS |
| TC-147 | CSRF | `POST`/`PATCH`/`DELETE` with `session_token` cookie + disallowed cross-origin `Origin`; then an allowed/no-`Origin` request | failure/api | disallowed → 403 `CSRF_BLOCKED`, nothing stored/changed; allowed/no-Origin → reaches the route (normal gate/validation result) | PASS |
| TC-148 | Validation | `POST` with 41 indicator instances (cap 40) | edge | 422, `too_long` reason on `indicators` | PASS |
| TC-149 | Validation | `POST` with `indicators` as a string instead of a list | edge | 422, `list_type` reason | PASS |
| TC-150 | Validation | `POST` with an unknown top-level field | edge | 422, `extra_forbidden` reason | PASS |
| TC-151 | Validation | `POST`/`PATCH` with `chart_type: "candlesticks"` (not in the catalogue) | edge | 422 `chart_type: must be one of [...]` | PASS |
| TC-152 | Validation | `PATCH {}` (no fields) | edge | 400 `no_fields_to_update` | PASS |

## API / Endpoint Tests (local, dummy Mongo)
> No real Mongo is started (host rule); `deps.db` is monkeypatched to an in-memory fake collection, and
> `feature_gate.require_feature`'s user resolver / flag store / clock are injected — the same pattern as
> `test_research_drawings.py` / `test_move_odds_routes.py`, so the gate, ownership and validation logic all run
> for real. CSRF is tested by mounting the real `middleware.CsrfProtectMiddleware` on the test app.

- **pytest:** `cd backend && MONGO_URL=mongodb://127.0.0.1:1 DB_NAME=test_charting /opt/nidp/venv/bin/python -m pytest tests/test_research_chart_layouts.py tests/test_research_chart.py tests/test_research_drawings.py tests/test_charting_feature_flag.py -q`
  - Output (real, 2026-09-23):
    ```
    .....................................................                    [100%]
    53 passed in 2.25s
    ```
    (15 in the new `test_research_chart_layouts.py`, 38 in the three pre-existing charting suites — all still green.)
  - Result: PASS
- Reason codes confirmed by direct inspection of the response bodies (not just presence of a 422):
  - too many indicator instances (41 > cap 40) → `{"type": "too_long", "loc": ["body","indicators"], "msg": "List should have at most 40 items after validation, not 41", "ctx": {"max_length": 40, "actual_length": 41}}`
  - `indicators` sent as a string → `{"type": "list_type", "loc": ["body","indicators"], "msg": "Input should be a valid list"}`
  - unknown top-level field → `{"type": "extra_forbidden", "loc": ["body","some_field_that_does_not_exist"], "msg": "Extra inputs are not permitted"}`
  - invalid `chart_type` → `"chart_type: must be one of ['candles', 'hollow_candles', 'bars', 'line', 'area', 'heikin_ashi']"`
- Router shape verified directly: `GET/POST /api/research/chart-layouts`, `PATCH/DELETE /api/research/chart-layouts/{layout_id}` — matches docs/charting.md §38.11 exactly.
- `backend/server.py` diff is exactly 2 added lines (1 import + 1 `include_router`, both next to the `research_drawings` lines) — verified with `git diff --stat backend/server.py` (`1 file changed, 2 insertions(+)`).
- `python -m py_compile server.py routes/research_chart_layouts.py tests/test_research_chart_layouts.py` → exit 0 (no syntax/import errors introduced).

## UI / Playwright Tests
Not applicable — no frontend files were touched by this package (layouts UI is owned by another concurrent
package). N/A.

## Data Correctness (staging)
Not run — no live database was touched (host rule: no real Mongo, no staging deploy from this package). See
`OVERRIDE_charting_w2_layouts.md`.

## Inputs required from user
- A staging session token, to run `POST/GET/PATCH/DELETE /api/research/chart-layouts` against the real staging
  Mongo after this lands in a deploy. Not requested this turn — see OVERRIDE.

## Verdict: PASS
