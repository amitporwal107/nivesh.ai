# SPT slice A — test cases: signals → opportunities → validation → signal outcomes

- **Branch:** `feat/spt-signals` (worktree `/home/deploy/nivesh-wt-spt-a`)
- **Date:** 2026-11-05 (written ~02:15 IST, before implementation)
- **Author:** Claude (builder A: FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Design:** `docs/scanner_paper_trading/DESIGN.md` (D1–D10, §3 collections, §4 contracts, §5 state machines, §7 events, §8 tests)
- **Scope:** `services/spt/signals/`, `services/spt/opportunities/`, `services/spt/outcomes/`, `routes/spt_signals.py`,
  `scripts/spt_backfill_signals.py`, a minimal hook in `services/scan_builder/signals.py`.
- **Environment of these tests:** unit tests in the backend image (`nivesh/backend:staging`, `--network none`), in-memory
  Mongo fakes. Nothing here is verified on staging (no staging writes are allowed tonight; the integrator verifies on staging).

## Deviations from DESIGN.md (kept short; each is also in the final report)

1. **Consolidation key window.** DESIGN/PRD: `SYMBOL|direction|horizon|window`. The window part is the IST day the window
   starts (the opportunity's first signal day), e.g. `RELIANCE|long|positional|2026-11-04`. A later signal attaches when it
   falls inside an existing opportunity's window (positional: `SPT_POSITIONAL_WINDOW_SESSIONS`, default 5 sessions from
   `first_seen_at`, weekday calendar; intraday: the same IST day until 15:31 IST, the end of the 15:30 minute). The key alone cannot be computed from one
   signal without knowing when the window started, so lookup is by (symbol, direction, horizon, window covers the signal).
2. **A REJECTED opportunity keeps absorbing signals of its own window** (they are attached, it stays REJECTED). Otherwise
   every later list mark of an illiquid stock would open a new opportunity that is rejected again (churn). EXPIRED does not
   absorb: a signal after an expiry starts a new opportunity.
3. **Conflicting evidence present at validation downgrades QUALIFIED to CONDITIONAL** (reason `conflicting_signals`).
   DESIGN's QUALIFIED rule does not mention conflicts; WF §5.4 says they must be surfaced. This is stricter than DESIGN,
   never looser. A conflict that arrives AFTER an opportunity is QUALIFIED does not change its state (DESIGN §5: QUALIFIED
   is left only for EXPIRED); it is recorded in `conflicts` and sets `conflict_after_qualified: true` for slice B to read.
4. **`timeframe` uses "1h" and "1W"** besides "1D"/"15m"/"5m" where a list's conditions use those bars (Long Build Up's
   1-hour DMI; Uptrend 52-week and High growth use weekly bars). PRD §6.2 allows "5m, 15m, 1D, 1W etc.".
5. **`scanner_score` of a list mark** is the stock's strength score from the day's scores doc only when that doc was saved
   at or after the detection and at most `SCORE_MATCH_S` (120 s) later; otherwise null with `scanner_score_note`. The scan
   round that records a mark saves the scores (with the same timestamp) right after recording; an earlier doc predates the
   mark and a later one (4 Nov's final doc is as of 22:45 IST) is not the score at detection. The hook waits
   `SPT_INGEST_DELAY_S` (20 s) and the catch-up leaves marks younger than 35 s to the hook, so the round's doc is read.
6. **QUALIFIED, REJECTED and EXPIRED are not revalidated.** `POST /opportunities/{id}/validate` answers 409
   `opportunity_not_revalidatable` for them (DESIGN §5 allows VALIDATING only from CREATED, CONDITIONAL, WATCHLIST,
   DATA_INSUFFICIENT).
7. **The first strong signal extends the window to its own** (`window_until` / `expires_at` = max(current, the strong
   signal's day + N sessions)). Without it, a plan that joins a window opened by list marks days earlier could be
   QUALIFIED with hours left. The consolidation key keeps the window's start day.
8. **`stale` has a grace of `STALE_GRACE_S` (120 s)** after `expiry_at`, so a mark recorded in the session's last seconds is
   not called late because of the hook's own 20 s delay.

## Test cases

Type: unit = pure function; svc = service with in-memory fakes; api = FastAPI TestClient with the in-memory fakes;
data = a fixture copied from the real 4 Nov Redis dump (`/home/deploy/nivesh-signal-archive/redis_dump_20261105.jsonl`,
market-wide data only).

| ID | Area | Scenario | Type | Expected | Covers |
|----|------|----------|------|----------|--------|
| SPT-A-01 | normalize | Every widget id whose rows are stocks (`ROW_KIND == "symbol"`) on every dashboard in `market_dashboard.DASHBOARDS` (Atlas, Day trade, Early movers) is in `LIST_MAP` | unit | test fails naming any missing id; every map entry has a known category, timeframe, horizon and direction | P0-1 |
| SPT-A-02 | normalize | Horizon rules | unit | every `POSITIONAL_LISTS` id → positional; 15-minute breakouts, RSI VWAP, 10x first 5 min (both), early movers, strong movers, Nifty 50 gainers, explosive → intraday | P0-1 |
| SPT-A-03 | normalize | Direction rules | unit | `open_interest`/`oi_7` take the recorded entry's `direction` (short when the stock fell); below-50/200-DMA and 10 %-down lists are short/bearish whatever the entry says; others long | P0-1 |
| SPT-A-04 | normalize | A strong signal | unit | scanner_id `strength_70`, family `signal_strength`, horizon positional, direction long, category from its `lists_at` (positional list first) | P0-1 |
| SPT-A-05 | ingest | A list mark becomes the PRD §6.2 event | svc | `_id` = `sig:<day>:<widget>:<SYM>`; signal_id, scanner_id, scanner_name, instrument_id = symbol, exchange NSE, segment Equity, direction, timeframe, detected_at = `first_seen`, detected_price = `entry`, scanner_score, score_version, signal_type/category, supporting_metrics = the raw entry, market_regime null, expiry_at, normalizer_version | P0-2, WF 25.1 |
| SPT-A-06 | ingest | Scanner score at detection | svc | list mark: score from the scores doc when its `as_of` is within 120 s of detection, else null + note (never invented); strong: `score_at` | P0-2 |
| SPT-A-07 | ingest | The same mark delivered twice (hook + catch-up, two workers) | svc | one document, one RECEIVED and one NORMALIZED event; second call reports duplicate | WF 25.2, PRD 23.3 #11 |
| SPT-A-08 | ingest | Quarantine reasons | svc | missing mapping, invalid symbol, missing price, invalid timestamp, outside session → stored with `status: quarantined` and the reason code(s); RECEIVED emitted, NORMALIZED not | P0-2, WF 4.4/4.5 |
| SPT-A-09 | ingest | An expired signal received late | svc | received more than 120 s after its `expiry_at` → quarantined `stale`; never consolidated | PRD 23.3 #12 |
| SPT-A-10 | ingest | Original score and timestamp are never overwritten | svc | re-delivery with a different score / time leaves the stored event byte-identical | PRD §18 rule 7, WF 25.1 |
| SPT-A-11 | ingest | Events | svc | idempotency keys `sig:<id>:received` / `sig:<id>:normalized`; envelope per events.py; replay inserts no event | DESIGN §7 |
| SPT-A-12 | ingest | Real 4 Nov marks (copied from the dump) | data | 2 strong + list marks of 6 widgets normalize; the archive's `scan-plan-v2` marks keep their raw fields in supporting_metrics | P0-2 |
| SPT-A-13 | hook | `scan_builder.signals.record` / `record_strong` with the hook | svc | flag: staging on, `SPT_INGEST_ENABLED=0` off, `=1` on elsewhere; returns what it returned before; ingest runs as a task; an ingest error is logged, never raised; nothing scheduled for an already-stored mark | P0-3 |
| SPT-A-14 | hook | Catch-up of a day | svc | reads the day's list index and strong index from the signal store, ingests the missing ones; a second run inserts nothing | P0-3, WF 20.3 |
| SPT-A-15 | consolidate | Four scanners flag the same stock long, positional | svc | ONE opportunity with four signals (ids, scanner ids, times, scores, families kept); scores not summed; OPPORTUNITY_CREATED once, OPPORTUNITY_UPDATED per attach | PRD 23.3 #1, WF 25.3 |
| SPT-A-16 | consolidate | Windows and horizons | svc | intraday and positional marks of one stock → two opportunities; a positional mark 6 sessions later → a new opportunity; an intraday mark the next day → a new one | P0-4 |
| SPT-A-17 | consolidate | Opposite directions on one stock | svc | both opportunities carry the other side's signals in `conflicts`; SIGNAL_CONFLICT_DETECTED once per signal (idempotent) | WF 25.4 |
| SPT-A-18 | consolidate | Strong signal | svc | attaches the frozen scan-plan-v3 plan in `strong`; a later strong signal in the window is attached but does not replace the first plan | P0-4 |
| SPT-A-19 | consolidate | Re-runs and races | svc | a second consolidation pass changes nothing; an open opportunity with the same key appearing between lookup and insert → the signal is attached to it, no duplicate | WF 25.2 |
| SPT-A-20 | consolidate | Quarantined events | svc | never attached to any opportunity | WF 4.4 |
| SPT-A-21 | store | `get`, `list_by_state`, `transition` | svc | conditional on expected states + version; wrong state → None, no write; version +1; `state_history` appended; QUALIFIED/REJECTED/EXPIRED emit their events | DESIGN §4 |
| SPT-A-22 | validate | Strong, plan ok, long, positional, fresh data, liquid, bullish | svc | QUALIFIED; the record has at, version, decision, reason_codes, explanations, opportunity_score, score_parts, market, stock, liquidity, derivatives (null, not_checked), data_as_of, revalidate_at; OPPORTUNITY_VALIDATED + OPPORTUNITY_QUALIFIED | P0-5, WF 6.5 |
| SPT-A-23 | validate | Risk-off regime (bearish, high volatility) | svc | CONDITIONAL, reason `regime_risk_off` | P0-5 |
| SPT-A-24 | validate | 20-day average traded value below the minimum | svc | REJECTED `liquidity_too_low` (OPPORTUNITY_REJECTED) | P0-5 |
| SPT-A-25 | validate | Data provider down / stale | svc | bars unreadable, bars stale, regime unavailable → DATA_INSUFFICIENT with reason; nothing invented; once data is back the revalidation moves it on | PRD 23.3 #5, WF 20 |
| SPT-A-26 | validate | Not tradable tonight | svc | no strong signal, intraday, short → validated and kept (WATCHLIST), never QUALIFIED | DESIGN D5 |
| SPT-A-27 | validate | Opportunity score | unit | built from DISTINCT families (two lists of one family count once), trend, participation, liquidity, regime; parts sum to the score; labelled "not a probability"; versioned; same inputs → same score | PRD 6.5, WF 25.21 |
| SPT-A-28 | validate | A bonus/split jump in the bars | unit | indicators use only the bars after `series_break` | P0-5 |
| SPT-A-29 | validate | Expiry | svc | past `window_until` → EXPIRED `window_ended`; a daily close below the plan's stop after detection → EXPIRED `closed_below_stop`; OPPORTUNITY_EXPIRED | P0-5 |
| SPT-A-30 | validate | Conflicting signals | svc | an otherwise qualifying opportunity with conflicts → CONDITIONAL `conflicting_signals` | WF 25.4 |
| SPT-A-31 | loop | Round | svc | enabled flag (staging / SPT_A_ENABLED); only the leader runs; catch-up → consolidate → validate → expire; `spt_state` {_id: spt_a, at, counts, errors}; a failing step is recorded and the round does not raise | P0-6 |
| SPT-A-32 | api | No session | api | 401 on every route | P0-7 |
| SPT-A-33 | api | GET /api/v1/scanner/signals(/{id}) | api | filters day, symbol, scanner_id, category, status; limit ≤ 500 (422 `invalid_limit`); bad day 422 `invalid_day`; unknown id 404 `signal_not_found` | P0-7 |
| SPT-A-34 | api | GET /api/v1/opportunities(/{id}), POST …/validate | api | filters state, day, symbol, horizon, direction, limit; 404 `opportunity_not_found`; 409 `opportunity_not_revalidatable`; 200 returns the validation | P0-7 |
| SPT-A-35 | backfill | `scripts/spt_backfill_signals.py` on an archive | svc | dry-run (default) prints counts and writes nothing; `--write` ingests and consolidates; a second `--write` adds nothing | P0-8, WF 20.3 |
| SPT-A-36 | outcomes | Forward returns and excursions | unit | T+1/5/10/20 close returns from the detection price; MFE/MAE per horizon (worked by hand); short signals measured in their own direction | P1-9, PRD 13.1 |
| SPT-A-37 | outcomes | Strong signal, hypothetical scan-plan-v3 | unit | first of stop / T1 / T2 / trend exit / time exit; the stop is judged on daily closes (scan-plan-v3's own rule), so a session that reaches a target and closes below the stop counts as the stop (conservative), and a gap below the stop is flagged (`gap_open`) and exits at that session's close; targets exit at the target, or the open on a gap above | P1-9, WF 17.1 |
| SPT-A-38 | outcomes | Series break after detection | unit | horizons after the break are null with reason `series_break` | P1-9 |
| SPT-A-39 | outcomes | Fade | svc | strong score below 70 in the detection day's scores doc → `faded: true`; no doc → null + reason | P1-9 |
| SPT-A-40 | outcomes | Kept apart from trades | svc | stored in `spt_signal_outcomes` keyed by signal id; no paper-trade collection is read or written; GET /api/v1/analytics/scanners gives counts, hit rates, average returns with sample sizes, small samples labelled | WF 25.20, PRD 13.7 |
| SPT-A-41 | outcomes | Evening run | svc | runs only after NSE's file for the day is in the bars; once per day | P1-9 |

## Not covered here (owned elsewhere or out of scope tonight)

- WF §25 items 5–19, 22: slices B and C.
- Real Mongo / Redis behaviour (unique index under concurrency, TTLs): verified by the integrator on staging, not here.
- Derivatives validation (WF §6.2 step 4): not built tonight; every validation says `derivatives: null` (not_checked).
