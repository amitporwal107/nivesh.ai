"""Yahoo Finance v8 chart API parser.

Endpoint:
    https://query1.finance.yahoo.com/v8/finance/chart/{TICKER}?period1=…&period2=…&interval=1d

Response shape:
    {
      "chart": {
        "result": [{
          "meta": {"symbol": "...", "exchangeTimezoneName": "...", ...},
          "timestamp": [unix_ts, ...],
          "indicators": {
            "quote": [{
              "open": [...], "high": [...], "low": [...],
              "close": [...], "volume": [...]
            }],
            "adjclose": [{"adjclose": [...]}]
          }
        }]
      }
    }

Pure function — bytes in, dicts out. No I/O.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def parse_yf_chart(body: bytes, *, symbol: str, series: str = "EQ") -> list[dict[str, Any]]:
    """Parse a YF chart-API JSON response into prices_eod-shaped rows.

    `symbol` is OUR canonical NSE symbol (without `.NS` suffix).
    `series` defaults to 'EQ'; YF doesn't expose series — caller supplies.
    """
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as e:
        raise ValueError(f"yf chart: invalid JSON ({e})") from e

    chart = payload.get("chart") or {}
    if chart.get("error"):
        # YF returns {"chart": {"result": null, "error": {...}}} on bad ticker
        raise ValueError(f"yf chart error: {chart['error']}")
    result = chart.get("result")
    if not result or not isinstance(result, list):
        return []
    entry = result[0]

    timestamps = entry.get("timestamp") or []
    quote_list = entry.get("indicators", {}).get("quote") or [{}]
    quote = quote_list[0] if quote_list else {}
    opens   = quote.get("open")   or []
    highs   = quote.get("high")   or []
    lows    = quote.get("low")    or []
    closes  = quote.get("close")  or []
    volumes = quote.get("volume") or []

    rows: list[dict[str, Any]] = []
    for i, ts in enumerate(timestamps):
        if ts is None:
            continue
        # YF timestamps are exchange-local epoch seconds at session open.
        # Use UTC date — YF aligns to NSE close so the date is correct.
        d = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()

        close_v = closes[i] if i < len(closes) else None
        # Skip rows where close is null (YF returns nulls on no-trade days)
        if close_v is None:
            continue

        rows.append({
            "as_of_date":  d,
            "symbol":      symbol.upper(),
            "series":      series,
            "isin":        None,
            "prev_close":  None,        # back-filled below
            "open_price":  opens[i]   if i < len(opens)   else None,
            "high_price":  highs[i]   if i < len(highs)   else None,
            "low_price":   lows[i]    if i < len(lows)    else None,
            "close_price": close_v,
            "last_price":  None,        # YF doesn't expose
            "avg_price":   None,        # ditto
            "volume":      int(volumes[i]) if i < len(volumes) and volumes[i] is not None else None,
            "turnover":    None,        # YF doesn't expose ₹ turnover; can derive from close*vol
            "trades":      None,
        })

    # Back-fill prev_close from previous row's close (within this batch).
    for i in range(1, len(rows)):
        rows[i]["prev_close"] = rows[i - 1]["close_price"]

    return rows


def epoch_range_for(start_iso: str, end_iso: str) -> tuple[int, int]:
    """Convert ISO date strings to YF's period1/period2 unix-second range."""
    s = datetime.strptime(start_iso, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    e = datetime.strptime(end_iso, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(s.timestamp()), int(e.timestamp())
