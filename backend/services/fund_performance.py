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


def _nav_return(current_nav: float, nav_data: list, days: int, trading_day_approx: int) -> Optional[float]:
    """Return % gain from `days` ago to today using the NAV history list (newest first).

    First tries to find an entry within ±15 days of the target date by calendar days.
    Falls back to the `trading_day_approx`-th entry in the list (newest-first ordering).
    Returns None when no usable NAV is found or the fund is younger than the period.
    """
    target = datetime.now(timezone.utc) - timedelta(days=days)
    nav_past = None
    for entry in nav_data:
        try:
            d = datetime.strptime(entry["date"], "%d-%m-%Y")
            if abs((d - target.replace(tzinfo=None)).days) < 15:
                nav_past = float(entry["nav"])
                break
        except (ValueError, KeyError):
            continue
    if nav_past is None and len(nav_data) > trading_day_approx:
        try:
            nav_past = float(nav_data[min(trading_day_approx, len(nav_data) - 1)]["nav"])
        except (ValueError, IndexError):
            pass
    if nav_past and nav_past > 0:
        return round(((current_nav - nav_past) / nav_past) * 100, 2)
    return None


async def fetch_scheme_history(scheme_code: str) -> Optional[dict]:
    """Fetch scheme details + multi-period NAV returns from mfapi.in.

    Returns return_1m, return_3m, return_1y, return_3y (any may be None if
    the fund doesn't have enough history for that period).
    """
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

        # Compute returns for each period (calendar days, trading-day fallback)
        return_1m  = _nav_return(current_nav, nav_data, days=30,   trading_day_approx=21)
        return_3m  = _nav_return(current_nav, nav_data, days=91,   trading_day_approx=63)
        return_1y  = _nav_return(current_nav, nav_data, days=365,  trading_day_approx=260)
        return_3y  = _nav_return(current_nav, nav_data, days=1095, trading_day_approx=780)

        return {
            "scheme_code": scheme_code,
            "scheme_name": meta.get("scheme_name", ""),
            "fund_house": meta.get("fund_house", ""),
            "scheme_category": meta.get("scheme_category", ""),
            "scheme_type": meta.get("scheme_type", ""),
            "current_nav": current_nav,
            "current_date": current_date,
            "return_1m":  return_1m,
            "return_3m":  return_3m,
            "return_1y":  return_1y,
            "return_3y":  return_3y,
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

    # Step 1: Fetch DaaS primitives by ISIN — correct, ISIN-based matching.
    # DaaS returns ret_1y / return_3m / return_1m / category_avg_1y already
    # computed from NIDP's own daily NAV ingestion (no name-matching, no stale
    # mfapi.in data).  We fall back to mfapi.in only for ISINs DaaS doesn't cover.
    isins = list({(h.get("ticker") or "").upper().strip() for h in mf_holdings
                  if (h.get("ticker") or "").strip()})
    daas_by_isin: dict = {}
    if isins:
        try:
            from services.copilot_tools import daas_client as _daas
            import feature_flags as _ff
            if _daas.is_configured() and _ff.is_enabled("v3_data_source_daas"):
                daas_by_isin = await _daas.get_v3_mf_primitives_bulk(isins) or {}
                logger.info("fund_performance: DaaS returned %d/%d primitives", len(daas_by_isin), len(isins))
        except Exception as e:
            logger.warning("fund_performance: DaaS fetch failed, using mfapi.in: %s", e)

    # Step 2: For ISINs not covered by DaaS, fall back to mfapi.in name matching.
    # Build scheme_code_map only for the uncovered holdings.
    daas_isins_covered = set(daas_by_isin.keys())
    mfapi_holdings = [h for h in mf_holdings
                      if (h.get("ticker") or "").upper().strip() not in daas_isins_covered]

    scheme_code_map = {}  # holding_name -> scheme_code (mfapi.in fallback only)
    for h in mfapi_holdings:
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

    # Fetch mfapi.in data only for the fallback set
    scheme_data = {}
    if scheme_code_map:
        semaphore = asyncio.Semaphore(5)

        async def fetch_one(code):
            async with semaphore:
                result = await fetch_scheme_history(code)
                if result:
                    scheme_data[code] = result
                await asyncio.sleep(0.2)

        codes_to_fetch = list(set(scheme_code_map.values()))
        await asyncio.gather(*[fetch_one(c) for c in codes_to_fetch[:100]], return_exceptions=True)

    # Step 3: Build category averages from DaaS (preferred) then mfapi.in
    category_returns = {}
    for prim in daas_by_isin.values():
        cat = prim.get("sub_category") or prim.get("category") or ""
        r1y = prim.get("ret_1y") or prim.get("return_1y")
        if cat and r1y is not None:
            try:
                category_returns.setdefault(cat, []).append(float(r1y))
            except (TypeError, ValueError):
                pass
    for data in scheme_data.values():
        cat = data.get("scheme_category", "Other")
        if data.get("return_1y") is not None:
            category_returns.setdefault(cat, []).append(data["return_1y"])

    category_avg = {cat: round(sum(v)/len(v), 2) for cat, v in category_returns.items() if v}

    # Step 4: Rate each fund
    fund_ratings = []
    over_count = 0
    meet_count = 0
    under_count = 0

    for h in mf_holdings:
        name = h.get("name", "")
        isin = (h.get("ticker") or "").upper().strip()
        # Prefer DaaS data (correct ISIN match); fall back to mfapi.in
        prim = daas_by_isin.get(isin)
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
            # simple_return_pct = total P&L since purchase (since-inception, NOT 1Y)
            # Used for "Since inception" period view; never put in return_1y.
            "simple_return_pct": simple_return,
            "return_1m":  None,
            "return_3m":  None,
            "return_1y":  None,
            "return_3y":  None,
            "benchmark_return": None,
            "benchmark_name": None,
            "alpha": None,
            "rating": "no_data",  # overperforming / meeting / underperforming / no_data
            "scheme_category": None,
            "scheme_code": code,
        }

        # Resolve period returns: DaaS (ISIN-matched, correct) → mfapi.in fallback
        # DaaS fields: ret_1y, return_3m, return_1m, return_6m, category_avg_1y
        # mfapi.in fields: return_1y, return_3m, return_1m, return_3y, scheme_category
        if prim is not None:
            r1y = prim.get("ret_1y") or prim.get("return_1y")
            cat = prim.get("sub_category") or prim.get("category") or ""
            if r1y is not None:
                rating["return_1m"]       = prim.get("return_1m")
                rating["return_3m"]       = prim.get("return_3m")
                rating["return_1y"]       = float(r1y)
                rating["return_3y"]       = prim.get("return_3y") or prim.get("return_3y_cagr")
                rating["scheme_category"] = cat
                rating["benchmark_name"]  = f"{cat} Avg" if cat else None
                # Use DaaS-provided category_avg_1y if available; else client-computed avg
                bm = prim.get("category_avg_1y") or category_avg.get(cat)
                if bm is not None:
                    rating["benchmark_return"] = float(bm)
                    rating["alpha"] = round(float(r1y) - float(bm), 2)
                    if float(r1y) > float(bm) + 2:
                        rating["rating"] = "overperforming"; over_count += 1
                    elif float(r1y) < float(bm) - 2:
                        rating["rating"] = "underperforming"; under_count += 1
                    else:
                        rating["rating"] = "meeting"; meet_count += 1
                else:
                    rating["rating"] = "meeting"; meet_count += 1
            # prim present but ret_1y missing → falls through to mfapi.in below

        if rating["return_1y"] is None and data and data.get("return_1y") is not None:
            # mfapi.in fallback for funds DaaS didn't cover
            cat = data.get("scheme_category", "Other")
            avg = category_avg.get(cat)
            rating["return_1m"]       = data.get("return_1m")
            rating["return_3m"]       = data.get("return_3m")
            rating["return_1y"]       = data["return_1y"]
            rating["return_3y"]       = data.get("return_3y")
            rating["scheme_category"] = cat
            rating["benchmark_name"]  = f"{cat} Avg"
            if avg is not None:
                rating["benchmark_return"] = avg
                rating["alpha"] = round(data["return_1y"] - avg, 2)
                if data["return_1y"] > avg + 2:
                    rating["rating"] = "overperforming"; over_count += 1
                elif data["return_1y"] < avg - 2:
                    rating["rating"] = "underperforming"; under_count += 1
                else:
                    rating["rating"] = "meeting"; meet_count += 1
            else:
                rating["rating"] = "meeting"; meet_count += 1

        if rating["return_1y"] is None:
            # No data from either source — leave return_1y=None so the fund is
            # excluded from period ranked lists (never substitute simple_return_pct).
            pass

        fund_ratings.append(rating)

    # Sort: overperforming first, then meeting, then underperforming; no_data last
    # Use -infinity as secondary key for no_data so None-return funds sort to bottom
    rating_order = {"overperforming": 0, "meeting": 1, "underperforming": 2, "no_data": 3}
    fund_ratings.sort(key=lambda x: (rating_order.get(x["rating"], 3), -(x.get("return_1y") if x.get("return_1y") is not None else float("-inf"))))

    # Step 5: Performance distribution + multi-period ranked lists
    def _ranked(field: str, reverse: bool = True) -> list:
        """Return fund ratings sorted by `field`, excluding funds with no data for that field."""
        return sorted(
            [r for r in fund_ratings if r.get(field) is not None],
            key=lambda x: x[field],
            reverse=reverse,
        )

    best  = _ranked("return_1y", reverse=True)
    worst = _ranked("return_1y", reverse=False)

    # Multi-period performer rows — same shape as top_performers but keyed by period
    def _performer_row(r: dict, field: str) -> dict:
        return {"name": r["name"], "return_pct": r.get(field), "period_field": field, "rating": r["rating"]}

    performers_by_period = {
        "inception": {
            "top":    [_performer_row(r, "simple_return_pct") for r in _ranked("simple_return_pct", True)[:10]],
            "bottom": [_performer_row(r, "simple_return_pct") for r in _ranked("simple_return_pct", False)[:10]],
        },
        "1Y": {
            "top":    [_performer_row(r, "return_1y") for r in _ranked("return_1y", True)[:10]],
            "bottom": [_performer_row(r, "return_1y") for r in _ranked("return_1y", False)[:10]],
        },
        "3M": {
            "top":    [_performer_row(r, "return_3m") for r in _ranked("return_3m", True)[:10]],
            "bottom": [_performer_row(r, "return_3m") for r in _ranked("return_3m", False)[:10]],
        },
        "1M": {
            "top":    [_performer_row(r, "return_1m") for r in _ranked("return_1m", True)[:10]],
            "bottom": [_performer_row(r, "return_1m") for r in _ranked("return_1m", False)[:10]],
        },
    }

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

    meeting = sorted(
        [r for r in fund_ratings if r.get("rating") == "meeting" and r.get("return_1y") is not None],
        key=lambda x: x["return_1y"],
        reverse=True,
    )

    return {
        "fund_ratings": fund_ratings,
        "performance_distribution": {
            "overperforming": over_count,
            "meeting": meet_count,
            "underperforming": under_count,
            "no_data": len(mf_holdings) - over_count - meet_count - under_count,
        },
        # Legacy fields (kept for backward compat — 1Y view)
        "top_performers":     [{"name": r["name"], "return_1y": r["return_1y"], "rating": r["rating"]} for r in best[:5]],
        "bottom_performers":  [{"name": r["name"], "return_1y": r["return_1y"], "rating": r["rating"]} for r in worst[:5]],
        "meeting_performers": [{"name": r["name"], "return_1y": r["return_1y"], "rating": r["rating"]} for r in meeting],
        # Multi-period ranked lists — keyed by "inception" | "1Y" | "3M" | "1M"
        # Each entry: {name, return_pct, period_field, rating}
        "performers_by_period": performers_by_period,
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
