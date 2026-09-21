# Functionality Verification Report — Simulation Lab → "Run spec template" tab

- **Branch:** detached at `96a29393` (worktree `/app/.claude/worktrees/ui-runspec`)
- **Date:** 2026-09-20
- **Author:** Claude (Full-Stack Developer + QA Engineer, per CONTEXT.md §0 step 3)
- **Environment:** local worktree only. **No staging, no deploy, no push** — a `dev` push is a live deploy and was
  not authorized for this task.
- **Changed areas:** backend routes/services: **no** · frontend src: **yes**
  (`frontend-v5/src/pages/Research/SimulationLabScreen.tsx`, `frontend-v5/src/pages/Research/simRunSpec.ts`)

## Summary
Adds one tab, `RUN SPEC TEMPLATE`, to the Simulation Lab screen, from the owner's design. It is static reference
content: a left panel showing the reusable run spec (`schema sim/v1`) with a **Blank skeleton / Filled example · Run A**
toggle and a **Copy to clipboard** button, and a right column with **How to use it** (01–04) and **Block rules**. It
calls no API and renders with no snapshot loaded. Two real files back it:
`research/sim_diag/specs/_TEMPLATE.sim-v1.yaml` (the skeleton people copy) and
`research/sim_diag/specs/EXAMPLE-R-2022-A.sim-v1.yaml` (configuration A as pre-registered and already run).

**Ordering, stated plainly:** VERIFICATION_PROTOCOL §1 asks for test cases authored *up front*. The design was settled
from the source documents before any code was written, but this file was created after the implementation compiled.
I am not claiming the up-front ordering.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | content parity | The two YAML template literals in `simRunSpec.ts` are byte-identical to the files they name | unit | both IDENTICAL | **PASS** |
| TC-2 | spec files | Both YAML files parse, with the same four top-level blocks and the same key set | edge | parse OK, identical structure | **PASS** |
| TC-3 | data | Every frozen-input filename, sha256, prediction commit, model, label and cost model in the filled example appears verbatim in `PREREGISTRATION_SIM_MATRIX.md` | data | all FOUND | **PASS** |
| TC-4 | data | Every parameter name the YAML uses exists as a field of `tradesim.Spec` | data | none missing | **PASS** |
| TC-5 | build | `npx tsc --noEmit` is clean | unit | exit 0, no diagnostics | **PASS** |
| TC-6 | build | `npm run build` succeeds and the bundle carries the tab's text | unit | exit 0, strings present | **PASS** |
| TC-7 | isolation | `RunSpecTab` makes no API call (no `get<`, `http(`, `fetch(`, `/api/`) | unit | none found | **PASS** |
| TC-8 | UI | The tab shows in the strip as `sl-tab-runspec` and switches the panel | e2e | tab selected, panel rendered | **BLOCKED** |
| TC-9 | UI | The toggle swaps skeleton ↔ filled example and clears the copied state | e2e | YAML body changes | **BLOCKED** |
| TC-10 | UI | Copy writes the shown YAML and shows a visible "Copied" state that clears | e2e | clipboard = YAML | **BLOCKED** |
| TC-11 | failure | Clipboard API unavailable/denied → "not available here" message, never a false "Copied" | failure | fallback message | **BLOCKED** (code path reviewed only) |
| TC-12 | edge | The tab renders with **no snapshot** (503 / error from `/api/sim-lab/run`) | edge | tab strip + panel render | **BLOCKED** (code path reviewed only) |
| TC-13 | edge | No horizontal page scroll at 390 px; readable in light and dark | e2e | no overflow | **BLOCKED** |
| TC-14 | edge | A 403 account never reaches the tab (the access gate returns first) | edge | "not enabled" card only | **BLOCKED** (code path reviewed only) |

## Local verification (real, unedited output)

### TC-5 — typecheck
```
$ cd frontend-v5 && npx tsc --version && npx tsc --noEmit; echo "tsc --noEmit exit: $?"
Version 5.9.3
tsc --noEmit exit: 0
```

### TC-6 — production build (tail; the two chunk warnings above it are pre-existing)
```
$ npm run build
> nivesh-frontend@0.1.0 build
> find src -name '*.js' -delete 2>/dev/null || true && tsc -b && vite build

vite v5.4.21 building for production...
✓ 3393 modules transformed.
dist/assets/mermaid-GHXKKRXX-B4DwmBAs.js             473.61 kB │ gzip: 148.70 kB │ map: 2,002.76 kB
dist/assets/index-CBBLhFqQ.js                        484.68 kB │ gzip: 160.14 kB │ map: 1,942.63 kB
dist/assets/index-B_ejVLbN.js                      2,482.23 kB │ gzip: 664.76 kB │ map: 7,547.67 kB
✓ built in 14.59s
build exit: 0
```
Bundle contains the tab (run against the previous build's chunk name):
```
$ grep -c "NIVESH · SIMULATION RUN SPEC" frontend-v5/dist/assets/index-BGt5DSPp.js
2
$ grep -o "Run spec template" ... | head -1
Run spec template
$ grep -o "never a sibling .result.yaml" ... | head -1
never a sibling .result.yaml
```

### TC-1 — the page and the files cannot drift
```
template literals found in simRunSpec.ts: 2
  IDENTICAL  research/sim_diag/specs/_TEMPLATE.sim-v1.yaml  (3665 chars on disk, 3665 embedded)
  IDENTICAL  research/sim_diag/specs/EXAMPLE-R-2022-A.sim-v1.yaml  (4294 chars on disk, 4294 embedded)
```

### TC-2 — both YAML files parse
`/app/research/tpd_run/.venv/bin/python` has no PyYAML (`ModuleNotFoundError: No module named 'yaml'`), so the
system `python3` (PyYAML 6.0) was used rather than installing into a venv other runs share.
```
============================================================================
research/sim_diag/specs/_TEMPLATE.sim-v1.yaml -> PyYAML 6.0 parsed OK
top-level keys: ['run', 'frozen_inputs', 'parameters', 'pre_registration']
  run: ['id', 'label', 'matrix_ref', 'registered_at', 'registered_by']
  frozen_inputs: ['dataset', 'dataset_sha256', 'oof_predictions', 'oof_sha256', 'picks', 'picks_sha256', 'calibration', 'calibration_sha256', 'prediction_commit', 'model', 'label', 'cost_model', 'bars', 'block', 'sealed']
  parameters: ['universe', 'selection', 'scope', 'entry', 'stop', 'stop_pct', 'target', 'target_pct', 'sizing', 'notional', 'costs_on', 'slippage_basis', 'policy', 'sessions', 'carry_sessions', 'participation_pct', 'max_chase_pct']
  pre_registration: ['hypothesis', 'isolates', 'metrics', 'decision_rule', 'failure', 'no_tuning_after_run']
  run.id                      = None
  parameters.scope keys       = ['sessions', 'window']
  pre_registration.no_tuning_after_run = True
============================================================================
research/sim_diag/specs/EXAMPLE-R-2022-A.sim-v1.yaml -> PyYAML 6.0 parsed OK
top-level keys: ['run', 'frozen_inputs', 'parameters', 'pre_registration']
  (identical key set to the skeleton)
  run.id                      = 'R-2022-A'
  run.registered_at           = datetime.date(2026, 9, 20)
  frozen_inputs.dataset_sha256= '7bb77e5ad50f4bf6a6db54527bc6a90437701e9d5bc5d36a87f4b187e0f9b327'
  parameters.entry/stop/target= NEXT_OPEN / FIXED / FIXED
  parameters.sessions         = 5  notional = 50000
  pre_registration.metrics    = 7 items
  pre_registration.no_tuning_after_run = True
```

## Data Correctness — TC-3 / TC-4
The filled example is not illustrative: every value was checked back against the pre-registration and the code.
```
  FOUND    dataset file         dataset_dev_20260919T212230.csv.gz
  FOUND    dataset sha256       7bb77e5ad50f4bf6a6db54527bc6a90437701e9d5bc5d36a87f4b187e0f9b327
  FOUND    oof file             dev_oof_20260919T214001.csv.gz
  FOUND    oof sha256           8763f064b35b633332db6c60bfdd36dbc3b8cf65bd3c83bb7eafb0ef38650569
  FOUND    picks file           dev_picks_M8_20260919T214001.csv
  FOUND    picks sha256         d05cccc241be6a55217b2557dc82657befd1420894b8e5c339f387caa0d3281b
  FOUND    calibration file     iso__M8__tbs_5_2.pkl
  FOUND    calibration sha256   1f1b22c567634f597dfaad4d006612e0af10d3637e24704fdae53f928e1c0597
  FOUND    prediction commit    a499ce19b22000756da00fc813b3aa27c8e18f9a
  FOUND    cost model           zerodha-equity-v1
  FOUND    model                M8
  FOUND    label                tbs_5_2

parameters vs the §4 matrix row for A (baseline conventions):
  FOUND    entry          spec='NEXT_OPEN'  prereg text 's1 open'
  FOUND    stop_pct       spec=2            prereg text '| 2% |'
  FOUND    target_pct     spec=5            prereg text '| 5% |'
  FOUND    notional       spec=50000        prereg text '50,000'
  FOUND    sessions cap   spec=5            prereg text 'at most 5 sessions'
  FOUND    policy         spec='STOP_FIRST' prereg text 'stop-first'
  FOUND    slippage_basis spec='DECISION'   prereg text 'decision day'
  FOUND    costs_on       spec=True         prereg text 'costs on'

ALL VALUES TRACE TO THE PRE-REGISTRATION: True

Spec fields used by the YAML that do NOT exist in tradesim.Spec: none
```

### TC-7 — the tab reads nothing
```
$ awk '/^function RunSpecTab/,0' frontend-v5/src/pages/Research/SimulationLabScreen.tsx \
    | grep -nE "get<|http\(|fetch\(|/api/"
  no API call, no fetch, no /api/ path inside RunSpecTab
```

## What the tab claims vs what the runner actually does today
The owner's step 04 describes runner behaviour that **does not exist**. Checked in
`research/sim_diag/run_matrix.py` and across `research/sim_diag/*.py`:

- There is **no spec loader**. `grep -rn "yaml|specs/" research/sim_diag/*.py` returns nothing. Configurations come
  from `matrix.py` (`MATRIX` / `SECONDARY` / `POOL`), not from a file.
- It writes `matrix_results.json` + `manifest.json` into `/app/research/sim_diag/matrix_<stamp>/`, outside git.
  **No `.result.yaml` is written anywhere** in the repo.
- It *does* refuse to run on a dirty tree — `main()` raises `uncommitted changes; commit first` from
  `git status --porcelain -- research/sim_diag research/model_v5 backend/nidp/services/tpd_model`. An uncommitted
  spec under `research/sim_diag/specs/` is caught by that path check, so "the runner refuses a spec that is not
  committed" is true **as a side effect of the tree check**, not because the spec is read.

So the tab states step 04 as intent and carries a `RUNNER TODAY` note beside it saying exactly the above. Nothing on
the page describes the unimplemented behaviour as current.

**Operational consequence, verified in this worktree:** the two new spec files make `research/sim_diag` dirty until
they are committed, which would block a non-smoke `run_matrix.py` run:
```
$ git status --porcelain -- research/sim_diag
?? research/sim_diag/specs/
```
(That is this worktree; `run_matrix.py` runs from `/app`, which is unaffected until these files land there.)

## UI / Playwright Tests
**NOT RUN — see `test_reports/OVERRIDE_sim_lab_runspec.md`.** No Playwright output is presented, and none was
invented. TC-8 … TC-14 are unverified.

## Inputs required from user
- Authorization for a `dev` push (a live deploy) — or a running local dev stack plus a `session_token` and the
  `sim_lab` feature flag on the verifying account — before the UI cases can be run.

## Verdict: BLOCKED
