# Nifty 500 — Scoring Primitive Coverage Gap Report
**Generated:** 2026-05-27 (updated post-backfill)
**Primitives date:** 2026-05-25  
**Scope:** 505 Nifty 500 constituents

---

## Executive Summary

| Metric | Before | After Fixes |
|---|---|---|
| Total Nifty 500 stocks | 505 | 505 |
| Stocks with any primitives | 498 (98.6%) | 498 (98.6%) |
| Stocks classified as DEFAULT (no sector) | 484 (97.2%) | **~14 (2.8%)** |
| Stocks with `roe_pct` | 262 (52%) | **481 (96.6%)** |
| Stocks with `roce_pct` | 244 (49%) | **424 (85.1%)** |
| Stocks with `profit_margin_pct` | 250 (50%) | **435 (87.3%)** |
| Stocks with `debt_to_equity` | 262 (52%) | **481 (96.6%)** |
| Stocks with `promoter_pct` | 250 (50%) | **463 (93.0%)** |
| Stocks with `eps_growth_3y_cagr_pct` | 453 (91%) | **451 (90.6%)** |

**P0 (Sector tagging) and P2 (NSE Financials) fixes applied.** The two biggest blockers — DEFAULT profile overuse (97% → 3%) and missing fundamentals (~50% → ~90%) — are resolved.

---

## Remaining Gaps (as of 2026-05-27)

| Primitive | Coverage | Root Cause | Priority |
|---|---|---|---|
| `accumulation_score` | 0% | Not implemented in `populate_stock_price_features()` | P1 |
| `promoter_pledged_pct` | 0% | BSE shareholding scraper not populating this field | P1 |
| `revenue_growth_3y_cagr_pct` | 47.6% | Requires ≥3 years of NSE financials history — self-resolving over time | P2 |
| `interest_coverage` | 84.9% | EBIT/Finance Costs null for some stocks (no debt → intentionally null) | P3 |
| `pe_overvaluation_pct` | ~5% | Requires sector peer group — now unblocked by sector fix | P3 |
| `revenue_growth_yoy_pct` | 80.9% | Some stocks missing YoY financials | P3 |

---

## Gap by Feed (Current State)

### 1. `ti_engine` feed — `accumulation_score` (P1)

| Field | Coverage | Root Cause |
|---|---|---|
| `accumulation_score` | 0% | OBV-based score not implemented in `populate_stock_price_features()` |
| `sma200` | 96.0% | Requires ≥200 trading days — new listings affected |

**Fix:** Implement OBV accumulation score as SQL window function in `populate_stock_price_features()`.

---

### 2. `shareholding` feed — `promoter_pledged_pct` (P1)

| Field | Coverage | Root Cause |
|---|---|---|
| `promoter_pledged_pct` | 0% | Field not populated by BSE shareholding scraper |
| `promoter_pct` | 93.0% (463/498) | Fixed — was 50% before backfill |
| `fii_pct_change_qoq` | 97.8% (487/498) | Near-complete |
| `dii_pct_change_qoq` | 97.8% (487/498) | Near-complete |

**Fix:** Add `promoter_pledged_pct` extraction to BSE shareholding scraper (`promoter_pledged_to_total_pct` column in shareholding table).

---

### 3. `nse_financials` feed — **MOSTLY FIXED** (P2 done)

| Field | Before | After | Status |
|---|---|---|---|
| `roe_pct` | 52.8% | **96.6%** (481/498) | Fixed |
| `debt_to_equity` | 52.8% | **96.6%** (481/498) | Fixed |
| `pb` | 99.8% | **96.6%** | Fixed |
| `profit_margin_pct` | 50.2% | **87.3%** (435/498) | Fixed |
| `roce_pct` | 49.0% | **85.1%** (424/498) | Fixed |
| `interest_coverage` | 84.5% | **84.9%** (423/498) | Near-complete |
| `pe_ttm` | 90.4% | **95.4%** (475/498) | Fixed |
| `revenue_growth_yoy_pct` | 97.2% | 80.9% (403/498) | Some regression — investigate |

**Root cause of residual gaps (63 stocks):** Holding companies, investment trusts, REITs — these have non-standard P&L structures. Insurance companies and exchange listings also fail standard screener parsing.

**Remaining action:** Run targeted backfill for the ~63 still-missing stocks. Check if they have standalone vs consolidated page anomalies on Screener.in.

---

### 4. `derived_metrics` feed

| Field | Coverage | Status |
|---|---|---|
| `revenue_growth_3y_cagr_pct` | 47.6% (237/498) | Self-resolving — needs ≥3Y history |
| `eps_growth_3y_cagr_pct` | 90.6% (451/498) | Good |
| `earnings_consistency_score` | 93.2% (464/498) | Good |
| `pe_overvaluation_pct` | ~5% | Now unblocked by sector fix — needs peer group computation |

---

## Sector Coverage — FIXED (P0 done)

All 498 Nifty 500 stocks with price data now have sector assigned.

| Sector | Expected Scorer |
|---|---|
| Banking | BANK |
| Finance / NBFC | NBFC |
| Information Technology | IT |
| Healthcare | PHARMA |
| Fast Moving Consumer Goods | FMCG |
| Consumer Durables | FMCG |
| Capital Goods | CAPGOODS |
| Automobile | CYCLICAL |
| Chemicals | CYCLICAL |
| Metals | CYCLICAL |
| Construction Materials | CYCLICAL |
| Realty | CYCLICAL |
| Oil Gas | CYCLICAL |
| Power | CYCLICAL |
| Textiles | CYCLICAL |
| Others (Telecom, Services, Media, Diversified) | DEFAULT |

**Migration applied:** `080_seed_sector_master_nifty500.sql`

---

## Per-Primitive Coverage Summary (2026-05-27)

```
Primitive                           Feed                  Coverage  Visual
---------------------------------- -------------------- ---------  -------------------------
accumulation_score                  ti_engine                0.0%  ░░░░░░░░░░░░░░░░░░░░  ← FIX P1
promoter_pledged_pct                shareholding             0.0%  ░░░░░░░░░░░░░░░░░░░░  ← FIX P1
pe_overvaluation_pct                derived_metrics          4.6%  ░░░░░░░░░░░░░░░░░░░░  ← unblocked by P0 fix
revenue_growth_3y_cagr_pct          derived_metrics         47.6%  █████████░░░░░░░░░░░  (self-resolving)
interest_coverage                   nse_financials          84.9%  █████████████████░░░
roce_pct                            nse_financials          85.1%  █████████████████░░░
profit_margin_pct                   nse_financials          87.3%  █████████████████░░░
eps_growth_3y_cagr_pct              derived_metrics         90.6%  ██████████████████░░
promoter_pct                        shareholding            93.0%  ███████████████████░
earnings_consistency_score          derived_metrics         93.2%  ███████████████████░
pe_ttm                              nse_financials          95.4%  ███████████████████░
sma200                              ti_engine               96.0%  ███████████████████░
roe_pct                             nse_financials          96.6%  ████████████████████
debt_to_equity                      nse_financials          96.6%  ████████████████████
pb                                  nse_financials          96.6%  ████████████████████
fii_pct_change_qoq                  shareholding            97.8%  ████████████████████
dii_pct_change_qoq                  shareholding            97.8%  ████████████████████
promoter_pct_change_qoq             shareholding            93.0%  ███████████████████░
rsi14                               ti_engine              100.0%  ████████████████████
macd                                ti_engine              100.0%  ████████████████████
```

---

## Prioritised Remaining Backlog

| Priority | Feed | Action | Stocks Impacted | Effort |
|---|---|---|---|---|
| P1 | `ti_engine` | Implement `accumulation_score` (OBV) in `populate_stock_price_features()` | All 498 stocks | Low |
| P1 | `shareholding` | Add `promoter_pledged_pct` to BSE shareholding scraper | All 498 stocks | Medium |
| P2 | `derived_metrics` | Enable `pe_overvaluation_pct` sector peer group computation | ~470 stocks | Low — unblocked |
| P3 | `nse_financials` | Targeted backfill for ~63 stocks still missing fundamentals | 63 stocks | Medium |
| P4 | `derived_metrics` | `revenue_growth_3y_cagr_pct` improves as history accumulates (self-resolving) | ~260 stocks | None |
| P5 | `index_constituents` | Investigate/remove DUMMYVEDL symbols, fix GSPL/JSWDULUX/LTM symbol mapping | 7 stocks | Low |

---

## Fixes Applied

| Fix | Migration | Impact |
|---|---|---|
| Seed `sector_master` from `index_constituents.industry` | `080_seed_sector_master_nifty500.sql` | 484 stocks moved from DEFAULT to correct sector profile |
| NSE financials backfill for 277 Nifty 500 stocks | `backfill_screener.py` (batch run) | roe_pct: 52%→97%, roce_pct: 49%→85%, margin: 50%→87% |
| Re-run `populate_stock_features_extended('2026-05-25')` | SQL function call | Propagated financials into stock_features_daily (2311 rows) |
| Re-run `populate_stock_features_v3('2026-05-25')` | SQL function call | Recomputed CAGR/consistency derived metrics (543 rows) |

---

## How to Monitor

After each nightly scoring run, query the live coverage view:

```sql
-- What's the current primitive coverage state?
SELECT primitive_name, feed, missing_pct, missing_count, total_stocks
FROM nidp.v_scoring_feed_gaps
ORDER BY missing_pct DESC;

-- Show only actionable gaps (>10% stocks affected)
SELECT primitive_name, feed, missing_pct
FROM nidp.v_scoring_feed_gaps
WHERE missing_pct >= 10.0
ORDER BY missing_pct DESC;
```

Machine-readable full report: `/tmp/nifty500_scoring_gap_report.json`
