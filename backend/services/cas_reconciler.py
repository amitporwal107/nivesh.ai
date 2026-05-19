"""Reconciliation checks for parsed CAS extractions.

Verifies that the numbers the parser pulled out of the PDF agree with
each other and with the printed statement totals. When a section fails
reconciliation the hybrid parser re-runs Vision on that section only.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List

from services.cas_schema import CASExtraction

logger = logging.getLogger(__name__)


# Per-row tolerance — paise rounding can produce small drift between
# `num_units × nav` and the printed `value`.
ROW_TOLERANCE_PCT = 0.02   # 2 %

# Section vs grand total tolerance — printed grand total may net out
# pledged units, locked-in MFs, or unsettled credits.
TOTAL_TOLERANCE_PCT = 0.05  # 5 %


@dataclass
class ReconResult:
    ok: bool
    dirty_sections: List[str] = field(default_factory=list)
    row_warnings: List[str] = field(default_factory=list)
    total_warnings: List[str] = field(default_factory=list)


def _row_ok(qty, price, value) -> bool:
    if qty is None or price is None or value is None:
        return True  # nothing to check — assume ok
    if not qty or not price:
        return True
    expected = qty * price
    if value == 0:
        return expected < 1.0  # both zero-ish
    return abs(expected - value) / abs(value) <= ROW_TOLERANCE_PCT


def reconcile(extraction: CASExtraction) -> ReconResult:
    """Run all sanity checks on a CASExtraction. Returns a ReconResult
    whose `dirty_sections` lists section names worth re-extracting."""
    result = ReconResult(ok=True)

    h = extraction.holdings

    # ── 1. Per-row consistency: qty × price ≈ value ─────────────────
    for row in h.equities:
        if not _row_ok(row.num_shares, row.market_price_inr, row.value_inr):
            msg = (f"equity row '{row.company_name}' "
                   f"qty={row.num_shares} px={row.market_price_inr} "
                   f"val={row.value_inr}")
            result.row_warnings.append(msg)
            if "equities" not in result.dirty_sections:
                result.dirty_sections.append("equities")

    for row in h.preference_shares:
        if not _row_ok(row.num_shares, row.market_price_inr, row.value_inr):
            result.row_warnings.append(f"pref row '{row.company_name}'")
            if "preference_shares" not in result.dirty_sections:
                result.dirty_sections.append("preference_shares")

    for row in h.sovereign_gold_bonds:
        if not _row_ok(row.num_units, row.market_price_per_unit_inr, row.value_inr):
            result.row_warnings.append(f"sgb row '{row.series or row.isin}'")
            if "sovereign_gold_bonds" not in result.dirty_sections:
                result.dirty_sections.append("sovereign_gold_bonds")

    for row in h.mutual_funds_demat:
        if not _row_ok(row.num_units, row.nav_inr, row.value_inr):
            result.row_warnings.append(f"mf-demat row '{row.fund_name}'")
            if "mutual_funds_demat" not in result.dirty_sections:
                result.dirty_sections.append("mutual_funds_demat")

    for row in h.mutual_fund_folios:
        if not _row_ok(row.num_units, row.current_nav_inr, row.current_value_inr):
            result.row_warnings.append(f"mf-folio row '{row.fund_name}'")
            if "mutual_fund_folios" not in result.dirty_sections:
                result.dirty_sections.append("mutual_fund_folios")

    # ── 2. Section sum vs grand total ───────────────────────────────
    printed_total = (
        extraction.portfolio_summary.total_value_inr
        if extraction.portfolio_summary else None
    )
    holdings_total = extraction.total_holding_value()
    if printed_total and holdings_total > 0:
        drift = abs(holdings_total - printed_total) / printed_total
        if drift > TOTAL_TOLERANCE_PCT:
            msg = (f"grand_total mismatch: holdings_sum={holdings_total:,.2f} "
                   f"printed={printed_total:,.2f} drift={drift:.1%}")
            result.total_warnings.append(msg)
            # Don't mark any section dirty here — drift over 5% is
            # *informational*; the per-row checks already flagged
            # individual sections. If no rows were flagged but total
            # mismatches, the most likely culprit is the section we have
            # the most uncertainty about (folios).
            if not result.dirty_sections:
                result.dirty_sections.append("mutual_fund_folios")

    if result.dirty_sections:
        result.ok = False
        logger.info(
            "reconcile: dirty sections=%s row_warnings=%d total_warnings=%d",
            result.dirty_sections, len(result.row_warnings), len(result.total_warnings),
        )
    return result
