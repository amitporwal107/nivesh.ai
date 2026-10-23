"""Saved stock screeners — per-user CRUD over MongoDB.

A saved screener stores the natural-language query (the same string the copilot
parser consumes) plus the structured builder conditions so it can be reloaded
into the visual Query Builder for editing. Scoped to the authenticated user.

Endpoints (all under /api):
    GET    /screeners            — list the user's saved screeners (newest first)
    POST   /screeners            — create one
    GET    /screeners/{id}       — fetch one
    PUT    /screeners/{id}       — update name / query / conditions / bucket
    DELETE /screeners/{id}       — delete one
    POST   /screeners/run        — run a rule list on the day's stock data (read-only)
"""
from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from deps import db, get_current_user
from services.copilot_tools import daas_client, stock_intelligence

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


class ScreenerCondition(BaseModel):
    key: str
    op: str = "over"                 # "over" | "under"
    value: str = ""


class ScreenerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    query: str = Field(min_length=1, max_length=600)
    conditions: List[ScreenerCondition] = Field(default_factory=list)
    bucket: Optional[str] = None     # "" | "large" | "mid" | "small" | "micro"


class ScreenerUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    query: Optional[str] = Field(default=None, min_length=1, max_length=600)
    conditions: Optional[List[ScreenerCondition]] = None
    bucket: Optional[str] = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in doc.items() if k != "_id"}


@router.get("/screeners")
async def list_screeners(request: Request) -> List[Dict[str, Any]]:
    user = await get_current_user(request)
    return await db.saved_screeners.find(
        {"user_id": user["user_id"]}, {"_id": 0}
    ).sort("updated_at", -1).to_list(200)


@router.post("/screeners")
async def create_screener(request: Request, payload: ScreenerCreate) -> Dict[str, Any]:
    user = await get_current_user(request)
    now = _now()
    doc = {
        "screener_id": f"scr_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "name": payload.name.strip(),
        "query": payload.query.strip(),
        "conditions": [c.model_dump() for c in payload.conditions],
        "bucket": payload.bucket or "",
        "created_at": now,
        "updated_at": now,
    }
    await db.saved_screeners.insert_one(doc)
    return _clean(doc)


# ── run a screen ─────────────────────────────────────────────────────────────
# A run reads the whole day of nidp.stock_features_daily once, through the same
# data-platform call the chat screener uses (nidp_stock_screener), and shapes the
# matches with the same builder (build_stock_screener_widget), so the screen and
# the chat render one widget contract.
#
# Nothing is filtered on the data platform. The response has to say how many
# stocks carry a value for each rule's metric, and that can only be counted on
# rows no rule has cut yet: a platform-side "ROE >= 20" on a day with no ROE
# returns no rows, which reads the same as "ROE is there, nothing is that high".

# The data platform's page cap (nidp/services/daas_api/responses.py _MAX_LIMIT).
_DAY_READ_LIMIT = 5000
# Request bucket → nidp.stock_features_daily.market_cap_bucket.
_CAP_BUCKETS = {"large": "LARGE_CAP", "mid": "MID_CAP", "small": "SMALL_CAP"}


# Mutual-fund evidence per stock, from the smart-money scanner (nidp.mf_holdings_deltas). The scanner
# covers one index universe (Nifty 500), so a stock outside it has no value for these metrics and fails a
# rule on them, exactly like any other metric the day does not carry. widget key → (scanner field, label).
_MF_UNIVERSE = "nifty500"
_MF_METRICS = {
    "mfChange":   ("mf_shares_pct_chg", "MF holding change"),
    "amcsUp":     ("amcs_up",           "Fund houses raising"),
    "amcsDn":     ("amcs_dn",           "Fund houses cutting"),
    "amcsHolding": ("amcs_holding",     "Fund houses holding"),
}


class ScreenRunCondition(BaseModel):
    key: str = Field(min_length=1, max_length=40)
    op: Literal["over", "under"] = "over"
    value: float = Field(allow_inf_nan=False)      # "20" (the saved shape) or 20


class ScreenRunRequest(BaseModel):
    conditions: List[ScreenRunCondition] = Field(default_factory=list, max_length=50)
    bucket: Optional[Literal["", "large", "mid", "small"]] = None
    sector: Optional[str] = Field(default=None, max_length=60)
    limit: int = Field(default=200, ge=1, le=500)   # matching stocks sent back
    # Add the mutual-fund columns to the rows even when no rule uses them (they are read anyway when one does).
    include_funds: bool = False

    @model_validator(mode="after")
    def _something_to_screen_on(self) -> "ScreenRunRequest":
        if not self.conditions and not self.bucket and not (self.sector or "").strip():
            raise ValueError("a screen needs at least one rule, a size bucket or a sector")
        return self


def _number(value: Any) -> Optional[float]:
    """A metric value as a number; None when the stock has no value for it."""
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def _passes(row: Dict[str, Any], filters: Dict[str, float]) -> bool:
    """The rule the stock_screener widget applies to its rows: bounds are
    inclusive, and a stock with no value for a metric fails a rule on it."""
    for filter_key, bound in filters.items():
        value = _number(row.get(filter_key[:-4]))
        if value is None:
            return False
        if filter_key.endswith("_min") and value < bound:
            return False
        if filter_key.endswith("_max") and value > bound:
            return False
    return True


def _filled(rows: List[Dict[str, Any]], key: str) -> Dict[str, int]:
    return {"filled": sum(1 for r in rows if r.get(key) not in (None, "")), "total": len(rows)}


async def _mf_by_symbol() -> Optional[Dict[str, Dict[str, Any]]]:
    """Scanner rows keyed by symbol, shaped as widget keys. None when the scanner did not answer:
    that is a gap in the evidence, never "no fund activity"."""
    if not daas_client.is_configured():
        return None
    try:
        status, body = await daas_client.get_raw(
            "/desk/smart-money/scanner", {"window": "3M", "universe": _MF_UNIVERSE, "limit": 500})
    except Exception as exc:  # noqa: BLE001
        logger.warning("screeners.run: the smart-money scanner read failed: %r", exc)
        return None
    rows = body.get("rows") if status == 200 and isinstance(body, dict) else None
    if not isinstance(rows, list):
        logger.warning("screeners.run: the smart-money scanner answered HTTP %s", status)
        return None
    return {
        str(r["symbol"]).upper(): {k: _number(r.get(src)) for k, (src, _label) in _MF_METRICS.items()}
        for r in rows if isinstance(r, dict) and r.get("symbol")
    }


@router.post("/screeners/run")
async def run_screener(request: Request, payload: ScreenRunRequest) -> Dict[str, Any]:
    await get_current_user(request)

    # The widget's own label map lists every metric a row carries.
    catalog = stock_intelligence.build_stock_screener_widget([])
    unknown = sorted({c.key for c in payload.conditions} - set(catalog["filter_labels"]) - set(_MF_METRICS))
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown screening metric: {', '.join(unknown)}")

    # "over" → <key>_min, "under" → <key>_max: the filter keys the widget reads.
    # Two rules on the same side of one metric keep the stricter bound (they are ANDed).
    filters: Dict[str, float] = {}
    for c in payload.conditions:
        if c.op == "over":
            filters[f"{c.key}_min"] = max(filters.get(f"{c.key}_min", c.value), c.value)
        else:
            filters[f"{c.key}_max"] = min(filters.get(f"{c.key}_max", c.value), c.value)

    try:
        fetched = await stock_intelligence.nidp_stock_screener(sort_by="market_cap_cr", limit=_DAY_READ_LIMIT)
    except Exception as exc:  # noqa: BLE001
        logger.error("screeners.run: the stock feature read failed: %r", exc)
        fetched = {"rows": [], "as_of_date": None, "ok": False}
    if not fetched.get("ok", True):
        # Same signal the chat screener gets: the source did not answer. Not a zero-match result.
        return {
            "ok": False, "as_of_date": None,
            "widget": stock_intelligence.build_stock_screener_widget([], initial_filters=filters),
            "coverage": {}, "matched": None, "universe_complete": False,
        }

    raw_rows: List[Dict[str, Any]] = fetched.get("rows") or []
    as_of = fetched.get("as_of_date")
    # Widget-keyed rows, one per raw row and in the same order.
    day = stock_intelligence.build_stock_screener_widget(raw_rows)["universe"]

    wants_funds = payload.include_funds or any(c.key in _MF_METRICS for c in payload.conditions)
    if wants_funds:
        mf = await _mf_by_symbol()
        for row in day:
            found = (mf or {}).get(str(row.get("ticker") or "").upper(), {})
            row.update({k: found.get(k) for k in _MF_METRICS})

    coverage_keys = [col["key"] for col in catalog["columns"]] + [c.key for c in payload.conditions]
    if wants_funds:
        coverage_keys += list(_MF_METRICS)
    coverage = {key: _filled(day, key) for key in dict.fromkeys(coverage_keys)}
    cap_bucket = _CAP_BUCKETS.get(payload.bucket or "")
    if cap_bucket:
        coverage["bucket"] = _filled(raw_rows, "market_cap_bucket")

    sector = (payload.sector or "").strip().lower()
    matched = [
        i for i, row in enumerate(day)
        if (not cap_bucket or raw_rows[i].get("market_cap_bucket") == cap_bucket)
        and (not sector or sector in str(row.get("sector") or "").lower())
        and _passes(row, filters)
    ]

    # Largest companies first (the widget's default order), then ticker, so the
    # cut at `limit` keeps the same stocks on every run even when market cap is empty.
    def _largest_first(i: int):
        mcap = _number(day[i].get("mcap"))
        return (mcap is None, -(mcap or 0.0), str(day[i].get("ticker") or ""))

    matched.sort(key=_largest_first)
    widget = stock_intelligence.build_stock_screener_widget(
        [raw_rows[i] for i in matched[:payload.limit]], initial_filters=filters, as_of_date=as_of,
    )
    if wants_funds:
        # The widget builder only knows the feature-store columns; carry the fund metrics across.
        for row, i in zip(widget["universe"], matched[:payload.limit]):
            row.update({k: day[i].get(k) for k in _MF_METRICS})
    return {
        "ok": True,
        "as_of_date": as_of,
        "widget": widget,
        "coverage": coverage,
        "matched": len(matched),
        # False when the read filled the data platform's page: later stocks were not screened.
        "universe_complete": len(raw_rows) < _DAY_READ_LIMIT,
    }


@router.get("/screeners/{screener_id}")
async def get_screener(request: Request, screener_id: str) -> Dict[str, Any]:
    user = await get_current_user(request)
    doc = await db.saved_screeners.find_one(
        {"screener_id": screener_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Screener not found")
    return doc


@router.put("/screeners/{screener_id}")
async def update_screener(request: Request, screener_id: str, payload: ScreenerUpdate) -> Dict[str, Any]:
    user = await get_current_user(request)
    changes: Dict[str, Any] = {}
    if payload.name is not None:       changes["name"] = payload.name.strip()
    if payload.query is not None:      changes["query"] = payload.query.strip()
    if payload.conditions is not None: changes["conditions"] = [c.model_dump() for c in payload.conditions]
    if payload.bucket is not None:     changes["bucket"] = payload.bucket
    if not changes:
        raise HTTPException(status_code=400, detail="No fields to update")
    changes["updated_at"] = _now()
    res = await db.saved_screeners.update_one(
        {"screener_id": screener_id, "user_id": user["user_id"]},
        {"$set": changes},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Screener not found")
    return await db.saved_screeners.find_one(
        {"screener_id": screener_id, "user_id": user["user_id"]}, {"_id": 0}
    )


@router.delete("/screeners/{screener_id}")
async def delete_screener(request: Request, screener_id: str) -> Dict[str, str]:
    user = await get_current_user(request)
    res = await db.saved_screeners.delete_one(
        {"screener_id": screener_id, "user_id": user["user_id"]}
    )
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Screener not found")
    return {"status": "deleted", "screener_id": screener_id}
