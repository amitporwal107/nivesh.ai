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
- NIDP `bhavcopy` (equity EOD), `fno_bhavcopy`, `index_close` and `corporate_actions`;
- the app's Kite live feed.

**Always kept**, because TrueData doesn't offer them: index constituents, FII/DII, bulk and block deals, delivery,
shareholding, the event calendar, mutual-fund feeds, and every other feed.

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
2. TrueData not integrated (`TRUEDATA_INTEGRATED = False` in the code, as shipped) → `current`.
3. No `TRUEDATA_USERNAME` / `TRUEDATA_PASSWORD` in the environment → `current`.
4. `truedata` without `"truedata_licence_confirmed": true` → `shadow`. TrueData's terms exclude simulation and display
   to third parties without SEBI and exchange approval; set the flag only after TrueData's written answer.

A missing or unreadable file means `current`.

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
- The AI scanner fetches its own NSE bhavcopy into `stock_ohlcv`. It is not under the switch; it moves when the
  TrueData EOD ingester exists.
- Kite stays the source for on-demand intraday candles and the instrument master, until the TrueData equivalents are
  built.
