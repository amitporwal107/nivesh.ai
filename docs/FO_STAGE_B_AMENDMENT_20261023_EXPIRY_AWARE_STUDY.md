# Amendment (2026-10-23) to B2 and B3: "Expiry-Aware Futures OI + Greeks Incremental Ranking Study"

Decision of record: the user's proposal of 2026-10-23 (E1/E2/E3, hypotheses H1-H7, four-layer incremental comparison). Committed before any B2/B3 code runs. B2 and B3 pre-registrations stand except where this file says otherwise; the later file wins.

## 1. Corrections found while checking the proposal against the code and data
1. **Kite supplies no Greeks.** The platform's Greeks are our own: `backend/services/option_pricing.py`, Black-76 on the forward (the same-expiry future's settle, else put-call parity, else carried spot), implied vol by bisection, delta/gamma/theta/vega, used by `routes/fno.py` for the Lab's chain. So "Kite Greeks" means "Greeks recomputed from end-of-day prices with this module". **B3's separate Black-Scholes / zero-dividend method is withdrawn; B3 uses `option_pricing` unchanged** (no second engine, per the proposal). Its version is recorded as `option_pricing@<git sha>` in every report; a change to it is a new experiment. Historical Greeks are recomputed per day from that day's own prices only (the module is pure and takes the day's inputs), never from today's.
2. **Data coverage differs from "October 2021 onward".** E2/E3 futures and every option feature exist only in the bhavcopy year (1 Oct 2025 to 22 Oct 2026, 260 sessions); features-table inputs start 29 Dec 2025. Kite's 2021+ history is near-month continuous futures only (B1). So H1-H7 are tested on one year; only the E1 futures-only layer has a longer look (B1). Stated in every report.
3. **Intraday remains out of scope** until saved snapshots exist (no historical intraday option prices; Kite lists active contracts only).

## 2. Hypotheses H1-H7, mapped to frozen tests (primary horizon 5 sessions, benchmark-relative, net of cost, as in B2)
| ID | Test | Where |
|---|---|---|
| H1 near-expiry OI more informative near expiry | E1 results, expiry-week (<=3 weekdays) vs other, same frozen settings | B2 section 8 (extended to expiry-week vs non-expiry-week at 1, 3, 5 and at 10, 20) |
| H2 next/far more persistent | E1, E2, E3 independently; also horizon 10 and 20 | B2 configs 1-3 |
| H3 cross-expiry agreement helps | agreement fraction (confirming expiries / 3) in {0, 1/3, 2/3, 1}; agree vs disagree | B2 configs 4-7 plus the fraction as a reported grouping |
| H4 OI migration separates rollover from new positioning | groups fixed now: near OI down and next OI up (rollover-like); near up and next flat or down (new near build); near, next, far all up (broad). OI change = per-contract change in OI / prior OI, flat = within +-1% | new, reported with H3 |
| H5 Greeks add incremental value beyond futures OI | layer comparison below | B3 experiment B |
| H6 options improve strategy selection more than direction | direction layer vs strategy outcome (B3 experiment D) reported separately | B3 |
| H7 expiry-week features help short horizons | 1, 3, 5 vs 10, 20 within expiry-week | B2 section 8 |

## 3. Layer comparison (the critical test), same sessions and universe for all four
L1 futures-only (frozen baseline signal); L2 L1 + expiry features (days to expiry, expiry-week flags, E1/E2/E3 values, migration, agreement); L3 L2 + options OI (PCR, OI and OI-change by strike bucket, concentration); L4 L3 + Greeks/IV (ATM IV change, skew, term structure, straddle-implied move, delta/gamma/vega-weighted OI per underlying and expiry). Reported: each layer's top-5/top-10 benchmark-relative net return and rank IC, the **increment of each layer over the one before** on common sessions, coverage and missingness.
- The ranking model is **not tuned**. Layer scores are fixed now: within each session the cross-sectional percentile of each feature, signed by the frozen direction rule of the category, averaged with equal weights within a layer (no fitted weights); the proposal's 25/15/15/20/15/10 weights are recorded as a second, separately counted variant (`proposal_weights`), not a replacement. Missing features are not redistributed: the layer score is null when coverage is under 80% (counted).
- Eligible universe: underlyings whose near-month future had OI and volume above zero that day and, for L3/L4, whose chain has at least 3 liquid strikes on each side in that expiry.
- Index workspaces (NIFTY, BANKNIFTY) are evaluated separately, never ranked against stocks; with so few series, only descriptive per-index results and no top-N claim.

## 4. Unchanged guardrails
Windows U/D/V/T and the D-learned/frozen selection rule (B2 section 5); session-level Newey-West statistics; permutation baselines; counted configurations; verdict rules (a layer is `supported` only with positive pooled increment on U+V+T for at least 3 of the frozen variants, t >= 1.645 on at least 2, at least 30 pooled signal sessions); nothing is `validated`; ranking stays research-only on screen and the production ranking and floors are not promoted.

## 5. Addendum (2026-10-23, before the first B2 run): positioning transitions
Decision of record: the user's message that states can occur on any day, evolve and reverse, and that transitions may carry more than the static class.
- **Scope now:** daily states per bucket (near, next, far) for every session. Intraday states need intraday OI, which is not stored historically; they are not claimed or tested (live snapshots will make that a later study).
- **State** of a bucket on a session = its build-up category under a setting (None when nothing fires). Settings for this family: `production_floors` (primary) and `no_threshold` (secondary), both frozen and counted; no new thresholds.
- **Transitions tested** (previous session's state -> today's state, same bucket, same setting), traded in the direction of today's state: short_buildup -> short_covering (long), long_buildup -> long_unwinding (short), short_covering -> long_buildup (long), long_unwinding -> short_buildup (short).
- **Static comparators:** today's state with any previous state; today's state with the same state the previous session (persistence of 2); and the same state on 3 consecutive sessions (`consecutive_build_sessions` >= 3, build-up categories only).
- **Outcome, windows, statistics:** as B2 (primary horizon 5, benchmark-relative, net of 0.15% round trip, pooled U+V+T, session-level Newey-West).
- **Rule (fixed now):** a transition `adds_information` only if its pooled mean is positive, t >= 1.645, at least 30 pooled signal sessions, AND its mean exceeds the static comparator for the same today's state in the same bucket and setting. Otherwise it is reported as not demonstrated. Descriptive only; nothing validated; 8 transition configurations x 3 buckets x 2 settings are added to the counted configurations.
