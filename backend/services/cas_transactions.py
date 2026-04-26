"""CAS transaction extraction + SIP pattern detection.

The casparser.in `/v4/smart/parse` response includes per-scheme transaction
arrays for non-demat MFs (CAMS / KFintech), each with:
  {date, description, type, amount, units, nav, balance}

Until now we only used these to find `buy_date`. This module extracts the
full transactions, normalises them, persists to `cas_transactions`, and
runs a pattern detector to identify SIPs (regular ≥3-month cadence + same
amount + same scheme).

Detected SIPs land in `detected_sips` so the UI can:
  • Show "Active SIP — ₹5,000/mo since Apr 2024" inline on the holding row
  • Surface "Pause / increase" actions in the advisor copilot
  • Track total monthly SIP outflow per client
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Transaction-type taxonomy ────────────────────────────────────────────
# casparser emits free-form `description` + sometimes `type`. Normalise to
# a small enum so downstream queries don't have to deal with string drift.
PURCHASE_KEYWORDS = ("PURCHASE", "INVEST", "SUBSCRIPTION", "ALLOTMENT")
SIP_KEYWORDS = ("SIP", "STP", "SYSTEMATIC")
REDEMPTION_KEYWORDS = ("REDEMPTION", "REDEEM", "WITHDRAW", "SELL")
SWITCH_KEYWORDS = ("SWITCH", "TRANSFER")
DIVIDEND_KEYWORDS = ("DIVIDEND", "IDCW", "PAYOUT")
# Tax / charge-side line items we want to track but exclude from buy-side aggregation
CHARGE_KEYWORDS = ("STAMP", "STT", "TDS", "CHARGE", "FEE", "TAX")

TXN_TYPE_PURCHASE = "PURCHASE"
TXN_TYPE_SIP_PURCHASE = "SIP_PURCHASE"
TXN_TYPE_REDEMPTION = "REDEMPTION"
TXN_TYPE_SWITCH_IN = "SWITCH_IN"
TXN_TYPE_SWITCH_OUT = "SWITCH_OUT"
TXN_TYPE_DIVIDEND = "DIVIDEND"
TXN_TYPE_CHARGE = "CHARGE"
TXN_TYPE_OTHER = "OTHER"


def _classify_txn(t: Dict[str, Any]) -> str:
    raw = (t.get("type") or t.get("description") or "").upper()
    if any(k in raw for k in CHARGE_KEYWORDS):
        return TXN_TYPE_CHARGE
    if any(k in raw for k in DIVIDEND_KEYWORDS):
        return TXN_TYPE_DIVIDEND
    if any(k in raw for k in SWITCH_KEYWORDS):
        # Switch sign convention: positive units → switch_in, negative → switch_out
        try:
            units = float(t.get("units") or 0)
        except (TypeError, ValueError):
            units = 0.0
        return TXN_TYPE_SWITCH_IN if units >= 0 else TXN_TYPE_SWITCH_OUT
    if any(k in raw for k in REDEMPTION_KEYWORDS):
        return TXN_TYPE_REDEMPTION
    if any(k in raw for k in SIP_KEYWORDS):
        return TXN_TYPE_SIP_PURCHASE
    if any(k in raw for k in PURCHASE_KEYWORDS):
        return TXN_TYPE_PURCHASE
    # Fallback: positive units + positive amount → assume purchase
    try:
        units = float(t.get("units") or 0)
        amt = float(t.get("amount") or 0)
    except (TypeError, ValueError):
        units = amt = 0.0
    if units > 0 and amt > 0:
        return TXN_TYPE_PURCHASE
    if units < 0 and amt < 0:
        return TXN_TYPE_REDEMPTION
    return TXN_TYPE_OTHER


def _safe_float(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _norm_date(v) -> Optional[str]:
    if not v:
        return None
    s = str(v)[:10]
    # Already ISO?
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    # dd-mm-yyyy or dd/mm/yyyy
    m = re.match(r"^(\d{2})[-/](\d{2})[-/](\d{4})$", s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return None


# ── Extract transactions from a parsed CAS payload ───────────────────────
def extract_transactions(parsed_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Walk the CAS API response and emit a flat list of normalised txns.

    Returns: list of `{date, scheme_name, isin, folio, amc, type, amount,
    units, nav, balance, raw_description}` dicts. Empty list when no
    folios/transactions are found (e.g., demat-only NSDL CAS).
    """
    out: List[Dict[str, Any]] = []
    for folio in parsed_data.get("mutual_funds") or []:
        amc = (folio.get("amc") or "").strip()
        folio_no = (folio.get("folio_number") or folio.get("folio") or "").strip()
        for scheme in folio.get("schemes") or folio.get("holdings") or []:
            scheme_name = (
                scheme.get("scheme_name")
                or scheme.get("scheme")
                or scheme.get("name")
                or ""
            ).strip()
            isin = (scheme.get("isin") or "").strip()
            for t in scheme.get("transactions") or []:
                if not isinstance(t, dict):
                    continue
                date = _norm_date(t.get("date") or t.get("txn_date") or t.get("transaction_date"))
                if not date:
                    continue
                amount = _safe_float(t.get("amount"))
                units = _safe_float(t.get("units"))
                if amount == 0 and units == 0:
                    continue
                out.append({
                    "date": date,
                    "scheme_name": scheme_name,
                    "isin": isin,
                    "folio": folio_no,
                    "amc": amc,
                    "type": _classify_txn(t),
                    "amount": round(amount, 2),
                    "units": round(units, 4),
                    "nav": round(_safe_float(t.get("nav")), 4),
                    "balance": round(_safe_float(t.get("balance")), 4),
                    "raw_description": (t.get("description") or t.get("type") or "").strip(),
                })
    return out


# ── SIP pattern detector ────────────────────────────────────────────────
# Heuristic: group by (folio, isin/scheme_name), then look for ≥3 purchase
# transactions with similar amounts (±5%) at regular cadence (~28-35 days
# = monthly, ~88-95 days = quarterly).
SIP_AMOUNT_TOLERANCE = 0.05         # 5% — accommodates small NAV-driven drift
SIP_MONTHLY_DAYS = (25, 36)         # inclusive
SIP_QUARTERLY_DAYS = (85, 100)
MIN_SIP_INSTALMENTS = 3             # need ≥3 in a row to call it a SIP


def _avg_gap_days(dates_iso: List[str]) -> Optional[float]:
    if len(dates_iso) < 2:
        return None
    dts = sorted(datetime.fromisoformat(d).date() for d in dates_iso)
    gaps = [(dts[i] - dts[i - 1]).days for i in range(1, len(dts))]
    return sum(gaps) / len(gaps) if gaps else None


def _is_within(value: float, low: float, high: float) -> bool:
    return low <= value <= high


def _classify_cadence(avg_gap: Optional[float]) -> Optional[str]:
    if avg_gap is None:
        return None
    if _is_within(avg_gap, *SIP_MONTHLY_DAYS):
        return "MONTHLY"
    if _is_within(avg_gap, *SIP_QUARTERLY_DAYS):
        return "QUARTERLY"
    return None


def detect_sip_patterns(transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group purchase transactions and emit one detected_sip dict per
    (folio, scheme) that meets the cadence + amount-stability + count
    thresholds. Each result contains:
      {scheme_name, folio, amc, isin, cadence, amount, instalment_count,
       first_date, last_date, total_invested, status, gap_days_avg}
    """
    # Group purchases (incl. SIP_PURCHASE) by key
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for t in transactions:
        if t["type"] not in (TXN_TYPE_PURCHASE, TXN_TYPE_SIP_PURCHASE):
            continue
        if t["amount"] <= 0:
            continue
        key = (t["folio"] or "", t["isin"] or t["scheme_name"])
        groups.setdefault(key, []).append(t)

    sips: List[Dict[str, Any]] = []
    for (folio, sch_key), txns in groups.items():
        if len(txns) < MIN_SIP_INSTALMENTS:
            continue
        # Sort chronological
        txns.sort(key=lambda x: x["date"])
        # Cadence check
        avg_gap = _avg_gap_days([t["date"] for t in txns])
        cadence = _classify_cadence(avg_gap)
        if not cadence:
            continue
        # Amount stability — median ±5%
        amounts = sorted(t["amount"] for t in txns)
        median = amounts[len(amounts) // 2]
        if median <= 0:
            continue
        if not all(
            abs(a - median) / median <= SIP_AMOUNT_TOLERANCE for a in amounts
        ):
            # Allow last instalment to differ (top-up / final NAV diff)
            stable = amounts[:-1]
            if not stable or not all(
                abs(a - median) / median <= SIP_AMOUNT_TOLERANCE for a in stable
            ):
                continue
        # SIP detected
        last = txns[-1]
        first = txns[0]
        # If most recent instalment is > 60 days ago for monthly (or > 120
        # for quarterly), mark as PAUSED — the SIP isn't currently active.
        last_date = datetime.fromisoformat(last["date"]).date()
        today = datetime.now(timezone.utc).date()
        days_since = (today - last_date).days
        cadence_window = 60 if cadence == "MONTHLY" else 120
        status = "ACTIVE" if days_since <= cadence_window else "PAUSED"

        sips.append({
            "scheme_name": last["scheme_name"],
            "folio": folio,
            "amc": last["amc"],
            "isin": last["isin"],
            "cadence": cadence,
            "amount": round(median, 2),
            "instalment_count": len(txns),
            "first_date": first["date"],
            "last_date": last["date"],
            "total_invested": round(sum(t["amount"] for t in txns), 2),
            "status": status,
            "days_since_last": days_since,
            "gap_days_avg": round(avg_gap, 1) if avg_gap else None,
        })
    return sips


# ── Persistence ─────────────────────────────────────────────────────────
async def persist_transactions_and_sips(
    db,
    user_id: str,
    parsed_data: Dict[str, Any],
    *,
    source: str = "CAS",
) -> Dict[str, int]:
    """Extract transactions + detected SIPs and upsert to Mongo.

    Idempotent: keyed by (user_id, folio, isin, date, amount, units) for
    transactions; (user_id, folio, isin) for detected SIPs. Re-uploading
    the same CAS results in `inserted=0, modified>=0` rather than dupes.
    """
    txns = extract_transactions(parsed_data)
    if not txns:
        return {"transactions": 0, "sips": 0}

    # Bulk upsert transactions
    txn_inserted = txn_modified = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    for t in txns:
        key = {
            "user_id": user_id,
            "folio": t["folio"],
            "isin": t["isin"],
            "date": t["date"],
            "amount": t["amount"],
            "units": t["units"],
        }
        update = {
            "$set": {
                **t,
                "user_id": user_id,
                "source": source,
                "last_seen_at": now_iso,
            },
            "$setOnInsert": {"created_at": now_iso},
        }
        r = await db.cas_transactions.update_one(key, update, upsert=True)
        if r.upserted_id is not None:
            txn_inserted += 1
        elif r.modified_count:
            txn_modified += 1

    # Detect + upsert SIPs
    sips = detect_sip_patterns(txns)
    sip_inserted = sip_modified = 0
    for s in sips:
        key = {
            "user_id": user_id,
            "folio": s["folio"],
            "isin": s["isin"] or s["scheme_name"],
        }
        update = {
            "$set": {**s, "user_id": user_id, "detected_at": now_iso},
            "$setOnInsert": {"created_at": now_iso},
        }
        r = await db.detected_sips.update_one(key, update, upsert=True)
        if r.upserted_id is not None:
            sip_inserted += 1
        elif r.modified_count:
            sip_modified += 1

    logger.info(
        f"CAS txns persisted: {txn_inserted} new + {txn_modified} updated · "
        f"SIPs: {sip_inserted} new + {sip_modified} updated"
    )
    return {
        "transactions": len(txns),
        "transactions_new": txn_inserted,
        "transactions_updated": txn_modified,
        "sips": len(sips),
        "sips_new": sip_inserted,
        "sips_updated": sip_modified,
    }
