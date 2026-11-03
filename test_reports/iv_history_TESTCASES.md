# F&O lab B2: daily IV history and regime history: test cases (authored before implementation)

Ask (2026-10-26): a daily implied-volatility (IV) history per F&O underlying and a regime history, so the Market Intelligence
screen can show IV rank, IV percentile and a regime timeline. Backend only.

Design (decided before the code):
- Mongo collection `fno_iv_history`, one document per (underlying, session): `_id` = `"<UNDERLYING>:<YYYY-MM-DD>"`,
  idempotent upsert. Inside, `buckets.near_month` and `buckets.next_month`: the 1st and 2nd futures expiries strictly
  after the session. Each row records `source`, `rate_pct`, `as_of`, `calc_version`, `method` (recorded | backfill) and,
  per bucket, the expiry, days to expiry, ATM strike, spot, the same-expiry future's settle price, the forward and
  how it was found, the call and put IV and the ATM IV (null with a `reason` when it cannot be worked out).
- The IV is the chain route's own calculation (routes/fno.py: shape_strikes, find_spot, atm_strike, model_summary,
  add_model, atm_iv on services/option_pricing Black-76). No second IV model.
- Past sessions are read from the data platform: DaaS `/v1/fno/{symbol}?on=YYYY-MM-DD` (nidp.fno_bhavcopy). A read whose
  day is not the day asked for is refused. A weekday with no rows (holiday, not loaded) is skipped and counted.
- `GET /api/fno/{symbol}/iv-history?days=N&bucket=near_month|next_month`: series oldest first, `sessions`, `current`;
  `iv_rank` and `iv_percentile` only with 252 or more sessions that have an IV, else null with a `reason`.
- `GET /api/macro/regime-history?days=N`: desk-regime-v1 recomputed per stored session from macro_daily (Nifty 50 close,
  India VIX), macro_features (50-session average; else the warehouse Nifty 50 closes, as /api/macro/today does) and
  stock_ohlcv breadth. Each point carries its rule version and the checks it could not make.

| ID | Case | Expected |
|----|------|----------|
| IV-1 | IV rank and IV percentile on a hand-worked window 10, 30, 12, 14, 11, 13 (current 13) | rank (13−10)/(30−10) = 15.0; percentile 3 of the 5 earlier sessions below 13 = 60.0 |
| IV-2 | A flat window (max = min) | rank null with a reason; percentile computed (0.0) |
| IV-3 | 251 sessions with an IV | `iv_rank` and `iv_percentile` null; `reason` names 251 sessions and the 252 needed; `sessions` = 251 |
| IV-4 | Exactly 252 sessions | rank and percentile present, worked over those 252 (window from/to/min/max reported) |
| IV-5 | More than 252 sessions | only the latest 252 sessions form the window; `sessions` counts them all |
| IV-6 | Sessions whose ATM IV is null | stored with their reason, shown in the series, not counted toward 252, never used as a value |
| IV-7 | The latest session has no IV | `current` is that session (IV null); rank and percentile null with a reason; no older IV passed off as current |
| IV-8 | The per-expiry ATM IV equals the chain route's `summary.atm_iv` on the same rows | identical figure, forward and basis (same model) |
| IV-9 | Near month and next month are the 1st and 2nd futures expiries strictly after the session | on an expiry day the expiring month is not used |
| IV-10 | Upserting the same session twice | one document; IV fields unchanged; `recorded_at` kept from the first write |
| IV-11 | A data-platform read fails (exception, 502, 404) for a session | nothing is written for that session; the recorder counts it as failed; never an IV of 0 |
| IV-12 | The data platform answers for another day than the one asked for | refused as a failed read; nothing written |
| IV-13 | A weekday with no F&O rows | skipped and counted as `no_rows`; nothing written; no interpolation |
| IV-14 | Route without a signed-in user | 401 `Not authenticated`; the store is not read |
| IV-15 | Route with nothing recorded | 200, `sessions` 0, `current` null, series [], a reason that says nothing is recorded |
| IV-16 | The IV store cannot be read | 502 `upstream_unavailable`, never an empty history |
| IV-17 | Bad symbol, `days` out of range, unknown bucket | 422 before the store is read |
| IV-18 | Each stored row carries source, rate_pct, as_of, calc_version, method, spot, future settle, forward, forward_basis | all present (null only when not worked out) |
| IV-19 | The F&O router's route list | adds only `GET /api/fno/{symbol}/iv-history`; still read only apart from the margin calculation |
| RG-1 | Regime history over stored sessions with every input | one point per session, oldest first, each with `rule_version` desk-regime-v1, the key the rule gives, no skipped checks |
| RG-2 | A session without India VIX | point keeps its trend regime; `skipped` names high_volatility; the summary counts it |
| RG-3 | A session without a 50-session average in macro_features | the warehouse Nifty 50 closes are used (same rule as /today) and the point names that source |
| RG-4 | A session where neither store has the trend inputs | key null with the reason; counted as unclassified; never a default regime |
| RG-5 | Breadth read fails for a session | the mixed check is skipped with the error named; other points unaffected |
| RG-6 | macro_daily rows without a Nifty close in the span | not treated as sessions; counted in `non_session_rows` |
| RG-7 | The macro store cannot be read | 502, never an empty history |
| RG-8 | Route without a signed-in user | 401; nothing read |
| RG-9 | `days` out of range | 422 |
| RG-10 | /api/macro/today's regime is unchanged by the shared warehouse helper | existing desk overview tests still pass |
| ALL-1 | Whole app imports (`python -c "import server"`) in the staging image | exit 0 |
| ALL-2 | Existing F&O and macro tests | still pass |
