# F&O Lab: option chain with the Analyse panel: test cases (authored before implementation)

Ask (user, 2026-10-24): build the v5 version of the Sensibull-style option chain with B and S buttons on each strike and a floating Analyse panel (screenshots + blog).
The panel is the Builder in its panel variant: the trades from the chain rows, the payoff from POST /api/desk/strategy/payoff, funds/margin and charges from POST /api/fno/margin.
Nothing is computed in the browser; no order is placed or offered (the blog's "place orders from the window" is not built: Nivesh places no orders).
Not in this step (stated): intrinsic/time-value columns, OI change %, LTP change % and IV as chain columns (IV and Greeks stay in the chain's model detail), IV chart and IVP (no IV history stored).

| ID | Scenario | Type | Expected |
|----|----------|------|----------|
| TC-1 | every strike row with a call or put has B and S buttons on that side; a side with no contract has none | e2e | buttons |
| TC-2 | clicking B on a call adds a buy leg at that strike priced at the end-of-day close and opens the Analyse panel ("1 trade selected"); the payoff request carries exactly that leg | e2e | request |
| TC-3 | clicking S on another strike adds a second leg; clicking an active button again removes that leg; removing the last closes the panel | e2e | legs |
| TC-4 | the panel shows net premium, funds and margin needed with its source line, and the payoff chart; a 503 from the margin route reads Unavailable with the reason | e2e | text |
| TC-5 | the panel can be minimised (body hidden, header and count stay) and closed (clears the trades and the active buttons) | e2e | state |
| TC-6 | the panel has no order button; "Record as paper trade" is disabled with the reason | e2e | absent/disabled |
| TC-7 | changing the underlying or the expiry starts a new analysis (trades cleared) | e2e | cleared |
| TC-8 | dragging the header moves the panel (desktop); at 390px the panel docks to the bottom and the page has no sideways overflow | e2e | position, 0 |
| TC-9 | the Paper strategies builder and the existing chain tests still pass; tsc exit 0 | e2e, tsc | pass |
