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
