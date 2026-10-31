# Frontend regression baseline: Trade Desk › Strategy Lab (2026-10-28)

**Status: baseline MEASURED.** All 9 specs ran. Nothing was fixed or changed; this is a measurement only.
All outputs below are copied from the real runner logs, with ANSI colour codes stripped.

## Code under test

- Worktree `/home/deploy/nivesh-strategy-copilot`, branch `fix/strategy-run-access`.
- At the start, HEAD was `4855622005368e8ea0d1da4127ec4b43f7c1256e` (= origin/dev `48556220`, "Merge pull request #379: remove duplicate trading screens (step 6)").
- `git status --porcelain --ignored -- frontend-v5` was empty, and `git diff HEAD -- frontend-v5` was empty: no edits, no untracked files and no node_modules.
- **I tested a snapshot copy, not the live worktree.** I rsync'd `frontend-v5/` (excluding node_modules) to
  `/tmp/claude-1002/-home-deploy-nivesh-ai/3d5d2da4-dd5c-4e4e-9753-e2b535562f89/scratchpad/fe-copy`. I then checked it against HEAD with `git hash-object` for every tracked file: `checked=1258 missing=0 mismatched=0`.
  - Why a copy: vite and Playwright write files into the project dir (vite's config timestamp file, `test-results/`, and `e2e/.auth/session.json` from auth-setup).
  - `e2e/fe-run-stgraph.sh` itself says to mount a COPY.
  - Your instruction was to leave the worktree untouched, and the copy guarantees that.
- During the run, the other session committed `53f72ede` ("fix(strategy-builder): a backtest that did not run is stored as FAILED, never OK"). It changes 4 files: `.github/workflows/backend-tests.yml`, `backend/routes/strategy_builder.py`, `backend/services/strategy_engine/backtest.py` and `backend/tests/test_strategy_failed_runs.py`.
  - `git diff --name-only 48556220 53f72ede -- frontend-v5` lists 0 files, so this baseline is valid for both SHAs.
- After all runs, the worktree's `frontend-v5` still had a 0-line diff vs HEAD and no untracked or ignored files.

## Environment

- Image `mcr.microsoft.com/playwright:v1.47.0-jammy`, node v20.17.0, `@playwright/test` 1.60.0 from volume `wl-fe-node-modules`, vite 5.4.21.
- Chromium came from volume `pw-browsers-1223`.
- `npm ls --depth=0` in the volume against this package.json showed no UNMET or invalid entries. The volume is up to date, so **no new node_modules volume was created**.
- Every container ran with `--network none`.
- The host was heavily loaded: load average about 11.7 on 4 cores. A sibling session's Playwright container (`loving_kowalevski`, worktree nivesh-desk-wizard) and a backend pytest container were running at the same time.
- Container clock (UTC): main run 2026-10-27T23:58:58Z; isolation 00:05:29Z; graphs 00:08:53Z; bot-details 00:10:56Z (05:28–05:41 IST on 2026-10-28).

## Which config ran which spec, and why

| Spec | Config / runner | Reason (from the code) |
|---|---|---|
| copilot-app-desk-lab, -desk-strategy-builder, -desk-strategy-ideas, -desk-strategy-top, -desk-trade-desk, copilot-app-builder, copilot-app-backtest-universe | `pw.copilot-app.config.ts` (production build + `vite preview` on :5174, base /v5/) | Matches `testMatch: /copilot-app.*\.spec\.ts/` and the headers say "Production build — see pw.copilot-app.config.ts" |
| copilot-app-desk-strategy-graphs | `e2e/fe-run-stgraph.sh` (build with `VITE_STRATEGY_HARNESS=1`, then `pw.copilot-app.config.ts`) | Header: "this spec fails under the standard pw.copilot-app.config.ts recipe by design. Run it with `bash frontend-v5/e2e/fe-run-stgraph.sh`" |
| strategy-config-bot-details | `playwright.config.ts --project=desktop-chrome` (webServer = vite dev server with `vite.test.config.ts`, VITE_BASE=/v5/; depends on `auth-setup`) | Header: "it runs in the mocked `desktop-chrome` project of playwright.config.ts". It does not match the copilot-app testMatch. |

## Exact commands

`S=/tmp/claude-1002/-home-deploy-nivesh-ai/3d5d2da4-dd5c-4e4e-9753-e2b535562f89/scratchpad`

Snapshot:
```
cd /home/deploy/nivesh-strategy-copilot && rsync -a --delete --exclude node_modules frontend-v5/ $S/fe-copy/
```

### Run 1: the 7 copilot-app specs
```
sudo docker run --rm --name baseline-main-20261028 --network none \
  -v $S/fe-copy:/app -v wl-fe-node-modules:/app/node_modules:ro -v pw-browsers-1223:/pw:ro -v $S/pw-out/main:/out -v $S/runs:/runs:ro \
  -e PLAYWRIGHT_BROWSERS_PATH=/pw -w /app mcr.microsoft.com/playwright:v1.47.0-jammy \
  bash /runs/inner_main.sh \
  e2e/tests/copilot-app-desk-lab.spec.ts e2e/tests/copilot-app-desk-strategy-builder.spec.ts e2e/tests/copilot-app-desk-strategy-ideas.spec.ts \
  e2e/tests/copilot-app-desk-strategy-top.spec.ts e2e/tests/copilot-app-desk-trade-desk.spec.ts e2e/tests/copilot-app-builder.spec.ts \
  e2e/tests/copilot-app-backtest-universe.spec.ts > $S/audit/run_main.log 2>&1
```
`$S/runs/inner_main.sh`:
```
cd /app
VITE_USE_MOCK_API=false VITE_BASE=/v5/ npx vite build --outDir /tmp/cp-dist --emptyOutDir > /tmp/build.log 2>&1 || { tail -40 /tmp/build.log; echo "BUILD FAILED"; exit 1; }
(VITE_BASE=/v5/ npx vite preview --outDir /tmp/cp-dist --port 5174 --strictPort > /tmp/prev.log 2>&1 &)
for i in $(seq 1 120); do (echo > /dev/tcp/127.0.0.1/5174) 2>/dev/null && break; sleep 0.5; done
# probe: fetch http://localhost:5174/v5/app and check it references /v5/assets
npx playwright test --config pw.copilot-app.config.ts "$@" --output /out --reporter=list
```
Real preflight output:
```
== date 2026-10-27T23:58:58Z  node v20.17.0  playwright Version 1.60.0
✓ built in 36.16s
== preview:   ➜  Local:   http://localhost:5174/v5/
== probe /v5/app -> 200 7116 has /v5/assets script
Running 231 tests using 3 workers
```

### Run 2: re-running each failing test alone (3 times each)
```
sudo docker run --rm --name baseline-iso-20261028 --network none \
  -v $S/fe-copy:/app -v wl-fe-node-modules:/app/node_modules:ro -v pw-browsers-1223:/pw:ro -v $S/pw-out/iso:/out -v $S/runs:/runs:ro \
  -e PLAYWRIGHT_BROWSERS_PATH=/pw -w /app mcr.microsoft.com/playwright:v1.47.0-jammy \
  bash /runs/inner_iso.sh e2e/tests/copilot-app-desk-strategy-ideas.spec.ts:463 e2e/tests/copilot-app-desk-strategy-ideas.spec.ts:522 e2e/tests/copilot-app-desk-strategy-ideas.spec.ts:553
```
`inner_iso.sh` makes the same build and preview once. Then, for each test and attempt n=1..3, it runs:
`npx playwright test --config pw.copilot-app.config.ts "<file:line>" --workers=1 --output /out/<test>-<n> --reporter=list`

### Run 3: strategy-graphs (harness build)
```
sudo docker run --rm --name baseline-stgraph-20261028 --network none \
  -v $S/fe-copy:/app -v wl-fe-node-modules:/app/node_modules:ro -v pw-browsers-1223:/pw:ro -v $S/pw-out/graphs:/out \
  -e PLAYWRIGHT_BROWSERS_PATH=/pw -w /app mcr.microsoft.com/playwright:v1.47.0-jammy \
  bash -c 'bash e2e/fe-run-stgraph.sh --output /out --reporter=list'
```

### Run 4: strategy-config-bot-details
```
sudo docker run --rm --name baseline-bot-20261028 --network none \
  -v $S/fe-copy:/app -v wl-fe-node-modules:/app/node_modules -v pw-browsers-1223:/pw:ro -v $S/pw-out/bot:/out -v $S/runs:/runs:ro \
  -e PLAYWRIGHT_BROWSERS_PATH=/pw -w /app mcr.microsoft.com/playwright:v1.47.0-jammy \
  bash /runs/inner_bot.sh
# inner_bot.sh:
npx playwright test --config playwright.config.ts --project=desktop-chrome e2e/tests/strategy-config-bot-details.spec.ts --output /out --reporter=list
```
- On this run, the node_modules volume was mounted read-write: I left off `:ro` by mistake.
- The vite dev server's cache dir is `node_modules/.vite`, so I checked for writes. `find <volume> -newermt '2026-10-28 05:00' | wc -l` returned `0`, and `.vite/deps` is still dated 2026-10-21. **The shared volume was not modified.**

## Runner totals (real lines)

| Run | Totals line |
|---|---|
| Run 1: 7 copilot-app specs | `3 failed` / `16 skipped` / `212 passed (5.3m)`, then `== playwright exit=1` |
| Run 3: strategy-graphs (harness) | `Running 32 tests using 3 workers` … `32 passed (57.4s)`, then `== fe-run-stgraph exit=0` |
| Run 4: bot-details | `Running 9 tests using 2 workers` … `9 passed (1.2m)`, then `== playwright exit=0` (1 auth-setup + 8 spec tests) |

**Across the 9 specs:** 271 tests. 252 passed, 3 failed, 16 skipped; 0 flaky. The `auth-setup` project also passed, and is not counted in the 271.

## Results per spec

The counts come from the list reporter's ✓ / ✘ / - lines in `run_main.clean.log` and the other logs. They add up to the totals.

| Spec | Passed | Failed | Skipped | Notes |
|---|---|---|---|---|
| copilot-app-desk-lab.spec.ts | 98 | 0 | 2 | The skips are `screenshots desktop` / `screenshots mobile` (they need the dir `playwright-report/fidelity-lab`) |
| copilot-app-desk-strategy-builder.spec.ts | 28 | 0 | 14 | The skips are 14 `shot <kind> 1440/390` cases (they need `SHOTS_DIR`) |
| copilot-app-desk-strategy-graphs.spec.ts | 32 | 0 | 0 | Harness build only (see above) |
| copilot-app-desk-strategy-ideas.spec.ts | 16 | **3** | 0 | SI-6, SI-7 and SI-7b fail every time (below) |
| copilot-app-desk-strategy-top.spec.ts | 27 | 0 | 0 | |
| copilot-app-desk-trade-desk.spec.ts | 37 | 0 | 0 | |
| copilot-app-builder.spec.ts | 4 | 0 | 0 | |
| copilot-app-backtest-universe.spec.ts | 2 | 0 | 0 | |
| strategy-config-bot-details.spec.ts | 8 | 0 | 0 | Plus `auth-setup` 1 passed |

All 16 skips are environment-gated screenshot cases (`test.skip(!SHOTS, …)` / `test.skip(!fs.existsSync(SHOT_DIR), …)`). They skip by design, not because of a failure.

## Failing tests (deterministic: each failed 3 out of 3 when run alone)

### 1. `copilot-app-desk-strategy-ideas.spec.ts:463` SI-6 Open full plan goes to One stock … Open this strategy also selects that candidate
```
    Error: expect(received).toMatchObject(expected)
    - Expected  - 1
    + Received  + 1
    @@ -10,7 +10,7 @@
        "src_bucket": "breakout_confirmed",
        "src_date": "2026-10-19",
        "src_kind": "ideas",
        "sym": "ICICIBANK",
        "tab": "trade",
    -   "view": "new",
    +   "view": "lab",
      }
    > 468 |     expect(Object.fromEntries(q)).toMatchObject({
      469 |       tab: "trade", view: "new", mode: "stock", sym: "ICICIBANK", // was more/strategy before the 2026-10-27 redesign direction: "bullish", instrument: "all", build: "1",
        at /app/e2e/tests/copilot-app-desk-strategy-ideas.spec.ts:468:35
```
Alone: attempt 1 ✘ (2.2s), attempt 2 ✘ (2.5s), attempt 3 ✘ (2.4s). The same `toMatchObject` error each time.

### 2. `copilot-app-desk-strategy-ideas.spec.ts:522` SI-7 the Overview's Top AI opportunities card links to the board (card and row), the row link scrolls to that idea
```
    Error: expect(locator).toBeVisible() failed
    Locator: getByTestId('desk-opps-card')
    Expected: visible
    Timeout: 5000ms
    Error: element(s) not found
    > 526 |     await expect(page.getByTestId("desk-opps-card")).toBeVisible();
        at /app/e2e/tests/copilot-app-desk-strategy-ideas.spec.ts:526:54
```
Alone: attempt 1 ✘ (5.6s), attempt 2 ✘ (5.8s), attempt 3 ✘ (5.8s). The same error each time.

### 3. `copilot-app-desk-strategy-ideas.spec.ts:553` SI-7b the phone Overview card has the same link
```
    Test timeout of 30000ms exceeded.
    Error: locator.click: Test timeout of 30000ms exceeded.
    Call log:
      - waiting for getByTestId('desk-top-opps-strategies')
    > 557 |     await page.getByTestId("desk-top-opps-strategies").click();
        at /app/e2e/tests/copilot-app-desk-strategy-ideas.spec.ts:557:56
```
Alone: attempt 1 ✘ (30.1s), attempt 2 ✘ (30.1s), attempt 3 ✘ (30.1s).

### What the code shows about these failures (read-only grep, nothing changed)

- `grep -rn "desk-opps-card\|desk-opps-strategies\|desk-top-opps-strategies" frontend-v5/src` finds **nothing**. The test IDs that SI-7 and SI-7b need do not exist in the app at this SHA.
  - This is consistent with the Overview card being removed in the desk redesign (HEAD is the "remove duplicate trading screens (step 6)" merge).
- For SI-6, `src/pages/CopilotApp/screens/tradingdesk/desk-nav.ts:198` maps the old view `"new"` to `set("trade", "lab", undefined, "build")`. So the app now writes `view=lab` (canonical desk URLs, commit 7ef83ad2), while the spec still expects `view: "new"`.
- Likely cause: the spec is out of date after the redesign, not a runtime crash.
- **UNVERIFIED:** whether the product intends these links to exist. That is a product decision and was not tested here.

These 3 failures are the existing state on dev. They are the **baseline**: a later change should not be blamed for them, and should not add new ones.

## Flaky tests

None were seen. Retries are 0 in `pw.copilot-app.config.ts`, and no test passed on one run and failed on another. The 3 failures above reproduced in 9 out of 9 isolated attempts.

## What could not be run

Nothing. All 9 requested specs ran.
- `copilot-app-desk-strategy-graphs` was run only under its harness build. Under the standard build it "fails by design" (per its header), so it was not also run there.

## Artifacts

All under `/tmp/claude-1002/-home-deploy-nivesh-ai/3d5d2da4-dd5c-4e4e-9753-e2b535562f89/scratchpad/`:
- Raw and ANSI-stripped logs: `audit/run_main.log`, `audit/run_main.clean.log`, `audit/run_iso.log`, `audit/run_graphs.log`, `audit/run_graphs.clean.log`, `audit/run_bot.log`, `audit/run_bot.clean.log`
- Failure screenshots and error-context: `pw-out/main/copilot-app-desk-strategy--*/` and `pw-out/iso/*/`
- Scripts: `runs/inner_main.sh`, `runs/inner_iso.sh`, `runs/inner_bot.sh`
