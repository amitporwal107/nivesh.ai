# F&O Lab: paper strategy builder (leg-based) : test cases (authored before implementation)

Ask (user, 2026-10-23): build the Paper strategy builder from the design canvas (Strategies, StrategiesMobile) after the Sensibull-style reference: structure tiles, editable trades, summary strip,
payoff chart with what-if controls, Greeks. Reuses what the desk already has: POST /api/desk/strategy/payoff (pure calculation, no write), PayoffChart, PayoffSummary, ScenarioControls (StrategyGraphs).
The builder computes NO payoff, Greek, cost or capital figure itself; it builds the request from the chain's end-of-day option prices and shows the route's answer. Probability of profit and margin
are shown as unavailable exactly as the route says. Option spreads cannot be recorded as paper trades (the desk's paper trades hold long shares only); the button is disabled with that reason.

| ID | Scenario | Type | Expected |
|----|----------|------|----------|
| TC-1 | the Paper strategies tab opens on the builder (a switch keeps the rule-based ideas one click away); a stock with a build-up label starts with the matching structure loaded (short build-up -> Bear Put Spread) | e2e | legs |
| TC-2 | structure tiles: Bullish / Bearish / Neutral / Others chips filter the tiles; clicking a tile loads its legs at the ATM and nearby strikes with the chain's end-of-day closes | e2e | legs, prices |
| TC-3 | the leg table is editable: B/S toggle, strike select, lots, price; each change sends a new payoff request whose legs equal the table (kind option, quantity = lots, lot_size from the futures, entry_price, strike, option_type, expiry) | e2e | request body |
| TC-4 | the summary and chart show the route's answer (max profit, max loss, breakeven, net premium, costs, capital); probability of profit and margin read as unavailable with the route's reasons; nothing is computed in the browser | e2e | text |
| TC-5 | what-if controls (price, IV shift, date) change the request; a failed payoff shows the notice with retry, never an empty chart | e2e | notice |
| TC-6 | a leg with no end-of-day price shows "no close" and blocks the request with a plain message; removing all legs shows the empty state | e2e | text |
| TC-7 | "Record as paper trade" is disabled with the reason; "Open the full Strategy Builder" opens it; nothing is sent to a broker | e2e | disabled |
| TC-8 | an index (NIFTY) works the same; no chain shows the lab's own notice | e2e | notice |
| TC-9 | 390px: tiles and legs stack, no sideways overflow; existing lab specs pass; tsc exit 0 | e2e, tsc | pass |
