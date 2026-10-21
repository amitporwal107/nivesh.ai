# OVERRIDE — Strategy config (table + endpoints + Bot details screen)

- **Branch:** feat/strategy-config (worktree, off origin/dev @ eb8add52)
- **Date:** 2026-10-21
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Companion report:** `test_reports/strategy_config_20261021.md`

REASON: A defect-fix round is actively rewriting the implementation as this turn ends, so no
verification can be pinned to a stable tree; and two of the gate's requirements need something only
the user can give or authorise. Four blockers, stated precisely:

1. **The tree is mid-rewrite — verifying now would produce a false result.** An adversarial review
   found 14 located defects (7 backend, 7 frontend) and a fix round is in flight: at the moment this
   file was written, `backend/routes/strategy_builder.py` had been modified seconds earlier
   (20:59:33), `config.py` at 20:58:51, `024_strategy_config.sql` at 20:59:11,
   `StrategyBuilderPage.tsx` at 20:59:27, and neither fix agent had returned.
   This is not hypothetical: earlier this session a `tsc --noEmit` PASS had to be RETRACTED because
   the file changed during the run (`d21bd986` → `25b9edab`). Every verification run since is pinned
   with before/after content hashes for that reason. A waiter is armed on both agents returning plus
   60s of file quiescence; verification runs then, against a settled tree, in the next turn.

   The defects being fixed are real and were reproduced against a live postgres and a real run of
   the suite — they are not style notes. The most serious:
   - `{"initial_capital": 0.004}` passes `NiveshConfig.validate()`, is rounded to `0.00` by
     `NUMERIC(18,2)`, trips the CHECK, and reaches the client as a **500 where the contract
     promises 422**.
   - `{"pyramiding": 40000}` passes validate() and overflows SMALLINT → 500; the served schema
     carries no maximum, so the UI will submit it.
   - `{"pyramiding": "3"}` → **200**, stored as `3`: the same Pydantic coercion hole that was closed
     for booleans earlier this session, in string shape.
   - `SET search_path TO public;` in the migration is session-scoped and leaks onto the pooled
     connection for every later borrower.
   - A failed config PUT toasts "the run uses the last saved config" and then runs with the
     **unsaved** value — a configuration that existed nowhere.
   - The six-step renumbering silently **broke an existing spec**, `strategy-builder-live.spec.ts:36`.

2. **Real staging API results — blocked: the branch is not deployed.** Proven, not assumed:
   `GET /api/strategy-builder/config-schema` returns **404** on staging while the existing
   `GET /api/strategy-builder/templates` returns **401**, so the server is healthy and the route is
   simply absent. `/opt/nivesh-staging/repo` is on `dev` @ `eb8add52` — the commit this branch was
   cut from — and `backend/migrations/024_strategy_config.sql` is not in it. Deploying means pulling
   and rebuilding the staging containers, which I do not do unasked.

3. **A staging `session_token` is needed and I do not have one.** `GET`/`PUT /strategies/{id}/config`
   both call `get_current_user`; without a token every staging call is a 401, so the endpoints cannot
   be exercised against the deployed API even once it is deployed. ASKED THE USER EXPLICITLY, three
   turns running. Never fabricated.

4. **Applying the migration to the staging DB needs explicit authorisation.** The user's standing
   instruction this session is that the staging database is SELECT-only; `CREATE TABLE` is a write.
   Compounding it: `post_deploy_migrate`'s own `schema_migrations` table does not exist on that
   database, so the `backend/migrations/` series has never run there and the orchestrator would
   attempt 20+ unapplied files rather than this one. The safe rollout is the single file, and that is
   the user's call. ASKED EXPLICITLY.

WHAT IS AND IS NOT CLAIMED:
- Verified earlier this session with real, unedited output, against the PRE-FIX tree: migration
  applies and re-applies, all four CHECK bounds reject correctly, FK cascades (real `psql`);
  `32 passed` on the endpoint suite and `486 passed` across all backend suites; `7 passed (20.9s)`
  on the new Playwright spec with mocked routes and `--network none`; `tsc --noEmit` exit 0,
  hash-pinned. Those results describe code that is being changed right now and will be re-run.
- Three of those Playwright assertions were shown by the reviewer to pass against a broken screen
  too (TC-25's disabled-check, TC-28's synchronous `expect(calls).toEqual([])`, TC-27's
  identical-defaults mock). The green run is therefore partly hollow; strengthening them is part of
  the fix round. Recorded here so the number is not read as stronger than it is.
- NOT claimed: that the current tree passes anything, that the Bot details screen works, or that any
  of this is deployed, complete, working or done. Nothing committed; nothing pushed; the branch does
  not exist on the remote; staging is byte-for-byte unchanged.
