# Functionality Verification Report — AMC Coverage Expansion + Smart Money Component

- **Branch:** feat/provider-foundations (996ad4c4, 02ae25cf, 37937eb8, a4475221)
- **Date:** 2026-10-22
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER + DOMAIN_EXPERT_ANALYST)
- **Environment:** staging — `nidp_staging` on the CloudPe NIDP VM (45.64.105.224)
- **Changed areas:** backend NIDP services + migrations: yes · backend/routes, backend/services: no · frontend src: no

## Summary
Two pieces of work. (1) Reached the historical mutual-fund disclosures for SBI, UTI, Nippon and
quant through the AdvisorKhoj static index of the official AMC files — they had working direct
adapters addressing only "latest", which is why each held a single month. (2) Added a Smart Money
accumulation/distribution score as an ADDITIONAL COMPONENT of the existing stock-selection engine
(shadow mode), per the architecture decision to avoid a second ranking engine.

## Test Cases

| ID | Scenario | Expected | Result |
|----|----------|----------|--------|
| TC-A1 | Matcher change does not alter already-resolved URLs | 0 changes over 70 pairs | **PASS** — identical=70 changed=0 lost=0 |
| TC-A2 | Nippon's `30-Sep-26` date form resolves | ≥12 of 13 months | **PASS** — 12/13 offline, 13/13 written live |
| TC-A3 | Filename beats publication directory | UTI 2025-10 from a `/2025-11/` dir resolves to Oct | **PASS** — matched `31.10.2025` in the filename |
| TC-A4 | Degenerate source cannot beat a good one | Nippon writes thousands, not 3 | **PASS** — 358,029 rows / 13 months (was 3) |
| TC-A5 | Source outage does not downgrade a held month | SBI 2026-09 stays OK | **PASS** — reconcile repaired 1 row |
| TC-A6 | 19 mf_holdings unit tests still pass | 19 passed | **PASS** |
| TC-B1 | Component writes only its own table | v3_stock_scores_daily untouched | **PASS** — service writes `smart_money_scores_daily` only |
| TC-B2 | No disclosed evidence ⇒ NULL, not 0 | `insufficient`, no score | **PASS** — 1,576 of 2,479 unscored; CHECK constraint enforces it |
| TC-B3 | Overlay is 0 for symbols without evidence | exactly 0.00 | **PASS** — min 0.00 max 0.00 over 1,576 rows |
| TC-B4 | Low confidence cannot swing the ranking | near-neutral overlay | **PASS** — low: −0.78..+1.22 (vs high −5.35..+6.20) |
| TC-B5 | NULL live score must not become a number | stays NULL, not ranked #1 | **PASS** — sentinel excluded, 0 sentinel rows |

## Real output — coverage after the backfill
```
  amc_id   | months_ok | months_empty |  rows
-----------+-----------+--------------+--------
 absl      |        13 |            0 | 199432
 franklin  |        13 |            0 |  90678
 icici_pru |        13 |            0 | 351224
 kotak     |        13 |            0 | 234272
 nippon    |        13 |            0 | 358029
 ppfas     |        13 |            0 |  21084
 quant     |        13 |            0 |  71076
 uti       |        12 |            1 |  31006
 axis      |         5 |            8 | 101610
 sbi       |         1 |           12 |  24737
```
8 AMCs at full 13-month depth, up from 5. `mf_holdings_backfill done: attempted=52 ok=38
empty=14 error=0 rows=460111`.

## Real output — pipeline totals
```
 months | holdings_rows | delta_rows | validated | component_rows
     13 |       1484206 |    1534422 |   1359578 |            939
```
`mf_holdings_deltas --all`: `fetched=1533278 inserted=1533278 status=OK duration=101353ms`.
`smart_money_scores`: `wrote 939 rows (universe 2480, lookback 3 months);
confidence={'high': 547, 'low': 345, 'medium': 47}`.

## Real output — honesty invariants on the enlarged dataset
```
 tc5_delta_mismatches | tc7_pct_on_zero_base | tc6_value_mistaken_for_buying | tc9_gap_leaks | tc8_unfounded_new
                    0 |                    0 |                             0 |             0 |                 0
```
Independently recomputed over 1,359,578 validated rows: share deltas match exactly; no percentage
change on a zero base; no case where a market-value rise with a flat share count was called
anything but `unchanged`; no coverage gap leaked a direction; no `new` position without a prior
observation.

## Real output — the §16 user story is now answerable
```
 security_isin |   symbol   | inc | red | amcs | new_pos
 INE002A01018  | RELIANCE   | 257 | 148 |    9 |      44
 INE397D01024  | BHARTIARTL | 215 | 121 |    9 |      23
 INE522F01014  | COALINDIA  | 210 | 102 |    9 |      37
 INE090A01021  | ICICIBANK  | 157 | 236 |    9 |       4
```
Nine independent AMCs now visible on major names (six before). ICICIBANK shows 157 schemes
increasing against 236 reducing — net distribution. Reporting both sides is what prevents
"157 funds are buying ICICIBANK".

## Defects found by running the code
1. **Nippon discovery** — `30-Sep-26` (day + month name + 2-digit year) matched no pattern; 45
   files were on the page unread. 0/13 → 13/13 months.
2. **Publication-vs-data month** — the matcher matched anywhere in the URL, so an AMC filing
   under its publication month returned the wrong month (Tata: "as on 30th September 2026" under
   `/2026-10/`). Now filename-first. Regression-checked over all 70 prior URLs.
3. **My own dispatch precedence** — a non-empty direct result won unconditionally, so Nippon's
   degenerate 3 rows suppressed the good source's 5,189. Now AdvisorKhoj first, plausibility
   floor, larger result wins, choice logged.
4. **Ledger downgrade on retry** — sbimf.com served 503 for its whole host during a `--all` pass,
   flipping a held month from OK to EMPTY while its rows remained. `status` now means "do we hold
   it"; `last_error` means "did the last attempt work".
5. **NULL became 100** — Postgres GREATEST/LEAST ignore NULLs, so the `__coverage__` sentinel row
   (NULL final_score) scored 100 and ranked #1 in the shadow view. Fixed in migration 168.
6. **Scale mismatch in the first shadow blend** — a 20% weighted pillar moved ranks by 97.5 places
   on average because final_score has stddev 9.53 while a percentile rank is uniform (~29).
   Replaced with a bounded, confidence-scaled additive overlay; average move 45.3.

## UNVERIFIED / limitations
- **UNVERIFIED on prod.** Staging only; prod untouched.
- **SBI has 1 of 13 months** — `sbimf.com` returned HTTP 503 for its entire host (homepage
  included) throughout this work. Its 13 months are resolvable (verified offline), so the
  `--trailing` catch-up should heal it once the host recovers. Axis has 5 of 13 (AdvisorKhoj
  exposes only 5). HDFC, Tata and Mirae remain unreached: AdvisorKhoj carries only factsheet PDFs
  for HDFC and Mirae, and Tata needs the filename-priority fix plus registration (not done here).
- **The component is shadow mode and must stay there** until it has been observed across more than
  one scoring date. Promotion into `composer.py` is a separate, evidence-led decision; the sub-signal
  weights are hypotheses, not tuned.
- **No publication timestamp on `mf_holdings_monthly`** — point-in-time backtesting (§39) still
  cannot be done honestly for this pillar. Recommended before any backtest uses it.
- Component coverage is 903 of 2,479 symbols (36%); the rest are `insufficient` by design.
- Trendlyne MCP could not be evaluated as an alternative source: every data tool returned
  `code:1009 "Rate limiting channel or user not subscribed"`.

## Verdict: PASS
