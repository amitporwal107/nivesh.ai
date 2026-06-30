"""
fetch_etf_prices.py

Pull current (delayed ~15min on the free tier) price data for US-listed
ETFs/stocks commonly used by Indian investors for international exposure
(the LRS-direct rows in nidp.international_investment_master), and either
export to CSV or upsert into nidp.international_etf_price so the International
Funds dashboard shows live-ish prices.

Requires: pip install yfinance pandas --break-system-packages
DB upsert additionally uses asyncpg (already a backend dependency) and reads
the POSTGRES_URL secret/env, same as services/pg_client.py.

Usage:
    python fetch_etf_prices.py                          # → CSV (default watchlist)
    python fetch_etf_prices.py --to-db                  # → upsert nidp.international_etf_price
    python fetch_etf_prices.py --to-db --no-csv         # DB only, skip CSV
    python fetch_etf_prices.py --tickers SPY,QQQ,VOO
    python fetch_etf_prices.py --tickers-file my_tickers.txt --out my_feed.csv
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

# Default watchlist: the LRS-direct US/global ETFs in the international master.
# Edit freely, or pass --tickers / --tickers-file.
DEFAULT_TICKERS = [
    "SPY",   # S&P 500
    "VOO",   # S&P 500 (Vanguard)
    "QQQ",   # Nasdaq-100
    "VTI",   # US Total Market
    "VXUS",  # Total International ex-US
    "VEA",   # Developed Markets ex-US
    "VWO",   # Emerging Markets
    "ARKK",  # ARK Innovation
    "SCHD",  # US Dividend
    "GLD",   # Gold
]

# Columns persisted to nidp.international_etf_price (must match the migration).
PRICE_FIELDS = [
    "ticker", "last_price", "currency", "previous_close", "day_high", "day_low",
    "year_high", "year_low", "volume", "market_cap", "exchange", "fetched_at_utc",
]


def load_tickers(args: argparse.Namespace) -> list[str]:
    if args.tickers:
        return [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    if args.tickers_file:
        with open(args.tickers_file) as f:
            return [line.strip().upper() for line in f if line.strip()]
    return DEFAULT_TICKERS


def fetch_prices(tickers: list[str]) -> pd.DataFrame:
    rows = []
    data = yf.Tickers(" ".join(tickers))

    for symbol in tickers:
        try:
            info = data.tickers[symbol].fast_info
            rows.append({
                "ticker": symbol,
                "last_price": info.get("last_price"),
                "currency": info.get("currency"),
                "previous_close": info.get("previous_close"),
                "day_high": info.get("day_high"),
                "day_low": info.get("day_low"),
                "year_high": info.get("year_high"),
                "year_low": info.get("year_low"),
                "volume": info.get("last_volume"),
                "market_cap": info.get("market_cap"),
                "exchange": info.get("exchange"),
                "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
        except Exception as e:
            print(f"  ! failed to fetch {symbol}: {e}", file=sys.stderr)
            rows.append({"ticker": symbol, "error": str(e)})

    return pd.DataFrame(rows)


_UPSERT_SQL = """
INSERT INTO nidp.international_etf_price
    (ticker, last_price, currency, previous_close, day_high, day_low,
     year_high, year_low, volume, market_cap, exchange, source, fetched_at)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,'yfinance',$12)
ON CONFLICT (ticker) DO UPDATE SET
    last_price     = EXCLUDED.last_price,
    currency       = EXCLUDED.currency,
    previous_close = EXCLUDED.previous_close,
    day_high       = EXCLUDED.day_high,
    day_low        = EXCLUDED.day_low,
    year_high      = EXCLUDED.year_high,
    year_low       = EXCLUDED.year_low,
    volume         = EXCLUDED.volume,
    market_cap     = EXCLUDED.market_cap,
    exchange       = EXCLUDED.exchange,
    source         = 'yfinance',
    fetched_at     = EXCLUDED.fetched_at
"""


def _num(v):
    """yfinance returns numpy scalars / None; coerce to plain float or None."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # drop NaN


async def _upsert(rows: list[dict]) -> int:
    import asyncpg
    url = os.environ.get("POSTGRES_URL")
    if not url:
        # Mirror pg_client's local fallback so a dev box "just works".
        url = "postgresql://postgres:postgres@localhost:5432/nivesh"
        print("POSTGRES_URL not set — using local default", file=sys.stderr)

    conn = await asyncpg.connect(url, statement_cache_size=0)
    n = 0
    try:
        for r in rows:
            if r.get("error") or r.get("last_price") is None:
                continue  # never write a fabricated/empty price
            fetched = r.get("fetched_at_utc")
            fetched_dt = datetime.fromisoformat(fetched) if isinstance(fetched, str) else datetime.now(timezone.utc)
            vol = r.get("volume")
            await conn.execute(
                _UPSERT_SQL,
                str(r["ticker"]).upper(),
                _num(r.get("last_price")), r.get("currency"),
                _num(r.get("previous_close")), _num(r.get("day_high")),
                _num(r.get("day_low")), _num(r.get("year_high")),
                _num(r.get("year_low")),
                int(vol) if vol is not None and _num(vol) is not None else None,
                _num(r.get("market_cap")), r.get("exchange"),
                fetched_dt,
            )
            n += 1
    finally:
        await conn.close()
    return n


def main():
    parser = argparse.ArgumentParser(description="Fetch US ETF/stock prices to CSV and/or nidp.international_etf_price")
    parser.add_argument("--tickers", help="Comma-separated tickers, e.g. SPY,QQQ,VXUS")
    parser.add_argument("--tickers-file", help="Path to a file with one ticker per line")
    parser.add_argument("--out", default="etf_price_feed.csv", help="Output CSV path")
    parser.add_argument("--to-db", action="store_true", help="Upsert into nidp.international_etf_price")
    parser.add_argument("--no-csv", action="store_true", help="Skip the CSV export (DB only)")
    args = parser.parse_args()

    tickers = load_tickers(args)
    print(f"Fetching prices for {len(tickers)} tickers: {', '.join(tickers)}")

    df = fetch_prices(tickers)

    if not args.no_csv:
        df.to_csv(args.out, index=False)
        print(f"Saved {len(df)} rows to {args.out}")

    if args.to_db:
        n = asyncio.run(_upsert(df.to_dict("records")))
        print(f"Upserted {n} priced rows into nidp.international_etf_price")

    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
