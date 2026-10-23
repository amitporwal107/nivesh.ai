# F&O Lab index workspace: state history and option-chain OI bars: test cases (authored before implementation)

Ask (user, 2026-10-23): complete the unbuilt parts of the design: for the NIFTY & BANKNIFTY workspace, the last-five-sessions positioning history and the option-chain OI bars.
Backend: GET /api/fno/{symbol}/positioning-history?sessions=N (new, read only). For each of the last weekdays it asks the data platform's /desk/fno-buildup?date=D, accepts the answer only when
its own as_of equals D (a holiday or a missing day is skipped, never filled), finds the symbol in the index rows (or the stock rows), and returns up to N sessions oldest first.
The history is the per-session label, price change % and OI change % of the near-month future (the same rule as the Lab's build-up). It is shown for tracking; the study found no added information in transitions.

| ID | Scenario | Type | Expected |
|----|----------|------|----------|
| TC-1 | the route returns the newest N accepted sessions oldest first, each with date, label, price_chg_pct, oi_chg_pct, cash_confirmation | pytest | rows |
| TC-2 | a day whose answer carries a different as_of (the platform fell back to the latest day), or a 404/502, is skipped; the rest still answer; `missing` counts them | pytest | skipped |
| TC-3 | a stock symbol is found in the stock rows; an index symbol in the index rows; an unknown symbol gets no rows for that day | pytest | rows |
| TC-4 | every day failing is 502 upstream_unavailable (never an empty "history") ; sessions outside 2..10 is 422 | pytest | status |
| TC-5 | the workspace shows "Last five sessions": each session's date and state chip, oldest to newest, with the note that a change of state is not a signal | e2e | text |
| TC-6 | a session with a missing label shows "No state", never a guess; a failed read shows the panel's own notice and leaves the card | e2e | text |
| TC-7 | the workspace shows option-chain OI bars: puts left, calls right, strikes around the ATM, the ATM strike marked, the put and call walls marked, with the note that OI is not who holds it nor support or resistance | e2e | bars |
| TC-8 | 390px: no sideways overflow; existing lab specs pass; tsc exit 0 | e2e, tsc | pass |
