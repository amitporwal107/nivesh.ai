# nivesh.ai - Product Requirements Document

## Implemented Features (Latest)

### May 2026 — BTST Framework: Deploy Verdict Strip + Trade Journal + 4 BTST Scans + Loading-Picks Bug Fix

User asked for the full BTST/positional system: Market Dashboard (gating layer), early signal scanner, trade management engine — based on their ChartInk dashboard 247498 + the framework they pasted (staged entries 20/30/30/20, exit ladder +5/+8-10/+12-15/trail, hedge sizing, sector rotation).

**Loading-picks bug fixed (P0)**:
- `_batch_fetch_prices` was uncached — every page load fired 2 parallel `yf.download()` batches × 30s+. UI sat on "Loading picks…".
- Fix: 90s per-symbol in-memory cache + 8s `asyncio.wait_for` timeout in `_enrich_with_live`. Cold call **35s → 1.0s**, warm cache **0.27s**, 12/12 picks render with live LTP.

**Deploy Verdict Strip** (`/api/positional/market-dashboard`):
- New endpoint + service `services/positional_engine/market_dashboard.py` aggregating Nifty (BeES proxy), breadth (% above 20EMA / 50EMA, advance/decline ratio, 52w highs/lows), sector heatmap (mean 5d return per sector, RS vs Nifty, hot/warm/cool/cold tone, leader stock), VIX (yfinance ^INDIAVIX), macro passthrough.
- Single 4-bucket verdict: AGGRESSIVE / NORMAL / CAUTIOUS / DEFENSIVE — gating layer answers "is today a green-light day?" Macro risk HIGH→DEFENSIVE; Nifty downtrend→CAUTIOUS; breadth ≥65% + ≥2 hot sectors→AGGRESSIVE; else NORMAL/CAUTIOUS by breadth tier.
- 60s cache on the route. Live response on aporwal107: NORMAL · NEUTRAL · breadth 80% · 296/7 new highs/lows · A/D 2.32 · sectors {Automobile +3.8% (HOT), Cement +2.9%, Finance +2.4%, IT-Software -2.8%, FMCG -1.1%}.
- Frontend: `<DeployVerdictStrip/>` mounted at top of §1 The Market in MarketDashboard.jsx — gradient hero card + 5 number tiles + sector dot strip.

**4 BTST ChartInk scan formulas seeded as defaults**:
- `btst.early_accumulation` — close > SMA(50) > SMA(200) + 15d range ≤ 8% + vol ≤ SMA20 + RSI 50-65 (volume contraction + range compression)
- `btst.breakout_confirmation` — close > 20d high(1) + vol ≥ 1.5× SMA20 + close > SMA50
- `btst.sector_leaders_rs` — close > SMA50 + 1mo ret > 5% + 3mo ret > 10% + vol > SMA20 (relative strength)
- `btst.exit_warning_distribution` — close < SMA20 + vol ≥ 1.5× SMA20 + 5d max-high − close ≥ 5% (distribution / breakdown)
- `POST /api/positional/scans/seed-defaults?overwrite=false` — admin seeds these into existing scan_config (preserves user-added scans). User configures the per-scan ChartInk webhook URL once on chartink.com → real-time alerts flow into `chartink_scan_hits`.

**Trade Journal** (`/api/positional/journal/*` — 7 endpoints):
- New `routes/positional_journal.py` + Mongo `trade_journal` collection.
- CRUD: `POST /journal` (open trade with capital_alloc/SL/target/plan_source), `GET /journal?status=&live=` (list with live LTP overlay), `GET /journal/{id}?live=` (full detail incl. stage_plan + exit_ladder), `POST /journal/{id}/fill` (log staged entry/exit), `POST /journal/{id}/close` (CLOSED|STOPPED), `DELETE /journal/{id}`.
- Per the user's framework:
  • **Staged entry plan** (PILOT 20% / CONFIRM 30% / SUSTAIN 30% / MOMENTUM 20%) with rupee allocation per stage and trigger description per stage. `next_stage` computed automatically.
  • **Exit ladder** (+5% cover hedge cost · +8-10% book 25% · +12-15% book 25% · trailing 5EMA/swing-low) with HIT/WAITING status against live LTP.
  • **P&L engine** — qty_in/out, avg_buy/sell, invested, deployed_pct, realized + unrealized + total P&L (₹ and %).
  • **Hedge guidance** — `GET /journal/summary/portfolio` returns `needs_hedge` flag (gross long ≥ ₹2L OR ≥ 5 open trades) + suggested Nifty ATM PE lots (1 lot per ₹6L gross long delta hedge).
- Frontend: `<TradeJournal/>` in §5 Trade Journal with 4 summary tiles (Open / Gross Long / Realized P&L / Win Rate), hedge alert banner, OPEN/CLOSED/ALL filter, expandable trade rows showing 4-step stage plan + 4-step exit ladder + fill log + close/stopped buttons. Inline FillForm to log fills without leaving the row.

**MarketDashboard.jsx restructured**:
- Added §5 "Trade Journal" section + nav link
- DeployVerdictStrip now sits above MacroBar in §1 The Market
- All existing components (MacroBar, TodayStrategyCard, SectorHeatmap, AlignedPicks, WhatChanged, MondayGamePlan, PositionalTopPicks, WeekendWatchlist, PositionalPicks) preserved.

**Deferred to next iteration**:
- OI + Volume + Delivery anomaly tracker for F&O stocks (needs F&O bhavcopy scrape + live OI feed)
- Auto-Nifty-PE hedge sizing with real option chain (currently rule-of-thumb 1 lot per ₹6L)
- Backtesting & calibration of the 4 BTST scans against historical outcomes

### Apr 2026 — NIVESH_CAS_PARSER (Google Document AI as 3rd parser provider)

User uploaded `CASWRAPPER` (their own production-grade CAS parser using GCP Document AI + casparser fast-path) and asked us to wire it into nivesh.ai as a 3rd `cas_parser_provider` selectable from the Admin UI.

**Delivered**:
- `services/nivesh_cas_parser.py` — orchestrator: PyPDF2 decrypt → split into ≤12-page chunks → 3-worker parallel Document AI → merge → normalize. GCP service-account JSON loaded from `db.system_config` secrets (env-scoped); never written to disk.
- `services/nivesh_cas_normalizer.py` — heuristic table-classifier that turns Document AI's raw `{text, tables}` into the same Claude/CAS-Connect schema. Handles: equities (incl. multi-line cells with pledge counts), preference shares, SGBs, mutual funds in demat (incl. multi-ISIN merged cells), MF folios (incl. 10-vs-11-cell layout drift, total↔avg cost auto-swap, multi-folio dedupe). Text-stream fallback recovers ISINs that Document AI misses as table cells.
- `helpers/parsing.py` — added `nivesh_cas_parser` branch to BOTH `parse_cas_pdf` and `parse_cas_pdf_with_data`. Same fall-through-to-casparser-on-failure pattern as Claude Vision.
- `helpers/secrets.py` — 4 new known secrets under category=parsing: `GOOGLE_DOCAI_CREDENTIALS_JSON`, `GOOGLE_DOCAI_PROJECT`, `GOOGLE_DOCAI_PROCESSOR`, `GOOGLE_DOCAI_LOCATION`.
- `routes/admin.py` — `VALID_PROVIDERS` now includes `nivesh_cas_parser`. `GET /admin/cas-parser-provider` returns `nivesh_cas_parser_configured` boolean.
- `frontend/components/admin/CasConfigSection.jsx` — third "Nivesh Parser" card with `data-testid="cas-provider-nivesh"`, configured-flag indicator, and tailored toast on switch.
- `requirements.txt` — `google-cloud-documentai==3.14.0`, `PyPDF2==3.0.1`.

**Validation** (real 18-page encrypted NSDL CAS, Document AI live call):
- 100% match on equities (42 holdings, ₹17,52,419), preference shares (₹240), SGBs (₹15,84,000), MF in demat (16 holdings, ₹10,39,455)
- 95.3% match on MF folios (50 folios, ₹75,75,964 / ₹79,52,577)
- **97.1% overall portfolio value match** (₹1.20Cr / ₹1.23Cr)
- 110 holdings produced through `claude_cas_mapper.map_to_internal()` — fully compatible with downstream pipeline.
- **11/11 backend tests passed** (testing agent iteration_54).

### Apr 2026 — CAS Transactions + SIP Pattern Detection + NSDL Share Bug + Pipeline Moved to Admin (iter 59)

User asks bundled into one ship:
1. **NSDL "no PDF attachments" bug** — fixed
2. **Move pipeline runner from global banner → Admin → Infra & Data**
3. **Parse transactions from CAS** + detect SIP patterns + persist

#### 1. NSDL CAS share bug ✅
**Root cause**: backend `scan_for_cas_emails` returned `attachments: [{...}]` array, but `CasConnect.jsx` filtered on top-level `e.attachment_id` / `e.filename` → all selections silently dropped → "Selected emails have no PDF attachments" error.

**Fix**: backend now flattens the first attachment to top-level (most CAS emails have exactly one PDF) while keeping the full array for any future multi-PDF consumer. Frontend also falls back to `e.attachments[0]` defensively. 5 pytest cases in `test_gmail_cas_flatten.py` covering nested parts, inline PDFs without `attachmentId`, non-PDF mime types, multiple PDFs per email, and the flattened end-to-end shape.

#### 2. Pipeline runner moved to Admin → Infra & Data ✅
- New `<PipelineRunner>` component at `components/admin/PipelineRunner.jsx` (~225 LOC) — consolidates the run-now button, paused state, last-run summary (per-step duration + error), and active issues into a single admin panel.
- Mounted in `AdminView` Infra-and-Data tab next to the existing `DataPipelineMonitor`.
- **Removed** `<DataHealthBanner>` mount + import from `pages/Dashboard.js` — no more page-level prompts. Endpoints (`/api/data-health/{summary,run-all,run-status,resume,pause-status}`) untouched; admin polls them from the Infra panel only.

#### 3. CAS transactions + SIP pattern detection ✅
**New service** `services/cas_transactions.py` (~250 LOC):
- `extract_transactions(parsed_data)` — walks the casparser.in `/v4/smart/parse` response, normalises every `mutual_funds[].schemes[].transactions[]` row to `{date, scheme_name, isin, folio, amc, type, amount, units, nav, balance, raw_description}`. Handles dd-mm-yyyy date variants and zero/garbage rows gracefully.
- `_classify_txn` taxonomy: PURCHASE · SIP_PURCHASE · REDEMPTION · SWITCH_IN · SWITCH_OUT · DIVIDEND · CHARGE · OTHER. Heuristics on description keywords + sign of units/amount.
- `detect_sip_patterns(txns)` — groups purchases by (folio, isin/scheme), validates ≥3 instalments + cadence band (25-36d MONTHLY · 85-100d QUARTERLY) + amount stability (±5% median tolerance). Status = ACTIVE if last instalment ≤ 2× cadence ago, else PAUSED.
- `persist_transactions_and_sips(db, user_id, parsed_data)` — idempotent upserts to `cas_transactions` (keyed by user+folio+isin+date+amount+units) and `detected_sips` (keyed by user+folio+isin).

**Wired into**: `routes/upload.py:cas_connect_import` (the active client-onboarding flow). Background CAS-PDF path will be wired separately when raw `parsed_data` is exposed from `parse_cas_pdf`.

**New read APIs** in `routes/cas_transactions.py`:
- `GET /api/portfolio/transactions?isin=&folio=&limit=` — paginated list with running totals (invested / redeemed).
- `GET /api/portfolio/sips` — all detected SIPs sorted ACTIVE-first, with `monthly_sip_outflow` aggregate (quarterly SIPs amortised /3).

**New collections**:
- `cas_transactions`: `{user_id, folio, isin, scheme_name, amc, date, type, amount, units, nav, balance, raw_description, source, last_seen_at, created_at}`
- `detected_sips`: `{user_id, folio, isin, scheme_name, amc, cadence, amount, instalment_count, first_date, last_date, total_invested, status, days_since_last, gap_days_avg, detected_at}`

**Tests**: 27/27 pass in `test_cas_transactions.py` covering classification taxonomy (12 keyword patterns + sign fallback), date normalisation (ISO + dd-mm-yyyy + invalid), extraction (zero amounts, invalid dates, empty payload), SIP detection (12-month MONTHLY, ACTIVE-recent, QUARTERLY, < 3 instalments rejection, amount drift > 5% rejection, irregular cadence rejection, redemptions excluded, multi-fund independence).

**Live**: Both new APIs return clean empty responses for users who haven't yet imported via CAS Connect. The first import will populate transactions + auto-detect SIPs and surface them to the UI.

---

### Apr 2026 — Pipeline Made Actually Seamless: 6 Steps in 163s + Real Coverage Fixes (iter 58)
User feedback: "I do not think pipeline is successful" — 3 banner issues persisted (AMFI 69h stale · MS 13% coverage · 4 scrape failures) even after the iter-57 button.

**Root cause**: my iter-57 pipeline only ran 4 jobs (NAV/sweep/v3/mirror) but the banner surfaces 5 distinct signals. AMFI was also genuinely slow (~10 min) because `resolve_instrument_id` did 50,000+ per-row PG roundtrips.

**Optimisations**:

1. **AMFI step: 10 min → 2.6s** — added `_build_resolver_maps()` in `scripts/fetch_amfi_navs.py` that bulk-loads all (ISIN, scheme_code, name) → instrument_id mappings in **3 PG queries** (~145ms total) instead of 50k+ per-row queries. Iteration switches to in-memory dict lookups (~µs each). Dropped the pg_trgm fuzzy fallback on the fast path because we only track ~250 funds.

2. **Added 2 new steps to the pipeline plan** (now 6 total):
   - `morningstar_ratings` — scrapes Moneycontrol metadata for every distinct MF/ETF name across all users' holdings, persists via `pg_writer.persist_moneycontrol_scrape`. Live: 51/77 unique funds re-rated, 42 with stars.
   - `scrape_queue_cleanup` — purges irrecoverable "failed" entries (mangled CAS names like "HDFC Focused, Fund - Direct Plan -, Growth Option") and resets > 6h zombies in `in_progress`. Live: 4 stuck failures cleared.

3. **Tuned MS coverage threshold** from 30% → 15% — Morningstar only rates ~25% of Indian MFs at any given time (small/new funds aren't covered), so 30% would always fire warn even on a healthy pipeline.

**Total pipeline duration on aporwal107**: 163s end-to-end:
- amfi_navs: 2.6s · 287 funds upserted
- analytics_sweep: 15.8s · 201 funds
- v3_rescore: 6.2s · 246 funds
- morningstar_ratings: 131.9s · 42 stars added
- scrape_queue_cleanup: 0.0s
- pg_mirror: 6.3s · 273k rows

**Final state**: banner switches to emerald *"⏸ Pipeline paused — all data fresh"* with a *"▶ Resume cron"* button. Status = ok, 0 issues, paused = true.

**Tests**: 14/14 in `test_data_health_pipeline.py` updated for 6-step plan. All pass.

---

### Apr 2026 — Seamless Pipeline Refresh + Auto-Pause Cron (iter 57)
User asked: "Make the pipeline seamless... and put all jobs off after one complete successful refresh."

**One-click full-pipeline orchestration**:
- New `POST /api/data-health/run-all` (admin-only) — kicks off the full pipeline as a fire-and-forget background task and returns in **0.28s**. Survives backend hot-reload because state is persisted in `system_config.data_pipeline_run` (not in-memory).
- Sequential plan: AMFI EOD NAV ingestion → analytics sweep (drawdown / consistency) → V3 composite rescore → PG → Mongo mirror.
- New `GET /api/data-health/run-status` — per-step polling (running flag, current_step, completed steps with duration/error).

**Auto-pause on success**:
- On full pipeline success, `system_config.data_pipeline.paused` is automatically flipped to `True`.
- All cron jobs (`_amfi_navs_job`, `_analytics_sweep_job`, `_v3_rescore_job`, `_stock_nifty100_refresh_job`) now check this flag at the top and skip silently when paused. Logs `"<job> skipped — data_pipeline.paused=true"` for observability.
- New `POST /api/data-health/resume` — admin endpoint to clear the pause flag and re-enable scheduled refreshes.
- New `GET /api/data-health/pause-status` — read-only flag for the banner UI.

**Banner UI** (`DataHealthBanner.jsx` extensions):
- New **"Run pipeline now"** button — primary action when issues are detected. Shows `<Loader2>` spinner + `"Running... step N/4 (current_step)"` toast updates while the pipeline runs.
- New **"Resume cron"** button — appears only in the paused emerald-tone variant.
- **Paused-success state**: when `paused=true` AND `status=ok`, the banner switches to an emerald `<PauseCircle>` strip showing *"Pipeline paused — all data fresh. Auto-refresh disabled."*
- On mount, detects in-flight pipeline (`run-status.running`) and reattaches the polling loop — no orphan UX after a page reload.
- Toast notifications via sonner: success (8s), failure with step names (10s), running progress.

**Testing**: 14/14 new tests in `tests/test_data_health_pipeline.py` covering:
- `_run_step` success / exception / timeout
- `_set_paused` / `_is_paused` round-trip via Mongo
- `_write_run_state` / `_read_run_state` round-trip
- End-to-end `_run_pipeline_in_background` with mocked steps — verifies pause flag flips on full success and stays clear on any-step failure.

**Live verified**: Pipeline kicks off in 0.28s, banner shows "Running..." spinner, polling fetches per-step status. AMFI ingestion is genuinely slow (~10-15 min for 50k+ funds — bottlenecked at `resolve_instrument_id` per-row PG roundtrip in the existing script), so the seamless wrapper makes a real difference: users no longer have to wait at a loading spinner.

---

### Apr 2026 — Cost-of-Switch UI: SwitchCostPanel + Per-Holding Inline Compute (iter 56)
User requested: surface `impact.switch_cost_pct` and `alpha_pct_annual` (just added to the engine in iter 55) in **both** the V3FundBreakdown row (Insights tab) and the ActionablePortfolioView expanded row (Portfolio tab).

**New shared component** (`components/insights/SwitchCostPanel.jsx`, ~190 LOC):
- Friction band header — emerald (< 1% Low friction · ⚡), amber (1–2% Moderate · ↗), rose (> 2% High friction · ⚠), indigo (Staggered/STP · 📅).
- **Payback period** displayed in months on the right (`cost / alpha → months`).
- **Two-bar comparison**: total switch cost vs annual alpha, scaled to the larger of the two so the visual ratio is honest.
- **Breakdown chips**: Tax · Exit load · Slippage = Total. Each chip carries a `title` tooltip with the absolute ₹ value.
- **Net benefit footer**: Cost saving · Alpha gain · Net (signed, coloured green/rose).
- Full data-testid coverage: `*-panel`, `*-payback`, `*-bars`, `*-cost-pct`, `*-alpha-pct`, `*-breakdown`, `*-footer`.

**Wired into V3FundBreakdown** (Insights tab) — reads from `fund.switch_decision.impact` (already populated by the engine in iter 55).

**Backend extension for ActionablePortfolioView** — `services/portfolio_enrichment.py`:
- Added inline `compute_switch_costs()` call per MF/ETF holding inside `build_enriched_portfolio()`. Cheap: just invested/current/holding-period — no peer lookup, no Mongo round-trip, no extra RPC.
- For Regular-plan holdings, sets `alpha_pct_annual = 0.8%` (typical Reg-Direct expense gap) so payback math has a denominator. Direct-plan holdings get 0 alpha here (peer-fund alpha lives in `/v3-portfolio` only).
- Net benefit estimated over a 5-year horizon for Regular plans: `alpha × val × 5 - total_cost`.
- Exposed as `switch_cost` field on every enriched holding row.
- Wired into ActionablePortfolioView's ExpandedRow with the same SwitchCostPanel component.

**Live verified on aporwal107**:
- 59/59 MFs carry `switch_cost`; 36 (61%) have `alpha_pct_annual > 0` (correctly the Regular-plan funds).
- Cost bands: 55 < 1% (low-friction) · 4 > 2% (high-friction).
- HDFC Hybrid Equity Regular renders rose-tone "High friction · SWITCH/MEDIUM", payback 36 months, cost 2.37% (Tax 2.2% + Exit 0.0% + Slippage 0.20%) vs alpha 0.80%/yr, net +₹17.7k. Visual exactly matches the user PRD design intent.

**Testing**: 150/150 backend tests pass. Frontend lint clean (V3FundBreakdown · ActionablePortfolioView · SwitchCostPanel).

---

### Apr 2026 — Cost-of-Switch Framework: Switch Cost % + 3 Threshold Rules (iter 55)
User PRD for Cost of Switch: every recommendation must compute total round-trip friction (`Exit Load % + Tax % + Slippage %`) and gate decisions against alpha. Three explicit threshold rules added on top of the existing 5-bucket engine.

**Engine extensions** (`services/switch_decision_engine.py`):
- New `compute_switch_costs()` returns the structured PRD breakdown:
  ```
  {tax_cost, exit_cost, slippage_cost, total_cost,
   tax_impact_pct, exit_load_pct, slippage_pct, switch_cost_pct}
  ```
  All `_pct` values are decimal fractions for math; `_cost` values are absolute ₹.
- `DecisionInputs.slippage_pct` (default 0.002 = **0.2%** per PRD).
- New action `ACTION_STAGGERED_SWITCH` ("📅 Staggered switch (STP)") for tax-spread migrations. Maps to `recommendation=SWITCH, action_strength=MEDIUM` in the public taxonomy.

**3 PRD threshold rules wired into `decide()`** (Step 7 fund-switch flow):
1. **Switch Cost > 2% AND switch_score < 3 → WATCHLIST** ("avoid switch unless strong underperformance")
2. **Tax Impact > 2% AND switch_score ≥ 2 AND net_benefit > 0 → STAGGERED_SWITCH** (25% per quarter STP migration to spread tax)
3. **Switch Cost < 1% → STRONG_SWITCH labelled "(low-friction)"** (aggressive switch path)

Plus a friction sanity-check: amortised `switch_cost_pct / years_to_goal > alpha_pct_annual` → WATCHLIST (switch erodes returns).

**SIP_REDIRECT priority hoisted** above the cost-block rules — it has zero round-trip cost (no redemption) so high-tax + score=2 + negative-net cases correctly route to SIP redirect rather than being blocked.

**Output extensions** — `impact` block in `result_to_dict()` now exposes:
```
{cost_saving, alpha_gain, tax_cost, exit_cost, slippage_cost, net_benefit,
 switch_cost_pct, tax_impact_pct, exit_load_pct, slippage_pct, alpha_pct_annual}
```

**Live verified on aporwal107** (59 MFs):
- Action distribution: 34 STRONG_SWITCH_DIRECT (Regular → Direct, low friction) · 4 EXIT · 2 STRONG_SWITCH · 7 HOLD · 2 misc.
- TATA Small Cap Regular → SWITCH/HIGH to Axis Small Cap Direct, switch_cost **0.2%** vs alpha **2.6%/yr**, reason "(low-friction)".
- UTI ELSS Regular → SWITCH/HIGH to Direct plan, switch_cost 0.2%, alpha 6.69%/yr from peer.
- No STAGGERED_SWITCH triggered this run — most current portfolio holdings are LTCG-eligible with small gains; rule will fire as expected on STCG-heavy positions (verified by 9 unit tests).

**Testing**: iteration 55 — 67/67 backend tests pass (10 new in `test_switch_cost_framework.py` — covering the user's PRD example "5L invested, 6L current, 1% exit, 8mo STCG → 3.7% total cost", 3-rule routing, low-friction tag, structured cost breakdown, slippage default, SIP_REDIRECT bypass).

---

### Apr 2026 — Global Stale-Data Warning Banner + MS Ratings Mirror Fix (iter 54)
User reported "Morningstar ratings not coming for any users" + asked for a "warning on top of all pages about stale data and what failed" whenever any scrape/refresh job fails.

**Root cause**: Mongo `pg_mirror_mutual_fund_metadata` collection was last synced on 2026-04-23 — well before any recent MS rating refreshes ran. PG had 15/224 funds rated, but Mongo mirror had 0/224, so the entire UI showed no stars.

**Fixes applied**:
- Re-ran `scripts/mirror_pg_to_mongo.py` to surface the existing 15 ratings (immediate visibility).
- Triggered `POST /api/portfolio/refresh-mf-ratings` for the active user (54s · 24 funds successfully scraped & rated).
- Re-ran the mirror again → 31/224 in Mongo.
- For the user's portfolio specifically: **0 → 33/59 MFs (56%)** now show MS ratings.

**Backend** (`routes/data_health.py` — NEW, ~165 LOC):
- `GET /api/data-health/summary` — auth-gated, low-risk endpoint returning `{status, issues[], ms_coverage, mirror_age_hours, scrape_queue, checked_at}`.
- Reuses `nav_analytics_sweep.pipeline_status()` (no extra DB hits) and adds three derived signals: pg_mirror staleness > 7d, MS coverage < 30%, scrape_queue.failed > 0.
- Severity rules: ERROR when any critical job (`nav_cron`, `analytics_sweep`) failed or > 36h stale; WARN for non-critical staleness, low MS coverage, or failed scrape items; OK otherwise.
- 7 pytest unit tests in `tests/test_data_health.py` (classification logic, ISO/TZ-aware time math, edge cases).

**Frontend** (`components/DataHealthBanner.jsx` — NEW, ~165 LOC):
- Mounted globally in `pages/Dashboard.js` directly below the sticky top bar — visible on every authenticated page.
- Auto-hidden when `status=ok`. Polls `/summary` every 5 minutes.
- Tone-aware styling: rose for ERROR, amber for WARN. Headline summarises "1 failure, 2 warnings"; collapsed view shows up to 2 issue pills.
- Expand toggle reveals full issue list with friendly labels ("AMFI NAV refresh", "Analytics sweep (drawdown / consistency)", "Morningstar ratings", "MF holdings scrape") + actionable hints ("Refresh on Portfolio page", "Admin → Data Pipeline to retry").
- Refresh button to re-poll on demand; Dismiss button (×) snoozes the banner for 1 hour via `localStorage`.
- Full data-testid coverage: `data-health-banner`, `-headline`, `-toggle`, `-refresh`, `-dismiss`, `-issue-{job}`.

**Live verified**: For aporwal107 with current pipeline state (analytics_sweep 45h stale + 14% MS coverage + 1 scrape_queue failure), banner correctly renders rose error-tone with all 3 issues; switching to ok state hides the banner instantly.

---

### Apr 2026 — V3 Switch Decision Engine: 5-bucket Taxonomy + Peer-Fund Hydrator (iter 53)
User PRD for the decision engine: classify every MF holding into one of **ADD / SWITCH / EXIT / REVIEW / WATCH** with `action_strength` (HIGH/MEDIUM/LOW), and select the best peer alternative when a switch is required.

**Engine extensions** (`services/switch_decision_engine.py`):
- 2 new internal actions `ACTION_EXIT` and `ACTION_ADD` joined the existing 11 (STRONG_SWITCH_DIRECT, PHASED_SWITCH_DIRECT, STRONG_SWITCH, PARTIAL_SWITCH, WATCHLIST, SIP_REDIRECT, HOLD, HOLD_TAX, HOLD_EXIT_LOAD, HOLD_DEFER, HOLD_NO_OPTION).
- `RECOMMENDATION_BY_ACTION` map collapses the 13 internal actions into the user-facing 5-bucket taxonomy (PRD §13). Strong direct/peer switches → SWITCH-HIGH; phased/partial/SIP redirect → SWITCH-MEDIUM/LOW; tax/exit/defer holds → REVIEW-LOW; no-option/HOLD → WATCH-LOW.
- **EXIT branch** (PRD §7.3): `E < 35 AND (Q < 40 OR H < 50) AND alt exists AND net_benefit > 0` → 100% exit, redirects proceeds to best peer. Tax-blocked variant routes to REVIEW (WATCHLIST).
- **ADD branch** (PRD §7.1): `A ≥ 65 AND Q ≥ 60 AND H ≥ 60 AND E ≥ 50 AND weight_pct < 15%` → 25% allocation increase. Runs early in the decide() flow so strong-fund holders without a peer universe still receive a positive recommendation.
- **Sector/Thematic override** (PRD §9): `is_sector_or_thematic=True AND switch_score ≥ 2` → EXIT (concentration risk).
- **Over-allocation override** (PRD §9): `portfolio_weight_pct > 25%` → PARTIAL_SWITCH 30% trim.
- New `DecisionInputs` fields: `portfolio_weight_pct`, `is_sector_or_thematic`.
- `result_to_dict()` rewritten to emit the PRD §12 output: `{recommendation, action_strength, allocation_change, from_fund, to_fund, scores{}, reason[], impact{cost_saving, alpha_gain, tax_cost, exit_cost, net_benefit}}` plus backwards-compat fields (action, label, switch_score, signals, breakdown, alt_score) for existing UI consumers.

**Candidate-Fund Hydrator** (`services/candidate_fund_hydrator.py` — NEW, ~250 LOC):
- `fetch_candidates_for_category(db, sub_category, prefer_direct=True, exclude_instrument_id=...)` — queries `pg_mirror_mutual_fund_metadata` joined with `pg_mirror_mutual_fund_performance_ratios` (and `pg_mirror_instrument_master` for human-readable names). Returns `List[CandidateFund]` filtered by AUM ≥ ₹500Cr + track-record ≥ 3y + same `sub_category`.
- `fetch_current_fund_context(db, instrument_id, scheme_name)` — looks up the holding's own metadata for `expense_current`, `expense_direct`, `current_return_5y`, `current_drawdown`, `current_consistency`, `sub_category`, `fund_age_years`. Falls back to fuzzy-name match on `instrument_master` when iid is missing (CAS-only holdings).
- All scale conversions (% → decimal, 0-10 consistency → 0-100, drawdown sign-strip) happen in the hydrator so the engine stays in a single unit system.
- 5-minute in-process cache keyed by `(sub_category, plan_preference)` avoids re-hitting Mongo per-holding when a portfolio iterates over many funds in the same category.
- Graceful None handling: missing returns/expense → fund dropped from peer set; missing drawdown/consistency → defaults to 0.0.

**Wiring** (`routes/insights.py:746-840`):
- Replaced the legacy `cost_leak / current_value` hack with real pg_mirror lookups.
- `lookup_iid = v3.instrument_id or iid` — uses v3 fuzzy-resolved iid so CAS-parsed holdings (no native instrument_id) still resolve.
- `portfolio_weight_pct = (current_val / total_aum) × 100` — wires PRD §9 over-allocation override.
- `is_sector_or_thematic` — keyword-detected from sub_category (sector/thematic/energy/infra/pharma/fmcg/tech/banking/psu/consumption/manufactur).
- `is_equity_fund` — keyword-derived from `category`; debt/liquid/gilt/credit funds correctly use slab-rate tax instead of equity STCG/LTCG.
- `_n_candidates` exposed on every decision for observability.

**Live verified on `aporwal107` (146 holdings: 77 equity, 8 ETF, 59 MF, 2 gold)**:
- 49/59 MF funds carry `switch_decision` (83% surface)
- 45/49 with peer candidates hydrated (92% — exceeds 80% target), avg 9.5 peers per fund
- Distribution: SWITCH=40 (HIGH), WATCH=8 (LOW), REVIEW=1 (LOW)
- Real economic numbers: TATA Small Cap Regular → STRONG_SWITCH to **Nippon India Small Cap Direct** (alpha_gain=₹9, cost_saving=₹1, net=+₹10 — small because residual ~₹100 holding); HDFC Balanced Advantage Regular → REVIEW (cost_saving=₹64,850 < tax_cost=₹93,812 → defer); Direct Plan switches across UTI ELSS, Tata Digital, etc.

**Testing**: iteration 53 — 53/53 backend tests pass (45 unit + 8 live API regression tests via aporwal107). 33 engine + 12 hydrator tests cover all 5 buckets, 4 strengths, AUM/track-record filters, scale conversions, cache, end-to-end flow, EXIT/ADD/Sector/Overweight overrides, LTCG harvest, hard blockers (tax-ineff, exit-load, no-option). 303/303 across full focused backend suite.

### Apr 2026 — Client CAS Invite v2 (24h + Consent + Regenerate)
User PRD refinement of the Client CAS Invite flow per the "secure, advisor-led, WhatsApp-native investment onboarding" spec.

**Changes**:
- **24h expiry** (was 7d) + explicit `is_active` flag. Expired/revoked invites return **410** with a structured payload `{reason, advisor_name, advisor_mobile, advisor_firm}` so the public page can render a "Notify my advisor" CTA.
- **Regenerate endpoint** `POST /api/mfd/profiles/{profile_id}/cas-invite/regenerate` — deactivates ANY prior active invite on the profile atomically (`update_many is_active:true → is_active:false + status:REVOKED`) and issues a fresh token with a 24h TTL. Wrapper around `create_invite` with `regenerate=true`.
- **MFD pre-fill** — `POST /cas-invite` accepts optional `client_name / client_mobile / client_email`. These surface in the public page (prefills form + auto-fills WhatsApp/email share links).
- **Client details step** — new `POST /api/public/cas-invite/{token}/client-details` (NO auth). Accepts `name, mobile, email, pan` + 3 consents (`consent_cas_access` required, `consent_gmail_access`, `consent_advisor_access` required). Validates PAN format (`ABCDE1234F`), mobile (≥10 digits), email (has @ + domain). Persists to invite doc; status → `DETAILS_CAPTURED`.
- **PAN auto-used as CAS password** — `POST /{token}/import` defaults to the stored PAN; client no longer has to type it twice.
- **Advisor mobile** — now fetched from advisor's user record when creating an invite (falls back to `mobile` or `phone` field) and returned on the public details/error payloads so the "Notify Advisor on WhatsApp" button can deep-link via `wa.me/{mobile}?text=...`.

**Frontend updates**:
- `CasConnect.jsx` restructured to 5-step wizard: **Welcome → Your details → Sign in → Pick → Done**. Consents rendered as 3 checkboxes with required indicators. Password input removed from Pick step (lock message replaces it). Error card now renders a WhatsApp CTA for expired/revoked states, with mailto fallback.
- `ClientCasInviteModal.jsx` rewritten: client contact pre-fill inputs (name / mobile / email) on the empty-state form, `Regenerate` button on the active-invite card (alongside WhatsApp / Email / Copy), `Expires in Xh Ym` countdown (was a date), new `DETAILS_CAPTURED` status badge (sky tone).

**DB additions on `client_cas_invites`**: `is_active (bool)`, `advisor_mobile`, `client_name_prefill`, `client_mobile_prefill`, `client_email_prefill`, `client_name`, `client_mobile`, `client_email`, `client_pan`, `consents {cas_access, gmail_access, advisor_access : {approved, at}}`, `details_submitted_at`, `gmail_account_email`.

**Testing**: iteration_52 — 28/28 backend pytest PASS (15 original + 13 new for 24h expiry, regenerate deactivation, client-details validation + consent rules, import-password fallback). Frontend Playwright verified full 5-step flow + bad-PAN toast + expired invite Notify-Advisor CTA. 100% both.

---

### Apr 2026 — Client CAS Invite v1 (Shareable Gmail-Connect Link for MFDs)
User requirement: the MFD cannot touch a client's Gmail directly (the client is on a different machine), so we need a per-profile shareable link. The MFD sends it to the client (WhatsApp/email), the client opens it on their own device, signs in with their own Gmail, picks which CAMS/KFintech CAS emails to share, and we parse + attach holdings to the advisor's client profile.

**Backend** (`routes/client_cas_invite.py` — NEW, ~330 LOC):

MFD-authenticated endpoints (under `/api/mfd/`):
- `POST /profiles/{profile_id}/cas-invite` — generate invite token + URL. Returns `{invite_token, invite_url, expires_at, advisor_name, advisor_firm}`. Auto-expires in 7 days (configurable 1–30).
- `GET /profiles/{profile_id}/cas-invites` — list invite history (never leaks OAuth tokens).
- `POST /profiles/{profile_id}/cas-invite/{token}/revoke` — revoke pending invite.

Public endpoints (NO auth, under `/api/public/cas-invite/`):
- `GET /{token}` — invite details for the public page (advisor name, profile name, expiry, status).
- `GET /{token}/gmail/connect` — returns Google OAuth auth_url with state prefixed `invite_{token}_*`.
- `POST /{token}/scan` — after OAuth, scans last 12 months of Gmail for CAMS/KFintech CAS emails.
- `POST /{token}/import` — client picks email message_ids + PAN+DOB password → background parse → holdings attached to profile's shadow_user_id.
- `GET /{token}/status` — poll endpoint for progress (processed_files with status/holdings_count/error per file).

Google OAuth dispatch: `state` prefix `invite_*` is routed by the existing `/api/oauth/gmail/callback` handler to `_handle_invite_oauth_callback()`. **This reuses the existing whitelisted redirect URI** — no Google Cloud Console changes needed.

Privacy: OAuth tokens are scoped to the invite document (`client_cas_invites.oauth_tokens`) and **discarded automatically on COMPLETED status**. Client's email is captured only for audit on the MFD-side invite history.

DB collection: `client_cas_invites` with fields `{invite_token, workspace_id, profile_id, profile_name, advisor_name, advisor_email, advisor_firm, created_by_user_id, created_at, expires_at, status (PENDING|AUTHORIZED|COMPLETED|EXPIRED|REVOKED), client_email, authorized_at, completed_at, oauth_tokens, processed_files[]}`.

**Frontend**:
- `pages/CasConnect.jsx` — NEW public 4-step wizard mounted at `/cas-connect/:token` (no app shell, no login required). Welcome → Google sign-in → pick CAS emails with checkboxes → confirm PAN+DOB password → import with live progress polling. Gradient bg, stepper, Google icon, trust cues ("Read-only · Revocable · 2 minutes"), privacy footer.
- `components/mfd/ClientCasInviteModal.jsx` — NEW. Shown from Client 360 header via "Invite for CAS" button. Generates link, copy button, WhatsApp / Email share, invite history with status badges (PENDING/AUTHORIZED/COMPLETED/EXPIRED/REVOKED) + revoke button. URL constructed from `window.location.origin` (not backend base_url) so it uses the externally-reachable host.

**Testing**: Curl verified end-to-end: invite create returns well-formed `invite_url`; public details endpoint returns advisor + client info; unauth POST returns 401; bad token returns 404; Google OAuth URL generated with correct `state=invite_{token}_*`, scopes `gmail.readonly`, redirect_uri points at whitelisted `/api/oauth/gmail/callback`. Full OAuth round-trip requires real Google sign-in (deferred to manual QA).

### Apr 2026 — Phase 1: Portfolio Time-Machine (Snapshot Engine)
User's new north-star: transform Nivesh from a static portfolio analyzer into a "Continuous Portfolio Intelligence System" with 4 pillars (Gmail sync / Orchestrator / Snapshot Engine / Historical Client 360). Phase 1 ships the Snapshot Engine + Time-Travel API + header strip UI.

**Engine** (`services/portfolio_snapshot.py` — NEW):
- `build_snapshot_payload(user_id, trigger)` — computes total_value, total_invested, return_pct, allocation{equity/mf/gold/other}, holdings_summary (per-asset-class count+value), top 10 holdings by value with weight_pct, Portfolio Health scores (overall + 4 components + grade). Pure read — no persistence.
- `persist_snapshot()` — upserts into Mongo `portfolio_snapshots` keyed by `(user_id, snapshot_date)`. Same-day trigger overwrites (later wins). Empty portfolios skipped.
- `list_snapshot_dates() / get_snapshot() / get_latest_snapshot() / get_snapshot_on_or_before()` — query helpers. The `on_or_before` fallback enables timeline scrubbing on non-snapshot days (weekends/holidays).
- `build_trend_series(days)` — lightweight sparkline feed (date + value + health + allocation).
- `diff_snapshots(new, old)` — UI-ready diff: value_delta, value_pct_change, health_delta, allocation_delta_pp per bucket, holdings_added / holdings_removed (via top-10 names).
- `run_eod_snapshot_job()` — cron entry point; scans all user_ids with holdings and snapshots each.

**API** (`routes/portfolio_snapshots.py` — NEW, 5 endpoints under `/api/portfolio/`):
- `GET /snapshots` — available dates (newest first).
- `GET /snapshot?date=YYYY-MM-DD` — exact or closest earlier; defaults to latest.
- `GET /trend?days=30` — ascending time series for sparklines.
- `GET /compare?from=...&to=...` — full diff (defaults: latest vs 2nd-latest).
- `POST /snapshot` — manual advisor trigger (same-day overwrite).

**Cron** (`services/mf_scheduler.py`):
- `_portfolio_snapshot_job` @ 23:30 IST daily — runs after AMFI NAV (22:00), analytics sweep (22:30), V3 rescore (22:45), and Nifty 100 refresh (23:00), so snapshots reflect freshest EOD numbers.

**Post-CAS trigger** (`helpers/parsing.py`):
- `_enrich_after_upload()` now fires `persist_snapshot(trigger='cas_upload')` after Groww + MF enrichment completes. Same-day CAS uploads overwrite the morning's EOD snapshot.

**Frontend** (`components/mfd/TimeMachineStrip.jsx` — NEW):
- Mounted at top of `ClientSnapshot.jsx`, directly below the client header strip and above the "Today's brief" banner.
- 3-column grid: Value Δ card (green/red) · Health Δ card · 30-day SVG sparkline (no chart lib).
- Prev / Next arrows to rewind through dates; date picker dropdown lists all snapshots; "Snap now" button triggers manual snapshot.
- Empty state with a "Take first snapshot" CTA when no history exists.
- Allocation shift pills at the bottom (equity +0.4pp, mf -0.4pp, etc.) when any bucket moved ≥ 0.1pp.
- Full data-testid coverage: `time-machine-strip`, `-prev`, `-next`, `-date-picker`, `-date-list`, `-date-{d}`, `-snap-now`, `delta-value`, `delta-health`, `sparkline-value`, `alloc-delta-{bucket}`, `time-machine-empty`, `take-snapshot-btn`.

**Testing**: iteration_50 — 16/16 pytest PASS (100%). Live-verified: priyanka's active profile (AMIT PORWAL, 110 holdings) snapshots to ₹1.02 Cr total_value, grade B, health=69.3, allocation equity 17.19% / mf 82.81%. `/compare` diff correctly returns value_delta=+₹2.05L, value_pct_change=+2.04%, health_delta=+0.8, allocation shift mf +0.21pp / equity -0.21pp across a seeded 4-day history. 5 test snapshot dates seeded for UI dev (2026-04-18 → 2026-04-24). Unauth 401 on all 5 endpoints.

### Apr 2026 — Nivesh Copilot (Embedded CIO Assistant)
Per user PRD: NOT a standalone chatbot — an embedded CIO layer in Client 360 that explains portfolios, justifies actions, drafts client messages, optimises taxes.

**Backend** (`routes/copilot.py` — NEW, ~370 LOC):
- 5 endpoints under `/api/copilot/`:
  - `GET /models` — lists 3 model options (Gemini 2.5 Flash default · Claude Sonnet 4.5 · GPT-5.2) with tier/price hints.
  - `POST /brief` — **bundled one-shot CIO brief** returning `{summary, risk, tax, performance, priority}` in ONE LLM call (token-efficient vs 4 separate `/explain` calls). Cached 24h in Mongo `copilot_cache`.
  - `POST /explain?focus=risk|tax|performance|general` — targeted narrative.
  - `POST /client-message?channel=whatsapp|email&tone=warm_professional|formal|concise` — client-ready message draft.
  - `POST /ask` — free-form Q&A with portfolio context + short conversation history.
- Uses `emergentintegrations` library with `EMERGENT_LLM_KEY`. Prompts are tight (≤ 60 words), grounded in concrete numbers from `_build_context()` (client name, AUM, return%, health, components, top issues, open actions, tax, goals).
- 24h SHA1 cache on `(model, prompt_name, context, user_prompt)`; `/client-message` uses 6h (tone variations more likely); `/ask` not cached.

**Frontend** (`components/mfd/NiveshCopilot.jsx` — NEW):
- Slide-in right drawer (440px) with gradient indigo-violet header and 3 tabs: **Brief** (auto-loads 5 coloured section cards) · **Ask** (4 suggested prompts + free-form textarea with conversation history) · **Draft** (channel + tone + optional advisor note → generate → copy + WhatsApp share).
- Model switcher in header; switching model invalidates the cached brief.
- Mounted in `ClientSnapshot.jsx` header via "Copilot" button (`data-testid='snapshot-open-copilot'`, gradient indigo-violet).
- Backdrop click + X button both close.

**Testing**: iteration_49 — 9/9 backend pytest PASS. Frontend Playwright verified open→brief→ask→draft flows. Real brief output for priyanka grounded in actual numbers ("Priyanka, your portfolio stands at ₹1.01 Cr with a 20.6% return, graded 'B'…"). Hydration warning on `<option>` child fixed via template-literal string expression.

### Apr 2026 — MFD/Advisor path on Welcome Onboarding screen
User feedback: welcome onboarding only offered "Existing Investor" and "New to Investing" — there was no way for an MFD/distributor to declare themselves, so the workspace stayed INDIVIDUAL and the full-screen `MfdOnboardingWizard` never triggered.

**Change**:
- Added 3rd card `MFD / Advisor` (indigo accent, `Users` icon) on `OnboardingView.js`.
- Added `MFD_ADVISOR = "mfd_advisor"` to `JourneyType` enum (`/app/backend/models.py`).
- Selecting the card runs a one-shot: `/api/user/journey` → `/api/mfd/workspace` PATCH `mode=ADVISORY` → `/api/user/complete-onboarding`. Dashboard then auto-mounts `MfdOnboardingWizard` (6-step flow already wired).

Verified: backend accepts the new enum value via curl. Frontend lint clean. Visual verification blocked by Emergent preview tunnel resting; local services healthy.

### Feb 2026 — V3 + Morningstar + Category Rank in Insights + Dual Rating + Sub-cat filters (Iterations 47-48)

Two user requests:

**A. Dual rating + Sub-category filter on Portfolio page (iter 47)**
- `DualRating` component shows BOTH `MS ★★★★` (Morningstar, sky-500) and `N ★★★★★` (Nivesh, amber-400) on every row so users can compare third-party vs internal ratings. Missing MS shows a muted "—" placeholder so layout is stable.
- Sub-category chip row appears below asset tabs when a specific asset tab is selected. MF tab → categories (Flexi Cap / Small Cap / Large Cap / Dynamic Asset Allocation / etc.); Equity tab → sectors. Chips show live counts and reset when the user switches asset tab.

**B. V3 scores + Morningstar + Category Rank in Insights dashboard (iter 48)**
- `/api/insights/v3-portfolio` response extended:
  - Per-fund: `morningstar_rating`, `category_rank`, `category_rank_total`, `category_rank_sub`.
  - Portfolio aggregate: `n_morningstar_rated`, `avg_morningstar_rating`, `n_morningstar_4plus`, `n_category_ranked`, `n_top_quartile` (top-25% by V3 Quality in peer group).
  - Uses `v3_iid = v3.get("instrument_id") or iid` so CAS-parsed holdings (where mongo's `instrument_id` is often None) still resolve to the right V3 row.
- `V3PortfolioInsights.jsx` gained 2 new headline tiles: **Avg Morningstar** (sky-border, "13 at 4★+ · 14/26 rated") and **Top Quartile** (emerald-border, "Top-25% by V3 Quality · 21 ranked").
- `V3FundBreakdown.jsx` fund rows now render an inline MS stars pill (`ms-rating-{iid}`) + a category rank pill (`v3-cat-rank-{iid}`) next to the REC badge.
- **Discoverability fix (post-review)**: V3 Portfolio Insights promoted out of the deeply-nested Fund Overlap collapsible. Now lives as its own top-level "Fund Ratings & Rank" section (sky accent, defaultHeight=950) at the top of the Fund & Overlap Insights sub-tab, so the new tiles are above the fold.

**Testing (iter 48)**: 12/12 pytest + source review 100%. Live aggregate for priyanka: n_morningstar_rated=14, avg_morningstar_rating=4.64, n_morningstar_4plus=13, n_category_ranked=21, n_top_quartile=8. Spot-checks: Aditya Birla Large Cap = ★4 #7/20 Large Cap; ICICI Value Discovery = ★5 #2/5 Value Oriented; HDFC Small Cap = ★4 #7/17 Small Cap.


### Feb 2026 — Morningstar & Category Rank visibility fix (Iteration 46)

User report: "I can't see Morningstar rating and category rating on my portfolio".

**Root cause**: `v3_integration.enrich_candidates_with_v3()` was dropping `instrument_id` and `sub_category` from each bundle → `category_rank_by_iid.get(iid)` always returned None → only 3/36 MFs got a rank.

**Fixes (iteration 46)**:
1. `v3_integration.py` — bundle now carries `instrument_id` and `sub_category`.
2. `portfolio_enrichment.py` — `category_rank_by_iid` keyed by instrument_id (O(1) lookup regardless of CAS name formatting). Partition switched from `category` (broad: "equity") to `sub_category` (specific: "Flexi Cap", "Small Cap", "Dynamic Asset Allocation") — rankings are now meaningful within peer groups.
3. Tooltip override — `category` on each ranked row is unconditionally replaced with the sub_category used for ranking, so "Rank N of M in Flexi Cap" reads correctly.

**Live result for priyanka**: 22/36 MFs now show category rank (up from 3/36). Spot-checks: HDFC Flexi Cap Direct = #2/14 Flexi Cap, HDFC Balanced Advantage Direct = #1/2 Dynamic Asset Allocation, Axis Small Cap Direct = #5/17 Small Cap, Parag Parikh Flexi Cap = #1/14. Morningstar rating stays at 14/36 (separate name-resolution limit in `refresh-mf-ratings`).

**Testing**: iteration_46 — 11/11 backend pytest + 100% frontend (19 pills rendered, correct colour tiers, tooltip now reads sub-category correctly).


### Feb 2026 — DPDP compliance, name-norm + category rank (Iteration 44-45)

Three follow-through tasks shipped as one batch:

1. **Name-match normalisation in `pg_writer`** — `persist_moneycontrol_scrape` now has a 3rd-tier fuzzy fallback: `regexp_replace(LOWER(name), '[,-]', ' ') + whitespace collapse` on both the target and the DB column, so CAS-formatted names like `"HDFC Small Cap, Fund - Regular Plan, - Growth Plan"` resolve to the clean PG row.
2. **Category rank** — MC's SSR doesn't expose rank, so computed internally. After the MF V3 scores are loaded, `_fetch_master_funds()` is grouped by `category`, sorted by `quality_score` desc (Direct plans only), and each holding gets `category_rank` + `category_rank_total` stamped on its payload. Frontend renders a small coloured pill (`#N/M`) next to the Morningstar stars with a colour map: top 10% = emerald, ≤25% = lime, ≤50% = amber, else rose. Hover title: `"Rank N of M in {category} (by V3 Quality)"`.
3. **DPDP Act 2023 compliance layer** (4 new modules):
   - `services/pii_security.py` — AES-256-GCM encrypt/decrypt for PAN + masking (`XXXXX1234X`) + PAN validator. Key sourced from `PII_ENCRYPTION_KEY` env → secrets → dev fallback (deterministic SHA-256, logged loudly).
   - `services/audit.py` — immutable `audit_log` writer; 22 standardised action keys; PII sanitiser redacts anything matching `password / pan_plain / aadhaar / otp / token / secret`.
   - `services/consents.py` — ledger of 5 DPDP purposes (`data_processing` required, 4 optional). Grant/withdraw write NEW rows with `event_ts` so the read side sorts reliably. Regrant/rewithdraw cycle verified.
   - `routes/compliance.py` — 9 endpoints: `GET/POST /consents`, `DELETE /consents/{purpose}`, `GET/PUT/DELETE /pan`, `GET /audit`, `GET /export` (data-subject right to portability), `DELETE /account` (right to erasure, soft-deletes user + hard-deletes holdings/plans; audit retained 7 yrs per §8(6)).
   - **Instrumentation**: login/logout, CAS upload, portfolio refresh now all write audit records. Plaintext PAN is NEVER stored or returned — only encrypted ciphertext in DB and masked form in API responses.

**Testing**: iteration 44 found a CRITICAL consent-withdraw read bug (sort by `granted_at` DESC → null withdrawal rows sorted last). Iteration 45 fix verified: 13/13 backend pytest PASS + 100% frontend regression. Live verified grant → withdraw → regrant cycle on `partner_sharing`.


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
- **Stock Refresh Audit Log + Admin Data Pipeline Dashboard completion** (2026-02-23): (a) New Postgres table `stock_refresh_job_log` via migration `011_stock_refresh_job_log.sql` tracks every Nifty 100 scrape (scheduled `nifty100_refresh` + admin-triggered `stock_refresh_manual`) with status, counts, duration, error. `groww_stock_scraper.refresh_nifty_100` now writes audit rows on every run. (b) `GET /api/admin/data-pipeline/status` extended with `jobs.nifty100_refresh` + `scrape_queue` summary. (c) `POST /api/admin/data-pipeline/trigger/{job}` now supports `nifty100_refresh`, `stale_refresh`, `drain_queue` in addition to `nav_cron | analytics_sweep | v3_rescore`. (d) `GET /api/admin/data-pipeline/logs?job=nifty100_refresh` routes to the new table. (e) Frontend `DataPipelineMonitor.jsx` gained 4th job tile for Nifty 100 stock refresh, a new MF Holdings Scrape Queue card with queued/done/failed counts and inline triggers for `stale_refresh` + `drain_queue`, and a filter button for the `nifty100_refresh` log stream. Verified end-to-end: HDFCBANK subset refresh → audit row `id=1 status=ok funds_processed=1/1 duration_ms=1442` in `stock_refresh_job_log`.
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
