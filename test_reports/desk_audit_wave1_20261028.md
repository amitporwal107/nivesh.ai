# Functionality Verification Report: desk audit wave 1 (F1, B1, B3)

- **Branch:** fix/desk-audit-wave1, merged with origin/dev 3a7b6487 (merge commit 379ca339)
- **Date:** 2026-10-28
- **Author:** Claude (full-stack developer + QA)
- **Environment:** Docker on the app VM. Backend tests ran with `--network none`. Playwright used mocked APIs.
- **Changed areas:** backend routes/services: yes · frontend src: yes · data platform (daas_api ownership router): yes
- **Test cases:** `test_reports/desk_audit_wave1_TESTCASES.md` (written before the fixes)

## Backend (pytest, nivesh/backend:staging image, `--network none`)
- **Command:** `python -m pytest -q` over 13 files: test_desk_audit_wave1_b1, test_desk_audit_wave1_b3, test_desk_redesign_routes, test_markets_evidence_routes, test_markets_home_daas, test_ownership_reaction, test_plan_sizing, test_risk_controls, test_risk_gate, test_risk_gate_ai_trader, test_risk_gate_desk_journal, test_strategy_plan, test_strategy_plan_templates_route.
- **Output:** `319 passed, 2 warnings in 27.97s`. This is on the branch after merging dev.
- **Full CI allowlist** (agent run, before the dev merge): `3 failed, 6766 passed, 28 skipped`.
  - The 3 failures are test_cas_api_client::test_sandbox_parse_and_map, test_cas_api_client::test_convenience_helper_returns_list and test_nidp_stamp_broadcast_at::test_run_commits_in_batches.
  - All three need the network and fail the same way on base commit 48556220.

## Frontend: Playwright, mocked APIs
- **tsc:** clean. **Build:** `✓ built in` (vite production build).
- **New spec** `copilot-app-desk-audit-wave1.spec.ts` (W-1…W-10): 9 passed, 0 failed.
- **Every `copilot-app-desk*` spec (34 files) at `--workers=3`:** `36 failed, 27 skipped, 762 passed (14.2m)`.
  - **35 of the 36 fail on dev too.** The same three spec files run on a clean copy of origin/dev 3a7b6487 gave `35 failed, 24 passed`. The failures are in `copilot-app-desk-strategy-graphs` (payoff-svg not found) and `copilot-app-desk-strategy-ideas` (SI-6, SI-7, SI-7b). Comparing the failure lists by file and line shows no difference except the next item.
  - **One appears only on the branch:** `copilot-app-desk-widgets` TC-1 ("total widgets > 8", received 3). It counts widgets after a fixed 600 ms wait. Re-run alone with `--repeat-each=3`, it gave `3 passed`. The branch's only widget change removes the section number from the title text and does not change which widgets render.
- **Earlier agent run, before the dev merge:** 533 passed and 2 failed.
  - UI-1 asserted the old evidence text. The spec was fixed and committed in `test(desk): UI-1 expects the readable regime evidence text`).
  - §6.7 alerts timed out under load.
  - Re-run alone with `--repeat-each=2`, both gave `4 passed`.

## Data correctness (staging)
- Not run. The branch is not merged, and staging runs dev.
- The ownership fix is in the data platform (`backend/nidp/services/daas_api/routers/ownership.py`). It takes effect on staging only after the NIDP VM's dev checkout is refreshed and `daas-api` is restarted.

## Inputs required from user
- The merge of the PR. Then a staging check:
  - Smart Money ownership reaction answers 200, not 502;
  - the idea scorecard has no FileNotFoundError row;
  - the NIFTY tile shows a day change;
  - no "pick" wording anywhere;
  - Strategy that fits is sized to the account.

## Verdict: BLOCKED
The mocked UI and the backend unit tests pass, and the branch fails nothing that dev doesn't also fail. The staging check after merge is still open.
