# F&O margin and charges from Zerodha's margin calculator: test cases (authored before implementation)

Ask (user, 2026-10-24): the strategy screens need Funds/Margin needed, which we had left unavailable because we have no SPAN/exposure source. Source found and verified read-only on staging:
Kite Connect's basket margin calculator (`basket_order_margins`): a CALCULATION of the exchange margin and the order charges for a basket (STT, exchange, SEBI, GST, brokerage, stamp duty); it places, modifies and cancels nothing.
Verified 2026-10-24: a GODFRYPHLP bear put spread (275 lot) returned initial 78,908.06 / final 77,519.31 and per-order charges.
Scope: new read-only route POST /api/fno/margin; legs are mapped to Kite tradingsymbols from the NFO instrument list (cached for the day). The wrapper exposes ONLY instruments + the basket calculation (a test pins this).
Needs the platform Kite session (daily login); without it the route says so (503 kite_session_unavailable) and the screens show "Unavailable". The figure is Zerodha's, for the platform account's rules, not an exchange-published number and not a quote: the screens label it so.

| ID | Scenario | Type | Expected |
|----|----------|------|----------|
| TC-1 | legs map to NFO tradingsymbols by underlying, expiry, strike and type; quantity = lots x the instrument's lot_size; BUY/SELL kept; a leg with no listed contract is reported by name and nothing is calculated | pytest | params |
| TC-2 | the Kite answer is shaped: required margin (final), initial margin, per-leg and total charges with each component, `source`, `as_of`; missing numbers are null, never 0 | pytest | shape |
| TC-3 | no Kite session (no token / token error) is 503 `kite_session_unavailable`; a Kite error is 502 with no provider text; bad input (no legs, more than 10, lots < 1, unknown option type) is 422 | pytest | status |
| TC-4 | the wrapper exposes no order surface: its public methods are exactly instruments and basket_margins; the module never references place/modify/cancel/gtt | pytest | names |
| TC-5 | the instrument list is read once and reused within the day | pytest | calls |
| TC-6 | the summary strip shows Funds/Margin needed from the route with the source label; a 503 shows "Unavailable" with the reason; probability of profit stays unavailable | e2e | text |
