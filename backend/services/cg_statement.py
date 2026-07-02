"""Realised Capital-Gains statement formatter (epic 0.12 / WORK-0081).

Pure function: takes the FIFO engine's realised events (TaxEvent, as dicts) and
produces a scheme-wise statement in the LOCKED broker/depository layout
(see .claude/workspace/advisory-workflows/cg-statement-format-spec.md):
  A. Short-Term equity (Sec 111A)   B. Long-Term equity (Sec 112A)   C. Summary
Dependency-light (only tax_constants) so it is unit-testable in isolation.

Known data gaps (surfaced, not faked): `expenses_rs` (brokerage/STT — not in
TaxEvent, sourced from CAS later → shown as 0), and grandfathering
`fmv_31jan18_rs` / `cost_for_ltcg_rs` (equity acquired < 01-Feb-2018). Debt-MF
sections are a follow-on. Rates/exemption come from the single source of truth
(tax_constants: FY25-26 STCG 20%, LTCG 12.5%, exemption Rs 1.25L).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from services.tax_constants import (
        EQUITY_STCG_RATE, EQUITY_LTCG_RATE, EQUITY_LTCG_EXEMPTION,
    )
except ImportError:  # standalone import (from within backend/services/)
    from tax_constants import (  # type: ignore
        EQUITY_STCG_RATE, EQUITY_LTCG_RATE, EQUITY_LTCG_EXEMPTION,
    )


def _fmt_date(v: Any) -> Optional[str]:
    if isinstance(v, datetime):
        return v.date().isoformat()
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def _mask_pan(pan: Optional[str]) -> Optional[str]:
    if not pan or len(pan) < 10:
        return pan
    return pan[:0] + "XXXXX" + pan[5:]  # ABCDE1234F -> XXXXX1234F


def _row(sr: int, e: Dict[str, Any], *, long_term: bool) -> Dict[str, Any]:
    qty = float(e.get("qty") or 0)
    bp = float(e.get("buy_price") or 0)
    sp = float(e.get("sell_price") or 0)
    purchase_value = round(bp * qty, 2)
    row = {
        "sr": sr,
        "isin": e.get("symbol"),
        "scheme_name": e.get("scheme_name") or e.get("symbol"),
        "qty": round(qty, 4),
        "purchase_date": _fmt_date(e.get("buy_date")),
        "purchase_rate_rs": round(bp, 4),
        "purchase_value_rs": purchase_value,
        "sale_date": _fmt_date(e.get("sell_date")),
        "sale_rate_rs": round(sp, 4),
        "sale_value_rs": round(sp * qty, 2),
        "expenses_rs": round(float(e.get("expenses_rs") or 0), 2),   # GAP: from CAS later
        "days_held": e.get("holding_period_days"),
        "gain_rs": round(float(e.get("gain_rs") or 0), 2),
    }
    if long_term:  # Sec 112A grandfathering columns (GAP: surfaced from engine later)
        row["fmv_31jan18_rs"] = e.get("fmv_31jan18_rs")               # None = NA (acquired >= 01-Feb-2018)
        row["cost_for_ltcg_rs"] = round(float(e.get("cost_for_ltcg_rs") or purchase_value), 2)
    return row


def _section_total(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    return {
        "purchase_value_rs": round(sum(r["purchase_value_rs"] for r in rows), 2),
        "sale_value_rs": round(sum(r["sale_value_rs"] for r in rows), 2),
        "expenses_rs": round(sum(r["expenses_rs"] for r in rows), 2),
        "gain_rs": round(sum(r["gain_rs"] for r in rows), 2),
    }


def build_statement(
    events: List[Dict[str, Any]], *, fy_label: str,
    holder: Optional[str] = None, pan: Optional[str] = None,
    period: Optional[str] = None, generated_on: Optional[str] = None,
) -> Dict[str, Any]:
    """Shape realised FIFO events into the locked A/B/C statement layout."""
    stcg = [e for e in events if (e.get("tax_type") or "").upper() == "STCG"]
    ltcg = [e for e in events if (e.get("tax_type") or "").upper() == "LTCG"]
    rows_a = [_row(i + 1, e, long_term=False) for i, e in enumerate(stcg)]
    rows_b = [_row(i + 1, e, long_term=True) for i, e in enumerate(ltcg)]

    st_total = round(sum(r["gain_rs"] for r in rows_a), 2)
    lt_total = round(sum(r["gain_rs"] for r in rows_b), 2)
    exemption = round(min(max(lt_total, 0.0), EQUITY_LTCG_EXEMPTION), 2)
    lt_taxable = round(max(0.0, lt_total - EQUITY_LTCG_EXEMPTION), 2)
    est_tax = round(max(0.0, st_total) * EQUITY_STCG_RATE + lt_taxable * EQUITY_LTCG_RATE, 2)

    return {
        "header": {
            "statement": "Capital Gain / (Loss) Statement",
            "holder": holder, "pan": _mask_pan(pan),
            "period": period, "fy": fy_label, "generated_on": generated_on,
        },
        "sections": {
            "A_stcg_equity": {
                "section": "111A",
                "title": "Short Term Capital Gains — Equity (holding ≤ 12 months, Sec 111A)",
                "rows": rows_a, "total": _section_total(rows_a),
            },
            "B_ltcg_equity": {
                "section": "112A",
                "title": "Long Term Capital Gains — Equity (holding > 12 months, Sec 112A)",
                "rows": rows_b, "total": _section_total(rows_b),
            },
        },
        "summary": [
            {"particulars": "Short Term Capital Gain / (Loss) — equity, STT paid", "section": "111A", "amount_rs": st_total},
            {"particulars": "Long Term Capital Gain / (Loss) — equity, STT paid", "section": "112A", "amount_rs": lt_total},
            {"particulars": "Total Capital Gain / (Loss)", "section": "", "amount_rs": round(st_total + lt_total, 2)},
            {"particulars": f"LTCG exemption u/s 112A (up to Rs {EQUITY_LTCG_EXEMPTION:,.0f})", "section": "112A", "amount_rs": exemption},
            {"particulars": "Taxable LTCG after exemption", "section": "112A", "amount_rs": lt_taxable},
        ],
        "estimated_tax_rs": est_tax,
        "notes": [
            "Gains computed on FIFO basis.",
            "Grandfathering (FMV as on 31-Jan-2018) applies for eligible equity units acquired before 01-Feb-2018 (Sec 112A).",
            "Indicative computation for planning — not a tax-filing document; confirm with your broker/RTA capital-gains statement.",
        ],
        "data_gaps": [
            "expenses_rs (brokerage/STT) not yet sourced from CAS transactions — shown as 0.",
            "fmv_31jan18_rs / cost_for_ltcg_rs (equity grandfathering) pending surfacing from capital_gains_engine.",
            "Debt-MF STCG/LTCG (Sec 50AA / indexed cost) sections are a follow-on.",
        ],
    }
