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
  "patterns": []                                                          // v1 batch 2: empty; filled by detectors
}
```

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
              "observed_values": {"close": 111.0, "breakout_level": 110.5, "body_pct": 0.87, "close_location": 0.92}}],
  "scores": null,                                    // §34.5: {formation, readiness, confirmation, failure_risk}, never summed
  "retest_quality": null                              // §35.2 amendment (N§13), descriptive only, null until PRICE_CONFIRMED:
                                                        // {"attempts": 1, "penetration_atr": 0.3, "penetration_pct": 1.1,
                                                        //  "retest_relative_volume": 0.85, "bars_confirmation_to_retest": 1,
                                                        //  "bars_retest_to_continuation": 2, "note": null}
}
```

## API (read-only) — `backend/routes/research_chart.py`, prefix `/api/research/chart`

| Endpoint | Returns | Errors |
|---|---|---|
| `GET /run` | manifest minus per-file hashes, plus `fixture` | 503 `snapshot_unavailable` |
| `GET /symbols` | `manifest.symbols` | 503 |
| `GET /{symbol}/ohlcv` | `{symbol, bars, data_quality_status, pit_status, findings, provenance}` — provenance from manifest.source + run_id + config_hash | 404 `unknown_symbol`, 503 |
| `GET /{symbol}/indicators?ids=a,b` | `{symbol, indicators:{id: {...}}}` (all if `ids` omitted) | 400 `unknown_indicator: <comma-separated unknown ids>`, 404, 503 |
| `GET /{symbol}/patterns` | `{symbol, patterns}` | 404, 503 |

Error codes are the token before any `: <detail>` suffix. All gated by `require_feature("charting")` → 403 `feature_not_enabled` for anyone not on the allowlist (admins
included, as the Lab does). Symbol path param validated `^[A-Z0-9&\-]{1,32}$`. A malformed or wrong-schema
snapshot → 503, never a partial response.

## Drawings (the only writable state) — `backend/routes/research_drawings.py`, prefix `/api/research/drawings`

Mongo collection `research_drawings`, PRD §7.3 record: `drawing_id, user_id, symbol, timeframe, drawing_type
(TRENDLINE|HORIZONTAL_LINE), anchor_points [{date, price}], style, created_at, updated_at`.
`POST` · `GET ?symbol=` · `PATCH /{id}` · `DELETE /{id}`. Every query filters by the caller's user_id; another
user's drawing → 404 (not 403, so ids don't leak). Same feature gate.
