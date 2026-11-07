# SPT UI — Trade Desk › Paper Trading: Opportunities · Analytics · Settings — functionality report

Builder F1, 5 Nov 2026. Worktree `/home/deploy/nivesh-wt-spt-ui` (branch `feat/spt-ui`), uncommitted (the integrator commits).

## Test cases

Authored before the build: `test_reports/spt_ui_paper_TESTCASES.md` (SPT-UI-P-01 … P-28).

## Files

- `frontend-v5/src/pages/CopilotApp/screens/tradingdesk/tabs/trade-desk/spt-api.ts`: types, tolerant parsers, react-query hooks
- `SptOpportunities.tsx`, `SptAnalytics.tsx`, `SptSettings.tsx`, `spt-parts.tsx` (same folder)
- `TradeDeskTab.tsx`: the three `sub` cases
- `frontend-v5/e2e/tests/copilot-app-desk-spt-paper.spec.ts`: 24 tests; every body is labelled `MOCK — not real data`
- `copilot-app-desk-pnl.spec.ts` (TC-032) and `copilot-app-desk-trade-desk.spec.ts` (NV-1): the expected Paper Trading chip list
  now has the three new labels. This is a one-line change in each, caused by the integrator's `desk-nav.ts` change.

## Results

These are real Playwright results, against mocked APIs and the production build. Full output:
`test_reports/spt_ui_paper_pw.txt`.

```
TSC_EXIT=0
BUILD_EXIT=0
  78 passed (1.5m)
PW_EXIT=0
```

The 78 tests break down as:
- 24 SPT-UI-P cases
- 54 existing cases from `copilot-app-desk-pnl`, `-pnl-exits`, `-trade-desk` and `-compliance-wording`

| Case IDs | Result |
|---|---|
| P-01 … P-27 | pass (the P-28 regression set is green) |

## Not verified (UNVERIFIED)

- **Real backend:** I did not call it. The SPT routes are not deployed to staging from this worktree, and the backend lives in
  `feat/spt-integration`. These tests prove that the screens render the code-read shapes and send the right requests. They do
  NOT prove that the live API answers those shapes, or that real data shows correctly.
- **Next step:** the integrator opens the three sub-views against staging after the deploy, and checks them with a real
  session: an approval-mode account, a config PUT, and the admin routes.

## Verdict: PASS (mocked UI layer only; real-API check pending, see above)
