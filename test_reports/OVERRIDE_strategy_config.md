# OVERRIDE — Strategy config (table + endpoints + Bot details screen)

- **Branch:** feat/strategy-config @ commit `9143e0b7`, pushed. PR **#279** open against `dev`.
- **Date:** 2026-10-21
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Companion report:** `test_reports/strategy_config_20261021.md` — every command and its real output.

REASON: One gate requirement is still genuinely unmet — exercising the endpoints against the
**deployed** staging API — and it is blocked by two things outside this session, one of them a
permission denial I will not route around. Everything else now passes and is recorded.

1. **The endpoints are not on staging, because the branch is not merged or deployed.**
   PR #279 is open and `mergeable: True clean`, but the merge API call was **denied by the Claude Code
   permission classifier** (writes to `dev`). `origin/dev` is still `eb8add52`. I did not attempt a
   workaround — no direct push to `dev`, no alternative transport. The user must merge (one click on
   the PR) or add a permission rule.
   Then `/opt/nivesh-staging/repo` needs a pull + container rebuild before any route exists to curl.
   Proof the route is still absent: `GET /api/strategy-builder/config-schema` → **404**, while the
   existing `GET /api/strategy-builder/templates` → **401** (healthy server, route simply not there).

2. **A staging `session_token` is still needed.** `GET`/`PUT /strategies/{id}/config` both call
   `get_current_user`, so even after the deploy, every call without a cookie is a 401. ASKED THE USER
   EXPLICITLY on four consecutive turns. Never fabricated, never stubbed.

WHAT IS NOW DONE AND PROVEN (all pinned by identical file hashes before and after each run):
- **501 backend tests pass** — `test_strategy_config.py` plus every `ai_trader` suite, in a throwaway
  container from the staging image, code mounted read-only, `--network none`.
- **9 Playwright cases pass** (29.3s) — route-mocked, offline, no token. Includes two cases the fix
  round added for defects it closed: a failed config save abandons the run, and Save with an invalid
  field warns and writes nothing.
- **`tsc --noEmit` clean.**
- **Migration verified then applied to the staging DB** (user authorised it this turn): applies on a
  fresh DB, idempotent on re-apply, FK cascades, all four CHECK bounds reject correctly, `search_path`
  left at its default, and the structure read back from staging itself. 0 rows written; `strategies`
  untouched at 4 rows.
- **14 reviewer-found defects fixed**, several reproduced against a real postgres first — including a
  500-instead-of-422 on `initial_capital: 0.004` (NUMERIC scale), a SMALLINT overflow on
  `pyramiding: 40000`, Pydantic coercing `true` and `"3"` past `validate()`, a `search_path` leak onto
  the pooled connection, a toast that claimed "last saved config" while running the unsaved value, and
  an existing Playwright spec silently broken by the six-step renumbering.

CORRECTIONS MADE THIS SESSION, recorded so the history is not read as cleaner than it was:
- A `tsc` PASS was **retracted**: the file changed during the run (`d21bd986` → `25b9edab`). Every run
  since carries before/after hashes, and one later run was discarded for the same reason.
- An earlier "7 passed" Playwright result was reported with the caveat that the reviewer had shown
  three of its assertions would also pass against a broken screen; those three were strengthened.
- A regression I introduced in a **pre-existing** test (`test_ai_trader_config_risk.py:292`, stale
  expected message after pyramiding gained an upper bound) was found by running the full suite rather
  than only the new one, and fixed.

NOT CLAIMED: that this is deployed, merged, or verified against the live staging API. It is committed,
pushed, and open as PR #279, with the migration applied to the staging database and nothing else on
staging touched.
