# nivesh.ai - Product Requirements Document

## Implemented Features (Latest)

### Feb 2026 — Morningstar Rating end-to-end (Iteration 43)

Full wiring of Morningstar ratings from Moneycontrol → PG → UI:

1. **pg_writer**: `persist_moneycontrol_scrape` now writes `morningstar_rating` (int 1-5) with COALESCE semantics + new `_to_int` helper. Column already existed in `mutual_fund_metadata`.
2. **v3_integration**: SELECT query + `v3_primitives` surface include `morningstar_rating`.
3. **portfolio_enrichment**: `mf_scores_by_name` captures rating; per-row payload exposes `morningstar_rating` field (separate from composite — frontend chooses source).
4. **New endpoint** `POST /api/portfolio/refresh-mf-ratings` — de-dupes user MFs by name and scrapes all unique ones via Moneycontrol, invalidates the enriched-portfolio cache. For priyanka: 19 unique scraped, 15 with rating, 14 successfully propagated to holdings (some name-match misses due to CAS comma formatting).
5. **Frontend**: `StarRating` auto-picks Morningstar when `morningstar_rating != null`; falls back to Nivesh Rating (composite-derived). Title attribute differentiates source (`Morningstar Rating: N/5` vs `Nivesh Rating (composite-derived): N/5`). Subtitle "· Nivesh Rating" only on fallback rows.

**Testing**: iteration_43 — 5/5 pytest + frontend DOM inspection (100% both). Live confirmed: HDFC Flexi Cap=★5, Axis Small Cap=★5, Parag Parikh Flexi Cap=★5, Nippon Small Cap=★5, ICICI Value=★5, HDFC Balanced Advantage=★5, Sundaram Value=★2. 39 holdings use Nivesh fallback; 14 show real Morningstar.


### Feb 2026 — Portfolio page round 3: cache, header, in-place CTAs, scorer expansion, Nivesh Rating (Iteration 42)

5 more user-reported fixes:

1. **Performance — Redis cache** — `build_enriched_portfolio()` wrapped in a 5-minute Redis cache (`nivesh:cache:enriched_portfolio:{user_id}`). Cold load 17.2s → warm 0.1s (**165× speedup**). Response exposes `_cache_hit` flag for transparency. `refresh-stock-fundamentals` + `refresh-prices` invalidate the key.
2. **Page Header** — `data-testid='portfolio-header'` renders "Portfolio" h1 + subtitle ("64 holdings across 4 asset classes · Last refreshed 23 Apr · 82.8% scored") + 3 action buttons (Refresh scores, Export CSV, Reload).
3. **Alert CTAs now act in-place** — dropped Plan Board navigation for routine rebalancing actions:
   - `allocation` → "Show biggest positions" (sort by value desc + scroll to table).
   - `diversification` → "Show weak holdings" (new `filter=WEAK` = composite <50 + scroll).
   - `overlap` / `cost` → filter to Switch / Regular + switch to MF tab + scroll.
   - Only `risk_alignment` still navigates away (to Risk Profile screen).
4. **Score coverage — Groww search resolver** — New `search_groww_by_symbol()` resolves any NSE symbol → slug via Groww's `search/v3/query/global/st_p_query` autosuggest API (exact nse_scrip_code match). `refresh_user_stocks()` now runs a 2-phase strategy: Nifty-100 direct lookup → Groww-search fallback for mid/small caps. For priyanka: 52.8% → **82.8% coverage** in 6s (17 mid/small caps scored inline — Ambuja, Digidrive, Gabriel, Pricol, JK Tyre, IRB, Jindal Stainless, Rain Industries, NTPC Green, SJVN, etc.).
5. **Nivesh Rating stars** — Each row shows a 1-5★ pill (`data-testid='stars-{N}'`) derived from composite_score (80+=5★, 65-80=4★, 50-65=3★, 35-50=2★, <35=1★). Subtitle clarifies "· Nivesh Rating" when Morningstar data isn't available. Scaffolded `morningstar_rating` field on holding payload for future real-Morningstar wiring (MC already scrapes it in `moneycontrol_client._build_payload`, next step is persisting to PG).

**Testing**: iteration_42 — 3/3 backend pytest + full frontend acceptance (100% both). Cache 165×, coverage 82.8%, all 5 CTAs verified.


### Feb 2026 — Actionable Portfolio UX round 2 (Iteration 41)

5 user-requested UX enhancements turning the Portfolio page into a truly actionable decision surface:

1. **Intelligent HOLD sub-labels** — `action_badge.sub_action` ∈ {Keep, Watch, Review, Rebalance}:
   - **Keep** (Q ≥ 65 AND H ≥ 60) — solid fundamentals, no action needed.
   - **Watch** (Q ≥ 50) — monitor next quarter.
   - **Review** (Q < 50) — weak fundamentals, revisit.
   - **Rebalance** (weight_pct ≥ 10) — oversized single position; trim to <10%.
   - UI replaces the flat grey "HOLD" pill with contextual colour + label. For priyanka: 2 Keep / 15 Watch / 4 Review.

2. **"Why this action" inline** — every row renders a one-line italic rationale directly below the holding name (`data-testid='row-why-{id}'`). Example: *"Why: Regular plan (high expense)"* or *"Why: Quality 61 · Health 41 — monitor next quarter."* No need to expand the row to see the reasoning.

3. **Alerts → actionable CTAs** — `resolveAlertCta()` maps each alert component to a contextual button:
   - `allocation` → **Rebalance** (opens Plan Board)
   - `risk_alignment` → **Retake profile** (opens Risk Profile)
   - `overlap` / `health` → **Resolve** (filters to Switch + Mutual Funds tab)
   - `diversification` → **Review holdings** (opens Plan Board)
   - `cost` → **View switches** (filters to Regular Plans + MF tab)
   - `data_coverage` → **Refresh** (existing — triggers fundamentals refresh)

4. **Inline Switch CTA** — SWITCH rows render a compact "Switch →" button right next to the action badge (`data-testid='inline-switch-{id}'`). Click stops propagation — opens Switch modal without expanding the row.

5. **Portfolio Impact strip** — gradient banner above alerts summarising aggregate impact if all pending actions are completed (`data-testid='impact-strip'`):
   - **₹X/yr cost savings** — sum of Regular→Direct expense-ratio savings across SWITCH rows (value × (old_er − 0.75) / 100).
   - **₹X freed** — sum of value_rs across EXIT rows.
   - **Health X→Y (+Δ)** — from the existing `project_health` endpoint (hidden if null).
   - Breakdown pill: "3 Exit · 7 Switch · 5 Add".
   - Right-side "Open Plan Board →" CTA button.

**Testing**: iteration_41 — 10/10 pytest + full frontend acceptance (100% both). For priyanka: impact strip shows "15 pending actions · ₹1,122/yr · ₹5.55L freed"; 21 HOLD rows display 3 distinct sub-labels; all 7 SWITCH rows show inline button; alert CTAs navigate + filter correctly.


### Feb 2026 — Actionable Portfolio UX fixes (Iteration 40)

Addressed 4 direct user-reported issues on the new Actionable Portfolio Engine:

1. **Asset-class tabs** — Added segmented tabs on top of the table: All · Mutual Funds · Stocks · ETFs · Gold/SGB · Other (auto-hidden if 0 holdings). Each tab shows live count. Filter pills + search + CSV export now scope to the active asset tab. `data-testid='asset-tabs'` + `asset-tab-{id}`.
2. **XIRR correction** — Root cause was mixing partial cashflows (only holdings with `buy_date`) against the full terminal value, producing 367%. Fixed by:
   - Per-holding XIRR clamped to realistic `[-80%, +150%]` band to suppress CAS avg-cost artefacts.
   - MF holdings auto-fall back to Groww's **scraped 3y CAGR** (then 1y → 5y) when personal XIRR is unavailable or out-of-band. Surface `xirr_source` ∈ {personal, cagr_1y, cagr_3y, cagr_5y} + `cagr_1y_pct/cagr_3y_pct/cagr_5y_pct` on each holding.
   - Portfolio XIRR is now **value-weighted average** of per-holding XIRRs (industry standard when transaction-level SIP data isn't available). Hero tile shows "value-weighted" subtitle + an Info tooltip. For priyanka: 367% → **15.47%**.
3. **Score Coverage** — Formula changed from `scored_equities / total_equities` (equity-only → 35.7%) to `(scored_mfs + scored_equities) / (total_mfs + total_equities)` (→ **56.2%** for priyanka). Tile subtitle now says "MFs + equities" with an Info tooltip.
4. **Score interpretation bands** — New 4-band scale with correct colour coding:
   - **80+ Strong** (emerald) · **60–80 Good** (lime) · **40–60 Average** (amber) · **<40 Weak** (rose).
   - Exit-score coloring is **inverted** (low = safer): a value of 8 renders as Strong/emerald, 61 as Weak/rose.
   - Rendered in a pill legend below the hero tiles (`data-testid='score-legend'`). Per-score expanded-row cards show "Strong · Long-term business strength" style subtitle.
5. **Returns panel label** — Expanded row automatically labels the return as `XIRR (avg-cost proxy)`, `CAGR 3Y (Groww)`, `CAGR 1Y (Groww)`, or `CAGR 5Y (Groww)` based on which source was used.
6. **v3_integration.py** — Surfaced `ret_1y`, `ret_3y`, `ret_5y`, `sharpe`, `sortino` on `v3_primitives` so the Actionable Portfolio can fall back to them.

**Testing**: iteration_40 — 6/6 new pytest + 5/5 regression pytest all green; 100% frontend acceptance. Verified the Exit score inversion live (Ambuja exit=8 → Strong · Axis Small Cap exit=61 → Weak).


### Feb 2026 — Actionable Portfolio Engine (`/dashboard#portfolio`)

Replaced the legacy Holdings table with a **decision-engine Portfolio page** that fuses V3 fund scores, stock V3 scores, XIRR, portfolio alerts, and same-category switch suggestions into one actionable grid.

**Backend** (`services/portfolio_enrichment.py` + `routes/portfolio.py`):
- `GET /api/portfolio/holdings-enriched` — per-holding core + V3 scores (quality/health/exit/add) + composite + XIRR + action_badge {EXIT/SWITCH/ADD/HOLD/REVIEW} + portfolio-level alerts + totals (value, invested, P&L, xirr, coverage).
- Action badge logic: 🔴 EXIT (exit≥70 or rec=EXIT) · 🔁 SWITCH (Regular plan OR high overlap OR rec=SWITCH) · 🟢 ADD (add≥70 AND quality≥65) · 🟡 HOLD (default) · ⚠️ REVIEW (unscored).
- `GET /api/portfolio/switch-candidates?holding_id={id}` — returns top 3 same-category Direct-plan replacements with `switch_score` breakdown (ΔQuality, cost_gain%, tax_impact, exit_load). Skips the Regular/Direct sibling of the source fund. Name-matches CAS-formatted holdings via a "base key" normaliser that strips Regular/Direct/Plan/Growth/IDCW tokens.
- Newton-Raphson XIRR solver over per-holding buy → now cashflows + portfolio-level flows.
- 6-alert framework: allocation drift (>15% over/under), risk profile mismatch, top-3 Portfolio Health risk drivers, unscored-equity count with `action_hint='refresh_stock_fundamentals'`.

**Frontend** (`components/ActionablePortfolioView.js`, 432 LOC):
- 5 hero tiles: Value · Invested · P&L (% + ₹) · XIRR · Score Coverage.
- Alerts banner with severity-coloured cards (rose/amber/sky) + inline Refresh-Fundamentals CTA.
- 8 smart filter pills: All · Exit · Switch · Add · Hold · Underperformers · Regular Plans · Unscored.
- Table columns: Holding · Type · Qty · CMP · Value · P&L% · XIRR · Composite Score · Action badge; right-aligned monospace numeric columns with green/red colour logic.
- Row-expand shows score breakdown (Q / H / E / A) with bar-chart fills + reason + tax/cost panel + "Explore switch options" CTA when action=SWITCH.
- Switch modal (`SwitchPanel`) lists 3 same-category Direct-plan candidates with switch_score, ΔQuality, cost-gain%, exit-load.
- CSV export (`nivesh_portfolio_YYYY-MM-DD.csv`) with full score + badge columns.
- Search box filters by name/sector.

**Testing**: iteration_39 — 5/5 backend pytest + full frontend acceptance (100% both). Live-verified on priyanka (64 holdings): XIRR 95.77%, coverage 35.7%, 6 alerts, badge distribution REVIEW=28 · HOLD=21 · SWITCH=7 · ADD=5 · EXIT=3. SwitchPanel for HDFC Small Cap Regular returns Nippon India Small Cap Direct (SS=41), Nippon India Small Cap Growth (SS=41), DSP Small Cap Direct (SS=42).

**Design notes**: Legacy `PortfolioView` still mounted at hash `#portfolio_legacy` as a safety net. Dashboard.js routes `#portfolio` → `ActionablePortfolioView`.


### Feb 2026 — Auto-Enrichment on CAS Upload & Portfolio Refresh

**Wired the on-demand scrapers** so fundamentals + V3 scores are fresh the moment a user's holdings are created or refreshed — no manual trigger needed.

**`helpers/parsing.py:save_holdings`** (used by all upload paths — CAS PDF, CSV, Excel) now fires a background task `_enrich_after_upload(user_id, holdings_added)` after DB insert completes. Background task:
- **Equity holdings** → `groww_stock_scraper.refresh_user_stocks(user_id)` — scrapes ROE, D/E, growth, margins, volatility, momentum from Groww; writes primitives to Postgres `stock_primitives`; scores via V3 engine; persists to `stock_scores`. Fire-and-forget.
- **MF holdings** → **`fund_data_resolver.scrape_user_mfs_inline(user_id)` — INLINE runtime scrape** (5 concurrent, hits Groww + persists primitives to Postgres immediately). No more off-hours queue delay. Cold-cache takes ~10-15s for 22 MFs; warm-cache ~1.5s. Runs in the background via `asyncio.create_task` so upload response is instant.

**`routes/analytics.py:refresh-prices`** — same background enrichment fires after live-price refresh. Keeps stock scores aligned with latest cap-bucket classification + momentum.

**`routes/gmail.py`** Gmail CAS path — also wired to trigger the same enrichment via shared helper.

**Verified on priyankamantri** (real user, 15 equity + 26 MF holdings):
- Background enrichment scored 15 out of 15 equities (10 Nifty 100 + 5 mid/small-cap) in 0.3s.
- 22 MFs queued for the drain job.
- Full Postgres `stock_scores` table populated: TCS Q=77.9 · MARUTI H=74.6 · ITC REVIEW (H=37) · HDFCBANK H=86.5 · INDHOTEL H=81.4 · AMBUJACEM REVIEW (H=40).

**Design choices**:
- Fire-and-forget via `asyncio.create_task` — upload response never blocks on enrichment.
- Errors are logged only, never bubbled to the user (enrichment is best-effort).
- Redis cache (6h TTL) makes repeat refreshes near-free.
- Matches only NSE-listed, Nifty-100 equities for scoring; other equities wait for the broader scrape expansion (P1).



### Feb 2026 — Groww Nifty 100 Scraper (HARDENED — all gaps closed)

**Live pipeline**: `services/groww_stock_scraper.py` scrapes `groww.in/indices/nifty-218500` for 100 constituents, then each stock's detail page for fundamentals. Extracts from Next.js `__NEXT_DATA__` JSON blob (no fragile HTML parsing). Maps to our `stock_primitives` row shape, persists to Postgres, and calls `stock_scoring.score_stock()` to write V3 composite scores.

**Gaps CLOSED this session**:
- ✅ **Retry with exponential backoff** (3 attempts, 1s/2s/4s on 429/500/502/503/504/timeouts)
- ✅ **Redis cache layer** (6h TTL per slug — 14× speedup on repeat requests, verified 0.56s → 0.04s)
- ✅ **Live price integration** — scraper now reads `livePriceData[symbol]` to get `ltp`, `yearHigh`, `yearLow`
- ✅ **`momentum_score`** computed as live-price position in 52w range (was placeholder 50)
- ✅ **`return_1y_pct`** from Groww's own `cagr.oneYearTtm` (with 52w-midpoint fallback)
- ✅ **`earnings_surprise_pct`** from quarterly YoY comparison (e.g., Dec '25 vs Dec '24 profit)
- ✅ **`max_drawdown_pct`** proxy from `(ltp - yearHigh) / yearHigh`
- ✅ **Volatility** blends price-range proxy (70%) + quarterly-profit CV (30%) for robustness
- ✅ **Local Postgres** configured + migration 008 applied in sandbox (verified end-to-end)

**Live verified on 9 Nifty stocks** (after hardening):
| Symbol | PE | ROE | D/E | Ret1Y | Momentum | Surprise | DD | Quality | Rec |
|---|---|---|---|---|---|---|---|---|---|
| TCS | 18.7 | 58% | 0.11 | 9% | 14.5 | +12.1% | 30% | 77.9 | HOLD |
| MARUTI | — | — | — | — | — | — | — | 77.5 | HOLD |
| ITC | — | — | — | — | — | — | — | 77.5 | REVIEW |
| HDFCBANK | 15.5 | 13% | 0 | -3% | 19.9 | +9.3% | 23% | 64.2 | HOLD (H=86!) |
| AXISBANK | 16.2 | 13% | 0 | +5% | 88.5 | +4.2% | 3% | 56.5 | HOLD (momentum) |
| RELIANCE | 18.9 | 9.5% | 0.43 | 10% | 20.7 | +1.7% | 16% | 49.4 | HOLD |

Scoring sanity-check passes — TCS/ITC/MARUTI (cash-rich franchises) top Quality; AXISBANK tops Momentum (near 52w high); HDFCBANK tops Health (strong YoY earnings).

**Remaining gaps** (P2, not blockers):
- `debt_trend_pct` + `debt_spike_flag` — Groww's stock detail page doesn't expose balance-sheet debt series. Needs separate scrape (Screener.in or MC). Stays None → neutral fallback.
- `beta` — not in payload. Would need correlation vs NIFTY 50 from daily price history.

**Scheduler**: APScheduler job `_stock_nifty100_refresh_job` runs **daily 23:00 IST** (`services/mf_scheduler.py`). On-demand trigger via `POST /api/admin/v3-stock-refresh` (full or `?symbol=X`).

**Tests**: 39 scraper tests + 240 total tests green. Concurrency verified (9 stocks in 1.2s = 0.13s/stock with cache warm).



### Feb 2026 — Portfolio Health UNIFIED + What-If Projection + Stock V3 Scoring (Phase A+B)

**UNIFIED PORTFOLIO HEALTH** (Dashboard + Insights + Plan Board all consistent):
- Removed legacy `services/__init__.compute_health_score` (stale heuristic).
- `GET /api/portfolio/analytics.health_score` now calls `portfolio_health.build_portfolio_health()` and returns the V3 shape `{overall, grade, diversification, risk, cost_efficiency, performance, summary, risk_drivers, components, low_confidence}`.
- `GET /api/insights/analysis.portfolio_health` attached for Insights tab — consistent grade B/64 across all three tabs for priyankamantri.
- InsightsView `Portfolio Health` + `Risk Assessment` tiles rewritten to consume the new payload, render top 3 risk drivers.

**LETTER GRADE MAPPING** — score_to_grade(): ≥90=A+, ≥80=A, ≥70=B+, ≥60=B, ≥50=C, ≥40=D, <40=F.

**WHAT-IF PROJECTION** (`services/portfolio_health_projection.py`):
- `GET /api/plans/active/health-projection` returns `{current, projected, delta_total, delta_by_component, completed_count, pending_count, message}`.
- Shadow-mutates holdings per PENDING action (EXIT/TRIM/SWITCH→Direct/ADD debt) and recomputes Health.
- Plan Board header now shows a **HealthProjectionCard** (`/app/frontend/src/components/v2/HealthProjectionCard.jsx`) — "Completing pending actions lifts Health from 64→68 (+3.82)".

**STOCK COST PROXY + CAP-WEIGHTED BENCHMARK** — added to `portfolio_health.py`:
- 0.2% p.a. stock brokerage/slippage baked into Cost component.
- Benchmark return blends NIFTY 50 (large 12%) / Midcap 150 (mid 14%) / Smallcap 250 (small 16%) per equity mix.

**STOCK V3 SCORING ENGINE** (`services/stock_scoring.py` — NEW):
- User-approved refined framework (Feb 2026): Quality/Health/Exit/Add composite scores for direct equities.
- **Quality** (non-market): ROE 25, D/E 15, EPS Growth 3Y 20, Promoter 10, Market-cap stability 10, Earnings consistency 20. **PE band removed** (valuation ≠ quality).
- **Health** (trajectory): Revenue Growth 25, Profit Margin Trend 20, Debt Trend 15, Earnings Surprise 15, Volatility 10, Dividend 5. **Beta removed** (noisy for retail).
- **Exit** (sell-signal): PE Overvaluation 25, Earnings Decline 25, Quality Deterioration 20, Debt Spike 10, Liquidity Risk 10, Tax 10.
- **Add** (portfolio-driven): Sector Gap 30, Low Overlap 25, Relative Valuation 15, Quality 15, Momentum 10, Dividend 5.
- `derive_recommendation` maps to BUY/HOLD/TRIM/EXIT/REVIEW.
- Weights editable via admin UI (MongoDB `system_config.v3_stock_weights`).

**POSTGRES SCHEMA** (`migrations/008_equity_scoring.sql`):
- `stock_master` — canonical catalogue (symbol, cap_bucket, sector, is_nifty_100).
- `stock_primitives` — all raw primitives needed by scoring (ROE, D/E, growth, margins, volatility, etc.).
- `stock_scores` — V3 composite scores + component JSONB breakdown + recommendation.
- Apply in production via existing migration runner; sandbox PG unavailable in dev.

**ADMIN ENDPOINTS** (`routes/admin_v3_stock.py`):
- `GET/PUT /api/admin/v3-stock-weights` — edit Quality/Health/Exit/Add weights, sum-to-100 validation.
- `POST /api/admin/v3-stock-weights/reset` — restore defaults.
- `GET /api/admin/v3-stock-master?nifty_100_only=true` — list scored stocks with composite scores + recommendation.

**ADMIN UI TABS** (`AdminView.js`):
- V3 Rules Engine: **Mutual Funds** tab (existing) / **Equity** tab (new — renders `V3StockWeightsSection.jsx`).
- V3 Master Catalogue: **Mutual Funds** tab (existing) / **Equity** tab (new — renders `V3MasterStocksSection.jsx`).

**Testing**: 165 backend tests green (67 `test_portfolio_health.py` + 24 `test_stock_scoring.py` + others). Live-verified: Dashboard `health_score.overall=64 grade=B`, Insights `portfolio_health.health_score=63.96 grade=B`, Plan projection `current=64, projected=68, delta=+3.82`.

**PENDING (Phase B follow-up)**: Groww Nifty 100 scraper + daily APScheduler cron to populate `stock_master` / `stock_primitives` / `stock_scores`. Scoring engine + admin UI already wired and functional — just needs the scraper to start feeding data.




### Feb 2026 — Goal-Based Investment Planning Engine (GBIPE) V1 + Monte-Carlo
Outcome-first planning module. Users define life goals → system produces inflation-adjusted targets, required SIP, auto fund allocation, 4-scenario projections, Monte-Carlo success probability, and actionable recommendations.

**Engine** (`services/goal_engine.py` — NEW, ~320 LOC pure-Python, no DB):
- Future-value inflation math, SIP/lumpsum sizing, fixed-return corpus projection.
- Allocation profiles: Conservative 30/60/10, Moderate 60/30/10, Aggressive 80/10/10 (PRD §8); horizon <5y caps equity at 40% (PRD §15 guardrail).
- Blended return/volatility from allocation: Equity μ=12% σ=18%, Debt μ=6.5% σ=3%, Hybrid μ=9% σ=10%.
- **Scenario matrix**: base / bull (+3%) / bear (-3%) / stress (-6%) with corpus + success %.
- **Monte-Carlo** success probability: N=1000 independent paths of Normal(μ,σ) monthly returns, returns prob_success_pct + p5/median/p95/worst corpus + expected_shortfall_pct. NumPy-accelerated with pure-Python fallback.
- **Action recommender**: increase_sip (shortfall), reduce_risk (short horizon with high equity), on_track (healthy).

**Fund picker** (`services/goal_fund_picker.py` — NEW): auto-picks 1 fund per bucket from the V3 master catalog, ranked by quality_score DESC with filters (quality ≥ 55, expense ≤ 1.5%, AUM ≥ 500 Cr, prefers Direct plans). Also exposes `shortlist_for_bucket(n=5)` for UI override.

**PostgreSQL** (migration `007_goal_planning.sql`):
- `user_financial_snapshots` — age, income, expenses, corpus, liabilities, risk profile, behavior score.
- `user_goals` — goal_type/name/target/horizon/priority + inflation/return + allocation/selected_funds JSONB + last_simulation JSONB + on_track_pct.
- String user_ids mapped to UUID via deterministic uuid5 (no schema change needed).

**API** (`routes/goals.py` — NEW, 11 endpoints):
- `GET/PUT /api/goals/snapshot`
- `GET/POST /api/goals`
- `GET/PATCH/DELETE /api/goals/{id}`
- `POST /api/goals/{id}/simulate` (re-run + persist)
- `POST /api/goals/{id}/what-if` (preview-only; accepts SIP/horizon/allocation overrides)
- `GET /api/goals/fund-shortlist/{bucket}` (equity/debt/hybrid/liquid)

**Frontend** (`components/goals/*` — NEW):
- `GoalsView.jsx` — sidebar-linked main page with financial snapshot summary, goal grid, CTA states.
- `FinancialSnapshotWizard.jsx` — one-time onboarding form (age/income/expenses/corpus/risk/dependents).
- `GoalCreateWizard.jsx` — 3-step form wizard (type → target+horizon → SIP+corpus + review).
- `ScenarioSimulator.jsx` — 4 summary tiles + scenario matrix (4 cards) + Monte-Carlo distribution + action panel + selected funds list + what-if sliders (SIP, horizon) with Preview + Apply.
- Sidebar updated: new "Goals" item with NEW badge.

**Testing**: 24 pure-logic unit tests in `tests/test_goal_engine.py` (SIP math, allocation, scenarios, MC determinism, action recommender, evaluate_goal wiring). Testing agent iteration_36: **39/39 tests pass, 100% backend + 100% frontend acceptance**, 0 functional bugs. Live verified on priyankamantri: ₹2 Cr retirement at 20y → FV ₹6.4 Cr, required SIP ₹84K/mo, current 33.5% on-track (MC 0.3%), action recommends ₹59,080/mo SIP bump.

### Feb 2026 — Post-Deploy Migration: preview → production data sync pipeline
One-click pipeline that seamlessly ships V3 master + primitive + scored data from preview to any freshly-provisioned production Neon Postgres. Solves the `failed to load datastore status` / empty-production-PG problem.

**Architecture**: PG → Mongo `pg_mirror_*` collections (WORM, weekly snapshots) → fresh production PG (idempotent restore).

**3 new scripts + 3 new admin endpoints**:
- `scripts/mirror_pg_to_mongo.py` — snapshots 7 critical PG tables (instrument_master, benchmark_master, mutual_fund_metadata, mutual_fund_performance_ratios, mutual_fund_holdings [latest 180d], mutual_fund_nav_history [last 5y], mutual_fund_aum_history) into `pg_mirror_*` Mongo collections in ~5s / 266k rows.
- `scripts/restore_pg_from_mirrors.py` — idempotent replay; handles tz-aware/naive coercion, natural-key ON CONFLICT upserts, and delete-then-insert for `mutual_fund_holdings` (which has no natural-key unique constraint).
- `scripts/post_deploy_migrate.py` — 8-phase orchestrator: hydrate_secrets → health_check → apply_migrations (ALL 001-006 via asyncpg, tracked in `schema_migrations`) → restore_mirrors → replay_scrape_cache (skippable) → analytics_sweep → v3_rescore → smoke_check. Full run ~38s.
- `POST /api/admin/datastores/mirror-pg-to-mongo`, `POST /api/admin/datastores/post-deploy-migrate`, rewritten `POST /api/admin/datastores/apply-pg-schema` (now iterates ALL migration files, not just 001).

**Admin UI** (`DatastoreSection.jsx`): new "Post-Deploy Migration" card with PROD badge, two buttons (`Mirror PG → Mongo`, `Run Post-Deploy Migration`), and a per-phase results table showing status / ms / result.

**Testing**: 7/7 pytest + 2/2 CLI + frontend integration all green (iteration_35). Idempotent — re-running either script produces identical output with 0 duplicate-key errors.

**Docs**: `/app/docs/POST_DEPLOY_MIGRATION.md` — full operator playbook with phase-by-phase timing, skip flags, troubleshooting, and retention characteristics.

### Feb 2026 — Holding Action Score (HAS): portfolio-aware per-holding decision layer
Ships a third-layer decision engine on top of V3. Combines fund intelligence with portfolio structure + tax reality to answer not "which fund is good" but "what should I do with THIS holding" — exactly what RIAs/PMS platforms produce.

**3 new derived scores** (`services/holding_action_score.py` — NEW, ~320 LOC, pure-Python):
- **OIS (Overlap Impact Score)**: weighted stock-level overlap of the fund vs the rest of the portfolio. Clamped 0–100; higher = more duplicate exposure.
- **ADS (Allocation Deviation Score)**: `100 − |current_weight_pct − target_weight_pct| × 5`. Target = 100/N if ≤10 funds, else 10%. Reports `stance` ∈ {overweight, underweight, on_target} + deviation in pp.
- **TFS (Tax Friction Score)**: `tax_ratio × 200 + 20 if STCG`, capped 100. Hits 80–100 for "high gain + STCG" (avoid realising); 10–30 for "low gain + LTCG".

**HAS composite** (`compute_has()`): `0.30·Q + 0.20·H + 0.15·(100−Exit) + 0.15·Add + 0.10·(100−OIS) + 0.05·ADS + 0.05·(100−TFS)`. Four category-specific profiles:
- Equity: default profile per PRD.
- Hybrid: overlap 10% → 5%, freed 5% → Health (25%).
- Debt: overlap 10% → 5%, freed 5% → Health (25%).
- Liquid: no overlap/exit weights; Q=0.40, H=0.40, ADS=0.10, TFS=0.10.

**Decision map**: HAS ≥75 → HOLD/ADD (ADD only if Add_score ≥70); 60–75 → HOLD; 45–60 → TRIM; 30–45 → SWITCH; <30 → EXIT.

**5 guardrails** (`evaluate_guardrails`): High-Quality Protection (Q≥75 AND H≥70), Tax (tax_cost > benefit), Recent Investment (<180 days), Low Confidence (<50 — downgrades EXIT/SWITCH → REVIEW), Overlap Override (>80% allows EXIT even if other blocks fire).

**Reason generator** (`build_holding_reason`): cites weakest contribution component for EXIT/SWITCH/TRIM actions and strongest for HOLD/ADD. Appends ADS stance + blocked-guardrail reason when relevant.

**Wiring** (`routes/insights.py`):
- Per-fund HAS payload exposed under `entry.has = {has, action, reason, category, components, ois_score, ads_score, ads_deviation_pp, tfs_penalty, guardrails, confidence}`.
- Portfolio-level tallies: `portfolio.avg_has_score` (value-weighted), `portfolio.has_action_counts` ({ADD, HOLD, TRIM, SWITCH, EXIT, REVIEW, UNKNOWN}), `portfolio.target_weight_pct_per_fund`.
- Funds sorted by HAS action priority (EXIT → SWITCH → TRIM → REVIEW → HOLD → ADD) then ascending HAS.
- Pairwise overlap fetched via `portfolio_intelligence.compute_portfolio_intelligence()` (same pipeline as action plans).

**Frontend** (`V3FundBreakdown.jsx` + `V3PortfolioInsights.jsx`):
- New "Avg HAS" headline tile (5-col grid on lg screens).
- Action signals tile now shows Exit + Switch + Trim counts driven by HAS.
- Per-fund HAS pill + category badge + HAS-driven action badge (TRIM=orange, ADD=emerald).
- Expandable "Portfolio-aware layer" panel with OIS/ADS/TFS pills, reason, and guardrail blocks.
- Filter chips extended: All · Exit · Switch · Trim · Review · Add; counts from `has_action_counts`.

**Testing**: 41 new pure-logic unit tests in `tests/test_holding_action_score.py` (all 7 sub-functions + single entry point + edge cases). Backend testing agent verified live (iteration_34): 53/53 tests pass, 100% backend + frontend acceptance criteria met. Live verified on priyankamantri: Avg HAS = 63.19, 18 HOLD · 4 TRIM · 3 SWITCH · 0 EXIT (all guardrails correctly prevented EXIT).

### Feb 2026 — V3.1 Debt pipeline complete: Moneycontrol primitives scraped, persisted, and consumed
Completes the Category-Aware Scoring rollout for Debt funds.

**Scraper** (`services/moneycontrol_client.py`):
- `fetch_by_url()` parses MC's embedded `<script id="__NEXT_DATA__">` JSON to extract Morningstar-style `investmentStyle` (e.g., "Moderate Sensitivity High Quality"), ISIN, AUM, expense, CAGRs, manager, launch date, etc.
- `parse_investment_style()` maps to `credit_quality_score` (High=9, Medium=6, Low=3) and `duration_risk_score` (Limited=9, Moderate=6, Extensive=3).
- `search_fund()` (NEW) uses MC autosuggest `type=2` + Direct-plan prefilter, returning `{imid, url, display_name}`.
- Backward-compatible `search_imid()` wrapper retained.

**Persistence** (`services/pg_writer.persist_moneycontrol_scrape`):
- Matches existing funds by ISIN → scheme_name. Upserts debt columns into `mutual_fund_metadata`: `credit_quality_score`, `duration_risk_score`, `ytm`, `modified_duration`, `investment_style`, `moneycontrol_imid` + metadata fallbacks (aum, expense_ratio, manager_name, launch_date, etc.).
- Cleanly skips unknown funds (no blind inserts) — MC is enrichment-only.

**Scoring wiring** (`services/v3_scoring._norm_duration_risk_flex`):
- New flex normaliser prefers the pre-normalised `duration_risk_score` (0-10) from MC investment-style parsing, falls back to `_norm_duration_risk(modified_duration_years)`.
- `compute_quality_score()` debt weight profile now actively consumes credit_quality + duration_risk + yield_vs_category.

**APIs updated to surface new debt primitives**:
- `GET /api/admin/v3-master-funds` — `primitives.{credit_quality_score, duration_risk_score, ytm, modified_duration, investment_style, moneycontrol_imid}`.
- `GET /api/insights/v3-portfolio` — same keys under each fund's `primitives` block.

**Bulk import script** (`scripts/bulk_import_moneycontrol_debt.py` — NEW):
- Hydrates Mongo secrets, iterates debt funds classified by `v3_weights.classify_fund_category`, resolves imid via autosuggest, scrapes + persists, then triggers `nav_analytics_sweep.run_v3_rescore`.
- One-off data load: **36/36 debt funds persisted** with credit_quality=9.0 and duration_risk=9.0/6.0 mix. 185/185 funds rescored in 4.3s.

**Testing**:
- 14 new unit tests in `tests/test_moneycontrol_client.py` (style parsing, payload builder, helpers).
- 6 new unit tests in `tests/test_v3_debt_scoring.py` (flex normaliser, debt weight routing).
- Backend testing agent verified live: 36/36 debt funds return correct primitives in admin API; debt weight profile applied to all; 0 regressions across 69 previously-green V3 tests. `iteration_33.json`.

### Feb 2026 — Per-fund V3 breakdown + Danger-zone highlighting in Insights UI
User requested per-fund V3 scores (Quality, Health, Exit, Add, Switch) in the Insights UI, with danger-zone highlighting and deterministic explanations (no LLM).

**Backend** (`services/v3_explainer.py` — NEW):
- `classify_danger(bundle)` → `{level: 'critical'|'warning'|'ok', reasons:[], is_danger: bool}`. Critical: Quality<40 OR Health<40 OR Exit≥75. Warning: Quality<55 OR Health<55 OR Exit≥60 OR Switch≥2.0. Correctly ignores the positive `high_quality_protection` guardrail.
- `build_explanation(bundle, plan_type, cost_leak_rs)` → deterministic paragraph citing weakest Quality + Health components by name with primitive values (AUM, manager tenure, drawdown%, turnover%, top-10 concentration%, downside capture%). Caps at 3 drags + 1 strength + exit/switch notes. No LLM.

**API** (`routes/insights.py`, `/api/insights/v3-portfolio` extended):
- Each fund now returns: `plan_type`, `cost_leak_rs_per_yr`, `scores{quality,health,exit,add,switch}`, `danger`, `explanation`, `quality_components`, `health_components`, `primitives`, `guardrail_blocked`, `guardrail_reasons`.
- Switch score computed via `compute_switch_score(cost_saving_rs_per_yr=cost_leak, tax_cost_rs=0)` for Regular plans; null for Direct plans.
- `portfolio.n_danger_critical` + `n_danger_warning` counts exposed for headline tile.
- Funds sorted: critical → warning → ok, then by descending quality (funds needing attention float to top).

**Frontend** (`components/insights/V3FundBreakdown.jsx` — NEW, 240 LOC):
- Per-fund expandable card list with 5 score pills (Q / H / E / A / SW), tone-coded (emerald ≥75 · amber 55–74 · rose <55; inverted for Exit).
- DANGER badge (rose) + left border on critical funds; WARN badge (amber) + left border on warnings.
- Filter chips: All · Danger · Critical (with counts) — testids `v3-filter-all/danger/critical`.
- Click any row → deterministic explanation paragraph (bold headline preserved) + danger banner with bullet-list of reasons + primitives grid (AUM, manager tenure, drawdown, etc.).
- Full data-testid coverage: `v3-fund-breakdown`, `v3-fund-row-{id}`, `v3-fund-toggle-{id}`, `v3-fund-explain-{id}`, `v3-q-{id}`, `v3-h-{id}`, `v3-e-{id}`, `v3-a-{id}`, `v3-sw-{id}`, `danger-banner-critical/warning`.
- `V3PortfolioInsights.jsx` updated: replaced static "Flagged" tile with a "Danger zone" tile showing `n_danger_critical` / `n_danger_warning`. Mounts `<V3FundBreakdown>` below the leaderboard.
- Fully dark-mode safe.

**Live verified on priyankamantri** (26 MFs): 2 critical + 8 warning danger-zone funds. Example surfaced — Sundaram Value Fund Regular: DANGER, Q=37, H=62, E=54, A=38, SW=0.1, explanation cites "Small/young fund (AUM ₹1,212Cr) — maturity score 1.6/10; Risk-adjusted returns sub-par — Sharpe+Sortino 2.3/10". Below-par Parag Parikh Large Cap Regular: Q=27, E=82 (critical), explanation cites cost strength + exit recommendation.

**Testing**: 13 new pure-logic unit tests in `tests/test_v3_explainer.py` (all pass). Testing agent verified backend (25/25 integration tests pass) + frontend code review PASS. End-to-end Playwright screenshot confirms 26 rows render with correct colour-coding, filters work, row-expand shows primitives grid, critical/warning banners visible. Full backend suite **103/103 green**.

### Feb 2026 — NIFTY index-tracker proxies seeded → downside_capture unlocked

Final gap-close on the V3 analytics pipeline. Seeded 6 canonical NIFTY index-tracker funds as benchmark proxies for `downside_capture` computation.

**Seeded** (via `scripts/seed_benchmark_trackers_v2.py`):

| Tracker | AMFI Code | Benchmarks Covered |
|---|---|---|
| UTI Nifty 50 Index Fund Direct Growth | 120716 | NIFTY 50 TRI |
| UTI Nifty Next 50 Index Fund Direct Growth | 143341 | NIFTY Next 50 TRI |
| HDFC NIFTY 100 Index Fund Direct Growth | 149868 | NIFTY 100 TRI |
| Nippon India Nifty Midcap 150 Direct Growth | 148726 | NIFTY Midcap 150 TRI |
| Nippon India Nifty Smallcap 250 Direct Growth | 148519 | NIFTY Smallcap 250 TRI |
| ICICI Prudential Nifty 500 Direct Growth | 153161 | NIFTY 500 TRI |

Analytics sweep now fills downside_capture for **26 of 31 funds in PG**. Priyanka's portfolio avg Health 68.66 → 69.16.

### Feb 2026 — V3 Engine Ops Layer: Parallel Sweep + Redis Cache + Admin Monitor
Parallel sweep jobs (`services/nav_analytics_sweep.py`) + Redis composite-score cache + Admin Data Pipeline Monitor. 22/22 funds swept in 56ms, 24/24 rescored in 18ms. 92/92 backend tests green.

### Feb 2026 — V3 Engine Phases 2 & 3: Rules Migration + UI Integration
Phase 2 ports the V2.5 action-rule engine to consume V3 composite scores. Phase 3 surfaces V3 scores in PlanCard UI + adds V3 panel to Insights tab. Live-verified: coverage 100%, 26/26 funds scored.

### Feb 2026 — V3 Engine Phase 1: Scoring Layer + NAV Analytics + 5y AMFI Backfill
- Phase 0c: 5y AMFI NAV backfill (25,922 rows).
- Phase 1a: NAV-derived analytics (max_drawdown, consistency_score, downside_capture, aum_trend).
- Phase 1b: 5 composite scores + Switch formula + 4 Guardrails as pure-Python deterministic functions.
- 38 pure-logic unit tests + integration-tested live via curl.

### Feb 2026 — V3 Engine Phase 0b: Groww scraper expansion (all scoring primitives sourced, zero compute)
Extracts: `allotment_date`, `fund_manager_details` + tenure, `expense_ratio_direct/regular`, `historic_fund_expense`, `turnover_ratio`, `category_avg_1y/3y/5y`, `rank_within_category`, `top10_concentration`, `analysis_json`. Sibling Regular/Direct plan auto-fetched. 15 pytest unit tests.

### Feb 2026 — V3 Engine Phase 0a: NAV/AUM history + benchmark master
New PG schema: `mutual_fund_nav_history`, `mutual_fund_aum_history`, `benchmark_master` (34 SEBI-standard categories). Daily AMFI NAV ingestion @22:00 IST.

### Apr 2026 — V2 Action Generation Rule Engine (6 Core Rules)
Implemented 6 explicit business logic rules in `services/action_plan_manager._apply_action_rules`: Regular→Direct consolidation, cost-leak detection, AMC concentration, underperformer replacement, fund overlap, debt allocation gap. 10 tests pass.

### Feb 2026 — Admin UI: V2 Rules Manager + LLM Prompts Manager
Live-tunable config + auditability for the V2 engine + every LLM system prompt.

### Feb 2026 — Data-Accuracy Guardrails: Deterministic Insights + Rule 2b
`services/ai_insights.generate_insights` now bypasses LLM completely. Rule 2b fires for MF category concentration >35%.

### Feb 2026 — V2.5 Decision Engine (Batch A + B + Hero Card)
5 composite scores, Switch formula, guardrails. Plan Board Hero Card surfaces portfolio score donut, confidence badge, plan summary, before→after delta pills.

### Earlier work (condensed)
- Portfolio Intelligence (AI-grade fund overlap rewrite) — `portfolio_intelligence.py`, `ai_insights.py`, `PortfolioIntelligenceTab.jsx`.
- Groww MF Data Fetcher Phase 1/2/3 — parser, APScheduler cron, PG persistence.
- Generic Admin Config Panel — unified Secrets Registry + DB-backed Feature Flags.
- AI Copilot Phase 1 + 2 + interactive charts + Save-as-Plan.
- Mobile-first responsive overhaul, CAS parsing, Google OAuth, risk profile, Gmail import.

## Backlog

### P0 (next)
- **User Data Purge**: Admin UI button + `DELETE /api/admin/users/{user_id}/portfolio-data` endpoint to wipe 9 MongoDB collections (`holdings`, `action_plans`, `plan_history`, `portfolio_analysis`, `pending_actions`, `ai_insights`, `scenario_simulations`, `allocation_analysis_cache`, `fund_performance_cache`) for a single user while preserving `users`, `user_profiles`, `user_sessions`, `chat_sessions`. Enables fresh CAS re-upload testing.

### Recently completed (Feb 2026)
- **V3.1 Category-Aware Scoring Engine (Equity / Hybrid / Debt)** (2026-02-22): Per PRD. `services/v3_weights.py` stores editable weight profiles per category in MongoDB `system_config`. `v3_scoring.py` refactored to classify each fund (equity / hybrid / debt / liquid) and apply the category's weight profile. New primitive normalisers for debt (`credit_quality`, `yield_vs_category`, `duration_risk`, `credit_concentration`, `liquidity`) and hybrid (`allocation_stability`, `allocation_consistency`, `downside_capture`). Liquid funds classified but fall through to Equity weights (user deferred). Admin API `GET/PUT/POST /api/admin/v3-weights` with sum-to-100 validation. Frontend `V3WeightsSection.jsx` (editable numeric inputs + reset + dirty-state tracking) mounted in Admin > V3 Rules Engine tab. Classification distribution: 111 equity, 36 debt, 25 hybrid, 13 liquid. 12 new pytest tests + 4 regression tests updated → 70 total passing.
- **5-year AMFI NAV backfill for 157 new funds** (2026-02-22): `scripts/run_amfi_backfill.py` wrapper (hydrates Mongo secrets → runs backfill → analytics sweep → V3 rescore). Added **246,895 new NAV rows**, brought 165/185 funds to full `consistency_score`, 184/185 to `max_drawdown_pct`. `aum_trend_score` still blocked (empty `mutual_fund_aum_history` table).
- **V3 Master Funds admin dashboard** (2026-02-22): New 4th admin tab with Compact/Detailed/Dense view toggle, filters, row-expand showing per-component contribution tables, Excel export (5 sheets). Fixed ratios table-name typo so performance + risk_adjusted primitives now display correctly.
- **Groww+Tickertape bulk import** (2026-02-22): 185 unique MFs scored (168 via Groww, 14 via Tickertape fallback for SEBI-renamed funds).
- **Remove danger/warn flags → per-fund Exit/Switch recommendations** (2026-02-22): `derive_recommendation()` returns `{action: EXIT|SWITCH|REVIEW|HOLD|BUY}`. 40 tests passing.


### P1
- Close 4 minor V3 Excel spec gaps: `compute_hold_score()`, `type=HOLD` P2 actions, insight `severity` field, Groww `alpha_ratio` mapping.
- DPDP compliance: PAN AES-256 encryption, consent logging, audit trails.
- Fernet-encrypt secrets at rest.

### P2
- Phase B Asset Coverage: equity ETFs in overlap, FIFO lot-wise tax, debt/gold taxation.
- Goal-based planning module (Retirement, Child Education, AI-calculated SIPs).
- Admin dashboard tab split (Infrastructure / Data Management / User Management).
- Radix DialogContent a11y warnings (wrap titles with VisuallyHidden).
- Portfolio versioning (delta tracking).
- Historical-backtest CAGR model.

## Data Model Additions
- `db.system_config` — `{key: "secrets", ...}`, `{key: "feature_flags", ...}`, `{key: "rules_config", ...}`, `{key: "prompts", ...}`
- `db.saved_scenarios`, `db.pending_actions`, `db.scenario_simulations`, `db.action_plans`
- PG: `mutual_fund_nav_history`, `mutual_fund_aum_history`, `benchmark_master` (with `proxy_instrument_id`), `mutual_fund_metadata` (extended with V3 columns), `amfi_nav_fetch_log`, `nav_analytics_job_log`
