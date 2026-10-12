# Functionality Verification Report — Provider foundations (docs/charting.md §32 Phase A): Kite Connect + Trendlyne MCP

- **Branch:** feat/provider-foundations
- **Date:** 2026-10-12
- **Author:** Claude (full-stack developer + QA)
- **Environment:** staging (staging.niveshcopilot.com)
- **Changed areas:** backend routes/services: yes · frontend src: no

## Summary
§32 Phase A only: a normalized provider contract (§32.4), `KiteMarketDataAdapter` (instrument
master + chunked historical candles, on top of `nidp/services/kite_bars`), `TrendlyneResearchAdapter`
(MCP client over streamable HTTP: entity search, parameter search/values, corporate events, document
search), secret-free request/response logging, and the eight Phase A endpoints under
`/api/research/providers`. Reconciliation, PIT validation, provenance lookup and UI (Phases B–D) are
out of scope and not built.

## Test Cases
> Authored UP FRONT — after API design and the live Trendlyne schema probe, before implementation.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | contract | `ProviderResult.to_dict()` carries every §32.4 field | unit | all 13 fields present, timestamps ISO-8601 UTC | PASS |
| TC-2 | kite | No access token configured | failure | `AUTH_EXPIRED`, not retryable, no SDK call made | PASS |
| TC-3 | kite | SDK raises `TokenException` mid-fetch | failure | `AUTH_EXPIRED`, not retried | PASS |
| TC-4 | kite | SDK returns 429 twice then succeeds | failure | retried with backoff, result `OK`, 3 calls | PASS |
| TC-5 | kite | 429 on every attempt (retry exhaustion) | failure | `RATE_LIMITED`, retryable, attempts == max | PASS |
| TC-6 | kite | 6-year daily range | unit | split into ≤2000-day windows, one call each, rows merged in order | PASS |
| TC-7 | kite | Symbol not in instrument master | edge | `IDENTIFIER_NOT_RESOLVED`, no candle call | PASS |
| TC-8 | kite | Zero candles returned | edge | status `EMPTY`, `error_code=EMPTY_RESPONSE`, records `[]` (never read as zero) | PASS |
| TC-9 | kite | Same bar returned twice, identical | edge | deduplicated, finding `duplicate_bars=1`, status `OK` | PASS |
| TC-10 | kite | Same timestamp, different prices | failure | status `BLOCKED`, finding `conflicting_duplicates` | PASS |
| TC-11 | kite | Bar with high < low / non-positive price | failure | status `BLOCKED`, finding `invalid_ohlc` | PASS |
| TC-12 | kite | One window fails after retries, others succeed | failure | status `PARTIAL`, `error_code=PARTIAL_RESPONSE`, failed window listed | PASS |
| TC-13 | kite | Series metadata | unit | `series_type` EOD/INTRADAY, `price_adjustment=UNVERIFIED`, `session_completeness=UNCHECKED` | PASS |
| TC-14 | kite | Instrument sync | unit | normalized rows (token, symbol, exchange, segment, type); unsupported exchange → `INVALID_REQUEST` | PASS |
| TC-15 | trendlyne | MCP URL not configured | failure | `NOT_CONFIGURED`, no network call | PASS |
| TC-16 | trendlyne | `search_entities` pipe-table payload (recorded live response) | unit | records with name/nse_code/bse_code/isin/entity_type/sector/industry | PASS |
| TC-17 | trendlyne | `search_entities` returns `data: []` | edge | status `EMPTY`, `EMPTY_RESPONSE` | PASS |
| TC-18 | trendlyne | Query matches several companies | edge | all candidates returned, `meta.ambiguous=true`, adapter does not pick one | PASS |
| TC-19 | trendlyne | Parameter values payload (recorded live response) | unit | one record per stock × field with `validation_status=PIT_UNVERIFIED`, `point_in_time_validated=false`, `publication_timestamp=null` | PASS |
| TC-20 | trendlyne | Body `status: error … Could not resolve stock code [code:1012]` under HTTP 200 / `isError:false` | failure | `IDENTIFIER_NOT_RESOLVED` — not a success | PASS |
| TC-21 | trendlyne | >10 stock codes or >10 parameters | edge | `INVALID_REQUEST` before any network call | PASS |
| TC-22 | trendlyne | Tool missing from live `tools/list`, or its required args changed | failure | `TOOL_SCHEMA_CHANGED`, tool not called | PASS |
| TC-23 | trendlyne | Payload header/shape differs from the recorded one | failure | `INVALID_PAYLOAD` (or `TOOL_SCHEMA_CHANGED` for a changed table header), no records | PASS |
| TC-24 | trendlyne | Watchlist (account-mutating) tool requested | edge | refused — not in the read-only allowlist | PASS |
| TC-25 | trendlyne | HTTP 403 / 5xx / timeout / 429 | failure | `AUTH_EXPIRED` / `PROVIDER_UNAVAILABLE` (retryable) / `RATE_LIMITED` (retryable) | PASS |
| TC-26 | trendlyne | Corporate events payload (recorded live response) | unit | one record per table row tagged with its section; empty sections yield none; all `PIT_UNVERIFIED` | PASS |
| TC-27 | trendlyne | Document search payload (recorded live response) | unit | chunk records with document id/type/date and text; `PIT_UNVERIFIED` | PASS |
| TC-28 | secrets | Token in MCP URL / Kite access token | unit | never present in a result, a log record, an exception message or an API response | PASS |
| TC-29 | log | Every call, success or failure | unit | one `provider_requests` + one `provider_responses` doc; `raw_payload_reference` resolves; payload hash stored | PASS |
| TC-30 | api | Endpoints without session / without the `charting` flag | api | 401 / 403 `feature_not_enabled` | PASS |
| TC-31 | api | `GET /api/research/providers` | api | both providers with capabilities and configured-state, no secret values | PASS |
| TC-32 | api | Adapter failure surfaces through the route | api | HTTP 502/503/424-class with `{error_code, retryable, request_id}`; request still logged | PASS |
| TC-33 | api | Malformed symbol / interval / date range | edge | 400/422, no provider call | PASS |
| TC-34 | api (staging, live) | `POST …/trendlyne/search-entity` `{"query":"Infosys"}` | api | 200, INFY/INE009A01021 present | NOT RUN |
| TC-35 | api (staging, live) | `POST …/trendlyne/fetch-parameters` INFY, `pettm` | api | 200, record `PIT_UNVERIFIED` | NOT RUN |
| TC-36 | api (staging, live) | `POST …/kite/sync-instruments` | api | 200, NSE EQ instruments > 1000 | NOT RUN |
| TC-37 | api (staging, live) | `POST …/kite/fetch-candles` INFY daily, recent month | api | 200, bars match an independent source (`nidp.prices_eod`) for the same dates | NOT RUN |
| TC-38 | api (staging, live) | `GET …/providers/health` | api | each provider reports reachable/auth state truthfully | NOT RUN |
| TC-39 | data (staging) | `provider_requests` / `provider_responses` after TC-34..37 | data | one pair per call, no token substring anywhere in either collection | NOT RUN |

## API / Endpoint Tests (staging)
> **Staging endpoint tests have NOT been run** (TC-34..TC-39 are NOT RUN): the branch is not deployed
> to staging and Kite has no access token yet. What follows is real output from this session, but it
> is unit-level and adapter-level evidence, not staging-endpoint evidence.

- **pytest** (throwaway container from `nivesh/backend:staging`, working tree mounted read-only, `--network none`):
  - Command: `docker run --rm --network none -v /home/deploy/nivesh.ai:/work:ro -w /work/backend -e MONGO_URL=mongodb://localhost:27017 -e DB_NAME=unit_test -e OPENAI_API_KEY=unit-test-placeholder nivesh/backend:staging python -m pytest tests/test_research_providers.py nidp/tests/services/kite_bars tests/test_research_chart_layouts.py -q -p no:cacheprovider`
  - Output: `79 passed, 1 warning in 7.15s` (52 provider tests covering TC-1..TC-33, 12 kite_bars, 15 chart-layouts regression)
  - First run: `1 failed, 63 passed` — TC-26, board-meeting rows end with an empty cell; `_pipe_rows` fixed, not the assertion.
  - Result: PASS

- **Trendlyne adapter against the live MCP server** (same image, real network, URL on stdin; not via the staging API):
  ```
  health: {"provider_id": "trendlyne", "configured": true, "reachable": true, "error_code": null, "provider_version": "Trendlyne-Financial-Server/3.1.1", "tools_offered": 13}
  search_entity('Infosys'): status=OK error_code=None version=Trendlyne-Financial-Server/3.1.1 records=3
      {"name": "Infosys Ltd.", "nse_code": "INFY", "bse_code": "500209", "isin": "INE009A01021", "entity_type": "stock", "sector": "Software & Services", "industry": "IT Consulting & Software"}
  search_parameters('PE ratio'): status=OK error_code=None version=Trendlyne-Financial-Server/3.1.1 records=10
  fetch_parameters(INFY,TCS x pettm,roea): status=OK error_code=None version=Trendlyne-Financial-Server/3.1.1 records=4
      [{"instrument_identifier": "INFY", "field_name": "PE TTM", "parameter_token": "pettm", "value": 13.71, "as_of_period": "2026-10-12", "validation_status": "PIT_UNVERIFIED", "publication_timestamp": null}, ...
  fetch_events('INFY'): status=OK error_code=None version=Trendlyne-Financial-Server/3.1.1 records=191
      {"bonus": {"rows": 5, "curtailed": false}, "split": {"rows": 0, "curtailed": false}, "rights": {"rows": 0, "curtailed": false}, "dividend": {"rows": 51, "curtailed": false}, "boardMeeting": {"rows": 135, "curtailed": false}}
  search_documents: status=OK error_code=None version=Trendlyne-Financial-Server/3.1.1 records=15
  fetch_parameters(NOTASYMBOLXYZ): ProviderError code=IDENTIFIER_NOT_RESOLVED retryable=False message=Could not resolve stock code(s): NOTASYMBOLXYZ. [code:1012]
  search_entity('zzqxnotacompany123'): status=EMPTY error_code=EMPTY_RESPONSE records=0
  ```
  - Consistency check: the provider's own summary text in the same payload says "51 dividends" and "5 bonuses"; the parser produced 51 and 5 rows.
  - Result: PASS at adapter level. UNVERIFIED through `/api/research/providers/*` on staging.

- **Kite adapter against live Kite Connect** (same image, real network; key file and token file mounted read-only at the paths `kite_bars` reads, so the default credential path ran; not via the staging API):
  ```
  default_token(): present, len 32
  sync_instruments(NSE): status=OK records=10360 by_segment={'INDICES': 136, 'NSE': 10224}
     INFY row: {'instrument_token': 408065, 'exchange_token': '1594', 'tradingsymbol': 'INFY', 'name': 'INFOSYS', 'exchange': 'NSE', 'segment': 'NSE', 'instrument_type': 'EQ', 'lot_size': 1, 'tick_size': 0.05}
  fetch_candles(INFY day 2026-09-28..2026-10-12): status=OK error_code=None bars=10
     meta: {"series_type": "EOD", "price_adjustment": "UNVERIFIED", "session_completeness": "UNCHECKED", "includes_current_session": true, "windows_requested": 1, "failed_windows": [], "findings": {"duplicate_bars": 0, "conflicting_duplicates": 0, "invalid_ohlc": 0, "unreadable_rows": 0}}
     KITE 2026-10-01 1010.0 1035.0 999.15 1035.0 15166446
     KITE 2026-10-05 1050.0 1052.3 1010.0 1020.5 12126808
     KITE 2026-10-06 1018.0 1020.5 1003.15 1013.85 8252213
     KITE 2026-10-07 1006.0 1009.0 990.1 992.0 7493993
     KITE 2026-10-08 1002.0 1012.65 992.9 997.0 14847874
     KITE 2026-10-09 1007.3 1030.9 1007.3 1023.4 14094234
     KITE 2026-10-12 1029.3 1033.8 1010.65 1015.45 8050833
  fetch_candles(INFY day 2019-01-01..2026-10-12): status=OK bars=1929 windows=2 failed=[] findings={'duplicate_bars': 0, 'conflicting_duplicates': 0, 'invalid_ohlc': 0, 'unreadable_rows': 0} first=2019-01-01 last=2026-10-12
  fetch_candles(INFY 15minute 2026-10-09): status=OK bars=24 series_type=INTRADAY first=2026-10-09T09:15:00+05:30
  fetch_candles('NIFTY 50' index): status=OK bars=10 last_close=22363.35
  fetch_candles(NOSUCHSYM): ProviderError code=IDENTIFIER_NOT_RESOLVED retryable=False message=NSE:NOSUCHSYM is not in Kite's instrument master
  bad token: ProviderError code=AUTH_EXPIRED retryable=False message=TokenException: Incorrect `api_key` or `access_token`.
  ```
  - **Independent cross-check** — Trendlyne `get_stock_eod_ohlc(INFY, weekly)`, raw tool output from the same run:
    ```
    2026-10-12 open 1029.300 high 1033.800 low 1010.650 close 1020.000 volume 8429312
    2026-10-09 open 1007.300 high 1030.900 low 1007.300 close 1023.400 volume 14094234
    2026-10-08 open 1002.000 high 1012.650 low  992.900 close  997.000 volume 14847874
    2026-10-07 open 1006.000 high 1009.000 low  990.100 close  992.000 volume  7493993
    2026-10-06 open 1018.000 high 1020.500 low 1003.150 close 1013.850 volume  8252213
    2026-10-05 open 1050.000 high 1052.300 low 1010.000 close 1020.500 volume 12126808
    2026-10-01 open 1010.000 high 1035.000 low  999.150 close 1035.000 volume 15166446
    ```
    The six completed sessions (10-01 to 10-09) match Kite exactly on open, high, low, close and volume.
    **The current session (2026-10-12) disagrees**: close 1015.45 (Kite) vs 1020.00 (Trendlyne), volume 8,050,833 vs
    8,429,312, fetched ~18:05 IST. Cause not established. The Kite result flags this bar via
    `includes_current_session: true`; it must not be treated as final. `nidp.prices_eod` could not be used as the
    comparison source because the staging NIDP warehouse was rebuilt without market data.
  - Result: PASS at adapter level for completed sessions. UNVERIFIED through `/api/research/providers/kite/*` on staging.

## Findings from the live Trendlyne probe (2026-10-12)
- 13 tools offered; 4 mutate the account's watchlists. The adapter allowlists 5 read-only tools.
- Failures arrive as HTTP 200 / `isError:false` with `status: error … [code:1012]` in the body.
- `get_stock_parameter_values` limit is 10 stock codes x 10 parameters (its Args text says 50 parameters;
  the Limits line says 10). docs/charting.md §33.1 says "10 stocks x 50 parameters" — doc drift, not yet corrected.
- The host returns `403` to curl's default user-agent and `200` to `python-httpx` (WAF rule, not auth).
- `get_document_search_results.markdown_data` is a JSON string inside JSON (double-encoded).

## UI / Playwright Tests
Not applicable — no frontend source changed.

## Data Correctness (staging)
NOT RUN — `provider_requests` / `provider_responses` on staging have no rows from this feature yet (TC-39).

## Inputs required from user
- Kite `request_token` — received 2026-10-12 and exchanged (user_id WVX837, login 18:03 IST); access token in `.kite-access-token` (git-ignored, mode 600). Expires ~06:00 IST 2026-10-13.
- `TRENDLYNE_MCP_URL` — provided by the user and written to `/opt/nivesh-staging/.env.staging` with their authorization (backup `.env.staging.bak-20261012-trendlyne-mcp`). Not yet visible to the running backend (needs a container recreate).
- Kite API key/secret — provided in `.kite-api` (git-ignored). Not yet in the staging env as `BROKER_ZERODHA_API_KEY/SECRET`; awaiting the user's decision.
- Go-ahead to push `feat/provider-foundations` and check it out on the staging VM.

## Verdict: BLOCKED
