# Strategy Builder — Project Plan

> Multi-asset (stock + MF) strategy authoring on top of NIDP. Reuses
> ~70% of existing positional_engine + V3 + NIDP. Zero paid data
> dependencies — every primitive sourced from NSE / AMFI / NSDL / RBI /
> Yahoo / FRED. Total est. **14–16 weeks** for full feature,
> **3–4 weeks** for usable MVP.
>
> Last revised: 2026-05-05

---

## 0 · Goals & non-goals

**Goals**
- User-authored strategies for **stocks and mutual funds**, not just admin-curated picks
- Survivorship-bias-free backtests using `nidp.index_constituents` history (stocks) and AMFI scheme-active history (funds)
- Same provenance discipline as NIDP (run_id, as_of_date carry-forward, validation gating) for every primitive — including legacy AMFI/mfapi feeds, which get migrated into NIDP
- AI Copilot drafts a strategy from natural language (Phase 4)
- **Zero recurring data cost** — all primitives from regulator/exchange free feeds

**Non-goals (v1)**
- Live broker execution — Kite Connect deferred
- Intraday strategies — daily timeframe only
- Options / F&O strategies — equity cash + MF only
- Public strategy sharing with moderation — private only in MVP
- News / sentiment overlays — Phase 5 nice-to-have

**Success metrics**
- 50+ user-authored strategies in 30 days post-launch
- Backtest p99 < 5s on Nifty 500 × 3 yrs (stocks); < 3s on full MF universe × 3 yrs
- Strategy → live signals pipeline matches positional_engine accuracy on shared templates (regression test)
- Zero paid-data invoices

---

## 1 · Data layer — what's wired vs. what's missing (all free sources)

### Stock primitives (NSE + Yahoo)
| Primitive | Source | URL/feed | Status |
|---|---|---|---|
| OHLCV (daily) | NSE bhavcopy | nseindia.com archives | ✅ `nidp.prices_eod` |
| Delivery % | NSE sec_bhavdata | nseindia.com archives | ✅ `nidp.delivery_data` |
| Index OHLC + PE/PB/DY | NSE ind_close_all | nseindia.com archives | ✅ `nidp.index_eod` |
| Point-in-time index membership | NSE | nseindia.com indices archive | ✅ `nidp.index_constituents` |
| FII/DII aggregate flows | NSE fii_stats | nseindia.com daily reports | ✅ `nidp.fii_dii_flows` |
| Bulk + block deals | NSE | nseindia.com archives | ✅ `nidp.bulk_deals` / `nidp.block_deals` |
| Corporate actions (incl. board meetings = earnings) | NSE CA feed | nseindia.com CA | ✅ `nidp.corporate_actions` |
| RBI yields (multi-tenor) | RBI ref-rate archive | rbi.org.in | ✅ `nidp.rbi_yields` |
| Trading calendar | NSE | nseindia.com holiday master | ✅ `nidp.nse_holidays` |
| Long-history OHLCV backfill | Yahoo Finance | yfinance | ✅ `nidp/services/yfinance_backfill/` |
| US macro (DXY, US10Y, etc.) | FRED | api.stlouisfed.org | ✅ `nidp/services/fred_macro/` |
| **Quarterly financials (P&L, BS, EPS, ROE, P/E)** | NSE XBRL Financial Results | nseindia.com/companies-listing/corporate-filings-financial-results | ❌ **Phase 2 build** |
| **Quarterly shareholding (promoter/FII/DII/public %)** | NSE XBRL Shareholding | nseindia.com/companies-listing/corporate-filings-shareholding-pattern | ❌ **Phase 2 build** |
| **Adjusted-close (split/bonus/dividend)** | derived from `corporate_actions` (+ already in yfinance Adj Close) | local | ❌ **Phase 2 — column add + derivation** |
| **Sector/industry classification** | NSE Equity Master CSV | nseindia.com EQUITY_L.csv | ❌ **Phase 2 build** (small) |
| **Free-float mcap** | IISL factors | niftyindices.com | ❌ **Phase 2 build** (small) |
| **Earnings calendar (computed)** | filter `corporate_actions` | local view | ❌ **Phase 2 — SQL view only** |

### Mutual fund primitives (AMFI + AMC + AMFI flows)
| Primitive | Source | URL/feed | Status |
|---|---|---|---|
| Daily NAV (all schemes) | AMFI portal | portal.amfiindia.com/spages/NAVAll.txt | ⚠️ Legacy `services/amfi_nav.py` — **canonicalise into NIDP, Phase 2** |
| Scheme master (AMC, category, ISINs, expense ratio, dates) | AMFI scheme master | portal.amfiindia.com | ⚠️ Legacy hydrator — migrate |
| NAV history per scheme | mfapi.in | api.mfapi.in/mf | ⚠️ Legacy `fund_performance.py` — migrate |
| Scheme returns (1Y / 3Y / 5Y vs category) | derived in V3 | local | ✅ `services/v3_scoring.py` |
| Risk metrics (Sharpe / Sortino / DD) | derived in V3 | local | ✅ V3 |
| **Portfolio holdings (top-N stocks per scheme)** | AMC monthly disclosures | each AMC website (SEBI-mandated free) | ❌ **Phase 2 build** |
| **AUM history per scheme** | AMFI quarterly AUM data | amfiindia.com/research-information/aum-data | ❌ **Phase 2 build** |
| **Manager tenure / changes** | AMFI Scheme Information Documents | amfi SID PDFs | ❌ **Phase 2 build** |
| **Inflow/outflow (category-level)** | AMFI monthly | amfiindia.com/research-information/other-data | ❌ **Phase 3** |

### NSDL primitives (free reports)
| Primitive | Source | URL/feed | Status |
|---|---|---|---|
| **FPI per-stock holdings (monthly)** | NSDL FPI Reports | fpi.nsdl.co.in/web/Reports | ❌ **Phase 2 build** — fixture present at `tests/test_data/nsdl/` |
| **FPI category breakdown** | NSDL daily statistics | fpi.nsdl.co.in | ❌ **Phase 3** |
| **DP-aggregate holdings** | NSDL monthly | fpi.nsdl.co.in | ❌ **Phase 3** |

**Bottom line:** 11 NIDP ingesters today → ~18–19 after Phase 2. Every gap closed by a free, regulator-published source. No paid feeds, no vendor risk.

---

## 2 · Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│ Frontend (React)                                                     │
│  /strategy-builder                                                   │
│   StepUniverse → StepStrategy → StepScreen → StepBacktest →         │
│                                              StepExecute             │
│  Asset toggle: STOCK | MF — drives universe options + DSL grammar   │
│  AICopilotPanel (Phase 4)                                            │
└────────────────────────────┬────────────────────────────────────────┘
                             │ REST
┌────────────────────────────▼────────────────────────────────────────┐
│ Backend                                                              │
│  routes/strategy_builder.py        — CRUD + run orchestration       │
│  services/strategy_engine/                                           │
│    ├── dsl.py            — JSON DSL parser + validator (multi-asset)│
│    ├── compiler_stock.py — DSL → SQL on stock snapshots             │
│    ├── compiler_mf.py    — DSL → SQL on MF snapshots                │
│    ├── runner.py         — daily strategy execution                 │
│    ├── backtest.py       — historical sweep over NIDP               │
│    ├── scoring_stock.py  — stock V3-style composite                 │
│    ├── scoring_mf.py     — wraps existing services/v3_scoring.py    │
│    └── alerts.py         — email / webhook dispatch                 │
│  services/copilot/strategy_drafter.py  (Phase 4, Anthropic SDK)     │
└────────────────────────────┬────────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────────┐
│ NIDP (canonical AS-OF substrate, all free sources)                  │
│  STOCK existing:    prices_eod · delivery · fii_dii · index_eod ·   │
│                     index_constituents · corporate_actions ·       │
│                     bulk_deals · block_deals · rbi_yields ·         │
│                     nse_holidays · stock_daily_snapshot ·           │
│                     market_daily_snapshot · fred_macro              │
│  MF legacy → NIDP:  amfi_nav · scheme_master · scheme_nav_history   │
│  PHASE 1 NEW:       stock_features_daily                             │
│  PHASE 2 NEW (stock): nse_financials_quarterly · shareholding_pattern│
│                       prices_eod_adjusted · sector_master ·         │
│                       free_float_factors · v_earnings_calendar      │
│  PHASE 2 NEW (MF):    mf_amc_portfolios · mf_aum_history ·          │
│                       mf_manager_history                             │
│  PHASE 2 NEW (NSDL):  nsdl_fpi_holdings                              │
│  STRATEGY:          user_universes · strategies · strategy_versions │
│                     strategy_runs · strategy_trades ·                │
│                     strategy_signals · strategy_alerts · audit       │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3 · Phase plan

### Phase 1 — Foundation MVP (3–4 weeks)
**Goal:** stock-only strategies on Nifty universes with technicals. MF deferred to Phase 2.

| # | Ticket | Files | Effort |
|---|---|---|---|
| 1.1 | Strategy core tables | `nidp/migrations/020_strategy_builder_core.sql` — `strategies`, `strategy_versions`, `strategy_runs`, `strategy_trades`, `user_universes` (with `asset_class` enum: STOCK/MF) | 0.5d |
| 1.2 | Stock features snapshot | `nidp/migrations/021_stock_features_daily.sql` — `nidp.stock_features_daily(symbol, as_of_date, rsi14, atr_pct, bb_width, vol_z20, deliv_trend10, sma50_slope, dist_52w_high, dist_200dma, accumulation_score, …)` | 0.5d |
| 1.3 | Feature snapshot builder | `nidp/services/feature_snapshotter/` — daily job, calls `services/positional_engine/feature_calculator.py`, writes one row per (symbol, date) | 2d |
| 1.4 | Avro contract | `nidp/contracts/stock_features_daily_v1.avsc` | 0.25d |
| 1.5 | DSL spec + validator | `services/strategy_engine/dsl.py` — JSON schema, multi-asset grammar, `validate_strategy(spec) → list[Error]` | 2d |
| 1.6 | Stock compiler | `services/strategy_engine/compiler_stock.py` — DSL → parameterised SQL against `stock_features_daily` ⋈ `stock_daily_snapshot` | 3d |
| 1.7 | 5 stock templates | `services/strategy_engine/templates/{momentum_breakout,accumulation,mean_reversion,div_yield,vol_breakout}.json` | 1d |
| 1.8 | Backtest runner | `services/strategy_engine/backtest.py` — sweep date range, simulate entries/exits with SL/target, record trades + slippage + brokerage | 4d |
| 1.9 | Routes | `routes/strategy_builder.py` — `POST /strategies`, `GET /strategies/{id}`, `POST /strategies/{id}/backtest`, `GET /universes`, `GET /templates` | 2d |
| 1.10 | Tests | DSL + compiler determinism + backtest correctness (golden Nifty50 90d) | 2d |
| 1.11 | Frontend wizard | `pages/StrategyBuilder.jsx` + 5 step components, asset-class toggle, localStorage persistence | 4d |
| 1.12 | Backtest results UI | Equity-curve chart (recharts), trades table, metrics card | 3d |

**Phase 1 deliverable:** /strategy-builder route, 5 stock templates, save/load, backtest. **~22 person-days.**

---

### Phase 2 — Multi-asset data depth (5–7 weeks)
**Goal:** MF support, stock fundamentals via NSE XBRL, adjusted prices, NSDL FPI per-stock. Three lanes run in parallel.

#### Lane 2A — Stock fundamentals + adjustments (free NSE feeds)
| # | Ticket | Files | Effort |
|---|---|---|---|
| 2A.1 | NSE XBRL financials ingester | `nidp/services/nse_financials/` — pulls quarterly XBRL filings, parses revenue / EBITDA / PAT / EPS / segment / balance sheet items → `nidp.nse_financials_quarterly(symbol, period_end, revenue_cr, ebitda_cr, pat_cr, eps, book_value, net_debt_cr, …)` | 7d |
| 2A.2 | Derived ratios view | `nidp.v_stock_fundamentals_latest(symbol, pe_ttm, pb, roe, roce, de, eps_growth_yoy, revenue_growth_yoy, mcap_cr)` — joins financials with prices_eod close | 1d |
| 2A.3 | Migration + Avro | `nidp/migrations/022_nse_financials.sql`, `nidp/contracts/nse_financials_v1.avsc` | 0.5d |
| 2A.4 | NSE shareholding XBRL ingester | `nidp/services/nse_shareholding/` — quarterly XBRL → `nidp.shareholding_pattern(symbol, period_end, promoter_pct, fii_pct, dii_pct, public_pct, mf_pct, insurance_pct, …)` | 4d |
| 2A.5 | Adjusted-close derivation | `nidp/services/price_adjuster/` — applies `corporate_actions` ratios backward; cross-checks against yfinance Adj Close (already in our backfill payload). Materialises `nidp.prices_eod_adjusted` | 3d |
| 2A.6 | Sector master ingester | `nidp/services/nse_equity_master/` — daily NSE EQUITY_L.csv → `nidp.sector_master(symbol, sector, industry, industry_new, listing_date)` | 1d |
| 2A.7 | Free-float factors ingester | `nidp/services/iisl_freefloat/` — quarterly NIFTY index methodology factors → `nidp.free_float_factors(symbol, factor, effective_from)` | 2d |
| 2A.8 | Earnings calendar view | `nidp/migrations/v_earnings_calendar.sql` — SQL view over `corporate_actions` filtered to BOARD_MEETING with results-related purpose | 0.5d |
| 2A.9 | Snapshot join | `nidp/services/snapshot_builder/stock_builder.py` — join all new fundamentals/shareholding/sector into `stock_daily_snapshot` | 2d |
| 2A.10 | Stock V3 scoring | `services/strategy_engine/scoring_stock.py` — Trend / Value / Quality / Momentum / Institutional composites with V3-style weight redistribution | 4d |

#### Lane 2B — MF data (canonicalise legacy + add holdings/AUM/managers)
| # | Ticket | Files | Effort |
|---|---|---|---|
| 2B.1 | MF NIDP migrations | `nidp/migrations/023_mf_core.sql` — `mf_scheme_master`, `mf_nav_daily`, `mf_amc_portfolios`, `mf_aum_history`, `mf_manager_history` | 1d |
| 2B.2 | AMFI NAV ingester (NIDP-ised) | `nidp/services/amfi_nav/` — pulls AMFI NAVAll.txt, validates, writes append-only with `source_run_id`. Existing `services/amfi_nav.py` becomes thin reader | 3d |
| 2B.3 | Scheme master ingester | `nidp/services/amfi_scheme_master/` — quarterly + on-event refresh of AMC, category, ISINs, expense ratio | 2d |
| 2B.4 | NAV history backfill | `nidp/services/mfapi_history/` — one-shot backfill from mfapi.in, then daily delta | 3d |
| 2B.5 | AMC monthly portfolios ingester | `nidp/services/mf_amc_portfolios/` — fetches each AMC's monthly disclosure (PDF/XLSX) → `mf_amc_portfolios(scheme_code, period_end, symbol, holding_pct, mcap_cr)`. **~28 AMCs, schema variance is the time sink** | 10d |
| 2B.6 | AMFI AUM history ingester | `nidp/services/amfi_aum/` — quarterly AUM data XLSX → `mf_aum_history(scheme_code, period_end, aum_cr)` | 3d |
| 2B.7 | Manager history ingester | `nidp/services/amfi_managers/` — SID PDF parser → `mf_manager_history(scheme_code, manager, from_date, to_date)` | 5d |
| 2B.8 | MF compiler | `services/strategy_engine/compiler_mf.py` — DSL → SQL on MF snapshots | 3d |
| 2B.9 | MF V3 wrapper | `services/strategy_engine/scoring_mf.py` — wraps `services/v3_scoring.py` so the same DSL `composite_score` works on funds | 1d |
| 2B.10 | 4 MF templates | `top_quartile_quality`, `low_overlap_complement`, `manager_continuity`, `aum_consistency` | 1d |

#### Lane 2C — NSDL FPI
| # | Ticket | Files | Effort |
|---|---|---|---|
| 2C.1 | NSDL FPI ingester | `nidp/services/nsdl_fpi/` — beneficiary-position PDFs/CSVs from fpi.nsdl.co.in → `nidp.nsdl_fpi_holdings(symbol, as_of_date, fpi_holding_pct, fpi_holding_qty)`. Fixture lives at `tests/test_data/nsdl/` | 8d |
| 2C.2 | Migration + Avro | `nidp/migrations/024_nsdl.sql`, contract | 0.5d |
| 2C.3 | DSL extension | Add `institutional.*` namespace covering NSE FII aggregate + NSDL per-stock + delivery trend | 1d |

#### Lane 2D — UI + integration
| # | Ticket | Files | Effort |
|---|---|---|---|
| 2D.1 | DSL grammar v2 | Adds `fundamentals.*`, `shareholding.*`, `mf.*`, `institutional.*`, `sector.*`; compiler routes by namespace | 2d |
| 2D.2 | Universe management UI | `StepUniverse.jsx` — paste tickers, save; "My Universes" list; MF universe by category/AMC | 3d |
| 2D.3 | Screen step UI | `StepScreen.jsx` — 14 condition cards (incl. MF-specific manager_tenure, AUM range, expense ratio) | 4d |
| 2D.4 | Asset-class-aware backtest UI | Stocks: per-trade entry/exit. MF: monthly rebalance + tracking error vs benchmark | 2d |
| 2D.5 | Tests | Ingester smoke + adjuster correctness against 5 known split events; AMC PDF parser fixture tests; NSDL parser fixture tests | 4d |

**Phase 2 deliverable:** stock fundamentals + shareholding + adjusted prices + full MF data + NSDL FPI; user can build "P/E < 25 AND ROE > 18% AND FPI Δ > 0.5pp QoQ AND breaking 200DMA" *or* "MF in equity-largecap with 5y manager tenure, top-quartile risk-adj returns, AUM > ₹5kCr". **~80 person-days across 3 parallel lanes (≈ 5–6 calendar weeks with 3 devs).**

---

### Phase 3 — Activation (3–4 weeks)
**Goal:** strategies generate daily signals, send alerts, integrate with watchlist + GTT export. MF-specific signals (rebalance triggers, switch suggestions).

| # | Ticket | Files | Effort |
|---|---|---|---|
| 3.1 | Daily strategy runner | `services/strategy_engine/runner.py` — APScheduler 18:45 IST (stocks) + 21:00 IST (MF post-NAV publication); writes `strategy_signals` | 3d |
| 3.2 | Migration | `nidp/migrations/025_strategy_signals.sql` | 0.25d |
| 3.3 | Alerts dispatcher | `services/strategy_engine/alerts.py` — email + Telegram + webhook; idempotent on (strategy_id, signal_id, channel) | 4d |
| 3.4 | Alerts UI | `StepExecute.jsx` — channel toggles, threshold settings, notification preview | 2d |
| 3.5 | Watchlist integration | "Add all signals to watchlist" — reuse existing watchlist | 1d |
| 3.6 | GTT CSV export (stocks) | Zerodha-format CSV: symbol, txn_type, qty, trigger, limit, sl, tgt | 1d |
| 3.7 | MF action plan | "Switch fund X → Y" generator using V3's existing Switch formula | 2d |
| 3.8 | Strategy dashboard | `StrategyDashboard.jsx` — live perf per saved strategy: today's signals, trailing 30d hit rate, equity since saved | 4d |
| 3.9 | Audit log | `nidp/migrations/026_strategy_audit.sql` — `strategy_audit(strategy_id, action, actor, prev_def, new_def, ts)` | 1d |
| 3.10 | Public templates promotion | Admin marks `is_public_template=true` → appears in template gallery | 2d |
| 3.11 | AMFI flows ingester | `nidp/services/amfi_flows/` — monthly category-level inflow/outflow for sector-rotation context | 2d |
| 3.12 | Tests | E2E: create strategy → run cron → assert email sent → assert signal in DB | 2d |

**Phase 3 deliverable:** strategies fire nightly across stocks + MF, users get notified, results tracked. **~24 person-days.**

---

### Phase 4 — AI Copilot + polish (3 weeks)

| # | Ticket | Files | Effort |
|---|---|---|---|
| 4.1 | Anthropic SDK integration | `services/copilot/strategy_drafter.py` — Haiku 4.5, prompt-cached system describing DSL grammar (stock + MF + institutional + sector), 9 template examples; returns DSL JSON | 5d |
| 4.2 | Copilot endpoint | `POST /api/copilot/draft-strategy { prompt, asset_class }` → strategy spec; rate-limited 25/user/month | 1d |
| 4.3 | Copilot UI | `AICopilotPanel.jsx` — natural-language input, draft preview, "use this" inserts into wizard | 2d |
| 4.4 | Walk-forward backtest | Train 2y, test 6m, roll. Reports stable-vs-overfit per template | 3d |
| 4.5 | Performance | Materialised view for last-90d feature window; query plan tuning on hot paths | 3d |
| 4.6 | Public sharing (gated) | `is_public` + admin moderation queue; share-link tokens | 3d |

**Phase 4 deliverable:** Copilot, walk-forward, sharing. **~17 person-days.**

---

## 4 · Migrations summary

```
nidp/migrations/
  020_strategy_builder_core.sql       (Phase 1)
  021_stock_features_daily.sql        (Phase 1)
  022_nse_financials.sql              (Phase 2A)
  023_mf_core.sql                     (Phase 2B)
  024_nsdl.sql                        (Phase 2C)
  025_strategy_signals.sql            (Phase 3)
  026_strategy_audit.sql              (Phase 3)
  + small additions for shareholding, adjusted_close, sector_master,
    free_float_factors, mf_amc_portfolios, mf_aum_history,
    mf_manager_history, amfi_flows
```

All append-only with `source_run_id` + `ingested_at`, hypertable-converted on time dims, validation findings gated for snapshot inclusion.

---

## 5 · DSL spec (locked in Phase 1)

```jsonc
// Stock strategy
{
  "version": "1",
  "asset_class": "STOCK",
  "name": "Quality Breakout with FPI Tailwind",
  "universe": { "type": "index", "ref": "NIFTY500" },
  "entry": {
    "all_of": [
      { "feature": "rsi14", "op": ">", "value": 55 },
      { "feature": "close", "op": ">", "compare_to": "sma200" },
      { "feature": "vol_z20", "op": ">", "value": 1.5 },
      { "fundamental": "roe", "op": ">", "value": 15 },
      { "fundamental": "pe_ttm", "op": "<", "compare_to": "sector_median_pe" },
      { "shareholding": "fii_pct_change_qoq", "op": ">", "value": 0.5 },
      { "institutional": "fpi_holding_pct_change_mom", "op": ">", "value": 0.3 },
      { "sector": "in", "value": ["BANKING","IT","PHARMA"] }
    ]
  },
  "exit": { "stoploss_pct": 6, "target_rr": 2.5, "max_hold_days": 30, "trailing_atr_mult": 2.5 },
  "ranking": { "by": "composite_score", "limit": 10 },
  "rebalance": "daily"
}

// MF strategy
{
  "version": "1",
  "asset_class": "MF",
  "name": "Quality Largecap with Manager Continuity",
  "universe": { "type": "category", "ref": "EQUITY_LARGECAP" },
  "entry": {
    "all_of": [
      { "mf": "manager_tenure_years", "op": ">=", "value": 5 },
      { "mf": "aum_cr", "op": ">=", "value": 5000 },
      { "mf": "v3_quality_score", "op": ">=", "value": 75 },
      { "mf": "expense_ratio", "op": "<", "compare_to": "category_median" },
      { "mf": "portfolio_overlap_with_user", "op": "<", "value": 0.4 }
    ]
  },
  "ranking": { "by": "v3_quality_score", "limit": 10 },
  "rebalance": "monthly"
}
```

Compiler dispatches by `asset_class` to `compiler_stock.py` or `compiler_mf.py`. Both emit SQL against NIDP snapshots.

---

## 6 · Risks & mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| NSE XBRL schema drift across companies | High | Versioned parser; per-company override table; treat parse failures as WARN findings (carry-forward last-known) |
| AMC PDF schema variance (28+ AMCs) | High | Per-AMC adapter; buffer 10d in 2B.5; if one AMC breaks, those schemes drop out of MF strategies until fixed (graceful degradation) |
| NSDL PDF schema drift | Medium | Versioned parser; fixture-locked tests; tolerate skipped dates with WARN findings |
| Backtest survivorship bias (stocks) | High | Already mitigated — `nidp.index_constituents` is point-in-time |
| Backtest survivorship bias (MF) | High | AMFI scheme master tracks active dates; closed schemes retained for backtest |
| Adjusted-close errors silently corrupt stock backtests | High | Cross-check derived adjusted-close against yfinance Adj Close (already in our backfill payload); golden-dataset test on 5 known splits/bonuses; assert exact match |
| MF backtest realism (entry/exit at NAV publication day) | Medium | Document T+1 settlement convention; show in UI |
| LLM-drafted strategies are nonsense | Medium | DSL validator rejects malformed; backtest required before "save" enables |
| User strategies overload DB | Medium | Cron runs strategies in batches with concurrency=4; rate-limit per-user runs |
| Compliance framing of stock + MF "recommendations" | High — not tech | Legal review before public sharing; persistent "not investment advice" disclaimer; honour SEBI RIA boundary |
| Migrating legacy AMFI/mfapi services creates regressions | Medium | Phase 2B.2 keeps `services/amfi_nav.py` as a thin reader against NIDP — old call sites untouched |
| Free-data scraping rate limits / IP blocks | Medium | Respect robots.txt; jittered delays; rotate User-Agent; backoff on 429; persistent retry queue |

---

## 7 · Critical-path dependencies

```
Phase 1.5 (DSL) ──► 1.6 (stock compiler) ──► 1.8 (backtest) ──► 1.12 (UI)
                  ↘ 2D.1 (DSL v2) ──► 2A.10 (stock V3 scoring)
                                  ──► 2B.8 (MF compiler) ──► 2B.9 (MF V3 wrapper)

Phase 2A.1 (financials) ──► 2A.2 (ratios view) ──► 2A.10 (V3 scoring)
Phase 2A.5 (adjusted close) ──► all stock backtest correctness
Phase 2B.2 (AMFI ingester) ──► 2B.4 (mfapi history) ──► 2B.8 (MF compiler)
Phase 2B.5 (AMC portfolios) — independent risk; if blocked, ship MF templates that don't need holdings (returns/risk-only)
Phase 2C.1 (NSDL) — independent; falls back to NSE FII aggregate if blocked

Phase 3.1 (runner) ──► 3.3 (alerts) ──► 3.8 (dashboard)
Phase 4.1 (copilot) — independent; can start any time after 1.5 (DSL locked)
```

Hard serialisation: **DSL spec → compilers → backtest**. Lock DSL grammar in week 1.

The three Phase 2 lanes (2A stock, 2B MF, 2C NSDL) are independent and parallelisable.

---

## 8 · Sequencing recommendation

| Week | Deliverable |
|---|---|
| 1–4 | Phase 1 — stock foundation MVP. Internal demo at end of week 4. |
| 5–10 | Phase 2 — three parallel lanes (2A stock fundamentals, 2B MF, 2C NSDL). Lane 2A finishes ~week 8, Lane 2B finishes ~week 10, Lane 2C finishes ~week 8. UI integration (2D) overlaps weeks 9–10. |
| 11–14 | Phase 3 activation. Soft-launch 10 users at week 13, public week 14. |
| 15–17 | Phase 4 Copilot + sharing (optional — can ship public without it). |

**Total: 14 weeks to public, 17 weeks with Copilot/sharing.**

With 3 devs running Phase 2 lanes in parallel, the path is tight but achievable. With 1 dev, Phase 2 stretches to ~10 weeks and total push to ~20.

---

## 9 · Open decisions to lock before kickoff

1. **DSL format:** JSON (proposed) vs YAML — recommend **JSON** (cleaner LLM target, validates with JSON Schema)
2. **Public strategies:** ship MVP private-only? — recommend **yes**, moderation is a separate problem
3. **Backtest realism:** simulate slippage + brokerage from day 1? — recommend **day 1, ₹20 + 0.05% per side for stocks; ₹0 + exit-load for MF**, otherwise numbers lie
4. **Daily-only?** — confirm we are *not* doing intraday — recommend **confirm yes**
5. **NSDL ingestion priority:** drop to Phase 3 if PDF parsing variance materialises — fallback covered by NSE FII aggregate
6. **Migrate legacy MF services into NIDP?** — recommend **migrate** so all primitives share the same provenance discipline; the plan does this in 2B.2 with backward-compatible thin readers (existing call sites untouched)
7. **AMC portfolio ingester risk strategy:** start with 5 largest AMCs (HDFC / SBI / ICICI / Nippon / Axis) covering ~60% of AUM — ship MF strategies on day 1 even if long-tail AMCs are still being onboarded

---

## 10 · Operating cost projection

| Item | Cost |
|---|---|
| Data feeds (NSE / AMFI / NSDL / RBI / FRED / Yahoo) | **₹0/yr** — all free regulator/exchange/public sources |
| Anthropic API (Phase 4 Copilot, Haiku 4.5, ~25 calls/user/month, 1000 users) | ~₹15k/yr (cached system prompt) |
| Storage (TimescaleDB chunks, ~5 GB/yr at current rate, scaling 2× with new ingesters) | minimal — fits existing PG |
| Infra (existing Cloud Run + Postgres + Redis) | unchanged from today |

Compared to the prior plan's **~₹1.5 L/yr** in Tijori + Value Research subscriptions, this saves ~₹1.5 L/yr while improving provenance discipline.

---

## 11 · Phase 1 → Phase 2 handoff checklist

By end of Phase 1 (week 4), verify:

- [ ] DSL spec frozen and documented in `services/strategy_engine/dsl.py` docstring
- [ ] `nidp.stock_features_daily` populated for last 365 trading days for Nifty 500 universe
- [ ] 5 stock templates run in <500ms each over Nifty 50 single-day
- [ ] Backtest of momentum_breakout template on Nifty 50 last 90d returns deterministic results across 3 runs
- [ ] Frontend wizard saves a draft to localStorage and reloads it on refresh
- [ ] At least 1 admin-authored strategy promoted to "public template"
- [ ] Phase 2 dependency: NSE XBRL fixture data captured for 5 sample companies (Reliance, TCS, HDFC Bank, Infosys, Bajaj Finance) with known quarterly results — used as parser test fixtures
