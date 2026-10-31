# Functionality Verification Report — Evidence & Validation screen (post-disclosure forward-returns study)

- **Branch:** feat/evidence-validation-screen (from feat/provider-foundations @ 8dc09801)
- **Date:** 2026-10-23
- **Author:** Claude (full-stack developer, with QA-engineer verification discipline)
- **Environment:** app VM `45.64.105.88` / staging containers (`nivesh/backend:staging`,
  `mcr.microsoft.com/playwright:v1.47.0-jammy`); no live warehouse query is involved — this screen
  serves a FROZEN, already-run, hash-guarded research study, not live SQL.
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary

Repurposes the "Post-Disclosure" screen into an **Evidence & Validation** screen on the Smart
Money tab: a transparent report of the real, pre-registered `NIDP-SHP-FWD-001` study (branch
`study/post-disclosure-forward-returns` @ `62443b98`), whose own result is **INCONCLUSIVE**. No
predictive score, no ranking, no buy/sell framing — ever. New files only, except a 6-line mount in
`SmartMoneyTab.tsx` (import + `<EvidenceValidationPanel />`):

- `backend/nidp/services/daas_api/routers/evidence_validation.py` — `GET /v1/desk/evidence/post-disclosure-study`
- `backend/routes/markets_evidence.py` — `GET /api/markets/evidence/post-disclosure-study` (thin proxy)
- `frontend-v5/src/pages/CopilotApp/screens/tradingdesk/evidence-validation-data.ts`
- `frontend-v5/src/pages/CopilotApp/screens/tradingdesk/EvidenceValidationPanel.tsx`
- `backend/nidp/tests/services/test_daas_evidence_validation.py`, `backend/tests/test_markets_evidence_routes.py`
- `frontend-v5/e2e/tests/copilot-app-desk-evidence-validation.spec.ts`
- registered in `backend/nidp/services/daas_api/app.py`, `backend/server.py`

**Design decision, stated explicitly (not guessed):** the DaaS router serves a hardcoded, frozen
snapshot of the study's own already-run, already-verified output — not a live SQL re-query, and not
a modification to `study.py` (which lives, untouched, on the unmerged
`study/post-disclosure-forward-returns` branch and was never copied or merged into this branch, per
the orchestrator's instruction). Every numeric field in `evidence_validation.py` is commented with
the exact source line it was copied from in
`test_reports/SHP_POST_DISCLOSURE_FORWARD_STUDY_20261023.md`, and the module records the study's
`PREREGISTRATION_SHA256` as provenance so the frozen numbers are traceable to the contract that
produced them. This keeps the hash-guard contract meaningful (the frozen numbers ARE the hash-guarded
run's real output) without needing to execute `study.py` from a branch this task was told not to merge.

## Test Cases
> Authored from the API/UI design (the orchestrator's exact UI contract) before implementation.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | api | verdict field | unit/api | `INCONCLUSIVE`, top-level, with a reason | PASS |
| TC-2 | api | disclosure text | unit/api | names "research artifact", "not a product feature", "no predictive score", "no ranking" | PASS |
| TC-3 | api | study period / quarters / review floor | unit/api | 2024-03-31→2026-06-30, 10 quarters, floor 12 | PASS |
| TC-4 | api | primary/secondary horizons | unit/api | primary 20, secondary [5,60] | PASS |
| TC-5 | api | eligible population | unit/api | 1,255 (matches report §4 "Eligible after screens") | PASS |
| TC-6 | api | pre-registration SHA-256 recorded | unit/api | matches study.py's `PREREG_SHA256` / report header | PASS |
| TC-7 | api | primary horizon row: spread + CI + blocks + positive quarters | unit/api | +1.0749pp, CI [-0.8673,+2.9054], blocks 10, pos 6/10 | PASS |
| TC-8 | api | secondary horizon rows (5, 60) each carry their own CI | unit/api | 5: -0.0007pp CI[-1.1932,+1.1074]; 60: -0.7468pp CI[-5.6316,+3.6992] | PASS |
| TC-9 | api | exactly one row marked primary | unit/api | sessions=20 only | PASS |
| TC-10 | api | cost-adjusted figure explicit | unit/api | cost_total_pp 0.9874; horizon-20 net 0.0875 | PASS |
| TC-11 | edge | Sep 2026 "not yet eligible" is its own field | edge | separate `not_yet_eligible` object, never a horizon row, never folded into `quarters` (stays 10) | PASS |
| TC-12 | edge | Sep 2026 never renders as 0 or positive | edge | not present in any `mean_spread_pp`/row | PASS |
| TC-13 | edge | no TRI / benchmark field anywhere | edge | no `benchmark*`/`tri*`/`vs_nifty` key in payload or rows | PASS |
| TC-14 | edge | no score/rank/signal key anywhere in the JSON tree | edge | recursive key-scan passes | PASS |
| TC-15 | api | count/total describe the 3 horizon rows | unit/api | count=total=3, len(rows)=3 | PASS |
| TC-16 | api | proxy forwards unchanged | api | identical JSON through `/api/markets/evidence/post-disclosure-study` | PASS |
| TC-17 | api | proxy: verdict + primary row + not_yet_eligible survive the hop | api | same values after proxy | PASS |
| TC-18 | failure | upstream 503/404/200-without-rows/non-JSON/unreachable | failure | 502 `upstream_unavailable`, never a fabricated study | PASS |
| TC-19 | failure | DaaS not configured | failure | 502, upstream never called | PASS |
| TC-20 | auth | signed-out user | failure | 401 `Not authenticated`, upstream never called | PASS |
| TC-21 | e2e | INCONCLUSIVE is the loud, primary state | e2e | headline block, not a footnote | PASS |
| TC-22 | e2e | primary horizon shows spread WITH CI, blocks, positive quarters | e2e | all four values visible together | PASS |
| TC-23 | e2e | secondary horizons (5, 60) shown, each with its own CI | e2e | both cards render with their real numbers | PASS |
| TC-24 | e2e | cost-adjusted figure shown explicitly | e2e | net-of-cost visible on every horizon card | PASS |
| TC-25 | e2e | Sep 2026 renders as its own field, never a zero/fold-in | e2e | dedicated card; horizon count stays 3 | PASS |
| TC-26 | e2e | no TRI row/benchmark figure on the panel | e2e | no "vs Nifty 500" / excess-return text; no `benchmark` text in any horizon card; absence is explained | PASS |
| TC-27 | e2e | nothing reads as score/rank/buy-sell signal | e2e | banned-phrase scan over the panel's own text | PASS |
| TC-28 | e2e | study contract fields on screen | e2e | period, quarters, horizon, eligible pairs all visible | PASS |
| TC-29 | failure | upstream failure is an error state, never a fabricated study | e2e | ErrorBlock shown, no verdict text rendered | PASS |
| TC-30 | e2e | pre-registration hash shown for provenance | e2e | full SHA-256 visible | PASS |
| TC-31 | regression | existing Smart Money tab (29 cases) unaffected by the mount | e2e | all pass except one unrelated, pre-existing date-drift assertion | PASS (see note) |

## API / Endpoint Tests

### pytest — the DaaS router (static, hash-cited snapshot) and the app-side proxy

Command (throwaway container, repo mounted read-only, per
`provider-credentials-and-test-harness.md`):

```
sudo docker run --rm --network none \
  -v /home/deploy/nivesh.ai/.claude/worktrees/agent-aac67438b8736b3f1:/work:ro \
  -w /work/backend -e PYTHONDONTWRITEBYTECODE=1 -e MONGO_URL=mongodb://localhost:27017 \
  -e DB_NAME=unit_test -e OPENAI_API_KEY=unit-test-placeholder \
  nivesh/backend:staging python -m pytest \
    nidp/tests/services/test_daas_evidence_validation.py tests/test_markets_evidence_routes.py \
    -q -p no:cacheprovider
```

Real output:

```
.........................                                                [100%]
=============================== warnings summary ===============================
../../usr/local/lib/python3.11/site-packages/starlette/formparsers.py:12
  /usr/local/lib/python3.11/site-packages/starlette/formparsers.py:12: PendingDeprecationWarning: Please use `import python_multipart` instead.
    import multipart

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
25 passed, 1 warning in 5.93s
```

### Wiring smoke — full app imports with the new router/route registered

```
sudo docker run --rm --network none -v <worktree>:/work:ro -w /work/backend ... \
  nivesh/backend:staging python -c "import nidp.services.daas_api.app as m; print(len(m.app.routes))"
-> daas app import OK, routes: 186

sudo docker run --rm -v <worktree>:/work:ro -w /work/backend ... nivesh/backend:staging \
  python -c "import server; print(len(server.app.routes), any(r.path=='/api/markets/evidence/post-disclosure-study' for r in server.app.routes))"
-> server.py import OK, app routes: 728
-> evidence route present: True
```

Both the DaaS app and the full app-side `server.py` import cleanly with the new router/route wired
in — a real, not merely syntactic, proof the registration is correct (FastAPI resolves all
decorators, dependencies and imports at import time).

### Backend syntax

```
python -c "import ast; [ast.parse(open(f).read(), filename=f) for f in [...]]" -> syntax OK for all 4 files
```
(Superseded in strength by the full import above; kept as the docs/BUILD_AND_DEPLOYMENT.md-listed check.)

## UI / Playwright Tests

### New spec

Command (repo mounted rw for the `.auth` write; `node_modules` and the Chromium 1223 build in
docker volumes per `provider-credentials-and-test-harness.md`):

```
sudo docker run --rm --network none \
  -v /home/deploy/nivesh.ai/.claude/worktrees/agent-aac67438b8736b3f1/frontend-v5:/app \
  -v evidence-fe-node-modules:/app/node_modules \
  -v pw-browsers-1223:/pw -e PLAYWRIGHT_BROWSERS_PATH=/pw \
  -w /app mcr.microsoft.com/playwright:v1.47.0-jammy \
  bash -lc 'npx playwright test e2e/tests/copilot-app-desk-evidence-validation.spec.ts --project=desktop-chrome'
```

Real output:

```
Running 11 tests using 2 workers
  ✓ auth-setup: inject dark-theme localStorage (6.0s)
  ✓ EV-1: INCONCLUSIVE is the loud, primary state of the panel (3.5s)
  ✓ EV-2: the primary horizon shows the mean spread WITH its 95% CI, blocks and positive quarters (3.4s)
  ✓ EV-3: the secondary horizons (5, 60) are shown, each with its own CI (2.4s)
  ✓ EV-4: the cost-adjusted figure is shown explicitly, not hidden (2.4s)
  ✓ EV-5: 2026-09-30 renders as its own explicit field, never a zero and never folded in (2.3s)
  ✓ EV-6: no Nifty 500 TRI row or benchmark figure appears anywhere on the panel (2.2s)
  ✓ EV-7: nothing on the panel reads as a score, a rank or a buy/sell signal (2.2s)
  ✓ EV-8: the study contract fields (period, quarters, horizon, eligible pairs) are on screen (2.3s)
  ✓ EV-9: a failing data platform is an error state, never a fabricated study (4.9s)
  ✓ EV-10: the pre-registration hash is shown for provenance (2.4s)
  11 passed (25.2s)
```

### Regression — existing Smart Money tab spec, unmodified except the mount

Command: same recipe, `e2e/tests/copilot-app-desk-smart-money.spec.ts --project=desktop-chrome`.

Real output (tail):

```
  29 passed (54.3s)
  1 failed: TC-F3: the disclosure date is shown, not the compute date
    Expected pattern: /Disclosed\s+0?1 Sept? 2026\s+·\s+51d ago/
    Received: "...Disclosed 1 Sept 2026 · 52d ago..."
```

**TC-F3 is a pre-existing, unrelated flake**, not caused by this change: it hardcodes "51d ago"
from a fixed fixture date (2026-09-01) against `new Date()` with no clock mocking, so the assertion
drifts by one day with the real calendar (today is 2026-10-23; 2026-09-01→2026-10-23 is 52 days,
not 51). It is purely a day-count string comparison unrelated to this diff: this branch touches only
`app.py`, `server.py`, `SmartMoneyTab.tsx` (one import + a 6-line mount of
`<EvidenceValidationPanel />`, both additive and after the existing content), plus new files. No
date-arithmetic code was touched. The other 29 of 30 cases in that spec pass unchanged, which is the
real regression evidence: the mount does not break the host tab. My own panel correctly renders its
own `ErrorBlock` state in this spec's run (its endpoint is unmocked there), proving panel-level
failure isolation (TC-F24's pattern, reused) rather than taking the screen down.

### tsc --noEmit

```
sudo docker run --rm -v <worktree>/frontend-v5:/app -v evidence-fe-node-modules:/app/node_modules \
  -w /app mcr.microsoft.com/playwright:v1.47.0-jammy bash -lc 'npx tsc --noEmit -p tsconfig.json'
-> exits 0, no diagnostics
```

## Data Correctness

This screen has **no live data to query** by design: it reports a FROZEN, pre-registered,
hash-guarded study (`study.py` re-hashes `preregistration.json` and aborts on any mismatch before
touching the warehouse), already run once on 2026-10-23 and recorded verbatim in
`test_reports/SHP_POST_DISCLOSURE_FORWARD_STUDY_20261023.md`. "Data correctness" here means: every
number this screen serves is byte-traceable to that real, already-run output — not a fresh SQL
query I ran against the warehouse.

Cross-check performed this session (`git show study/post-disclosure-forward-returns:...` — read
only, branch never merged or copied):

| Field served | Value in `evidence_validation.py` | Source line in the real report |
|---|---|---|
| `study_period` | 2024-03-31 → 2026-06-30 | §3.3 table / §4 "Formation quarters : 10 (2024-03-31 .. 2026-06-30)" |
| `quarters` | 10 | same line |
| `review_floor_blocks` | 12 | same line: "Review floor : 12 independent blocks" |
| `eligible_population` | 1255 | §4 "Eligible after screens : 1255" |
| `eligible_primary_estimand_n` | 1248 | §4 "Eligible with FII+DII pair (primary) : 1248" |
| horizon 20 `mean_spread_pp`/CI/blocks/positive | +1.0749 / [-0.8673,+2.9054] / 10 / 6 | §4.1 "mean spread +1.0749 pp \| 95% CI [-0.8673, +2.9054] pp \| blocks 10 \| positive quarters 6/10" |
| horizon 20 `net_of_cost_pp` | +0.0875 | same line: "net of 0.9874 pp costs +0.0875 pp" |
| horizon 5 row | -0.0007 / [-1.1932,+1.1074] / 10 / 5 / -0.9881 | §4.1 horizon-5 summary line |
| horizon 60 row | -0.7468 / [-5.6316,+3.6992] / 10 / 5 / -1.7342 | §4.1 horizon-60 summary line |
| `preregistration_sha256` | 5452b055...734ec7071 | report header "Pre-registration SHA-256" + `study.py`'s `PREREG_SHA256` |
| `not_yet_eligible.quarter` | 2026-09-30 | §3.3: "2026-09-30 — the only quarter with a real publication timestamp — has no entry session at all" |
| benchmark absence | no benchmark field anywhere | §3.2: Nifty 500 index_eod is PRICE-only, 25.4% of 2025 covered, 375-day max gap — matches the orchestrator's brief exactly |

**Reconciliation against the orchestrator's brief:** every number given in the task brief (study
period, 10 quarters, eligible 1,255, primary horizon 20, 20-session spread +1.0749pp / CI
[-0.8673,+2.9054] / 10 blocks / 6-of-10 positive, net-of-cost +0.0875pp, Sep-2026 not-yet-eligible,
no TRI) was independently re-derived from the real report text in this session (not copied from the
brief) and **matches exactly, with no discrepancy found.** I trust the report
(`test_reports/SHP_POST_DISCLOSURE_FORWARD_STUDY_20261023.md`) as ground truth because it is the
actual, already-run script output with its own hand-verification section (§4.5), not a summary; the
orchestrator's brief turned out to be a correct transcription of it.

## Inputs required from user

- none

## Verdict: PASS
