# Chart snapshot contract — v1 (schema_version 1)

The offline engine (`research/charting/export.py`) WRITES this; the API (`backend/services/research_chart.py`) READS it;
the Charts tab renders what the API returns. Nothing is computed at request time — the Sim Lab rule
(`backend/routes/sim_lab.py`: "no DB, no network, no other file").

**Location:** `backend/services/research_chart_snapshot/` — must be under `backend/` because the backend image copies
only `backend/requirements.txt` and mounts `backend/` (`deploy/nivesh-app/Dockerfile.backend.prod:10,28`); `research/`
is not visible to the running API.

**Data licensing (NI-1):** contains Kite-derived prices. Served only behind `require_feature("charting")`
(owner allowlist). Never public.

## Files

```text
backend/services/research_chart_snapshot/
  manifest.json
  symbols/<SYMBOL>.json.gz      one per display symbol
```

## manifest.json

```json
{
  "schema_version": 1,
  "fixture": false,                     // true => synthetic dev data; the UI MUST show a loud banner
  "run_id": "chart_20260921T120000Z",
  "generated_at": "2026-09-21T12:00:00Z",
  "engine_version": "0.1.0",
  "profile": "PATTERN_CONFIRMATION_V1_RESEARCH",
  "config_hash": "<sha256 from research.charting.config.config_hash()>",
  "source": {
    "provider": "kite",
    "series": "daily",
    "adjustment_status": "ADJUSTED | UNADJUSTED | UNVERIFIED",
    "files": [{"name": "part-....csv.gz", "sha256": "..."}],
    "last_bar_date": "2026-09-18"
  },
  "universe_rule": "string describing the display-universe selection",

  // The controlled indicator preset catalogue this snapshot's series were built from (§38.5, D-3).
  // Written in full, so GET /catalogue serves the dialog straight off the snapshot and can never
  // describe a preset differently from the series that were actually computed. Adding a preset means
  // a new catalogue version and a re-export — never a runtime change.
  "indicator_catalogue": {
    "version": "1.0.0",
    "categories": ["trend", "momentum", "volatility", "volume"],
    "indicators": [
      {"indicator_id": "rsi", "name": "Relative strength index", "category": "momentum",
       "default_pane": "own", "output_fields": ["rsi"], "calculation_version": "...",
       "missing_data_policy": "...",
       "reference_bands": [{"value": 30.0, "label": "oversold"}, {"value": 70.0, "label": "overbought"}],
       "band_fill": {"from": 30.0, "to": 70.0},
       "presets": [{"preset_id": "rsi_14", "name": "RSI 14", "series_id": "rsi_14",
                    "parameters": {"period": 14}, "pane": "rsi_14", "plot_fields": null}]}
    ]
  },
  "indicator_catalogue_hash": "<sha256 over the normalised catalogue>",

  "symbols": [
    {"symbol": "RELIANCE", "n_bars": 1417, "first_date": "2021-01-01", "last_date": "2026-09-18",
     "data_quality_status": "VALID", "pit_status": "PIT_VALIDATED",
     "file": "symbols/RELIANCE.json.gz", "sha256": "<of the .gz file>", "n_patterns": 0}
  ]
}
```

## symbols/<SYMBOL>.json.gz

```json
{
  "symbol": "RELIANCE",
  "bars": [["2021-01-01", 1990.0, 2004.5, 1985.1, 1998.3, 5213456]],   // [date, open, high, low, close, volume], ascending
  "data_quality_status": "VALID",
  "pit_status": "PIT_VALIDATED",
  "findings": [{"date": "2022-03-01", "rule_id": "MISSING_CANDLE", "observed": {}}],
  "indicators": {
    "sma_20": {"contract": {"indicator_id": "sma_20", "parameters": {"n": 20}, "warmup_period": 20,
               "calculation_version": "1", "missing_data_policy": "..."},
               "pane": "price",                                         // "price" overlays candles; else its own pane
               "values": [["2021-01-29", 1995.2]]}                     // warmup bars omitted, never 0/NaN
  },
  // Multi-output indicators: each row is [date, ...values in contract.output_fields order], and
  // "plot_fields" lists which outputs the chart draws (absent = all). Example:
  // "bollinger": {"contract": {..., "output_fields": ["bb_mid","bb_upper","bb_lower","bb_width","bb_pos"]},
  //               "pane": "price", "plot_fields": ["bb_mid","bb_upper","bb_lower"],
  //               "values": [["2021-01-29", 933.0, 993.9, 872.2, 0.130, 0.047]]}
  "patterns": [],                                                         // v1 batch 2: empty; filled by detectors
  "timeframes": {                              // §38.7/§38.12 W2 -- display-only weekly/monthly
    "1W": {
      "bars": [["2021-01-08", 1990.0, 2050.0, 1980.0, 2020.0, 15000000, false]],
      // [date, open, high, low, close, volume, incomplete] -- ONE element longer than the daily
      // `bars` row (never confusable with it). `date` is the period's LAST session's date.
      // `incomplete: true` on exactly the newest bar of the whole series (never treat it as a
      // confirmed close) -- research/charting/resample.py's module docstring has the full rule.
      "indicators": { "sma_20": { "...": "same shape as the daily indicators map, computed by" } }
      // the SAME series.py functions run against the resampled 1W frame -- never re-derived in
      // the browser (§38.2, §8.7 contract).
    },
    "1M": { "bars": [ /* same 7-wide shape, one row per calendar month */ ], "indicators": { } }
  }
}
```

`timeframes` is written by `research/charting/resample.py` (weekly = NSE sessions grouped by ISO
week Monday-Friday; monthly = calendar months; holidays are simply absent -- no placeholder row is
ever synthesized for a non-trading day) and `research/charting/export.py` (§38.7). It is always
present with exactly the keys `1W` and `1M`; pattern detection stays daily-only, so `timeframes.*`
never carries a `patterns` key. `findings`/`data_quality_status`/`pit_status` are not duplicated
per timeframe -- they describe the underlying daily series regardless of which timeframe is
requested (`GET .../ohlcv?timeframe=1W` still reports the daily `data_quality_status`/`pit_status`,
but serves `findings: []`, since §9.1 findings are daily-session-indexed and have no 1:1 meaning on
a resampled bar).

Pattern objects (filled once detectors land; UI must render an empty list gracefully):

```json
{
  "pattern_id": "RELIANCE:RECTANGLE:2024-03-01",
  "pattern_type": "RECTANGLE", "direction": "BULLISH|BEARISH|NEUTRAL",
  "population": "CONFIRMED | EARLY",                 // §34.2: early (stages 1-3) never mixed with confirmed
  "status": "<§11 state>", "stage": "S1|S2|S3|null",
  "formation_start": "2024-01-10", "formation_end": "2024-03-01",
  "levels": {"support": 100.0, "resistance": 110.0, "breakout_level": 110.5, "invalidation_level": 99.5},
  "pivots": [{"date": "2024-01-15", "price": 110.0, "kind": "HIGH", "confirmed_date": "2024-01-18"}],
  "components": {"geometry": "PASS", "price": "PASS", "volume": "FAIL", "volatility": "PASS",
                 "market": "UNAVAILABLE", "sector": "UNAVAILABLE", "data_quality": "VALID"},
  "rules": [{"rule_id": "RECT_MIN_TOUCHES", "result": "PASS", "observed": 2, "threshold": 2}],
  "events": [{"date": "2024-03-01", "event_type": "PRICE_CONFIRMED", "rule_id": "CLOSE_ABOVE_BREAKOUT",
              "observed_values": {"close": 111.0, "breakout_level": 110.5}}],
  "scores": null                                     // §34.5: {formation, readiness, confirmation, failure_risk}, never summed
}
```

CANDLE-MOVE (2026-09-22, decisions-log #93/#110): breakout candle quality (`body_pct`,
`close_location`) and the pattern-level `retest_quality` block (§35.2 amendment, N§13) are
**not** part of this production pattern object -- they never appear in this snapshot. They
live only in the separate research enrichment record produced by
`research/charting/enrich.py`'s `enrich_pattern(pattern_dict, bars, t, benchmark_df=...)`,
keyed by `pattern_id`, computed point-in-time from this pattern object + bars (never
mutating it -- §37.6). That enrichment record is not currently written into this committed
snapshot (see `research/charting/export.py`, which calls `detect_as_of` directly and has no
`enrich_pattern` call site yet); it is a separate, forward-looking research artifact.

## API (read-only) — `backend/routes/research_chart.py`, prefix `/api/research/chart`

| Endpoint | Returns | Errors |
|---|---|---|
| `GET /run` | manifest minus per-file hashes, plus `fixture` | 503 `snapshot_unavailable` |
| `GET /symbols` | `manifest.symbols` | 503 |
| `GET /{symbol}/ohlcv?timeframe=1D\|1W\|1M` | `{symbol, timeframe, bars, data_quality_status, pit_status, findings, provenance}` — provenance from manifest.source + run_id + config_hash; `findings` is `[]` unless `timeframe=1D` (§9.1 findings are daily-indexed) | 400 `unknown_timeframe: <value>`, 404 `unknown_symbol`, 503 |
| `GET /{symbol}/indicators?timeframe=1D\|1W\|1M&ids=a,b` | `{symbol, timeframe, indicators:{id: {...}}}` (all if `ids` omitted) | 400 `unknown_indicator: <comma-separated unknown ids>`, 400 `unknown_timeframe: <value>`, 404, 503 |
| `GET /{symbol}/patterns` | `{symbol, patterns}` — daily only, no `timeframe` param (§38.7) | 404, 503 |

`timeframe` defaults to `1D` on both endpoints it appears on, so a caller that never passes it is
unaffected. Error codes are the token before any `: <detail>` suffix. All gated by
`require_feature("charting")` → 403 `feature_not_enabled` for anyone not on the allowlist (admins
included, as the Lab does). Symbol path param validated `^[A-Z0-9&\-]{1,32}$`. A malformed or wrong-schema
snapshot → 503, never a partial response.

## Drawings (the only writable state) — `backend/routes/research_drawings.py`, prefix `/api/research/drawings`

Mongo collection `research_drawings`, PRD §7.3 record: `drawing_id, user_id, symbol, timeframe, drawing_type
(TRENDLINE|HORIZONTAL_LINE), anchor_points [{date, price}], style, created_at, updated_at`.
`POST` · `GET ?symbol=` · `PATCH /{id}` · `DELETE /{id}`. Every query filters by the caller's user_id; another
user's drawing → 404 (not 403, so ids don't leak). Same feature gate.
