# OVERRIDE — Copilot chat: an advisor's own portfolio in the investor and trader personas (branch `fix/copilot-persona-own-portfolio`)

REASON: The fix is not on staging until its PR is merged into `dev`, and the one check that proves it end to end — an advisor in the Trader persona clicking a broker position and getting an answer with levels — needs the user's own signed-in session, which I do not have. Everything short of that is verified below (unit tests, typecheck, mocked Playwright, and a read-only run of the staging engine on the exact questions). To finish: merge the PR, then click the COLPAL position on the Trader desk on staging.

- **Date:** 2026-10-14
- **Author:** Claude (full-stack developer + QA)
- **Status of the work:** IN PROGRESS — code complete and tested off staging; staging check owed after merge.
- **Changed areas:** backend routes: yes (`backend/routes/chat.py`) · frontend src: yes (4 files)

## What was wrong (seen on staging, 2026-10-14 06:30–06:32 IST)
An advisor (workspace type `ADVISORY`) in the **Trader** persona clicked the COLPAL row of the broker positions block. The app asked: "Show the COLPAL chart with support and resistance. My broker account has an open position of 550 at an average of ₹35.88." The answer was "I can't chart COLPAL … The workspace has no clients linked", with no tool step.

1. `/api/chat/stream` chose the path from the workspace type alone. For an advisor it used the cross-client book unless the text matched a research phrase; this text matched none (`_is_research_tool_intent` → `False`, checked in the staging container). The book path has no tools.
2. The row was a 1,760 put option (premium ₹35.88), but the question did not say so, so even the tool-using engine compared ₹35.88 with the share price (₹1,767) and refused to reason about the position.

## The rule (user, 2026-10-14)
"The advisor portfolio is uploaded...he will have access to his own holdings and positions for investor and trader persona."

## Test cases (written before the fix)
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | backend | advisor + persona `trader` / `investor` (any case, padded) | unit | not the client book | PASS |
| TC-2 | backend | advisor + no persona, `advisor`, unknown value, non-string | unit | client book, as before | PASS |
| TC-3 | backend | non-advisor + any persona | unit | never the client book | PASS |
| TC-4 | backend | `/chat/stream`, advisor, persona `trader` / `investor`, the chart question | route (fakes) | reads the caller's own holdings, not the book | PASS |
| TC-5 | backend | `/chat/stream`, advisor, persona `advisor` / none / unknown | route (fakes) | reads the book, not own holdings | PASS |
| TC-6 | frontend | position row click in the Trader persona | e2e (mocked) | request body carries `persona: "trader"` | PASS |
| TC-7 | frontend | question text for a share, a short, an option, a future | e2e (mocked) | option names strike, side, expiry and "average premium"; future names itself and expiry; share unchanged | PASS |
| TC-8 | engine | the new option question on the staging engine (read-only, nothing saved) | live engine | levels returned; ₹35.88 read as the option premium | PASS |
| TC-9 | staging | advisor in Trader persona clicks the COLPAL position | live UI | answer with levels and tool/route shown | NOT RUN — needs merge + the user's session |

## Evidence
- **Before the fix**, the new tests: `20 failed, 4 passed` (the 4 are the cases that assert today's behaviour).
- **After**: `python -m pytest tests/test_chat_persona_routing.py -q -p no:cacheprovider` → `24 passed, 1 warning in 7.35s`.
- With two broker-hub suites alongside: `199 passed, 1 warning in 9.93s`; `import server` works and `/api/chat/stream` is registered.
- **Typecheck:** `npx tsc --noEmit -p tsconfig.json` → clean.
- **Playwright (mocked APIs), trader spec:** `17 passed (11.3s)`, including the new case.
- **Playwright, whole Copilot app suite:** `316 passed (3.6m)`, `23 skipped`, 0 failed.
- **Staging engine, read-only, the user's account** (the investor path, which this fix routes to):
  - old wording → `routed to ('stock_analyst', 'COLPAL', 0.92) | widget: instrument_detail`; levels Resistance ₹1,918, 50-day average ₹1,881, price ₹1,767, support ₹1,716; but "an average of ₹35.88 is far from COLPAL's current price … I can't reconcile the two".
  - new option wording → same levels, and "Breakeven at expiry: 1,760 − 35.88 = ₹1,724.12 … Total premium paid: ₹19,734, which is your maximum loss … the put is ₹7 out of the money."

## Not verified
- TC-9: nothing of this is on staging yet.
- The engine answers with levels in text and an instrument card. It says "I can't draw a chart in this chat": a drawn chart is not something this fix adds.
- `POST /api/chat/send` (older dock) takes no persona and is unchanged.
- For Zerodha-style rows the position's symbol is the contract's trading symbol (e.g. `NIFTY26OCT25000CE`), which the engine may not resolve to the underlying; ICICI rows carry the underlying.

- **This is not a pass.** Resolve before merge to `main`.
