# F&O threshold research: plan, verified data facts, and what is built

Date: 2026-10-23 · Inputs: `docs/NIVESH_FO_SMART_MONEY_INTELLIGENCE_PRD.md`, `docs/FO_SMART_MONEY_PRD_GAP_ANALYSIS.md`, the user's decisions of 2026-10-23.

## 1. Decisions on record

1. Candidate screen and the research job are built **in parallel**. The research report is the **release gate** for any live-ranked claim. A status is shown beside every setting: `research_setting_not_validated`, `research_result`, `validated`, `insufficient_evidence`, with experiment id, data window and last-updated time.
2. **Three separate scores** (Signal Strength, Tradeability, Strategy Quality). Stock Signal Strength weights (research settings): futures OI 30, futures price 20, volume 15, options-chain 15, cash and delivery 10, technical 10. **A missing input is never redistributed**: the score keeps its 100-point denominator, shows coverage and the missing input with its weight, is marked incomplete, and needs a configurable minimum coverage before a candidate is ranked or published. Fundamentals are a separate context panel, not an input.
3. **NIFTY and BANKNIFTY**: extend the existing view into two independent workspaces behind a selector, with an index-agnostic API. Constituent-based history is limited until point-in-time membership exists.
4. **Research**: do not run the whole grid and pick the winner. Discover on one period, freeze a small set, test on an untouched period, report net of costs with uncertainty and sample size. Intraday thresholds are validated separately from daily ones.
5. Cost model (STT, exchange charges, GST, stamp duty, brokerage, spread, slippage) and a documented probability-of-profit method are **strategy-release blockers**. Position-aware alerts are a separate milestone and are not called complete until positions are mapped.

## 2. Data facts verified on 2026-10-23 (read-only)

Warehouse (`nidp`, staging):
- `fno_bhavcopy`: 260 sessions, 1 Oct 2025 to 22 Oct 2026; STF 162,109 rows, IDF 4,047, STO 8.76 M, IDO 1.33 M.
- `prices_eod`: 632 sessions from 1 Apr 2024, with `deliv_qty` and `deliv_pct` filled on every EQ row.
- `stock_features_daily`: 201 sessions from 29 Dec 2025. `index_constituents`: 4 snapshots (12 Oct onward). `security_reference_daily`: 10 days. No `intraday_bars` table.

Kite historical API, called with the platform token (`oi=True`):
- **Daily continuous futures with OI**: INFY, NIFTY and BANKNIFTY each returned **1,240 sessions from 25 Oct 2021** when 5 years were requested, every row with OI above zero. SWIGGY returned 201 rows from 31 Dec 2025 (it has only existed since then). A 2-year request returned 496 rows for INFY.
- **Intraday with OI**: 15-minute (3 days: 59 rows) and 60-minute (10 days: 50 rows) candles carry `oi` for the **active** contract. INFY's October contract listed around 29 Jul, so contract-only history is about three months.
- Not verified: options history with OI, intraday continuous series, per-request limits beyond what the code assumes (5 minute 100 days, 15 minute 200, 60 minute 400), and how the continuous series treats OI at rollover (a discontinuity is expected where the series switches contract; the research must handle it explicitly).
- Kite's instrument list holds active contracts only, so intraday OI for **expired** contracts cannot be fetched later. That is why the live series is saved from now on (section 3).

## 3. What is persisted now (and what is not)

Before this work the live feed kept only the latest snapshot (`replace_one {_id: "latest"}`), so no intraday OI series existed.
- **Per-day close** (`kite_live_close`, PR #309, merged 23 Oct): written once after each close, kept a year.
- **Intraday series** (`kite_live_intraday`, this branch): every 5 minutes of an open session, one document with the near-month futures' and NIFTY 50 / NIFTY BANK price, OI and volume, with the contract's underlying and expiry. Written when seen, so it is point-in-time by construction. 180 days. About 20 KB a document, 75 documents a day.
- Both need the backend restarted after deploy to start writing (the staging backend is bind-mounted).

## 4. Two-stage research as agreed

| Stage | Data | Purpose | Status |
|---|---|---|---|
| A discovery | `fno_bhavcopy` (260 sessions) and Kite daily continuous (recent year) | narrow the PRD grid to a small frozen set | **not built** |
| B historical validation | Kite daily continuous before Oct 2025 (up to 5 years for the liquid names) | test the frozen set on a period not used to choose it | **not built** |
| C live shadow | `kite_live_intraday` and the saved closes | record the signal when it occurs, evaluate later, never reconstruct | storage built, evaluator not |
| D controlled release | validated thresholds plus cost model and POP | enable ranked candidates, with monitoring and rollback | not started |

Design notes for the runner (not yet written):
- Contract choice: the near-month contract per day, with an explicit rollover rule; OI change compared on the same contract, never across a roll.
- Point-in-time universe: derive F&O membership per day from the bhavcopy itself (a stock with futures rows that day was in F&O that day). Index constituents stay a stated limitation.
- Outcomes at 1, 3, 5, 10 and 20 sessions after the next executable price, direction-adjusted, net of a cost model that must include brokerage, STT, exchange charges, GST, stamp duty and slippage; the cost model is itself a deliverable.
- Record every configuration tested and the count (the multiple-testing denominator). Same inputs and config must give the same report hash.
- Verdict logic: `validated` only with positive out-of-sample net expectancy and enough samples; too few samples is `insufficient_evidence`; never `validated` from in-sample alone. One year may well end as "not validated yet", which is the honest result.

## 5. Built on branch `feat/fo-candidates-v2` (draft PR to dev)

- `services/fno_candidates` v2: three-score model, coverage and minimum-coverage gate, fundamentals as a context panel, research-status block on every response; `GET /api/fno/scan/candidates`.
- `kite_live_feed`: intraday OI snapshot persistence.
- Tests: backend `175 passed` (candidates v2, F&O routes, Kite feed). No frontend and no research runner yet.

## 6. Next, in priority order

1. Threshold research runner, Stage A, with the cost model; first real report.
2. Candidate screen shell in the F&O Lab (cards with three score bars, coverage, research-status chip, incomplete markers).
3. NIFTY and BANKNIFTY workspaces (selector over the current view, index-agnostic API).
4. Cost model and POP method; then strategy recommendations.
5. Intraday OI: Stage C evaluator and, separately, intraday threshold research.
6. Position mapping and position-aware alerts.

## 7. Requirement added 2026-10-23: intraday option OI change per underlying

The user's reference (a Sensibull-style "OI Change" screen): for each F&O stock and for NIFTY and BANKNIFTY, call and put OI by strike with the **change over a chosen window** (last 5, 10, 15, 30 minutes, 1, 2, 3 hours, full day), the spot marked, a choice of expiries, a strike range or "N strikes above and below ATM", and a replay slider from 9:15 to the close.

What exists: end-of-day per-strike OI and the day's change from the bhavcopy (the Lab's option-chain view). No intraday option OI is stored, and the live feed subscribes no option contracts (only cash, indices and, since PR #307, near-month futures).

Verified on 2026-10-23 (read-only, Kite REST `quote`, platform token):
- Kite lists **42,691** option contracts across 219 underlyings. RELIANCE 215 contracts over 3 expiries; SWIGGY 256 over 3; BANKNIFTY 977 over 6; NIFTY 1,824 over 18 expiries (weekly and monthly).
- A +-10 strike window around the future's price, 2 expiries, calls and puts, was **84 contracts for RELIANCE: 84 quotes returned in 0.03 s, 83 with OI above zero**. Each quote carries `oi`, `oi_day_high`, `oi_day_low`, `volume`, `last_price`, depth and a timestamp.
- For all 214 F&O stocks that window is about **8,990 contracts**, plus the NIFTY and BANKNIFTY chains. At 500 instruments per call that is about 20 calls a cycle, so a 5-minute snapshot of the whole list is feasible on the existing REST path.

Design implied (not built):
1. A snapshot job in the feed that, each 5 minutes of an open session, reads the windowed option chains (ATM +-N strikes, two nearest expiries; wider and weekly expiries for NIFTY and BANKNIFTY) and saves strike, type, OI, price and volume under the bucket time. Re-centre the window on the current ATM each cycle.
2. "Change over the last N minutes" and the replay slider are differences between two saved snapshots, so the view works from the first day the job runs; nothing before that exists to replay.
3. Storage: about 10,000 rows a snapshot, roughly 400 KB, 75 snapshots a day, about 30 MB a day. Keep a short retention (for example 30 days) or store only the changed strikes; decide before building.
4. A read route by underlying, expiry, window and strike range (index-agnostic, the same for stocks and indices), and the view in the F&O Lab beside the existing option-chain OI.
5. Backfill for the current day only if needed: Kite's historical candles with `oi=True` for an option contract (15-minute) should work for active contracts, one request per contract (about 9,000 requests, roughly 50 minutes at 3 a second). Not verified for options.

This belongs to the "intraday OI" milestone, validated separately from the daily threshold research (PRD sections 4 and 10; the user's decision B). It is a descriptive view, so it can ship before thresholds are validated, but it must show its data timestamp and say that OI change is not proof of intent.
