# OVERRIDE — Simulation Lab UI (Research → Simulation Lab)

- **Branch:** feat/paper-trade-engine (worktree /app/.claude/worktrees/paper-engine)
- **Date:** 2026-09-20
- **Scope of the skip:** the **staging** half of `.claude/VERIFICATION_PROTOCOL.md` only — real staging API calls and
  the Playwright run against the deployed page.
- **Companion report (not a skip):** `test_reports/sim_lab_ui.md`, which carries the up-front test cases and the
  real local evidence for the four endpoints (200 / 422 / 403 / 503 paths) and for `npx tsc --noEmit` +
  `npm run build`.

REASON: staging verification is blocked pending the owner's explicit authorization of a `dev` push. App staging
redeploys from `origin/dev`, which also feeds the live login, so pushing this branch's work to `dev` is a live,
production-adjacent deploy. The task that produced this change explicitly withheld that authorization ("do not deploy
anything, do not push to dev"), and no other environment serves `/api/sim-lab/*` or the V5 `/research` page behind
`RequireAuth` + the `sim_lab` feature gate. Rather than fabricate staging output or a Playwright transcript, the work
stops here and says so.

## What is therefore UNVERIFIED

- That the page renders at all in a browser, that every tab loads, and that the matrix / candidate / trade row-detail
  panels open.
- No horizontal overflow at 390 px; correct reading in light and dark themes.
- That the red **DEVELOPMENT FIXTURE** banner shows while the committed snapshot is the fixture.
- That `/api/sim-lab/*` answers the same way inside the full `backend/server.py` app (Mongo + real env) as it does
  under the injected-gate TestClient used locally.
- Data correctness against the real frozen run: the committed snapshot is a hand-written **fixture**, not results.

## What unblocks it

1. Owner authorization for a `dev` push (a live deploy), or a local dev-stack run of backend + frontend-v5.
2. `sim_lab` turned on for the verifying account (the flag is allowlist-mode and fails closed; it also still needs a
   `KNOWN_FEATURES` entry in `backend/feature_flags.py` — a file another agent owns this session — to be manageable
   from the admin panel and to appear in `/auth/me`'s feature map).
3. The generated snapshot from the frozen run in place of the fixture.
4. Then: `curl` the four endpoints on staging with a session cookie, and `npx playwright test` driving the tabs via
   the `data-testid`s (`sim-lab-screen`, `sl-tab-*`, `sl-matrix-row-*`, `sl-cand-row`, `sl-trade-row`,
   `sl-banner-internal`, `sl-banner-fixture`).
