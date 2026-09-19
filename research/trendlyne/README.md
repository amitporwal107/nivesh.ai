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
- Calls are counted per day and month in Redis (`tl:v1:calls:YYYY-MM-DD`); `TL_DAILY_CALL_CAP` (default 300) stops
  calls before the plan limit.
- Parameter codes come from `cache.search_parameters("roe")`. Responses label values with display names ("ROE Ann. %"),
  so a verified code→label map is kept in Redis; a parameter whose label cannot be matched confidently is not cached.
- The server URL is the credential (`/app/.trendy-line-mcp-server.url`, mode 600). Never print or commit it.
- Trendlyne data is for internal research only; do not redistribute it.

Tests: `python -m pytest research/trendlyne -q` (fake Redis and fake server; no network).
