# Market-data source switch

**What it is:** one switch that decides where Nivesh's market data comes from: our own feeds today, TrueData once it
is plugged in. Owner decision, 29 Oct 2026: one switch for everything, flipped by a config file in a pull request.
Once TrueData is plugged in, our own feeds that it replaces are switched off.

- **File:** `backend/config/market_data_source.json`
- **Code:** `backend/nidp/shared/market_data_source.py` (read by the NIDP jobs and by the app backend)
- **Check what each server will do:** `python -m nidp.shared.market_data_source` (prints the resolution)

## The three settings
| `source` | Who serves | Our replaced feeds | TrueData feeds |
|---|---|---|---|
| `current` (today) | our feeds | run | off |
| `shadow` | our feeds | run | run beside them, for comparison only |
| `truedata` | TrueData | **switched off** | run |

**Replaced feeds:**
- NIDP `index_close` and `corporate_actions`;
- the app's Kite live feed.

**Always kept: NSE's equity and F&O bhavcopies (`bhavcopy`, `fno_bhavcopy`).** They stay the record and the
cross-check. On the 29 Oct trial, TrueData's prices matched them exactly, but TrueData has:
- no raw (unadjusted) history: even a past day's bhavcopy comes back adjusted;
- no delisted securities;
- no F&O settlement price, previous close or series;
- no open interest for untraded contracts.

Option strikes and paper-trade history need raw prices.

**Also always kept**, because TrueData doesn't offer them: index constituents, FII/DII, bulk and block deals,
delivery, shareholding, the event calendar, mutual-fund feeds, and every other feed.

## What "switched off" does
- **NIDP ingester:** records a SKIPPED run with error class `SWITCHED_OFF` and the reason, so feed health shows why.
  It does not fetch.
- **feed_reconciler:** does not try to heal a switched-off feed.
- **dlq_redrive:** leaves that feed's entries PENDING, untouched.
- **Kite live feed:** not started.

## Safety: the file cannot switch our feeds off by mistake
The code steps down from what the file asks for whenever it cannot honour it, and records why:
1. `MARKET_DATA_SOURCE_FORCE_CURRENT=1` in a server's environment → `current`. This is the emergency way back without a
   PR.
2. `truedata` while TrueData is not integrated (`TRUEDATA_INTEGRATED = False` in the code, as shipped) → `shadow`.
   `shadow` does not need this gate: it never switches our feeds off, it only runs TrueData beside them for the
   data-quality checks.
3. No `TRUEDATA_USERNAME` / `TRUEDATA_PASSWORD` in the environment → `current`.
4. `truedata` without `"truedata_licence_confirmed": true` → `shadow`. TrueData's terms exclude simulation and display
   to third parties without SEBI and exchange approval; set the flag only after TrueData's written answer.

A missing or unreadable file means `current`.

## Going back to our current feeds (if we do not go with TrueData)
Owner, 29 Oct 2026: "if we are not going with TrueData we can switch it to the current implementation."
- **The normal way:** a PR that sets `"source": "current"` in `backend/config/market_data_source.json`. After the merge,
  the app backend uses it once it restarts, and the NIDP jobs use it once their dev checkout is refreshed.
- **The emergency way, no PR:** `MARKET_DATA_SOURCE_FORCE_CURRENT=1` in a server's environment (`nidp.env`,
  `.env.staging`). It wins over the file on that server.

What `current` gives back:
- every replaced feed runs again (`index_close`, `corporate_actions`, the Kite live feed);
- the reconciler and the DLQ re-drive heal them again;
- **nothing calls TrueData.** Every TrueData entry point checks `truedata_is_on()` before it does anything:

| TrueData entry point | At `current` |
|---|---|
| `services/providers/truedata_adapter.py` (app) | returns DQ_BLOCKED / NOT_CONFIGURED with `switched_off` and the reason; TrueData is not called |
| `python -m nidp.services.truedata_crosscheck` (NIDP) | prints verdict SWITCHED_OFF and exits 2; it reads neither the warehouse nor TrueData. With `--record` (the nightly cron) it records a SKIPPED run. `--evaluation` runs it anyway as a manual trial measurement |
| `services/truedata_live` (app: the live feed in shadow) | not started |
| TrueData ingesters (later PRs) | must follow the same rule (`truedata_is_on()` / `feed_is_on()`) |

The TrueData code can stay in the repository at `current`: it is inert there. NSE's own bhavcopies never stopped, so
there is no data gap to repair. Tests: SW-1 … SW-7 in `test_reports/truedata_client_TESTCASES.md`.

## Data-quality checks on TrueData (run in `shadow` and `truedata`)
Owner, 29 Oct 2026: "make sure we keep data quality checks on TrueData".

| Where | What it checks | Where results go |
|---|---|---|
| **Live feed in shadow** (`services/truedata_live`, app backend; one connection via a Mongo lease) | Connection: login, segments, symbol limit, login expiry, every symbol subscribed, heartbeat (15 s delayed, 60 s lost → reconnect). Every tick: price > 0, tick-size grid, circuit band, crossed book, OHLC consistency, day high/low and volume never going backwards, OI (negative, or 0 when it was positive), exchange time not in the future or backwards, sequence gaps, jumps, symbols going quiet. Once a minute: TrueData vs Kite on the same symbol (within one tick or 0.05% when both quotes are within 2 s), previous close, OI | Mongo `truedata_shadow` (status) and `truedata_shadow_minutes` (one document per minute, 30 days); `GET /api/live/truedata/status`; email/Telegram alerts (failed login, lost heartbeat in market hours, login expiring, Kite disagreeing on more than 5% of quotes) |
| **Nightly cross-check** (`python -m nidp.services.truedata_crosscheck --record`, weekdays 22:45 IST, `deploy/cloudpe/nidp/nidp-staging-truedata.cron`) | TrueData's bhavcopy vs NSE's files: every equity row (OHLC + volume), every traded F&O contract (close + OI), coverage. The known TrueData limit (OI above 2,147,483,647 reported as 0) is a WARN, not an alert | `nidp.job_log` + `source_registry` (feed status page), `nidp.validation_runs` / `validation_findings` (ingester `truedata_crosscheck`); alert on ERROR/CRITICAL |

**Turning the checks on (staging):**
1. TrueData logins in the server environments:
   - REST: `TRUEDATA_USERNAME` / `TRUEDATA_PASSWORD` on both servers (`nidp.env`, `.env.staging`);
   - WebSocket: `TRUEDATA_WS_USERNAME` / `TRUEDATA_WS_PASSWORD` / `TRUEDATA_WS_PORT` on the app server.
2. A PR setting `"source": "shadow"`. Our feeds keep serving; the app backend restart starts the live checks.
3. Install the cron file on the NIDP VM (see its header).

## Moving to TrueData
1. **TrueData replies** with documentation, trial credentials and a licence answer.
2. **Build and verify the TrueData side in a PR:**
   - EOD equity, F&O, index and corporate-action ingesters on `BaseIngester`, so they go through the same quality
     gates;
   - a live-quote adapter on the provider contract (`services/providers/contract.py`);
   - set `TRUEDATA_INTEGRATED = True` in that PR, once the trial scorecards pass.
3. **Store the credentials** in each server's environment (`nidp.env` on the NIDP VM, `.env.staging` on the app VM).
   This is the owner's step.
4. **PR:** `"source": "shadow"`. Both sources run; compare them for N days under the data-quality checks.
5. **PR:** `"source": "truedata"`, `"truedata_licence_confirmed": true`. Our replaced feeds go off.

Each merge to `dev` deploys the app. The NIDP jobs read the file from their dev checkout once it is refreshed.

## Not covered yet
- The AI scanner fetches its own NSE bhavcopy into `stock_ohlcv`. Like the NIDP bhavcopies, it stays on NSE's raw
  files. It is not under the switch.
- Kite stays the source for on-demand intraday candles and the instrument master, until the TrueData equivalents are
  built. TrueData's 1-minute history (back to Apr 2024) and symbol master (lot and tick size) are the planned
  replacements.
- TrueData live streaming: the trial REST login is refused on the WebSocket; a separate sandbox WebSocket login
  (50 symbols, until 5 Nov 2026) works. The TrueData live feed is the next PR, tested in market hours.
