"""Latest validation runs per (ingester, date)."""
from __future__ import annotations

from typing import Any, Dict, List
import logging

from fastapi import APIRouter, Depends, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.query_api.auth import require_bearer


logger = logging.getLogger(__name__)
router = APIRouter(prefix="", tags=["validation"], dependencies=[Depends(require_bearer)])


@router.get("/validation")
async def validation(limit: int = Query(50, ge=1, le=500)) -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch("""
                SELECT ingester, target_date, status,
                       rules_run, rules_failed, findings_count, started_at
                  FROM nidp.v_latest_validation
                 ORDER BY started_at DESC
                 LIMIT $1
            """, limit)
        except Exception as e:                                        # noqa: BLE001
            logger.warning("validation: query failed: %s", e)
            return {"validation": [], "error": str(e)[:200]}

    out: List[Dict[str, Any]] = [
        {
            "ingester":       r["ingester"],
            "target_date":    r["target_date"].isoformat() if r["target_date"] else None,
            "status":         r["status"],
            "rules_run":      r["rules_run"],
            "rules_failed":   r["rules_failed"],
            "findings_count": r["findings_count"],
            "started_at":     r["started_at"].isoformat() if r["started_at"] else None,
        }
        for r in rows
    ]
    return {"validation": out, "error": None}
