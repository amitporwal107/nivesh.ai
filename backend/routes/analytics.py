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
from services.tax_engine import card_tax_block as _card_tax_block
from services.mf_category_enricher import enrich_mf_with_sebi_category
from services.fund_clusterer import cluster_overlapping_funds
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

    # Heatmap data — only compute return_pct when real cost basis exists.
    # CAS imports often have buy_price=0 (cost basis unknown); falling back to
    # current_price makes inv==cur and pct==0 for every tile, which is wrong.
    # When buy_price is absent, emit return_pct=None so the tile renders as
    # muted grey (cost_basis_estimated=True) rather than a fake 0% green.
    heatmap_data = []
    for h in holdings:
        cost_basis_estimated = h.get("buy_price", 0) <= 0
        inv = h["quantity"] * h["buy_price"] if not cost_basis_estimated else 0
        cur = h["quantity"] * h["current_price"]
        pct = ((cur - inv) / inv * 100) if inv > 0 else None
        if cur > 0:
            heatmap_data.append({
                "name": h["name"][:30],
                "ticker": h.get("ticker", ""),
                "value": round(cur, 2),
                "invested": round(inv, 2) if not cost_basis_estimated else None,
                "return_pct": round(pct, 1) if pct is not None else None,
                "cost_basis_estimated": cost_basis_estimated,
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
        logger.warning("Portfolio Health compute failed for %s: %s", user['user_id'], e)
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
    """Manually refresh live equity/ETF prices. Also fires background stock
    fundamentals + MF catalogue enrichment so Insights/Plan Board scores
    stay fresh on the next render."""
    user = await get_current_user(request)
    uid = user["user_id"]
    holdings = await db.holdings.find(
        {"user_id": uid, "asset_type": {"$in": ["equity", "etf"]}},
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

    # Fire-and-forget enrichment (Groww stock fundamentals + inline MF scrape).
    # Redis cache (6h / 30d respectively) makes repeat refreshes near-free.
    import asyncio as _asyncio
    async def _bg():
        try:
            from services.groww_stock_scraper import refresh_user_stocks
            from services import fund_data_resolver as _fdr
            await refresh_user_stocks(uid)
            await _fdr.scrape_user_mfs_inline(uid)
        except Exception as e:  # noqa: BLE001
            logger.warning("refresh-prices bg enrichment failed: %s", e)
    _asyncio.create_task(_bg())

    return {"message": "Prices refreshed", **stats}


@router.post("/portfolio/refresh-stock-fundamentals")
async def refresh_stock_fundamentals(request: Request):
    """Trigger Groww fundamentals refresh for the user's equity holdings.
    Scrapes ROE, D/E, growth, margins, volatility + computes V3 composite
    Quality/Health/Exit/Add scores. Typically takes 3-5s for a 10-stock
    portfolio.
    """
    user = await get_current_user(request)
    from services import groww_stock_scraper as _gs
    from services import redis_client as _rc
    from services import audit as _audit
    result = await _gs.refresh_user_stocks(user["user_id"])
    # Invalidate the enriched-portfolio cache so the UI gets fresh scores.
    try:
        await _rc.cache_del(f"enriched_portfolio:{user['user_id']}")
    except Exception:  # noqa: BLE001
        pass
    try:
        await _audit.record(
            user_id=user["user_id"], action="portfolio_refresh",
            resource="stock_fundamentals",
            ip=request.client.host if request.client else "",
            ua=request.headers.get("user-agent", ""),
            details=result if isinstance(result, dict) else None,
        )
    except Exception:  # noqa: BLE001
        pass
    return result


@router.post("/portfolio/refresh-mf-ratings")
async def refresh_mf_ratings(request: Request):
    """Trigger Moneycontrol rescrape for the user's mutual fund holdings to
    refresh Morningstar ratings + CAGR + investment-style primitives.

    Runs sequentially with a 15-fund cap per call (~10s). Invalidates the
    enriched-portfolio Redis cache on completion.
    """
    user = await get_current_user(request)
    from deps import db
    from services import moneycontrol_client as _mc
    from services import pg_writer as _pgw
    from services import redis_client as _rc

    cursor = db.holdings.find(
        {"user_id": user["user_id"], "asset_type": {"$in": ["mutual_fund", "etf"]}},
        {"_id": 0, "name": 1, "ticker": 1},
    )
    holdings = await cursor.to_list(200)
    # De-dupe by name (Regular/Direct share a rating, so scrape once)
    seen = set()
    uniq = []
    for h in holdings:
        nl = (h.get("name") or "").lower().strip()
        if nl and nl not in seen:
            seen.add(nl); uniq.append(h)
    ok = 0
    fail: list[dict] = []
    rated = 0
    for h in uniq:  # process all unique MFs (no artificial cap)
        name = h.get("name") or ""
        try:
            hit = await _mc.search_fund(name)
            if not hit:
                fail.append({"name": name, "reason": "mc_search_miss"})
                continue
            payload = await _mc.fetch_by_url(hit["url"])
            if not payload:
                fail.append({"name": name, "reason": "fetch_failed"})
                continue
            # Don't overwrite payload['scheme_name'] with the CAS comma-laden
            # holding name — MC returns the canonical name which matches PG.
            # But do surface the user's name for the fuzzy-match fallback.
            if h.get("ticker") and not payload.get("isin"):
                payload["isin"] = h["ticker"]
            mf_id = await _pgw.persist_moneycontrol_scrape(payload)
            if mf_id:
                ok += 1
                if payload.get("morningstar_rating") is not None:
                    rated += 1
        except Exception as e:  # noqa: BLE001
            fail.append({"name": name, "reason": str(e)[:120]})

    try:
        await _rc.cache_del(f"enriched_portfolio:{user['user_id']}")
    except Exception:  # noqa: BLE001
        pass

    return {
        "ok": True,
        "total": len(holdings),
        "scraped": ok,
        "with_rating": rated,
        "failed": len(fail),
        "failed_details": fail[:10],
    }


@router.get("/portfolio/stock-scores")
async def get_user_stock_scores(request: Request):
    """Return V3 composite scores (Quality/Health/Exit/Add) for every equity
    holding the user owns. Data lives in Postgres `stock_scores` — populated
    by `refresh-stock-fundamentals` or the daily Nifty 100 cron.
    """
    user = await get_current_user(request)
    cursor = db.holdings.find(
        {"user_id": user["user_id"], "asset_type": "equity"},
        {"_id": 0, "nse_symbol": 1, "name": 1, "quantity": 1, "current_price": 1},
    )
    holdings = await cursor.to_list(500)
    if not holdings:
        return {"holdings": [], "coverage": 0}
    symbols = [h["nse_symbol"].upper() for h in holdings if h.get("nse_symbol")]
    if not symbols:
        return {"holdings": [], "coverage": 0}

    try:
        from services import pg_client
        pool = await pg_client.get_pool()
        if pool is None:
            return {"holdings": [], "coverage": 0, "error": "Postgres unavailable"}
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT sm.nse_symbol, sm.company_name, sm.sector, sm.cap_bucket,
                       sm.market_cap_cr,
                       ss.quality_score, ss.health_score, ss.exit_score, ss.add_score,
                       ss.recommendation, ss.recommendation_reason, ss.low_confidence,
                       ss.computed_at
                FROM stock_master sm
                LEFT JOIN stock_scores ss ON ss.nse_symbol = sm.nse_symbol
                WHERE sm.nse_symbol = ANY($1::text[])
                """,
                symbols,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("stock-scores fetch failed: %s", e)
        return {"holdings": [], "coverage": 0, "error": str(e)}

    by_sym = {r["nse_symbol"]: r for r in rows}
    out = []
    scored = 0
    for h in holdings:
        sym = (h.get("nse_symbol") or "").upper()
        row = by_sym.get(sym)
        val = float(h.get("quantity") or 0) * float(h.get("current_price") or 0)
        entry = {
            "nse_symbol": sym, "name": h.get("name"),
            "quantity": h.get("quantity"), "current_value_rs": round(val, 2),
            "scores": None, "recommendation": None,
        }
        if row and row["quality_score"] is not None:
            entry["scores"] = {
                "quality": float(row["quality_score"]),
                "health": float(row["health_score"]) if row["health_score"] else None,
                "exit": float(row["exit_score"]) if row["exit_score"] else None,
                "add": float(row["add_score"]) if row["add_score"] else None,
            }
            entry["recommendation"] = {
                "action": row["recommendation"] or "REVIEW",
                "reason": row["recommendation_reason"],
            }
            entry["sector"] = row["sector"]
            entry["cap_bucket"] = row["cap_bucket"]
            entry["computed_at"] = row["computed_at"].isoformat() if row["computed_at"] else None
            entry["low_confidence"] = bool(row["low_confidence"])
            scored += 1
        out.append(entry)

    coverage = round((scored / len(holdings)) * 100, 1) if holdings else 0
    return {"holdings": out, "coverage_pct": coverage, "scored": scored, "total": len(holdings)}


# ── Per-holding recommendation helper ─────────────────────────────────────────

def _mf_recommendation(ret_1y, category_avg_1y, quality_score, is_regular: bool) -> dict:
    """Derive Hold/Exit/Buy More/Switch for a MF/ETF holding."""
    if is_regular:
        return {"action": "SWITCH", "reason": "Switch to Direct plan — save ~0.7–1% p.a. in expense ratio"}
    if quality_score is not None and quality_score < 40:
        return {"action": "EXIT", "reason": f"Quality score {quality_score:.0f}/100 — below acceptable threshold"}
    if ret_1y is not None and category_avg_1y is not None:
        alpha = round(float(ret_1y) - float(category_avg_1y), 1)
        if alpha <= -5:
            return {"action": "EXIT", "reason": f"Trailing category by {abs(alpha):.1f}pp over 1 year"}
        if alpha >= 3 and (quality_score or 0) > 70:
            return {"action": "BUY_MORE", "reason": f"Outperforming category by {alpha:.1f}pp with strong quality score"}
    return {"action": "HOLD", "reason": "Performing in line with category; no action needed"}


@router.get("/portfolio/recommendations/v5")
async def get_portfolio_recommendations_v5(request: Request):
    """Per-holding NIDP-scored recommendations (Hold / Exit / Buy More / Switch)
    plus top-5 per asset class.

    Sources:
      Equity  — Postgres stock_scores (quality, health, exit, recommendation)
      MF/ETF  — DaaS v3-primitives (ret_1y, category_avg_1y) + rule logic
      Gold/SGB — HOLD by default (government-backed, guaranteed returns)
    """
    user = await get_current_user(request)
    all_holdings = await db.holdings.find(
        {"user_id": user["user_id"]},
        {"_id": 0, "name": 1, "ticker": 1, "asset_type": 1, "nse_symbol": 1,
         "quantity": 1, "current_price": 1, "buy_price": 1},
    ).to_list(2000)

    if not all_holdings:
        return {"holdings": [], "top5_by_asset_class": {}}

    # ── MF/ETF: DaaS primitives ─────────────────────────────────────────────
    mf_isins = list({
        (h.get("ticker") or "").upper().strip()
        for h in all_holdings
        if (h.get("asset_type") or "").lower() in ("mutual_fund", "etf")
        and (h.get("ticker") or "").strip()
    })
    daas_by_isin: dict = {}
    if mf_isins:
        try:
            from services.copilot_tools import daas_client as _daas
            import feature_flags as _ff
            if _daas.is_configured() and _ff.is_enabled("v3_data_source_daas"):
                daas_by_isin = await _daas.get_v3_mf_primitives_bulk(mf_isins) or {}
        except Exception as e:
            logger.warning("recommendations: DaaS fetch failed: %s", e)

    # ── Equity: stock_scores ────────────────────────────────────────────────
    eq_symbols = list({
        (h.get("nse_symbol") or "").upper()
        for h in all_holdings
        if (h.get("asset_type") or "").lower() == "equity"
        and (h.get("nse_symbol") or "").strip()
    })
    stock_scores_map: dict = {}
    if eq_symbols:
        try:
            from services import pg_client
            pool = await pg_client.get_pool()
            if pool:
                async with pool.acquire() as conn:
                    rows = await conn.fetch(
                        """SELECT nse_symbol, quality_score, health_score, exit_score,
                                  recommendation, recommendation_reason
                             FROM stock_scores WHERE nse_symbol = ANY($1::text[])""",
                        eq_symbols,
                    )
                stock_scores_map = {r["nse_symbol"]: dict(r) for r in rows}
        except Exception as e:
            logger.warning("recommendations: stock_scores fetch failed: %s", e)

    _ACTION_ORDER = {"BUY_MORE": 0, "HOLD": 1, "SWITCH": 2, "EXIT": 3, "REVIEW": 4}
    results = []

    for h in all_holdings:
        at   = (h.get("asset_type") or "other").lower()
        isin = (h.get("ticker") or "").upper().strip()
        sym  = (h.get("nse_symbol") or "").upper()
        name = (h.get("name") or "")[:60]
        val  = float(h.get("quantity") or 0) * float(h.get("current_price") or 0)
        rec  = {"action": "HOLD", "reason": "No scoring data", "quality_score": None, "health_score": None, "confidence": "low"}

        if at == "equity" and sym and sym in stock_scores_map:
            ss  = stock_scores_map[sym]
            qs  = float(ss["quality_score"]) if ss.get("quality_score") is not None else None
            hs  = float(ss["health_score"])  if ss.get("health_score")  is not None else None
            rec = {"action": ss.get("recommendation") or "HOLD",
                   "reason": ss.get("recommendation_reason") or "Based on NIDP V3 quality and health scores",
                   "quality_score": qs, "health_score": hs, "confidence": "high"}

        elif at in ("mutual_fund", "etf") and isin and isin in daas_by_isin:
            prim = daas_by_isin[isin]
            qs   = prim.get("quality_score")
            hs   = prim.get("health_score")
            r1y  = prim.get("ret_1y") or prim.get("return_1y")
            cat  = prim.get("category_avg_1y")
            is_regular = "regular" in name.lower() and "direct" not in name.lower()
            mf_rec = _mf_recommendation(
                float(r1y) if r1y is not None else None,
                float(cat) if cat is not None else None,
                float(qs)  if qs  is not None else None,
                is_regular,
            )
            rec = {**mf_rec,
                   "quality_score": float(qs) if qs is not None else None,
                   "health_score":  float(hs) if hs is not None else None,
                   "confidence": "medium"}

        elif at == "gold":
            rec = {"action": "HOLD", "reason": "SGB — government-backed with guaranteed gold price returns",
                   "quality_score": None, "health_score": None, "confidence": "high"}

        results.append({
            "isin": isin, "nse_symbol": sym, "name": name,
            "asset_type": at, "current_value_rs": round(val, 2),
            **rec,
        })

    # ── Top 5 per asset class (prioritise actionable > HOLD, then by quality) ─
    def _top5(asset_type_filter: str) -> list:
        bucket = [r for r in results if r["asset_type"] == asset_type_filter]
        actionable = [r for r in bucket if r["action"] != "HOLD"]
        ranked = sorted(actionable or bucket,
                        key=lambda x: (_ACTION_ORDER.get(x["action"], 5), -(x.get("quality_score") or 0)))
        return [{"name": r["name"], "action": r["action"], "reason": r["reason"],
                 "quality_score": r.get("quality_score"), "current_value_rs": r["current_value_rs"]}
                for r in ranked[:5]]

    return {
        "holdings": results,
        "top5_by_asset_class": {
            "mutual_fund": _top5("mutual_fund"),
            "equity":      _top5("equity"),
            "etf":         _top5("etf"),
            "gold":        _top5("gold"),
        },
    }


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
async def get_fund_performance(
    request: Request,
    portfolio_id: str = "",
    force: str = "",
    period: str = "1y",
    benchmark: str = "peer",
):
    """Get MF benchmark ratings. Cached for 2 hours.

    Query params:
      period    — lookback window: "1y" | "3y" | "5y" (default "1y")
      benchmark — comparison basis: "peer" | "index" (default "peer")

    Screens served: 10_performance.svg (mobile + webapp)
    """
    _VALID_PERIODS = {"1y", "3y", "5y"}
    _VALID_BENCHMARKS = {"peer", "index"}
    if period not in _VALID_PERIODS:
        period = "1y"
    if benchmark not in _VALID_BENCHMARKS:
        benchmark = "peer"

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
        return {
            "fund_ratings": [],
            "performance_distribution": {},
            "category_overlap": [],
            "summary": {},
            "period": period,
            "benchmark": benchmark,
        }

    nav_cache = await fetch_nav_data()
    # compute_benchmark_ratings does not accept period/benchmark yet — augment after
    result = await compute_benchmark_ratings(holdings, nav_cache)

    # Augment each fund rating item with v4 benchmark fields
    benchmark_index_label = "NIFTY 50" if benchmark == "index" else "Category Average"
    for item in result.get("fund_ratings", []):
        if isinstance(item, dict):
            item.setdefault("alpha_3y_benchmark_pp", None)
            item.setdefault("benchmark_index", benchmark_index_label)

    # Attach top-level period + benchmark to response
    result["period"] = period
    result["benchmark"] = benchmark

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

    # Fund Overlap Clusters (replaces the pre-2026-05-20 nested pair-loop).
    #
    # OLD behaviour: every cross-product pair was emitted, with no
    # SEBI-category gate. Cross-category pairs (Large Cap vs Index Fund)
    # made it into the user-facing insights because `compute_fund_overlap`
    # used the holding's `sector` field — which reflects the primary
    # stock universe, not the SEBI primary category. Both a Large Cap
    # fund and a Nifty 50 Index fund had `sector = "Large Cap"`.
    #
    # NEW behaviour: enrich MF holdings with `sebi_category` +
    # `sebi_subcategory`, then cluster N-way INSIDE each category.
    # A cluster of 3 Nifty 50 funds is now ONE row, not 3 pairs.
    # Cross-category pairings are impossible by construction.
    mf_holdings = [h for h in holdings if h.get("asset_type") == "mutual_fund"]
    mf_holdings = enrich_mf_with_sebi_category(mf_holdings)
    overlap_clusters = cluster_overlapping_funds(mf_holdings)

    # Legacy `overlap_matrix`: keep as a flat list of within-cluster
    # pair-edges so existing UI consumers (the deep-analytics heatmap)
    # keep working. The new cluster shape is what insight generation
    # now consumes.
    overlap_matrix = []
    for cluster in overlap_clusters:
        members = cluster["members"]
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                overlap_matrix.append({
                    "fund_a":      members[i]["name"],
                    "fund_b":      members[j]["name"],
                    "overlap_pct": cluster["avg_overlap_pct"],
                    "reasons":     [f"Same SEBI category: {cluster['sebi_subcategory'] or cluster['sebi_category']}"],
                })
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

        # Tax classification — reuse services/tax_engine so the dashboard
        # stays consistent with copilot/switch-decision tools. Honest framing
        # (tier + confidence), not a "you'll pay ₹X" number.
        tax_block = _card_tax_block(h, inv, cur)

        performance_cards.append({
            "holding_id": h.get("holding_id"),  # primary key for click-to-drilldown
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
            "tax": tax_block,
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
        "overlap_clusters": overlap_clusters,
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
        logger.error("Allocation analysis failed: %s", e)
        return {"error": f"Analysis failed: {str(e)}"}


@router.get("/portfolio/holding-detail/{isin}")
async def get_holding_detail(isin: str, request: Request):
    """Return V3 DaaS primitives + category peer data for a single ISIN.

    Fetches from NIDP DaaS using get_v3_mf_primitives_bulk([isin]).
    Also fetches top-3 peers from analytics.fund_category_rank via
    the category leaderboard DaaS endpoint.

    Returns daas_available=false (not an error) when the ISIN has no V3
    data — e.g. equities or funds not yet in the NIDP analytics lake.
    """
    await get_current_user(request)  # auth guard

    isin_clean = (isin or "").strip().upper()
    if not isin_clean:
        raise HTTPException(status_code=400, detail="isin is required")

    # ── 1. V3 MF primitives from DaaS ────────────────────────────────
    from services.copilot_tools.daas_client import get_v3_mf_primitives_bulk, _get as daas_get, DaasError

    prim: dict = {}
    try:
        bulk = await get_v3_mf_primitives_bulk([isin_clean])
        prim = bulk.get(isin_clean) or {}
    except Exception as exc:
        logger.warning("holding-detail DaaS primitives error isin=%s: %s", isin_clean, exc)

    daas_available = bool(prim)

    if not daas_available:
        return {
            "isin": isin_clean,
            "name": None,
            "category": None,
            "returns": {"1m": None, "3m": None, "1y": None, "3y": None},
            "category_avg": {"1y": None, "3y": None},
            "risk": {"sharpe": None, "sortino": None, "volatility_1y": None, "max_drawdown": None},
            "ranking": {"composite_rank": None, "category_size": None, "top_position_pct": None},
            "top_peers": [],
            "daas_available": False,
        }

    # ── 2. Extract primitives ─────────────────────────────────────────
    def _f(key: str):
        v = prim.get(key)
        return round(float(v), 2) if v is not None else None

    name = prim.get("scheme_name")
    sub_category = prim.get("sub_category") or prim.get("category")

    returns = {
        "1m": _f("return_1m"),
        "3m": _f("return_3m"),
        "1y": _f("ret_1y"),
        "3y": _f("ret_3y"),
    }
    category_avg = {
        "1y": _f("category_avg_1y"),
        "3y": _f("category_avg_3y"),
    }
    risk = {
        "sharpe": _f("sharpe"),
        "sortino": _f("sortino"),
        "volatility_1y": _f("volatility_1y"),
        "max_drawdown": _f("max_drawdown_pct"),
    }

    composite_rank = prim.get("category_rank")
    composite_rank_int = int(composite_rank) if composite_rank is not None else None

    # ── 3. Category size + top peers via DaaS category leaderboard ────
    category_size = None
    top_peers: list = []

    if sub_category:
        try:
            peers_resp = await daas_get(
                f"/mf/performance/category/{sub_category}",
                params={"metric": "composite_rank", "limit": "5"},
            )
            if peers_resp and isinstance(peers_resp.get("data"), list):
                category_size = peers_resp.get("total") or len(peers_resp["data"])
                for row in peers_resp["data"][:3]:
                    if (row.get("isin") or "").upper() != isin_clean:
                        top_peers.append({
                            "name": row.get("scheme_name"),
                            "return_1y": round(float(row["return_1y"]), 2) if row.get("return_1y") is not None else None,
                            "composite_rank": int(row["composite_rank"]) if row.get("composite_rank") is not None else None,
                        })
                    if len(top_peers) >= 3:
                        break
        except DaasError as exc:
            logger.warning("holding-detail peers error isin=%s sub_cat=%s: %s", isin_clean, sub_category, exc)
        except Exception as exc:
            logger.warning("holding-detail peers unexpected error isin=%s: %s", isin_clean, exc)

    top_position_pct = None
    if composite_rank_int is not None and category_size:
        try:
            top_position_pct = round(composite_rank_int / int(category_size) * 100, 1)
        except Exception:
            pass

    return {
        "isin": isin_clean,
        "name": name,
        "category": sub_category,
        "returns": returns,
        "category_avg": category_avg,
        "risk": risk,
        "ranking": {
            "composite_rank": composite_rank_int,
            "category_size": int(category_size) if category_size is not None else None,
            "top_position_pct": top_position_pct,
        },
        "top_peers": top_peers,
        "daas_available": True,
    }


@router.get("/portfolio/value-history")
async def get_portfolio_value_history(request: Request):
    """Monthly portfolio value history from CAS statement extraction.

    Returns the [{month, value_rs}] array stored in the user's profile
    during CAS import (cas_summary_vision.py). These are the real monthly
    portfolio values printed on the CAS statement — not modelled numbers.

    Also returns the current_value from holdings so the last data-point
    can be spliced in.
    """
    user = await get_current_user(request)
    user_id = user["user_id"]

    profile = await db.user_profiles.find_one({"user_id": user_id}, {"_id": 0,
        "cas_monthly_values": 1, "cas_portfolio_value_rs": 1}) or {}

    monthly_values = profile.get("cas_monthly_values") or []

    # Sort chronologically (month strings are "Apr 2025" etc.)
    from dateutil.parser import parse as _dp
    def _sort_key(item):
        try:
            return _dp("1 " + item["month"])
        except Exception:
            return _dp("1 Jan 2000")

    try:
        monthly_values = sorted(monthly_values, key=_sort_key)
    except Exception:
        pass

    # Current portfolio value from live holdings (more up-to-date than CAS)
    total_current = 0.0
    try:
        async for h in db.holdings.find({"user_id": user_id},
                                        {"_id": 0, "quantity": 1, "current_price": 1}):
            total_current += float(h.get("quantity") or 0) * float(h.get("current_price") or 0)
    except Exception:
        total_current = float(profile.get("cas_portfolio_value_rs") or 0)

    return {
        "monthly_values": monthly_values,     # [{month: str, value_rs: float}]
        "current_value_rs": round(total_current, 2),
        "source": "cas_statement",
        "count": len(monthly_values),
    }
