# Integrated Stock Intelligence Engine — Design + Test Cases (DRAFT)

Status: IN PROGRESS. Design only; no implementation yet. Source: product brief pasted 2026-10-20.
Scope chosen by user: full vertical slice (scoring service, API, shortlist UI, backtest), reversal
strategy first, momentum continuation as the benchmark strategy.

Existing-code facts below come from a read-only subagent survey of
/home/deploy/nivesh-trading-desk (branch feat/trading-desk-backend). UNVERIFIED by me: re-check each
cited file before building on it. Not opened by the survey: sector_master (027/080/086) and
v3_stock_scores_daily internals.

## 1. Building blocks that exist

| Need | Existing source |
|---|---|
| Per-stock technicals | `nidp.stock_features_daily` (sma20/50/100/200, rsi14, return_5/20/60d, atr14, dist_52w_high_pct, dist_52w_low_pct, vol_z20, swing_low/high_20) |
| Fundamentals | same table via fundamental_engine (pe_ttm, roe_pct, debt_to_equity, growth yoy, promoter_pledged_pct); `nse_financials_cashflow` for CFO |
| Stock-in-sector scoring | `nidp.v3_stock_scores_daily` (sector_sector profiles; governance score) |
| Sector daily stats | `analytics.sector_snapshot` (avg returns, advancing/declining, median RSI, ranks) |
| Index prices | `nidp.index_eod` |
| Events | `nidp.event_calendar` (intimated_at), `nidp.corporate_announcements` (filed_at, LLM impact_score/sentiment) |
| Scanner/rules | `positional_engine/setup_rules.py` (scan-rules.v2), `/api/positional/scan-universe` |

## 2. Gaps (must be built or reported as unknown)

1. No near-52w-low reversal rule; no base / higher-low detection; no stage-1 / stage-2 split.
2. No sector rotation: no sector-vs-Nifty 500 RS series, no % above 50/200 DMA breadth, no acceleration.
3. No 100-point blended score; no momentum / catalyst / valuation-risk buckets.
4. EMA20/EMA50, 52w price levels, named ROC and relative volume are not in the snapshot.
5. Cash-flow quality, pledge trend and valuation history are not wired into features.
6. Catalysts are not aggregated per symbol/date. Point-in-time timestamps exist (intimated_at, filed_at)
   but older event_calendar rows lack first_seen_at.

## 3. Design

### 3.1 Scoring (config-driven; weights are hypotheses, not tuned)
Components, each 0-100 or `null` (unknown): sector 20, technical 25, momentum 15, fundamental 20,
catalyst 10, valuation_risk 10. Unknown components are excluded from the total, the total is
re-normalised over known weights, and the response carries `coverage_pct` and `unknown_components`.
A stock with coverage below a threshold cannot be ranked above "watchlist".

Hard gates (override the score): pledge above limit, severe distress (interest cover < 1.5 or
negative CFO for N periods), liquidity below floor, invalidated setup (close below invalidation).
Gate result is `excluded` or `warning`, shown prominently with the reason.

Stage 1 `opportunity_quality` = sector + fundamental + catalyst + valuation_risk.
Stage 2 `trade_readiness` = technical + momentum + liquidity + volatility + event timing + reward/risk.
Strategy profiles: early_reversal, confirmed_breakout, momentum_continuation, fundamental_recovery.
Each profile sets weights and required conditions. Output status:
`excluded | avoid | watchlist | setup_forming | trigger_ready | confirmed`.

Sector-appropriate fundamentals: reuse sector_scoring profiles (bank, nbfc, it, pharma, fmcg,
capgoods, cyclical, default); no universal P/E or D/E threshold.

### 3.2 New data (migrations, forward-only, IF NOT EXISTS)
- `nidp.sector_rotation_daily(sector, as_of_date, rs_vs_nifty500_20d, rs_slope, breadth_above_50dma, breadth_above_200dma, quadrant)`
- `nidp.stock_opportunity_daily(symbol, as_of_date, profile, stage1, stage2, total, components jsonb, gates jsonb, status, explanation jsonb, config_version)`
- Backtest tables: `nidp.opportunity_backtest_runs`, `nidp.opportunity_backtest_outcomes`.
All built from data published on or before as_of_date (event rows filtered by intimated_at/filed_at).

### 3.3 API (DaaS, `/v1/opportunities/...`, proxied by app `/api/opportunities/...`)
- `GET /shortlist?profile=early_reversal&as_of=&limit=` -> ranked rows with score, stage1, stage2,
  status, `why_this_stock`, `why_now`, `confirms`, `uncertain`, `invalidation`, `entry_trigger`,
  `reward_risk`, `components` (each with value, weight, known flag), `gates`, `data_status`.
- `GET /stock/{symbol}?profile=` -> the same record plus contradictory evidence.
- `GET /backtest/{run_id}` -> horizon stats (below).
Errors follow existing API conventions in docs/API_DOCUMENTATION.md.

### 3.4 UI
New "Opportunities" view in the trading desk next to ScannerTab: strategy-profile selector, ranked
shortlist, row drill-down showing the five answers (why this stock, why now, what confirms, what is
uncertain, what invalidates), unknown components shown as "Unknown", never as zero or neutral.

### 3.5 Backtest
Point-in-time replay of early_reversal and momentum_continuation vs baselines (technical-only,
fundamental-only, sector-only). Metrics: mean/median return and win rate at 5/10/20 sessions,
+5%/+10% target hit rate, max adverse excursion, failed-breakout rate, results after costs and
slippage (stated assumption, configurable), splits by market regime / sector regime / quality group.
Fundamentals restricted to filings published before the decision date.

## 4. Test cases (authored before implementation)

Unit (pure functions, pytest, no DB/network):
1. Weights sum to 100; total = weighted sum when all six components known.
2. Unknown component is excluded and re-normalised; `unknown_components` lists it; it is never 0 or 50.
3. Coverage below threshold caps status at watchlist.
4. Each hard gate (pledge, distress, liquidity, invalidated setup) forces excluded/warning regardless of a 95 score.
5. Boundaries for early-reversal: dist_52w_low 15.0 in / 15.01 out (threshold TBD by user), higher-low count, RSI recovery.
6. Strong chart + weak fundamentals -> flagged speculative, not high-quality.
7. Strong fundamentals + broken chart -> watchlist, stage2 low.
8. Bank/NBFC use their own profile; the same raw D/E does not penalise a bank.
9. Point-in-time: an announcement filed after as_of is ignored; a filing published after as_of is not used.
10. Profile switch changes weights/requirements deterministically; same inputs -> same output.
11. evaluate() is a pure function of rows + as_of.
12. Explanation always contains the five answers; `uncertain` is non-empty when any component is unknown.

API (staging, real responses):
13. /shortlist returns 200, rows sorted by total desc, schema complete, profile filter respected.
14. Bad profile -> 422; future as_of -> 4xx with clear error; empty universe -> 200 with empty list and data_status.
15. Auth/rate conventions as the other /api routes.

Data tests (real staging DB):
16. Row counts per as_of; sector_rotation_daily covers every sector in sector_master; no NULL-as-neutral.
17. Spot-check 5 symbols: component inputs match stock_features_daily / v3_stock_scores_daily values.

UI (Playwright, repo mocks + one real-staging screenshot):
18. Profile selector refetches; ranked rows; drill-down shows the five answers; unknown rendered as "Unknown".
19. Excluded stock shows its gate reason prominently; empty and error states.
20. Typecheck (tsc --noEmit) clean.

Backtest:
21. No look-ahead: shuffling post-as_of data does not change a decision.
22. Costs and slippage reduce returns vs gross; baselines run on identical universe and dates.
23. Report includes sample size per bucket and says so when it is too small to conclude.

## 5. Open questions (NEEDS-INPUT)
1. Which checkout to build in: nivesh.ai (current branch feat/provider-foundations, lacks setup_rules.py) or the nivesh-trading-desk worktree (feat/trading-desk-backend, has the scanner)?
2. "Near 52-week low" threshold (e.g. within 15% / 20%) and min price/liquidity floor.
3. Backtest window and universe (Nifty 500? years of history available in staging warehouse?).
4. Cost/slippage assumption (default proposal: 0.25% round trip + 0.10% slippage).

## 6. Integration with the Smart Trading Desk (added 2026-10-20 on user instruction)

Requirement source: `docs/prd/SMART_TRADING_DESK.prd.md` (PRD). The engine is a feature of the desk, not a separate app.
Build location: the desk branch feat/trading-desk-backend (worktree /home/deploy/nivesh-trading-desk).
That worktree currently has uncommitted changes from another session, so work goes in a new worktree
branched from it (see open question 1), not in the dirty tree.

| PRD item | How the engine plugs in |
|---|---|
| Module 2 §5.2 categories | "Reversal candidates" becomes an engine-backed category in ScannerTab; "Momentum" gets the engine's momentum_continuation profile as a second ranking. Existing scan-rules.v2 categories stay unchanged (back-compat). |
| §5.3 table fields | Engine fills Pattern, Confirmation, Catalyst, Risk. "AI probability" stays "—": the engine score is a rule-based score, labelled as such, never shown as a probability (PRD §5.3, §5.8). |
| §5.6 confirmation rules | Thresholds live in a versioned config (like RULES_VERSION in setup_rules.py), not in UI code. |
| §5.7 opportunity detail (10 items) | Engine record maps to items 3,4,5,6,7,9,10; item 8 (historical validation) comes from the backtest; items 1-2 show "—" with reason where no calibrated model exists. |
| Module 3 Market Intelligence | Catalyst component reads the same classified announcements/event_calendar the module uses. |
| Module 4 §7.6-7.7 | Backtest harness reuses the no-look-ahead rule; results feed "historical validation statistics". |
| Module 5 §8.6 | Portfolio-aware overlay (already-held, sector concentration) is a later phase, not in this slice. |
| §5.8 | Result discloses eligible universe and exclusion rules; missing data is never neutral. |

API: new routes sit under the existing /api/positional prefix (positional.py) next to /scan-universe,
e.g. GET /api/positional/opportunities, rather than a new /api/opportunities prefix. The DaaS-side
snapshot is extended (EMA20/50, 52w levels, dist_52w_low_pct, sector rotation) instead of a parallel feed.
UI: a profile selector and "Why this stock / why now / confirms / uncertain / invalidates" panel inside
the existing ScannerTab drill-down; no new top-level tab.
Section 3.3/3.4 above are superseded by this section where they differ.
