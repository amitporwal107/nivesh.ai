"""Postgres write layer for MF scrape pipeline.

Persists a full Groww scrape to:
  - instrument_master           (upsert MF by isin / scheme_code)
  - instrument_master           (upsert each underlying equity by stock_slug)
  - mutual_fund_metadata        (upsert)
  - mutual_fund_holdings        (replace latest holdings for today)
  - mutual_fund_performance_ratios (upsert by date)
  - scrape_audit_log            (append)

All operations are no-ops when POSTGRES_URL is unset; resolver must tolerate
this gracefully.
"""
from __future__ import annotations
import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import asyncpg

from services import pg_client

logger = logging.getLogger(__name__)


# ── Instrument upserts ───────────────────────────────────────────────────
async def upsert_mf(
    conn: asyncpg.Connection,
    scheme_name: str,
    scheme_code: Optional[str],
    isin: Optional[str],
) -> Optional[uuid.UUID]:
    """Upsert a MF row; return its instrument_id. Resolution order:
    isin → symbol (scheme_code) → by name insert.
    """
    if isin:
        row = await conn.fetchrow(
            "SELECT instrument_id FROM instrument_master "
            "WHERE isin = $1 AND instrument_type = 'MUTUAL_FUND'",
            isin,
        )
        if row:
            await conn.execute(
                "UPDATE instrument_master SET instrument_name = COALESCE($1, instrument_name), "
                "symbol = COALESCE($2, symbol), updated_at = NOW() WHERE instrument_id = $3",
                scheme_name, scheme_code, row["instrument_id"],
            )
            return row["instrument_id"]
    if scheme_code:
        row = await conn.fetchrow(
            "SELECT instrument_id FROM instrument_master "
            "WHERE symbol = $1 AND instrument_type = 'MUTUAL_FUND'",
            scheme_code,
        )
        if row:
            await conn.execute(
                "UPDATE instrument_master SET instrument_name = COALESCE($1, instrument_name), "
                "isin = COALESCE($2, isin), updated_at = NOW() WHERE instrument_id = $3",
                scheme_name, isin, row["instrument_id"],
            )
            return row["instrument_id"]
    # Insert new
    row = await conn.fetchrow(
        "INSERT INTO instrument_master (symbol, instrument_name, instrument_type, isin) "
        "VALUES ($1, $2, 'MUTUAL_FUND', $3) RETURNING instrument_id",
        scheme_code, scheme_name, isin,
    )
    return row["instrument_id"] if row else None


async def upsert_equity(
    conn: asyncpg.Connection,
    name: str,
    stock_slug: Optional[str],
) -> Optional[uuid.UUID]:
    """Upsert an equity row by stock_slug (used as symbol)."""
    if not name:
        return None
    symbol = stock_slug or name
    row = await conn.fetchrow(
        "SELECT instrument_id FROM instrument_master "
        "WHERE symbol = $1 AND instrument_type = 'EQUITY'",
        symbol,
    )
    if row:
        return row["instrument_id"]
    try:
        row = await conn.fetchrow(
            "INSERT INTO instrument_master (symbol, instrument_name, instrument_type) "
            "VALUES ($1, $2, 'EQUITY') ON CONFLICT DO NOTHING RETURNING instrument_id",
            symbol, name,
        )
        if row:
            return row["instrument_id"]
        # ON CONFLICT hit — refetch
        row = await conn.fetchrow(
            "SELECT instrument_id FROM instrument_master "
            "WHERE symbol = $1 AND instrument_type = 'EQUITY'",
            symbol,
        )
        return row["instrument_id"] if row else None
    except Exception as e:  # noqa: BLE001
        logger.warning(f"upsert_equity failed for {name!r}: {e}")
        return None


# ── Main persist ─────────────────────────────────────────────────────────
async def persist_scrape(data: Dict[str, Any]) -> Optional[uuid.UUID]:
    """Persist a validated scrape. Returns mutual_fund instrument_id or None.

    `data` shape = output of `groww_client.fetch_fund()`: holdings, ratios,
    metadata, split, sectors, slug, valid, scheme_name, source.
    """
    pool = await pg_client.get_pool()
    if pool is None:
        return None

    meta = data.get("metadata") or {}
    scheme_code = meta.get("scheme_code") or meta.get("direct_scheme_code")
    isin = meta.get("isin")
    scheme_name = data.get("scheme_name") or meta.get("scheme_name") or ""

    today = date.today()
    async with pool.acquire() as conn:
        async with conn.transaction():
            mf_id = await upsert_mf(conn, scheme_name, scheme_code, isin)
            if mf_id is None:
                return None

            # Metadata
            v3 = data.get("v3_primitives") or {}
            primary_mgr = v3.get("primary_manager") or {}
            cat_avg = v3.get("category_avg_returns") or {}
            cat_rank = v3.get("rank_within_category") or {}
            import json as _json
            await conn.execute(
                """
                INSERT INTO mutual_fund_metadata
                    (instrument_id, groww_slug, aum_cr, nav, nav_date, expense_ratio,
                     rating, risk_label, category, last_scraped_at, updated_at,
                     allotment_date, fund_age_years,
                     manager_name, manager_since, manager_tenure_years,
                     manager_education, manager_funds_count, fund_managers,
                     expense_ratio_direct, expense_ratio_regular,
                     expense_ratio_3y_ago, expense_trend_delta, historic_expense_json,
                     turnover_ratio, turnover_as_of,
                     category_avg_1y, category_avg_3y, category_avg_5y,
                     rank_within_category_1y, rank_within_category_3y, rank_within_category_5y,
                     top10_concentration_pct, sibling_slug, analysis_json,
                     sub_category, launch_date)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,NOW(),NOW(),
                        $10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,
                        $25,$26,$27,$28,$29,$30,$31,$32,$33,$34,$35)
                ON CONFLICT (instrument_id) DO UPDATE SET
                    groww_slug = EXCLUDED.groww_slug,
                    aum_cr = EXCLUDED.aum_cr,
                    nav = EXCLUDED.nav,
                    nav_date = EXCLUDED.nav_date,
                    expense_ratio = EXCLUDED.expense_ratio,
                    rating = EXCLUDED.rating,
                    risk_label = EXCLUDED.risk_label,
                    category = EXCLUDED.category,
                    last_scraped_at = NOW(),
                    updated_at = NOW(),
                    allotment_date = EXCLUDED.allotment_date,
                    fund_age_years = EXCLUDED.fund_age_years,
                    manager_name = EXCLUDED.manager_name,
                    manager_since = EXCLUDED.manager_since,
                    manager_tenure_years = EXCLUDED.manager_tenure_years,
                    manager_education = EXCLUDED.manager_education,
                    manager_funds_count = EXCLUDED.manager_funds_count,
                    fund_managers = EXCLUDED.fund_managers,
                    expense_ratio_direct = COALESCE(EXCLUDED.expense_ratio_direct, mutual_fund_metadata.expense_ratio_direct),
                    expense_ratio_regular = COALESCE(EXCLUDED.expense_ratio_regular, mutual_fund_metadata.expense_ratio_regular),
                    expense_ratio_3y_ago = EXCLUDED.expense_ratio_3y_ago,
                    expense_trend_delta = EXCLUDED.expense_trend_delta,
                    historic_expense_json = EXCLUDED.historic_expense_json,
                    turnover_ratio = EXCLUDED.turnover_ratio,
                    turnover_as_of = EXCLUDED.turnover_as_of,
                    category_avg_1y = EXCLUDED.category_avg_1y,
                    category_avg_3y = EXCLUDED.category_avg_3y,
                    category_avg_5y = EXCLUDED.category_avg_5y,
                    rank_within_category_1y = EXCLUDED.rank_within_category_1y,
                    rank_within_category_3y = EXCLUDED.rank_within_category_3y,
                    rank_within_category_5y = EXCLUDED.rank_within_category_5y,
                    top10_concentration_pct = EXCLUDED.top10_concentration_pct,
                    sibling_slug = EXCLUDED.sibling_slug,
                    analysis_json = EXCLUDED.analysis_json,
                    sub_category = EXCLUDED.sub_category,
                    launch_date = EXCLUDED.launch_date
                """,
                mf_id,
                data.get("slug"),
                meta.get("aum_cr"),
                meta.get("nav"),
                _parse_date(meta.get("nav_date")),
                meta.get("expense_ratio"),
                int(meta.get("groww_rating")) if meta.get("groww_rating") else None,
                meta.get("risk_label"),
                meta.get("sub_category") or meta.get("category"),
                # V3 primitives
                _parse_date(v3.get("allotment_date")),
                v3.get("fund_age_years"),
                primary_mgr.get("name"),
                _parse_date(primary_mgr.get("since")),
                primary_mgr.get("tenure_years"),
                primary_mgr.get("education"),
                primary_mgr.get("funds_managed_count"),
                _json.dumps(v3.get("fund_managers") or []),
                meta.get("expense_ratio_direct"),
                meta.get("expense_ratio_regular"),
                v3.get("expense_ratio_3y_ago"),
                v3.get("expense_trend_delta"),
                _json.dumps(v3.get("historic_expense") or []),
                v3.get("turnover_ratio"),
                _parse_date(v3.get("turnover_as_of")),
                cat_avg.get("1y"),
                cat_avg.get("3y"),
                cat_avg.get("5y"),
                cat_rank.get("1y"),
                cat_rank.get("3y"),
                cat_rank.get("5y"),
                v3.get("top10_concentration_pct"),
                v3.get("sibling_slug"),
                _json.dumps(v3.get("analysis") or []),
                meta.get("sub_category"),
                _parse_date(meta.get("launch_date")),
            )

            # V3 Phase 1a: snapshot current AUM into history (monthly granularity).
            # Idempotent by (instrument_id, snapshot_date) — one row per day.
            if meta.get("aum_cr"):
                await conn.execute(
                    """
                    INSERT INTO mutual_fund_aum_history (instrument_id, snapshot_date, aum_cr, source)
                    VALUES ($1, $2, $3, 'groww')
                    ON CONFLICT (instrument_id, snapshot_date) DO UPDATE SET aum_cr = EXCLUDED.aum_cr
                    """,
                    mf_id, today, meta.get("aum_cr"),
                )

            # Persist benchmark_index from benchmark_master (keyed by category)
            cat_for_bench = meta.get("sub_category") or meta.get("category")
            if cat_for_bench:
                await conn.execute(
                    """
                    UPDATE mutual_fund_metadata SET benchmark_index = b.benchmark_name
                    FROM benchmark_master b
                    WHERE mutual_fund_metadata.instrument_id = $1
                      AND b.category = $2
                      AND mutual_fund_metadata.benchmark_index IS NULL
                    """,
                    mf_id, cat_for_bench,
                )

            # Ratios
            r = data.get("ratios") or {}
            if any(v is not None for v in r.values()):
                await conn.execute(
                    """
                    INSERT INTO mutual_fund_performance_ratios
                        (instrument_id, ratios_date, pe_ratio, pb_ratio, alpha, beta,
                         sharpe, sortino, std_dev, ret_1y, ret_3y, ret_5y)
                    VALUES ($1,$2,NULL,NULL,$3,$4,$5,$6,$7,$8,$9,$10)
                    ON CONFLICT (instrument_id, ratios_date) DO UPDATE SET
                        alpha=EXCLUDED.alpha, beta=EXCLUDED.beta,
                        sharpe=EXCLUDED.sharpe, sortino=EXCLUDED.sortino,
                        std_dev=EXCLUDED.std_dev,
                        ret_1y=EXCLUDED.ret_1y, ret_3y=EXCLUDED.ret_3y, ret_5y=EXCLUDED.ret_5y
                    """,
                    mf_id, today,
                    r.get("alpha"), r.get("beta"),
                    r.get("sharpe"), r.get("sortino"),
                    r.get("std_dev"),
                    r.get("ret_1y"), r.get("ret_3y"), r.get("ret_5y"),
                )

            # Holdings — replace today's snapshot
            holdings: List[Dict[str, Any]] = data.get("holdings") or []
            if holdings:
                await conn.execute(
                    "DELETE FROM mutual_fund_holdings "
                    "WHERE instrument_id = $1 AND holding_date = $2",
                    mf_id, today,
                )
                for rank, h in enumerate(holdings, start=1):
                    eq_id = await upsert_equity(conn, h.get("name", ""), h.get("stock_slug"))
                    await conn.execute(
                        """
                        INSERT INTO mutual_fund_holdings
                            (instrument_id, holding_instrument_id, holding_name,
                             holding_stock_slug, holding_sector, holding_type,
                             weight_percent, rank, holding_date)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                        ON CONFLICT (instrument_id, holding_date, rank) DO UPDATE SET
                            holding_instrument_id=EXCLUDED.holding_instrument_id,
                            holding_name=EXCLUDED.holding_name,
                            holding_stock_slug=EXCLUDED.holding_stock_slug,
                            holding_sector=EXCLUDED.holding_sector,
                            holding_type=EXCLUDED.holding_type,
                            weight_percent=EXCLUDED.weight_percent
                        """,
                        mf_id, eq_id, h.get("name"), h.get("stock_slug"),
                        h.get("sector"), h.get("instrument_type"),
                        _to_numeric(h.get("pct"), 5, 2),
                        h.get("rank", rank), today,
                    )

    # Recursively persist sibling plan (its own instrument_id, its own metadata row,
    # but carries the cross-filled expense_ratio_direct/regular).
    sibling = data.get("sibling")
    if sibling and sibling.get("valid"):
        sib_meta = sibling.setdefault("metadata", {})
        # Propagate the expense pair we already resolved on the primary
        prim_meta = data.get("metadata") or {}
        sib_meta["expense_ratio_direct"] = (
            sib_meta.get("expense_ratio_direct") or prim_meta.get("expense_ratio_direct")
        )
        sib_meta["expense_ratio_regular"] = (
            sib_meta.get("expense_ratio_regular") or prim_meta.get("expense_ratio_regular")
        )
        # Avoid infinite recursion: strip the sibling's own sibling reference
        sibling_copy = {k: v for k, v in sibling.items() if k != "sibling"}
        try:
            await persist_scrape(sibling_copy)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"sibling persist failed for {sibling.get('slug')}: {e}")

    return mf_id


async def log_scrape_attempt(
    *,
    instrument_id: Optional[uuid.UUID],
    instrument_name: str,
    slug: Optional[str],
    status: str,                # ok|partial|failed|skipped
    holdings_count: int = 0,
    validation_issues: Optional[str] = None,
    source: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> None:
    pool = await pg_client.get_pool()
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO scrape_audit_log
                    (instrument_id, instrument_name, slug, status,
                     holdings_count, validation_issues, source, duration_ms)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                """,
                instrument_id, instrument_name, slug, status,
                holdings_count, validation_issues, source, duration_ms,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"scrape audit log insert failed: {e}")


# ── Reads for dashboard + fallback ───────────────────────────────────────
async def load_fund_from_pg(
    *,
    isin: Optional[str] = None,
    scheme_code: Optional[str] = None,
    scheme_name: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Assemble a scrape-shaped dict from Postgres (used as final fallback
    when Redis miss + Mongo miss + Groww failure)."""
    pool = await pg_client.get_pool()
    if pool is None:
        return None
    master = await pg_client.lookup_instrument(
        symbol=scheme_code, isin=isin, instrument_type="MUTUAL_FUND"
    )
    if master is None and scheme_name:
        hits = await pg_client.search_mf_by_name(scheme_name, limit=1)
        master = hits[0] if hits else None
    if master is None:
        return None
    mf_id = master["instrument_id"]
    async with pool.acquire() as conn:
        meta_row = await conn.fetchrow(
            "SELECT * FROM mutual_fund_metadata WHERE instrument_id = $1", mf_id
        )
        ratio_row = await conn.fetchrow(
            "SELECT * FROM mutual_fund_performance_ratios "
            "WHERE instrument_id = $1 ORDER BY ratios_date DESC LIMIT 1",
            mf_id,
        )
        latest_date_row = await conn.fetchrow(
            "SELECT MAX(holding_date) AS d FROM mutual_fund_holdings WHERE instrument_id = $1",
            mf_id,
        )
        holdings_rows: List[asyncpg.Record] = []
        if latest_date_row and latest_date_row["d"]:
            holdings_rows = await conn.fetch(
                "SELECT * FROM mutual_fund_holdings "
                "WHERE instrument_id = $1 AND holding_date = $2 ORDER BY rank ASC",
                mf_id, latest_date_row["d"],
            )
    if not meta_row and not holdings_rows:
        return None
    return _hydrate_from_rows(master, meta_row, ratio_row, holdings_rows)


def _hydrate_from_rows(master, meta, ratios, holdings) -> Dict[str, Any]:
    h_list = [{
        "name": r["holding_name"],
        "stock_slug": r["holding_stock_slug"],
        "sector": r["holding_sector"] or "",
        "instrument_type": r["holding_type"] or "",
        "pct": float(r["weight_percent"]) if r["weight_percent"] is not None else 0,
        "rank": r["rank"],
    } for r in (holdings or [])]
    sector_map: Dict[str, float] = {}
    for h in h_list:
        sec = h["sector"] or "Unclassified"
        sector_map[sec] = sector_map.get(sec, 0.0) + h["pct"]
    sectors = sorted(
        [{"name": k, "pct": round(v, 2)} for k, v in sector_map.items()],
        key=lambda x: x["pct"], reverse=True,
    )
    ratios_dict = {}
    if ratios:
        ratios_dict = {k: float(ratios[k]) if ratios[k] is not None else None
                       for k in ("alpha", "beta", "sharpe", "sortino", "std_dev",
                                 "ret_1y", "ret_3y", "ret_5y")}
    return {
        "scheme_name": master.get("instrument_name"),
        "holdings": h_list,
        "sectors": sectors,
        "split": {},
        "ratios": ratios_dict,
        "metadata": {
            "isin": master.get("isin"),
            "scheme_code": master.get("symbol"),
            "aum_cr": float(meta["aum_cr"]) if meta and meta["aum_cr"] is not None else None,
            "nav": float(meta["nav"]) if meta and meta["nav"] is not None else None,
            "expense_ratio": float(meta["expense_ratio"]) if meta and meta["expense_ratio"] is not None else None,
            "category": meta["category"] if meta else None,
            "risk_label": meta["risk_label"] if meta else None,
        } if meta else {"isin": master.get("isin"), "scheme_code": master.get("symbol")},
        "slug": meta["groww_slug"] if meta else None,
        "fetched_at": (meta["last_scraped_at"].isoformat()
                       if meta and meta["last_scraped_at"] else None),
        "source": "pg",
        "valid": bool(h_list),
    }


# ── Dashboard listings ───────────────────────────────────────────────────
async def list_scraped_funds(limit: int = 200) -> List[Dict[str, Any]]:
    pool = await pg_client.get_pool()
    if pool is None:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT im.instrument_id, im.instrument_name, im.symbol AS scheme_code,
                   im.isin, m.groww_slug, m.aum_cr, m.nav, m.expense_ratio,
                   m.category, m.last_scraped_at,
                   (SELECT COUNT(*) FROM mutual_fund_holdings h
                      WHERE h.instrument_id = im.instrument_id
                        AND h.holding_date = (
                            SELECT MAX(holding_date) FROM mutual_fund_holdings
                            WHERE instrument_id = im.instrument_id
                        )) AS holdings_count
            FROM instrument_master im
            LEFT JOIN mutual_fund_metadata m ON m.instrument_id = im.instrument_id
            WHERE im.instrument_type = 'MUTUAL_FUND'
            ORDER BY m.last_scraped_at DESC NULLS LAST, im.instrument_name
            LIMIT $1
            """,
            limit,
        )
    return [{
        "instrument_id": str(r["instrument_id"]),
        "instrument_name": r["instrument_name"],
        "scheme_code": r["scheme_code"],
        "isin": r["isin"],
        "groww_slug": r["groww_slug"],
        "aum_cr": float(r["aum_cr"]) if r["aum_cr"] is not None else None,
        "nav": float(r["nav"]) if r["nav"] is not None else None,
        "expense_ratio": float(r["expense_ratio"]) if r["expense_ratio"] is not None else None,
        "category": r["category"],
        "holdings_count": r["holdings_count"],
        "last_scraped_at": r["last_scraped_at"].isoformat() if r["last_scraped_at"] else None,
    } for r in rows]


async def list_audit_log(limit: int = 100) -> List[Dict[str, Any]]:
    pool = await pg_client.get_pool()
    if pool is None:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, instrument_id, instrument_name, slug, status, "
            "holdings_count, validation_issues, source, duration_ms, created_at "
            "FROM scrape_audit_log ORDER BY created_at DESC LIMIT $1",
            limit,
        )
    return [{
        "id": str(r["id"]),
        "instrument_id": str(r["instrument_id"]) if r["instrument_id"] else None,
        "instrument_name": r["instrument_name"],
        "slug": r["slug"],
        "status": r["status"],
        "holdings_count": r["holdings_count"],
        "validation_issues": r["validation_issues"],
        "source": r["source"],
        "duration_ms": r["duration_ms"],
        "created_at": r["created_at"].isoformat(),
    } for r in rows]


async def get_fund_detail(instrument_id: str) -> Optional[Dict[str, Any]]:
    pool = await pg_client.get_pool()
    if pool is None:
        return None
    iid = uuid.UUID(instrument_id)
    async with pool.acquire() as conn:
        master = await conn.fetchrow(
            "SELECT * FROM instrument_master WHERE instrument_id = $1", iid
        )
        if master is None:
            return None
        meta = await conn.fetchrow(
            "SELECT * FROM mutual_fund_metadata WHERE instrument_id = $1", iid
        )
        ratios = await conn.fetch(
            "SELECT * FROM mutual_fund_performance_ratios "
            "WHERE instrument_id = $1 ORDER BY ratios_date DESC LIMIT 30",
            iid,
        )
        latest_date = await conn.fetchval(
            "SELECT MAX(holding_date) FROM mutual_fund_holdings WHERE instrument_id = $1",
            iid,
        )
        holdings = []
        if latest_date:
            holdings = await conn.fetch(
                "SELECT rank, holding_name, holding_stock_slug, holding_sector, "
                "holding_type, weight_percent "
                "FROM mutual_fund_holdings "
                "WHERE instrument_id = $1 AND holding_date = $2 "
                "ORDER BY rank ASC",
                iid, latest_date,
            )
        audit = await conn.fetch(
            "SELECT id, slug, status, holdings_count, validation_issues, source, "
            "duration_ms, created_at "
            "FROM scrape_audit_log WHERE instrument_id = $1 "
            "ORDER BY created_at DESC LIMIT 20",
            iid,
        )
    return {
        "instrument": {k: (str(v) if isinstance(v, uuid.UUID) else
                           v.isoformat() if isinstance(v, datetime) else v)
                       for k, v in dict(master).items()},
        "metadata": _row_to_plain(meta) if meta else None,
        "latest_holdings_date": latest_date.isoformat() if latest_date else None,
        "holdings": [_row_to_plain(r) for r in holdings],
        "ratios_history": [_row_to_plain(r) for r in ratios],
        "recent_audit": [{**_row_to_plain(r), "id": str(r["id"])} for r in audit],
    }


# ── helpers ──────────────────────────────────────────────────────────────
def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s).date()
    except (TypeError, ValueError):
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except ValueError:
            return None


def _to_numeric(v: Any, precision: int, scale: int) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        cap = 10 ** (precision - scale) - 0.01
        if abs(f) > cap:
            return cap if f > 0 else -cap
        return round(f, scale)
    except (TypeError, ValueError):
        return None


def _row_to_plain(row) -> Dict[str, Any]:
    if row is None:
        return {}
    out: Dict[str, Any] = {}
    for k, v in dict(row).items():
        if isinstance(v, uuid.UUID):
            out[k] = str(v)
        elif isinstance(v, (datetime, date)):
            out[k] = v.isoformat()
        elif hasattr(v, "__float__"):
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                out[k] = v
        else:
            out[k] = v
    return out
