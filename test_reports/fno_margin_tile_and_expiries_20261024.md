# F&O Lab: margin tile + three-month expiry selection (2026-10-24)

Branch fix/margin-tile (from origin/dev). Frontend only: FnoBuilder.tsx, FnoTab.tsx, copilot-app-desk-lab.spec.ts.

## Cases
- TC-9 payoff summary margin tile shows the calculator figure and source (mocked /api/fno/margin 200); dash + reason on 503.
- TC-EXP expiry row: Weekly / Monthly / Next / Far + date list; futures strip per contract selects its expiry; builder expiry buttons (<=95 days) request the chain for the picked expiry.

## Real results (this session, mocked APIs, production build)
- tsc --noEmit: exit 0; vite build: exit 0
- npx playwright test --config pw.copilot-app.config.ts (all copilot-app specs): 921 passed, 42 skipped, 0 failed
- Backend margin route on deployed staging container (calculation run in-container, no creds printed): required_margin 20908, initial_margin 22668, charges total 53.2, source Zerodha margin calculator, as_of 2026-10-24.

## UNVERIFIED
- Deployed UI not checked after this change (not yet deployed); no staging session token this turn.
- Margin 20,908 vs max loss 4,800 for the put spread is the broker calculator's figure; not reconciled.

## Verdict: PASS
