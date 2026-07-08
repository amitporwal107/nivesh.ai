# Functionality Verification — In-chat guided copilot onboarding

**Change:** Bring the copilot tour into the real chat as a conversational, stateful
onboarding. On a fresh chat the copilot greets the user, explains in plain English how it
works, then offers its catalog of jobs; picking one hands off to the REAL copilot
(`submitMessage`) so the guided steps are canned product copy but the answer is live.
Mirrors the `/copilot` tour's content. No new backend.

**Area:** frontend `frontend-v5/src` (chat page) → verified with Playwright.

**Files**
- `src/pages/Chat/CopilotOnboarding.tsx` (new) — the conversational stepper (welcome → how-I-think → pick-a-job), 10 workflows + 4 goal chips.
- `src/pages/Chat/index.tsx` — first-visit auto-open (localStorage-gated; skipped on `?q=`/`?seed=` deep-links or an existing conversation), a "Take the tour" launcher chip, and the handoff `onLaunch → submitMessage`.
- `e2e/tests/copilot-onboarding.spec.ts` (new) — the test cases below.

## Test cases (authored before implementation)

| # | Case | Expected |
|---|------|----------|
| 1 | Fresh chat | onboarding auto-opens (welcome bubble) |
| 2-3 | Step through | "Show me" → how-I-think; "Next" → job chips (Portfolio health review, Tax-loss harvesting…) |
| 4 | Pick a workflow | POSTs `/api/chat/stream` with `message = "What's the one thing I should fix first?"` (real copilot invoked); onboarding closes |
| 5-6 | Dismiss / re-open | "Skip" closes it; "Take the tour" launcher re-opens it |

## How run (real commands)

```
$ npx tsc --noEmit               # EXIT 0
$ VITE_BASE=/v5/ npx vite build  # ✓ built in 57.53s (EXIT 0)
$ VITE_BASE=/v5/ npx vite preview --port 5195 --strictPort
$ PW_BASE_URL=http://localhost:5195 npx playwright test e2e/tests/copilot-onboarding.spec.ts --config pw.copilot.config.ts
```

The chat page is auth-gated, so the suite answers `/api/auth/me` with a 200 (logged-in
user) to render it; the onboarding itself is client-side. The handoff is asserted
mock-independently by intercepting the outgoing `POST /api/chat/stream` and checking its
body carries the workflow's prompt.

## Real output

```
Running 4 tests using 1 worker

  ✓  1 › 1 · auto-opens on a fresh chat (2.0s)
  ✓  2 › 2-3 · steps through welcome → how-I-think → pick-a-job (1.9s)
  ✓  3 › 4 · picking a workflow hands off to the real copilot (2.0s)
  ✓  4 › 5-6 · dismiss then re-open via the launcher chip (2.0s)

  4 passed (11.5s)
```

Handoff request captured live (real browser drive):
`POST /api/chat/stream  body={"message":"What's the one thing I should fix first?","session_id":"sid"}`

## Visual check

Rendered on the chat landing (dark): "GUIDED TOUR" header + Skip, न-avatar bubbles for
welcome / how-I-think / pick-a-job, the 10 workflow chips and 4 "start from a goal" chips,
and the new "Take the tour" launcher in the "My Portfolio Insights" row — all matching the
chat's existing chip/bubble styling.

## Notes / limits

- **UNVERIFIED (by design):** the signed-in end-to-end answer from the real
  `/api/chat/stream` on a live portfolio was not exercised (auth-gated; needs a session
  token). The onboarding is proven to *invoke* the real send with the correct prompt; the
  streamed answer is the pre-existing chat path, unchanged.
- Built against a production build (base `/v5/`), the surface that deploys to staging.

## Verdict: PASS
