# Results: ADX and relative-strength variants of the AI scanner score (Phase 4.3)

**Registration:** `docs/ai_research/P4_ADX_RS_PREREGISTRATION.md`, commit `4c408401` (2026-10-27 07:33 IST, before any
result).
**Analysis code:** `research/p4_adx_rs/run_study.py`, commit `8ea7afb6` (sha256 `9f1823f1…`, the same file the run
used).
**Run:** 2026-10-27 07:45–07:48 IST. Inputs were exported read-only from the staging warehouse after the index-history
backfill (`test_reports/index_backfill_20261027.md`).
**Output:** `research/p4_adx_rs/results_20261027/` (`result.json`, `per_date.json`, with file hashes and the input hash).

## Decision under the pre-registered rule
**Keep B0. The current scanner weights are not changed.** No arm met all four conditions.

| Arm | (a) validation | (b) test | (c) test net spread ≥ B0 | (d) same sign in both regimes (test) | Adopt |
|---|---|---|---|---|---|
| A1: + ADX term | ✗ | ✗ | ✓ | ✗ | no |
| A2: RS63 vs Nifty 50 replaces the sector term | ✓ | ✓ | ✓ | ✗ (see below) | no |
| A3: A2 + ADX term | ✗ | ✓ | ✓ | ✗ | no |

## Numbers
- Signal dates: 385.
  - discovery: 2025-02-17 .. 2026-02-11 (233 dates);
  - validation: 2026-02-12 .. 2026-06-15 (71);
  - test: 2026-06-16 .. 2026-10-09 (81).
- Median 511–597 stocks per date.
- Outcome: 10-session excess return, entry at the next open.
- IC: daily Spearman rank correlation. Δ is the paired difference with B0, with a Newey-West t at lag 9 and a one-sided
  block-permutation p.

| Split | B0 IC (t) | A1 Δ (t, p) | A2 Δ (t, p) | A3 Δ (t, p) |
|---|---|---|---|---|
| Discovery | 0.0085 (0.43) | −0.0084 (−2.80, 0.997) | −0.0037 (−0.98, 0.80) | −0.0124 (−3.24, 0.997) |
| Validation | 0.0011 (0.03) | −0.0045 (−1.07, 0.82) | **+0.0109 (2.75, 0.035)** | +0.0057 (1.22, 0.14) |
| Test | 0.0075 (0.41) | +0.0031 (0.87, 0.23) | **+0.0122 (3.18, 0.007)** | +0.0127 (2.09, 0.045) |

Top decile (each arm's highest-scored 10%), mean 10-session return net of 0.35% costs:

| Split | B0 | A1 | A2 | A3 |
|---|---|---|---|---|
| Discovery | +0.23% | +0.22% | +0.17% | +0.17% |
| Validation | +0.26% | −0.06% | +0.28% | +0.12% |
| Test | −0.99% | −0.94% | −0.89% | −0.82% |

Top-decile hit rate (excess return > 0): 45–50% for every arm in every split.

## What the results say
1. **The current score shows no measurable ranking skill** for 10-session excess returns in this window. B0's mean daily
   IC is 0.001–0.009 and no t-statistic exceeds 0.5. Its top decile lost 0.99% after costs in the test period. This
   matters more than any of the variants. Per the owner's criteria (4.3), it is not grounds to change the weights. It is
   grounds **not to present the scanner's rank as evidence of an edge.** The desk already calls these "ideas", and its
   cards should keep saying the ranking is not a prediction.
2. **ADX (A1) hurts.** It is significantly worse in discovery (t −2.80) and not better later. Do not add it.
3. **RS63 vs Nifty 50 (A2) is the one promising candidate.**
   - It beat B0 in validation and in test, out of sample, with a better net spread.
   - It failed condition (d) because **the whole test period was a single regime**: Nifty 50 was below its 200-session
     average on all 81 test dates, so the "up" half was empty.
   - In validation it was positive in both regimes: up, 11 dates, t 4.46; down, 60 dates, t 2.11.
   - In discovery it was slightly negative (−0.0037, t −0.98).
   - Under the registered rule it is **not adopted**. The rule is not changed after the fact.
4. **Coverage.** On a typical day 67–77% of the top-decile forward movers were outside the scanner's universe. Most are
   below the ₹10 crore median traded value or the ₹20 price floor. That is a deliberate liquidity choice, not a bug, but it
   means the scanner cannot see most large short-term movers.

## Limitations
- About 2.5 years of prices; validation and test hold only about 7–8 independent 10-session periods each.
- One regime dominated the test period.
- The per-sector macro tilt has no point-in-time history, so it was left out for every arm. The macro multiplier was
  omitted because it does not change rankings.
- The Nifty 50 history for 2024-09-23 .. 2025-09-29 was backfilled on 2026-10-27 from NSE's official files and checked
  against NIFTYBEES (correlation 0.9906).

## Next step
A separate, newly registered confirmation test of A2 on data that did not exist at registration:
`docs/ai_research/P4_RS63_CONFIRMATION_PREREGISTRATION.md`. Until it passes, the scanner keeps its current weights.
