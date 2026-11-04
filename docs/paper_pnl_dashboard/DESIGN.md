# Real-time paper P&L dashboard — design (4 Nov 2026)

Source: the owner's `nivesh_realtime_pnl_dashboard_spec.md` (pasted 4 Nov 2026). Owner decisions the same morning:

| Decision | Answer |
|---|---|
| Placement | Trade Desk › Paper Trading › **P&L dashboard** (third sub-view: Live desk · Trade journal · P&L dashboard), `?tab=trade&view=paper&sub=pnl` |
| Wording | Standard trading words on this screen: Avg price, Stop loss, Target, Long/Short, "Near stop loss", "Target reached" |
| Scope | **Paper only** in this release. Live broker P&L is a later release; My portfolio keeps the broker book |

## What the spec asked for, and how this repo already answers parts of it

| Spec | Here |
|---|---|
| New Postgres ledger (`trading_accounts`, `trading_executions`, `trading_positions`, ...) | **Not created.** The paper ledger already exists (Mongo `desk_paper_trades`: cash trades and multi-leg F&O structures, lifecycle, fills, cost card) and the owner's "one store" rule forbids a second copy. The P&L engine reads it **read-only** and converts each trade into normalized executions (spec §5.3: one canonical engine fed by normalized executions). |
| Redis latest-quote cache | **Reused**: the platform Kite feed already writes `nivesh:quote:<EXCHANGE>:<SYMBOL>` (services/kite_live_feed/quote_cache.py). |
| WebSocket `/ws/v1/trading/pnl` | **Server-sent events** `/api/desk/pnl/stream` (the app's existing live transport, `/api/live/stream`), with polling fallback. Every event is a full snapshot with a monotonic `sequence`, so gaps and duplicates cannot corrupt the screen (spec §7.8's reconnect / snapshot-after-reconnect / duplicate rejection fall out of that). |
| `/api/v1/trading/...` paths | `/api/desk/pnl...` — the desk's existing prefix (all paper-trade routes live under `/api/desk`). |
| `pnl_snapshots` table for the intraday chart | **Derived** from Kite intraday candles of the instruments held (the curve exists from the first minute, needs no new job or table, and is reproducible). |
| Partial exits, reversals, shorts (TC-002…TC-005) | The engine supports them (weighted average, spec §16 `accounting_method: WEIGHTED_AVERAGE`). Today's paper ledger never produces them (cash trades are long-only and close whole), so the engine is unit-tested on them directly. |
| Live mode, broker reconciliation, AI supervisor, PATCH risk | Out of this release (owner: paper only). The payload carries `mode: "PAPER"` everywhere so Live can join later without a contract change. |

## Price rule (owner, 29 Oct "Kite close until EOD"; 28 Oct "no stale market data")

Per open position, first that applies:

| When | Price | `price_status` |
|---|---|---|
| Session open (09:15–15:30 IST), quote in Redis/feed and fresh | Kite live LTP | `LIVE` |
| Session open, quote older than the feed's stale limit (2.5 cadences) | that LTP, labelled with its time | `DELAYED` |
| Session open, contract not on the feed (stock options, far strikes, next-month futures) | Kite REST `quote()` for the named contract (read-only, ≤ 40 per call, cached 5 s per worker) | `LIVE` / `DELAYED` by its exchange timestamp |
| After 15:30, before the exchange's EOD rows | the saved Kite close (provisional) / the contract's last traded price today | `CLOSE` |
| Otherwise | the ledger's own end-of-day mark (nidp prices_eod / F&O bhavcopy) | `EOD` |
| None of the above | no price; the position's P&L is null and the totals say they are incomplete | `MISSING` |

Freshness is measured from the feed's `received_at` (server clock), not its `exchange_ts`: on staging (4 Nov 09:30 IST) the
feed's `exchange_ts` read `04:00:03+05:30`, the container's UTC clock labelled IST, 5 h 30 m off (a feed bug, reported separately).
A REST quote is aged from Kite's `last_trade_time`. A contract that has not traded yet today may use its previous session's last
trade (the owner's T-1 rule), always `DELAYED`, with no day figure. Each worker reloads the day's platform token before a Kite call
(`platform_token.refresh_cache`, at most once a minute): only the feed's leader refreshes its own copy.

**Display only.** The live price never fills, exits, or marks the ledger: the paper engine keeps deciding exits on end-of-day bars
(evening check). A stop touched intraday is shown as an alert that says so.

## Accounting

- Executions per trade: cash trade = BUY quantity at the fill (`sim_entry_price`, else the reference entry when `entry_status`
  is assumed/reached) and, if closed, SELL at `exit_price`. Strategy trade = one execution per leg (side, lots × lot size, the
  leg's entry price) and, if closed, the opposite side at the leg's `exit_mark`. A waiting / not-reached entry has NO execution
  (spec §13.4 rule 2) and is listed under pending entries.
- Position = weighted average (spec §16). Unrealized = (LTP − avg) × signed qty × multiplier; realized from closed quantity.
- Strategy P&L = sum of its legs (never added again to the leg totals).
- Charges: closed trades = the desk cost card's figures stored at the close (**booked**, modelled — paper has no contract note);
  open trades = the same cost card with the closing side at the current price (**estimated**). Never mixed (spec §5.2 F).
- Net = gross − charges. Return % = net ÷ the paper account's starting capital.
- Day P&L = (LTP − previous close) × qty for positions held into today (entry session before today), (LTP − avg) × qty otherwise.
- Reconciliation (spec §17 "paper P&L reconciled against the existing simulator"): every closed trade's engine realized P&L is
  compared with the ledger's stored `realized_pnl_rs`; a difference over ₹0.01 is a `RECONCILIATION_MISMATCH` alert.
- Period filter applies to closed trades (by exit session); open positions are always current.

## API (all GET, user-scoped by the session; 401 without one; nothing writes)

`GET /api/desk/pnl?segment=ALL|EQUITY|FUTURES|OPTIONS&period=TODAY|1W|1M|ALL|CUSTOM&from=YYYY-MM-DD&to=YYYY-MM-DD`

```jsonc
{
  "mode": "PAPER", "currency": "INR", "as_of": "2026-11-04T10:30:01+05:30", "sequence": 1762232401000,
  "filters": {"segment": "ALL", "period": "TODAY", "from": "2026-11-04", "to": "2026-11-04"},
  "market": {"session": "open|pre_open|closed", "feed": "live|delayed|closed|expired|not_connected|disabled",
             "feed_age_seconds": 1.2, "stale_after_seconds": 75, "price_rule": "…", "day": "2026-11-04"},
  "summary": {"realized_pnl": 0, "unrealized_pnl": 4200.5, "gross_pnl": 4200.5, "charges_booked": 0, "charges_estimated": 120.4,
              "net_pnl": 4080.1, "day_pnl": 950.0, "allocated_capital": 10000000, "return_pct": 0.0408,
              "open_positions": 3, "winning_positions": 2, "losing_positions": 1, "closed_trades": 0,
              "pending_entries": 0, "unpriced_positions": 0, "stale_positions": 0, "complete": true},
  "by_segment": [{"segment": "EQUITY", "open_positions": 3, "realized_pnl": 0, "unrealized_pnl": 4200.5, "charges": 120.4, "net_pnl": 4080.1}],
  "positions": [{   // + price_day; summary also has open_legs; market.notes[]; strategies[].summary/opened_at/risk_note
     "position_id": "<trade_id>" | "<trade_id>:<leg>", "trade_id": "…", "leg_index": null, "strategy_id": null | "<trade_id>",
     "strategy_name": null | "Bull call spread", "mode": "PAPER", "account": "Paper account",
     "instrument": "ICICIBANK" | "NIFTY 25 Nov 26000 CE", "symbol": "ICICIBANK", "underlying": "ICICIBANK",
     "segment": "EQUITY|FUTURES|OPTIONS", "side": "LONG|SHORT", "net_quantity": 35, "lots": null, "lot_size": null,
     "avg_price": 1413.21, "ltp": 1431.5, "prev_close": 1420.1, "price_status": "LIVE|DELAYED|CLOSE|EOD|MISSING",
     "price_source": "Kite live", "price_at": "…", "price_age_seconds": 0.8,
     "invested_value": 49462.35, "unrealized_pnl": 640.15, "realized_pnl": 0, "gross_pnl": 640.15,
     "charges_estimated": 40.2, "net_pnl": 599.95, "day_pnl": 399.0, "return_pct": 1.29,
     "stop_loss": 1374.9, "target": 1489.83, "distance_to_stop_pct": 3.95, "risk_used_pct": 0.0,
     "status": "ACTIVE|STOP_LOSS_HIT|NEAR_STOP_LOSS|TARGET_REACHED|EXIT_DUE|SETTLED", "opened_at": "…", "expiry": null,
     "executions": [{"execution_id": "…", "side": "BUY", "quantity": 35, "price": 1413.21, "at": "…", "kind": "fill"}]
  }],
  "strategies": [{"strategy_id": "…", "name": "Bull call spread", "underlying": "NIFTY", "direction": "bullish", "status": "OPEN",
                  "legs": ["<trade_id>:0", "<trade_id>:1"], "underlying_ltp": 25890.0, "stop_underlying": null, "target_underlying": null,
                  "entry_net_premium": -5000, "current_value": -3250, "unrealized_pnl": 1750, "charges_estimated": 100,
                  "net_pnl": 1650, "capital_at_risk": 5000, "complete": true}],
  "pending_entries": [{"trade_id": "…", "symbol": "HDFCBANK", "entry_rule": "break_above", "level": 1655, "ltp": 1641.2}],
  "closed": [{"trade_id": "…", "instrument": "AXISBANK", "segment": "EQUITY", "closed_at": "…", "exit_session": "2026-10-24",
              "exit_reason": "stop", "realized_pnl": -3200, "charges": 160.1, "net_pnl": -3360.1}],
  "risk": {"capital": {"starting": 10000000, "cash": 10000000, "blocked": 123887.21, "available": 9876112.79, "utilisation_pct": 1.24,
                       "basis": "capital at risk, not exchange margin"},
           "open_risk_rs": -2100.0, "open_risk_limit_rs": 300000, "daily_loss_limit_rs": 200000, "daily_loss_used_pct": 0,
           "alerts": [{"severity": "CRITICAL|WARNING|INFO", "type": "STOP_LOSS_HIT|NEAR_STOP_LOSS|TARGET_REACHED|EXIT_DUE|EXPIRY|STALE_PRICE|FEED|RECONCILIATION_MISMATCH|CAPITAL",
                       "position_id": "…", "symbol": "…", "message": "…", "observed": 1371.2, "threshold": 1374.9}]},
  "analytics": {"trades": 2, "wins": 0, "losses": 2, "win_rate_pct": 0, "profit_factor": null, "avg_win": null, "avg_loss": -2400.1,
                "max_drawdown_rs": -4800.2, "max_drawdown_pct": 0.048, "daily": [{"date": "2026-10-24", "net_pnl": -3360.1}]},
  "reconciliation": {"checked": 2, "mismatches": []},
  "notes": {"display_only": "…", "charges": "…", "capital": "…"}
}
```

`GET /api/desk/pnl/stream?<same filters>` — `text/event-stream`: `retry: 3000`, then `event: snapshot` with the body above every
`PNL_STREAM_SECONDS` (3 s in session, 30 s otherwise), a `: heartbeat` comment every 15 s, closed after 30 min (the browser
reconnects and receives a fresh snapshot).

`GET /api/desk/pnl/timeseries?interval=5m|15m` — the current open book through today's session (or the last session before the
open): `{date, interval, baseline_gross, points: [{t, unrealized_pnl, realized_pnl, gross_pnl, net_pnl, change_since_baseline}],
positions_used, missing: [{position_id, reason}], basis}`. Candles are Kite's (raw), carried forward for a minute an instrument did
not trade; a position with no candles is listed in `missing` and left out of the curve (which then says it is partial).

## Frontend

`frontend-v5/src/pages/CopilotApp/screens/tradingdesk/tabs/trade-desk/`: `pnl-data.ts` (types, readers that trust nothing, the SSE
hook with polling fallback, pause when hidden, sequence check), `PnlDashboard.tsx` (page), `pnl-parts.tsx` (cards, table, chart,
alerts). Desktop order = spec §3.1; phone order = spec §3.2 with expandable position cards. CSV export of the filtered positions in
the browser. Live exit is not offered (paper desk closes trades in Live desk; this view links there).

## Verified on staging (4 Nov 2026, 09:31–09:33 IST, market open)

Branch code loaded inside the staging backend container against the real Mongo ledger, Redis quote cache, Kite feed and data
platform (test_reports/paper_pnl_dashboard_*.md): the owner's 10 open paper trades (5 share trades, 5 option structures, one with a
cash leg) priced live; every average price and quantity equal to the stored fills; warm reads 7–16 ms (cold 2.8 s); the stream
sends a snapshot every 3 s; the intraday curve from 09:15; no trade document changed.

---

# v2 — the owner's "Real-Time PnL Dashboard" design (4 Nov 2026, afternoon)

The owner pasted a standalone design ("Real-Time PnL Dashboard (standalone).html", mock data) and asked: "Please change the p&l
dashboard to this". Decisions the same afternoon (AskUserQuestion):

| Decision | Answer |
|---|---|
| Live mode | **Live, read-only.** Broker NET positions from the user's connected accounts (the read My portfolio / Open positions use), refreshed at most every 60 s; prices from the same live feed as paper (every few seconds). Broker positions have no stop/target or entry signal (shown "not recorded"); nothing places, modifies or cancels a broker order. Long-term holdings are NOT positions here (they stay on My portfolio). |
| Modify risk | **Edit stop and target** of an open paper SHARE trade: a new dated version, in force from the next session (today's bar is still checked against the old levels at the evening check), with an audit record. Option structures keep their levels (read-only) in this release. |
| Sections the design does not draw (period filter, closed trades + analytics, waiting entries, by segment) | Kept, in one **folded section at the bottom**; the design's own sections stay in its order. |
| Wording | Standard trading words stay allowed here (4 Nov exception). The design's "Suggested action" / "AI suggestion" read as advice: shown as "Points to review" and "Rule-based reading of the figures above" (25 Oct rule: never recommend / pick / suggested). |

## Page order (desktop), as drawn

1. Header — mark, "Trading Desk", "Overview · Real-time P&L"; right: feed pill, one pill per account (name + OK / STALE / SIGN IN / ERROR / OFF), IST clock, Pause / Resume (freezes the screen's updates; the stream is closed while paused).
2. Filter bar — mode (All · Paper · Live), account select, segment select, search (instrument or strategy; filters the table only, never the totals).
3. Hero (net P&L after estimated charges for the selection, return % on capital, "Gross − est. charges", stale note) + 2×2 KPIs (Realized, Unrealized, Est. charges, Open positions: winning · losing).
4. Two mode cards: Paper, Live (net, return, "N positions · ₹X allocated", REAL / UNREAL); the selected mode's card is outlined.
5. Intraday net P&L chart — cumulative from the session open for the selected mode; HIGH / LOW; zero line; end dot.
6. Open positions — one row per share position and per leg (a leg's strategy name under its instrument); columns Mode·Account, Instrument, Side·Qty, Avg, LTP, Unrealized, Realized, Net P&L, SL / Target, Risk used, Status; sort chips Net P&L · Return % · Exposure; Export CSV. A row expands to: P&L breakdown · Fills · Actions (Modify risk, Simulate exit / Initiate exit); the candle chart (Chart Analysis' AnalysisChart, 15m, with TARGET 1 / ENTRY / STOP / LTP lines) + Trade journal (signals at entry); Trade P&L chart (net of est. charges since entry).
7. Risk monitor (meters: Margin used, Daily loss limit, Exposure, Open positions at risk; alerts) + "AI Trading Supervisor" card (rule-based reading; no LLM call).
8. Footer line.
9. Folded: period filter · closed trades + analytics · waiting entries · P&L by segment (the v1 components).

Phone (< 640 px of room): the same order; positions as cards that expand to the same detail; no page-level sideways scroll.

## API changes (v2)

### `GET /api/desk/pnl` and `/stream` — new query `mode=ALL|PAPER|LIVE` (default ALL) and `account=ALL|paper|<broker account_id>` (default ALL)

`mode` / `account` filter `positions`, `strategies`, `summary`, `by_segment`, `risk.alerts`, `pending_entries`, `closed` (closed and
pending are paper only). Unknown values answer 422 `invalid_mode` / `invalid_account` (an account id that is not one of the
user's answers 422 too). Body changes:

```jsonc
{
  "mode": "ALL" | "PAPER" | "LIVE",            // the SELECTED mode (v1 always sent "PAPER")
  "filters": {"segment": "...", "period": "...", "from": null, "to": null, "mode": "ALL", "account": "ALL"},
  "accounts": [                                // always every account, whatever the filters
    {"account_id": "paper", "name": "Paper account", "mode": "PAPER", "broker": null,
     "state": "OK", "state_note": null, "read_at": "…", "capital": 10000000, "capital_basis": "…",
     "open_positions": 3, "net_pnl": 1234.5},
    {"account_id": "<id>", "name": "Zerodha", "mode": "LIVE", "broker": "zerodha",
     "state": "OK" | "STALE" | "SIGN_IN" | "ERROR" | "OFF", "state_note": "Session expired: sign in to Zerodha again." | null,
     "read_at": "…" | null, "capital": null, "capital_basis": "…", "open_positions": 0, "net_pnl": null}
  ],
  "modes": {                                    // always both, unfiltered by mode/account (segment applies)
    "PAPER": {"realized_pnl": 0, "unrealized_pnl": 0, "gross_pnl": 0, "charges": 0, "net_pnl": 0, "capital": 10000000,
              "return_pct": 0, "open_positions": 0, "complete": true, "available": true, "note": null},
    "LIVE":  {"realized_pnl": null, "unrealized_pnl": 0, "gross_pnl": 0, "charges": 0, "net_pnl": 0, "capital": null,
              "return_pct": null, "open_positions": 0, "complete": true, "available": false,
              "note": "No broker account could be read: Zerodha session expired; ICICI Direct session expired."}
  },
  "summary": { …v1 fields…, "exposure_rs": 123456.0, "capital_basis": "…" },   // for the selection
  "positions": [{ …v1 fields…,
     "mode": "PAPER" | "LIVE", "account_id": "paper" | "<id>", "account": "Paper account" | "Zerodha",
     "broker_pnl": null | 1234.5,              // LIVE: the broker's own P&L figure on its last read (includes its realised part)
     "broker_read_at": null | "…",
     "product": null | "intraday" | "delivery" | "carryforward" | "margin",
     "exposure_rs": 49000.0,                   // |net quantity × multiplier × LTP|, null without a price
     "editable_levels": true | false,          // PAPER share trade, open: Modify risk allowed
     "pending_levels": null | {"stop_loss": 1360.0, "target": 1500.0, "from_session": "2026-11-05", "version": 2},
     "executions_note": null | "Today's fills from the broker's trade book; earlier fills are not sent by brokers."
  }],
  "risk": { …v1…, "margin": {"used_pct": 1.2, "basis": "paper: capital blocked by open trades, not exchange margin" | "not read from brokers"},
            "exposure_rs": 123456.0 }
}
```

LIVE position rules: quantity, average and product are the broker's (signed quantity: negative = short); LTP and its status come
from the same price resolver as paper (`prices.resolve`, contract mapped through `services/positions/symbols`); unrealized =
(LTP − avg) × signed qty × multiplier; realized = null (brokers do not split it; `broker_pnl` shows their own total);
charges_estimated = the desk cost card for the closing side at the current price; stop_loss / target / pending_levels = null;
status ACTIVE (or EXPIRES_TODAY on the expiry day). A position whose contract cannot be mapped or priced is MISSING (left out of
totals, said so). Broker reads are cached per user for `PNL_BROKER_TTL_S` (60 s); an account read older than 2 × TTL is STALE.
A broker read that fails gives its account `SIGN_IN` (session expired / not connected) or `ERROR`, never a failed snapshot.

### `GET /api/desk/pnl/timeseries` — new `mode=ALL|PAPER|LIVE` and `trade=<paper trade id | live position id>`

- `mode` picks the book of the intraday curve (LIVE = the broker positions' instruments).
- `trade` returns ONE trade's curve: `{"trade": "<id>", "mode": "PAPER", "from": "<ISO of the first point>", "since_entry": true|false,
  "points": [{"t", "gross_pnl", "net_pnl"}], "basis": "…", "missing": [...]}`. A paper SHARE trade is drawn from its entry session
  (at most 10 sessions back at 15m, else "since <day>"); a paper structure and a live position over today's session only
  (`since_entry: false`, the basis says why). Net = gross − the trade's estimated charges (constant).
- 404 `trade_not_found` for an id that is not the user's open position.

### `GET /api/desk/pnl/journal/{trade_id}` — signals at entry (read-only)

```jsonc
{"trade_id": "…", "symbol": "ICICIBANK", "entry_day": "2026-11-04", "found": true | false,
 "why": null | "No scan signal for ICICIBANK on 4 Nov." | "Scan signals are kept 3 days; this trade opened on 28 Oct.",
 "signal": null | {"kind": "strong" | "scored", "first_strong": "…" | null, "score": 82, "parts": {"quality": 24, "trend": 16, "reason": 14,
            "size": 10, "participation": 6, "penalty": 0}, "reasons": ["RSI(14) 58", "…"], "lists": [{"id": "…", "title": "Breakout"}],
            "entry": 1245.0, "stop_loss": 1220.0, "target_1": 1295.0, "target_2": 1345.0, "rr_1": 2, "rr_2": 4,
            "trend_exit": "…", "plan_ok": true, "plan_note": null, "rules": "scan-plan-v3"},
 "trade": {"source": {"kind": "…", "bucket": "…", "signal_date": "…"} | null, "rationale": "…" | null, "note": "…" | null,
           "opened_at": "…", "entry_rule": "at_once"}}
```

Looked up in the Scan dashboard's store (Redis, kept 3 days): the strong record (score ≥ 70, its frozen plan) for the stock on the
trade's entry day, else that day's stored score. Paper share trades only; a structure or a live position answers 404
`journal_not_available` (the screen says broker positions record no entry signal).

### `PATCH /api/desk/paper-trades/{trade_id}/levels` — Modify risk (WRITES; paper share trades only)

Body `{"stop_price": 1360.0, "target_price": 1500.0 | null, "note": "…"}` (at least one of the two levels; unknown fields 422
`unknown_field`). Header `Idempotency-Key` optional (a replay with the same key and body answers the first answer).

| Check | Answer |
|---|---|
| not the user's / unknown | 404 `trade_not_found` |
| closed | 409 `trade_already_closed` |
| a structure | 409 `levels_not_editable` |
| stop not a positive price / target not a positive price | 422 `invalid_stop_price` / `invalid_target_price` |
| stop ≥ the last end-of-day close (long) | 422 `stop_not_below_price` |
| target ≤ the last end-of-day close | 422 `target_not_above_price` |
| stop ≥ target | 422 `stop_not_below_target` |
| nothing changes | 422 `no_change` |

Effect: appends `{version, at, session: <IST day of the change>, stop_price, target_price, prev_stop, prev_target, note}` to the
trade's append-only `level_changes`; the simulator applies a change to bars AFTER its session (so today's bar keeps the old levels
at the evening check — no hindsight); `stop_history` gets a version with reason `manual`; the trailing ATR rule (opt-in) only raises
from the new stop. An audit record is written. Answer 200: the public trade (with `level_changes`, `current_stop`, `current_target`,
`pending_levels`).

`svc.public_trade` adds `level_changes`, `current_target` and `pending_levels` (the latest change not yet in force); the P&L
positions read `stop_loss` / `target` = the levels in force, `pending_levels` = the waiting change.
