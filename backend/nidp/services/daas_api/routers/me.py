"""Self-service introspection: who am I, how much have I used."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import jsonify


router = APIRouter(prefix="/me", tags=["meta"], dependencies=[Depends(require_api_key)])


@router.get("", summary="Identity + plan + current rate-limit state")
async def me(request: Request) -> Dict[str, Any]:
    rec = request.state.daas_key
    decision = request.state.daas_decision
    return {
        "key_id":        rec.key_id,
        "key_prefix":    rec.key_prefix,
        "name":          rec.name,
        "owner_email":   rec.owner_email,
        "plan":          rec.plan,
        "rate_limit": {
            "limit_rpm":       rec.rate_limit_rpm,
            "remaining_rpm":   decision.remaining_rpm,
            "reset_seconds":   decision.reset_seconds,
        },
        "daily_quota": {
            "limit":     rec.daily_quota,
            "used":      decision.daily_used,
            "remaining": decision.daily_remaining,
        },
        "expires_at":    jsonify(rec.expires_at),
    }


@router.get("/usage", summary="Daily request counts for the last N days")
async def usage(request: Request, days: int = 30) -> Dict[str, Any]:
    if days < 1 or days > 90:
        days = 30
    rec = request.state.daas_key
    pool = await get_pool()
    cutoff = date.today() - timedelta(days=days - 1)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT day, request_count, error_count, last_request_at
              FROM nidp.daas_daily_usage
             WHERE key_id = $1 AND day >= $2
             ORDER BY day DESC
            """,
            rec.key_id, cutoff,
        )
    by_day = {
        r["day"].isoformat(): {
            "requests": int(r["request_count"]),
            "errors":   int(r["error_count"]),
            "last_request_at": jsonify(r["last_request_at"]),
        }
        for r in rows
    }
    # Fill gap days with zeros so callers can plot a continuous series.
    series = []
    total_requests = 0
    total_errors = 0
    for offset in range(days):
        d = (date.today() - timedelta(days=offset)).isoformat()
        cell = by_day.get(d) or {"requests": 0, "errors": 0, "last_request_at": None}
        series.append({"day": d, **cell})
        total_requests += cell["requests"]
        total_errors += cell["errors"]
    return {
        "key_id":  rec.key_id,
        "days":    days,
        "totals":  {"requests": total_requests, "errors": total_errors},
        "series":  series,
    }
