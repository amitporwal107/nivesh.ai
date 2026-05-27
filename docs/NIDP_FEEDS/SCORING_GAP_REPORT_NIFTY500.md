# Nifty 500 — Scoring Primitive Coverage Gap Report
**Generated:** 2026-05-27  
**Primitives date:** 2026-05-25  
**Scope:** 505 Nifty 500 constituents

---

## Executive Summary

| Metric | Value |
|---|---|
| Total Nifty 500 stocks | 505 |
| Stocks with any primitives | 498 (98.6%) |
| **Stocks with zero primitive gaps** | **0 / 498 (0%)** |
| Fully covered stocks | 0 |
| Stocks classified as DEFAULT (no sector) | 484 / 498 (97.2%) |

**No stock in Nifty 500 is fully scored today.** Every stock has at least one missing primitive. The root causes are 4 broken/incomplete feeds and 1 missing sector classification source.

---

## Critical Gaps (>50% stocks affected)

| Primitive | Feed | Coverage | Action |
|---|---|---|---|
| `promoter_pledged_pct` | shareholding | **0%** | Pledging data not being written to `stock_features_daily` — BSE shareholding parser missing this field |
| `accumulation_score` | ti_engine | **0%** | TI engine not computing OBV-based accumulation score for any stock |
| `pe_overvaluation_pct` | derived_metrics | **4.6%** | `pe_vs_sector_pct` computation needs sector peer groups — blocked by sector tagging gap (see §5) |
| `revenue_growth_3y_cagr_pct` | derived_metrics | **31.1%** | 3Y CAGR requires ≥3 years of NSE financials history — many stocks don't have it yet |
| `roce_pct` | nse_financials | **49.0%** | ROCE not being parsed/written for ~255 stocks — Screener consolidated page parsing gap |
| `profit_margin_pct` | nse_financials | **50.2%** | Same root cause as `roce_pct` — P&L row parsing failure |
| `promoter_pct` | shareholding | **50.2%** | Shareholding data missing for ~249 stocks |
| `promoter_pct_change_qoq` | shareholding | **50.2%** | Derived from promoter_pct — same root cause |
| `roe_pct` | nse_financials | **52.8%** | Missing for ~235 stocks — ROE requires PAT + Equity from balance sheet |
| `debt_to_equity` | nse_financials | **52.8%** | Balance sheet data not parsed for ~235 stocks |
| `fii_pct_change_qoq` | shareholding | **53.2%** | FII QoQ change — shareholding feed gap |
| `dii_pct_change_qoq` | shareholding | **53.2%** | DII QoQ change — shareholding feed gap |

---

## Gap by Feed (Prioritised Repair Order)

### 1. `shareholding` feed — **498/498 stocks affected**
All 498 stocks are missing at least one shareholding primitive. This is the single highest-impact gap.

| Field | Coverage | Root Cause |
|---|---|---|
| `promoter_pledged_pct` | 0% | Field not populated by BSE shareholding scraper |
| `promoter_pct` | 50.2% | Shareholding data absent for ~249 stocks |
| `promoter_pct_change_qoq` | 50.2% | Derived from promoter_pct |
| `fii_pct_change_qoq` | 53.2% | FII quarterly change not computed |
| `dii_pct_change_qoq` | 53.2% | DII quarterly change not computed |

**Fix:** 
- Add `promoter_pledged_pct` extraction to BSE shareholding scraper
- Run shareholding backfill for Nifty 500 stocks where `promoter_pct IS NULL`
- Add QoQ change computation to derived_metrics pipeline

---

### 2. `ti_engine` feed — **498/498 stocks affected**

| Field | Coverage | Root Cause |
|---|---|---|
| `accumulation_score` | 0% | Not implemented in `populate_stock_price_features()` |
| `sma200` | 96.0% | Requires ≥200 trading days of price history — new listings affected |

**Fix:**
- Implement OBV-based `accumulation_score` in `populate_stock_price_features()` (SQL or Python)
- `sma200` gap is self-resolving as price history accumulates

---

### 3. `nse_financials` feed — **277/498 stocks affected**

| Field | Coverage | Root Cause |
|---|---|---|
| `roce_pct` | 49.0% | EBIT / Capital Employed not being computed for ~255 stocks |
| `profit_margin_pct` | 50.2% | PAT Margin not written for ~249 stocks |
| `roe_pct` | 52.8% | ROE not written for ~235 stocks |
| `debt_to_equity` | 52.8% | Balance sheet row parse failures |
| `interest_coverage` | 84.5% | EBIT/Interest not computed — fewer stocks affected |
| `pe_ttm` | 90.4% | Generally good coverage |
| `revenue_growth_yoy_pct` | 97.2% | Near-complete |
| `pb` | 99.8% | Near-complete |

**Root cause pattern:** Balance sheet and P&L fundamentals are missing for stocks where the `nse_financials` Screener page returns data in a non-standard format (e.g. holding companies, insurance companies misclassified as DEFAULT).

**Fix:**
- Audit the `nse_financials` backfill for the ~250 stocks with null P&L fields
- Run `python -m nidp.services.nse_financials.backfill --symbols <affected-list>` 
- Check if these stocks have consolidated vs standalone page anomalies (like banks had for NPA)

---

### 4. `derived_metrics` feed — **475/498 stocks affected**

| Field | Coverage | Root Cause |
|---|---|---|
| `pe_overvaluation_pct` | 4.6% | Requires sector peer group → blocked by sector tagging gap |
| `revenue_growth_3y_cagr_pct` | 31.1% | Needs ≥3 years NSE financials history |
| `eps_growth_3y_cagr_pct` | 91.0% | Better covered — EPS easier to compute |
| `earnings_consistency_score` | 93.4% | Near-complete |

**Fix:**
- `pe_overvaluation_pct`: unblocked once sector tagging gap (#5 below) is fixed
- `revenue_growth_3y_cagr_pct`: run historical backfill for stocks with ≥3Y of financials data

---

## Sector Tagging Gap — Root Cause of DEFAULT Profile

**97.2% of Nifty 500 stocks are scoring under the DEFAULT profile** because `sector_master` only has 2 sectors tagged:

| Sector | Stocks in sector_master |
|---|---|
| BANKING | 14 |
| IT | 9 |
| **All others** | **0** |

However, `index_constituents.industry` has **NSE GICS industry labels for all 505 stocks**:

| NSE Industry Label | Count | Maps to Scorer |
|---|---|---|
| Financial Services | 101 | NBFC + BANK (needs sub-split) |
| Capital Goods | 63 | CAPGOODS |
| Healthcare | 49 | PHARMA |
| Automobile and Auto Components | 38 | CYCLICAL |
| Fast Moving Consumer Goods | 28 | FMCG |
| Information Technology | 27 | IT |
| Chemicals | 26 | CYCLICAL |
| Metals & Mining | 20 | CYCLICAL |
| Construction Materials | 11 | CYCLICAL |
| Realty | 11 | CYCLICAL |

**Fix:** Populate `sector_master` from `index_constituents.industry` using the NSE→scoring-profile mapping. This will:
1. Route 101 Financial Services stocks to BANK/NBFC (fix stock sub-tagging using bank keywords)
2. Route 63 Capital Goods stocks to CAPGOODS scorer
3. Route 49 Healthcare stocks to PHARMA scorer
4. Route ~125 cyclical stocks (Auto + Metals + Chemicals + Construction) to CYCLICAL scorer
5. Route 28 FMCG stocks to FMCG scorer
6. Route 27 IT stocks to IT scorer (14 already tagged)
7. Unblock `pe_overvaluation_pct` which requires sector peers

---

## Stocks with No Primitives at All (7 stocks)

These 7 Nifty 500 stocks have **zero rows** in `stock_features_daily` and will produce no score:

```
DUMMYVEDL1  DUMMYVEDL2  DUMMYVEDL3  DUMMYVEDL4  GSPL  JSWDULUX  LTM
```

- `DUMMYVEDL1–4`: Likely placeholder/test symbols in `index_constituents` — verify and remove
- `GSPL`: Gujarat State Petronet — check if NSE symbol mapping is correct
- `JSWDULUX`: May have been recently added to Nifty 500 / no price history yet
- `LTM`: Recently listed or symbol mismatch — needs investigation

---

## Per-Primitive Coverage Summary

```
Primitive                           Feed                  Coverage  Visual
---------------------------------- -------------------- ---------  -------------------------
promoter_pledged_pct                shareholding             0.0%  ░░░░░░░░░░░░░░░░░░░░  ← FIX
accumulation_score                  ti_engine                0.0%  ░░░░░░░░░░░░░░░░░░░░  ← FIX
pe_overvaluation_pct                derived_metrics          4.6%  ░░░░░░░░░░░░░░░░░░░░  ← FIX
revenue_growth_3y_cagr_pct          derived_metrics         31.1%  ██████░░░░░░░░░░░░░░  ← FIX
roce_pct                            nse_financials          49.0%  █████████░░░░░░░░░░░  ← FIX
profit_margin_pct                   nse_financials          50.2%  ██████████░░░░░░░░░░  ← FIX
promoter_pct                        shareholding            50.2%  ██████████░░░░░░░░░░  ←
promoter_pct_change_qoq             shareholding            50.2%  ██████████░░░░░░░░░░  ←
roe_pct                             nse_financials          52.8%  ██████████░░░░░░░░░░  ←
debt_to_equity                      nse_financials          52.8%  ██████████░░░░░░░░░░  ←
fii_pct_change_qoq                  shareholding            53.2%  ██████████░░░░░░░░░░  ←
dii_pct_change_qoq                  shareholding            53.2%  ██████████░░░░░░░░░░  ←
interest_coverage                   nse_financials          84.5%  ████████████████░░░░
pe_ttm                              nse_financials          90.4%  ██████████████████░░
eps_growth_3y_cagr_pct              derived_metrics         91.0%  ██████████████████░░
earnings_consistency_score          derived_metrics         93.4%  ██████████████████░░
sma200                              ti_engine               96.0%  ███████████████████░
revenue_growth_yoy_pct              nse_financials          97.2%  ███████████████████░
pb                                  nse_financials          99.8%  ███████████████████░
```

---

## Prioritised Fix Backlog

| Priority | Feed | Action | Stocks Unblocked | Effort |
|---|---|---|---|---|
| P0 | `sector_master` | Seed from `index_constituents.industry` using NSE→profile map | 484 stocks get correct profile | Low — SQL migration |
| P1 | `shareholding` | Add `promoter_pledged_pct` to BSE scraper + run backfill | All 498 stocks | Medium |
| P1 | `ti_engine` | Implement `accumulation_score` in `populate_stock_price_features()` | All 498 stocks | Low |
| P2 | `nse_financials` | Backfill P&L + balance sheet for ~250 stocks with null fundamentals | ~250 stocks | High |
| P2 | `derived_metrics` | Fix `revenue_growth_3y_cagr_pct` for stocks with ≥3Y history available | ~150 stocks | Medium |
| P3 | `derived_metrics` | Enable `pe_overvaluation_pct` after sector tagging is fixed | ~470 stocks | Low — unblocked by P0 |
| P4 | `index_constituents` | Investigate/remove DUMMYVEDL symbols, fix GSPL/JSWDULUX/LTM symbol mapping | 7 stocks | Low |

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

The scoring engine also logs `WARNING` lines for every primitive missing in >10% of stocks:
```
v3_scores_engine[coverage]: 'accumulation_score' missing for 100.0% of stocks (feed: ti_engine) — fix the ti_engine ingester
```

Machine-readable full report: `/tmp/nifty500_scoring_gap_report.json`
