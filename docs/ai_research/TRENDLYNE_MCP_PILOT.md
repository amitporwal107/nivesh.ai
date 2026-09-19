# Trendlyne MCP — batch-limit pilot (2026-09-19)

**Answer: one bulk call returns at most 10 stocks × 50 parameters = 500 values.** Limits are enforced by the server
(error code 1012) and are not published on Trendlyne's help pages. Measured on server "Trendlyne-Financial-Server"
3.1.1, protocol 2025-06-18, through our own client (`/app/research/trendlyne/tl_mcp.py`). The server URL is the
credential and lives only in `/app/.trendy-line-mcp-server.url` (mode 600).

## The server exposes 12 tools, not the 5 documented
`search_entities` · `search_financial_parameters` · **`get_stock_parameter_values(stock_codes, parameters)`** ·
`get_parameter_values_multi_stock(query)` (semantic) · `get_ownership_deals_insider_sast(stock_code, type)` ·
`get_overview_news_corp_events(stock_code, type)` · `get_document_search_results(query)` · five watchlist tools.

## Batch test (every call logged in `/app/research/trendlyne/batch_test_log.csv`)
| test | stocks × params | result | time | bytes |
|---|---|---|---|---|
| T1 | 5 × 5 | 25 values | 0.41 s | 1,781 |
| T2 | 10 × 10 | 100 values (1 blank) | 0.50 s | 5,385 |
| T3 | **10 × 50** | **500 values** (25 blank) | 0.58 s | 22,185 |
| T4 | 11 × 10 | rejected: "Maximum 10 stock codes allowed per call" | 0.16 s | 337 |
| T5 | 25 × 10 | rejected (same) | 0.20 s | 337 |
| T6 | repeat of T2 | identical 5,385 bytes, 0.45 s — no visible caching effect | | |
| T7 | 10 × 61 | rejected: "Maximum 50 parameters allowed per call" | 0.17 s | 335 |
The tool's own description says "at most 10 … parameters" in one line and "1 to 50" in another; 50 works.

## What we learned
1. **One bad stock code rejects the whole batch** ("Could not resolve stock code(s)") — validate codes first.
2. **Numeric BSE codes failed** for two BSE-only stocks; their **ISINs worked**. Prefer NSE symbol, else ISIN.
3. **`search_entities` returns a text table**, not JSON; for BSE-only companies `nse_code` holds a number.
4. **Parameter codes** come from `search_financial_parameters` (10 per lookup); 143 codes cached in
   `params_catalog.json`, so repeat pulls need no lookups. There is no DII code: DII = institutional − FII, checked on
   GMM Pfaudler against the shareholding tool (32.81 − 14.39 = 18.42 = MF 16.52 + other institutions 1.90).
5. **Prices lag one session:** on Sat 19 Sep 09:40 IST, "LTP" equalled the 17 Sep close for 75 of 78 NSE stocks and the
   18 Sep close for none. Price-based fields (PE, 52-week distance, day change, RSI) are therefore as of 17 Sep.
6. **The semantic tool ignores named stocks**: asked for 12 named companies, it returned 10 other power stocks with
   unrequested parameters. Use it only for exploration.
7. `netdebta` (Net Debt Annual) came back empty for all 87 stocks.
8. No quota headers are returned; our client counted 52 tool calls for the whole pilot, 5 of them rejected. Whether
   rejected calls count against the quota is not visible to us — check the Trendlyne MCP page counter.

## Output
Owner's Screener list of 18 Sep (89 names): **87 pulled** (2 not in Trendlyne: Airfloa Rail, Horizon Reclaim), 50
parameters each + derived DII, 91% of cells filled → `/app/research/trendlyne/screener_20260918_trendlyne.csv`.
All 87 Trendlyne names match the Screener names. Steady-state cost for this list: **9 calls** (10 stocks per call).

## Cost model for planning
| job | calls |
|---|---|
| 100 stocks × 50 parameters | 10 |
| 1,000 stocks × 50 parameters | 100 |
| full company deep-dive (overview, technical, news, events, shareholding, SAST, deals, 2–5 document searches) | ~10–15 per company (estimate) |
Trendlyne data is for internal research only (the Trendlyne report PDF prohibits redistribution without consent).

## Caching (added 2026-09-19, owner request: no repeated calls for data that does not change intraday)
Code: `research/trendlyne/` (`tl_client.py`, `tl_cache.py`, 13 tests). Redis `nidp-redis` db 2, keys `tl:v1:*` (the
instance had no keys before; every key has an expiry). Bulk values are cached per (stock, parameter) with freshness
classes: `eod` until the next 07:00 IST; `filing` (shareholding, results, statements) daily during filing season, else
7 days; lookups 30 days; unresolvable codes 1 day. Missing pairs are packed into as few calls as possible.
Verified live: the full 87 × 50 request again → **0 calls** (4,350 hits); a new 3-stock request → 2 calls then 0 on
repeat; after packing, Siemens (half cached) + Waaree → 1 call then 0. Redis footprint 2.3 MB. Calls are counted in
Redis (55 on 2026-09-19) with a daily cap (`TL_DAILY_CALL_CAP`, default 300).
