"""Admin endpoints for allocation band configuration.

  GET  /api/admin/allocation-bands          — current bands + defaults
  PUT  /api/admin/allocation-bands          — replace full config
  POST /api/admin/allocation-bands/reset    — restore defaults
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from deps import db, require_admin
from services import allocation_bands

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

TIERS = allocation_bands.TIERS
ASSETS = allocation_bands.ASSETS


class BandsPayload(BaseModel):
    bands: Dict[str, Dict[str, Dict[str, float]]]


def _validate_bands(bands: Dict[str, Any]) -> list[str]:
    """Return a list of validation error strings, empty if valid."""
    errors: list[str] = []
    for tier in TIERS:
        if tier not in bands:
            errors.append(f"Missing tier: {tier}")
            continue
        asset_map = bands[tier]
        for asset in ASSETS:
            if asset not in asset_map:
                errors.append(f"{tier}.{asset} missing")
                continue
            b = asset_map[asset]
            mn, tgt, mx = b.get("min"), b.get("target"), b.get("max")
            if None in (mn, tgt, mx):
                errors.append(f"{tier}.{asset} missing min/target/max")
                continue
            if not (0 <= mn <= tgt <= mx <= 100):
                errors.append(
                    f"{tier}.{asset}: must satisfy 0 ≤ min({mn}) ≤ target({tgt}) ≤ max({mx}) ≤ 100"
                )
    return errors


@router.get("/admin/allocation-bands")
async def get_allocation_bands(request: Request):
    await require_admin(request)
    return {
        "bands": allocation_bands.get_bands(),
        "defaults": allocation_bands.DEFAULT_BANDS,
        "tiers": TIERS,
        "assets": list(ASSETS),
    }


@router.put("/admin/allocation-bands")
async def put_allocation_bands(request: Request, payload: BandsPayload):
    await require_admin(request)
    errors = _validate_bands(payload.bands)
    if errors:
        raise HTTPException(status_code=422, detail={"validation_errors": errors})
    allocation_bands.update_in_memory(payload.bands)
    await allocation_bands.save_to_db(db)
    logger.info("allocation_bands updated via admin PUT")
    return {"ok": True, "bands": allocation_bands.get_bands()}


@router.post("/admin/allocation-bands/reset")
async def reset_allocation_bands(request: Request):
    await require_admin(request)
    allocation_bands.reset_to_defaults()
    await allocation_bands.save_to_db(db)
    logger.info("allocation_bands reset to defaults via admin POST")
    return {"ok": True, "bands": allocation_bands.get_bands()}
