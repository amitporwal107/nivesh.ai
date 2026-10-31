# Pre-registration: confirmation test of A2 (63-session relative strength vs Nifty 50)

**Registered:** 2026-10-27. This is before any signal date after 2026-10-09, the last one used in the first study, has a
complete outcome.
**Why:** in `P4_ADX_RS_RESULTS.md`, A2 beat the current score out of sample in validation (Δ IC +0.0109, t 2.75) and test
(Δ +0.0122, t 3.18). It was not adopted because the test period contained only one regime (Nifty 50 below its 200-session
average on every date). This confirmation is a new analysis with its own rule; it does not reopen the first one.

## Design (identical to the first study except where stated)
- Same data sources, universe, scores (B0 and A2 only), outcome (10-session excess return from the next open), metrics,
  Newey-West lag 9, block-permutation (10-session blocks, 1,000 draws), seed 20261028.
- Code: `research/p4_adx_rs/run_study.py` at commit `8ea7afb6`, restricted to signal dates **after 2026-10-09**. The
  confirmation is one split, with no discovery or validation.
- **When it runs:** once both of these hold:
  - at least **60** new signal dates have a complete outcome;
  - at least **20** of them fall in each regime (Nifty 50 above / below its 200-session average).

  Check monthly. If the regime condition is not met by 2027-06-30, run anyway and report the result as single-regime.

## Adoption rule (all must hold)
1. Δ IC (A2 − B0) > 0 with Newey-West t ≥ 2.0 and permutation p < 0.05 over the confirmation dates.
2. Δ IC > 0 in each regime half that has at least 20 dates.
3. The top-decile net (0.35% costs) mean is not below B0's.

If all hold, the scanner's "sector" term may be replaced by RS63 vs Nifty 50, through a normal PR with the engine version
bumped. Otherwise the weights stay and the result is recorded, negative or inconclusive.
