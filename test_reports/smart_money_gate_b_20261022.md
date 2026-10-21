# Functionality Verification Report — Smart Money Component, Gate B (multi-date stability)

- **Branch:** feat/provider-foundations
- **Date:** 2026-10-22
- **Author:** Claude (QA_ENGINEER + DOMAIN_EXPERT_ANALYST + FULL_STACK_DEVELOPER)
- **Environment:** staging — `nidp_staging` (CloudPe NIDP VM)
- **Changed areas:** backend NIDP service + migration: yes · backend/routes, backend/services: no · frontend: no
- **Still shadow mode.** Nothing was promoted; `nidp.v3_stock_scores_daily` is untouched.

## Summary
Gate B asks whether the component is observed across several independent scoring dates with
coverage and score changes recorded. Added a `--month` historical mode and produced **13 scoring
dates** (2025-11 → 2026-10) from the 13 backfilled disclosure months, then measured stability.

## Test Cases

| ID | Scenario | Expected | Result |
|----|----------|----------|--------|
| TC-D1 | `--month` caps visible disclosures to that month | no later month used | **PASS** — `latest_disclosure` per date equals the capped month |
| TC-D2 | Multi-date series exists | ≥ 3 dates | **PASS** — 13 dates |
| TC-D3 | Coverage recorded per date | monotonic, explicable | **PASS** — 845 → 965 as depth accrues |
| TC-D4 | Early dates degrade confidence, not fabricate it | low/medium only | **PASS** — 2025-11 is 100% `low`; `high` appears from 2026-01 once 3 months exist |
| TC-D5 | Overlapping vs non-overlapping correlation distinguished | flag correct | **PASS** — `overlapping` TRUE iff steps < lookback |
| TC-D6 | Signal is stable, not noise | non-overlap corr > 0.3 | **PASS** — 0.605 at 3 steps |
| TC-D7 | Daily rescoring adds nothing | identical within a month | **PASS** — 2026-10-12 → 2026-10-21 corr = **1.000** |
| TC-D8 | Unit tests unaffected | 19 passed | **PASS** |

## Real output — coverage and confidence per scoring date
```
2025-11-12  845 rows  confidence={'low': 845}
2025-12-12  896 rows  confidence={'medium': 541, 'low': 355}
2026-01-12  909 rows  confidence={'high': 510, 'low': 345, 'medium': 54}
...
2026-09-12  947 rows  confidence={'high': 525, 'low': 366, 'medium': 56}
2026-10-12  965 rows  confidence={'high': 548, 'low': 369, 'medium': 48}
```

## Real output — persistence, by spacing
```
 steps_apart | overlapping | pairs | avg_corr
           1 | t           |    12 |    0.882
           2 | t           |    11 |    0.750
           3 | f           |    10 |    0.605
           4 | f           |     9 |    0.541
           5 | f           |     8 |    0.499
           6 | f           |     7 |    0.468
```
With a 3-month lookback, spacings of 1 and 2 share input months, so their correlation is partly
mechanical. **At zero overlap (3 steps) the correlation is still 0.605**, decaying gently to 0.468
at 6 months — a genuinely persistent signal, not a window artefact.

## Real output — top-quintile churn
```
 next_month_quintile | symbols | pct
                   2 |      32 |  1.6
                   3 |     162 |  8.1
                   4 |     498 | 24.8
                   5 |    1314 | 65.5
```
65.5% of top-quintile names stay top-quintile; 90% stay in quintile 4–5; **none** fall to quintile 1.

## Interpretation
- **Stability: met.** The component is sticky and decays smoothly. It is not noise.
- **Low new information per period.** 65% top-quintile retention and a monthly step function (TC-D7)
  mean few new candidates per month. This supports the existing design choice — a bounded,
  confidence-scaled overlay (migration 168) rather than a candidate generator or a ranking driver.
- **Persistence is not predictive value.** Nothing here shows the signal forecasts returns.

## Gate position after this work
- **Gate A (data integrity)** — partially met. Provenance landed (migration 169), but `published_at`
  is uncaptured and `source_payload_sha256` covers only post-169 rows.
- **Gate B (multi-date shadow validation)** — **met for stability**, with the caveat below.
- **Gate C (incremental predictive value)** — NOT started and still blocked: needs `published_at`
  and historical universe membership (`index_constituents` has 3 distinct dates).
- **Gate D (promotion)** — not reached.

## UNVERIFIED / limitations
- **This series is reporting-date-based, NOT point-in-time.** Every backfilled row was observed in
  October 2026, so a historical scoring date still "sees" data earlier than any user could have.
  It is therefore valid evidence of **signal stability** and invalid as a backtest. The `--month`
  help text says so at the point of use.
- 13 dates from 13 disclosure months of a single market regime. Stability across regimes is unknown.
- Coverage is ~965 of ~2,480 symbols (39%); the rest have no class-A evidence by design.
- Staging only; prod untouched.

## Verdict: PASS
