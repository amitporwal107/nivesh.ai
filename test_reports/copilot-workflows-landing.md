# Functionality Verification — Copilot chat workflow landing (Phase 1)

**Change:** Replace the conversational in-chat onboarding with a persona-aware **workflow
landing** in the copilot chat (`/v5/chat`):
- **Default** = a list of workflows (investor 10 / advisor 9), each row runs that workflow
  on the user's real portfolio (→ `submitMessage(prompt)`).
- **"Guided tour"** button = a Next/Back **stepper** that opens the full workflow tiles one
  at a time (ASK → ANALYZE → DECIDE → ACT), each with a "Run this on my portfolio" action.
Persona from `useMe().workspaceType === "ADVISORY"`. Rendered as a scoped `.copilot-tour`
dark island (per the "keep dark tiles" decision).

**Scope note (honesty):** Phase 1 delivers the structure + navigation. The tile stage copy
is an honest *description* of each workflow (not fabricated portfolio numbers); the answer
that streams when you click "Run" is **live** (the real copilot on your portfolio). Live
*prefill* of tile headline metrics (real health score, harvestable ₹, etc.) is **Phase 1b**;
the 2 data-blocked tiles ("What moved today", advisor "idle cash") are Phase 3.

**Files**
- `src/pages/Chat/workflowCatalog.ts` (new) — single source of truth (investor 10 + advisor 9: key, title, sub, prompt, tag, stages).
- `src/pages/Chat/CopilotWorkflows.tsx` (new) — persona list + guided-tour stepper (responsive 4-stage grid, Next/Back, progress dots, keyboard, a11y).
- `src/pages/Chat/index.tsx` — removed the onboarding (import, state, auto-open effect, render block, "Take the tour" chip); render `<CopilotWorkflows>` whenever `messages.length === 0`.
- `src/pages/Chat/CopilotOnboarding.tsx` + `e2e/tests/copilot-onboarding.spec.ts` — **deleted** (superseded); catalog extracted first so nothing is lost.
- `e2e/tests/copilot-workflows.spec.ts` (new) — the cases below.

## Test cases

| # | Persona | Case | Expected |
|---|---------|------|----------|
| 1 | investor | default landing | workflow list, `data-role="investor"`, shows "Portfolio health review" + "Too many funds?" |
| 2 | investor | click a row | POSTs `/api/chat/stream` with that workflow's prompt |
| 3 | investor | guided tour | stepper opens; ASK/ANALYZE/DECIDE/ACT visible; Next → wf 02; "Run" sends its prompt |
| 4 | advisor | default | `data-role="advisor"`, shows "At-risk & churn"/"AUM & book health", NOT "Portfolio health review" |
| 5 | advisor | click a row | POSTs `/api/chat/stream` with the book-level prompt ("Which clients might leave?") |

## Real output (production build, base `/v5/`)

```
$ npx tsc --noEmit                          # EXIT 0
$ VITE_BASE=/v5/ npx vite build             # ✓ built (EXIT 0)
$ PW_BASE_URL=http://localhost:5203 npx playwright test e2e/tests/copilot-workflows.spec.ts --config pw.copilot.config.ts

  ✓  1 › investor › default landing is the investor workflow list (2.0s)
  ✓  2 › investor › clicking a workflow row runs it on the portfolio (1.6s)
  ✓  3 › investor › guided tour steps through tiles and Run sends the prompt (2.2s)
  ✓  4 › advisor › advisor sees the book workflows, not investor ones (1.6s)
  ✓  5 › advisor › advisor row runs a book-level prompt (1.1s)

  5 passed
```

## Visual check
Investor: dark-island list of the 10 workflows + "Guided tour"; stepper shows one workflow
with the 4 stages in a 2×2 grid (fits the chat column — the tour's fixed 4-wide filmstrip
would overflow) + Run/Back/Next + progress dots. Advisor: the 9 book workflows, advisor
nav in the sidebar (persona correct). "My Portfolio Insights" chips preserved below.

## Notes / limits
- **UNVERIFIED on staging** until this deploys — the list/stepper are client-side and were
  proven against the production build; the "Run" handoff uses the pre-existing live
  `/api/chat/stream`. Will re-run on staging both modes after deploy.
- Phase 1b (live tile prefill) + Phase 2 (advisor feeds) + Phase 3 (2 blocked feeds) follow.

## Verdict: PASS
