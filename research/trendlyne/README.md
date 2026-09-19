# Trendlyne MCP client with a Redis cache

Company-level data for in-depth analysis comes from the Trendlyne MCP server (owner rule, 2026-09-19). Everything it
serves is end-of-day or slower, so every response is cached in Redis and a value is fetched from Trendlyne at most once
per freshness window.

```python
import tl_cache as T
from tl_client import TLClient
cache = T.TLCache(TLClient(), T.RedisStore())          # redis://127.0.0.1:6380/2 (TL_REDIS_URL), keys "tl:v1:*"
data = cache.get_params(["APARINDS", "POLYCAB"], ["roea", "rocea", "prompct", "pettm"])   # {code: {param: value}}
cache.stats   # {'calls': MCP calls made, 'hits': cached values, 'misses': fetched values, 'rejected': ...}
```

| Data | Freshness class | Cached until |
|---|---|---|
| Price, volume, delivery, technicals, scores, PE/PEG/P/S, market cap | `eod` | next 07:00 IST |
| Shareholding, quarterly results, annual statements and ratios | `filing` | next 07:00 IST during filing season (day 1–60 after a quarter end), else 7 days |
| Entity search, parameter search, label map | `static` | 30 days (label map 90) |
| Document search / news | `docs` / `news` | 7 days / 1 hour |
| Stock codes Trendlyne cannot resolve | `neg` | 1 day |

- Bulk values are cached per (stock, parameter). A request fetches only the missing pairs, packed into as few calls as
  possible (server limit: 10 stocks × 50 parameters per call).
- One unresolvable stock code makes Trendlyne reject the whole batch; the cache records the bad code and retries the
  batch without it. Use NSE symbols, or ISINs for BSE-only stocks (numeric BSE codes failed).
- Calls are counted per day and month in Redis (`tl:v1:calls:YYYY-MM-DD`); `TL_DAILY_CALL_CAP` (default 800, Max plan 1,000/day) and `TL_MONTHLY_CALL_CAP` (default 9,000) stops
  calls before the plan limit.
- Parameter codes come from `cache.search_parameters("roe")`. Responses label values with display names ("ROE Ann. %"),
  so a verified code→label map is kept in Redis; a parameter whose label cannot be matched confidently is not cached.
- The server URL is the credential (`/app/.trendy-line-mcp-server.url`, mode 600). Never print or commit it.
- Trendlyne data is for internal research only; do not redistribute it.

Tests: `python -m pytest research/trendlyne -q` (fake Redis and fake server; no network).

## Daily history (archive) and the daily job
- Every response fetched from Trendlyne is appended to `TL_ARCHIVE_DIR/<YYYY-MM-DD>/param_values.jsonl.gz` (bulk
  values, with the raw labelled response) or `tool_responses.jsonl.gz` (overview, news, events, deals, lookups).
  Append-only, never rewritten; read with `tl_cache.read_archive(kind, start=..., end=...)`. The cache expires, the
  archive does not. `TLCache.restore(record)` rebuilds cache entries from an archived record without a call.
- Cron `/etc/cron.d/tl-daily` runs `/app/research/trendlyne/run_daily.sh` at 07:30 IST Mon–Sat (just after the 07:00
  end-of-day expiry) with a deployed copy of this code in `/app/research/trendlyne/bin/`: bulk parameters for the
  universe every run (~1 call per 10 stocks), per-stock views (overview incl. ASM status, events, bulk/block deals, news)
  daily (news, overview, deals; ~3 calls per stock); events and quarterly data only when the stock's news shows a new filing or event (7-day safety expiry). Writes `screens/<date>/screen.{csv,html}`. Logs: `/app/research/trendlyne/logs/`.
  Re-deploy after code changes: `install -m 644 research/trendlyne/{tl_client,tl_cache,screen_list,daily_archive}.py /app/research/trendlyne/bin/`.

## Top gainers of the day (Trendlyne's screener is not available through MCP)
`python top_gainers.py --index NIFTY500 --n 20` ranks every index member by day change from **one Kite `ohlc` call**
(live in market hours; the last session's full move otherwise — 498/498 matched the 18-Sep bhavcopy), then enriches
only the top N through the Trendlyne cache (bulk metrics, ASM status, latest headline; ~2 calls per new stock, 0 when
cached). Indices: NIFTY50/100/200/500, MIDCAP150, SMALLCAP250 (members from niftyindices.com, refreshed weekly).
Needs the day's Kite login. Output: `/app/research/trendlyne/gainers/<INDEX>_<date_time>_{all,top}.csv`.
