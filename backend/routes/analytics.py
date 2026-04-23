"""Analytics routes: portfolio analytics, deep analytics, fund performance, simulations."""
from fastapi import APIRouter, HTTPException, Request
from datetime import datetime, timezone, timedelta
import hashlib
import json
import logging

from deps import db, get_current_user
from services import compute_risk_analysis, generate_recommendations, simulate_optimized_portfolio
from services import portfolio_health as ph_svc
from services.amfi_nav import fetch_nav_data, update_holdings_nav, lookup_nav
from services.fund_performance import compute_benchmark_ratings
from services.live_price import fetch_live_prices
from services.sgb_prices import apply_sgb_issue_prices
from services.equity_sectors import enrich_holdings_with_sectors
from helpers.portfolio_utils import extract_fund_house, compute_fund_overlap
from deps import ai_engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.get("/portfolio/analytics")
async def get_analytics(request: Request, portfolio_id: str = ""):
    user = await get_current_user(request)
    query = {"user_id": user["user_id"]}
    if portfolio_id:
        query["portfolio_id"] = portfolio_id
    holdings = await db.holdings.find(query, {"_id": 0}).to_list(2000)

    # Update mutual fund holdings with live NAV from AMFI
    holdings = await update_holdings_nav(holdings)
    for h in holdings:
        if h.get("nav_source") == "AMFI" and h.get("holding_id"):
            await db.holdings.update_one(
                {"holding_id": h["holding_id"]},
                {"$set": {"current_price": h["current_price"], "nav_date": h.get("nav_date", ""), "nav_source": "AMFI"}}
            )

    # Update equity and ETF holdings with live prices
    holdings, live_price_stats = await fetch_live_prices(holdings)
    for h in holdings:
        if h.get("price_source") == "yahoo_finance" and h.get("holding_id"):
            await db.holdings.update_one(
                {"holding_id": h["holding_id"]},
                {"$set": {
                    "current_price": h["current_price"],
                    "price_source": "yahoo_finance",
                    "price_updated_at": h.get("price_updated_at", ""),
                    "nse_symbol": h.get("nse_symbol", ""),
                }}
            )

    # Apply SGB issue prices
    holdings, sgb_updated = apply_sgb_issue_prices(holdings)
    for h in holdings:
        if h.get("price_source_buy") == "rbi_sgb_mapping" and h.get("holding_id"):
            await db.holdings.update_one(
                {"holding_id": h["holding_id"]},
                {"$set": {
                    "buy_price": h["buy_price"],
                    "sgb_series": h.get("sgb_series", ""),
                    "sgb_issue_date": h.get("sgb_issue_date", ""),
                    "price_source_buy": "rbi_sgb_mapping",
                }}
            )

    # Enrich equity holdings with proper sectors
    holdings = enrich_holdings_with_sectors(holdings)
    for h in holdings:
        if h.get("sector") != "Other" and h.get("holding_id"):
            await db.holdings.update_one(
                {"holding_id": h["holding_id"]},
                {"$set": {"sector": h["sector"]}}
            )

    if not holdings:
        return {
            "total_invested": 0, "current_value": 0, "total_returns": 0,
            "returns_pct": 0, "asset_allocation": [], "sector_exposure": [],
            "risk_score": 0, "risk_label": "N/A", "holdings_count": 0,
            "top_gainers": [], "top_losers": []
        }

    total_invested = 0
    current_value = 0
    asset_map = {}
    sector_map_equity = {}
    holding_perf = []
    missing_cmp_count = 0
    assumed_cost_count = 0

    for h in holdings:
        buy_p = h["buy_price"] if h["buy_price"] > 0 else h["current_price"]
        inv = h["quantity"] * buy_p
        cur = h["quantity"] * h["current_price"]
        total_invested += inv
        current_value += cur

        if h["buy_price"] > 0 and abs(h["buy_price"] - h["current_price"]) < 0.01:
            missing_cmp_count += 1
        if h["buy_price"] == 0 or (h.get("source") == "cas" and abs(h["buy_price"] - h["current_price"]) < 0.01):
            assumed_cost_count += 1

        at = h.get("asset_type", "other")
        asset_map[at] = asset_map.get(at, 0) + cur

        if at == "equity":
            sec = h.get("sector", "Other")
            sector_map_equity[sec] = sector_map_equity.get(sec, 0) + cur

        pct_change = ((cur - inv) / inv * 100) if inv > 0 else 0
        holding_perf.append({"name": h["name"], "pct_change": round(pct_change, 2), "value": cur, "asset_type": h.get("asset_type", "other")})

    total_returns = current_value - total_invested
    returns_pct = (total_returns / total_invested * 100) if total_invested > 0 else 0

    asset_allocation = [{"name": k, "value": round(v, 2)} for k, v in asset_map.items()]
    sector_exposure = [{"name": k, "value": round(v, 2)} for k, v in sector_map_equity.items()]

    # Risk scoring
    risk_score = 0
    if len(holdings) < 3:
        risk_score += 30
    elif len(holdings) < 5:
        risk_score += 15

    if asset_allocation:
        max_asset_pct = max(a["value"] for a in asset_allocation) / current_value * 100 if current_value > 0 else 0
        if max_asset_pct > 80:
            risk_score += 30
        elif max_asset_pct > 60:
            risk_score += 20
        elif max_asset_pct > 40:
            risk_score += 10

    if sector_exposure:
        max_sector_pct = max(s["value"] for s in sector_exposure) / current_value * 100 if current_value > 0 else 0
        if max_sector_pct > 50:
            risk_score += 25
        elif max_sector_pct > 30:
            risk_score += 15

    equity_val_total = (asset_map.get("equity", 0) + asset_map.get("mutual_fund", 0) + asset_map.get("etf", 0))
    equity_pct = equity_val_total / current_value * 100 if current_value > 0 else 0
    if equity_pct > 80:
        risk_score += 15

    risk_score = min(risk_score, 100)
    risk_label = "Low" if risk_score < 30 else "Moderate" if risk_score < 60 else "High"

    holding_perf.sort(key=lambda x: x["pct_change"], reverse=True)
    top_gainers = holding_perf[:10]
    top_losers = list(reversed(holding_perf[-10:])) if len(holding_perf) > 10 else []

    # Heatmap data
    heatmap_data = []
    for h in holdings:
        inv = h["quantity"] * h["buy_price"]
        cur = h["quantity"] * h["current_price"]
        pct = ((cur - inv) / inv * 100) if inv > 0 else 0
        if cur > 0:
            heatmap_data.append({
                "name": h["name"][:30],
                "ticker": h.get("ticker", ""),
                "value": round(cur, 2),
                "invested": round(inv, 2),
                "return_pct": round(pct, 1),
                "asset_type": h.get("asset_type", "other"),
                "sector": h.get("sector", "Other"),
            })
    heatmap_data.sort(key=lambda x: x["value"], reverse=True)

    # Simulated performance trend
    trend = []
    base = total_invested if total_invested > 0 else current_value * 0.9
    for i in range(30):
        day_offset = 29 - i
        d = datetime.now(timezone.utc) - timedelta(days=day_offset)
        day_hash = int(hashlib.sha256(d.strftime("%Y-%m-%d").encode()).hexdigest()[:8], 16)
        noise = ((day_hash % 1000) / 1000.0 - 0.5) * 0.03
        progress = (30 - day_offset) / 30
        modeled = base + (total_returns * progress) + (noise * current_value)
        trend.append({
            "date": d.strftime("%b %d"),
            "value": round(max(modeled, base * 0.85), 0),
        })
    if trend:
        trend[-1]["value"] = round(current_value, 0)

    # Simulated day change
    today_hash = int(hashlib.sha256(datetime.now(timezone.utc).strftime("%Y-%m-%d").encode()).hexdigest()[:8], 16)
    day_pct = ((today_hash % 2000) / 2000.0 - 0.5) * 0.04
    day_change = round(current_value * day_pct, 2)
    day_change_pct = round((day_change / current_value * 100) if current_value > 0 else 0, 2)

    # Data quality flags
    data_flags = {
        "day_change_simulated": True,
        "performance_trend_simulated": True,
        "missing_cmp_count": missing_cmp_count,
        "assumed_cost_count": assumed_cost_count,
        "total_holdings": len(holdings),
        "sector_exposure_equity_only": True,
        "explanations": {
            "day_change": "Day change is simulated. Real-time market data feed is not connected.",
            "performance_trend": "The 30-day trend is modeled, not based on actual historical portfolio values.",
            "risk_score": f"Risk Score ({risk_score}/100): Based on concentration, diversity, sector concentration, equity overweight ({equity_pct:.0f}%).",
            "health_diversification": "Diversification: HHI concentration, asset types, sector spread.",
            "health_risk": "Risk Management: Inverse of raw risk score.",
            "health_cost": "Cost Efficiency: Regular vs Direct plan penalty.",
            "health_performance": "Performance: Based on overall portfolio return %.",
            "health_overall": "Overall Health = 30% Diversification + 25% Risk + 20% Cost + 25% Performance.",
            "sector_exposure": "Sector exposure is for equity holdings only.",
            "missing_cmp": f"{missing_cmp_count} holdings have CMP equal to Buy Price.",
        }
    }

    # ── Unified Portfolio Health (source of truth: services/portfolio_health.py) ──
    try:
        hr = await ph_svc.build_portfolio_health(user["user_id"])
        comps = hr.components or {}
        health_payload = {
            "overall": round(hr.health_score or 0),
            "grade": hr.grade,
            "diversification": round((comps.get("diversification").score if comps.get("diversification") else 0)),
            "risk":             round((comps.get("risk").score            if comps.get("risk")            else 0)),
            "cost_efficiency":  round((comps.get("cost").score            if comps.get("cost")            else 0)),
            "performance":      round((comps.get("performance").score    if comps.get("performance")    else 0)),
            "low_confidence": hr.low_confidence,
            "summary": hr.summary,
            "risk_drivers": hr.risk_drivers,
            "components": hr.to_dict().get("components"),
        }
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Portfolio Health compute failed for {user['user_id']}: {e}")
        health_payload = {
            "overall": 0, "grade": "N/A",
            "diversification": 0, "risk": 0, "cost_efficiency": 0, "performance": 0,
            "low_confidence": True, "summary": "Portfolio Health unavailable.",
            "risk_drivers": [], "components": {},
        }

    return {
        "total_invested": round(total_invested, 2),
        "current_value": round(current_value, 2),
        "total_returns": round(total_returns, 2),
        "returns_pct": round(returns_pct, 2),
        "day_change": day_change,
        "day_change_pct": day_change_pct,
        "asset_allocation": asset_allocation,
        "sector_exposure": sector_exposure,
        "risk_score": risk_score,
        "risk_label": risk_label,
        "holdings_count": len(holdings),
        "top_gainers": top_gainers,
        "top_losers": top_losers,
        "heatmap_data": heatmap_data[:40],
        "performance_trend": trend,
        "data_flags": data_flags,
        "live_price_stats": live_price_stats,
        "health_score": health_payload,
        "risk_analysis": compute_risk_analysis(holdings, current_value),
        "recommendations": generate_recommendations(holdings, current_value, total_invested),
    }


@router.post("/portfolio/refresh-prices")
async def refresh_equity_prices(request: Request):
    """Manually refresh live equity/ETF prices."""
    user = await get_current_user(request)
    holdings = await db.holdings.find(
        {"user_id": user["user_id"], "asset_type": {"$in": ["equity", "etf"]}},
        {"_id": 0}
    ).to_list(2000)

    if not holdings:
        return {"updated": 0, "message": "No equity/ETF holdings found"}

    holdings, stats = await fetch_live_prices(holdings)
    for h in holdings:
        if h.get("price_source") == "yahoo_finance" and h.get("holding_id"):
            await db.holdings.update_one(
                {"holding_id": h["holding_id"]},
                {"$set": {
                    "current_price": h["current_price"],
                    "price_source": "yahoo_finance",
                    "price_updated_at": h.get("price_updated_at", ""),
                    "nse_symbol": h.get("nse_symbol", ""),
                }}
            )
    return {"message": "Prices refreshed", **stats}


@router.get("/portfolio/simulate")
async def simulate_portfolio(request: Request, portfolio_id: str = ""):
    """Simulate optimized portfolio."""
    user = await get_current_user(request)
    query = {"user_id": user["user_id"]}
    if portfolio_id:
        query["portfolio_id"] = portfolio_id
    holdings = await db.holdings.find(query, {"_id": 0}).to_list(2000)
    if not holdings:
        return {"current_returns_pct": 0, "optimized_returns_pct": 0, "additional_returns": 0, "actions": []}

    holdings, _ = await fetch_live_prices(holdings)
    holdings = await update_holdings_nav(holdings)

    total_invested = sum(h["quantity"] * (h["buy_price"] if h["buy_price"] > 0 else h["current_price"]) for h in holdings)
    current_value = sum(h["quantity"] * h["current_price"] for h in holdings)

    return simulate_optimized_portfolio(holdings, current_value, total_invested)


@router.post("/nav/refresh")
async def refresh_nav(request: Request):
    """Manually refresh AMFI NAV cache."""
    user = await get_current_user(request)
    nav_map = await fetch_nav_data()
    holdings = await db.holdings.find({"user_id": user["user_id"], "asset_type": "mutual_fund"}, {"_id": 0}).to_list(2000)
    updated_count = 0
    for h in holdings:
        isin = (h.get("ticker") or "").upper().strip()
        name = h.get("name", "")
        nav_entry = None
        if isin and isin in nav_map:
            nav_entry = nav_map[isin]
        elif name:
            nav_entry = await lookup_nav(name=name)
        if nav_entry:
            await db.holdings.update_one(
                {"holding_id": h["holding_id"]},
                {"$set": {"current_price": nav_entry["nav"], "nav_date": nav_entry["date"], "nav_source": "AMFI"}}
            )
            updated_count += 1
    return {"updated": updated_count, "total_mf": len(holdings), "nav_entries": len(nav_map)}


@router.get("/portfolio/fund-performance")
async def get_fund_performance(request: Request, portfolio_id: str = "", force: str = ""):
    """Get MF benchmark ratings. Cached for 2 hours."""
    user = await get_current_user(request)
    user_id = user["user_id"]

    if not force:
        cached = await db.fund_performance_cache.find_one({"user_id": user_id}, {"_id": 0})
        if cached:
            cached_at = cached.get("cached_at", "")
            if cached_at:
                try:
                    from dateutil.parser import parse as parse_date
                    age = (datetime.now(timezone.utc) - parse_date(cached_at).replace(tzinfo=timezone.utc)).total_seconds()
                    if age < 7200:
                        return cached.get("data", {})
                except Exception:
                    pass

    query = {"user_id": user_id}
    if portfolio_id:
        query["portfolio_id"] = portfolio_id
    holdings = await db.holdings.find(query, {"_id": 0}).to_list(2000)

    if not holdings:
        return {"fund_ratings": [], "performance_distribution": {}, "category_overlap": [], "summary": {}}

    nav_cache = await fetch_nav_data()
    result = await compute_benchmark_ratings(holdings, nav_cache)

    await db.fund_performance_cache.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "data": result, "cached_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True
    )

    return result


@router.get("/portfolio/deep-analytics")
async def get_deep_analytics(request: Request, portfolio_id: str = ""):
    """Advanced analytics: overexposure, fund overlap, performance cards."""
    user = await get_current_user(request)
    query = {"user_id": user["user_id"]}
    if portfolio_id:
        query["portfolio_id"] = portfolio_id
    holdings = await db.holdings.find(query, {"_id": 0}).to_list(2000)

    if not holdings:
        return {"overexposure": {}, "overlap_matrix": [], "performance_cards": []}

    holdings, _ = await fetch_live_prices(holdings)
    holdings, _ = apply_sgb_issue_prices(holdings)
    holdings = enrich_holdings_with_sectors(holdings)

    total_value = sum(h["quantity"] * h["current_price"] for h in holdings)
    if total_value == 0:
        return {"overexposure": {}, "overlap_matrix": [], "performance_cards": []}

    # Overexposure Analysis
    fund_house_map = {}
    sector_concentration = {}
    asset_type_values = {}

    for h in holdings:
        val = h["quantity"] * h["current_price"]
        name = h.get("name", "")
        sector = h.get("sector", "Other")
        asset_type = h.get("asset_type", "other")

        if asset_type == "mutual_fund":
            fund_house = extract_fund_house(name)
            fund_house_map.setdefault(fund_house, {"value": 0, "count": 0, "funds": []})
            fund_house_map[fund_house]["value"] += val
            fund_house_map[fund_house]["count"] += 1
            fund_house_map[fund_house]["funds"].append(name[:50])

        sector_concentration.setdefault(sector, {"value": 0, "count": 0, "holdings": []})
        sector_concentration[sector]["value"] += val
        sector_concentration[sector]["count"] += 1
        sector_concentration[sector]["holdings"].append(name[:40])

        asset_type_values[asset_type] = asset_type_values.get(asset_type, 0) + val

    fund_house_data = []
    for fh, data in sorted(fund_house_map.items(), key=lambda x: x[1]["value"], reverse=True):
        pct = (data["value"] / total_value * 100) if total_value > 0 else 0
        fund_house_data.append({
            "name": fh,
            "value": round(data["value"], 2),
            "pct": round(pct, 1),
            "count": data["count"],
            "funds": data["funds"][:5],
            "risk_level": "high" if pct > 40 else "medium" if pct > 25 else "low"
        })

    sector_data = []
    for sec, data in sorted(sector_concentration.items(), key=lambda x: x[1]["value"], reverse=True):
        pct = (data["value"] / total_value * 100) if total_value > 0 else 0
        sector_data.append({
            "name": sec,
            "value": round(data["value"], 2),
            "pct": round(pct, 1),
            "count": data["count"],
            "holdings": data["holdings"][:5],
            "risk_level": "high" if pct > 40 else "medium" if pct > 25 else "low"
        })

    # Fund Overlap Matrix
    mf_holdings = [h for h in holdings if h.get("asset_type") == "mutual_fund"]
    overlap_matrix = []

    if len(mf_holdings) >= 2:
        for i in range(len(mf_holdings)):
            for j in range(i + 1, len(mf_holdings)):
                overlap = compute_fund_overlap(mf_holdings[i], mf_holdings[j])
                if overlap["overlap_pct"] > 0:
                    overlap_matrix.append(overlap)

        overlap_matrix.sort(key=lambda x: x["overlap_pct"], reverse=True)
        overlap_matrix = overlap_matrix[:15]

    # Performance Cards
    performance_cards = []
    for h in holdings:
        inv = h["quantity"] * h["buy_price"]
        cur = h["quantity"] * h["current_price"]
        abs_return = cur - inv
        pct_return = ((cur - inv) / inv * 100) if inv > 0 else 0
        weight = (cur / total_value * 100) if total_value > 0 else 0

        cagr = None
        if h.get("buy_date") and inv > 0 and cur > 0:
            try:
                from dateutil.parser import parse as parse_date
                buy_dt = parse_date(h["buy_date"])
                now_dt = datetime.now(timezone.utc)
                years = (now_dt - buy_dt.replace(tzinfo=timezone.utc)).days / 365.25
                # Only compute CAGR for holdings older than 1 year — otherwise
                # short horizons annualise into absurd multipliers (e.g., a fund
                # bought 30 days ago with 50% return becomes CAGR ~1e6%).
                if years >= 1.0:
                    cagr = round(((cur / inv) ** (1 / years) - 1) * 100, 1)
            except Exception:
                pass

        performance_cards.append({
            "name": h["name"][:50],
            "ticker": h.get("ticker", ""),
            "asset_type": h.get("asset_type", "other"),
            "sector": h.get("sector", "Other"),
            "quantity": h["quantity"],
            "buy_price": round(h["buy_price"], 2),
            "current_price": round(h["current_price"], 2),
            "invested": round(inv, 2),
            "current_value": round(cur, 2),
            "abs_return": round(abs_return, 2),
            "pct_return": round(pct_return, 1),
            "weight": round(weight, 1),
            "cagr": cagr,
            "nav_source": h.get("nav_source", ""),
            "nav_date": h.get("nav_date", ""),
        })

    performance_cards.sort(key=lambda x: x["pct_return"], reverse=True)

    # ── Duplication Score & Overlap Insights ──
    # Compute category-level duplication
    mf_by_category = {}
    for h in mf_holdings:
        cat = h.get("sector", "Other")
        val = h["quantity"] * h["current_price"]
        mf_by_category.setdefault(cat, {"funds": [], "total_value": 0})
        mf_by_category[cat]["funds"].append({"name": h["name"][:50], "value": round(val, 2)})
        mf_by_category[cat]["total_value"] += val

    mf_total = sum(h["quantity"] * h["current_price"] for h in mf_holdings) if mf_holdings else 0
    overlapping_value = sum(d["total_value"] for d in mf_by_category.values() if len(d["funds"]) >= 2)
    duplication_pct = round((overlapping_value / mf_total * 100) if mf_total > 0 else 0, 1)
    duplication_level = "high" if duplication_pct > 25 else "moderate" if duplication_pct > 10 else "low"

    # Category overlap with ₹ values for stacked bars
    category_overlap_detail = []
    for cat, data in sorted(mf_by_category.items(), key=lambda x: -x[1]["total_value"]):
        fund_count = len(data["funds"])
        is_overlapping = fund_count >= 2
        # Estimate: unique portion = 1 fund's share; overlap = rest
        unique_value = data["total_value"] / fund_count if fund_count > 0 else 0
        overlap_value = data["total_value"] - unique_value if is_overlapping else 0
        category_overlap_detail.append({
            "category": cat,
            "fund_count": fund_count,
            "total_value": round(data["total_value"], 2),
            "unique_value": round(unique_value, 2),
            "overlap_value": round(overlap_value, 2),
            "is_overlapping": is_overlapping,
            "funds": [f["name"] for f in data["funds"][:6]],
            "pct_of_mf": round(data["total_value"] / mf_total * 100, 1) if mf_total > 0 else 0,
        })

    # Sector exposure across ALL funds (estimate stock-level overlap)
    sector_across_funds = {}
    for h in mf_holdings:
        sector = h.get("sector", "Other")
        val = h["quantity"] * h["current_price"]
        sector_across_funds.setdefault(sector, {"value": 0, "fund_count": 0, "fund_names": set()})
        sector_across_funds[sector]["value"] += val
        sector_across_funds[sector]["fund_count"] += 1
        sector_across_funds[sector]["fund_names"].add(extract_fund_house(h["name"]))

    top_sector_overlaps = []
    for sec, data in sorted(sector_across_funds.items(), key=lambda x: -x[1]["value"]):
        pct = round(data["value"] / mf_total * 100, 1) if mf_total > 0 else 0
        top_sector_overlaps.append({
            "sector": sec,
            "value": round(data["value"], 2),
            "pct": pct,
            "fund_count": data["fund_count"],
            "amc_count": len(data["fund_names"]),
            "risk_level": "high" if pct > 25 else "moderate" if pct > 15 else "low",
        })

    # Generate AI-like insights
    overlap_insights = []
    # High-overlap categories
    for cat_data in category_overlap_detail:
        if cat_data["fund_count"] >= 3 and cat_data["is_overlapping"]:
            overlap_insights.append({
                "type": "warning",
                "text": f"You have {cat_data['fund_count']} {cat_data['category']} funds with significant overlap",
                "detail": f"₹{cat_data['total_value']/100000:.1f}L invested across {cat_data['fund_count']} funds in the same category. Consider consolidating to 1-2 best performers.",
                "category": cat_data["category"],
                "impact": "high" if cat_data["fund_count"] >= 5 else "medium",
            })
    # Sector concentration
    for sec_data in top_sector_overlaps[:3]:
        if sec_data["pct"] > 20:
            overlap_insights.append({
                "type": "alert",
                "text": f"Overexposed to {sec_data['sector']} sector ({sec_data['pct']}% of MF portfolio)",
                "detail": f"Spread across {sec_data['fund_count']} funds from {sec_data['amc_count']} AMCs. High sector concentration increases risk.",
                "category": sec_data["sector"],
                "impact": "high" if sec_data["pct"] > 30 else "medium",
            })
    # Fund house concentration
    for fh_data in fund_house_data[:2]:
        if fh_data["pct"] > 25:
            overlap_insights.append({
                "type": "info",
                "text": f"{fh_data['name']} dominates your MF portfolio ({fh_data['pct']}%)",
                "detail": f"{fh_data['count']} funds worth ₹{fh_data['value']/100000:.1f}L. Diversify across AMCs to reduce single-AMC risk.",
                "category": fh_data["name"],
                "impact": "medium",
            })
    # Positive insight if low duplication
    if duplication_pct < 15:
        overlap_insights.append({
            "type": "success",
            "text": f"Good diversification — only {duplication_pct}% overlap detected",
            "detail": "Your fund selection is well-diversified across categories.",
            "category": "overall",
            "impact": "low",
        })

    return {
        "overexposure": {
            "fund_house": fund_house_data,
            "sector": sector_data[:15],
            "total_value": round(total_value, 2),
        },
        "overlap_matrix": overlap_matrix,
        "performance_cards": performance_cards,
        "duplication": {
            "score": duplication_pct,
            "level": duplication_level,
            "overlapping_value": round(overlapping_value, 2),
            "mf_total": round(mf_total, 2),
            "category_detail": category_overlap_detail,
            "sector_overlaps": top_sector_overlaps[:10],
            "insights": overlap_insights[:6],
        },
    }


@router.get("/portfolio/allocation-analysis")
async def get_allocation_analysis(request: Request, force: str = ""):
    """AI-powered look-through company and sector allocation analysis."""
    user = await get_current_user(request)
    user_id = user["user_id"]

    # Check cache (valid for 6 hours)
    if not force:
        cached = await db.allocation_analysis_cache.find_one({"user_id": user_id}, {"_id": 0})
        if cached and cached.get("cached_at"):
            try:
                from dateutil.parser import parse as parse_date
                age = (datetime.now(timezone.utc) - parse_date(cached["cached_at"]).replace(tzinfo=timezone.utc)).total_seconds()
                if age < 21600:
                    return cached.get("data", {})
            except Exception:
                pass

    # SECURITY: Only send fund names, weights, sectors to OpenAI. NO PII (no user_id, email, PAN, address).
    holdings = await db.holdings.find(
        {"user_id": user_id},
        {"_id": 0, "name": 1, "ticker": 1, "asset_type": 1, "quantity": 1, "current_price": 1, "sector": 1}
    ).to_list(2000)
    if not holdings:
        return {"error": "No holdings found. Upload your portfolio first."}

    holdings = enrich_holdings_with_sectors(holdings)
    total_value = sum(h["quantity"] * h["current_price"] for h in holdings)
    if total_value == 0:
        return {"error": "Portfolio value is zero."}

    # Build prompt data
    direct_equity = []
    mutual_funds = []

    for h in holdings:
        val = h["quantity"] * h["current_price"]
        weight = round(val / total_value, 4) if total_value > 0 else 0

        if h.get("asset_type") == "equity":
            direct_equity.append({
                "name": h["name"],
                "weight": weight,
                "sector": h.get("sector", "Other"),
                "value": round(val, 0),
            })
        elif h.get("asset_type") in ("mutual_fund", "etf"):
            mutual_funds.append({
                "name": h["name"],
                "weight": weight,
                "category": h.get("sector", "Other"),
                "value": round(val, 0),
            })

    prompt = f"""Here is my portfolio data.

Total portfolio value: ₹{total_value:,.0f}

Direct Equity Holdings ({len(direct_equity)} stocks):
{json.dumps(direct_equity, indent=2)}

Mutual Funds ({len(mutual_funds)} funds):
{json.dumps(mutual_funds, indent=2)}

Note: Mutual fund underlying holdings are NOT provided. Use your knowledge of these Indian mutual fund schemes to estimate their typical top 10-15 holdings and sector allocation. Mark estimated data in data_quality.

Tasks:
1) Calculate total company exposure across mutual funds (look-through) + direct equity
2) Calculate true sector allocation (not MF categories — actual underlying sectors like Financials, IT, Energy, FMCG, etc.)
3) Identify top 10 companies and top 5 sectors
4) Flag concentration risks (sector > 30%, company > 10%)

Return STRICT JSON only."""

    try:
        result = await ai_engine.analyze_allocation(prompt)

        if "error" in result:
            return result

        # Cache the result
        await db.allocation_analysis_cache.update_one(
            {"user_id": user_id},
            {"$set": {
                "user_id": user_id,
                "data": result,
                "cached_at": datetime.now(timezone.utc).isoformat(),
                "holdings_count": len(holdings),
                "total_value": round(total_value, 2),
            }},
            upsert=True,
        )

        return result
    except Exception as e:
        logger.error(f"Allocation analysis failed: {e}")
        return {"error": f"Analysis failed: {str(e)}"}
