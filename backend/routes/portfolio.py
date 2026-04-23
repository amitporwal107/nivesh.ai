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
