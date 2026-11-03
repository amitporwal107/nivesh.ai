"""TrueData corporate JSON → checked rows in crore. Pure: no I/O, no database, no network.

Every rule here comes from the supervised load of 2 Nov 2026 (test_reports/truedata_research_data_20261102.md), where
each one caused a real defect or a near miss:

  * One filing is listed under 2-4 ids (two id ranges, same file time) → `dedupe`.
  * The by-day list has no period end → `period_end_of` reads the statement header.
  * LevelOfRoundingUsedInFinancialStatements is usually blank → `infer_units`: TrueData FY revenue / our FY revenue,
    accepted only within 1.5x of a unit factor (units are >= 10x apart, so a ratio between 1.5x and 6.7x decides
    nothing: RADICO's revenue is gross of excise, ratio 3.475, and a 3x tolerance loaded it 10x too small); else the
    share-capital anchor; else the filing's own rounding text; else the row is REFUSED. Never guessed.
  * CurrentLiabilities is often 0 while Liabilities and NoncurrentLiabilities are filled → CL = L − NCL.
  * Bank-format statements (OtherAssetsGroup.Advances > 0) are not mapped: current ratio means nothing for a bank.
  * Cash flow: fiscal-year filings only. nidp.nse_financials_cashflow is annual and v_stock_fundamentals_latest divides
    the latest CFO by TTM PAT, so a half-year CFO would halve cfo_pat_ratio.
  * Identity checks before anything is offered: assets = equity + liabilities (1 %), CA <= TA, receivables <= CA,
    CFO + CFI + CFF = net change in cash before FX (1 % of the largest leg, min 2 units).

Added in the job (not in the supervised scripts):
  * Finance costs per quarter from the quarter-only P&L (cumulative=false): Expenses.NonOperating.InterestExpense, only
    for a ~3-month period, never for a bank-format P&L, and only when TrueData's quarter revenue agrees with ours for the
    same quarter (confirms period, nature and unit together).
  * A per-filing unit guard: the unit is inferred once per company and nature from a fiscal-year P&L, so a filing whose
    share capital is >= 6.67x (10 / 1.5) away from that P&L's paid-up capital, in reporting units, is refused: the
    company may have changed its rounding between filings. Bonus issues and splits (2-6x) pass. On the 2 Nov raw files
    it refuses one row the supervised load took: SWIGGY's pre-IPO Sep-2024 filing (capital 13,440 incl. preference
    capital vs 261 later; its own rounding text says "Millions" although its values are crore-consistent).
"""
from __future__ import annotations

import html
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

FACTORS: Dict[str, float] = {"crore": 1.0, "million": 10.0, "lakh": 100.0, "thousand": 1e4, "rupee": 1e7}
UNIT_TOLERANCE = 1.5
ROUNDING_WORDS = {"crore": "crore", "crores": "crore", "lakh": "lakh", "lakhs": "lakh", "lacs": "lakh",
                  "millions": "million", "million": "million", "thousands": "thousand", "thousand": "thousand",
                  "rupees": "rupee", "actual": "rupee"}

H1_FY = frozenset({"Second quarter", "Half yearly", "Yearly"})            # filings that carry a balance sheet
QUARTER_LABELS = frozenset({"First quarter", "Second quarter", "Third quarter", "Yearly"})   # quarter-only P&L exists
NATURES = frozenset({"Consolidated", "Standalone"})
DUPLICATE_WINDOW_DAYS = 45
SME_H1_FILING_DAYS = 120
IDENTITY_TOLERANCE = 0.01
QUARTER_DAYS = (80, 100)
QUARTER_REVENUE_TOLERANCE = 0.05
# A unit change moves the share capital by >= 10x; bonus issues and splits move it 2-6x (BAJFINANCE 2025: 5.0x,
# PATANJALI: 3.0x, both real). Refuse only what could be a unit change: >= 10 / 1.5.
CAPITAL_RATIO_MAX = 10 / UNIT_TOLERANCE

# Balance-sheet columns of nidp.nse_financials_quarterly this job may fill. equity_share_capital_cr is deliberately NOT
# here: filling it would switch on the market-cap / P-B formulas of populate_stock_features_extended.
BS_COLUMNS = ("current_assets_cr", "current_liabilities_cr", "inventory_cr", "trade_receivables_cr",
              "trade_payables_cr", "cash_and_equiv_cr", "long_term_debt_cr", "short_term_debt_cr", "total_equity_cr")
CF_COLUMNS = ("cfo_cr", "cfi_cr", "cff_cr", "capex_cr", "net_change_cash_cr")
FC_COLUMNS = ("finance_costs_cr",)

EMPTY_KEY = "_truedata_empty"          # cache marker: TrueData answered "no such statement"


# ── small helpers ────────────────────────────────────────────────────────────────────────────────────────────────

def num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def to_date(v: Any) -> Optional[date]:
    s = str(v or "").strip()[:10]
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _file_dt(file_time: str) -> datetime:
    try:
        return datetime.fromisoformat((file_time or "1970-01-01T00:00:00")[:19])
    except ValueError:
        return datetime(1970, 1, 1)


def to_crore(value: Optional[float], unit: str) -> Optional[Decimal]:
    """Reporting units → crore, rounded to the warehouse's 4 decimals (the supervised load's arithmetic)."""
    if value is None:
        return None
    return Decimal(repr(round(value / FACTORS[unit], 4)))


def is_empty_answer(payload: Any) -> bool:
    return isinstance(payload, dict) and EMPTY_KEY in payload


def usable(payload: Any) -> bool:
    return isinstance(payload, dict) and EMPTY_KEY not in payload and isinstance(payload.get("GeneralInfo"), dict)


# ── filings ──────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Filing:
    id: int
    file_time: str
    symbol: str          # our NSE symbol
    quarter: str         # TrueData's ReportingQuarter label
    nature: str          # 'Consolidated' | 'Standalone'

    @property
    def consolidated(self) -> bool:
        return self.nature == "Consolidated"

    @property
    def key(self) -> Tuple[str, str]:
        return self.symbol, self.nature


def resolve_symbol(rec: Mapping[str, Any], known: Iterable[str], bse_map: Mapping[str, str]) -> Optional[str]:
    """TrueData's NSE symbol (HTML entities decoded: "M&amp;M" → "M&M"); when that is not one of ours (None,
    "NOTLISTED", a BSE-only name), the NSE symbol mapped from the BSE scrip code. None when neither is ours."""
    known = known if isinstance(known, (set, frozenset, dict)) else set(known)
    s = html.unescape(str(rec.get("Symbol") or "").strip().strip('"'))
    if s and s in known:
        return s
    mapped = bse_map.get(str(rec.get("scripcode") or "").strip())
    return mapped if mapped and mapped in known else None


def filings_from_records(records: Iterable[Mapping[str, Any]], known: Iterable[str],
                         bse_map: Mapping[str, str]) -> Tuple[List[Filing], Counter]:
    """List records (any number of days) → our filings, one per id. Records not resolvable to our symbols, or with an
    unknown nature or id, are counted and dropped."""
    known = set(known)
    counts: Counter = Counter()
    by_id: Dict[int, Filing] = {}
    for r in records:
        try:
            fid = int(r.get("id"))
        except (TypeError, ValueError):
            counts["list_bad_id"] += 1
            continue
        nature = str(r.get("Nature") or "").strip()
        if nature not in NATURES:
            counts["list_unknown_nature"] += 1
            continue
        sym = resolve_symbol(r, known, bse_map)
        if sym is None:
            counts["list_not_our_symbol"] += 1
            continue
        by_id[fid] = Filing(fid, str(r.get("file_time") or ""), sym, str(r.get("ReportingQuarter") or "").strip(),
                            nature)
    return sorted(by_id.values(), key=lambda f: (f.file_time, f.id)), counts


def prefer_consolidated(filings: Sequence[Filing]) -> List[Filing]:
    """Consolidated filings; standalone ones only for a company that files no consolidated statement at all."""
    has_cons = {f.symbol for f in filings if f.consolidated}
    return [f for f in filings if f.consolidated or f.symbol not in has_cons]


def dedupe(filings: Sequence[Filing]) -> List[Filing]:
    """TrueData lists one filing under 2-4 ids (two id ranges, same file time; sometimes a re-file a minute later).
    Per (symbol, nature, quarter label), filings less than 45 days apart are one period: keep the latest file time,
    then the highest id."""
    groups: Dict[Tuple[str, str, str], List[Filing]] = defaultdict(list)
    for f in filings:
        groups[(f.symbol, f.nature, f.quarter)].append(f)
    keep: List[Filing] = []
    for rows in groups.values():
        rows.sort(key=lambda f: (f.file_time, f.id))
        cluster: List[Filing] = []
        for f in rows:
            if cluster and (_file_dt(f.file_time) - _file_dt(cluster[0].file_time)).days >= DUPLICATE_WINDOW_DAYS:
                keep.append(cluster[-1])
                cluster = []
            cluster.append(f)
        if cluster:
            keep.append(cluster[-1])
    return sorted(keep, key=lambda f: (f.file_time, f.id))


def period_end_of(filing: Filing, gi: Mapping[str, Any]) -> Optional[date]:
    """Balance-sheet date. The by-date list carries no period end, so read the statement's own header."""
    end = to_date(gi.get("DateOfEndOfReportingPeriod"))
    if end:
        return end
    fy_start, fy_end = to_date(gi.get("DateOfStartOfFinancialYear")), to_date(gi.get("DateOfEndOfFinancialYear"))
    if filing.quarter == "Yearly":
        return fy_end
    if fy_start and filing.quarter in ("Second quarter", "Half yearly"):
        m6, y6 = fy_start.month + 6, fy_start.year
        if m6 > 12:
            m6, y6 = m6 - 12, y6 + 1
        h1_end = date(y6, m6, 1) - timedelta(days=1)            # Apr FY → 30 Sep; Jan FY (ABB) → 30 Jun
        if filing.quarter == "Second quarter":
            return h1_end
        filed = to_date(filing.file_time)                         # SME half-yearly: H1 if filed within 4 months of H1
        return h1_end if filed and filed <= h1_end + timedelta(days=SME_H1_FILING_DAYS) else fy_end
    return None


# ── units ────────────────────────────────────────────────────────────────────────────────────────────────────────

def nearest_unit(ratio: Optional[float]) -> Optional[str]:
    """The unit whose factor (TrueData figure / crore figure) is nearest to `ratio`, only if within 1.5x of it."""
    if not ratio or ratio <= 0 or not math.isfinite(ratio):
        return None
    name, f = min(FACTORS.items(), key=lambda kv: abs(math.log(ratio / kv[1])))
    return name if abs(math.log(ratio / f)) < math.log(UNIT_TOLERANCE) else None


class OurFinancials:
    """Our own revenue per period, from nidp.nse_financials_quarterly (rows: symbol, period_end, consolidated,
    period_type, revenue_from_ops_cr, total_income_cr)."""

    def __init__(self, rows: Iterable[Mapping[str, Any]]):
        self.annual: Dict[Tuple[str, bool, date], float] = {}
        self.quarters: Dict[Tuple[str, bool], List[Tuple[date, float]]] = defaultdict(list)
        self.quarter: Dict[Tuple[str, bool, date], float] = {}
        for r in rows:
            rv = num(r.get("revenue_from_ops_cr")) or num(r.get("total_income_cr"))
            pe = r.get("period_end")
            pe = pe if isinstance(pe, date) else to_date(pe)
            if rv is None or pe is None:
                continue
            key = (str(r["symbol"]), bool(r["consolidated"]))
            ptype = str(r.get("period_type") or "").lower()
            if ptype == "annual":
                self.annual[key + (pe,)] = rv
            elif ptype == "quarterly":
                self.quarters[key].append((pe, rv))
                self.quarter[key + (pe,)] = rv
        for q in self.quarters.values():
            q.sort()

    def fy_revenue(self, symbol: str, consolidated: bool, fy_end: Optional[date]) -> Tuple[Optional[float], str]:
        if fy_end is None:
            return None, ""
        if (symbol, consolidated, fy_end) in self.annual:
            return self.annual[(symbol, consolidated, fy_end)], "annual row"
        q = [x for x in self.quarters.get((symbol, consolidated), []) if x[0] <= fy_end][-4:]
        if len(q) == 4 and q[-1][0] == fy_end:
            try:
                year_before = fy_end.replace(year=fy_end.year - 1)
            except ValueError:                                        # 29 Feb
                year_before = fy_end - timedelta(days=365)
            if q[0][0] > year_before:
                return sum(v for _, v in q), "sum of 4 quarters"
        return None, ""

    def quarter_revenue(self, symbol: str, consolidated: bool, period_end: date) -> Optional[float]:
        return self.quarter.get((symbol, consolidated, period_end))


@dataclass(frozen=True)
class Unit:
    name: str
    how: str
    anchor_capital: Optional[float] = None     # paid-up capital (reporting units) of the anchoring FY P&L


def td_revenue(pl: Mapping[str, Any]) -> Optional[float]:
    inc = pl.get("Income") or {}
    return num((inc.get("Operating") or {}).get("RevenueFromOperations")) or num(inc.get("TotalIncome"))


def infer_units(fy_pnls: Mapping[Tuple[str, str], Sequence[Tuple[Filing, Mapping[str, Any]]]],
                ours: OurFinancials, shares: Mapping[str, float]) -> Tuple[Dict[Tuple[str, str], Unit], Dict]:
    """One unit per (symbol, nature) from its fiscal-year P&Ls (cumulative, newest first).

    (a) revenue anchor: TrueData FY revenue / our FY revenue (annual row, else four quarters ending at the FY end);
    (b) share-capital anchor: our shares outstanding (market cap / close) vs PaidUpCapital × unit / FaceValue.
    Each accepted only within 1.5x of a unit factor. Returns (units, notes for keys without a unit)."""
    units: Dict[Tuple[str, str], Unit] = {}
    notes: Dict[Tuple[str, str], str] = {}
    for key, cands in fy_pnls.items():
        sym, nature = key
        cons = nature == "Consolidated"
        cands = [(f, pl) for f, pl in sorted(cands, key=lambda c: (c[0].file_time, c[0].id), reverse=True)
                 if usable(pl)]
        for f, pl in cands:
            rev = td_revenue(pl)
            fy_end = to_date((pl.get("GeneralInfo") or {}).get("ReportingEndDate"))
            ref, how = ours.fy_revenue(sym, cons, fy_end)
            if not (rev and ref and ref > 0):
                continue
            ratio = rev / ref
            name = nearest_unit(ratio)
            if name:
                units[key] = Unit(name, f"revenue anchor ({how}) ratio {ratio:.4g}", num(pl.get("PaidUpCapital")))
                break
            notes.setdefault(key, f"revenue anchor mismatch ratio {ratio:.4g}")
        if key in units or not shares.get(sym):
            continue
        for f, pl in cands:
            puc, fv = num(pl.get("PaidUpCapital")), num(pl.get("FaceValue"))
            if not (puc and fv and puc > 0 and fv > 0):
                continue
            rupees_per_unit = shares[sym] * fv / puc               # 1e7 crore, 1e6 million, 1e5 lakh ...
            name = nearest_unit(1e7 / rupees_per_unit)
            if name:
                units[key] = Unit(name, f"share-capital anchor (rupees per unit {rupees_per_unit:.4g})", puc)
                break
            notes.setdefault(key, f"share-capital anchor mismatch (rupees per unit {rupees_per_unit:.4g})")
    return units, notes


def unit_for(filing: Filing, units: Mapping[Tuple[str, str], Unit], notes: Mapping[Tuple[str, str], str],
             gi: Optional[Mapping[str, Any]]) -> Tuple[Optional[Unit], str]:
    """The company's anchored unit, else the filing's own rounding text, else (None, why)."""
    if filing.key in units:
        return units[filing.key], ""
    word = str((gi or {}).get("LevelOfRoundingUsedInFinancialStatements") or "").strip()
    w = ROUNDING_WORDS.get(word.lower())
    if w:
        return Unit(w, f"filing rounding '{word}'"), ""
    return None, notes.get(filing.key, "no anchor and no rounding text")


def capital_mismatch(statement_capital: Optional[float], unit: Unit) -> Optional[str]:
    """A reason when this filing's share capital is >= 6.67x away from the anchoring P&L's (units may differ); None
    when consistent or not checkable."""
    a = unit.anchor_capital
    if not (statement_capital and statement_capital > 0 and a and a > 0):
        return None
    ratio = statement_capital / a
    if ratio >= CAPITAL_RATIO_MAX or ratio <= 1 / CAPITAL_RATIO_MAX:
        return f"share capital {statement_capital:g} vs anchor {a:g} (unit may differ from the anchor filing)"
    return None


# ── offers ───────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class Offer:
    kind: str                         # 'balance_sheet' | 'cash_flow' | 'finance_costs'
    symbol: str
    period_end: date
    consolidated: bool
    quarter: str
    filing_id: int
    file_time: str
    unit: str
    unit_how: str
    values: Dict[str, Decimal]        # warehouse column → crore; NULLs left out
    may_insert: bool = False          # may create a row when none exists for the date


@dataclass(frozen=True)
class Reject:
    kind: str
    symbol: str
    period_end: Optional[date]
    filing_id: int
    reason: str


@dataclass
class TransformResult:
    offers: List[Offer] = field(default_factory=list)
    rejects: List[Reject] = field(default_factory=list)
    counts: Counter = field(default_factory=Counter)
    units: Dict[Tuple[str, str], Unit] = field(default_factory=dict)
    unit_notes: Dict[Tuple[str, str], str] = field(default_factory=dict)

    def summary(self) -> Dict[str, Any]:
        by_kind = Counter(o.kind for o in self.offers)
        reasons = Counter(f"{r.kind}: {r.reason.split(' (')[0][:60]}" for r in self.rejects)
        return {"offers": dict(by_kind), "rejects": len(self.rejects), "counts": dict(sorted(self.counts.items())),
                "units": dict(Counter(u.name for u in self.units.values())),
                "units_how": dict(Counter(u.how.split(" (")[0].split(" ratio")[0] for u in self.units.values())),
                "reject_reasons": dict(reasons.most_common(12))}


def _group(d: Mapping[str, Any], *names: str) -> Mapping[str, Any]:
    for n in names:
        g = d.get(n)
        if isinstance(g, dict):
            return g
    return {}


def balance_sheet_offer(filing: Filing, al: Mapping[str, Any], unit: Optional[Unit], unit_why: str,
                        out: TransformResult) -> Optional[Offer]:
    gi = al.get("GeneralInfo") or {}
    assets, liabs = _group(al, "AllAssets"), _group(al, "AllLiabilities")
    A, OA = _group(assets, "CurrentAssetsGroup"), _group(assets, "OtherAssetsGroup")
    L = _group(liabs, "currentLiabilitiesGroup", "CurrentLiabilitiesGroup")
    NL = _group(liabs, "noncurrentLiabilitiesGrouup", "noncurrentLiabilitiesGroup", "NoncurrentLiabilitiesGroup")
    E = _group(liabs, "equityAndLiabilitiesGroup", "EquityAndLiabilitiesGroup")
    if num(OA.get("Advances")):
        out.counts["bs_bank_format_skipped"] += 1
        return None
    period_end = period_end_of(filing, gi)
    total_assets = num(A.get("Assets"))
    eq_liab = num(L.get("EquityAndLiabilities"))
    liabilities = num(L.get("Liabilities"))
    equity = num(E.get("Equity")) or num(E.get("ShareholdersFunds"))
    ca = num(A.get("CurrentAssets")) or None
    cl = num(L.get("CurrentLiabilities"))
    ncl = num(NL.get("NoncurrentLiabilities"))
    if not cl and liabilities and ncl is not None and liabilities - ncl > 0:
        cl = liabilities - ncl                                     # TrueData leaves CurrentLiabilities 0 (TCS)
    recv = num(A.get("TradeReceivablesCurrent")) or num(A.get("TradeReceivables")) or None
    msme = num(L.get("OutstandingDuesOfMicroEnterprisesAndSmallEnterprises")) or 0.0
    others = num(L.get("OutstandingDuesOfCreditorsOtherThanMicroEnterprisesAndSmallEnterprises")) or 0.0
    pay = num(L.get("TradePayablesCurrent")) or (msme + others) or None
    raw = {"current_assets_cr": ca, "current_liabilities_cr": cl or None, "inventory_cr": num(A.get("Inventories")),
           "trade_receivables_cr": recv, "trade_payables_cr": pay,
           "cash_and_equiv_cr": num(A.get("CashAndCashEquivalents")),
           "long_term_debt_cr": num(NL.get("BorrowingsNoncurrent")) or num(NL.get("LongTermBorrowings")),
           "short_term_debt_cr": num(L.get("BorrowingsCurrent")) or num(L.get("ShortTermBorrowings")),
           "total_equity_cr": equity}
    why: List[str] = []
    if unit is None:
        why.append(f"unit unknown ({unit_why})")
    else:
        bad = capital_mismatch(num(E.get("EquityShareCapital")) or num(E.get("ShareCapital")), unit)
        if bad:
            why.append(bad)
    if period_end is None:
        why.append("no period end")
    if not total_assets:
        why.append("no total assets")
    elif eq_liab and abs(eq_liab / total_assets - 1) > IDENTITY_TOLERANCE:
        why.append(f"assets {total_assets:.0f} != equity+liabilities {eq_liab:.0f}")
    if ca and total_assets and ca > total_assets * 1.001:
        why.append("current assets > total assets")
    if recv and ca and recv > ca * 1.001:
        why.append("receivables > current assets")
    if why:
        out.rejects.append(Reject("balance_sheet", filing.symbol, period_end, filing.id, "; ".join(why)))
        return None
    values = {c: to_crore(v, unit.name) for c, v in raw.items() if v is not None}
    return Offer("balance_sheet", filing.symbol, period_end, filing.consolidated, filing.quarter, filing.id,
                 filing.file_time, unit.name, unit.how, values, may_insert=filing.quarter == "Yearly")


def cash_flow_offer(filing: Filing, cf: Mapping[str, Any], al: Optional[Mapping[str, Any]], unit: Optional[Unit],
                    unit_why: str, out: TransformResult) -> Optional[Offer]:
    if filing.quarter != "Yearly":
        out.counts["cf_half_year_not_loaded"] += 1                # never: the table is annual
        return None
    gi = cf.get("GeneralInfo") or {}
    S = _group(cf, "CashFlowSummary")
    INV = _group(cf, "CashFlowFromInvestingActivity")
    cfo, cfi, cff = num(S.get("CashFlowOperating")), num(S.get("CashFlowInvesting")), num(S.get("CashFlowFinancing"))
    net = num(S.get("CashIncreaseDecrease"))
    fx = num(S.get("FinancingEffectOfExchRateOnCash")) or 0.0
    before = num(S.get("CashIncreaseDecreaseBeforeExchRate"))
    capex_out = sum(num(INV.get(k)) or 0.0 for k in ("PurchasePropPlantEquipAsInvesting",
                                                     "PurchaseOfIntangibleAssetsAsInvesting",
                                                     "PurchaseOfTangibleAssetsAsInvesting"))
    period_end = to_date(gi.get("ReportingEndDate"))     # an FY filing's header may say 01-Jan..31-Mar: values are FY
    why: List[str] = []
    if unit is None:
        why.append(f"unit unknown ({unit_why})")
    elif usable(al):
        E = _group(_group(al, "AllLiabilities"), "equityAndLiabilitiesGroup", "EquityAndLiabilitiesGroup")
        bad = capital_mismatch(num(E.get("EquityShareCapital")) or num(E.get("ShareCapital")), unit)
        if bad:
            why.append(bad)
    if period_end is None:
        why.append("no period end")
    if cfo is None:
        why.append("no CFO")
    if cfo is not None and cfi is not None and cff is not None and net is not None:
        scale = max(abs(cfo), abs(cfi), abs(cff), 1.0)
        expected = before if before is not None else net - fx
        if abs((cfo + cfi + cff) - expected) > max(IDENTITY_TOLERANCE * scale, 2.0):
            why.append(f"CFO+CFI+CFF {cfo + cfi + cff:.0f} != net change before FX {expected:.0f}")
    if why:
        out.rejects.append(Reject("cash_flow", filing.symbol, period_end, filing.id, "; ".join(why)))
        return None
    raw = {"cfo_cr": cfo, "cfi_cr": cfi, "cff_cr": cff, "capex_cr": -capex_out if capex_out else None,
           "net_change_cash_cr": net}
    values = {c: to_crore(v, unit.name) for c, v in raw.items() if v is not None}
    return Offer("cash_flow", filing.symbol, period_end, filing.consolidated, filing.quarter, filing.id,
                 filing.file_time, unit.name, unit.how, values, may_insert=True)


def is_bank_pnl(pl: Mapping[str, Any]) -> bool:
    gi = pl.get("GeneralInfo") or {}
    op = _group(_group(pl, "Income"), "Operating")
    return str(gi.get("Type") or "").strip().lower() == "banking" or num(op.get("TotalInterestEarned")) is not None


def finance_cost_offer(filing: Filing, plq: Mapping[str, Any], unit: Optional[Unit], unit_why: str,
                       ours: OurFinancials, out: TransformResult) -> Optional[Offer]:
    if filing.quarter not in QUARTER_LABELS:
        out.counts["fc_not_a_quarter_filing"] += 1
        return None
    if is_bank_pnl(plq):
        out.counts["fc_bank_format_skipped"] += 1
        return None
    gi = plq.get("GeneralInfo") or {}
    start, end = to_date(gi.get("ReportingStartDate")), to_date(gi.get("ReportingEndDate"))
    interest = num(_group(_group(plq, "Expenses"), "NonOperating").get("InterestExpense"))
    if interest is None:
        out.counts["fc_no_interest_field"] += 1
        return None
    why: List[str] = []
    if unit is None:
        why.append(f"unit unknown ({unit_why})")
    else:
        bad = capital_mismatch(num(plq.get("PaidUpCapital")), unit)
        if bad:
            why.append(bad)
    if not (start and end and QUARTER_DAYS[0] <= (end - start).days + 1 <= QUARTER_DAYS[1]):
        why.append(f"period {start}..{end} is not a single quarter")
    if interest < 0:
        why.append(f"negative interest expense {interest:g}")
    if unit is not None and end is not None and not why:
        ref = ours.quarter_revenue(filing.symbol, filing.consolidated, end)
        rev = td_revenue(plq)
        if not ref or ref <= 0 or not rev:
            why.append("no quarter revenue on both sides to confirm the period")
        elif abs((rev / FACTORS[unit.name]) / ref - 1) > QUARTER_REVENUE_TOLERANCE:
            why.append(f"quarter revenue {rev / FACTORS[unit.name]:.2f} cr vs ours {ref:.2f} cr")
    if why:
        out.rejects.append(Reject("finance_costs", filing.symbol, end, filing.id, "; ".join(why)))
        return None
    return Offer("finance_costs", filing.symbol, end, filing.consolidated, filing.quarter, filing.id,
                 filing.file_time, unit.name, unit.how, {"finance_costs_cr": to_crore(interest, unit.name)})


# ── the whole pass ───────────────────────────────────────────────────────────────────────────────────────────────

Getter = Callable[[str, int], Optional[Mapping[str, Any]]]     # (kind, filing id) → payload | empty marker | None


def fy_pnl_candidates(all_filings: Sequence[Filing], keys: Iterable[Tuple[str, str]]) -> Dict[Tuple[str, str],
                                                                                             List[Filing]]:
    keys = set(keys)
    out: Dict[Tuple[str, str], List[Filing]] = defaultdict(list)
    for f in all_filings:
        if f.quarter == "Yearly" and f.key in keys:
            out[f.key].append(f)
    for v in out.values():
        v.sort(key=lambda f: (f.file_time, f.id), reverse=True)
    return out


def statements_needed(window_filings: Sequence[Filing], all_filings: Sequence[Filing], finance_costs: bool = True,
                      rank: Optional[Mapping[str, int]] = None) -> List[Tuple[str, int]]:
    """(kind, filing id) to have in the cache, in fetch order. Company by company (`rank`: lower first, e.g. largest
    market cap): its latest FY P&L (unit anchor), then the balance sheet and cash flow of each half-year / fiscal-year
    filing; after every company, the quarter-only P&Ls (finance costs). A run cut short has the most useful part."""
    rank = rank or {}
    last = len(rank) + 1
    fy = fy_pnl_candidates(all_filings, {f.key for f in window_filings})
    first: List[Tuple[int, str, int, Tuple[str, int]]] = []
    for key, cands in fy.items():
        first.append((rank.get(key[0], last), key[0], 0, ("pl", cands[0].id)))
    for f in window_filings:
        if f.quarter in H1_FY:
            first.append((rank.get(f.symbol, last), f.symbol, 1, ("al", f.id)))
            first.append((rank.get(f.symbol, last), f.symbol, 2, ("cf", f.id)))
    need = [n for *_, n in sorted(first, key=lambda x: x[:3] + (x[3][1],))]
    if finance_costs:
        need += [("plq", f.id) for f in sorted(window_filings, key=lambda f: (rank.get(f.symbol, last), f.symbol, f.id))
                 if f.quarter in QUARTER_LABELS]
    seen, ordered = set(), []
    for n in need:
        if n not in seen:
            seen.add(n)
            ordered.append(n)
    return ordered


def build(window_filings: Sequence[Filing], all_filings: Sequence[Filing], get: Getter, ours: OurFinancials,
          shares: Mapping[str, float], finance_costs: bool = True) -> TransformResult:
    """Offers for the load window's filings. `all_filings` (deduped, nature-filtered) supplies the fiscal-year P&Ls that
    anchor each company's unit. A statement `get` returns None for (not fetched) is counted, never guessed."""
    out = TransformResult()
    cands = fy_pnl_candidates(all_filings, {f.key for f in window_filings})
    fy_pnls = {k: [(f, get("pl", f.id)) for f in v] for k, v in cands.items()}
    out.units, out.unit_notes = infer_units(fy_pnls, ours, shares)
    for f in window_filings:
        out.counts["filings"] += 1
        if f.quarter in H1_FY:
            al = get("al", f.id)
            gi = al.get("GeneralInfo") if usable(al) else None
            unit, why = unit_for(f, out.units, out.unit_notes, gi)
            if al is None:
                out.counts["bs_not_fetched"] += 1
            elif not usable(al) or not isinstance(al.get("AllAssets"), dict):
                out.counts["bs_empty"] += 1
            else:
                o = balance_sheet_offer(f, al, unit, why, out)
                if o:
                    out.offers.append(o)
            cf = get("cf", f.id)
            if cf is None:
                out.counts["cf_not_fetched"] += 1
            elif not usable(cf) or not isinstance(cf.get("CashFlowSummary"), dict):
                out.counts["cf_empty"] += 1
            else:
                o = cash_flow_offer(f, cf, al, unit, why, out)
                if o:
                    out.offers.append(o)
        if finance_costs and f.quarter in QUARTER_LABELS:
            plq = get("plq", f.id)
            if plq is None:
                out.counts["fc_not_fetched"] += 1
            elif not usable(plq):
                out.counts["fc_empty"] += 1
            else:
                unit, why = unit_for(f, out.units, out.unit_notes, None)
                o = finance_cost_offer(f, plq, unit, why, ours, out)
                if o:
                    out.offers.append(o)
    out.offers = latest_per_key(out.offers, out.counts)
    return out


def latest_per_key(offers: Sequence[Offer], counts: Counter) -> List[Offer]:
    """One offer per (kind, symbol, period end, consolidated): the latest filing (file time, then id)."""
    best: Dict[Tuple[str, str, date, bool], Offer] = {}
    for o in offers:
        k = (o.kind, o.symbol, o.period_end, o.consolidated)
        if k in best:
            counts["superseded_by_later_filing"] += 1
            if (o.file_time, o.filing_id) < (best[k].file_time, best[k].filing_id):
                continue
        best[k] = o
    return sorted(best.values(), key=lambda o: (o.kind, o.symbol, o.period_end, o.consolidated))
