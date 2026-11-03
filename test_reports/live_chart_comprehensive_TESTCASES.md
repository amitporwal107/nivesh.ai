# Live chart, comprehensive — design, API contracts and test cases (2026-10-29)

Owner asks (29 Oct): "display OI futures and option volume, price change and OI change in the same chart", "make the chart
comprehensive", "display market events as a signal on the chart to see the price/volume reaction of the event"; "if we have
the data we need to show it on the charts". Owner choices (29 Oct, 19:00 IST):
- Layout: STACKED PANES on one time axis with one crosshair/readout: price (+ events) · volume · futures OI · options.
- Options: nearest expiry, ATM ±5 strikes, CE and PE, read on demand from Kite history (cached); the feed also starts saving
  every stock's full chain (separate PR, feat/feed-option-chains).
- Events: results & board meetings, exchange filings, corporate actions, market-wide (macro calendar, F&O expiry days, big
  FII/DII flow days).

Screen: Trade Desk › Chart Analysis › Live chart (`tabs/trade-desk/LiveChart.tsx`), chart `tradingdesk/CandleChart.tsx`.
Rules that hold everywhere: real data only, nothing invented; a value Kite did not give is null and drawn as a gap; every pane
says its source and why it is empty; live in the session, the Kite close after it, the exchange's EOD once loaded (owner rule
29 Oct); nothing here is an input to a paper fill, risk or sizing. Read only, nothing sent to a broker.

## UI design (stacked panes, shared x = the candles' slots)

```
 READOUT (hover/←→): 29 Oct 15:00 · O H L C · Vol · Fut OI 1.52 Cr (+0.4%) · CE OI Δ +12.3 L · PE OI Δ −4.1 L · PCR 0.86 · ◆ Results
 ┌ price: candles · EMA20 · entry/stop/T1/T2 · WATCH/READY/CONFIRMED/RVOL pills · event glyphs on the bottom edge ┐
 ├ volume                                                                                                         ┤
 ├ FUTURES OI [Current|Next|Far|All]: OI line (right axis) + per-bar OI Δ bars coloured by build-up (LB SB SC LU)  ┤
 ├ OPTIONS (nearest expiry, ATM ±5): CE OI Δ up-bars / PE OI Δ down-bars + PCR line; CE/PE volume in the readout ┤
 └ EVENTS: list under the chart — kind, date, title, reaction (day %, next day %, gap %, volume × 20-day avg)      ┘
```
Toggles ("Signals on chart"): Pattern · Confirmation · Volume · F&O · Events (new). Pane toggles: Futures OI, Options.
Glyphs: R results · B board meeting · F filing · C corporate action · M macro · X F&O expiry · $ FII/DII flow day.
Phone (390 px): panes stack at reduced heights; no sideways scroll.

## API contracts

### A. Futures per-bar series — extend GET /api/fno/{symbol}/futures/oi-buildup (mode "intraday" only)
Each `contracts[i]` and `consolidated` gains `bars: [[t_iso_ist, close, volume, oi]]` for the sessions sent PLUS the one
baseline bar before them (so the first shown bar has an OI change). Consolidated: close = the near month's, volume and OI
summed over the listed expiries at the same t (a t missing in any listed expiry → oi null for that t, never a partial sum).
mode "end_of_day": `bars` is [] (unchanged otherwise).

### B. Options intraday — NEW GET /api/fno/{symbol}/options/intraday?interval=15m&sessions=2&strikes=5
Kite historical_data(oi=1) for the nearest unexpired expiry, the ATM strike ±`strikes` (max 8), CE and PE. ATM = the listed
strike nearest the underlying's reference price (the cash symbol's last Kite price: live quote in the session, else the
saved Kite close / last candle; `ref` says which). Reloads the stored platform Kite login first. Cache 60 s open / 600 s
closed per (symbol, interval, sessions, strikes). Kite historical limit respected (paced).
```
{ "symbol", "mode": "intraday", "interval", "sessions", "expiry": "YYYY-MM-DD", "atm": 1870.0, "strikes": [..11 floats..],
  "ref": {"price", "source": "kite_live|kite_close|candle", "at"},
  "series": [ {"t", "ce_oi", "pe_oi", "ce_oi_change", "pe_oi_change", "ce_volume", "pe_volume", "pcr"} ],   // sums over the
            // strikes; a t where any requested contract has no candle → that t's sums are null (never a partial sum);
            // change = this bar's sum − the previous bar's (first bar of the response: vs the baseline bar, else null);
            // pcr = pe_oi / ce_oi (null when ce_oi is 0 or null)
  "contracts": [ {"tradingsymbol", "strike", "type": "CE|PE", "bars": [[t, o, h, l, c, v, oi]]} ],
  "missing": ["TRADINGSYMBOL", ...],                       // requested contracts Kite returned no candles for
  "availability": "ok" | "token_missing" | "token_expired" | "no_options" | "no_bars" | "upstream_unavailable",
  "source": "Kite intraday (historical, oi)", "as_of", "note", "read_only": true }
```
400 on a bad interval / strikes; 200 with availability ≠ ok when Kite cannot answer (the pane says why).

### C. Chart events — NEW GET /api/desk/chart-events/{symbol}?from=YYYY-MM-DD&to=YYYY-MM-DD (default: last 90 days → +30)
```
{ "symbol", "from", "to",
  "events": [ {"id", "date": "YYYY-MM-DD", "time": "HH:MM"|null, "kind": "results|board|filing|dividend|split|bonus|buyback|
               rights|agm|demerger|macro|fno_expiry|fii_dii", "scope": "stock|market", "title", "detail"|null, "source",
               "url"|null,
               "reaction": {"basis": "nidp.prices_eod_adjusted (+ today's Kite close, provisional)", "day_change_pct",
                            "next_day_change_pct", "gap_pct", "volume_x_avg20", "provisional": bool} | null } ],  // null for a
                            // future date or a day without bars; reaction day = the event's session (an event after 15:30
                            // or on a holiday reacts on the next session)
  "sources": {"events_calendar": "ok"|"unavailable: <why>", "filings": ..., "corporate_actions": ..., "macro": ...,
              "fno_expiry": ..., "fii_dii": ...},
  "fii_dii_rule": "<how a flow day is chosen, e.g. |net| at or above the 90th percentile of the last 250 sessions>",
  "read_only": true }
```
Requires login (`get_current_user`); a failed source never fails the route (it is listed in `sources`).

## Test cases

### Backend (pytest, fakes)
| id | case | expected |
|---|---|---|
| A1 | intraday futures answer carries per-contract bars incl. one baseline bar | bars len = shown bars + 1, [t, close, vol, oi] |
| A2 | consolidated bars sum OI/volume only where every listed expiry has the t | partial t → oi null |
| A3 | end-of-day answer | bars [] |
| B1 | ATM picked from the ref price; strikes = ATM ±5 listed strikes (fewer listed → fewer, said) | 11 strikes, CE+PE |
| B2 | series sums, changes, pcr; a t missing for one contract → null sums | as contract |
| B3 | token missing / expired / Kite failure | availability says so; no exception text leaked |
| B4 | nearest unexpired expiry; on expiry day after 15:30 still that day's contracts | expiry chosen |
| B5 | login reloaded before the Kite read; cache hit within TTL makes no Kite call | reload count, calls |
| B6 | bad interval / strikes > 8 | 400 / 422 |
| C1 | merges results/board, filings, corporate actions, macro, F&O expiry, FII/DII into one sorted list | kinds, dates |
| C2 | reaction: day %, next day %, gap %, volume × avg20 from daily bars; event after 15:30 → next session | numbers |
| C3 | future event or no bars → reaction null | null |
| C4 | one source fails → others still answer, sources lists the failure | 200 |
| C5 | today's event uses the Kite close bar, reaction.provisional true | flag |

### Staging (real data, read only, in-process before merge; deployed after merge)
| id | case | expected |
|---|---|---|
| S1 | ADANIPORTS oi-buildup intraday: bars per contract over 28–29 Oct with OI | values = Kite candles |
| S2 | ADANIPORTS options intraday: nearest expiry, ATM near 1,870, 22 contracts, series with pcr | data test vs Kite candle of 1 contract |
| S3 | ADANIPORTS chart events last 90 days: results date(s), filings, any corporate action, macro, expiries, FII/DII days | each source ok or why |
| S4 | a known results day's reaction equals the move computed from nidp.prices_eod_adjusted | equal |

### UI (Playwright, mocked API — MOCK, not real data)
| id | case | expected |
|---|---|---|
| P1 | futures pane: OI line + OI Δ bars coloured by build-up; slot chips switch the series | per-bar colour/data attrs |
| P2 | options pane: CE/PE OI Δ bars + PCR line; empty pane says why (token expired / no options) | testids, text |
| P3 | one readout for all panes at the hovered bar (keyboard ← →) | readout text |
| P4 | event glyphs on the price pane at the right bar; Events toggle hides them; events list with reaction numbers | glyph count, rows |
| P5 | daily fallback: futures/options panes say they need the day's Kite login; events still drawn | text |
| P6 | 390 px: panes stacked, no sideways scroll | layout |
