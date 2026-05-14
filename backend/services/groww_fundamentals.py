"""Groww Fundamentals Fetcher

Fetches real-time fundamental data for stocks from Groww.
Caches data in Redis with 24-hour expiry.
"""
import aiohttp
import logging
from typing import Dict, Any, Optional
import json
from services.redis_client import redis_client

logger = logging.getLogger(__name__)

GROWW_API_BASE = "https://groww.in/v1/api"
CACHE_EXPIRY_SECONDS = 86400  # 24 hours


async def fetch_stock_fundamentals(nse_symbol: str) -> Optional[Dict[str, Any]]:
    """Fetch stock fundamental data from Groww and cache in Redis.
    
    Args:
        nse_symbol: NSE symbol (e.g., "GABRIEL")
    
    Returns:
        {
            "pe_ratio": 58.18,
            "roe": 20.01,
            "debt_to_equity": 0.08,
            "market_cap": 14550,  # in crores
            "eps": 17.41,
            "pb_ratio": 11.39,
            "dividend_yield": 0.46,
            "52_week_high": 1388.0,
            "52_week_low": 528.4,
            "book_value": 88.89,
            "cached_at": "2026-04-19T08:50:00Z"
        }
    """
    redis = get_redis()
    cache_key = f"groww:fundamentals:{nse_symbol}"
    
    # Check Redis cache first
    try:
        cached = await redis.get(cache_key)
        if cached:
            logger.info("Cache HIT for %s", nse_symbol)
            return json.loads(cached)
    except Exception as e:
        logger.warning("Redis cache read failed for %s: %s", nse_symbol, e)
    
    # Cache MISS - fetch from Groww
    logger.info("Cache MISS for %s, fetching from Groww...", nse_symbol)
    
    try:
        # Groww stock detail endpoint
        url = f"{GROWW_API_BASE}/stocks_data/v1/accord_points/stock/{nse_symbol}"
        
        async with aiohttp.ClientSession() as session:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json"
            }
            
            async with session.get(url, headers=headers, timeout=10) as response:
                if response.status != 200:
                    logger.error("Groww API error for %s: %s", nse_symbol, response.status)
                    return None
                
                data = await response.json()
                
                # Parse fundamental data
                fundamentals = _parse_groww_data(data, nse_symbol)
                
                if fundamentals:
                    # Cache in Redis for 24 hours
                    try:
                        await redis.setex(
                            cache_key,
                            CACHE_EXPIRY_SECONDS,
                            json.dumps(fundamentals)
                        )
                        logger.info("Cached fundamentals for %s (24h TTL)", nse_symbol)
                    except Exception as e:
                        logger.warning("Redis cache write failed: %s", e)
                
                return fundamentals
    
    except aiohttp.ClientError as e:
        logger.error("HTTP error fetching %s: %s", nse_symbol, e)
        return None
    except Exception as e:
        logger.error("Unexpected error fetching %s: %s", nse_symbol, e)
        return None


def _parse_groww_data(data: Dict[str, Any], symbol: str) -> Optional[Dict[str, Any]]:
    """Parse Groww API response and extract fundamental metrics."""
    try:
        # Groww API structure (may vary)
        stock_data = data.get("stockData", {}) or data.get("data", {})
        
        # Extract key metrics
        fundamentals = {
            "nse_symbol": symbol,
            "pe_ratio": _safe_float(stock_data.get("peRatio")),
            "roe": _safe_float(stock_data.get("roe")),
            "debt_to_equity": _safe_float(stock_data.get("debtToEquity")),
            "market_cap": _safe_float(stock_data.get("marketCap")),
            "eps": _safe_float(stock_data.get("eps")),
            "pb_ratio": _safe_float(stock_data.get("pbRatio")),
            "dividend_yield": _safe_float(stock_data.get("dividendYield")),
            "52_week_high": _safe_float(stock_data.get("high52Week")),
            "52_week_low": _safe_float(stock_data.get("low52Week")),
            "book_value": _safe_float(stock_data.get("bookValue")),
            "industry_pe": _safe_float(stock_data.get("industryPE")),
            "face_value": _safe_float(stock_data.get("faceValue")),
        }
        
        # Remove None values
        fundamentals = {k: v for k, v in fundamentals.items() if v is not None}
        
        if len(fundamentals) > 2:  # At least some data beyond symbol
            from datetime import datetime, timezone
            fundamentals["cached_at"] = datetime.now(timezone.utc).isoformat()
            return fundamentals
        else:
            logger.warning("Insufficient fundamental data for %s", symbol)
            return None
    
    except Exception as e:
        logger.error("Error parsing Groww data for %s: %s", symbol, e)
        return None


def _safe_float(value: Any) -> Optional[float]:
    """Safely convert value to float, return None if invalid."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


async def bulk_fetch_fundamentals(nse_symbols: list[str]) -> Dict[str, Dict[str, Any]]:
    """Fetch fundamentals for multiple stocks in parallel.
    
    Args:
        nse_symbols: List of NSE symbols
    
    Returns:
        Dict mapping symbol to fundamentals
    """
    import asyncio
    
    tasks = [fetch_stock_fundamentals(symbol) for symbol in nse_symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    fundamentals_map = {}
    for symbol, result in zip(nse_symbols, results):
        if isinstance(result, dict):
            fundamentals_map[symbol] = result
        elif isinstance(result, Exception):
            logger.error("Failed to fetch %s: %s", symbol, result)
    
    return fundamentals_map


async def refresh_cache_for_user(user_id: str):
    """Refresh fundamental data cache for all user's stock holdings."""
    from deps import db
    
    # Get user's stock holdings
    holdings = await db.holdings.find({
        "user_id": user_id,
        "asset_type": "equity"
    }, {"_id": 0, "nse_symbol": 1}).to_list(200)
    
    symbols = [h["nse_symbol"] for h in holdings if h.get("nse_symbol")]
    
    if not symbols:
        logger.info("No stock holdings for user %s", user_id)
        return
    
    logger.info("Refreshing fundamentals for %s stocks", len(symbols))
    fundamentals_map = await bulk_fetch_fundamentals(symbols)
    logger.info("Successfully fetched %s/%s stocks", len(fundamentals_map), len(symbols))
    
    return fundamentals_map
