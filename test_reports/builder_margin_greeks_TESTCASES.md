# Desk F&O strategy builder: margin wording, record pointer, per-leg Greeks, all charges: test cases (authored before implementation)

Ask (2026-10-24): four defects on the Desk F&O builder, checked on origin/dev 19263e08.
1. The payoff route's `margin_reason` ("No margin source exists in this system ... broker margin APIs are account-level, not per structure") is false: `services/fno_margin.py` asks Zerodha's margin calculator for one structure. The plan caveat ("no source exists in this system") and the futures warning ("no margin estimate exists in this system") repeat it. The summary's own fallback says "no margin source for this position".
2. The builder shows a permanently disabled "Record as paper trade" with "the desk's paper trades hold long shares only". False: option structures are recorded as strategy paper trades from a plan (PlanActions -> POST /api/desk/paper-trades, kind "strategy").
3. The route returns per-leg Greeks (`pre_expiry.per_leg_greeks`); nothing renders them.
4. The margin strip parses SEBI and stamp duty charges and does not show them.

Choices (stated here so the tests check them):
- Backend wording: the payoff calculation does not estimate margin; margin for a structure comes only from Zerodha's margin calculator, which needs the platform's daily Kite login (POST /api/fno/margin answers 503 without it). The plan caveat and the futures warning say the plan does not estimate margin, without claiming no source exists. ideas.py and picks.py use the plan's caveat constant instead of their own copy.
- The builder already overrides the summary's margin tile with the calculator's figure or a pointer to the strip (PR #337); the summary's own fallback text is corrected so no screen says "no margin source".
- Record: option (a). The dead button is removed; the text points to the full Strategy Builder, where a plan's candidate is recorded with "Paper trade this". It says that the trades typed here are not carried over (openStrategy passes only the symbol and source), because that is how the code works. Option (b) is not trivially safe: the strategy paper trade needs a saved plan id and a plan candidate.
- Per-leg Greeks: a compact table under the pre-expiry chart only, captioned as a model estimate (the answer's model, Black-76, end-of-day inputs), one row per leg plus the net row from the answer; a missing leg or value prints "—".
- Charges: every component the calculator returns (brokerage, STT, exchange, SEBI, stamp duty, GST) and the calculator's own `charges.total`, all to the paisa so the parts visibly add up to the total (rounded rupees showed SEBI ₹0.01 as ₹0 and 5.50 + 5.65 as 6 + 6).

| ID | Scenario | Type | Expected |
|----|----------|------|----------|
| U-1 | engine.MARGIN_REASON on a valid and an invalid payoff | pytest | says the payoff calculation does not estimate margin, names Zerodha's margin calculator and the daily Kite login; does not say "No margin source exists" |
| U-2 | regime_fit.metrics_for margin_reason | pytest | margin None; reason is the corrected text (old pin "no margin source" replaced) |
| U-3 | plan.MARGIN_CAVEAT; ideas and picks caveats | pytest | no "no source exists"; names the margin calculator; ideas.CAVEATS-equivalent and picks.CAVEATS carry plan.MARGIN_CAVEAT, so the live swap to MARGIN_LIVE_CAVEAT still matches |
| U-4 | futures candidate warning | pytest | equals live_reads.OLD_FUTURES_WARNING (the live swap still fires); no "no margin estimate exists in this system" |
| U-5 | existing live-read, payoff, plan, ideas, picks, regime-fit, fno-margin suites | pytest | still pass |
| E-1 | builder, calculator answers | e2e | summary tile ₹77,519 with "source: Zerodha margin calculator"; strategy graphs contain neither "No margin source" nor "does not estimate margin" |
| E-2 | builder, record pointer | e2e | no `desk-builder-record` button; `desk-builder-record-why` names the full Strategy Builder and "Paper trade this", says the trades here are not carried over and that nothing is sent to a broker; does not say "long shares only"; "Open the full Strategy Builder" is enabled |
| E-3 | builder, per-leg Greeks in the pre-expiry view | e2e | `payoff-leg-greeks` caption has "model estimate", "Black-76", "end-of-day inputs"; one row per leg with the leg label and Δ Γ Θ Vega ρ formatted as the readout; a net row; the table is absent in the expiry view |
| E-4 | builder, charges | e2e | charges line shows SEBI ₹0.01 and stamp duty ₹0.00 beside brokerage, STT, exchange, GST, and the total ₹59.40 equals `charges.total` |
| X-1 | edge: margin calculator 503 | e2e | strip "Unavailable · ... not logged in to Kite today"; summary tile "—" with that reason; no figure; no charges line |
| X-2 | edge: a leg's Greeks null, one value null | e2e | that leg's row prints "—" in every cell; a null value prints "—" in its cell |
| X-3 | edge: per_leg_greeks empty in the answer | e2e | the section says per-leg Greeks are not in this answer ("—"), no table rows |
| X-4 | summary fallback: margin and margin_reason both null | e2e | note says the payoff calculation does not estimate margin; never "no margin source" |
| R-1 | regression: lab, strategy builder, ideas, top, graphs specs | e2e | pass with the changed texts |
