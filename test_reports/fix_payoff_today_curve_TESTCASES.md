# Payoff chart: today's curve against the expiry curve: test cases (authored before implementation)

Ask (user, 2026-10-24): why do we not show today's payoff against the expiry payoff (the broker's chart draws both and a Greeks table).
Cause: the payoff request asked for the pre-expiry (today) estimate only when an evaluation date had been set in the what-if controls; none was set by default, so the chart said "Pre-expiry estimate unavailable. None was requested".
Verified 2026-10-24 against the broker's own table, with the engine run on the broker's prices: at 24 Oct our T+0 payoff row (5,578 4,783 3,719 2,470 1,182 13 -921 -1,578 -1,988 -2,213) matches the broker's (5,560 4,750 3,680 2,430 1,140 -24 -949 -1,600 -2,000 -2,220) within about 1%; delta, gamma and vega within about 1%; theta differs (-172 vs -107, convention not established).
Fix: the builder starts with the evaluation date set to the data date (while it is before the expiry); the chart opens on the estimate and draws the payoff at expiry behind it on the same grid; the date stays movable.

| ID | Scenario | Type | Expected |
|----|----------|------|----------|
| TC-1 | the first payoff request carries pre_expiry.date = the chain's data date (when before the expiry); on the expiry day or later no date is sent | e2e | request |
| TC-2 | with an estimate in the answer the chart draws both lines (today and expiry) and the legend names both; with no estimate it falls back to the expiry line only | e2e | testids |
| TC-3 | the scale holds both curves (no clipping): both paths are inside the plot | e2e | geometry |
| TC-4 | moving the date in the what-if controls changes the request's pre_expiry.date | e2e | request |
| TC-5 | existing builder, payoff-chart and lab specs pass; tsc exit 0 | e2e, tsc | pass |
