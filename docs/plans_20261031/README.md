# Copilot plans, 31 Oct 2026 (refreshed 1 Nov)

Two plans, written for the owner first (plain words, then the decisions) and for the engineers who build them (verified file references,
numbered slices). Nothing here is built. The Risk Management plan was dropped at the owner's request and is not part of this set.

| Order | Plan | What it gives | First slice that can start now |
|---|---|---|---|
| 1 | [SCREENER_WATCHLIST_PLAN.md](SCREENER_WATCHLIST_PLAN.md) | Screener and Watchlists reachable from the Trader menu; add screen results to "My lists"; screen and add from chat with a confirmation card | W1 (menu rows) and W2 (server: shared screen service, bulk add, advisor guard) |
| 2 | [STRATEGY_BUILDER_CHAT_PLAN.md](STRATEGY_BUILDER_CHAT_PLAN.md) | Suggest, edit, save and record multi-leg strategies from chat; the "Plan a bearish trade for UNIONBANK" answer; cash-stock back-test; options replay on 13 months | SB1 (read-only suggestions and the UNIONBANK answer) |

## Why this order, and what depends on what

- **Plan 1 first.** It is smaller, almost all of it exists in pieces, and its slice W5 introduces the one new chat pattern both plans need: a
  block that proposes a write and a confirmation card that performs it from the user's own browser session. Plan 2's save and record steps (SB4)
  reuse that card instead of inventing another.
- **Plan 2's first slice does not wait for Plan 1.** SB1 and SB2 are read-only. SB3 onward needs a place to keep drafts; SB4 needs W5's card (or
  starts with a link to the existing paper ticket).
- **Both plans add chat intents to `services/copilot_visual`** (16 on dev). Each new intent touches the same lists (`INTENTS`, `AGENT_FOR`,
  `BUILDERS`, `payload.validate`, a suggestions template, the spec's `INTENTS`, a real staging capture), so build them one at a time, not in parallel.
  Open PRs #435 and #436 edit the open-trades and daily-review answers in the same files: merge them first or expect small conflicts.
- **Data limit that shapes Plan 2:** the warehouse holds option prices for 13 months (1 Oct 2025 to 30 Oct 2026, end of day). Releases A and B of
  Plan 2 do not depend on it; release C does, and says so on screen.

## The decision that matters most in each plan

| Plan | Decision | Recommendation |
|---|---|---|
| Screener and Watchlist | May the chat add stocks to a list, and where does the Trader menu point (decisions 1 and 2 of the plan)? | Yes, only through a confirmation card the user presses; two Trader menu rows that open the existing desk views |
| Strategy builder in chat | First release scope and whether to buy history (decisions 1 and 2) | Release A first (suggest, edit, save, paper); no data purchase; get TrueData's written position on simulation use before any use of its data |

All numbers in the plans were measured read-only on staging on 31 Oct 2026; each plan lists what it did not verify.
