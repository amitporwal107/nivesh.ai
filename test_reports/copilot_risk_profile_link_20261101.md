# "Set up your risk profile" opens the screen where the profile is edited — 2026-11-01

Scope: frontend only, two lines. No backend, API or data change.

## The defect (found while reporting #431, not fixed there)
The notice action `set_risk_profile` on the "How much should I risk?" answer went to
`trader/desk?tab=risk&view=limits`. That view (`LimitsView.tsx`) only shows each limit with used and left.
The profile's change form (`risk-profile-form`) lives in Risk Desk › Controls & profile (`view=controls`,
`ControlsView.tsx`). A user with no profile was sent to a screen with nothing to set up.

## Change
- `frontend-v5/src/components/chat/visual/blocks/Simple.tsx`: `set_risk_profile` → `trader/desk?tab=risk&view=controls`.
- `frontend-v5/e2e/tests/copilot-app-risk-profile.spec.ts` RP-2: asserts the `view=controls` URL.

## Test cases (authored before the edit)
| Id | Case | Expected |
|---|---|---|
| RP-1 | answer with no saved profile | no stale warning, defaults called defaults, the ask comes first |
| RP-2 | click "Set up your risk profile" | URL is `/app/trader/desk?tab=risk&view=controls` |
| RD-10 | open `?tab=risk&view=controls` | `risk-profile-form` is present; no PUT without a reason; a tightening is sent as {changes, reason} |
| RD-1..19, RC-1..15 | rest of the Risk Desk | unchanged |

## Real output (this session, worktree on origin/dev + the two edits)
```
TSC_EXIT=0
...
  ✓  39 [copilot-app] › e2e/tests/copilot-app-risk-profile.spec.ts:80:3 › ... › RP-2 the action opens the Risk Desk's Controls & profile, where the profile is edited (1.1s)
  ✓  28 [copilot-app] › e2e/tests/copilot-app-desk-risk-desk.spec.ts:435:3 › ... › RD-10 the profile form: the rule; no PUT without a reason; a tightening is sent as {changes, reason} and logged (1.4s)
  41 passed (31.2s)
```
Command: vite production build + vite preview + Playwright 1.47 in docker, specs `copilot-app-risk-profile`,
`copilot-app-desk-risk-controls`, `copilot-app-desk-risk-desk`. The API responses in these specs are mocks
(labelled "MOCK — not real data" in the spec titles); they prove the link target and that the destination view
holds the form, not what a real staging session returns.

## UNVERIFIED
- Not run against the deployed staging app: needs this branch merged, the frontend image rebuilt, and a signed-in session.
- Whether the form is editable for a non-admin account with no saved profile on real data (the mocked RD-10 uses an account that can tighten).

## Verdict: PASS
