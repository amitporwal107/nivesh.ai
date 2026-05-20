"""Fund Performance Service — fetches historical NAV from mfapi.in,
computes 1-year returns, and rates MF holdings against category-average benchmarks."""
import httpx
import logging
import time
import asyncio
from typing import Optional
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

MFAPI_BASE = "https://api.mfapi.in/mf"

# Cache: scheme_code -> {nav_1y_ago, nav_current, return_1y, category, ...}
_perf_cache = {}
_perf_cache_ts = 0
PERF_CACHE_TTL = 7200  # 2 hours


async def fetch_scheme_history(scheme_code: str) -> Optional[dict]:
    """Fetch scheme details + 1-year-ago NAV from mfapi.in."""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(f"{MFAPI_BASE}/{scheme_code}")
            if resp.status_code != 200:
                return None
            data = resp.json()

        meta = data.get("meta", {})
        nav_data = data.get("data", [])

        if not nav_data:
            return None

        current_nav = float(nav_data[0]["nav"])
        current_date = nav_data[0]["date"]

        # Find NAV closest to 1 year ago
        target_date = datetime.now(timezone.utc) - timedelta(days=365)
        nav_1y = None
        for entry in nav_data:
            try:
                d = datetime.strptime(entry["date"], "%d-%m-%Y")
                diff = abs((d - target_date.replace(tzinfo=None)).days)
                if diff < 15:  # Within 15 days of 1 year ago
                    nav_1y = float(entry["nav"])
                    break
            except (ValueError, KeyError):
                continue

        # Fallback: use entry ~250-370 trading days in
        if nav_1y is None and len(nav_data) > 250:
            try:
                nav_1y = float(nav_data[min(260, len(nav_data) - 1)]["nav"])
            except (ValueError, IndexError):
                pass

        return_1y = None
        if nav_1y and nav_1y > 0:
            return_1y = round(((current_nav - nav_1y) / nav_1y) * 100, 2)

        return {
            "scheme_code": scheme_code,
            "scheme_name": meta.get("scheme_name", ""),
            "fund_house": meta.get("fund_house", ""),
            "scheme_category": meta.get("scheme_category", ""),
            "scheme_type": meta.get("scheme_type", ""),
            "current_nav": current_nav,
            "current_date": current_date,
            "nav_1y_ago": nav_1y,
            "return_1y": return_1y,
        }
    except Exception as e:
        logger.warning("mfapi.in fetch failed for %s: %s", scheme_code, e)
        return None


async def compute_benchmark_ratings(holdings: list, nav_cache: dict) -> dict:
    """For all mutual fund holdings, compute 1Y returns via mfapi.in,
    then rate against category-average benchmark.

    Returns:
    {
        "fund_ratings": [...],  # Per-fund benchmark comparison
        "performance_distribution": {...},  # Pie chart data
        "category_overlap": [...],  # Bar graph data for sector/category overlap
        "summary": {...}
    }
    """
    mf_holdings = [h for h in holdings if h.get("asset_type") == "mutual_fund"]

    if not mf_holdings:
        return {
            "fund_ratings": [],
            "performance_distribution": {"overperforming": 0, "meeting": 0, "underperforming": 0},
            "category_overlap": [],
            "summary": {},
        }

    # Step 1: Get scheme_codes from our AMFI NAV cache
    scheme_code_map = {}  # holding_name -> scheme_code
    for h in mf_holdings:
        isin = (h.get("ticker") or "").upper().strip()
        name = h.get("name", "")
        entry = None

        if isin and isin in nav_cache:
            entry = nav_cache[isin]
        elif name:
            name_lower = name.lower().replace(" - ", " ").replace("  ", " ").strip()
            if name_lower in nav_cache:
                entry = nav_cache[name_lower]
            else:
                for key, val in nav_cache.items():
                    if isinstance(key, str) and not key.startswith("INF"):
                        if name_lower[:25] in key:
                            entry = val
                            break

        if entry and entry.get("scheme_code"):
            scheme_code_map[name] = entry["scheme_code"]

    # Step 2: Fetch historical data from mfapi.in (batch with rate limiting)
    scheme_data = {}
    codes_to_fetch = list(set(scheme_code_map.values()))

    # Limit to 20 concurrent requests to be respectful
    semaphore = asyncio.Semaphore(5)

    async def fetch_one(code):
        async with semaphore:
            result = await fetch_scheme_history(code)
            if result:
                scheme_data[code] = result
            await asyncio.sleep(0.2)  # Rate limit

    tasks = [fetch_one(code) for code in codes_to_fetch[:100]]
    await asyncio.gather(*tasks, return_exceptions=True)

    # Step 3: Group by category and compute category averages
    category_returns = {}  # category -> [return_1y, ...]
    for code, data in scheme_data.items():
        cat = data.get("scheme_category", "Other")
        if data.get("return_1y") is not None:
            category_returns.setdefault(cat, []).append(data["return_1y"])

    category_avg = {}
    for cat, returns in category_returns.items():
        if returns:
            category_avg[cat] = round(sum(returns) / len(returns), 2)

    # Step 4: Rate each fund
    fund_ratings = []
    over_count = 0
    meet_count = 0
    under_count = 0

    for h in mf_holdings:
        name = h.get("name", "")
        code = scheme_code_map.get(name)
        data = scheme_data.get(code) if code else None

        invested = h["quantity"] * h["buy_price"]
        current = h["quantity"] * h["current_price"]
        simple_return = round(((current - invested) / invested * 100), 2) if invested > 0 else 0

        rating = {
            "name": name[:60],
            "ticker": h.get("ticker", ""),
            "sector": h.get("sector", "Other"),
            "invested": round(invested, 2),
            "current_value": round(current, 2),
            "simple_return_pct": simple_return,
            "return_1y": None,
            "benchmark_return": None,
            "benchmark_name": None,
            "alpha": None,
            "rating": "no_data",  # overperforming / meeting / underperforming / no_data
            "scheme_category": None,
            "scheme_code": code,
        }

        if data and data.get("return_1y") is not None:
            cat = data.get("scheme_category", "Other")
            avg = category_avg.get(cat)
            rating["return_1y"] = data["return_1y"]
            rating["scheme_category"] = cat
            rating["benchmark_name"] = f"{cat} Avg"

            if avg is not None:
                rating["benchmark_return"] = avg
                rating["alpha"] = round(data["return_1y"] - avg, 2)

                # Threshold: ±2% for "meeting"
                if data["return_1y"] > avg + 2:
                    rating["rating"] = "overperforming"
                    over_count += 1
                elif data["return_1y"] < avg - 2:
                    rating["rating"] = "underperforming"
                    under_count += 1
                else:
                    rating["rating"] = "meeting"
                    meet_count += 1
            else:
                meet_count += 1
                rating["rating"] = "meeting"
        else:
            # Use simple return as fallback for display, but mark as no_data
            rating["return_1y"] = simple_return

        fund_ratings.append(rating)

    # Sort: overperforming first, then meeting, then underperforming
    rating_order = {"overperforming": 0, "meeting": 1, "underperforming": 2, "no_data": 3}
    fund_ratings.sort(key=lambda x: (rating_order.get(x["rating"], 3), -(x.get("return_1y") or 0)))

    # Step 5: Performance distribution pie chart
    best = sorted([r for r in fund_ratings if r.get("return_1y") is not None], key=lambda x: x["return_1y"], reverse=True)
    worst = sorted([r for r in fund_ratings if r.get("return_1y") is not None], key=lambda x: x["return_1y"])

    # Step 6: Category overlap bar chart data
    category_count = {}
    for h in mf_holdings:
        sector = h.get("sector", "Other")
        category_count.setdefault(sector, {"count": 0, "funds": [], "total_value": 0})
        category_count[sector]["count"] += 1
        category_count[sector]["funds"].append(h["name"][:40])
        category_count[sector]["total_value"] += h["quantity"] * h["current_price"]

    category_overlap = []
    for cat, data in sorted(category_count.items(), key=lambda x: x[1]["count"], reverse=True):
        category_overlap.append({
            "category": cat,
            "count": data["count"],
            "funds": data["funds"][:6],
            "total_value": round(data["total_value"], 2),
            "is_overlapping": data["count"] > 1,
        })

    # ── In-portfolio alternative finder ────────────────────────────────
    # For each underperforming holding, look up the best peer the user
    # already owns in the same scheme_category. Honest framing:
    #   - Only suggests funds the user already holds (no fabricated buys).
    #   - Uplift = (peer_return_1y − holding_return_1y) × current_value × 1%.
    #   - Confidence ladders down when return_1y is a fallback or peer alpha
    #     is small.
    # This contract is consumed by the dashboard Action Matrix (alternative
    # arrow on Review/Exit rows + aggregate "potential uplift ₹/yr" banner).
    enrich_with_alternatives(fund_ratings)
    total_uplift_per_year_rs = round(sum(
        (r.get("alternative") or {}).get("uplift_per_year_rs", 0) for r in fund_ratings
    ), 0)

    return {
        "fund_ratings": fund_ratings,
        "performance_distribution": {
            "overperforming": over_count,
            "meeting": meet_count,
            "underperforming": under_count,
            "no_data": len(mf_holdings) - over_count - meet_count - under_count,
        },
        "top_performers": [{"name": r["name"], "return_1y": r["return_1y"], "rating": r["rating"]} for r in best[:5]],
        "bottom_performers": [{"name": r["name"], "return_1y": r["return_1y"], "rating": r["rating"]} for r in worst[:5]],
        "category_overlap": category_overlap,
        "total_uplift_per_year_rs": total_uplift_per_year_rs,
        "summary": {
            "total_mf": len(mf_holdings),
            "matched": len(scheme_data),
            "categories": len(category_returns),
            "category_averages": category_avg,
        },
    }


# ── In-portfolio alternative finder ────────────────────────────────────
def enrich_with_alternatives(fund_ratings: list) -> None:
    """Mutates each rating in-place to attach an ``alternative`` dict when
    a better-performing peer exists in the user's portfolio under the same
    category. Pure logic — never raises; skips rows that lack the needed
    fields. See ``fund_performance.compute_benchmark_ratings`` for context.
    """
    # Group by scheme_category → list of (rating, return_1y, alpha)
    by_cat: dict = {}
    for r in fund_ratings:
        cat = r.get("scheme_category")
        ret = r.get("return_1y")
        if not cat or ret is None:
            continue
        by_cat.setdefault(cat, []).append(r)

    # Sort each category descending by return_1y
    for cat, peers in by_cat.items():
        peers.sort(key=lambda x: x.get("return_1y", 0), reverse=True)

    # Minimum alpha (peer − holding) to consider it a real improvement.
    # Below this, returns are noise and the UI must not nudge the user.
    MIN_ALPHA_PP = 1.0

    for r in fund_ratings:
        cat = r.get("scheme_category")
        ret = r.get("return_1y")
        if not cat or ret is None:
            continue
        peers = by_cat.get(cat, [])
        # Best peer in same category that is NOT this holding itself.
        best = next((p for p in peers if p.get("name") != r.get("name")), None)
        if not best:
            continue  # solo fund in this category
        peer_ret = best.get("return_1y")
        if peer_ret is None or peer_ret - ret < MIN_ALPHA_PP:
            continue  # no meaningful uplift

        current_val = r.get("current_value", 0) or 0
        uplift = round((peer_ret - ret) * current_val / 100.0, 0)
        if uplift <= 0:
            continue

        # Confidence ladder. HIGH only when both rows have category-grounded
        # return_1y AND uplift is materially above noise.
        if r.get("rating") in ("underperforming", "meeting") and best.get("rating") in ("overperforming", "meeting") and (peer_ret - ret) >= 3.0:
            conf = "HIGH"
        elif (peer_ret - ret) >= 1.5:
            conf = "MEDIUM"
        else:
            conf = "LOW"

        r["alternative"] = {
            "name": best.get("name"),
            "scheme_code": best.get("scheme_code"),
            "peer_return_1y": round(peer_ret, 2),
            "holding_return_1y": round(ret, 2),
            "alpha_pp": round(peer_ret - ret, 2),
            "uplift_per_year_rs": uplift,
            "confidence": conf,
        }
