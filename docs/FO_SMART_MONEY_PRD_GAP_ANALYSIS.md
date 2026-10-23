# F&O Smart Money Intelligence PRD: what the repo already has, and what the F&O Lab screen needs

Date: 2026-10-23 · Input: `docs/NIVESH_FO_SMART_MONEY_INTELLIGENCE_PRD.md` (v1.0) · Method: code read this session plus read-only queries on the staging warehouse.
Status of this document: analysis only. Nothing in it is built, and "have" below means the code or data exists, not that it has been validated.

## 1. Verdict

Your instinct is right for the **display** layers: most of the data and several of the computations the PRD asks for are already behind the F&O Lab. Three things are not there, and they are the ones the PRD itself puts first:

1. **No validated thresholds, and no point-in-time history to validate them properly** (section 3). The warehouse has one year of F&O bhavcopy; it does not have historical index constituents or F&O eligibility.
2. **No intraday open interest anywhere.** The PRD's "OI persistence" and any hourly build-up (the Chartink screen you showed) cannot be computed from end-of-day data. Since 23 Oct the live Kite feed carries near-month futures OI, and the first saved close is written tomorrow, so a live-versus-previous-close build-up becomes possible from tomorrow, not before.
3. **No portfolio-aware alerting** and no probability-of-profit estimate in the strategy engine.

The F&O Lab screen can be rebuilt around the PRD's screens without a new application. The PRD's section 22 asks for the research foundation to come before a candidate dashboard; section 6 below proposes how to honour that without blocking the screen work.

## 2. Data the platform actually has (verified 2026-10-23, staging warehouse, read-only)

| Need (PRD section) | What exists | Depth / limit |
|---|---|---|
| Futures and options price, OI, change in OI, volume (4, 9) | `nidp.fno_bhavcopy`: stock futures STF 162,109 rows, index futures IDF 4,047, stock options STO 8.76 M, index options IDO 1.33 M | 260 sessions, 1 Oct 2025 to 22 Oct 2026. End of day only |
| Cash price, volume (8) | `nidp.prices_eod` | 632 sessions from 1 Apr 2024 |
| Delivery quantity and % (8) | `prices_eod.deliv_qty`, `deliv_pct`, filled on 100% of EQ rows including the last 60 days | End of day, published after the session |
| Technical features: EMA/SMA 20/50/200, RSI, MACD, ATR, returns, volume z-score, delivery trend (8) | `nidp.stock_features_daily`, served by DaaS `/features/bulk` | 201 sessions from 29 Dec 2025 |
| Fundamentals and ownership (8) | same table: ROE, ROCE, debt, growth, P/E, promoter, pledge, FII/DII | quarterly, with source and as-of columns |
| Bulk and block deals (8) | `v_trendlyne_deals_net` (10,243 rows, transfers netted) | |
| Events (8) | `event_calendar` 27,313 rows, `corporate_announcements` 192,322 rows | |
| Options-chain summary, PCR, max pain, ATM IV, expected move, per-strike Greeks (9) | `GET /api/fno/{symbol}/chain`: Black-76 from settle prices, model and timestamp stated | one expiry at a time; IV is computed, not stored |
| Index breadth and constituent contribution (10) | `GET /api/markets/sector-heatmap?index=<name>` (`routes/markets_desk.py`; the DaaS side returns `index_impact_pct` per stock and breadth): contribution and breadth for any index that has a constituent list, e.g. `Nifty Bank` | Nifty 50 / Nifty Bank constituent lists exist, as 4 snapshots (see below) |
| Live futures price and OI (9, 10) | Kite websocket, 219 near-month contracts, `GET /api/live/snapshot?universe=futures` (PR #307, deployed) | live only; the per-day close is saved from the next close (PR #309) |
| Intraday bars / intraday OI (4, 10) | **none**: `nidp.intraday_bars` does not exist on staging | |
| Point-in-time index constituents (5, 6) | `nidp.index_constituents`: 4 snapshots, 12 Oct 2026 onward | **cannot rebuild a historical NIFTY or BANKNIFTY membership** |
| F&O eligibility history (5) | `nidp.security_reference_daily`: 10 days | but eligibility can be derived per day from the bhavcopy itself: a stock with futures rows that day was in F&O that day |
| Term structure and skew (9, 10) | not present (one expiry per request) | |

## 3. PRD section by section against the repo

Legend: HAVE = exists and is used; PART = exists but short of the PRD; MISSING; CONFLICT = the PRD says something the current code or my in-flight draft does the opposite of.

| PRD | Requirement | State | Evidence and the gap |
|---|---|---|---|
| 4 | Four-regime classification | HAVE | `/api/fno/scan/buildup`, labels from the route, counts and scatter in the Lab. Gap: the PRD wants the reference interval and timestamps shown, and `neutral / insufficient data` as an explicit class. OI change is summed over **every expiry**, the PRD wants consistent contracts |
| 4 | OI percentile, relative volume ratio, basis % | PART | vol_z20 exists (a z-score, not the PRD's ratio, though `avg_volume_20` makes the ratio computable); basis exists in the futures route; OI percentile is computable from 260 sessions of bhavcopy but is not computed anywhere |
| 5 | Eligibility with an auditable reason per exclusion | PART | the scan returns `fno_eligible`, flags and a master date; no per-exclusion reason list. (My draft engine does count exclusions by reason) |
| 5 | Historical universe, no survivorship | MISSING | see section 2: no historical constituents; contract-level history can be derived from the bhavcopy |
| 6 | Threshold research framework | MISSING | no experiment store, grid runner or train/validation/test split for F&O. Reusable parts: `services/smart_money_study` (an evaluator that already returned INCONCLUSIVE and is wired to a promotion-decision table), `services/strategy_engine/backtest` (slippage and brokerage constants), the `tpd` research jobs |
| 6 | Validation realism | PART | the data (260 sessions, about 219 underlyings) supports exploratory research, not strong out-of-sample claims: a 5 to 20 session horizon over one year gives few independent samples per category. The report should say so |
| 7 | Three separate scores, not one | CONFLICT | my in-flight draft produces one `rank_score` |
| 7 | Do not silently redistribute weights for missing features | CONFLICT | my draft renormalises over known components, which the PRD forbids; it must show unknown components and a score marked incomplete instead |
| 7 | Stock signal weights (OI 30, price 20, volume 15, options 15, cash/delivery 10, technical 10) | CONFLICT | the draft used the first PRD's five buckets (30/25/20/15/10) with fundamentals inside the score. This PRD keeps fundamentals out of the signal score |
| 8 | Delivery vs its own average, bulk/block with source | PART | `deliv_pct_avg_20` and `deliv_trend10` exist; the latest day's delivery % against that average is not in the features but is in `prices_eod`, so it is computable. Availability timestamps are not recorded |
| 8 | Technical set (EMA 20/50/200, RSI, MACD, ROC, VWAP, ATR, relative strength, support/resistance, gaps) | PART | SMAs, RSI, MACD, ATR, returns exist; the desk chart has EMA/VWAP/RSI/MACD tiles. Missing: relative strength versus NIFTY 500 and sector, anchored VWAP, volume profile, previous-day/week levels, gap analysis |
| 8 | Fundamentals as a separate lens | HAVE | features carry the figures; presenting them as a separate lens is a UI choice |
| 9 | Options OI by strike, PCR, walls, max pain, ATM straddle, IV, Greeks | HAVE | `routes/fno.py` chain and summary; the Lab's option-chain view |
| 9 | IV change, skew, term structure, bid/ask | MISSING | bhavcopy has no bid/ask or IV history; IV is derived per request |
| 10 | NIFTY and BANKNIFTY futures OI, PCR, walls, max pain, VIX, breadth, constituent contribution | HAVE (separate views) | the Lab's index cards, the chain view, the VIX on the tape, `GET /api/markets/sector-heatmap?index=`. Not yet one workspace per index |
| 10 | Independent signal and ranking per index | MISSING | the scan returns one row per index with the same label logic |
| 11 | Strategy comparison: legs, breakevens, max loss/profit, capital at risk, reward:risk, scenarios, costs, Greeks | HAVE | `POST /api/desk/strategy/plan` and `/ideas`, payoff engine, scenario fan, evidence ledger, `no_trade` / `wait` statuses, ranking by fit to the regime and explicitly not by performance |
| 11 | Probability of profit with method | MISSING | no POP in the strategy engine (searched) |
| 11, 17 | Costs: brokerage, STT, exchange fees, GST, stamp duty, slippage | PART | the engine's cost model is slippage % plus flat brokerage; its own `EXCLUDED` list names taxes, STT and exchange charges |
| 12 | Position-aware alerts | PART | alerts exist for price, filings, volume, scanner, sector, risk (`services/desk_alerts.py`), evaluated once in the evening on end-of-day data; broker positions are read-only and available. No F&O build-up alert type, no position-to-signal mapping, no live trigger |
| 13 | Screens 1 to 3 (dashboard, candidate detail, index workspaces) | PART | see section 5 |
| 13 | Screen 4 research workbench | MISSING | |
| 13 | Screen 5 risk center | PART | positions screen and paper desk exist; no signal-conflict or hedge-cost view |
| 14 | Entities with lineage (event time, ingestion time, source, version) | PART | the warehouse tables carry source and ingest time; there is no `fo_signal`, `fo_signal_rank`, threshold-config or experiment store. Nothing is persisted per signal, so nothing can be audited or back-checked later |
| 15 | `/api/v1/fo/*` surface | MISSING | existing routes are `/api/fno/*` and `/api/desk/strategy/*`; mapping them is a naming choice |
| 17 | Paper trading with versioned signals and immutable snapshots | PART | `desk-paper-v3` paper trades exist (costs, MFE/MAE, strategy trades); they do not store the signal version or an immutable market snapshot |
| 18 | Kill switch for signal publication; human-reviewed promotion | MISSING | a promotion-decision table exists for the smart-money study; no switch for F&O |

## 4. Conflicts to settle before any more code

1. **Scoring (PRD 7).** Replace my single rank score with three separate, labelled scores (signal strength, tradeability, strategy quality). Show unknown inputs and mark a score incomplete; do not renormalise. Keep fundamentals out of the signal score and show them as their own lens.
2. **Thresholds as facts (PRD 1, 6, 22).** The floors in my draft (turnover 50 crore, price move 0.5%, OI change 3%, volume z 1.0, RSI bands) are hypotheses. The UI must carry a "research setting, not validated" status next to them, and the response must carry the threshold version.
3. **The Chartink hourly idea.** It needs intraday OI. Until a live-versus-previous-close baseline has accumulated, the Lab can only say "end of day".
4. **"Most profitable strategy".** The PRD agrees with the repo: no strategy can be called most profitable without costs-included out-of-sample evidence. The Lab should say "best fit to current conditions" and show the comparison table the PRD asks for, with POP only once a method exists.

## 5. The F&O Lab screen, rebuilt around the PRD (changes to this screen only)

The Lab has four views today: **OI build-up · F&O stocks**, **NIFTY & BANKNIFTY**, **Option chain OI**, **Paper strategies**. Proposed mapping:

| PRD screen | Where it lives | Change |
|---|---|---|
| 1 Intelligence dashboard | the OI build-up view | add a "Top candidates" block above the existing table: four categories, up to five cards each (price, OI, RVOL, three score bars, freshness, research status), filters (date, liquidity, sector). The scatter and the full table stay |
| 2 Candidate detail | a panel opened from a card (reuse the desk chart and the strategy comparison) | price and OI chart, cash/delivery, technical, fundamental and event lenses, the option chain for that stock (route exists), evidence and counter-evidence, strategy comparison from the plan engine |
| 3 NIFTY / BANKNIFTY | the NIFTY & BANKNIFTY view | one workspace per index: futures and options structure, breadth, constituent contribution, implied move, strike concentrations, strategy candidates |
| 4 Research workbench | new view, or a separate admin page | needs the experiment store first (section 6) |
| 5 Position intelligence | a new view fed by the broker positions | needs the alert service |

Already drafted and uncommitted in the dev worktree: a pure ranking engine and `GET /api/fno/scan/candidates`, with 27 unit tests. The tests were green (109 passed, one failure that was a stale route-list assertion, since corrected) before the last edit round, which moved it to a weighted rank score; that round was **not re-run**. It follows the first PRD, so it needs the section 4 changes before it is used, and I will not build further on it until you answer section 7.

## 6. Order of work that keeps faith with PRD section 22

The data to start the research exists now, so the two tracks can run side by side:

- **Track A, research foundation (PRD phase 1).** A job that rebuilds a point-in-time universe from the bhavcopy, classifies the four regimes per day, and evaluates the PRD's threshold grid against 1, 3, 5, 10 and 20 session outcomes with costs, split into train, validation and a held-out test. Store every tested configuration. The first report will probably be INCONCLUSIVE on one year of data, as the smart-money study was; that is an honest result, and it fixes what the UI may claim.
- **Track B, the Lab screen (PRD phases 2 and 3 display).** Candidate cards, candidate detail and index workspaces, with every threshold labelled by its research status and threshold version, and no score presented as a probability.
- **Later:** persisting signals (`fo_signal`), position-aware alerts and the notification feed, the cost model completion, POP.

## 7. Decisions needed from you

1. Run Track A and Track B in parallel as above, or hold the candidate screen until the first research report exists (the PRD's literal reading)?
2. For the score model, confirm the PRD's three separate scores with its stock weights (30/20/15/15/10/10), shown as incomplete when an input is missing.
3. Index workspaces: build them as full per-index pages now, or first as an extension of the current NIFTY & BANKNIFTY view?
