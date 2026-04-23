"""Portfolio management + Holdings CRUD routes."""
from fastapi import APIRouter, HTTPException, Request
from datetime import datetime, timezone
import uuid
import logging

from deps import db, get_current_user
from models import PortfolioCreate, HoldingCreate, HoldingUpdate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.get("/portfolios")
async def list_portfolios(request: Request):
    user = await get_current_user(request)
    portfolios = await db.portfolios.find({"user_id": user["user_id"]}, {"_id": 0}).to_list(50)
    for p in portfolios:
        count = await db.holdings.count_documents({"user_id": user["user_id"], "portfolio_id": p["portfolio_id"]})
        p["holdings_count"] = count
    return portfolios


@router.post("/portfolios")
async def create_portfolio(request: Request, data: PortfolioCreate):
    user = await get_current_user(request)
    doc = {
        "portfolio_id": f"pf_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "name": data.name,
        "member_name": data.member_name,
        "relationship": data.relationship,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.portfolios.insert_one(doc)
    result = await db.portfolios.find_one({"portfolio_id": doc["portfolio_id"]}, {"_id": 0})
    return result


@router.delete("/portfolios/{portfolio_id}")
async def delete_portfolio(request: Request, portfolio_id: str):
    user = await get_current_user(request)
    result = await db.portfolios.delete_one({"portfolio_id": portfolio_id, "user_id": user["user_id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    deleted = await db.holdings.delete_many({"user_id": user["user_id"], "portfolio_id": portfolio_id})
    return {"message": f"Portfolio deleted with {deleted.deleted_count} holdings"}


# ==================== INSTRUMENT SEARCH ====================

@router.get("/search/instruments")
async def search_instruments(q: str = ""):
    from instruments_data import INDIAN_INSTRUMENTS
    if not q or len(q) < 2:
        return []
    q_lower = q.lower()
    results = []
    for inst in INDIAN_INSTRUMENTS:
        if q_lower in inst["name"].lower() or q_lower in inst["ticker"].lower():
            results.append(inst)
        if len(results) >= 15:
            break
    return results


# ==================== HOLDINGS CRUD ====================

@router.get("/portfolio/holdings-enriched")
async def get_enriched_holdings(request: Request):
    """Actionable Portfolio payload — per-holding scores + action badges +
    XIRR + portfolio alerts. Powers the new decision-engine Portfolio page.
    """
    user = await get_current_user(request)
    from services import portfolio_enrichment as _pe
    return await _pe.build_enriched_portfolio(user["user_id"])


@router.get("/portfolio/switch-candidates")
async def switch_candidates(request: Request, holding_id: str, limit: int = 3):
    """Return top same-category replacement funds for a given MF holding.

    Ranks by (add_score + quality_score)/2 desc; skips the original fund and
    its Regular/Direct sibling. Includes a computed switch_score breakdown."""
    user = await get_current_user(request)
    holding = await db.holdings.find_one(
        {"holding_id": holding_id, "user_id": user["user_id"]}, {"_id": 0},
    )
    if not holding:
        raise HTTPException(status_code=404, detail="Holding not found")

    from services import pg_client
    from services import portfolio_enrichment as _pe
    from services.action_plan_manager import _normalize_fund_name
    from routes.admin_v3_master import _fetch_master_funds

    # Load full V3 catalogue once (cheap — one query)
    try:
        funds = await _fetch_master_funds(limit=None)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"switch-candidates: master funds unavailable → {e}")
        return {"candidates": [], "category": None, "source_quality": None}

    # Resolve current holding's category via fuzzy name match
    def _base_key(n: str) -> str:
        """Normalise + strip Regular/Direct/Plan so HDFC Small Cap's
        Regular plan matches its Direct sibling for category lookup."""
        import re
        k = _normalize_fund_name(n or "")
        k = re.sub(r"\b(regular|direct|plan|growth|idcw|div|dividend)\b", " ", k)
        return " ".join(k.split())

    norm_holding = _base_key(holding.get("name") or "")
    old_fund = None
    if norm_holding:
        for f in funds:
            if _base_key(f.get("scheme_name") or "") == norm_holding:
                old_fund = f
                break
        if old_fund is None:
            for f in funds:
                nf = _base_key(f.get("scheme_name") or "")
                if nf and (nf in norm_holding or norm_holding in nf):
                    old_fund = f
                    break
    category = (old_fund or {}).get("category") or holding.get("category")
    if not category:
        return {"candidates": [], "category": None, "source_quality": None,
                "source_fund": holding.get("name")}

    old_scores = (old_fund or {}).get("scores") or {}
    old_er = ((old_fund or {}).get("primitives") or {}).get("expense_ratio_direct") \
        or ((old_fund or {}).get("primitives") or {}).get("expense_ratio_regular") or 1.0

    # Filter same-category, scored, and not the same fund (drop Regular/Direct sibling too)
    old_base = _base_key(holding.get("name") or "")

    old_quality = old_scores.get("quality") or 0
    siblings = [
        f for f in funds
        if f.get("category") == category
        and f.get("scores", {}).get("quality") is not None
        and _base_key(f.get("scheme_name") or "") != old_base
        # Must have "direct" in the name AND not "regular" — more reliable than plan_type field
        and "direct" in (f.get("scheme_name") or "").lower()
        and "regular" not in (f.get("scheme_name") or "").lower()
    ]
    # Sort: quality-improvement first, then by switch_score proxy (add+quality)
    ranked = sorted(
        siblings,
        key=lambda f: (
            (f.get("scores", {}).get("quality") or 0) - old_quality,
            (f.get("scores", {}).get("add") or 0) + (f.get("scores", {}).get("quality") or 0)
        ),
        reverse=True,
    )[:max(1, min(10, int(limit)))]

    cand_list = []
    for c in ranked:
        c_prim = c.get("primitives") or {}
        new_er = c_prim.get("expense_ratio_direct") or c_prim.get("expense_ratio_regular") or 0.5
        ss = _pe.compute_switch_score(
            old={"scores": old_scores, "expense_ratio": old_er, "tax_impact_pct": 0},
            new={"scores": c.get("scores") or {}, "expense_ratio": new_er},
            exit_load_pct=1.0,
        )
        cand_list.append({
            "instrument_id": c.get("instrument_id"),
            "name": c.get("scheme_name"),
            "category": c.get("category"),
            "sub_category": c.get("sub_category"),
            "amc": c.get("amc_name"),
            "plan_type": c.get("plan_type"),
            "scores": c.get("scores"),
            "switch_score": ss,
        })

    return {
        "source_fund": holding.get("name"),
        "category": category,
        "source_quality": old_scores.get("quality"),
        "candidates": cand_list,
    }




@router.get("/portfolio/holdings")
async def get_holdings(request: Request, portfolio_id: str = "", asset_type: str = ""):
    user = await get_current_user(request)
    query = {"user_id": user["user_id"]}
    if portfolio_id:
        query["portfolio_id"] = portfolio_id
    if asset_type:
        query["asset_type"] = asset_type
    holdings = await db.holdings.find(query, {"_id": 0}).to_list(2000)
    return holdings


@router.post("/portfolio/holdings")
async def add_holding(request: Request, holding: HoldingCreate):
    user = await get_current_user(request)
    holding_doc = {
        "holding_id": f"hold_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "portfolio_id": holding.portfolio_id or "",
        "name": holding.name,
        "ticker": holding.ticker,
        "asset_type": holding.asset_type,
        "quantity": holding.quantity,
        "buy_price": holding.buy_price,
        "current_price": holding.current_price,
        "sector": holding.sector or "Other",
        "buy_date": holding.buy_date or None,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.holdings.insert_one(holding_doc)
    result = await db.holdings.find_one({"holding_id": holding_doc["holding_id"]}, {"_id": 0})
    return result


@router.put("/portfolio/holdings/{holding_id}")
async def update_holding(request: Request, holding_id: str, holding: HoldingUpdate):
    user = await get_current_user(request)
    # Use exclude_unset so the caller can explicitly set buy_date=null to clear it.
    # Without exclude_unset we couldn't distinguish "not passed" from "passed as null".
    update_data = holding.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    await db.holdings.update_one(
        {"holding_id": holding_id, "user_id": user["user_id"]},
        {"$set": update_data}
    )
    result = await db.holdings.find_one({"holding_id": holding_id}, {"_id": 0})
    if not result:
        raise HTTPException(status_code=404, detail="Holding not found")
    return result


@router.delete("/portfolio/holdings/{holding_id}")
async def delete_holding(request: Request, holding_id: str):
    user = await get_current_user(request)
    result = await db.holdings.delete_one({"holding_id": holding_id, "user_id": user["user_id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Holding not found")
    return {"message": "Holding deleted"}


@router.delete("/portfolio/holdings-all")
async def clear_all_holdings(request: Request):
    """Delete ALL holdings and associated data for the current user."""
    user = await get_current_user(request)
    uid = user["user_id"]

    holdings_deleted = (await db.holdings.delete_many({"user_id": uid})).deleted_count
    await db.fund_performance_cache.delete_many({"user_id": uid})
    await db.gmail_imports.delete_many({"user_id": uid})
    await db.portfolio_analysis.delete_many({"user_id": uid})
    await db.ai_insights.delete_many({"user_id": uid})
    await db.upload_tasks.delete_many({"user_id": uid})
    await db.chat_messages.delete_many({"user_id": uid})

    return {"message": f"{holdings_deleted} holdings cleared. All portfolio data reset.", "deleted": holdings_deleted}



@router.post("/portfolio/refresh-stock-morningstar")
async def refresh_stock_morningstar(request: Request):
    """
    Fetch Morningstar quantitative star ratings for all equity holdings
    in the user's portfolio and persist them to stock_scores.
    Runs a Playwright token fetch once, then makes lightweight API calls.
    """
    user = await get_current_user(request)
    uid  = user["user_id"]

    # Fetch equity holdings
    holdings = await db.holdings.find(
        {"user_id": uid, "asset_type": "equity"},
        {"_id": 0, "nse_symbol": 1, "name": 1}
    ).to_list(200)

    if not holdings:
        return {"message": "No equity holdings found", "updated": 0}

    # Normalize for the scraper
    items = [
        {
            "nse_symbol":   (h.get("nse_symbol") or "").upper().strip(),
            "company_name": h.get("name") or h.get("nse_symbol") or "",
        }
        for h in holdings if h.get("nse_symbol")
    ]
    # Deduplicate by symbol
    seen: set = set()
    unique_items = []
    for it in items:
        if it["nse_symbol"] not in seen:
            seen.add(it["nse_symbol"])
            unique_items.append(it)

    from services.morningstar_stock_client import batch_refresh_stock_morningstar
    from services import pg_client

    logger.info(f"Refreshing Morningstar ratings for {len(unique_items)} stocks…")
    ratings = await batch_refresh_stock_morningstar(unique_items)

    if not ratings:
        return {"message": "No Morningstar data found (token may have failed)", "updated": 0}

    # Persist to PostgreSQL stock_scores
    pool = await pg_client.get_pool()
    updated = 0
    if pool:
        async with pool.acquire() as conn:
            # Ensure column exists (idempotent)
            await conn.execute(
                "ALTER TABLE stock_scores ADD COLUMN IF NOT EXISTS morningstar_rating INTEGER"
            )
            for sym, data in ratings.items():
                rating = data.get("morningstar_rating")
                if rating is None:
                    continue
                result = await conn.execute(
                    "UPDATE stock_scores SET morningstar_rating = $1 WHERE nse_symbol = $2",
                    rating, sym
                )
                if result == "UPDATE 1":
                    updated += 1

    # Invalidate Redis cache so next portfolio load reflects new data
    try:
        from services.redis_client import invalidate_portfolio_cache
        await invalidate_portfolio_cache(uid)
    except Exception:
        pass

    return {
        "message": f"Morningstar ratings refreshed: {updated} stocks updated in DB",
        "updated": updated,
        "ratings": {sym: d["morningstar_rating"] for sym, d in ratings.items()},
    }
