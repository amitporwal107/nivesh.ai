"""Portfolio builder — ParsedData → ordered list of HoldingRow.

Pure function. No I/O. Deterministic. Dedupes per PRD §6:

  • Equity (demat): (pan_hash, isin, quantity)
      — same ISIN + same qty is treated as the same line; keep first, warn.
  • Mutual fund:    (pan_hash, amc, folio, scheme_code)
      — same AMC + folio + scheme is the same holding; keep first, warn.
  • Insurance / NPS / non-ISIN demat: no dedupe key.

Every row carries a ``source_trace`` JSONB describing where it came from,
so an analyst can trace any holding back to the SDK payload, the
ingestion_job, and the raw_parsed_data document.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from ..schemas.parsed_data import ParsedData
from ..schemas.snapshot import HoldingRow

log = logging.getLogger(__name__)


def build_holdings(
    payload: ParsedData,
    *,
    pan_hash: str,
    source_type: str,
    statement_to: str,                    # ISO date
    ingestion_job_id: UUID,
    raw_data_ref: str | None = None,
    sdk_method: str = "upload",
) -> list[HoldingRow]:
    """Flatten + dedupe a ParsedData payload into ``HoldingRow``s."""
    rows: list[HoldingRow] = []
    seen_equity: set[tuple[str, str]] = set()         # (isin, qty)
    seen_mf:     set[tuple[str, str | None, str | None]] = set()  # (amc, folio_number, isin|scheme_code)
    dropped = 0

    base_trace: dict[str, Any] = {
        "source_type": source_type,
        "statement_to": statement_to,
        "parser_ref": {
            "sdk_method": sdk_method,
            "ingestion_job_id": str(ingestion_job_id),
            "raw_data_ref": raw_data_ref,
        },
    }

    # ── Demat side: equities / demat_mutual_funds / corporate_bonds /
    #               aifs / government_securities (per the SDK's bucketed shape),
    #               plus any legacy flat `holdings` list. DematAccount.iter_lines()
    #               normalises both into (asset_class, DematHolding) tuples.
    for account in payload.demat_accounts:
        for asset_class, h in account.iter_lines():
            if h.isin:
                key = (h.isin, str(h.units))
                if key in seen_equity:
                    dropped += 1
                    continue
                seen_equity.add(key)
            trace = {
                **base_trace,
                "folio": None,
                "demat_dp_id": account.dp_id,
                "demat_client_id": account.client_id,
            }
            rows.append(HoldingRow(
                asset_class=asset_class,
                isin=h.isin,
                amfi_code=None,
                folio=None,
                scheme_code=None,
                amc=None,
                name=h.name,
                quantity=h.units,
                value=h.value,
                source_trace=trace,
            ))

    # ── Mutual funds ──────────────────────────────────────────────────────
    # SDK shape: payload.mutual_funds is a flat list of folios; each folio
    # has `amc, folio_number, schemes[]`. (Earlier code expected an extra
    # AMC-wrapper layer that doesn't exist — root cause of the 52 missing
    # MF rows in the 60-vs-112 bug.)
    for fol in payload.mutual_funds:
        for s in fol.schemes:
            # Dedupe by (amc, folio_number, isin) — ISIN is more reliable
            # than the legacy scheme_code which the SDK rarely populates.
            key = (fol.amc, fol.folio_number, s.isin or s.scheme_code)
            if key in seen_mf:
                dropped += 1
                continue
            seen_mf.add(key)
            trace = {
                **base_trace,
                "folio":     fol.folio_number,
                "registrar": fol.registrar,
            }
            rows.append(HoldingRow(
                asset_class="mutual_fund",
                isin=s.isin,
                amfi_code=s.scheme_code,        # legacy field; usually null for SDK output
                folio=fol.folio_number,
                scheme_code=s.scheme_code,
                amc=fol.amc,
                name=s.name,
                quantity=s.units,
                value=s.value,
                source_trace=trace,
            ))

    # ── Insurance ─────────────────────────────────────────────────────────
    for pol in payload.insurance.life_insurance_policies:
        trace = {**base_trace, "folio": pol.policy_number, "insurance_sum_assured": str(pol.sum_assured) if pol.sum_assured else None}
        rows.append(HoldingRow(
            asset_class="insurance",
            isin=None,
            amfi_code=None,
            folio=pol.policy_number,
            scheme_code=None,
            amc=None,
            name=pol.name,
            quantity=Decimal("1"),
            value=pol.value,
            source_trace=trace,
        ))

    # ── NPS ───────────────────────────────────────────────────────────────
    for n in payload.nps:
        trace = {**base_trace, "folio": n.pran}
        rows.append(HoldingRow(
            asset_class="nps",
            isin=None,
            amfi_code=None,
            folio=n.pran,
            scheme_code=None,
            amc=None,
            name=n.scheme,
            quantity=n.units,
            value=n.value,
            source_trace=trace,
        ))

    if dropped:
        log.warning(
            "portfolio_builder dropped %d duplicate rows", dropped,
            extra={
                "eventType": "BUILDER_DUPES_DROPPED",
                "ingestion_job_id": str(ingestion_job_id),
                "pan_hash_prefix": pan_hash[:8],
                "dropped": dropped,
            },
        )

    return rows
