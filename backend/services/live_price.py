"""Live Price Service — Fetches real-time prices for equity and ETF holdings from Yahoo Finance via NSE symbols."""

import csv
import io
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import httpx
import yfinance as yf

logger = logging.getLogger(__name__)

# In-memory caches
_isin_to_symbol: Dict[str, str] = {}
_isin_cache_ts: float = 0
_ISIN_CACHE_TTL = 86400  # 24 hours

_price_cache: Dict[str, dict] = {}
_price_cache_ts: float = 0
_PRICE_CACHE_TTL = 300  # 5 minutes

NSE_EQUITY_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
NSE_ETF_URL = "https://nsearchives.nseindia.com/content/equities/eq_etfseclist.csv"
NSE_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# Local fallback bundled in the repo so ISIN→symbol resolution still works
# when nsearchives is unreachable (sandboxes, restricted egress, weekends).
import os
_LOCAL_EQUITY_CSV = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "equity_list.csv")


def _load_isin_map_from_local() -> Dict[str, str]:
    """Read the bundled NSE equity master CSV and return ISIN→symbol.
    Header: SYMBOL, NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE,
            MARKET LOT, ISIN NUMBER, FACE VALUE."""
    mapping: Dict[str, str] = {}
    try:
        with open(_LOCAL_EQUITY_CSV, "r", encoding="utf-8", errors="ignore") as fp:
            reader = csv.reader(fp)
            next(reader, None)
            for row in reader:
                if len(row) >= 7:
                    sym = row[0].strip()
                    isin = row[6].strip()
                    if sym and isin:
                        mapping[isin] = sym
    except FileNotFoundError:
        logger.debug("Local equity_list.csv not found at %s", _LOCAL_EQUITY_CSV)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Local equity CSV read failed: {e}")
    return mapping


async def _load_isin_map() -> Dict[str, str]:
    """Download NSE equity + ETF master lists and build ISIN -> NSE symbol mapping."""
    global _isin_to_symbol, _isin_cache_ts

    if _isin_to_symbol and (time.time() - _isin_cache_ts) < _ISIN_CACHE_TTL:
        return _isin_to_symbol

    mapping: Dict[str, str] = {}
    async with httpx.AsyncClient(timeout=15, headers=NSE_HEADERS) as client:
        # Equity list: SYMBOL,NAME,SERIES,LISTING_DATE,PAID_UP,MARKET_LOT,ISIN,FACE_VALUE
        try:
            resp = await client.get(NSE_EQUITY_URL)
            if resp.status_code == 200:
                reader = csv.reader(io.StringIO(resp.text))
                next(reader, None)  # skip header
                for row in reader:
                    if len(row) >= 7:
                        symbol = row[0].strip()
                        isin = row[6].strip()
                        if isin.startswith("INE"):
                            mapping[isin] = symbol
                logger.info(f"Loaded {len(mapping)} equity ISIN mappings from NSE")
        except Exception as e:
            logger.warning(f"Failed to fetch NSE equity list: {e}")

        # ETF list: Symbol,Underlying,SecurityName,DateofListing,MarketLot,ISINNumber,FaceValue
        try:
            resp = await client.get(NSE_ETF_URL)
            if resp.status_code == 200:
                reader = csv.reader(io.StringIO(resp.text))
                next(reader, None)
                etf_count = 0
                for row in reader:
                    if len(row) >= 6:
                        symbol = row[0].strip()
                        isin = row[5].strip()
                        if isin and isin not in mapping:
                            mapping[isin] = symbol
                            etf_count += 1
                logger.info(f"Loaded {etf_count} ETF ISIN mappings from NSE")
        except Exception as e:
            logger.warning(f"Failed to fetch NSE ETF list: {e}")

    # Network fetch may fail in sandboxes / weekends — fall back to the
    # bundled equity_list.csv so resolution still works offline.
    if not mapping:
        local = _load_isin_map_from_local()
        if local:
            mapping = local
            logger.info(f"ISIN map loaded from local equity_list.csv ({len(mapping)} rows)")

    if mapping:
        _isin_to_symbol = mapping
        _isin_cache_ts = time.time()

    return _isin_to_symbol


def _batch_fetch_prices(symbols: List[str]) -> Dict[str, float]:
    """Fetch latest closing prices for a batch of NSE symbols using yfinance."""
    if not symbols:
        return {}

    nse_tickers = [f"{s}.NS" for s in symbols]
    prices: Dict[str, float] = {}

    try:
        # Batch download — single API call for all tickers
        ticker_str = " ".join(nse_tickers)
        data = yf.download(ticker_str, period="5d", progress=False, threads=True)

        if data.empty:
            return prices

        # Handle single vs multiple tickers (yfinance changes column structure)
        if len(nse_tickers) == 1:
            t = nse_tickers[0]
            sym = t.replace(".NS", "")
            if "Close" in data.columns:
                last_valid = data["Close"].dropna()
                if not last_valid.empty:
                    prices[sym] = round(float(last_valid.iloc[-1]), 2)
        else:
            for t in nse_tickers:
                sym = t.replace(".NS", "")
                try:
                    col = data["Close"][t]
                    last_valid = col.dropna()
                    if not last_valid.empty:
                        prices[sym] = round(float(last_valid.iloc[-1]), 2)
                except (KeyError, IndexError):
                    pass

    except Exception as e:
        logger.error(f"yfinance batch download failed: {e}")

    return prices


async def fetch_live_prices(holdings: List[dict]) -> Tuple[List[dict], dict]:
    """
    Fetch live prices for equity and ETF holdings.
    Returns (updated_holdings, stats_dict).
    Gold/SGB holdings are skipped (keep existing price).
    """
    global _price_cache, _price_cache_ts

    isin_map = await _load_isin_map()
    if not isin_map:
        logger.warning("ISIN map is empty — skipping live price fetch")
        return holdings, {"updated": 0, "failed": 0, "skipped": 0, "source": "none"}

    # Collect ISINs that need price updates (equity + ETF only)
    isins_to_fetch: Dict[str, str] = {}  # isin -> nse_symbol
    for h in holdings:
        asset_type = h.get("asset_type", "other")
        if asset_type not in ("equity", "etf"):
            continue
        isin = (h.get("ticker") or "").strip().upper()
        if not isin:
            continue
        nse_sym = isin_map.get(isin)
        if nse_sym:
            isins_to_fetch[isin] = nse_sym

    if not isins_to_fetch:
        return holdings, {"updated": 0, "failed": 0, "skipped": len(holdings), "source": "no_mapping"}

    # Check cache freshness
    use_cache = (time.time() - _price_cache_ts) < _PRICE_CACHE_TTL and _price_cache
    symbols_needed = list(set(isins_to_fetch.values()))

    if use_cache:
        # Only fetch symbols not in cache
        uncached = [s for s in symbols_needed if s not in _price_cache]
        if uncached:
            new_prices = _batch_fetch_prices(uncached)
            _price_cache.update({s: {"price": p, "ts": time.time()} for s, p in new_prices.items()})
        prices = {s: _price_cache[s]["price"] for s in symbols_needed if s in _price_cache}
    else:
        # Fetch all in batches of 50
        all_prices: Dict[str, float] = {}
        for i in range(0, len(symbols_needed), 50):
            batch = symbols_needed[i:i + 50]
            batch_prices = _batch_fetch_prices(batch)
            all_prices.update(batch_prices)

        _price_cache = {s: {"price": p, "ts": time.time()} for s, p in all_prices.items()}
        _price_cache_ts = time.time()
        prices = all_prices

    # Apply prices to holdings
    updated_count = 0
    failed_count = 0
    for h in holdings:
        asset_type = h.get("asset_type", "other")
        if asset_type not in ("equity", "etf"):
            continue
        isin = (h.get("ticker") or "").strip().upper()
        nse_sym = isins_to_fetch.get(isin)
        if nse_sym and nse_sym in prices:
            h["current_price"] = prices[nse_sym]
            h["price_source"] = "yahoo_finance"
            h["price_updated_at"] = datetime.now(timezone.utc).isoformat()
            h["nse_symbol"] = nse_sym
            updated_count += 1
        elif nse_sym:
            failed_count += 1

    return holdings, {
        "updated": updated_count,
        "failed": failed_count,
        "skipped": len(holdings) - updated_count - failed_count,
        "total_symbols": len(symbols_needed),
        "source": "yahoo_finance",
    }
