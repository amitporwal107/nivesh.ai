# Screener + Watchlist in the Copilot — test cases (authored before the code of each slice)

Plan: `docs/plans_20261031/SCREENER_WATCHLIST_PLAN.md`. Decisions taken as the plan recommends them (owner: "work on the screener and
watchlist first", "complete it", 1 Nov 2026): two Trader rail rows; chat adds only through a confirmation card; 100 stocks per list;
deterministic parser first, LLM only for what it leaves unmapped; list writes blocked while an advisor views a client; no fund-house
metrics in chat screens.

Every UI case below runs on MOCKED API responses (spec titles say `MOCK — not real data`) unless a row says STAGING.

## W1 — Trader rail rows (`e2e/tests/copilot-app-trader-rail.spec.ts`)
| Id | Case | Expected |
|---|---|---|
| RL-1 | Trader mode rail | Smart trading desk, Screener, Watchlists in that order; Stock research and Sector rotation absent |
| RL-2 | press Screener | URL `?tab=market&view=screener`, Screener panel visible, only that row lit |
| RL-3 | press Watchlists | URL `?tab=trade&view=watchlists`, Watchlists panel visible, only that row lit |
| RL-4 | on `?tab=risk&view=limits` | only the desk row lit; going Screener → desk row re-lights the desk row |
| RL-5 | old route `/app/tool/screener` in Trader; Investor rail | redirects to the desk view with Screener lit; Investor keeps Screener + "Watchlist & alerts", no "Watchlists" |
| RL-6 | phone 390 px | drawer lists both rows; pressing one navigates and closes the drawer |

## W2 — server (`backend/tests/test_watchlists.py`, `test_screeners_run.py`)
| Id | Case | Expected |
|---|---|---|
| B-1 | 100 symbols in one call | all added in ONE guarded write (`$push $each`); order kept; repeat call adds 0, `already` = all |
| B-2 | 101 in one request / 99 + 2 | 101 → 422; the one that fits is added, the other refused `list_full` by name; never > 100 |
| B-3 | mixed request | trimmed / upper-cased / de-duplicated; already-there, unknown (`not_in_instrument_list`), malformed (`invalid_symbol`) reported separately |
| B-4 | empty / missing `symbols` | 422; a malformed symbol is never looked up |
| B-5 | another user's list, missing list | 404, nothing written |
| B-6 | instrument list cannot be checked | 503 "nothing was added", list unchanged |
| B-7 | look-ups | concurrent but never above the module's 8; only for stocks not already in the list |
| B-8 | lost race | read again, redo, no symbol twice, `already` names the stock the other request added |
| B-9 | not signed in | 401 |
| B-10 | advisor viewing a client | 403 on create, rename, delete, add, bulk add, remove; stored data unchanged; reads still 200 |
| S-1 | screen moved to `services/screener_run.py` | `test_screeners_run.py` unchanged and green (80 passed, 1 skipped) |
| M-1..3 | mutations: guard off / 100-limit off / 503 stop off | each fails exactly its test |

## W3 — "Add to a list" on the Screener page (`e2e/tests/copilot-app-screener-add.spec.ts`)
| Id | Case | Expected |
|---|---|---|
| AL-1 | results table | each row has a checkbox; pressing it does not open the stock panel, pressing the row still does |
| AL-2 | nothing selected | the confirm button is disabled; NO write call is made by loading, running, selecting or choosing a list |
| AL-3 | select 3, pick a list, confirm | exactly one `POST /api/watchlists/{id}/symbols/bulk` with those symbols in table order; result "Added 3" and a link to My lists |
| AL-4 | "New list…" | creates the list (`POST /api/watchlists {name}`), then one bulk add; default name `Screen · <rules> · <date>` ≤ 60 chars; a 409 name clash shows the sentence and adds nothing |
| AL-5 | "Select all" on > 100 matches | selects the first 100 in the run's order (largest market cap first) and says so; count is 100 |
| AL-6 | list with less room than selected | says how many fit before the press |
| AL-7 | answer with already / refused | "N were already there"; each refused stock by name with its reason |
| AL-8 | server says 403 (advisor viewing a client) or 503 | the server's sentence is shown; no success line |
| AL-9 | double press | one POST; the button is disabled while it runs |
| AL-10 | label | "Keep this screen (re-runs daily)" on the rules saver; the Add bar says it is a fixed snapshot; other users of `SaveAsWatchlist` unchanged |
| AL-11 | phone 390 px | no sideways scroll; confirm button ≥ 44 px high |
| AL-12 | a new run | the selection is cleared |
