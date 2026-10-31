"""The existing services each visual answer reads, called in-process (no HTTP loopback). Read-only.

Each reader is the slimmest existing function behind the route the desk already uses; each raises on failure (the
builder records the source as missing and shows no figure from it). The unit tests replace these functions.

    market_snapshot     DaaS /v1/snapshots/market (nidp.market_daily_snapshot) — the Copilot market node's own read
    index_rows          DaaS /v1/indices/{name}/eod (nidp.index_eod), oldest first
    sector_returns      DaaS /v1/desk/sector-returns (NSE sectoral indices) — GET /api/markets/sector-returns
    chain               routes.fno.chain — GET /api/fno/{symbol}/chain (summary: expected move, ATM IV, PCR, max pain, walls)
    fii_dii             DaaS /v1/market-pulse/fii-dii (nidp.fii_dii_flows, NSE first) — GET /api/markets/fii-dii
    buildup             routes.fno._buildup_scan — GET /api/fno/scan/buildup (refused when older than the previous session)
    regime              the desk regime (routes.macro._desk_regime via strategy_plan.sources._regime)
    watchlist_day       services.ai_watchlist_store.get_day — GET /api/desk/ai-watchlist (Mongo ai_watchlist_days)
    positional_watchlist routes.positional.get_watchlist — GET /api/positional/watchlist (breakout_confirmed bucket)
    scan_snapshot       routes.positional._scan_snapshot — DaaS /v1/features/scan-snapshot (stock_features_daily + bhavcopy)
    delivery_latest     DaaS /v1/prices/delivery/{symbol} (nidp.delivery_data), the newest day
    stock_bars          routes.research_chart._live_bars — DaaS /v1/prices/adjusted/{symbol} (prices_eod_adjusted)
    ema                 routes.research_chart._ema_masked — the feature engine's EMA (technical_indicator_engine)
    window              services.market_freshness.window — today and the previous NSE session

Release 2:
    open_trades         routes.desk_trading.list_paper_trades — GET /api/desk/paper-trades (open, with marks and P&L)
    fno_top             services.strategy_plan.regime_fit.build_top — POST /api/desk/strategy/top (F&O classes)
    risk_book           services.risk_book.read (Mongo desk_paper_trades, risk_profiles, paper_accounts): the account's
                        day/week P&L, open risk and exposure — the same read the risk service itself checks a trade against
    risk_profile        services.risk_profile.read — GET /api/risk/profile (the account's own limits)
    latest_trade_plan   Mongo trade_plans, the newest stored plan for a symbol (services.strategy_plan.trade_plan.COLLECTION)

Release 3:
    closed_trades       Mongo desk_paper_trades, the user's newest closed paper trades, shaped as the desk shapes them
                        (routes.desk_trading._public). A plain read: GET /api/desk/paper-trades also runs the exit rule on
                        open trades (a write), which a review has no reason to do.
    risk_decisions      Mongo risk_decisions (services.risk_controls.DECISIONS), the user's entry checks since a time:
                        outcome, reasons, symbol, time (the risk snapshot itself is not read)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import quote


async def window():
    from services import market_freshness
    return await market_freshness.window()


async def _daas(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    from services.copilot_tools import daas_client
    if not daas_client.is_configured():
        raise RuntimeError("the data platform (DaaS) is not configured")
    body = await daas_client._get(path, params=params)
    if body is None:
        raise RuntimeError(f"DaaS {path} answered 404")
    return body


async def market_snapshot() -> Dict[str, Any]:
    body = await _daas("/snapshots/market")
    data = body.get("data") if isinstance(body, dict) and isinstance(body.get("data"), dict) else body
    if not isinstance(data, dict) or not data.get("as_of_date"):
        raise RuntimeError("the market snapshot has no as-of date")
    return data


async def index_rows(name: str, limit: int) -> List[Dict[str, Any]]:
    body = await _daas(f"/indices/{quote(name)}/eod", {"limit": limit})
    rows = body.get("data") if isinstance(body, dict) else None
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(f"no {name} rows in nidp.index_eod")
    return sorted((r for r in rows if isinstance(r, dict)), key=lambda r: str(r.get("as_of_date")))


async def sector_returns() -> Dict[str, Any]:
    body = await _daas("/desk/sector-returns")
    if not isinstance(body, dict) or not isinstance(body.get("sectors"), list):
        raise RuntimeError("the sector-returns route sent no sectors")
    return body


async def chain(request: Any, symbol: str) -> Dict[str, Any]:
    from routes import fno
    return await fno.chain(request, symbol=symbol, expiry=None, around=fno.DEFAULT_AROUND)


async def fii_dii(days: int = 30) -> Dict[str, Any]:
    from services.copilot_tools import daas_client
    body = await daas_client.get_market_pulse_fii_dii(days=days)
    if not isinstance(body, dict) or not body.get("daily"):
        raise RuntimeError("no FII/DII cash rows")
    return body


async def buildup() -> Dict[str, Any]:
    from routes import fno
    return await fno._buildup_scan(None)


async def regime() -> Dict[str, Any]:
    from services.strategy_plan import sources
    out = await sources._regime()
    if not out.get("ok"):
        raise RuntimeError(out.get("error") or "the desk regime is unavailable")
    return out["data"]


async def market_state() -> Dict[str, Any]:
    """The market state the risk service sizes and checks new paper trades with ({regime BULL|BEAR|SIDEWAYS, vix, as_of,
    key}), with its own freshness judgement: the same two calls as GET /api/risk/freshness, so the Market regime card on
    the desk and this answer cannot disagree."""
    from datetime import datetime, timezone
    from services.risk_gate import inputs as risk_inputs
    from services.risk_gate import service as risk_service
    market = await risk_inputs.market_state()
    if market.get("regime") is None:
        raise RuntimeError(market.get("error") or "the market state is unavailable")
    return {**market, "freshness": risk_service.market_freshness(market, datetime.now(timezone.utc))}


async def watchlist_day() -> Optional[Dict[str, Any]]:
    from services import ai_watchlist_store
    return await ai_watchlist_store.get_day(None)


async def positional_watchlist(request: Any) -> Dict[str, Any]:
    from routes import positional
    return await positional.get_watchlist(request, limit=30)


async def scan_snapshot() -> Dict[str, Any]:
    from routes import positional
    return await positional._scan_snapshot()


async def delivery_latest(symbol: str) -> Optional[Dict[str, Any]]:
    body = await _daas(f"/prices/delivery/{quote(symbol)}", {"limit": 1})
    rows = body.get("data") if isinstance(body, dict) else None
    return rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None


async def stock_bars(symbol: str) -> List[list]:
    from routes import research_chart
    return await research_chart._live_bars(symbol)


def ema(closes: List[float], n: int) -> List[Optional[float]]:
    import numpy as np
    from routes import research_chart
    return research_chart._ema_masked(np.array(closes, dtype=float), n)


async def trade_idea(request: Any, user_id: str, symbol: str, message: str) -> Any:
    from services import copilot_trade_idea
    return await copilot_trade_idea.build(request, user_id, symbol, message)


# ── Release 2 ────────────────────────────────────────────────────────────────

async def open_trades(request: Any) -> Dict[str, Any]:
    from routes import desk_trading
    return await desk_trading.list_paper_trades(request, status_filter="open")


async def fno_top(request: Any, user_id: str, limit: int = 5) -> Dict[str, Any]:
    """build_top alone does not store the TradePlans it builds — only the /top ROUTE does, right after calling it
    (routes/strategy_plan.py strategy_top). Store them the same way here, or the fno_setups card's plan_id would be
    a plan that GET /api/desk/trade-plans/{id} has never heard of."""
    from routes import strategy_plan as sp
    from services.strategy_plan import regime_fit
    out = await regime_fit.build_top(request, user_id, limit=limit, classes=["index_options", "stock_fno"], distinct=True)
    await sp.store_trade_plans(sp.trade_plans_of_top(out), user_id)
    return out


async def risk_book(user_id: str) -> Dict[str, Any]:
    from deps import db
    from services import risk_book as rb
    return await rb.read(db, user_id)


async def risk_profile(user_id: str) -> Dict[str, Any]:
    from deps import db
    from services import risk_profile as rp
    return await rp.read(db, user_id)


async def latest_trade_plan(symbol: str) -> Optional[Dict[str, Any]]:
    """The newest STORED TradePlan for `symbol` (any segment), Mongo `trade_plans`, or None. The plan's own record of
    what was decided when it was built — the "original thesis" a validity check compares today's read against."""
    from deps import db
    from services.strategy_plan.trade_plan import COLLECTION
    doc = await db[COLLECTION].find_one({"instrument.symbol": symbol}, sort=[("created_at", -1)])
    return doc


# ── Release 3 ────────────────────────────────────────────────────────────────

async def closed_trades(user_id: str, limit: int = 300) -> List[Dict[str, Any]]:
    """The user's newest `limit` closed paper trades (cash and F&O structures), newest close first, as the desk's own
    list shows a closed trade."""
    from deps import db
    from routes import desk_trading
    from services import desk_trading as svc
    docs = await db[svc.TRADES].find({"user_id": user_id, "status": "closed"}).sort("closed_at", -1).to_list(limit)
    return [desk_trading._public(d) for d in docs]


async def risk_decisions(user_id: str, since_utc: str, limit: int = 1000) -> List[Dict[str, Any]]:
    """The user's risk-check decisions at or after `since_utc` (an ISO UTC time; rows store `at` the same way), newest
    first, without the snapshot / checks / budget detail."""
    from deps import db
    from services import risk_controls as rc
    return await db[rc.DECISIONS].find(
        {"user_id": user_id, "at": {"$gte": since_utc}},
        {"_id": 1, "at": 1, "outcome": 1, "symbol": 1, "reasons": 1, "source": 1, "supersedes": 1, "path": 1},
    ).sort("at", -1).to_list(limit)
