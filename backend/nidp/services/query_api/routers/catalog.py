"""Catalog endpoint — every NIDP table's row count + first/last date,
plus by-domain rollup. Mirrors the payload shape the React
NidpCatalogPanel already binds to. The wealth-advisor API service
proxies this through /api/admin/nidp/catalog."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import logging

from fastapi import APIRouter, Depends

from nidp.shared.storage.pg import get_pool
from nidp.services.query_api.auth import require_bearer


logger = logging.getLogger(__name__)
router = APIRouter(prefix="", tags=["catalog"], dependencies=[Depends(require_bearer)])


# (table, date_col_or_None, domain). sector_master + document_chunks
# have no row-level ingestion date worth surfacing — count-only.
_CATALOG_TABLES: List[Tuple[str, Optional[str], str]] = [
    ("prices_eod",                "as_of_date",   "Market data"),
    ("prices_eod_adjusted",       "as_of_date",   "Market data"),
    ("delivery_data",             "as_of_date",   "Market data"),
    ("index_eod",                 "as_of_date",   "Market data"),
    ("fno_bhavcopy",              "as_of_date",   "Market data"),
    ("fii_dii_flows",             "as_of_date",   "Flows & events"),
    ("bulk_deals",                "as_of_date",   "Flows & events"),
    ("block_deals",               "as_of_date",   "Flows & events"),
    ("corporate_actions",         "ex_date",      "Flows & events"),
    ("index_constituents",        "as_of_date",   "Reference"),
    ("nse_holidays",              "holiday_date", "Reference"),
    ("sector_master",             None,           "Reference"),
    ("nse_financials_quarterly",  "period_end",   "Fundamentals"),
    ("shareholding_pattern",      "as_of_date",   "Fundamentals"),
    ("rbi_yields",                "as_of_date",   "Macro"),
    ("fred_macro",                "as_of_date",   "Macro"),
    ("corporate_announcements",   "filed_at",     "Disclosure"),
    ("documents",                 "ingested_at",  "Disclosure"),
    ("document_chunks",           None,           "Disclosure"),
    ("stock_features_daily",      "as_of_date",   "Derived"),
    ("market_daily_snapshot",     "as_of_date",   "Derived"),
    ("stock_daily_snapshot",      "as_of_date",   "Derived"),
]


@router.get("/catalog")
async def catalog() -> Dict[str, Any]:
    pool = await get_pool()

    async with pool.acquire() as conn:
        tables_out: List[Dict[str, Any]] = []
        for tbl, datecol, domain in _CATALOG_TABLES:
            try:
                if datecol:
                    row = await conn.fetchrow(
                        f"SELECT count(*) AS rows, "
                        f"min({datecol})::text AS first_at, "
                        f"max({datecol})::text AS last_at "
                        f"FROM nidp.{tbl}"
                    )
                else:
                    row = await conn.fetchrow(
                        f"SELECT count(*) AS rows, NULL::text AS first_at, "
                        f"NULL::text AS last_at FROM nidp.{tbl}"
                    )
                tables_out.append({
                    "table":    tbl,
                    "domain":   domain,
                    "date_col": datecol,
                    "rows":     row["rows"],
                    "first_at": row["first_at"],
                    "last_at":  row["last_at"],
                    "error":    None,
                })
            except Exception as e:                                    # noqa: BLE001
                tables_out.append({
                    "table":    tbl,
                    "domain":   domain,
                    "date_col": datecol,
                    "rows":     None,
                    "first_at": None,
                    "last_at":  None,
                    "error":    str(e)[:200],
                })

    by_domain: Dict[str, Dict[str, Any]] = {}
    for t in tables_out:
        d = t["domain"]
        agg = by_domain.setdefault(d, {
            "domain": d, "tables": 0, "rows": 0,
            "earliest": None, "latest": None,
        })
        agg["tables"] += 1
        if t["rows"] is not None:
            agg["rows"] += t["rows"]
        if t["first_at"]:
            agg["earliest"] = t["first_at"] if agg["earliest"] is None else min(agg["earliest"], t["first_at"])
        if t["last_at"]:
            agg["latest"]   = t["last_at"]  if agg["latest"]   is None else max(agg["latest"],   t["last_at"])

    return {
        "as_of":     datetime.utcnow().isoformat() + "Z",
        "totals":    {"tables": len(tables_out)},
        "by_domain": list(by_domain.values()),
        "tables":    tables_out,
    }
