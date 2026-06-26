"""Custom CAMS + KFintech Consolidated Account Statement (CAS) extractor.

Reads a CAMS/KFintech consolidated mutual-fund CAS PDF directly (digital text via
pdfplumber) and extracts every folio holding using the statement's own
authoritative ``Market Value`` column, then reconciles the extracted sum against
the statement's printed ``Total`` row and a per-holding ``units × NAV ≈ market``
check.

Why this exists
---------------
CAMS and KFintech jointly issue one consolidated statement that covers BOTH
registrars (each scheme row carries a ``Registrar : CAMS|KFINTECH`` tag). The
onboarding waterfall currently routes these to the offline ``casparser`` library
with **no reconciliation gate** — a silent-data-loss risk identical to the one
that motivated the custom NSDL/CDSL extractors. This extractor parses the two
real layouts directly and refuses (``reconciled = False``) any parse that does
not tie out to the printed total, so the caller can fall back to casparser rather
than persist a wrong portfolio.

Two layouts are handled (auto-detected):

* **Summary CAS** ("Consolidated Account Summary") — a holdings snapshot, one row
  per folio/scheme::

      <folio><ISIN> <code> - <name> <cost> <units> <navdate> <nav> <market> <Registrar>

  ending in ``Total <cost-total> <market-total>`` (both clean). The folio and
  ISIN are sometimes glued together (``910124242826/0INF846K01859``); the ISIN is
  a fixed 12-char ``IN`` code, so it anchors the split. Numeric columns are read
  from the RIGHT because the leading scheme code/name may contain digits.

* **Detailed CAS** ("Consolidated Account Statement") — per-folio blocks with
  transactions; each holding's snapshot is on its ``Closing Unit Balance:`` line::

      Closing Unit Balance: <units> NAV on <date> : INR <nav> \
        Total Cost Value : INR <cost> Market Value on <date> : INR <market>

  On folios that carry transactions the NAV date interleaves character-by-character
  into the "Closing Unit Balance" label (``Clo2s5in-Jgu Unn-i2t0 B2a6lance:``), so
  the closing line is anchored on the surviving ``lance: <units> NAV on …`` tail.
  The per-AMC ``PORTFOLIO SUMMARY`` market values are corrupted (trailing unit
  digits fused on, e.g. ``3816408.73931920``) and are NOT trusted; only the clean
  ``Total`` *cost* figure and the per-holding ``units × NAV`` check gate the parse.

Public entry point: ``extract_cams_kfin_cas(pdf_bytes, password) -> ExtractResult``.
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from services.nsdl_cas_extractor import Holding

logger = logging.getLogger(__name__)


class _CKHolding(Holding):
    """NSDL ``Holding`` with a CAMS/KFin source tag (aids fallback diagnostics;
    the persist layer rewrites ``source`` to ``"cas"`` for CAS imports anyway)."""

    def as_holding_dict(self) -> dict:
        d = super().as_holding_dict()
        d["source"] = "cams_kfin_cas"
        return d

# ── Lexical patterns ──────────────────────────────────────────────────
# ISIN: "IN" + 10 alphanumerics. No leading \b — summary rows glue the folio to
# the ISIN with no space ("910124242826/0INF846K01859"); the fixed 12-char length
# bounds the match. Used with .search() to find the ISIN anywhere on a row.
_ISIN = re.compile(r"(IN[A-Z0-9]{10})")
_NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_DATE = re.compile(r"\d{1,2}-[A-Za-z]{3}-\d{4}")

# Summary holdings table header — skip it (it contains the word "ISIN").
_SUMMARY_HEADER = "Folio No."
# The "Total <cost> <market>" reconciliation row (both layouts print it; the
# market figure is clean in the Summary layout, corrupted in the Detailed one).
_TOTAL = re.compile(r"^Total\s+([\d,]+\.?\d*)\s+([\d,]+\.?\d*)")
# End-of-holdings markers.
_SUMMARY_STOP = "Loads and Fees"

# Detailed-layout anchors.
_DET_FOLIO = re.compile(r"Folio No\s*:\s*([\d/ ]+?)\s+PAN")
_DET_ISIN = re.compile(r"ISIN\s*:\s*(IN[A-Z0-9]{10})")
_DET_REG = re.compile(r"Registrar\s*:\s*(CAMS|KFINTECH)")
# Closing snapshot — anchored on the surviving "lance:" + intact NAV/cost/market
# tail so it matches both the clean and the date-corrupted label.
_DET_CLOSE = re.compile(
    r"lance:\s*([\d,]+\.?\d*)\s+NAV on\s+\S+\s*:\s*INR\s*([\d,]+\.?\d*)\s+"
    r"Total Cost Value\s*:\s*INR\s*([\d,]+\.?\d*)\s+"
    r"Market Value on\s+\S+\s*:\s*INR\s*([\d,]+\.?\d*)"
)
# Detailed scheme line: "<code>-<name> … (Demat|Non-Demat) … ISIN:<isin> Registrar : <reg>"
_DET_SCHEME = re.compile(r"^([A-Z0-9]{2,12})-(.+?)\s*\((?:Non-)?Demat\)")


@dataclass
class ExtractResult:
    holdings: list[Holding] = field(default_factory=list)
    grand_total: Optional[float] = None        # portfolio market value (sum / printed)
    investor_name: str = ""
    statement_date: str = ""                    # ISO-ish "DD-MMM-YYYY" period end
    layout: str = ""                            # "summary" | "detailed"
    reconciliation: dict = field(default_factory=dict)

    @property
    def reconciled(self) -> bool:
        return bool(self.reconciliation.get("ok"))


def _f(s) -> float:
    try:
        return float(str(s).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _refine_mf_type(name: str) -> str:
    """CAMS/KFin statements are mutual-fund folios only; refine the obvious
    ETF / gold sub-types by name, else plain mutual_fund (matches how the NSDL
    extractor refines its M/F classes)."""
    low = name.lower()
    if "gold" in low:
        return "gold"
    if "etf" in low or "bees" in low or "exchange traded" in low:
        return "etf"
    return "mutual_fund"


def _make_holding(name: str, isin: str, folio: str, units: float, nav: float,
                  cost: float, market: float) -> Holding:
    buy_price = (cost / units) if units else nav
    return _CKHolding(
        name=name or isin,
        isin=isin,
        nsdl_class="F",                       # folio (mutual fund) — shared taxonomy
        asset_type=_refine_mf_type(name),
        quantity=units,
        current_price=nav,
        buy_price=buy_price,
        value=market,
        cost_basis=cost or None,
        account="Mutual Fund Folios",
        folio=folio,
    )


def _clean_name(raw: str) -> str:
    """Strip the leading scheme code ("128MCGPG - " / "G299-") and collapse runs.
    Whitespace is normalised *first* so the anchored code-strip fires even when the
    text arrives with a leading space (summary rows carry one after the ISIN)."""
    name = re.sub(r"\s{2,}", " ", raw).strip()
    name = re.sub(r"^[A-Z0-9]{2,12}\s*-\s*", "", name).strip(" .-")
    return name or raw.strip()


# ── Summary layout ────────────────────────────────────────────────────
def _parse_summary(pages: list[str], res: ExtractResult) -> None:
    res.layout = "summary"
    stop = False
    for text in pages:
        if stop:
            break
        for raw in text.split("\n"):
            line = raw.strip()
            if not line:
                continue
            if line.startswith(_SUMMARY_STOP):
                stop = True
                break
            if res.statement_date == "":
                md = re.search(r"As on\s+(\d{1,2}-[A-Za-z]{3}-\d{4})", line)
                if md:
                    res.statement_date = md.group(1)
            mt = _TOTAL.match(line)
            if mt:
                res.reconciliation["printed_cost_total"] = _f(mt.group(1))
                res.reconciliation["printed_market_total"] = _f(mt.group(2))
                continue
            if line.startswith(_SUMMARY_HEADER) or "Scheme Name" in line:
                continue
            m = _ISIN.search(line)
            if not m:
                continue
            isin = m.group(1)
            folio = line[:m.start()].strip()
            after = line[m.end():]
            reg = "KFINTECH" if "KFINTECH" in after else ("CAMS" if "CAMS" in after else "")
            body = after.replace("KFINTECH", "").replace("CAMS", "")
            name = _clean_name(_NUM.sub("", _DATE.sub("", body)))
            nums = [_f(x.group()) for x in _NUM.finditer(_DATE.sub(" ", body))]
            if len(nums) < 4:
                continue
            # Columns (right-anchored): … Cost Units [NAVdate] NAV Market
            cost, units, nav, market = nums[-4], nums[-3], nums[-2], nums[-1]
            h = _make_holding(name, isin, folio, units, nav, cost, market)
            h.account = reg or h.account
            res.holdings.append(h)


# ── Detailed layout ───────────────────────────────────────────────────
def _parse_detailed(pages: list[str], res: ExtractResult) -> None:
    res.layout = "detailed"
    cur_isin: Optional[str] = None
    cur_folio = ""
    cur_name = ""
    for text in pages:
        for raw in text.split("\n"):
            line = raw.strip()
            if not line:
                continue
            if res.statement_date == "":
                md = re.search(r"\bTo\s+(\d{1,2}-[A-Za-z]{3}-\d{4})", line)
                if md:
                    res.statement_date = md.group(1)
            mt = _TOTAL.match(line)
            if mt and "printed_cost_total" not in res.reconciliation:
                # Only the cost figure is clean here; the market figure is corrupted.
                res.reconciliation["printed_cost_total"] = _f(mt.group(1))
            mf = _DET_FOLIO.search(line)
            if mf:
                cur_folio = mf.group(1).replace(" ", "")
            ms = _DET_SCHEME.match(line)
            if ms:
                cur_name = _clean_name(ms.group(1) + "-" + ms.group(2))
            mi = _DET_ISIN.search(line)
            if mi:
                cur_isin = mi.group(1)
            mc = _DET_CLOSE.search(line)
            if mc:
                units, nav, cost, market = (_f(g) for g in mc.groups())
                if (units > 0 or market > 0) and cur_isin:
                    res.holdings.append(
                        _make_holding(cur_name, cur_isin, cur_folio, units, nav, cost, market)
                    )
                # Reset per-holding scheme context; folio persists until next "Folio No".
                cur_isin = None
                cur_name = ""


def _reconcile(res: ExtractResult, tol_abs: float = 1.0, tol_pct: float = 0.005) -> None:
    """Gate the parse. ``ok`` requires (1) every holding's ``units × NAV`` ties to
    its market value, (2) the extracted cost sum matches the printed Total cost,
    and (3) — summary layout only, where it is clean — the market sum matches the
    printed Total market."""
    if not res.holdings:
        res.reconciliation["ok"] = False
        res.reconciliation["reason"] = "no holdings"
        return

    bad = [
        h for h in res.holdings
        if abs(h.quantity * h.current_price - h.value) > max(tol_abs, tol_pct * abs(h.value))
    ]
    extracted_cost = round(sum((h.cost_basis or 0.0) for h in res.holdings), 2)
    extracted_market = round(sum(h.value for h in res.holdings), 2)
    res.grand_total = extracted_market

    printed_cost = res.reconciliation.get("printed_cost_total")
    printed_market = res.reconciliation.get("printed_market_total")

    cost_ok = (
        printed_cost is not None
        and abs(extracted_cost - printed_cost) <= max(tol_abs, tol_pct * printed_cost)
    )
    market_ok = True
    if printed_market is not None:  # only the summary layout prints a clean market total
        market_ok = abs(extracted_market - printed_market) <= max(tol_abs, tol_pct * printed_market)

    res.reconciliation.update({
        "ok": (not bad) and cost_ok and market_ok,
        "holdings_count": len(res.holdings),
        "per_holding_value_mismatches": len(bad),
        "extracted_cost": extracted_cost,
        "extracted_market": extracted_market,
        "cost_diff": round(extracted_cost - printed_cost, 2) if printed_cost is not None else None,
        "market_diff": round(extracted_market - printed_market, 2) if printed_market is not None else None,
    })


def extract_cams_kfin_cas(pdf_bytes: bytes, password: str = "") -> ExtractResult:
    """Extract + reconcile a CAMS/KFintech consolidated CAS PDF. Never raises on a
    bad row; the caller checks ``result.reconciled`` and refuses to persist a
    statement that does not reconcile to its printed total."""
    import pdfplumber

    res = ExtractResult()
    with pdfplumber.open(io.BytesIO(pdf_bytes), password=password) as pdf:
        pages = [(page.extract_text() or "") for page in pdf.pages]

    full = "\n".join(pages)
    # Guard: only attempt this on a CAMS/KFintech consolidated statement.
    low = full.lower()
    if not (("cams" in low or "kfin" in low or "kfintech" in low)
            and "consolidated account" in low):
        res.reconciliation = {"ok": False, "reason": "not a CAMS/KFintech CAS"}
        return res

    # The Detailed layout has per-folio "Closing Unit Balance:" lines; the Summary
    # layout does not (its "Unit Balance" appears only as a column header).
    if "Closing Unit Balance" in full:
        _parse_detailed(pages, res)
    else:
        _parse_summary(pages, res)

    _reconcile(res)
    return res
