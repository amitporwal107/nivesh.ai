"""FLOW LEDGER auto-fill — app-side proxy to the NIDP DaaS.

The tracker runs in the browser and the DaaS is key-gated, so the key cannot go to
the client. This forwards the auto-fill endpoints and nothing else.

Deliberately NOT best-effort. ``copilot_widgets._daas_get`` returns None on any
failure so a widget can degrade quietly — right for a widget, wrong here: this
endpoint's whole job is to report what NIDP knows, so a silent None would render as
"no data for this symbol" and be indistinguishable from a real, correct gap. A
failure to reach NIDP is reported as a failure to reach NIDP.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict

import httpx
from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/flows", tags=["flow-ledger"])

_DAAS_URL = (
    os.environ.get("NIDP_DAAS_BASE_URL")
    or os.environ.get("NIDP_DAAS_URL")
    or "https://staging-data.niveshcopilot.com/daas"
).rstrip("/")

# The admin UI registers the key as NIDP_DAAS_INTERNAL_TOKEN while Cloud Run may use
# NIDP_DAAS_API_KEY. Reading only one leaves this empty on the other deployment and
# every call fails auth — the same asymmetry that silently killed copilot_widgets.
_DAAS_KEY = (
    os.environ.get("NIDP_DAAS_API_KEY")
    or os.environ.get("NIDP_DAAS_INTERNAL_TOKEN")
    or ""
)

# Symbols and sector names only. Anything else is rejected here rather than
# forwarded, so this proxy can never be used to reach an arbitrary DaaS path.
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9&\-]{1,24}$")
_SECTOR_RE = re.compile(r"^[A-Za-z][A-Za-z ]{1,48}$")


async def _daas_get(path: str, timeout: float = 20.0) -> Dict[str, Any]:
    if not _DAAS_KEY:
        raise HTTPException(
            status_code=503,
            detail="NIDP data service is not configured on this deployment")
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{_DAAS_URL}{path}",
                                    headers={"X-API-Key": _DAAS_KEY})
    except Exception as e:                                          # noqa: BLE001
        logger.warning("flow-ledger DaaS GET %s failed: %s", path, e)
        raise HTTPException(status_code=502,
                            detail="Could not reach the NIDP data service")
    if resp.status_code != 200:
        logger.info("flow-ledger DaaS GET %s -> %s", path, resp.status_code)
        raise HTTPException(
            status_code=502,
            detail=f"NIDP data service returned {resp.status_code}")
    return resp.json()


def _unwrap(payload: Dict[str, Any]) -> Dict[str, Any]:
    """DaaS wraps rows in an envelope; the tracker wants the single row."""
    data = payload.get("data")
    if isinstance(data, list):
        if not data:
            raise HTTPException(status_code=404, detail="No ledger data returned")
        return data[0]
    return payload


@router.get("/ledger/company/{symbol}")
async def company_ledger(symbol: str) -> Dict[str, Any]:
    if not _SYMBOL_RE.match(symbol or ""):
        raise HTTPException(status_code=400, detail=f"invalid symbol {symbol!r}")
    return _unwrap(await _daas_get(f"/v1/flows/ledger/company/{symbol.upper()}"))


@router.get("/ledger/sector/{sector}")
async def sector_ledger(sector: str) -> Dict[str, Any]:
    if not _SECTOR_RE.match(sector or ""):
        raise HTTPException(status_code=400, detail=f"invalid sector {sector!r}")
    return _unwrap(await _daas_get(f"/v1/flows/ledger/sector/{sector}"))


@router.get("/ledger/sectors")
async def list_sectors() -> Dict[str, Any]:
    payload = await _daas_get("/v1/flows/ledger/sectors")
    return {"sectors": payload.get("data", [])}
