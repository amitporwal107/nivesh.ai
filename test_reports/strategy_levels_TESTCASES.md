# Entry, stop-loss and target levels for every options strategy: test cases (authored before implementation)

Ask (user, 2026-10-24, with a written spec): for every strategy show the strategy-level entry (net debit/credit), a planned stop-loss and a risk boundary, two targets, the underlying's entry/stop/target, Greek-based exit conditions, max profit/loss, capital, risk-reward.
Honest framing (stated on screen): these are RULE-BASED, HYPOTHETICAL levels worked out from the payoff engine's own numbers with fixed research settings (below). They are not predictions, not advice, and no accuracy or hit rate is claimed: the one-year tests found no skill in these signals. A stop is a theoretical level; a real stop order can fill worse in a gap.
Not built (stated): an entry RANGE (needs bid/ask, not in end-of-day data), a "best strategy" ranking (nothing is validated), live-quote re-estimation.

Settings (research, version `strategy-levels-v1`):
- per unit = total / (lot size x gcd of the legs' lots); debit D = -net premium per unit, credit C = +net premium per unit.
- DEBIT: planned stop = value falls to 70% of D (loss 30% of D); risk boundary = the maximum loss (D for a debit); T1 = D + 30% of D, T2 = D + 60% of D, each capped at D + max profit per unit.
- CREDIT, defined risk (finite max loss L per unit): planned stop = buyback at C + min(C, 0.5 L); risk boundary = max loss L; T1 = buyback at 50% of C, T2 = buyback at 20% of C.
- CREDIT, undefined risk (loss unbounded): planned stop = buyback at 2C (loss = C); risk boundary = "unbounded: no maximum"; targets as above.
- Underlying: entry = spot. Bullish (net delta > +0.05 per share): stop = the put wall if it is below the spot, else spot - expected move; target = the call wall if above, else spot + expected move. Bearish mirrored. Neutral (|net delta| <= 0.05): range = put wall .. call wall (or spot +- expected move); a close outside it invalidates.
- The strategy's value at the stop and target underlying prices is the engine's model estimate for the data date (T+0), not a quote.
- Greek rule: entry net delta per share d0; exit review when it falls below 30% of d0 (same sign) for a directional strategy, or when |net delta| exceeds 0.20 for a neutral one. Expiry week (<= 3 days to expiry): a gamma warning.

| ID | Scenario | Type | Expected |
|----|----------|------|----------|
| TC-1 | bull call spread (debit): entry D, planned stop 0.7D, risk boundary D, T1/T2 +30%/+60% capped at max profit; max profit/loss per unit, risk-reward | pytest | numbers worked by hand |
| TC-2 | bear put spread: bearish, underlying stop above spot (call wall or spot + move), target below | pytest | levels |
| TC-3 | bull put spread (credit, defined risk): entry C, stop buyback C + min(C, 0.5L), boundary L, targets 50% and 20% of C | pytest | numbers |
| TC-4 | short straddle (credit, undefined risk): stop buyback 2C, boundary "unbounded", neutral range from the walls | pytest | numbers |
| TC-5 | a wall on the wrong side of the spot is replaced by the expected move edge; no walls and no move leaves the level null (never a guess) | pytest | null |
| TC-6 | per-unit maths with 2 lots and a 4,525 lot: identical per-unit figures to 1 lot | pytest | equal |
| TC-7 | an invalid structure returns the engine's problems, no levels; expiry week adds the gamma warning; the executable-stop caveat is always present | pytest | flags |
| TC-8 | POST /api/fno/strategy-levels: 200 shape, 422 on a bad body | pytest | status |
| TC-9 | the builder shows the levels card: entry, planned stop, risk boundary, targets, underlying levels, Greek rule, the caveats; nothing says best/accuracy | e2e | text |
