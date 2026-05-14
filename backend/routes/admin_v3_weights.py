"""Admin endpoints for V3.1 category-aware weight configuration.

  GET  /api/admin/v3-weights              — return current weights config
  PUT  /api/admin/v3-weights              — replace full config
  POST /api/admin/v3-weights/reset        — restore defaults
"""
from __future__ import annotations
import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from deps import db, require_admin
from services import v3_weights

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


class WeightsPayload(BaseModel):
    weights: Dict[str, Dict[str, Dict[str, float]]]


def _summary() -> Dict[str, Any]:
    cfg = v3_weights.get_full_config()
    summary = {}
    for cat, dims in cfg.items():
        summary[cat] = {}
        for dim, wmap in dims.items():
            summary[cat][dim] = {
                "weights": wmap,
                "total": sum(wmap.values()),
                "components": list(wmap.keys()),
            }
    return summary


@router.get("/admin/v3-weights")
async def get_v3_weights(request: Request):
    await require_admin(request)
    return {
        "weights": v3_weights.get_full_config(),
        "defaults": v3_weights.DEFAULT_WEIGHTS,
        "summary": _summary(),
    }


@router.put("/admin/v3-weights")
async def put_v3_weights(request: Request, payload: WeightsPayload):
    await require_admin(request)
    cfg = payload.weights
    # Minimal validation — each dimension's weights should sum to 100 ± 0.5
    issues = []
    for cat, dims in cfg.items():
        for dim, wmap in dims.items():
            total = sum(wmap.values())
            if abs(total - 100) > 0.5:
                issues.append(f"{cat}.{dim} sums to {total}, expected 100")
    if issues:
        raise HTTPException(status_code=422, detail={"issues": issues})

    # Apply each weight map atomically
    for cat, dims in cfg.items():
        for dim, wmap in dims.items():
            v3_weights.set_weights(cat, dim, {k: int(round(v)) for k, v in wmap.items()})
    await v3_weights.save_to_db(db)
    logger.info("v3-weights updated; categories=%s", list(cfg))
    return {"status": "ok", "weights": v3_weights.get_full_config()}


@router.post("/admin/v3-weights/reset")
async def reset_v3_weights(request: Request):
    await require_admin(request)
    v3_weights.reset_to_defaults()
    await v3_weights.save_to_db(db)
    return {"status": "ok", "weights": v3_weights.get_full_config()}
