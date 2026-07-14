"""Portfolio management + Holdings CRUD routes."""
from fastapi import APIRouter, HTTPException, Request
from datetime import datetime, timezone
import uuid
import logging

from deps import db, get_current_user
from models import PortfolioCreate, HoldingCreate, HoldingUpdate
from core.exceptions import ResourceNotFoundException, ValidationException, SystemException
from core.dto import clean, clean_list
from services import dashboard_cache as _dc
from services.sgb_prices import resolve_sgb_display_name

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.get("/portfolios")
async def list_portfolios(request: Request):
    user = await get_current_user(request)
    portfolios = clean_list(await db.portfolios.find({"user_id": user["user_id"]}, {"_id": 0}).to_list(50))
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
    return clean(result)


@router.delete("/portfolios/{portfolio_id}")
async def delete_portfolio(request: Request, portfolio_id: str):
    user = await get_current_user(request)
    result = await db.portfolios.delete_one({"portfolio_id": portfolio_id, "user_id": user["user_id"]})
    if result.deleted_count == 0:
        raise ResourceNotFoundException("Portfolio not found", code="RES-002")
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
async def get_enriched_holdings(request: Request, fresh: bool = False):
    """Actionable Portfolio payload — per-holding scores + action badges +
    XIRR + portfolio alerts. Powers the new decision-engine Portfolio page.

    Pass `?fresh=true` to bypass the 5-minute Redis cache. Useful when an
    earlier empty response (e.g., a request that landed before CAS ingest
    completed) got cached and is masking the real holdings.
    """
    user = await get_current_user(request)
    from services import portfolio_enrichment as _pe
    user_id = user["user_id"]

    try:
        return await _pe.build_enriched_portfolio(user_id, use_cache=not fresh)
    except Exception as e:  # noqa: BLE001
        # Safety net: never let a partial enrichment failure (Mongo timeout,
        # decision-engine glitch, peer-fetch hiccup) flip the UI into the
        # "Upload CAS" empty-state. Fall back to a minimal response built
        # straight from the holdings collection so the user at least sees
        # their portfolio, with an `_enrichment_error` flag so frontend can
        # surface a soft warning later if we add one.
        logger.exception("holdings-enriched enrichment failed for %s: %s", user_id, e)
        try:
            raw = await db.holdings.find(
                {"user_id": user_id}, {"_id": 0},
            ).to_list(2000)
            holdings = []
            for h in raw:
                qty = float(h.get("quantity") or 0)
                bp = float(h.get("buy_price") or 0)
                cp = float(h.get("current_price") or 0)
                val = qty * cp
                inv = qty * bp
                cb_known = bp > 0
                holdings.append({
                    "holding_id": h.get("holding_id"),
                    "name": resolve_sgb_display_name(h.get("name"), h.get("ticker")),
                    "isin": h.get("ticker"),
                    "nse_symbol": h.get("nse_symbol"),
                    "asset_type": h.get("asset_type"),
                    "sector": h.get("sector"),
                    "category": h.get("category"),
                    "quantity": qty,
                    "buy_price": bp,
                    "current_price": cp,
                    "buy_date": h.get("buy_date"),
                    "value_rs": round(val, 2),
                    "invested_rs": round(inv, 2) if cb_known else None,
                    "pnl_rs": round(val - inv, 2) if cb_known else None,
                    "pnl_pct": round((val - inv) / inv * 100, 2) if cb_known and inv > 0 else None,
                    # Enrichment fields — left null on the fallback path so
                    # the frontend renders dashes / em-dashes rather than
                    # stale or fabricated values.
                    "scores": None,
                    "composite_score": None,
                    "action_badge": None,
                    "switch_cost": None,
                    "weight_pct": None,
                    "low_confidence": True,
                })
            return {
                "holdings": holdings,
                "alerts": [],
                "totals": {
                    "value_rs": round(sum(h["value_rs"] for h in holdings), 2),
                    "invested_rs": round(sum(h["invested_rs"] or 0 for h in holdings), 2),
                },
                "coverage_pct": 0,
                "health": None,
                "_enrichment_error": str(e)[:200],
            }
        except Exception as inner:  # noqa: BLE001
            logger.exception("holdings-enriched fallback also failed: %s", inner)
            raise SystemException(
                "Portfolio enrichment temporarily unavailable. Try ?fresh=true.",
                code="SYS-001",
            )


@router.get("/portfolio/international-recommendations")
async def international_recommendations(request: Request):
    """End-to-end international FoF recommendation for the current user.

    Returns:
      • target % + ₹ amount to invest in international
      • current exposure
      • Core / Selective / Tactical / Avoid bands with cached fund primitives
      • portfolio context (risk, horizon, IT concentration, US exposure)

    If the international fund cache is empty, response includes `_stale: true`
    and the caller should POST `/portfolio/international-funds/refresh` first.
    """
    user = await get_current_user(request)
    from services import international_funds as _intl
    return await _intl.recommend_international_funds(user["user_id"])


@router.post("/portfolio/international-funds/refresh")
async def refresh_international_fund_cache(request: Request, force: bool = False):
    """Refresh the local international FoF cache by scraping Groww.

    Walks the curated seed list and re-pulls primitives (returns, expense,
    AUM, ratios, holdings) via the existing groww_client. Skips funds whose
    cached row is < 24h old unless ?force=true. Returns a summary dict.

    Auth: requires login (any user can trigger). Rate-limited at the cache
    layer — repeated calls are no-ops.
    """
    await get_current_user(request)  # auth gate, no user-specific state
    from services import international_funds as _intl
    return await _intl.refresh_international_funds(force=force)


@router.get("/funds/international")
async def international_fund_universe(request: Request, route: str = "", geography: str = ""):
    """International investment universe for the International Funds dashboard.

    Reads `nidp.v_international_funds` (migration 116) — the curated cross-route
    universe of international options for Indian investors (Indian FoF / Feeder /
    ETF / Domestic + LRS-direct US ETFs), with a unified price block (LRS ticker
    price via yfinance, else AMFI NAV) and NIDP analytics where the scheme is
    linked + scored. Proper-schema replacement for the Groww scrape-cache.

    Query (both optional, case-insensitive):
      • route     — Indian FoF | Indian Feeder | Indian ETF | Indian Domestic | LRS Direct
      • geography — US | Global | Europe | Emerging Markets | …

    Returns {ok, count, routes[], funds[]}. Real data only — if the NIDP pool is
    unavailable the response carries ok=false rather than fabricated rows.
    """
    await get_current_user(request)
    from services import pg_client

    pool = await pg_client.get_pool()
    if pool is None:
        return {"ok": False, "error": "no_pg_pool", "funds": [], "routes": [], "count": 0}

    # Validate route against the master's allowed set (avoids silent empty results).
    valid_routes = {"indian fof": "Indian FoF", "indian feeder": "Indian Feeder",
                    "indian etf": "Indian ETF", "indian domestic": "Indian Domestic",
                    "lrs direct": "LRS Direct"}
    route_filter = valid_routes.get((route or "").strip().lower())  # None ⇒ all
    geo_filter = (geography or "").strip() or None

    sql = """
        SELECT instrument_key, fund_name, amc, route, vehicle_type, underlying,
               geography, category, expense_ratio_text, expense_ratio_pct,
               subscription_status, status_class, ticker, scheme_code, notes,
               price, price_currency, change_pct, price_source, price_as_of,
               year_high, year_low,
               aum_cr, risk_o_meter, ret_1y, ret_3y, ret_5y, sharpe,
               max_drawdown_pct, analytics_available
          FROM nidp.v_international_funds
         WHERE ($1::text IS NULL OR route = $1::text)
           AND ($2::text IS NULL OR geography = $2::text)
         ORDER BY route, expense_ratio_pct ASC NULLS LAST, fund_name
    """
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, route_filter, geo_filter)
    except Exception as e:  # noqa: BLE001
        logger.warning("funds.international universe query failed: %s", e)
        return {"ok": False, "error": "query_failed", "funds": [], "routes": [], "count": 0}

    def _f(v):
        return round(float(v), 4) if v is not None else None

    funds = []
    for r in rows:
        funds.append({
            "instrument_key": r["instrument_key"],
            "fund_name":      r["fund_name"],
            "amc":            r["amc"],
            "route":          r["route"],
            "vehicle_type":   r["vehicle_type"],
            "underlying":     r["underlying"],
            "geography":      r["geography"],
            "category":       r["category"],
            "expense_ratio_text": r["expense_ratio_text"],
            "expense_ratio_pct":  _f(r["expense_ratio_pct"]),
            "subscription_status": r["subscription_status"],
            "status_class":   r["status_class"],
            "ticker":         r["ticker"],
            "scheme_code":    r["scheme_code"],
            "notes":          r["notes"],
            "price":          _f(r["price"]),
            "price_currency": r["price_currency"],
            "change_pct":     _f(r["change_pct"]),
            "price_source":   r["price_source"],
            "price_as_of":    r["price_as_of"].isoformat() if r["price_as_of"] else None,
            "year_high":      _f(r["year_high"]),
            "year_low":       _f(r["year_low"]),
            "aum_cr":         _f(r["aum_cr"]),
            "risk_o_meter":   r["risk_o_meter"],
            "ret_1y":         _f(r["ret_1y"]),
            "ret_3y":         _f(r["ret_3y"]),
            "ret_5y":         _f(r["ret_5y"]),
            "sharpe":         _f(r["sharpe"]),
            "max_drawdown_pct": _f(r["max_drawdown_pct"]),
            "analytics_available": bool(r["analytics_available"]),
        })

    # Per-route roll-up: count + how many are priced live + open for subscription.
    routes: dict = {}
    for f in funds:
        rb = routes.setdefault(f["route"], {"route": f["route"], "count": 0,
                                            "priced": 0, "open": 0})
        rb["count"] += 1
        if f["price"] is not None:
            rb["priced"] += 1
        if f["status_class"] == "open":
            rb["open"] += 1
    route_order = {"Indian FoF": 0, "Indian Feeder": 1, "Indian ETF": 2,
                   "Indian Domestic": 3, "LRS Direct": 4}
    route_list = sorted(routes.values(), key=lambda x: route_order.get(x["route"], 9))

    return {
        "ok": True,
        "count": len(funds),
        "route_filter": route_filter,
        "geography_filter": geo_filter,
        "routes": route_list,
        "funds": funds,
    }


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
        raise ResourceNotFoundException("Holding not found", code="RES-003")

    from services import pg_client
    from services import portfolio_enrichment as _pe
    from services.action_plan_manager import _normalize_fund_name
    from routes.admin_v3_master import _fetch_master_funds

    # Load full V3 catalogue once (cheap — one query)
    try:
        funds = await _fetch_master_funds(limit=None)
    except Exception as e:  # noqa: BLE001
        logger.warning("switch-candidates: master funds unavailable → %s", e)
        return {"candidates": [], "category": None, "source_quality": None}

    # Resolve current holding's category via fuzzy name match
    def _base_key(n: str) -> str:
        """Normalise + strip plan/growth/option words so two variants of
        the same scheme collapse. Without stripping `fund`/`scheme` the
        Regular variant ("SBI Contra Fund Regular Plan Growth") wouldn't
        match its Direct sibling ("SBI Contra Direct Plan Growth"), so the
        sibling slips into the candidate list as a "replacement"."""
        import re
        k = _normalize_fund_name(n or "")
        k = re.sub(
            r"\b(regular|direct|plan|growth|idcw|div|dividend|fund|scheme|the)\b",
            " ", k,
        )
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

    # Real exit load on EXITING the current fund (not the candidate).
    # Hardcoding 1.0% inflated friction uniformly and made the modal say
    # "Exit load 1.0%" for every candidate even when the holding had none.
    holding_exit_load_pct = float(holding.get("exit_load_pct") or 0)

    # Build switch scores for ALL siblings, then keep only those that are
    # genuinely better than the current holding on at least one of the
    # two PRD axes (quality OR cost). A candidate that loses on both is
    # not a "replacement" — it's a downgrade. Without this the modal was
    # showing -29 ΔQuality picks like Sundaram Value as recommendations.
    QUALITY_FLOOR = -1.0   # tolerate ~1pt rounding noise on quality
    scored = []
    for c in siblings:
        c_prim = c.get("primitives") or {}
        # No silent default — when expense data is missing we want the UI
        # to render "—" instead of an invented 0.5% that creates phantom
        # cost gains downstream.
        new_er = c_prim.get("expense_ratio_direct") or c_prim.get("expense_ratio_regular")
        ss = _pe.compute_switch_score(
            old={"scores": old_scores, "expense_ratio": old_er, "tax_impact_pct": 0},
            new={"scores": c.get("scores") or {}, "expense_ratio": new_er if new_er is not None else old_er},
            exit_load_pct=holding_exit_load_pct,
        )
        # Surface the raw delta even when negative (compute_switch_score
        # currently clamps cost_gain to ≥0, hiding a cost LOSS — recompute
        # the signed delta here so the UI can show "+extra cost" honestly).
        if new_er is not None and old_er:
            ss["cost_gain_pct_signed"] = round((old_er - new_er) / max(0.01, old_er) * 100.0, 1)
        else:
            ss["cost_gain_pct_signed"] = None
        ss["expense_ratio_new"] = new_er  # may be None
        scored.append((c, ss))

    # Filter: must improve on quality OR cost. Weak candidates dropped.
    qualified = [
        (c, ss) for c, ss in scored
        if (ss.get("delta_quality") or 0) > QUALITY_FLOOR
        or ((ss.get("cost_gain_pct_signed") or 0) > 0)
    ]
    qualified.sort(
        key=lambda pair: (
            (pair[1].get("delta_quality") or 0),
            (pair[1].get("cost_gain_pct_signed") or 0),
        ),
        reverse=True,
    )
    qualified = qualified[:max(1, min(10, int(limit)))]

    cand_list = []
    for c, ss in qualified:
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
    if holding.portfolio_id:
        pf = await db.portfolios.find_one(
            {"portfolio_id": holding.portfolio_id, "user_id": user["user_id"]}
        )
        if not pf:
            raise ResourceNotFoundException("Portfolio not found", code="RES-002")
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
    await _dc.invalidate(user["user_id"])
    return clean(result)


@router.put("/portfolio/holdings/{holding_id}")
async def update_holding(request: Request, holding_id: str, holding: HoldingUpdate):
    user = await get_current_user(request)
    # Use exclude_unset so the caller can explicitly set buy_date=null to clear it.
    # Without exclude_unset we couldn't distinguish "not passed" from "passed as null".
    update_data = holding.model_dump(exclude_unset=True)
    if not update_data:
        raise ValidationException("No fields to update", code="VAL-001")
    await db.holdings.update_one(
        {"holding_id": holding_id, "user_id": user["user_id"]},
        {"$set": update_data}
    )
    result = await db.holdings.find_one({"holding_id": holding_id}, {"_id": 0})
    if not result:
        raise ResourceNotFoundException("Holding not found", code="RES-003")
    await _dc.invalidate(user["user_id"])
    return result


@router.delete("/portfolio/holdings/{holding_id}")
async def delete_holding(request: Request, holding_id: str):
    user = await get_current_user(request)
    result = await db.holdings.delete_one({"holding_id": holding_id, "user_id": user["user_id"]})
    if result.deleted_count == 0:
        raise ResourceNotFoundException("Holding not found", code="RES-003")
    await _dc.invalidate(user["user_id"])
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
    await _dc.invalidate(uid)

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

    logger.info("Refreshing Morningstar ratings for %s stocks…", len(unique_items))
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


@router.post("/portfolio/resync")
async def resync_portfolio(request: Request) -> dict:
    """Trigger a NAV + benchmark data refresh for the current user's portfolio.

    Invalidates the portfolio_performance_cache rows for this user so the next
    Performance page load recomputes fresh values. Returns the new last_synced_at
    timestamp on success; preserves prior data and returns an error field on failure.
    """
    user = await get_current_user(request)
    user_id = user["user_id"]
    now = datetime.now(timezone.utc)

    try:
        # Invalidate performance cache so next load recomputes
        try:
            from services import pg_client
            pool = await pg_client.get_pool()
            if pool:
                async with pool.acquire() as conn:
                    # RETURNING COUNT(*) is invalid; use execute() and check status
                    status = await conn.execute(
                        "DELETE FROM portfolio_performance_cache WHERE user_id = $1",
                        user_id,
                    )
                    logger.info("resync: perf cache clear for %s: %s", user_id, status)
        except Exception as pg_err:
            logger.warning("resync: pg cache clear failed (non-fatal): %s", pg_err)

        # Invalidate Redis enrichment cache
        try:
            from services.redis_client import invalidate_portfolio_cache
            await invalidate_portfolio_cache(user_id)
        except Exception:
            pass

        return {
            "ok": True,
            "last_synced_at": now.isoformat(),
            "message": "Portfolio data refreshed. Performance metrics will recompute on next load.",
        }
    except Exception as e:  # noqa: BLE001
        logger.exception("resync failed for %s: %s", user_id, e)
        return {
            "ok": False,
            "last_synced_at": None,
            "error": "Resync failed — prior data preserved. Try again shortly.",
        }
