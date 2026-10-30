# Test cases: TrueData serves the live feed (`feat/truedata-serving`)

Owner, 30 Oct 2026:
- "Please switch completely to True data".
- Asked how, chose "Build the serving side now": everything behind the switch, tested on the 50-symbol sandbox. The final flip waits for TrueData's production login and the owner's licence decision.

Written before implementation.

## Design
**One seam, no change to the Kite feed.**
- `services/kite_live_feed/feed.py::LiveFeed` already takes its broker through injected factories:
  - `kite_factory(key, token)` → an object with `instruments(exchange)` and `quote(keys)`;
  - `ticker_factory(key, token)` → a `TickerSource`-like object that calls `on_tick(token, tick)` with Kite-shaped ticks.
- This PR adds `services/truedata_live/gateway.py`, which implements both against TrueData:
  - **`TrueDataAsKite.instruments("NSE" | "NFO")`** returns TrueData's symbol master (REST `getAllSymbols`) in Kite's instrument-row shape: `tradingsymbol`, `instrument_token`, `segment`, `instrument_type`, `name`, `expiry`, `strike`, `lot_size`, `tick_size`.
    - Symbols are written in **Kite's naming**, so every cache key, chain and screen keeps working unchanged:
      - stocks and indices: same name;
      - futures: `NIFTY26NOVFUT`;
      - monthly options: `NIFTY26NOV22900CE`;
      - weekly options: `NIFTY26N0322900CE`, with month codes 1–9, O, N, D.
    - TrueData's own name (`NIFTY26110322900CE`) is kept in a map for subscribing.
    - Dated futures come from TrueData's continuous rows (`NIFTY-I/-II/-III`, which carry the expiry).
  - **`TrueDataAsKite.quote(keys)`**: TrueData has no bulk quote on our plan (`getLTPBulk` is an add-on), so this answers `{}`. The feed's REST fallback then publishes no new quotes. The snapshot's age makes the screens read Delayed, never fresh.
  - **`TrueDataTicker`** has the `TickerSource` surface: `start`, `set_tokens`, `stop`, `healthy`, `connected`, `auth_failed`, `full_tokens`.
    - It runs TrueData's WebSocket in its own thread and subscribes by TrueData name, in the feed's priority order, up to the login's `maxsymbols`.
    - It turns `touchline` / `trade` / `bidask` into Kite ticks: `last_price`, `ohlc` (close = previous close), `volume_traded`, `oi`, `exchange_timestamp`, and `depth` (top of book).
    - **A crossed bid/ask is never published** (depth left out). It is counted.
    - It feeds every message to the existing data-quality checks (`TrueDataShadow` in a passive mode: no connection of its own and no Kite comparison, because Kite is off). They keep writing `truedata_shadow_minutes` and the status.
- **Wiring:** with `"source": "truedata"` effective, the backend starts `LiveFeed` with the TrueData factories and no Kite feed.
  - The token getter returns a non-secret marker when the WebSocket login is configured, so `not_connected` still means "no login".
  - No separate shadow connection is opened: one login allows one connection.
  - At `current` / `shadow` nothing changes.
- **`TRUEDATA_INTEGRATED` stays False in this PR.** The serving code is inert on every server until a later PR turns it on after the market-hours check (S-1).
- **Not in this PR:**
  - intraday candles from TrueData (next PR; REST bars were complete on 30 Oct);
  - the NIDP index-close and corporate-action loaders (next PR).
  - Margins and broker sign-in stay on Kite: TrueData has neither.

## Cases (unit, synthetic TrueData rows and messages: MOCK — not real data)
| ID | Case | Expected |
|---|---|---|
| TS-1 | NSE instruments from the master's EQ rows plus the configured indices | One row per EQ symbol: `segment` NSE, `instrument_type` EQ, `instrument_token` = TrueData `symbolid`, `tick_size` from the master. Index rows are `segment` INDICES under Kite's names (`NIFTY 50`, `NIFTY BANK`, `INDIA VIX`…). Other series (T0, BE…) are left out |
| TS-2 | NFO futures | `NIFTY-I` with expiry 2026-11-23 and lot 65 → `NIFTY26NOVFUT`, FUT, `name` NIFTY, expiry date, lot 65. Likewise -II and -III |
| TS-3 | Option names | NIFTY 3 Nov 2026 22900 CE (weekly) → `NIFTY26N0322900CE`. NIFTY 23 Nov 2026 (the month's last expiry, so monthly) → `NIFTY26NOV22900CE`. RELIANCE 1172.5 PE 23 Nov → `RELIANCE26NOV1172.5PE`. Month codes: Jan `1` … Sep `9`, Oct `O`, Nov `N`, Dec `D` |
| TS-4 | The universe code accepts the rows | `universe.fno_underlyings`, `near_month_futures`, `option_contracts` and `index_symbols` give the same structures they give for Kite rows of the same contracts |
| TS-5 | Ticks | A `trade` gives a Kite tick: `instrument_token`, `last_price`, `ohlc` {open, high, low, close = prev close}, `volume_traded`, `oi`, `exchange_timestamp` (aware IST), `depth.buy[0]` / `depth.sell[0]`. A `touchline` gives the same. A `bidask` updates only the depth of the symbol's last tick |
| TS-6 | Crossed book | A bid above the ask is not put in `depth`, and it is counted (CROSSED_BOOK) in the data-quality minute |
| TS-7 | Symbol limit and resubscribe | Subscribes the first `maxsymbols` tokens in the order given and lists the rest as over the limit. `set_tokens` adds and removes only the difference |
| TS-8 | Health | `healthy()` is False before the login reply, and after 60 s without a heartbeat or tick. A refused login sets `auth_failed`. A duplicate login ("already connected") is reported, never retried in a tight loop |
| TS-9 | LiveFeed end to end on the TrueData gateway (fake DB, fake WebSocket) | The snapshot has `source` ws and quotes under Kite names (`NIFTY 50`, `RELIANCE`, `NIFTY26NOVFUT`). The NIFTY option chain is in the cache index. Status `live`. No Kite factory is called |
| TS-10 | Switch wiring | `current` → Kite feed. `shadow` → Kite feed + shadow. `truedata` → TrueData-served `LiveFeed` only (no Kite feed, no second TrueData connection). With `TRUEDATA_INTEGRATED` False, `truedata` still resolves to `shadow` (existing MS tests) |
| TS-11 | Secrets | No WebSocket or REST password in logs, status, snapshot or minute documents |

## Market-hours check (S): needs the sandbox WebSocket, Mon 2 Nov – Wed 4 Nov
| ID | Case | Expected |
|---|---|---|
| S-1 | Throwaway container, `TRUEDATA_INTEGRATED` forced in process, in-memory DB, real Kite cache read for comparison | Login ok. Subscribed ≤ 50 (indices, near futures, NIFTY ATM options first). The snapshot's quotes agree with Kite's on ≥ 99% of comparable pairs. The NIFTY chain is built. No crossed book published |

## Verification plan
- pytest: the new gateway tests and the TS-9 end-to-end test, plus the existing `test_kite_live_feed.py`, `test_truedata_live.py` and switch suites (the Kite feed must be unchanged).
- S-1 in market hours, then a PR that sets `TRUEDATA_INTEGRATED = True`.
- The flip to `"source": "truedata"` waits for the production login and the owner's licence decision.
