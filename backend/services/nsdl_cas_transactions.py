"""NSDL eCAS mutual-fund transaction extraction, multi-statement merge & XIRR.

An NSDL Consolidated Account Statement carries a *Mutual Funds Transaction
Statement* covering only the statement's own period (one month). To build a
lifetime ledger you feed many monthly CAS PDFs through ``extract_mf_transactions``
and merge them with ``build_ledger``, which de-duplicates overlapping rows and
verifies balance continuity across statement boundaries. ``portfolio_xirr`` then
computes a money-weighted return over the covered window using transaction flows
plus the folio market values from each statement's holdings table.

Honesty notes
-------------
* Demat (equity / SGB) transactions in an NSDL CAS are custody movements
  (pledge / margin / settlement) with NO price — they yield no cost basis and
  are intentionally not parsed here.
* XIRR is only as complete as the statements supplied. Coverage is reported on
  the result; a true since-inception XIRR requires every CAS back to the first
  investment. The engine never silently presents a windowed return as lifetime.
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

_ISIN = r"[A-Z]{2}[A-Z0-9]{9}\d"
# Scheme header: "ISIN: INF179K01WA6 - HDFC Mutual Fund - Scheme Name: GFGT -
#  HDFC Balanced Advantage Folio No - 35007279"
_SCHEME = re.compile(
    rf"ISIN:\s*({_ISIN})\s*-\s*(.*?)\s*-\s*Scheme Name:\s*(.*?)\s*Folio No\s*-\s*(\S+)"
)
_TXN_DATE = re.compile(r"^(\d{1,2})-([A-Z]{3})-(\d{4})\s+(.*)")
_NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_OPEN = re.compile(r"Opening Balance\s+([\d,]+\.\d+)")
_CLOSE = re.compile(r"Closing Balance\s+([\d,]+\.\d+)")
_MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}

# Transaction-type normalisation. Outflows reduce the unit balance.
_OUTFLOW = ("REDEMPTION", "SWITCH_OUT")

# Map this module's transaction types onto the canonical strings used by the
# existing `db.cas_transactions` collection (see services/cas_transactions.py
# and tax_engine_fifo._BUY_TYPES/_SELL_TYPES) so XIRR + behavioural signals +
# SIP detection consume our rows unchanged.
_TYPE_TO_CANONICAL = {
    "PURCHASE": "PURCHASE",
    "SIP": "SIP_PURCHASE",
    "SWITCH_IN": "SWITCH_IN",
    "REDEMPTION": "REDEMPTION",
    "SWITCH_OUT": "SWITCH_OUT",
    "OTHER": "OTHER",
}


def _classify(label: str) -> str:
    low = label.lower()
    if "switch out" in low:
        return "SWITCH_OUT"
    if "switch in" in low:
        return "SWITCH_IN"
    if "redemption" in low:
        return "REDEMPTION"
    if "sip" in low or "systematic" in low or "sys. investment" in low or "sys investment" in low:
        return "SIP"
    if "purchase" in low or "additional" in low:
        return "PURCHASE"
    return "OTHER"


def _to_iso(d: str, mon: str, y: str) -> str:
    return f"{int(y):04d}-{_MONTHS.get(mon.upper(), 0):02d}-{int(d):02d}"


def _f(s) -> float:
    try:
        return float(str(s).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


@dataclass
class MFTxn:
    date: str                 # ISO YYYY-MM-DD
    isin: str
    folio: str
    scheme: str
    amc: str
    txn_type: str             # PURCHASE / SIP / SWITCH_IN / REDEMPTION / SWITCH_OUT / OTHER
    raw_label: str
    amount: float             # gross transaction value in `
    stamp_duty: float
    nav: float
    price: float
    units: float              # SIGNED: + inflow, - outflow
    period: str = ""          # statement 'to' date (ISO) this row was read from

    def key(self) -> tuple:
        # Identity for cross-statement de-duplication.
        return (self.isin, self.folio, self.date, self.raw_label,
                round(self.amount, 2), round(abs(self.units), 3))


@dataclass
class SchemeRecon:
    isin: str
    folio: str
    opening: float
    closing: float
    net_units: float          # Σ signed transaction units
    ok: bool


@dataclass
class TxnExtract:
    period: str = ""
    txns: list[MFTxn] = field(default_factory=list)
    schemes: list[SchemeRecon] = field(default_factory=list)

    @property
    def reconciled(self) -> bool:
        return all(s.ok for s in self.schemes) if self.schemes else False


def extract_mf_transactions(pdf_bytes: bytes, password: str = "") -> TxnExtract:
    """Parse the Mutual Funds Transaction Statement from one NSDL CAS PDF and
    reconcile each scheme's Opening + Σunits == Closing balance."""
    import pdfplumber

    res = TxnExtract()
    cur = None                 # (isin, amc, scheme, folio)
    opening = None
    running = 0.0
    in_mf = False

    def flush(closing: Optional[float]):
        nonlocal cur, opening, running
        if cur and opening is not None and closing is not None:
            ok = abs((opening + running) - closing) <= 0.01
            res.schemes.append(SchemeRecon(cur[0], cur[3], opening, closing, round(running, 3), ok))
            if not ok:
                logger.warning("nsdl-txn: %s/%s opening %.3f + net %.3f != closing %.3f",
                               cur[0], cur[3], opening, running, closing)
        cur, opening, running = cur, None, 0.0

    with pdfplumber.open(io.BytesIO(pdf_bytes), password=password) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if "Mutual Funds Transaction Statement" in text:
                in_mf = True
                mperiod = re.search(r"Period from .*? to (\d{1,2}-[A-Za-z]{3}-\d{4})", text)
                if mperiod and not res.period:
                    dd, mm, yy = mperiod.group(1).split("-")
                    res.period = _to_iso(dd, mm, yy)
            if not in_mf:
                continue
            stop = False
            for raw in text.split("\n"):
                line = raw.strip()
                if not line:
                    continue
                # End marker shares the page with the final scheme's last
                # transactions and Closing Balance, so it must be detected
                # AFTER those lines have been processed below — set a flag and
                # finish the page, then stop.
                if "End of Statement" in line:
                    stop = True
                    continue

                sm = _SCHEME.search(line)
                if sm:
                    cur = (sm.group(1), sm.group(2).strip(), sm.group(3).strip(), sm.group(4).strip())
                    opening = None
                    running = 0.0
                    continue

                mo = _OPEN.search(line)
                if mo and cur:
                    opening = _f(mo.group(1))
                    continue

                mc = _CLOSE.search(line)
                if mc and cur:
                    flush(_f(mc.group(1)))
                    cur = None
                    continue

                dm = _TXN_DATE.match(line)
                if dm and cur:
                    nums = [_f(m.group()) for m in _NUM.finditer(dm.group(4))]
                    if len(nums) < 5:
                        continue
                    amount, stamp, nav, price, units = nums[-5], nums[-4], nums[-3], nums[-2], nums[-1]
                    label = _NUM.sub("", dm.group(4)).strip(" -")
                    label = re.sub(r"\s{2,}", " ", label)
                    ttype = _classify(label)
                    signed = -units if ttype in _OUTFLOW else units
                    res.txns.append(MFTxn(
                        date=_to_iso(*dm.group(1, 2, 3)),
                        isin=cur[0], folio=cur[3], scheme=cur[2], amc=cur[1],
                        txn_type=ttype, raw_label=label, amount=amount, stamp_duty=stamp,
                        nav=nav, price=price, units=signed, period=res.period,
                    ))
                    running += signed

            if stop:
                flush(None)   # close any scheme left open at end of statement
                cur = None
                break

    return res


def to_cas_transaction_docs(txns: list[MFTxn]) -> list[dict]:
    """Convert parsed MFTxn rows into the flat dict shape persisted in
    ``db.cas_transactions`` (see services.cas_transactions). ``amount`` is the
    positive magnitude — direction is carried by ``type`` (the XIRR engine signs
    by type); ``units`` keeps our signed convention (+ inflow, − outflow)."""
    docs = []
    for t in txns:
        amount = t.amount + t.stamp_duty
        docs.append({
            "date": t.date,
            "scheme_name": t.scheme,
            "isin": t.isin,
            "folio": t.folio,
            "amc": t.amc,
            "type": _TYPE_TO_CANONICAL.get(t.txn_type, "OTHER"),
            "amount": round(abs(amount), 2),
            "units": round(t.units, 4),
            "nav": round(t.nav, 4),
            "balance": 0.0,
            "raw_description": t.raw_label,
        })
    return docs


# ── Multi-statement merge ─────────────────────────────────────────────
@dataclass
class Ledger:
    txns: list[MFTxn] = field(default_factory=list)
    periods: list[str] = field(default_factory=list)
    continuity: list[dict] = field(default_factory=list)  # cross-statement balance checks
    duplicates_dropped: int = 0

    @property
    def coverage(self) -> str:
        if not self.txns:
            return "no transactions"
        ds = sorted(t.date for t in self.txns)
        return f"{ds[0]} → {ds[-1]} ({len(self.txns)} txns, {len(self.periods)} statements)"


def build_ledger(extracts: list[TxnExtract]) -> Ledger:
    """Merge per-statement extracts into a deduplicated lifetime ledger and
    verify that each folio's closing balance in statement N equals its opening
    balance in statement N+1 (continuity across the seam)."""
    led = Ledger()
    seen: set = set()
    for ex in sorted(extracts, key=lambda e: e.period):
        if ex.period:
            led.periods.append(ex.period)
        for t in ex.txns:
            k = t.key()
            if k in seen:
                led.duplicates_dropped += 1
                continue
            seen.add(k)
            led.txns.append(t)

    # Continuity: closing(period_i) should equal opening(period_{i+1}) per folio.
    by_period: dict[str, dict[tuple, SchemeRecon]] = {}
    for ex in extracts:
        by_period[ex.period] = {(s.isin, s.folio): s for s in ex.schemes}
    ordered = sorted(p for p in by_period if p)
    for a, b in zip(ordered, ordered[1:]):
        for key, sa in by_period[a].items():
            sb = by_period[b].get(key)
            if sb is None:
                continue
            ok = abs(sa.closing - sb.opening) <= 0.01
            if not ok:
                led.continuity.append({
                    "isin": key[0], "folio": key[1], "from": a, "to": b,
                    "closing": sa.closing, "next_opening": sb.opening, "ok": ok,
                })
    led.txns.sort(key=lambda t: (t.date, t.isin, t.folio))
    return led


# ── XIRR ──────────────────────────────────────────────────────────────
def _xirr(flows: list[tuple[str, float]]) -> Optional[float]:
    """Money-weighted annualised return for (ISO-date, amount) cashflows.
    Sign convention: money leaving the investor is negative, money/value
    returning is positive. Newton-Raphson with a bisection fallback."""
    from datetime import date as _date

    if len(flows) < 2:
        return None
    days = []
    for d, amt in flows:
        y, m, dd = (int(x) for x in d.split("-"))
        days.append((( _date(y, m, dd) - _date(*[int(x) for x in flows[0][0].split("-")])).days, amt))
    if not any(a < 0 for _, a in days) or not any(a > 0 for _, a in days):
        return None

    def npv(rate: float) -> float:
        return sum(a / (1.0 + rate) ** (t / 365.0) for t, a in days)

    lo, hi = -0.9999, 10.0
    flo, fhi = npv(lo), npv(hi)
    if flo * fhi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        fm = npv(mid)
        if abs(fm) < 1e-6:
            return mid
        if flo * fm < 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2


@dataclass
class XirrResult:
    xirr: Optional[float]
    invested: float           # net external cash in (purchases − redemptions, incl. stamp)
    start_value: float        # portfolio value at window start (from holdings)
    end_value: float          # portfolio value at window end (from holdings)
    start_date: str
    end_date: str
    flows: int
    note: str = ""


def portfolio_xirr(ledger: Ledger,
                   start_value: float, start_date: str,
                   end_value: float, end_date: str) -> XirrResult:
    """Windowed money-weighted return: open with the portfolio value at the
    first statement (cash out), apply every merged transaction flow, then close
    with the current portfolio value (cash in). ``start_value`` / ``end_value``
    come from the holdings tables of the first / last statements supplied."""
    flows: list[tuple[str, float]] = [(start_date, -abs(start_value))]
    invested = 0.0
    for t in ledger.txns:
        if not (start_date < t.date <= end_date):
            continue
        if t.units > 0:                       # inflow: investor pays amount + stamp
            cash = -(t.amount + t.stamp_duty)
            invested += t.amount + t.stamp_duty
        else:                                 # outflow: investor receives amount
            cash = t.amount
            invested -= t.amount
        flows.append((t.date, cash))
    flows.append((end_date, abs(end_value)))
    rate = _xirr(flows)
    return XirrResult(
        xirr=rate, invested=round(invested, 2),
        start_value=round(start_value, 2), end_value=round(end_value, 2),
        start_date=start_date, end_date=end_date, flows=len(flows),
        note=("windowed XIRR over supplied statements — feed earlier CAS to "
              "extend toward inception"),
    )
