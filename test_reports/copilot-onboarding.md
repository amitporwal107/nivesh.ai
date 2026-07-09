# Functionality Verification — In-chat guided copilot onboarding (role-aware)

**Change:** Bring the copilot tour into the real chat as a conversational, stateful
onboarding. On a fresh chat the copilot greets the user, explains in plain English how it
works, then offers its catalog of jobs; picking one hands off to the REAL copilot
(`submitMessage`) so the guided steps are canned product copy but the answer is live.
**Role-aware:** advisors (`workspace_type === "ADVISORY"`) get the client-book tour +
book-level workflows (matching the copilot's advisor mode); investors get the
personal-portfolio tour. No new backend.

**Area:** frontend `frontend-v5/src` (chat page) → verified with Playwright.

**Files**
- `src/pages/Chat/CopilotOnboarding.tsx` — conversational stepper (welcome → how-I-think → pick-a-job); INVESTOR script (10 workflows + 4 goal chips) and ADVISOR script (9 book workflows); `data-role` reflects which.
- `src/pages/Chat/index.tsx` — first-visit auto-open (localStorage-gated; skipped on `?q=`/`?seed=` or an existing conversation), a "Take the tour" launcher chip, `isAdvisor` from `useMe().data.workspaceType`, and the handoff `onLaunch → submitMessage`.
- `e2e/tests/copilot-onboarding.spec.ts` — the test cases below.

## Test cases (authored before implementation)

| # | Case | Expected |
|---|------|----------|
| 1 | Fresh chat | onboarding auto-opens (welcome bubble) |
| 2-3 | Step through | "Show me" → how-I-think; "Next" → investor job chips |
| 4 | Pick a workflow | POSTs `/api/chat/stream` with `message = "What's the one thing I should fix first?"`; onboarding closes |
| 5-6 | Dismiss / re-open | "Skip" closes; "Take the tour" re-opens |
| 7 | Advisor role | `data-role="advisor"`, copy says "client book" / "your clients' live NIDP data", shows "At-risk & churn"/"Reviews due", NOT "Portfolio health review" |
| 8 | Advisor handoff | picking "At-risk & churn" POSTs `message = "Which clients might leave?"` |

## How run (real commands)

```
$ npx tsc --noEmit               # EXIT 0
$ VITE_BASE=/v5/ npx vite build  # ✓ built (EXIT 0)
$ VITE_BASE=/v5/ npx vite preview --port 5199 --strictPort
$ PW_BASE_URL=http://localhost:5199 npx playwright test e2e/tests/copilot-onboarding.spec.ts --config pw.copilot.config.ts
```

The chat page is auth-gated, so the suite answers `/api/auth/me` with a 200 (investor or
`workspace_type:"ADVISORY"`) to render it. The handoff is asserted mock-independently by
intercepting `POST /api/chat/stream` and checking its body carries the workflow prompt.

## Real output

```
Running 6 tests using 1 worker

  ✓  1 › 1 · auto-opens on a fresh chat (5.4s)
  ✓  2 › 2-3 · steps through welcome → how-I-think → pick-a-job (3.8s)
  ✓  3 › 4 · picking a workflow hands off to the real copilot (5.9s)
  ✓  4 › 5-6 · dismiss then re-open via the launcher chip (2.9s)
  ✓  5 › advisor role › 7 · advisor sees the client-book tour, not the investor one (1.6s)
  ✓  6 › advisor role › 8 · advisor workflow hands off the book-level prompt (2.1s)

  6 passed (26.4s)
```

## Visual check

- Investor: "GUIDED TOUR" + welcome/how/pick bubbles, 10 portfolio workflows + 4 goal chips, "Take the tour" launcher.
- Advisor: copy reads "I read your entire **client book** and tell you who to call first" / "your clients' live NIDP data"; the 9 book workflows (AUM & book health, At-risk & churn, Reviews due, Harvest across the book, Idle cash to deploy, Off-mandate clients, SIP step-ups, Onboarding stuck, Suitability & disclosures); no investor goal chips.

## Related finding (separate from this change)

The "I couldn't retrieve the data needed…" the user hit on "fix first" was investigated
live on staging (with a user session token): `build_dashboard_recommendations` returns 8
recommendations fine, and the exact question reproduced **twice with real answers** — could
not reproduce the error. It is the copilot's rule-4 *transient*-failure fallback ("please
try again"), not a broken path. Not addressed here; a resilience hardening (retry / answer
from partial data) is offered as a follow-up.

## Verdict: PASS
