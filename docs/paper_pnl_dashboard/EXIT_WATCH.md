# Exit watch: stop-loss levels and exit alerts for live broker positions

Owner ask (4 Nov 2026, 18:5x IST, on the live P&L dashboard): "I need proper alerts and signals when to exit and take a stop loss".
Owner choices (AskUserQuestion, same evening):
- Delivery: **"In the app only for now"**. Staging has no email or Telegram sender (SMTP_* and NIDP_TELEGRAM_* are unset).
- Default stop: **"2 × ATR, trailing (Recommended)"**. Hedged futures use their put strike.

Brokers stay read-only. Nothing here places, modifies or cancels an order. An alert is a line on the screen, nothing more.
Standard trading words (stop loss, exit) are allowed on the P&L dashboard (owner, 3–4 Nov).

## Scope (release 1)

**What is watched**
- Every LIVE broker position on the P&L dashboard, from every connected account.
- Paper trades are not watched here. They already carry their own stop and target, raise STOP_LOSS_HIT / NEAR_STOP_LOSS on
  the dashboard, and are closed by the evening exit check.

**One watched position per account and underlying**
- The delta-one legs (shares and futures of the same underlying) must all be on one side, long or short.
- If an option protects them, that option is the hedge. For a long position that is a long put; for a short position, a
  long call. The option's quantity must be at least the delta-one quantity.
- Not watched, each listed with its reason:
  - option-only positions
  - delta-one legs on both sides
  - rows with no NSE symbol (for example an ICICI SGB code)

All levels are on the **underlying's share price**:
- puts settle on it
- a future follows it within its basis
- one scale for every position keeps the alerts comparable.

## The stop

The rule is `exit-atr-trail-v1`. Its bars are NSE end-of-day bars of the underlying, read through `desk_trading.fetch_bars`.
They are exchange data only: a Kite close never sets a stop (owner rule 29 Oct, "never feed a Kite close to exits or alerts").

1. **Series-break guard.** `nidp.prices_eod` is NOT adjusted for bonuses or splits. Example: HDFCAMC 1:1 bonus, ex-date
   2025-11-26, close 5,336.5 → 2,679.0.
   - Any close-to-close ratio below 0.65 or above 1.5 in the last 60 sessions is treated as a break.
   - Only the bars after the latest break are used.
   - A stop stored before the break is discarded and worked out again. Its history reads "price series break
     (bonus or split)".
2. **ATR14.** Wilder's average true range over 14 sessions. It needs at least 15 bars after any break; otherwise the
   position shows NO_STOP with the reason.
3. **Candidate.**
   - Long: close − 2 × ATR14.
   - Short: close + 2 × ATR14.
   - Rounded to 2 decimals.
4. **First stop.** The candidate from the latest end-of-day bar when the watcher first sees the position. It is stored with
   that day.
5. **Trail.** On each new end-of-day session after the stored day:
   - Long: stop = max(stored, candidate).
   - Short: stop = min(stored, candidate).
   - The stop never loosens.
   - Every evening adds a history entry {day, close, atr, candidate, stop, moved}.
6. **Your own stop wins.** If `position_levels` (PUT /api/positions/{underlying}/levels) holds a stop or a trail for the
   underlying, the stop is `positions.store.effective_stop(levels, price, side)` and the method is `yours`. The rule's level is
   still worked out and shown as the reference.
7. **Hedged.** The stop is the protective option's strike (the highest put strike for a long, the lowest call strike for a
   short). The method is `put_floor` / `call_cap`.
   - Floor loss at expiry = (future average − strike + option average) × quantity for a long, mirrored for a short.
   - Shares + put: the same, with the share average.
   - If the hedge covers less than the delta-one quantity, the position is NOT hedged. It uses the trail and carries the
     note "partly hedged (x of y)".

**Loss at stop (₹, gross, from the average cost; negative = a gain locked in)**
- Shares: (average − stop) × quantity (mirrored for a short).
- Futures: (future average − (stop + basis)) × quantity, where basis = future price − share price now. The future is assumed
  to keep today's basis; the screen says so.
- Hedged: the floor loss at expiry.

## Status (worked out on every read and every live round)

- **Price:** the live feed's quote in the session (`kite_live_feed.day_quote.day_quotes`). Otherwise the saved Kite close or
  the exchange close is shown, labelled with its source.
- **HIT:** the price is through the stop (long ≤ stop, short ≥ stop).
- **FLOOR:** a hedged position is at or through its strike. This is a WARNING, not CRITICAL: the loss is capped.
- **NEAR:** within `EXIT_NEAR_ATR` × ATR of the stop (default 0.5).
- **OK:** otherwise.
- **NO_STOP:** no level (the reason is shown).
- `distance_pct` = (price − stop) / price × 100 (long; mirrored for a short). `distance_atr` = (price − stop) / ATR.

## Alerts (in-app, one-shot, Mongo `exit_alerts`)

| kind | fires when | severity | once per |
|---|---|---|---|
| STOP_HIT | in the session, a LIVE price is through the stop | CRITICAL | position + stop value |
| NEAR_STOP | in the session, a LIVE price is within 0.5 ATR of the stop | WARNING | position + day |
| FLOOR_REACHED | in the session, a hedged position's LIVE price is at or through its strike | WARNING | position + strike + day |
| CLOSE_THROUGH_STOP | evening: the exchange close is through the stop in force that day | CRITICAL | position + day |
| SUPPORT_BREAK | evening: the close is below the previous 20 sessions' lowest low (long) / above their highest high (short) | WARNING | position + day |
| TREND_TURN | evening: today close < EMA20 < EMA50 (long; the reverse for a short), which was not true the session before | WARNING | position + day |
| STOP_RAISED | evening: the trail moved the stop | INFO | position + day |
| HEDGE_REMOVED | the stored level was a floor/cap and the book now holds the delta-one legs without that option | CRITICAL | position + day |
| RESULTS_SOON | a results date (DaaS /v1/events, event_type quarterly_results) is within the next 3 calendar days | INFO | position + event date |

Rules that apply to every alert:
- An alert fires only on data that was read. A stale or missing price fires nothing.
- When the feed is not live, the round records why (`feed_not_live`).
- `_id` = sha1 of (user, position key, kind, dedupe value), so a second round inserts nothing (duplicate key = already fired).
- Each alert stores:
  - the price and the level
  - the price source and its time
  - the rule id
  - `seen: false`
- Text uses standard words. Example: "ACME (ICICI Direct) is at ₹172.40, through its stop loss ₹174.20
  (2 × ATR trail). Nothing has been sold: the broker is read-only here."

## Watcher (`services/exit_watch/runner.py`)

**When it runs**
- On where APP_ENV=staging or EXIT_WATCH_ENABLED=1; EXIT_WATCH_ENABLED=0 turns it off.
- One leader across workers: Redis key `nivesh:exitwatch:leader`, through the scan dashboard's store `lead()`.

**The book**
- Every user whose broker positions were read in the last `EXIT_WATCH_BOOK_DAYS` (3) days.
- Their latest `position_snapshots` document per account; rows with a quantity.
- The watcher never calls a broker. `book_as_of` is the snapshot's `last_seen_at`.

**Live round** (09:15–15:30 IST weekdays, every `EXIT_WATCH_LOOP_S` = 30 s)
1. Build the book.
2. Store a missing level.
3. Read `day_quotes` for the underlyings.
4. Fire STOP_HIT / NEAR_STOP / FLOOR_REACHED / HEDGE_REMOVED.
5. Write `exit_watch_state` {_id: "live", at, users, positions, fired, feed_why}.

**Evening round** (18:30–23:30 IST weekdays, every 10 min until done for the day)
- It runs once `fetch_bars` holds TODAY's bar for an underlying.
- It then ratchets the stop and fires the evening alerts.
- An underlying whose bar is not in yet is tried again next time.
- When every watched underlying is done, the round writes `exit_watch_state` {_id: "eod", day}.
- RESULTS_SOON is checked in this round.

## API

### `GET /api/desk/pnl/exits?account=ALL|<account_id>`

The book comes from the dashboard's own broker read (`paper_pnl.live.read_broker_book`, cached 60 s). Stored levels are
used where they exist. A missing level is worked out in memory and marked `stored: false`. **A read writes nothing.**

- 401 without a session.
- 422 `invalid_account`.

```json
{
  "as_of": "ISO", "session": "open|closed",
  "rule": {"id": "exit-atr-trail-v1", "text": "..."},
  "watcher": {"enabled": true, "live_round_at": "ISO|null", "eod_day": "YYYY-MM-DD|null", "feed_why": null},
  "positions": [{
    "key": "acct|SYM|long", "account_id": "...", "account": "ICICI Direct", "underlying": "ACME",
    "label": "ACME shares", "kind": "shares|future|hedged", "side": "long|short",
    "legs": [{"instrument": "ACME", "type": "EQ|FUT|PE|CE", "quantity": 500, "avg": 200.0, "expiry": null, "strike": null}],
    "price": 179.65, "price_source": "kite_live|kite_close|eod", "price_as_of": "ISO",
    "stop": 160.71, "method": "atr_trail|yours|put_floor|call_cap|none", "stop_day": "2026-11-04", "stored": true,
    "rule_stop": 160.71, "atr": 9.47, "atr_pct": 5.27,
    "distance_pct": 10.54, "distance_atr": 2.0, "status": "OK|NEAR|HIT|FLOOR|NO_STOP", "why": null,
    "loss_at_stop": 19645.0, "loss_basis": "text", "support": 174.2, "note": null,
    "history": [{"day": "...", "stop": 0, "candidate": 0, "close": 0, "atr": 0, "moved": true, "reason": "..."}],
    "own": {"stop": null, "target": 300.0, "trail_pct": null}
  }],
  "not_watched": [{"label": "SGBX01 (ICICI Direct)", "why": "no NSE symbol for this broker code"}],
  "alerts": [{"id": "...", "at": "ISO", "day": "...", "kind": "STOP_HIT", "severity": "CRITICAL", "key": "...",
              "underlying": "...", "account": "...", "text": "...", "price": 0, "level": 0, "source": "kite_live",
              "seen": false}],
  "unseen": 1,
  "accounts": [{"account_id": "...", "name": "ICICI Direct", "state": "OK|STALE|SIGN_IN|ERROR|OFF"}]
}
```

The alerts are the last 7 days, newest first, at most 100.

### `POST /api/desk/pnl/exits/seen`

- Body `{"ids": ["..."]}`, or `{}` for all of the user's unseen alerts.
- Returns `{"marked": n}`.
- 422 `invalid_body`.
- Writes only the caller's own alert docs.

### Your own stop

Reuses `PUT /api/positions/{underlying}/levels` and `DELETE` on the same path.

- **That PUT replaces the whole document.** So each position carries `own`, the user's stored {stop, target,
  trail_pct} for the underlying, or null.
- **"Set my stop"** sends {stop, target, trail_pct} with the target and trail unchanged.
- **"Use the rule"** clears both the stop and the trail, since both set the stop:
  - with a target kept: PUT {stop: null, target, trail_pct: null}
  - without one: DELETE

## Screen (P&L dashboard)

Shown in modes ALL and LIVE, hidden in PAPER.
- **Banner** under the header when `unseen > 0`: the newest unseen alert's text, the count, and a "Mark seen" button.
  - `pnl-exit-banner`, `pnl-exit-seen`
- **Section "Exit watch"** after the positions block, before the risk monitor: `pnl-exits`.
  - Desktop: a table, one row per watched position (`pnl-exit-row`).
    - Position: symbol, account, kind chip.
    - Price, with its source.
    - Stop loss, with a method chip (`pnl-exit-stop`).
    - Distance (% · ATR).
    - Status chip (`pnl-exit-status`).
    - Loss at stop.
    - Latest signal.
  - Phone: cards (`pnl-exit-card`), with no page-level sideways scroll.
  - Expanding a row shows:
    - the stop history (the last 5 evenings)
    - the rule text
    - "Set my stop" (`pnl-exit-setstop`, input `pnl-exit-setstop-input`, save `pnl-exit-setstop-save`)
    - "Use the rule" (`pnl-exit-userule`, only when the method is `yours`)
  - Below: "Not watched" lines, then the alerts list (`pnl-exit-alerts`, items `pnl-exit-alert`, unseen ones marked), and the
    watcher line: "Checked live every 30 s in market hours · stops move after NSE's end-of-day file · in-app only".
- Refetch every 30 s while the page is open.
