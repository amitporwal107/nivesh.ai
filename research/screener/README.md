# Local screener + model validation

**Screens** (`screens.json`, declarative: universe, filter, sort, fields) run on one market snapshot:
- live / latest session: Kite `quote` for the whole universe (Nifty 500 = 2 calls). Outside market hours Kite zeroes
  volume and VWAP, so those come from the official NSE bhavcopy.
- any past session: `--session YYYY-MM-DD` uses the official NSE bhavcopy only (no Kite; no price-band limits).

```
python screener.py list
python screener.py run gainers --X 5                  # Nifty 500, daily return > 5%, sorted desc
python screener.py all --session 2026-09-18           # every screen from the bhavcopy
python validate_model.py --session 2026-09-18         # v4 forward predictions vs actual outcomes
```
Screens: gainers, losers, high_touch (the v4 outcome: day high >= +X% over the previous close), faded_highs (touched +X%
but gave it back), strong_close, liquid_gainers, gap_up, gap_down (the H-A/H-B signal), upper/lower_circuit, value_leaders.

**Validation** scores the v4 forward predictions made the evening before a session against its official bhavcopy:
selected-5 hits (with close-to-close return — movement is not direction), precision and lift at top 10/20/50, recall,
AUC, Brier score and decile calibration; one row per target is appended to `validation/ledger.csv`.

Verified on 18 Sep: Kite last price, open, high, low = bhavcopy for 498/498; traded value = independent EOD file
within 0.1% for 498/498. Caveat: NSE's previous close is not adjusted on ex-dates (false moves on those days).
Data: Kite and NSE data for internal use only. Outputs under `/app/research/screener/` (snapshots, results, validation).
Evening job: `/etc/cron.d/screener-evening` → `/app/research/screener/run_evening.sh` (19:30 IST Mon–Fri, retry 21:30).
