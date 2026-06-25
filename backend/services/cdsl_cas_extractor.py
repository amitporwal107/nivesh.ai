"""Custom CDSL Consolidated Account Statement (eCAS) extractor.

Reads a CDSL eCAS PDF directly (digital text via pdfplumber) and extracts demat
holdings (equities + demat ETFs/silver) and mutual-fund folios using the
statement's own authoritative ``Value in `` column, then reconciles against the
printed per-account summary (CDSL Demat total + MF Folios total + Grand Total).

Why this exists
---------------
The offline ``casparser`` library parses a CDSL eCAS but silently drops the
ENTIRE CDSL demat equity section — on a real statement it returned only the MF
folios (₹13.85L) of a ₹28.45L portfolio, a 51% loss, even though the demat
equities are present in the text. This mirrors casparser's NSDL column-shift
bug. CDSL CAS is digital text, so a direct reconciling extractor (sibling of
``nsdl_cas_extractor``) recovers the full portfolio.

Layout notes (CDSL eCAS):
* Summary page: ``CDSL Demat Account <name> <N> <value>`` / ``Mutual Fund Folios
  <N> Folios <N> <value>`` / ``Grand Total <value>``.
* Demat holdings rows: ``ISIN <name> <balances…> <price> <value>`` — value is the
  last number, price the second-last; quantity is derived as value/price (the
  several balance columns — opening/credit/debit/closing/frozen/pledge — are
  ambiguous, so we trust the authoritative value, not a balance column).
* Folio valuation rows: ``<scheme name> ISIN <folio> <units> <nav> <cost>
  <value> <pnl> <return>`` — value ≈ units × nav, pnl ≈ value − cost.
* Header/footer lines are bilingual (Devanagari-interleaved) garble and are
  skipped.

Public entry point: ``extract_cdsl_cas(pdf_bytes, password) -> CdslResult``.
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from services.nsdl_cas_extractor import Holding, _refine_type

logger = logging.getLogger(__name__)

# No trailing \b: CDSL folio rows glue the ISIN to the folio number with no
# space (e.g. "INF204K01HY3499296439646/0"); a trailing boundary would skip them.
# ISINs are exactly 12 chars (IN + 10), so the fixed length bounds the match.
_ISIN = re.compile(r"\b(IN[A-Z0-9]{10})")
_NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_DATE = re.compile(r"\d{1,2}-\d{2}-\d{4}|\d{1,2}-[A-Za-z]{3}-\d{4}")


def _is_garble(line: str) -> bool:
    return any("ऀ" <= c <= "ॿ" for c in line)  # Devanagari block


def _f(s) -> float:
    try:
        return float(str(s).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _nums_after(text: str) -> list[float]:
    cleaned = _DATE.sub(" ", text)
    return [_f(m.group()) for m in _NUM.finditer(cleaned)]


@dataclass
class CdslResult:
    holdings: list[Holding] = field(default_factory=list)
    grand_total: Optional[float] = None
    demat_total: Optional[float] = None     # printed CDSL demat account value
    folio_total: Optional[float] = None     # printed MF folios value
    investor_name: str = ""
    reconciliation: dict = field(default_factory=dict)

    @property
    def reconciled(self) -> bool:
        return bool(self.reconciliation.get("ok"))


def _approx(a: float, b: float, scale: float) -> bool:
    return abs(a - b) <= max(1.0, 0.01 * abs(scale))


def _try_folio(after_isin: str) -> Optional[tuple]:
    """If the numbers after the ISIN match the folio valuation shape, return
    (units, nav, cost, value); else None. Anchored from the right so the leading
    folio number/UCC don't matter; handles the optional trailing return% column.
    """
    n = _nums_after(after_isin)
    if len(n) < 5:
        return None
    # Hypothesis A: [.. units nav cost value pnl return]  → value=n[-3]
    # Hypothesis B: [.. units nav cost value pnl]          → value=n[-2]
    for units, nav, cost, value, pnl in (
        (n[-6], n[-5], n[-4], n[-3], n[-2]) if len(n) >= 6 else (0, 0, 0, 0, 0),
        (n[-5], n[-4], n[-3], n[-2], n[-1]),
    ):
        if units <= 0 or nav <= 0:
            continue
        if _approx(value, units * nav, value) and _approx(pnl, value - cost, max(abs(value), 1.0)):
            return units, nav, cost, value
    return None


def extract_cdsl_cas(pdf_bytes: bytes, password: str = "") -> CdslResult:
    """Extract + reconcile a CDSL eCAS PDF. Never raises on a bad row; callers
    check ``result.reconciled`` before persisting."""
    import pdfplumber

    res = CdslResult()
    with pdfplumber.open(io.BytesIO(pdf_bytes), password=password) as pdf:
        for page in pdf.pages:
            for raw in (page.extract_text() or "").split("\n"):
                line = raw.strip()
                if not line or _is_garble(line):
                    continue

                # ── Summary figures ──────────────────────────────────
                if res.demat_total is None and "CDSL Demat Account" in line and "Folios" not in line:
                    nums = _nums_after(line)
                    if nums:
                        res.demat_total = nums[-1]
                if res.folio_total is None and re.search(r"Mutual Fund Folios\b.*\bFolios\b", line):
                    nums = _nums_after(line)
                    if nums:
                        res.folio_total = nums[-1]
                if line.startswith("Grand Total") and res.grand_total is None:
                    nums = _nums_after(line)
                    if nums:
                        res.grand_total = nums[-1]
                if not res.investor_name and "PAN :" in line:
                    res.investor_name = line.split("(")[0].strip()

                # ── Holding rows (must carry a trailing rupee value) ──
                m = _ISIN.search(line)
                if not m:
                    continue
                after = line[m.end():]
                if not re.search(r"[\d,]+\.\d{2}\s*$", after):
                    continue  # no trailing value → transaction row / metadata, skip
                isin = m.group(1)
                name = re.sub(r"\s{2,}", " ", _NUM.sub("", _DATE.sub("", after))).strip(" .-#") or isin

                folio = _try_folio(after)
                if folio:
                    units, nav, cost, value = folio
                    res.holdings.append(Holding(
                        name=name, isin=isin, nsdl_class="F",
                        asset_type=_refine_type("F", name),
                        quantity=round(units, 4), current_price=round(nav, 4),
                        buy_price=round(cost / units, 4) if units else round(nav, 4),
                        value=round(value, 2), cost_basis=round(cost, 2),
                        account="Mutual Fund Folios",
                    ))
                else:
                    nums = _nums_after(after)
                    if len(nums) < 2:
                        continue
                    value, price = nums[-1], nums[-2]
                    qty = value / price if price else 0.0
                    low = name.lower()
                    at = ("gold" if ("gold" in low or "sgb" in low)
                          else "etf" if ("etf" in low or "bees" in low or "silver" in low)
                          else "equity")
                    res.holdings.append(Holding(
                        name=name, isin=isin, nsdl_class="E",
                        asset_type=at,
                        quantity=round(qty, 4), current_price=round(price, 4),
                        buy_price=round(price, 4), value=round(value, 2),
                        account="CDSL Demat Account",
                    ))

    res.reconciliation = _reconcile(res)
    return res


def _reconcile(res: CdslResult, tol_abs: float = 2.0, tol_pct: float = 0.005) -> dict:
    demat = round(sum(h.value for h in res.holdings if h.nsdl_class != "F"), 2)
    folio = round(sum(h.value for h in res.holdings if h.nsdl_class == "F"), 2)
    total = round(demat + folio, 2)

    def chk(got, printed):
        if printed is None:
            return None
        diff = round(got - printed, 2)
        return {"printed": printed, "extracted": got, "diff": diff,
                "ok": abs(diff) <= tol_abs or abs(diff) <= abs(printed) * tol_pct}

    per = {"demat": chk(demat, res.demat_total),
           "folio": chk(folio, res.folio_total),
           "total": chk(total, res.grand_total)}
    ok = all(v["ok"] for v in per.values() if v is not None) and res.grand_total is not None
    return {"ok": ok, "per": per, "holdings_count": len(res.holdings)}
