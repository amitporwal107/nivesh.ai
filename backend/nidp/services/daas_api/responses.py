"""Shared response helpers + pagination + date coercion."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Query


_MAX_LIMIT = 5_000
_DEFAULT_LIMIT = 100


def page_params(
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT, description=f"Rows to return (1–{_MAX_LIMIT})"),
    offset: int = Query(0, ge=0, le=1_000_000, description="Rows to skip"),
) -> Dict[str, int]:
    return {"limit": limit, "offset": offset}


def parse_date(s: Optional[str], *, field: str) -> Optional[date]:
    if s is None or s == "":
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field} must be YYYY-MM-DD")


def jsonify(value: Any) -> Any:
    """Coerce DB row values into JSON-safe primitives. asyncpg returns
    Decimal/datetime/date — the API contract is strings/numbers."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat() if value.tzinfo else value.isoformat() + "Z"
    if isinstance(value, date):
        return value.isoformat()
    return value


def row_to_dict(row: Any) -> Dict[str, Any]:
    return {k: jsonify(v) for k, v in dict(row).items()}


def envelope(
    data: List[Dict[str, Any]],
    *,
    limit: int,
    offset: int,
    total: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "data":   data,
        "count":  len(data),
        "pagination": {
            "limit":   limit,
            "offset":  offset,
            "total":   total,
            "next_offset": offset + limit if (len(data) == limit and (total is None or offset + limit < total)) else None,
        },
        "as_of":  datetime.utcnow().isoformat() + "Z",
    }
    if extra:
        out.update(extra)
    return out


def normalise_symbol(s: str) -> str:
    """NSE symbols are upper-case, alphanumeric. We don't strip suffix
    series here — that's an explicit `series` query param."""
    return s.strip().upper()
