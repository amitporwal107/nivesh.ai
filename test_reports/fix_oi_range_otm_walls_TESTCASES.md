# F&O Lab "OI range": put wall below and call wall above the price: test cases (authored before implementation)

Ask (user, 2026-10-23, GODFRYPHLP): "Why the OI range is incorrect; the current stock price is 1600". Screen: spot 1,669.12, OI range 1,900 - 2,100, max pain 1,850.
Verified cause (warehouse, read-only): the stock fell 1,807.5 -> 1,669 in four sessions. Put OI peaks at the 1,900 strike (36,575) which is now deep in the money (close 240.35), and call OI peaks at 2,100 (76,450).
The tile took the highest put OI and highest call OI over EVERY strike, so its "put wall" (1,900) sat ABOVE the price: in-the-money puts opened when the stock traded higher, not a floor.
Fix: add `put_wall` (highest put OI among strikes at or below the spot) and `call_wall` (highest call OI among strikes at or above it) to the chain summary, and use them for the OI range tile,
the S/R tags, the chain read, the range bar and the index headline. The raw highest-OI strikes stay (`max_put_oi`, `max_call_oi`) and the chain view's "Highest call/put OI" still says exactly that.

| ID | Scenario | Type | Expected |
|----|----------|------|----------|
| TC-1 | summarise_chain: put_wall is the highest put OI at or below the spot; call_wall the highest call OI at or above it; ties go to the strike nearer the spot | pytest | strikes |
| TC-2 | GODFRYPHLP-like chain (spot 1669; put OI peak at 1900, call peak at 2100): put_wall = the best put strike <= 1669, call_wall = 2100; max_put_oi stays 1900 | pytest | strikes |
| TC-3 | no strike on a side (or no spot): that wall is null, the raw maxima are unchanged | pytest | null |
| TC-4 | OI range tile shows put wall - call wall when the summary has them; the sub-label says "below the price" and "above it" | e2e | text |
| TC-5 | wrong-side case: the tile does not show the in-the-money 1,900 put strike as the floor; a note says where the raw highest put OI sits and that it is above the price | e2e | text |
| TC-6 | older response without the new fields: the tile falls back to the old range, unchanged | e2e | unchanged |
| TC-7 | the chain table tags S and R on the walls; existing lab specs pass; tsc exit 0 | e2e, tsc | pass |
