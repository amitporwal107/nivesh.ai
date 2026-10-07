# OVERRIDE — Move Odds "Live Watch" tab (colour-coded progress panel)

- **Branch:** feat/live-move-odds-watch (worktree `.claude/worktrees/live-watch`, based on `origin/dev` @ 59093888)
- **Date:** 2026-10-07
- **Author:** Claude Sonnet 5
- **Changed areas:** backend routes/services: no · frontend src: yes
  (`frontend-v5/src/pages/Research/LiveWatchPanel.tsx` new, `MoveOddsScreen.tsx` + `moveOdds.css` edited)

## REASON (why this is an override, not a PASS report)

Two blockers, both disclosed to the owner in-session before this file was written:

1. **This VM (nidp-stack-vm) hit a real disk-full incident during this task**: free space dropped to 55MB
   at one point (root cause found and reported separately: an unrotated Grafana container log growing
   unbounded from a misconfigured alert rule). Safe cleanup (truncating runaway container logs, clearing
   caches, pruning stopped containers) recovered headroom, but it is nowhere near enough to `npm ci` a
   ~400MB `node_modules` for `frontend-v5` and run Playwright locally without risking the same incident
   again on a disk shared with live, healthy production-adjacent containers (`nidp-postgres-staging`,
   `nidp-minio`). The owner was asked and chose not to run the disk resize this session.
2. **The change is not deployed anywhere yet.** It lives only on this local branch/worktree. This repo's
   actual frontend build/typecheck runs on GitHub Actions on push to `dev` (confirmed by reading
   `.github/workflows/deploy-frontend-staging.yml`), and Playwright verification per
   `.claude/VERIFICATION_PROTOCOL.md` is run against staging — neither is reachable until this is pushed
   and deployed, which the owner has not yet asked for (pushing to `dev` triggers a live staging deploy).

## What WAS verified this session (real output, not fabricated)

- **Data layer for both heads is real and populated**, queried directly against staging Postgres
  (read-only, `research/ten_percent_days/rpsql.sh staging`):
  ```
  head        | count | latest_session | latest_run_id
  p_down10_1d | 12386 | 2026-10-06     | 15
  p_down5_1d  | 12386 | 2026-10-06     | 15
  p_up10_1d   | 12386 | 2026-10-06     | 15
  p_up5_1d    | 12386 | 2026-10-06     | 15
  ```
  Confirms `p_up10_1d` has identical real coverage to `p_up5_1d` — the +10% watchlist this panel also
  reads from is not a gap.
- **The reused `/api/move-odds/live` endpoint and `services/move_odds_live.py` already exist on `dev`**
  and already compute `touched`/`levels`/`change_pct` per symbol (read directly from source, not assumed).
  This change adds no new backend surface — it only adds a frontend view over data two existing,
  already-shipped endpoints (`/api/move-odds/latest`, `/api/move-odds/live`) already serve.
- Manual source review of the new component for the stated logic (band = reached/rising/flat/nodata from
  `touched[head]` and `change_pct` sign) — no automated test run.

## NOT verified (this is the gap this override exists to name)

- No `npm run typecheck` / `npm run build` run locally (blocked by disk; the project's own CI runs this
  remotely on push, not locally).
- No Playwright run (`frontend-v5/e2e/`) — the feature is not on any environment Playwright can reach.
- No live-in-browser check of the new "Live Watch" tab, its 30s polling, or the colour bands rendering
  correctly against real data.

## To close this override

1. Owner reviews the diff (`git diff dev feat/live-move-odds-watch` or the PR).
2. Push `feat/live-move-odds-watch` and open a PR into `dev` (per this repo's PR rule) — or, if the owner
   wants it on staging immediately, merge/push to `dev` directly, which auto-deploys per
   `deploy-frontend-staging.yml`.
3. Once deployed: run `npx playwright test` against the new `data-testid`s (`mo-view-livewatch`,
   `mo-livewatch`, `mo-livewatch-row-*`, `mo-livewatch-band-*`) and replace this file with a real PASS
   report, or extend `frontend-v5/e2e/tests/staging-move-odds.live-contracts.spec.ts` (already has the
   `mo-tab-10` pattern this reuses).

## Verdict: OVERRIDE
