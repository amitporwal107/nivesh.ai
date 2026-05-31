# PRD — v5 Portfolio & Performance Dashboard

## Feature: v5 Portfolio & Performance Dashboard
**Status:** DRAFT · **Author:** ⟨your name⟩ · **Date:** 2026-05-29

## 1. Problem
Nivesh investors with large, fragmented MF portfolios (current dataset: 111 holdings across ~60 funds) can see *what* their returns are but not *why*. The v4 surface (health gauge, risk-vs-return bubble, benchmark donut, heatmap) is chart-heavy and verdict-light, has no plain-language takeaway, no return attribution, and no way to understand portfolio composition by asset class / sector / fund / AMC or to work with holdings in a detailed table. As portfolios grow past ~50 funds this becomes the top driver of "I don't understand my portfolio" support contacts and churn. v5 re-platforms the experience into a narrative-first dashboard (design ref: Screenshot 4 "Nivesh") and adds composition + detailed-holdings views.

## 2. Goals & non-goals
- **Goals:**
  - Lead every view with a generated plain-language verdict (e.g. "You beat the benchmark by 2.1 points").
  - Explain performance via a return-attribution waterfall and ranked contributors.
  - Add a Composition Explorer (asset class / sector / fund / group) and a Detailed Holdings table with drill-down.
  - Re-skin all existing v4 analytics into the v5 design system with no loss of capability.
  - Preserve every holding in totals even when benchmark data is missing.
- **Non-goals:**
  - No order placement, switching, or execution (routes to Plan board only).
  - No KYC/onboarding changes.
  - Tax module stays at its current WIP state — not re-specced here.
  - No new attribution factor-model research; v5 ships the agreed factor set (see §11).
  - Carry-over views may later be split into their own PRDs; this PRD specs them at parity, not redesign.

## 3. User stories
- As a retail investor, I want a one-line verdict on whether I beat the benchmark so that I understand my portfolio without reading charts.
- As an engaged investor, I want to see which decisions (sector tilt, stock picks, costs, cash) drove my alpha so that I can repeat what worked.
- As an investor with many funds, I want to break my portfolio down by asset class, sector, fund, and AMC so that I can spot concentration.
- As a hands-on user, I want a sortable, filterable table of all holdings with drill-down so that I can inspect any position.
- As any user, I want to export the current view so that I can share or file it.

## 4. Requirements

### Functional
1. **Shell** — Sidebar with DASHBOARDS (Overview, Concentration, Diversification, Risk, Performance, Goals, Tax) and WORKSPACE (Plan board, Portfolio builder, Chat copilot); active route highlighted. Top bar shows context breadcrumb `DASHBOARD · {VIEW} · {PERIOD}`, editorial verdict headline, status pill, Export, Resync, and `Plan a move →`.
2. **Period selector** — Global control (1M/3M/6M/1Y/3Y/Since inception) that drives all time-bound metrics and persists within a session.
3. **Performance KPI strip** — Period-matched portfolio return, Alpha (pp, after fees), Sharpe (with ≥1.0 pass marker), Hit rate (% of months beating benchmark).
   - **Return metric is period-matched:** when the period selector is "1M / 3M / 6M / 1Y / 3Y", the KPI shows the **period return** `= (current_value / value_N_periods_ago − 1)` for the portfolio AND the same-period benchmark return (e.g. `return_1y` when 1Y is selected). XIRR is **not** used for bounded periods.
   - **Since inception** is the only period where XIRR is shown — because XIRR is inherently a lifespan metric (money-weighted, needs all cashflow dates). The matching benchmark metric is the index CAGR from the portfolio's first investment date to today.
   - **Alpha** is always `portfolio_period_return − benchmark_period_return` on the *same* time window. Never mix XIRR (lifespan) with `return_1y` (365 days) in the same alpha computation.
   - **Per-holding XIRR** in the Detailed Holdings table (§4.10) remains XIRR — it is calculated per fund over that fund's holding lifespan, and it is NOT compared to the period benchmark in the KPI strip.
4. **Attribution waterfall** — Base benchmark → ordered contribution steps → drag steps → final portfolio return; positive steps green, negative red; auto caption naming top contributor and biggest leakage.
5. **Top contributors** — Ranked list of N names driving X% of alpha; each row: name, return %, alpha contribution (pp); detractors in red.
6. **Monthly returns strip** — 12 cells: month, portfolio return, benchmark delta, beat/miss dot.
7. **Composition Explorer** — Dimension toggle (Asset class / Sector / Fund / Group=AMC); default sorted donut or horizontal bar + legend table (weight %, current value, P&L); treemap as secondary view; metric basis toggle (weight % / invested / current value); click segment → drill-down + filters Detailed Holdings.
8. **Concentration callouts** — Flag when any single asset class/sector/fund/group exceeds configured thresholds (defaults: top holding >10%, top sector >35%).
9. **Diversification overlap** — Surface stocks/holdings duplicated across multiple funds.
10. **Detailed Holdings view** — Sortable/filterable/searchable table of all holdings; columns: fund, AMC, asset class, category, units, NAV, last updated, invested, current value, P&L (abs + %), weight %, XIRR, benchmark delta, status; row click opens holding detail drawer; AMFI-unmatched rows marked; filtered export.
11. **Carry-over (parity, re-skinned):** Health Score gauge + verdict; snapshot cards (Positive Returns, Outperforming Benchmark, Need Review, Total Gain); Risk-vs-Return bubble (X=return%, Y=weight%, size≈invested, color buckets +15%+/0–15%/–15–0%/<–15%); Benchmark donut (Outperforming/Meeting/Underperforming + coverage note) with clickable segments; Best & Worst Performers list; Performance Heatmap (size=invested, color=P&L), click → holding detail.
12. **Export** — Current view to PDF/CSV preserving active filters and period.
13. **Resync** — Re-pulls NAV/benchmark data and updates a visible last-synced timestamp.

### Non-functional
14. Initial render < 2.5s on cached dataset; charts/tables virtualize or aggregate at ≥100 holdings.
15. All positive/negative values carry explicit sign + non-color cue (icon/sign) in addition to green/red (color-blind safe), meeting WCAG AA contrast.
16. INR formatting with lakh/crore (e.g. `+₹23.00 L`).
17. Full read parity on mobile (collapsed sidebar, stacked single column, table horizontally scrollable).
18. Every chart/table implements loading, empty, partial-data, and error states.

## 5. Acceptance criteria (the QA contract)

**Verdict & KPIs**
- [ ] Given AMFI-matched data, when Performance loads with period=1Y, then the headline reads "You beat the benchmark by {alpha} points" where `alpha = round(portfolio_1y_return − benchmark_1y_return, 1)`, and the number is green. Both values use the same 365-day window — XIRR (lifespan) is NOT used in this comparison.
- [ ] Given period=Since inception, the headline uses `alpha = round(portfolio_xirr − benchmark_inception_cagr, 1)`, where `benchmark_inception_cagr` is the benchmark CAGR from the portfolio's first investment date to today (not a fixed 1-year window).
- [ ] Given `alpha < 0`, then the headline reads "You trailed the benchmark by {abs(alpha)} points", the number is red, and the status pill is not `HEALTHY`.
- [ ] The return KPI card label reads "Return (1Y)" / "Return (3Y)" / "XIRR (Since inception)" to make the measurement window explicit to the user.
- [ ] Given Sharpe ≥ 1.0, then the Sharpe card shows the `above 1.0 ✓` marker; given < 1.0, the marker is absent/failed.
- [ ] The XIRR card shows the benchmark reference value (e.g. `NIFTY +16.6%`) sourced from the same period as the selected range.

**Attribution waterfall**
- [ ] The sum of the base bar plus all contribution and drag steps equals the final "You" bar within ±0.1 pp.
- [ ] Positive steps render green, negative steps render red; the final bar uses the portfolio accent.
- [ ] The caption names the single largest positive contributor and the single largest (most negative) drag, matching the underlying step values.

**Top contributors**
- [ ] Rows are sorted by absolute alpha contribution descending; detractors (negative pp) render red.
- [ ] The "N names · X% of alpha" header equals `round(sum(listed contributions) / total_alpha × 100)`.

**Monthly returns**
- [ ] Exactly the months in the selected period render; each cell's beat/miss dot is green iff `month_return ≥ benchmark_return`, else red.

**Composition Explorer**
- [ ] Switching the dimension toggle (Asset class/Sector/Fund/Group) re-renders the chart and legend for that dimension without page reload.
- [ ] For any dimension, the sum of segment weights equals 100% ± 0.1% (rounding), and segment values reconcile to the portfolio total.
- [ ] Switching metric basis (weight/invested/current) updates both chart proportions and legend numbers consistently.
- [ ] Clicking a segment filters the Detailed Holdings table to exactly the holdings in that segment (count shown).
- [ ] Given a concentration threshold breach, a warning chip appears naming the breaching item and its actual %.

**Detailed Holdings**
- [ ] All holdings appear (count equals portfolio holding count, e.g. 111); no holding is dropped, including AMFI-unmatched ones.
- [ ] Sorting any numeric column orders rows correctly asc/desc; default sort is by current value descending.
- [ ] Applying a filter updates the visible row count and the export reflects the filtered set.
- [ ] AMFI-unmatched rows display a marker and show "—"/"unavailable" (not 0 or blank) for benchmark/attribution fields.
- [ ] Clicking a row opens the holding detail drawer for that exact fund.

**Carry-over parity**
- [ ] Health gauge value 0–100 maps to the correct band label and matches the status pill state.
- [ ] Benchmark donut counts (Outperforming/Meeting/Underperforming) sum to the matched-fund count in the coverage note; clicking a segment filters to those funds.
- [ ] Bubble chart color of each point matches its return bucket; bubble area is monotonic with invested amount.

**Export / Resync / errors**
- [ ] Export produces a file reflecting the current view, period, and active filters.
- [ ] Resync updates the last-synced timestamp on success; on failure the prior data remains and an error state is shown (no blank view).
- [ ] Error case: given the returns/benchmark API returns an error, then affected widgets show their error state and the rest of the dashboard still renders.
- [ ] Edge case (empty portfolio): every view shows its empty state with no NaN/Infinity/`undefined` rendered.
- [ ] Edge case (single holding at 100%): composition charts and concentration callouts render without divide-by-zero.
- [ ] Edge case (unauthorized): a user without access to a portfolio cannot load its data via the view or export.

## 6. UX / design notes
- **Design target:** Screenshot 4 ("Nivesh"). Dark near-black canvas, mint/emerald accent (positive + primary), muted red (negative); editorial serif headline (sentence case); uppercase letter-spaced monospace labels; monospace sign-prefixed numbers. Owned with DESIGNER role; reference design tokens before build.
- **Hierarchy per view:** verdict headline → KPI strip → primary analytical component → supporting panels.
- **States to handle (all widgets):** loading (skeleton), empty, partial-data (some AMFI-unmatched), error, stale-data indicator.
- **Drill-down pattern (consistent):** segment / bar / tile / row → filtered detail or holding drawer.
- **Responsive:** desktop = full sidebar + multi-column; mobile = collapsed sidebar + stacked column, holdings table horizontally scrollable.
- **Tooltips:** hover (desktop) / tap (mobile).

## 7. Technical notes
- **APIs (link `API_DOCUMENTATION.md`):** AMFI NAV + scheme metadata feed; fund↔category-benchmark mapping; returns engine computing XIRR, alpha (after fees), Sharpe, hit rate, and attribution factors at portfolio and holding level. Resync triggers a refresh job; expose `last_synced_at` + `source`.
- **Schema (link `DATABASE_SCHEMA.md`):** holdings need asset_class, sector, AMC/group, category, units, cost basis, NAV history; `amfi_matched` flag; computed weight/XIRR/benchmark-delta. New: composition aggregates and concentration thresholds (configurable).
- **Attribution service** is net-new and non-trivial → **needs an ADR** covering the factor model and how steps reconcile to total alpha.
- **New dependencies:** charting lib supporting waterfall + treemap + donut + bubble (justify one lib to cover all to avoid bundle bloat); virtualization for the holdings table.
- **Computation placement:** XIRR/attribution should be server-computed and cached per period to meet §14; client only renders.

## 8. Dependencies & sequencing
1. AMFI ingestion + fund↔benchmark mapping (blocks all benchmark/attribution metrics).
2. Returns/attribution service + ADR (blocks Performance flagship).
3. Composition aggregates in schema (blocks Composition Explorer + Concentration/Diversification).
4. Design tokens finalized (blocks build of all v5 views).
5. Then: Performance flagship → Composition/Holdings → carry-over re-skins → export. Hand to PROJECT role for ordering.

## 9. Risks
- **AMFI match gaps** (currently ~38 of 60 funds matched) → attribution/benchmark coverage looks thin; mitigate with explicit "unavailable" handling and a coverage note (REQ §4.11), never silent drops.
- **Attribution credibility** — if waterfall steps don't reconcile or feel arbitrary, trust drops; mitigate via ADR, ±0.1pp reconciliation check (AC), and transparent factor labels.
- **Performance at 100+ holdings** — heavy charts/table; mitigate with server aggregation + virtualization (§14).
- **Color-only semantics** exclude color-blind users; mitigate with sign/icon cues (§15).
- **Scope creep** — single PRD covers many views; mitigate with non-goals and option to split carry-over views into sub-PRDs.

## 10. Success metric & rollout
- **Measure:**
  - Primary: ≥30% reduction in "don't understand my portfolio" support contacts within 60 days of full rollout.
  - Engagement: ≥40% of active users open Performance or Composition view weekly; ≥15% use a drill-down.
  - Quality: attribution reconciliation error = 0 in production telemetry.
- **Rollout:** Feature-flagged; internal dogfood → 10% phased → 100%. **Rollback trigger:** attribution reconciliation failures > 0.1% of loads, p75 render > 4s, or crash rate regression vs v4.

## 11. Open questions
- **"Group" definition** — defaulted to AMC / fund house. Confirm whether it should mean family members / linked accounts or a user-defined custom grouping. *Owner: Product. Resolve before APPROVED.*
- **Canonical benchmark** — KPI references NIFTY 50, attribution references NIFTY 500. Confirm benchmark(s) of record per asset class. *Owner: Product/Quant.*
- **Attribution factor model** — confirm factor set (Brinson allocation/selection vs custom) and whether "Mid-cap" is a size factor or one-off. *Owner: Quant. Drives the ADR.*
- **Health-score formula & status-pill thresholds.** *Owner: Product/Quant.*
- **"Need Review" criteria** — conditions that flag a fund for review. *Owner: Product.*
