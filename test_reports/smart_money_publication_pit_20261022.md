# Functionality Verification Report — Publication timestamps + point-in-time Smart Money series

- **Branch:** feat/provider-foundations
- **Date:** 2026-10-22
- **Author:** Claude (QA_ENGINEER + DOMAIN_EXPERT_ANALYST + FULL_STACK_DEVELOPER)
- **Environment:** staging — `nidp_staging` (CloudPe NIDP VM)
- **Changed areas:** backend NIDP services + migrations: yes · backend/routes, backend/services: no · frontend: no
- **Still shadow mode.** `nidp.v3_stock_scores_daily` untouched; nothing promoted.

## Summary
`published_at` was the stated blocker for honest point-in-time use of the MF holdings pillar.
Measured that every AMC source exposes `Last-Modified`, established a rule for when that header is
credible as a publication date, backfilled it, carried the resulting knowledge date into the delta
layer, and produced a **point-in-time** monthly series alongside the reporting-date one so the
look-ahead between them is measurable rather than assumed.

## Test Cases

| ID | Scenario | Expected | Result |
|----|----------|----------|--------|
| TC-E1 | Sources expose Last-Modified | most do | **PASS** — 118/118 AMC-months returned a header |
| TC-E2 | Credible headers become published_at | plausible only | **PASS** — 86 plausible; 18 cache-touch + 14 re-upload left NULL |
| TC-E3 | Rule rejects a cache touch inside the lag window | rejected | **PASS** — axis 2026-09 LM = our fetch date → `cache_touch` |
| TC-E4 | Rule rejects a pre-month-end date | rejected | **PASS** — unit case `before_month_end` |
| TC-E5 | Derived lag matches SEBI M+10 | median ≈ 10 | **PASS** — avg 10.0, median 9, min 5, max 47 over 86 AMC-months |
| TC-E6 | Never drop a known published_at on re-ingest | retained | **PASS** — `coalesce(EXCLUDED…, existing)` in writer + backfill |
| TC-E7 | Deltas know when a change became knowable | both months required | **PASS** — `known_from = greatest(cur, prev)` |
| TC-E8 | Point-in-time mode excludes unknowable data | coverage shrinks | **PASS** — 965 → 944 (recent), 896 → 824 (older) |
| TC-E9 | Both series coexist for comparison | 3-col PK | **PASS** — `(as_of_date, symbol, point_in_time)` |
| TC-E10 | Unit tests unaffected | 19 passed | **PASS** |

## Real output — publication coverage
```
 publication_provenance |  rows   | pct
 published_at_captured  | 1232927 | 74.8
 observed_only          |  415234 | 25.2

 avg_days | min_days | median_days | max_days | amc_months
     10.0 |        5 |           9 |       47 |         86
```
A median 9-day lag across 86 independent AMC-months is what corroborates these as real publication
timestamps: SEBI requires disclosure within 10 days of month end.

Per-AMC dateability — tata/nippon/absl/kotak 13 of 13; uti 11; quant 9; ppfas 8; icici_pru 5;
**axis 0 and franklin 0** (their CDNs rewrite `Last-Modified` on access, so it carries no
information and is correctly discarded rather than used).

## Real output — point-in-time readiness of the delta layer
```
 current_month | delta_rows | pit_safe_rows | pit_safe_pct | earliest_known | days_to_fully_known
 2026-09-01    |     204533 |        167386 |         81.8 | 2026-10-07     |                  17
 2026-05-01    |     142983 |         83724 |         58.6 | 2026-06-08     |                   9
 2025-09-01    |     110421 |         72704 |         65.8 | 2025-10-08     |                  10
```
57–82% of the delta layer is backtest-safe, and the earliest knowledge dates land ~6–8 days after
month end, consistent with the publication lag above.

## Real output — the look-ahead a naive historical run would have introduced
```
 as_of_date | rpt | pit | common | score_corr | mean_abs_diff
 2025-12-12 | 896 | 824 |    824 |      0.794 |          8.25
 2026-05-12 | 924 | 869 |    869 |      0.857 |          7.50
 2026-10-12 | 965 | 944 |    944 |      0.927 |          4.94
```
Same scoring date, same symbols: the reporting-date score differs from the honest one by a **mean
5–9 points on a 0–100 scale**, worst for older months (more re-uploaded/undateable files). This is
the quantity that would otherwise have leaked into a backtest unnoticed.

## Real output — persistence survives point-in-time construction
```
 steps | pairs | avg_corr      (point-in-time series)
     1 |    10 |    0.870      (overlapping lookback — partly mechanical)
     3 |     8 |    0.590      (NO overlap)
     6 |     5 |    0.478
```
Against 0.605 / 0.468 for the reporting-date series. **The signal's persistence is not an artefact
of look-ahead** — it holds when only knowable data is used. This is the main scientific result here.

## Gate position
- **Gate A (data integrity)** — now substantially met: 74.8% of holdings rows carry a real
  publication timestamp, with the remainder honestly marked `observed_only`. Residual gap:
  axis and franklin cannot be dated at all, and `source_payload_sha256` still covers only
  post-169 writes.
- **Gate B (multi-date stability)** — met, and now also met under point-in-time construction.
- **Gate C (incremental predictive value)** — **unblocked but not attempted.** The inputs now
  exist (a PIT series over 11 scoring dates). Still missing: historical universe membership
  (`index_constituents` has 3 distinct dates), so any study carries unavoidable survivorship bias.
- **Gate D (promotion)** — not reached.

## UNVERIFIED / limitations
- `published_at` is an **upper bound**, not the exact release moment: the real publication may
  have been slightly earlier than the file's `Last-Modified`. Consumers must use
  `coalesce(published_at, source_observed_at)` (exposed as `known_from` / `nidp.v_mf_holdings_asof`).
- 11 PIT scoring dates in **one market regime**. Stability across regimes is unknown.
- Point-in-time coverage excludes axis and franklin entirely, so the PIT series is a *different
  and smaller* AMC mix than the reporting-date series — part of the measured gap is composition,
  not just timing.
- Staging only; prod untouched.

## Verdict: PASS
