# SOP and KRA — Tech Support agent (autodesk-ts-v1)

Written 7 Nov 2026 by Account 2. Review board item R16. Status: **draft for the owner's review.** Sections marked *Built* describe the code in `backend/autodesk/agents/tech_support.py` as read on 7 Nov. Sections marked *Proposed* are not built; each points to the board item that would build it.

## 1. Role
Reliability. Tells the desk whether it is safe to take new risk today, and why not when it is not. It is deterministic code (kind `DETERMINISTIC`): no model, no judgement calls. It never creates signals, approves or executes (`prohibited` in its descriptor).

## 2. Key results (KRA)
| # | Result | Measure | State |
|---|---|---|---|
| K1 | A pre-market verdict exists before 08:45 IST on every trading day | one `premarket-report-v1` per session date | Built (check) / R8 open: nothing yet proves who starts the cycle |
| K2 | The verdict is never more optimistic than the data | BLOCKED when the previous session's cash data is missing, old or under 500 rows | Built |
| K3 | Every non-READY verdict says which check failed and the data date it saw | `checks[].detail` and `as_of` | Built |
| K4 | A failure reaches a human | Slack alert within a minute of the verdict | Proposed (R12, `testcases_alerts_slack.md`) |
| K5 | The desk stays watched during the session | recurring checks D1–D13 on the board | Proposed (R7, R14) |
| K6 | Post-session data and books are confirmed | checks E1–E10 on the board | Proposed |

## 3. Daily procedure

### 3.1 Pre-market (Built)
Runs as task `PREMARKET_HEALTH_CHECK` in the session cycle (PREMARKET 08:30, SCAN 08:45 IST). Inputs: session date, database answer flag, market view.

| Check | READY when | Otherwise | Effect |
|---|---|---|---|
| `desk_db` | the desk database answered | BLOCKED | whole verdict BLOCKED |
| `cash_eod` | latest cash day is not older than the previous NSE session and has at least 500 rows | BLOCKED (older, too few rows, unreadable, or previous session unknown) | whole verdict BLOCKED |
| `fno_eod` | latest F&O day equals the previous session and has at least 50 underlyings | DEGRADED (other day, too few, unreadable, previous session unknown) | cash only |
| `vix` | India VIX present for the session | DEGRADED | noted; does not block; regime inputs listed as missing |

Verdict and what it allows:
- READY: new risk allowed in cash, futures, options.
- DEGRADED: cash only.
- BLOCKED: nothing new. Existing positions are untouched.

Stale data is never used to make a day look healthy (owner rule). Data for the previous session may be late: cash is visible from 19:30 IST and F&O from 22:45 IST on the session day, so a check run before those times on the next morning's cycle is not the cause of a late-data failure; a feed that did not land is.

### 3.2 During the session (Proposed, board D1–D13)
Recurring checks on quote freshness (120 s rule for live fills), Kite login validity, the cycle clock, queue backlog, stuck workflows, reservations against the ledger, and fill-cutoff times (cash 15:15, F&O 15:30). None is built. Needs R7 (something that watches) and R14 (a health endpoint, requested from Account 1).

### 3.3 Post-session (Proposed, board E1–E10)
After 18:00 IST: end-of-day books balance, ledger sums match positions, events cursors caught up, journal complete, next-day data publication watched.

## 4. When a check fails, is blocked or only partly completes
The per-check plans (what to try, how long, how it clears) are on the Desk Checks Review board and are the source of truth. The rules that never change:

1. **Do not retry into a worse state.** A retry may repeat a read. It never repeats a write that is not idempotent.
2. **Fail closed.** If the agent cannot tell, the answer is the more restrictive one (this is why an unknown previous session gives BLOCKED for cash).
3. **Partial is reported as partial.** A check that read some data and not the rest is DEGRADED or BLOCKED with the counts in its detail, never READY.
4. **One owner per failure.** Each non-READY verdict is raised once (de-duplicated), with the check name, data date seen, since when, what was tried, and what the desk may still do.
5. **Escalate by clock, not by mood.** A BLOCKED verdict still standing at 08:45 IST is raised as critical. The on-call owner is an open decision (board Q4/Q5; alerts go to Slack channel C0CFKMTJNUD once R12 exists).
6. **Clearing is recorded.** A cleared check produces a RESOLVED notice, not silence.

## 5. Boundaries
Tech Support must not:
- place, modify or cancel orders, or hold broker order credentials (the order-path guard test enforces this for the whole desk);
- change a risk limit, a policy, a verdict from another agent or an account's mode;
- write market data or paper with substitute data. Mock data is never used to turn a verdict green;
- write to shared staging databases outside the desk's own tables;
- print or store secrets, tokens or login links.

Agent-written messages avoid the advice words in the owner's list (buy, sell, stop loss, SL, target, entry, exit, accumulate, book profit, upside, price target, recommend, pick).

## 6. Gaps found while writing this (for the owner and Account 1)
- The agent only handles `PREMARKET_HEALTH_CHECK`. K5 and K6 have no agent code yet.
- Nothing in the agent raises an alert; the verdict is stored and shown on a screen only.
- Thresholds (500, 50) are constants in code. Whether they are right for the Nifty 500 and Total Market universes is not checked; if the universe widens, the cash threshold needs a decision.
- The agent file is Account 1's. Any change goes through `REQUEST A2->A1` on the status board.

## 7. Test cases for this SOP
Existing tests for the verdict are in the desk suite (`tests/autodesk`); the SOP adds no code, so it adds no tests. Tests for K4–K6 are the Slack cases AD-AL-01..28 and the board checks, to be written before those parts are built.
