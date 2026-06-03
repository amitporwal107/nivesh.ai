"""Parse NSE corporate-pledgedata JSON response.

The NSE bulk endpoint returns:
{
  "comNameList": ["Company A", ...],
  "data": [
    {
      "comName": "Company A",
      "shp": "31-Mar-2026",               // shareholding pattern date
      "totIssuedShares": "35286502",       // total issued shares
      "totPromoterHolding": "15893364",    // promoter holding (shares)
      "percPromoterHolding": "    45.04",  // promoter holding %
      "numSharesPledged": "1598704",       // total shares pledged
      "percSharesPledged": "4.53",         // pledged % of total
      "percPromoterShares": "     0.00",   // pledged % of promoter (often 0)
      "percTotShares": "     0.00",        // often 0 in NSE data
      ...
    }, ...
  ]
}

We extract:
  - company_name
  - period_end (from shp)
  - pledged_shares (numSharesPledged)
  - promoter_pledged_to_total_pct = percSharesPledged
  - promoter_pledged_pct = numSharesPledged / totPromoterHolding * 100
    (computed, since percPromoterShares is often 0 in the API response)
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


def parse_pledge_response(body: bytes) -> list[dict[str, Any]]:
    """Parse the bulk NSE pledge data JSON response.

    Returns a list of dicts with:
      company_name, period_end, pledged_shares,
      promoter_pledged_pct, promoter_pledged_to_total_pct
    """
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        logger.error("nse_pledge_data: JSON decode failed: %s", e)
        return []

    records = payload.get("data", [])
    if not isinstance(records, list):
        logger.warning("nse_pledge_data: 'data' is not a list")
        return []

    out: list[dict[str, Any]] = []
    for rec in records:
        if not isinstance(rec, dict):
            continue

        com_name = (rec.get("comName") or "").strip()
        if not com_name:
            continue

        period_end = _parse_nse_date(rec.get("shp"))
        if not period_end:
            continue

        pledged_shares = _safe_int(rec.get("numSharesPledged"))
        tot_issued = _safe_int(rec.get("totIssuedShares"))
        tot_promoter = _safe_int(rec.get("totPromoterHolding"))

        # percSharesPledged = pledged / total × 100 (from NSE)
        pledged_to_total = _safe_float(rec.get("percSharesPledged"))

        # Compute pledged as % of promoter holding ourselves,
        # since percPromoterShares is often 0 in the NSE response.
        # NOTE: numSharesPledged includes ALL pledged shares (not just
        # promoter), so ratio can exceed 100% when public holders also
        # pledge.  Cap at 100% — beyond that the number is unreliable.
        if pledged_shares and tot_promoter and tot_promoter > 0:
            raw_pct = pledged_shares / tot_promoter * 100
            pledged_of_promoter = round(min(raw_pct, 100.0), 4)
        else:
            pledged_of_promoter = _safe_float(rec.get("percPromoterShares"))

        # Skip records where there's genuinely no pledge data
        if pledged_to_total is None and pledged_of_promoter is None and pledged_shares is None:
            continue

        out.append({
            "company_name": com_name,
            "period_end": period_end,
            "pledged_shares": pledged_shares,
            "promoter_pledged_pct": pledged_of_promoter,
            "promoter_pledged_to_total_pct": pledged_to_total,
        })

    return out


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return round(float(str(v).strip()), 4)
    except (ValueError, TypeError):
        return None


def _safe_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(float(str(v).strip()))
    except (ValueError, TypeError):
        return None


def _parse_nse_date(s: Any) -> Optional[date]:
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None
