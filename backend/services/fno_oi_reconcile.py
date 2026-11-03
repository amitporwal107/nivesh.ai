"""F&O open-interest reconciliation: does every OI figure the app shows agree with the exchange's files and with itself?

Asked for by the owner on 3 Nov 2026 ("For HDFCAMC the OI delta looks to be unreal"), as a reconciliation between three
sources: the previous session's NSE F&O bhavcopy (P), the current session's bhavcopy (D), and the intraday Kite
snapshots (K), against what the app shows: the option chain table and the chart. Checks (test_reports/
fno_oi_reconcile_TESTCASES.md):

    C1  previous-day closing OI   the app's oi − change_in_oi per contract = the contract's OI in P (absent from P = 0)
    C2  current closing OI        the app's oi (chain, futures, the chart's last daily bar) = D; Kite's last candle ON
                                  day D = D (the third source; a contract with no candle that day is not comparable)
    C3  OI change                 change_in_oi = D − P, for the app's figures and for NSE's own column as stored
    C4  OI change %               the screen's formula, change ÷ (oi − change) × 100 (frontend reco-data.ts oiChangePct,
                                  ChartAnalysis.tsx pctOf), on the app's figures = (D − P) ÷ P × 100. WARN when the
                                  figures agree but the base is under SMALL_BASE_LOTS lots and the % is BIG_PCT or more:
                                  a true figure that reads as a huge move (2,420 PE: 3 lots → 57 lots = +1800%)
    C5  intraday OI change        futures windows: oi_change = this window's OI − the previous window's; the options pane:
                                  summed CE / PE OI = Σ the contracts' candles at that time, *_oi_change = row − previous
                                  row. WARN when the pane has no sums at all (one contract without a candle blanks them)
    C6  chart totals vs the chain the chain summary totals (the chart's PCR, walls) = Σ D over the expiry; each
                                  consolidated strike = Σ the per-expiry chain rows; the chart's futures pane last OI =
                                  the futures route's OI for the slot's contract (Σ for consolidated)
    C7  segments sum to net       Σ increases + Σ decreases of a series' OI changes = its last OI − its first OI. A gap
                                  is attributed to contract rolls where the series changes contract (the current-month
                                  line falls into expiry, and the jump to the next contract is never a bar)

Statuses: PASS matched · FAIL did not match (a wrong figure, or one misleading by construction) · WARN the figures match
but the display misleads or is empty · SKIP a source could not answer (the reason is kept; never counted as a pass).

Everything here is pure: no database, no Kite, no HTTP. scripts/reconcile_fno_oi.py reads the sources and calls `run`.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"
_RANK = {FAIL: 3, WARN: 2, PASS: 1, SKIP: 0}

CHECKS: Dict[str, str] = {
    "C1": "Previous-day closing OI matches the previous session's bhavcopy",
    "C2": "Current closing OI matches the current session's bhavcopy",
    "C3": "OI change = current OI - previous OI",
    "C4": "OI change % = change / previous OI x 100",
    "C5": "Intraday OI change matches the intraday snapshot differences",
    "C6": "Chart totals match the option chain",
    "C7": "Increase and decrease segments sum to the net OI movement",
}

SMALL_BASE_LOTS = 10     # a previous OI under this many lots is a small base for a % change
BIG_PCT = 100.0          # ... and a % change this large on it reads as a huge move
PCT_TOL = 0.05           # percent points; the screen shows one decimal
EXAMPLES = 8             # non-passing findings kept per check in the summary

Key = Tuple[str, str, Optional[float]]          # (expiry, FUT | CE | PE, strike; None for a future)
Book = Dict[Key, Dict[str, Optional[int]]]      # key → {"oi", "chg", "lot"}


# ── helpers ──────────────────────────────────────────────────────────────────

def _int(v: Any) -> Optional[int]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(round(f)) if f == f else None


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _day(v: Any) -> Optional[str]:
    return v[:10] if isinstance(v, str) and len(v) >= 10 else None


def label(key: Key) -> str:
    expiry, kind, strike = key
    if kind == "FUT":
        return f"{expiry} FUT"
    k = int(strike) if strike is not None and float(strike).is_integer() else strike
    return f"{expiry} {k} {kind}"


def finding(check: str, status: str, item: str, expected: Any = None, actual: Any = None, note: Optional[str] = None,
            source: Optional[str] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"check": check, "status": status, "item": item}
    if expected is not None or actual is not None:
        out["expected"], out["actual"] = expected, actual
        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            out["diff"] = round(actual - expected, 4)
    if source:
        out["source"] = source
    if note:
        out["note"] = note
    return out


def bhav_book(rows: Iterable[Any]) -> Book:
    """Bhavcopy rows (DaaS /v1/fno/{symbol}?on=day) → {(expiry, FUT|CE|PE, strike|None): {oi, chg, lot}}."""
    book: Book = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        expiry, kind = _day(r.get("expiry_date")), str(r.get("option_type") or "").upper()
        if not expiry or kind not in ("FUT", "CE", "PE"):
            continue
        strike = None if kind == "FUT" else _num(r.get("strike_price"))
        if kind != "FUT" and strike is None:
            continue
        book[(expiry, kind, strike)] = {"oi": _int(r.get("open_interest")), "chg": _int(r.get("change_in_oi")),
                                        "lot": _int(r.get("new_board_lot_qty"))}
    return book


def chain_items(chains: Dict[str, Dict[str, Any]]) -> List[Tuple[Key, Dict[str, Any]]]:
    """Every call and put the chain route sent, per expiry: (key, side)."""
    out: List[Tuple[Key, Dict[str, Any]]] = []
    for expiry, ch in chains.items():
        for r in (ch or {}).get("strikes") or []:
            strike = _num(r.get("strike"))
            for side, kind in (("call", "CE"), ("put", "PE")):
                s = r.get(side)
                if strike is not None and isinstance(s, dict):
                    out.append(((expiry, kind, strike), s))
    return out


def futures_items(futures: Optional[Dict[str, Any]]) -> List[Tuple[Key, Dict[str, Any]]]:
    return [((f["expiry"], "FUT", None), f) for f in (futures or {}).get("futures") or [] if isinstance(f, dict) and f.get("expiry")]


def _prev_oi(prev: Book, key: Key) -> int:
    """A contract's OI on the previous session; a contract not listed then had none."""
    return (prev.get(key) or {}).get("oi") or 0


def screen_pct(oi: Optional[int], change: Optional[int]) -> Optional[float]:
    """The screen's OI Δ% (frontend reco-data.ts oiChangePct and ChartAnalysis.tsx pctOf): change ÷ (oi − change) × 100,
    none when the previous OI it implies is not above zero."""
    if oi is None or change is None:
        return None
    prev = oi - change
    return change / prev * 100 if prev > 0 else None


def expected_pct(today: Optional[int], prev: Optional[int]) -> Optional[float]:
    """(D − P) ÷ P × 100 from the two bhavcopies; none for a contract with no OI the session before."""
    if today is None or prev is None or prev <= 0:
        return None
    return (today - prev) / prev * 100


# ── C1 previous-day closing OI ───────────────────────────────────────────────

def check_previous_oi(items: Sequence[Tuple[Key, Dict[str, Any]]], prev: Book, where: str) -> List[Dict[str, Any]]:
    out = []
    for key, s in items:
        oi, chg = _int(s.get("oi")), _int(s.get("change_in_oi"))
        if oi is None or chg is None:
            out.append(finding("C1", SKIP, label(key), note=f"{where} sent no OI or OI change", source=where))
            continue
        exp, act = _prev_oi(prev, key), oi - chg
        note = None if key in prev else "not listed on the previous session (previous OI 0)"
        out.append(finding("C1", PASS if act == exp else FAIL, label(key), exp, act, note, where))
    return out


# ── C2 current closing OI ────────────────────────────────────────────────────

def check_close_oi(items: Sequence[Tuple[Key, Dict[str, Any]]], today: Book, where: str) -> List[Dict[str, Any]]:
    out = []
    for key, s in items:
        act = _int(s.get("oi"))
        row = today.get(key)
        if row is None:
            out.append(finding("C2", FAIL, label(key), None, act, "the app shows a contract the day's bhavcopy does not have", where))
            continue
        out.append(finding("C2", PASS if act == row["oi"] else FAIL, label(key), row["oi"], act, None, where))
    return out


def kite_last_on_day(buildup: Optional[Dict[str, Any]], options: Optional[Dict[str, Any]], day: str
                     ) -> Tuple[Dict[Key, Tuple[str, int]], List[str], Optional[str]]:
    """Kite's last candle ON `day` per contract: ({key: (time, oi)}, contracts with no candle that day, why Kite could
    not be read or None). Futures candles are [t, close, volume, oi]; option candles [t, o, h, l, c, volume, oi]."""
    last: Dict[Key, Tuple[str, int]] = {}
    none: List[str] = []
    reasons = []
    if buildup is not None:
        if buildup.get("mode") != "intraday":
            reasons.append(f"futures: {buildup.get('kite_reason') or buildup.get('mode') or 'no intraday mode'}")
        else:
            for c in buildup.get("contracts") or []:
                key = (c.get("expiry"), "FUT", None)
                bars = [b for b in c.get("bars") or [] if _day(b[0]) == day and _int(b[3]) is not None]
                if bars:
                    last[key] = (bars[-1][0], _int(bars[-1][3]))
                else:
                    none.append(label(key))
    if options is not None:
        if options.get("availability") != "ok":
            reasons.append(f"options: {options.get('availability')}")
        else:
            expiry = options.get("expiry")
            listed = set()
            for c in options.get("contracts") or []:
                listed.add(c.get("tradingsymbol"))
                key = (expiry, str(c.get("type") or "").upper(), _num(c.get("strike")))
                bars = [b for b in c.get("bars") or [] if _day(b[0]) == day and len(b) > 6 and _int(b[6]) is not None]
                if bars:
                    last[key] = (bars[-1][0], _int(bars[-1][6]))
                else:
                    none.append(label(key))
            none.extend(f"{m} (Kite sent no candles)" for m in options.get("missing") or [] if m not in listed)
    return last, none, "; ".join(reasons) or None


def check_kite_close(last: Dict[Key, Tuple[str, int]], none: Sequence[str], reason: Optional[str], today: Book,
                     day: str) -> List[Dict[str, Any]]:
    out = []
    if reason:
        out.append(finding("C2", SKIP, "Kite intraday", note=f"Kite could not be compared: {reason}", source="kite"))
    for key, (t, oi) in sorted(last.items(), key=lambda kv: label(kv[0])):
        row = today.get(key)
        if row is None or row["oi"] is None:
            out.append(finding("C2", SKIP, label(key), None, oi, f"not in the {day} bhavcopy", "kite"))
            continue
        out.append(finding("C2", PASS if oi == row["oi"] else FAIL, label(key), row["oi"], oi,
                           None if oi == row["oi"] else f"Kite's last candle on {day} ({t[11:16]}) vs NSE's closing OI",
                           "kite"))
    for item in none:
        out.append(finding("C2", SKIP, item, note=f"no Kite candle on {day}: not comparable", source="kite"))
    return out


def check_chart_close(buildup: Optional[Dict[str, Any]], today: Book, day: str) -> List[Dict[str, Any]]:
    """The chart's futures pane (daily bars): the last bar per slot is day D with D's OI for its contract."""
    out = []
    for c in (buildup or {}).get("contracts") or []:
        bars = c.get("daily_bars") or []
        if not bars:
            continue
        last = bars[-1]
        item = f"chart {c.get('slot')} ({last[5]})"
        if last[0][:10] != day:
            out.append(finding("C2", FAIL, item, day, last[0][:10], "the chart's last daily bar is not the bhavcopy's day", "chart"))
            continue
        row = today.get((last[5], "FUT", None))
        exp = row["oi"] if row else None
        out.append(finding("C2", PASS if exp is not None and _int(last[3]) == exp else FAIL, item, exp, _int(last[3]), None, "chart"))
    return out


# ── C3 OI change ─────────────────────────────────────────────────────────────

def check_change(items: Sequence[Tuple[Key, Dict[str, Any]]], today: Book, prev: Book, where: str) -> List[Dict[str, Any]]:
    out = []
    for key, s in items:
        row = today.get(key)
        act = _int(s.get("change_in_oi"))
        if row is None or row["oi"] is None:
            out.append(finding("C3", SKIP, label(key), None, act, "not in the day's bhavcopy", where))
            continue
        exp = row["oi"] - _prev_oi(prev, key)
        out.append(finding("C3", PASS if act == exp else FAIL, label(key), exp, act, None, where))
    return out


def check_source_change(today: Book, prev: Book) -> List[Dict[str, Any]]:
    """NSE's own change_in_oi column as stored for D = D's OI − P's OI as stored: catches a partial or missing load."""
    out = []
    for key, row in sorted(today.items(), key=lambda kv: label(kv[0])):
        if row["oi"] is None or row["chg"] is None:
            continue
        exp = row["oi"] - _prev_oi(prev, key)
        out.append(finding("C3", PASS if row["chg"] == exp else FAIL, label(key), exp, row["chg"],
                           None if row["chg"] == exp else "NSE's change_in_oi disagrees with the stored previous session",
                           "bhavcopy"))
    return out


def check_chart_change(buildup: Optional[Dict[str, Any]], today: Book, prev: Book, day: str) -> List[Dict[str, Any]]:
    out = []
    for c in (buildup or {}).get("contracts") or []:
        bars = c.get("daily_bars") or []
        if not bars or bars[-1][0][:10] != day:
            continue
        last = bars[-1]
        key = (last[5], "FUT", None)
        row = today.get(key)
        if row is None or row["oi"] is None:
            continue
        exp = row["oi"] - _prev_oi(prev, key)
        out.append(finding("C3", PASS if _int(last[4]) == exp else FAIL, f"chart {c.get('slot')} ({last[5]})", exp, _int(last[4]), None, "chart"))
    return out


# ── C4 OI change % ───────────────────────────────────────────────────────────

def _pct_finding(item: str, act: Optional[float], exp: Optional[float], prev_oi: Optional[int], today_oi: Optional[int],
                 lot: Optional[int], small_base_lots: int, where: str) -> Dict[str, Any]:
    if act is None and exp is None:
        note = "new contract: no % shown and none expected" if (today_oi or 0) > 0 and not prev_oi else None
        return finding("C4", PASS, item, None, None, note, where)
    if act is None or exp is None:
        return finding("C4", FAIL, item, None if exp is None else round(exp, 1), None if act is None else round(act, 1),
                       "one side has a % and the other none", where)
    if abs(act - exp) > PCT_TOL:
        return finding("C4", FAIL, item, round(exp, 2), round(act, 2), None, where)
    if lot and prev_oi is not None and prev_oi < small_base_lots * lot and abs(act) >= BIG_PCT:
        return finding("C4", WARN, item, round(exp, 1), round(act, 1),
                       f"true but misleading: {prev_oi // lot} lots -> {(today_oi or 0) // lot} lots "
                       f"(OI {prev_oi:,} -> {today_oi or 0:,}, a base under {small_base_lots} lots)", where)
    return finding("C4", PASS, item, round(exp, 1), round(act, 1), None, where)


def check_change_pct(items: Sequence[Tuple[Key, Dict[str, Any]]], today: Book, prev: Book, lot_size: Optional[int],
                     where: str, small_base_lots: int = SMALL_BASE_LOTS) -> List[Dict[str, Any]]:
    out = []
    for key, s in items:
        row = today.get(key)
        if row is None:
            continue
        p = _prev_oi(prev, key)
        act = screen_pct(_int(s.get("oi")), _int(s.get("change_in_oi")))
        out.append(_pct_finding(label(key), act, expected_pct(row["oi"], p), p, row["oi"], row.get("lot") or lot_size,
                                small_base_lots, where))
    return out


def check_chart_change_pct(buildup: Optional[Dict[str, Any]], today: Book, prev: Book, day: str,
                           small_base_lots: int = SMALL_BASE_LOTS) -> List[Dict[str, Any]]:
    """The chart's FUT OI Δ stat (pctOf on the last daily bar) per slot."""
    out = []
    for c in (buildup or {}).get("contracts") or []:
        bars = c.get("daily_bars") or []
        if not bars or bars[-1][0][:10] != day:
            continue
        last = bars[-1]
        key = (last[5], "FUT", None)
        row = today.get(key)
        if row is None:
            continue
        p = _prev_oi(prev, key)
        out.append(_pct_finding(f"chart {c.get('slot')} ({last[5]})", screen_pct(_int(last[3]), _int(last[4])),
                                expected_pct(row["oi"], p), p, row["oi"], row.get("lot") or c.get("lot_size"), small_base_lots, "chart"))
    return out


# ── C5 intraday OI change ────────────────────────────────────────────────────

def _series_of(buildup: Optional[Dict[str, Any]]) -> List[Tuple[str, Dict[str, Any]]]:
    b = buildup or {}
    out = [(f"{c.get('slot')} ({c.get('expiry')})", c) for c in b.get("contracts") or []]
    if isinstance(b.get("consolidated"), dict):
        out.append(("consolidated", b["consolidated"]))
    return out


def check_intraday_windows(buildup: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Each intraday window's oi_change = its OI − the previous window's OI (the same contract all through), and its
    oi_change_pct = oi_change ÷ (oi − oi_change) × 100 (2 decimals)."""
    if buildup is None:
        return []
    if buildup.get("mode") != "intraday":
        return [finding("C5", SKIP, "futures windows", note=f"no intraday windows: {buildup.get('kite_reason') or buildup.get('mode')}", source="kite")]
    out = []
    for name, s in _series_of(buildup):
        ws = s.get("windows") or []
        bad, n = [], 0
        for a, b in zip(ws, ws[1:]):
            oa, ob, ch = _int(a.get("oi")), _int(b.get("oi")), _int(b.get("oi_change"))
            if oa is None or ob is None or ch is None:
                continue
            n += 1
            if ch != ob - oa:
                bad.append(finding("C5", FAIL, f"{name} window {b.get('start', '')[5:16]}", ob - oa, ch, None, "kite"))
            pct = _num(b.get("oi_change_pct"))
            want = screen_pct(ob, ch)
            if pct is not None and want is not None and abs(pct - want) > 0.011:
                bad.append(finding("C4", FAIL, f"{name} window {b.get('start', '')[5:16]} OI %", round(want, 2), pct, None, "kite"))
        out.extend(bad)
        if n and not any(f["check"] == "C5" for f in bad):
            out.append(finding("C5", PASS, f"{name}: {n} window changes = OI differences", source="kite"))
    return out


def check_options_series(options: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The options pane: each row's ce_oi / pe_oi = Σ the contracts' candle OI at that time (every contract must have a
    candle then), and *_oi_change = this row − the previous row. A null row is a sum the service withheld."""
    if options is None:
        return []
    if options.get("availability") != "ok":
        return [finding("C5", SKIP, "options pane", note=f"Kite options intraday not available: {options.get('availability')}", source="kite")]
    contracts = [c for c in options.get("contracts") or [] if str(c.get("type") or "").upper() in ("CE", "PE")]
    listed = {c.get("tradingsymbol") for c in contracts}
    missing = [m for m in options.get("missing") or [] if m not in listed]     # the route may list one in both
    # candle OI per time and side; a time is complete when EVERY requested contract (both sides, and those Kite sent
    # nothing for) has a candle then: the service's rule for sending sums at all
    at: Dict[str, Dict[str, List[Optional[int]]]] = {}
    for c in contracts:
        for b in c.get("bars") or []:
            if len(b) > 6:
                at.setdefault(b[0], {"CE": [], "PE": []})[str(c["type"]).upper()].append(_int(b[6]))
    n_all = len(contracts) + len(missing)
    rows = options.get("series") or []
    out, sums_ok, chg_ok, withheld = [], 0, 0, 0
    for i, r in enumerate(rows):
        here = at.get(r.get("t")) or {"CE": [], "PE": []}
        complete = len(here["CE"]) + len(here["PE"]) == n_all
        for side in ("ce", "pe"):
            got = _int(r.get(f"{side}_oi"))
            vals = here[side.upper()]
            want = sum(vals) if complete and all(v is not None for v in vals) else None
            if got is None:
                withheld += 1
                if want is not None:
                    out.append(finding("C5", FAIL, f"options {side.upper()} sum {str(r.get('t'))[5:16]}", want, None,
                                       "every contract has a candle here but the sum is missing", "kite"))
                continue
            if got != want:
                out.append(finding("C5", FAIL, f"options {side.upper()} sum {str(r.get('t'))[5:16]}", want, got, None, "kite"))
            else:
                sums_ok += 1
            prev = rows[i - 1] if i > 0 else None
            p, ch = (_int(prev.get(f"{side}_oi")) if prev else None), _int(r.get(f"{side}_oi_change"))
            if p is not None and ch is not None:
                if ch == got - p:
                    chg_ok += 1
                else:
                    out.append(finding("C5", FAIL, f"options {side.upper()} change {str(r.get('t'))[5:16]}", got - p, ch, None, "kite"))
    total = 2 * len(rows)
    if total and withheld == total:
        gaps = sorted({str(c.get("tradingsymbol")) for c in contracts if len(c.get("bars") or []) < len(rows)} | set(missing))
        named = ", ".join(gaps[:6]) + (f" and {len(gaps) - 6} more" if len(gaps) > 6 else "")
        out.append(finding("C5", WARN, "options pane sums", note=f"no sums at all: {withheld} of {total} CE/PE rows are null because "
                           f"{len(gaps)} of {n_all} contracts lack a candle at some time ({named})", source="kite"))
    elif sums_ok or chg_ok:
        out.append(finding("C5", PASS, f"options pane: {sums_ok} sums = contract candles, {chg_ok} changes = row differences"
                           + (f", {withheld} rows withheld" if withheld else ""), source="kite"))
    return out


# ── C6 chart totals vs the chain ─────────────────────────────────────────────

def check_chain_totals(chains: Dict[str, Dict[str, Any]], today: Book) -> List[Dict[str, Any]]:
    """Each expiry's summary totals (the chart's PCR, walls and OI stats) = Σ the day's bhavcopy over that expiry."""
    out = []
    for expiry, ch in chains.items():
        s = (ch or {}).get("summary") or {}
        for field, kind, col in (("total_call_oi", "CE", "oi"), ("total_put_oi", "PE", "oi"),
                                 ("total_call_oi_change", "CE", "chg"), ("total_put_oi_change", "PE", "chg")):
            exp = sum((v[col] or 0) for k, v in today.items() if k[0] == expiry and k[1] == kind)
            act = _int(s.get(field))
            out.append(finding("C6", PASS if act == exp else FAIL, f"{expiry} chain summary {field}", exp, act, None, "chain"))
    return out


def check_consolidated(consolidated: Optional[Dict[str, Any]], chains: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Each consolidated strike = Σ the per-expiry chain rows at that strike; its totals = Σ the per-expiry totals."""
    if not consolidated:
        return []
    out = []
    expiries = [e for e in consolidated.get("expiries") or []]
    missing = [e for e in expiries if e not in chains]
    if missing:
        return [finding("C6", SKIP, "consolidated", note=f"no per-expiry chain read for {', '.join(missing)}", source="chain")]
    by: Dict[Tuple[str, float], Dict[str, Any]] = {}
    for e in expiries:
        for r in chains[e].get("strikes") or []:
            by[(e, float(r["strike"]))] = r
    partial = [e for e in expiries if (chains[e].get("strikes_returned") or 0) < (chains[e].get("strike_count") or 0)]
    bad, n = [], 0
    for r in consolidated.get("strikes") or []:
        k = float(r["strike"])
        for side in ("call", "put"):
            got = r.get(side) or {}
            for field in ("oi", "change_in_oi"):
                vals = [_int(((by.get((e, k)) or {}).get(side) or {}).get(field)) for e in expiries]
                if any((e, k) not in by for e in expiries) and partial:
                    continue
                want = sum(v for v in vals if v is not None) if any(v is not None for v in vals) else None
                n += 1
                if _int(got.get(field)) != want:
                    bad.append(finding("C6", FAIL, f"consolidated {int(k) if k.is_integer() else k} {side} {field}", want, _int(got.get(field)), None, "chain"))
    out.extend(bad)
    if n and not bad:
        out.append(finding("C6", PASS, f"consolidated: {n} strike figures = sum of the per-expiry chains", source="chain"))
    s = consolidated.get("summary") or {}
    for field in ("total_call_oi", "total_put_oi", "total_call_oi_change", "total_put_oi_change"):
        want = sum(_int((chains[e].get("summary") or {}).get(field)) or 0 for e in expiries)
        out.append(finding("C6", PASS if _int(s.get(field)) == want else FAIL, f"consolidated summary {field}", want, _int(s.get(field)), None, "chain"))
    return out


def check_chart_futures(buildup: Optional[Dict[str, Any]], futures: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The chart's futures pane, last daily bar: the slot's OI = the futures route's OI for that contract; consolidated =
    Σ the futures route's OI."""
    if not buildup or not futures:
        return []
    out = []
    by = {f["expiry"]: _int(f.get("oi")) for f in futures.get("futures") or [] if isinstance(f, dict)}
    as_of = futures.get("as_of")
    for name, s in _series_of(buildup):
        bars = s.get("daily_bars") or []
        if not bars:
            continue
        last = bars[-1]
        if last[0][:10] != as_of:
            out.append(finding("C6", FAIL, f"chart {name} last bar day", as_of, last[0][:10], None, "chart"))
            continue
        want = sum(v for v in by.values() if v is not None) if name == "consolidated" else by.get(last[5])
        out.append(finding("C6", PASS if _int(last[3]) == want else FAIL, f"chart {name} futures OI", want, _int(last[3]), None, "chart"))
    return out


# ── C7 segments sum to the net movement ──────────────────────────────────────

def segments(rows: Sequence[Sequence[Any]]) -> Dict[str, Any]:
    """daily_bars [[day, close, volume, oi, oi_change, expiry], ...] → the OI change bars against the line.
    net = last OI − first OI; increases / decreases = Σ of the bars after the first (the first bar's change is from
    before the series); rolls = each day the series changes contract, with the jump no bar shows: the new contract's OI
    the session before (oi − its change) minus the old contract's last OI."""
    inc = dec = 0
    rolls: List[Dict[str, Any]] = []
    nulls = 0
    for a, b in zip(rows, rows[1:]):
        ch = _int(b[4])
        if ch is None:
            nulls += 1
        elif ch >= 0:
            inc += ch
        else:
            dec += ch
        if b[5] != a[5]:
            oa, ob = _int(a[3]), _int(b[3])
            if oa is not None and ob is not None:
                rolls.append({"day": b[0][:10], "from": a[5], "to": b[5], "jump": ob - (ch or 0) - oa})
    net = (_int(rows[-1][3]) or 0) - (_int(rows[0][3]) or 0) if rows else 0
    gap = net - (inc + dec)
    jumps = sum(r["jump"] for r in rolls)
    return {"increases": inc, "decreases": dec, "net": net, "gap": gap, "rolls": rolls, "roll_jumps": jumps,
            "unexplained": gap - jumps, "null_changes": nulls}


def check_daily_segments(buildup: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for name, s in _series_of(buildup):
        rows = [r for r in s.get("daily_bars") or [] if _int(r[3]) is not None]
        if len(rows) < 2:
            continue
        g = segments(rows)
        item = f"chart daily {name}: {rows[0][0][:10]} .. {rows[-1][0][:10]}"
        detail = (f"increases {g['increases']:+,}, decreases {g['decreases']:+,} = {g['increases'] + g['decreases']:+,}; "
                  f"the line moved {g['net']:+,}")
        if g["gap"] == 0:
            out.append(finding("C7", PASS, item, g["net"], g["increases"] + g["decreases"], detail, "chart"))
            continue
        why = []
        if g["rolls"]:
            named = ", ".join(f"{r['day']} {r['from']}->{r['to']} {r['jump']:+,}" for r in g["rolls"][:4])
            why.append(f"{len(g['rolls'])} contract roll(s) worth {g['roll_jumps']:+,} are never a bar ({named})")
        if g["unexplained"]:
            why.append(f"{g['unexplained']:+,} unexplained ({g['null_changes']} bars with no change)")
        out.append(finding("C7", FAIL, item, g["net"], g["increases"] + g["decreases"], detail + "; " + "; ".join(why), "chart"))
    return out


def check_window_segments(buildup: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Intraday windows: Σ window oi_change = the last window's OI − the OI before the first window."""
    if not buildup or buildup.get("mode") != "intraday":
        return []
    out = []
    for name, s in _series_of(buildup):
        ws = [w for w in s.get("windows") or [] if _int(w.get("oi")) is not None and _int(w.get("oi_change")) is not None]
        if not ws:
            continue
        total = sum(_int(w["oi_change"]) for w in ws)
        net = _int(ws[-1]["oi"]) - (_int(ws[0]["oi"]) - _int(ws[0]["oi_change"]))
        inc = sum(_int(w["oi_change"]) for w in ws if _int(w["oi_change"]) > 0)
        out.append(finding("C7", PASS if total == net else FAIL, f"intraday windows {name}", net, total,
                           f"increases {inc:+,}, decreases {total - inc:+,}", "kite"))
    return out


def check_options_segments(options: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The options pane: Σ *_oi_change over a run of non-null rows = the run's last sum − the sum before it."""
    if not options or options.get("availability") != "ok":
        return []
    rows = options.get("series") or []
    out = []
    for side in ("ce", "pe"):
        vals = [(_int(r.get(f"{side}_oi")), _int(r.get(f"{side}_oi_change"))) for r in rows]
        live = [(v, c) for v, c in vals if v is not None and c is not None]
        if not live:
            continue
        if any(v is None for v, _ in vals[vals.index(live[0]):]):
            out.append(finding("C7", SKIP, f"options pane {side.upper()}", note="the sums have gaps: no single run to add up", source="kite"))
            continue
        total, net = sum(c for _, c in live), live[-1][0] - (live[0][0] - live[0][1])
        out.append(finding("C7", PASS if total == net else FAIL, f"options pane {side.upper()}", net, total, None, "kite"))
    return out


# ── run and report ───────────────────────────────────────────────────────────

def run(symbol: str, day: str, prev_day: Optional[str], today_rows: Iterable[Any], prev_rows: Optional[Iterable[Any]],
        chains: Dict[str, Dict[str, Any]], consolidated: Optional[Dict[str, Any]], futures: Optional[Dict[str, Any]],
        buildup: Optional[Dict[str, Any]], options: Optional[Dict[str, Any]], skips: Sequence[Dict[str, Any]] = (),
        small_base_lots: int = SMALL_BASE_LOTS) -> Dict[str, Any]:
    """Every check over one underlying's sources → {"symbol", "day", "prev_day", "findings", "checks", "status"}.
    `skips` are findings the reader already made for sources that could not answer."""
    today = bhav_book(today_rows)
    prev = bhav_book(prev_rows) if prev_rows is not None else None
    chain_i, fut_i = chain_items(chains), futures_items(futures)
    lot = next((_int(c.get("lot_size")) for c in chains.values() if c and c.get("lot_size")), None)
    f: List[Dict[str, Any]] = list(skips)
    if prev is None:
        why = (f"the previous session's bhavcopy ({prev_day}) could not be read" if prev_day
               else "no previous session in the chart's daily bars")
        for c in ("C1", "C3", "C4"):
            f.append(finding(c, SKIP, "previous session", note=why))
    else:
        f += check_previous_oi(chain_i, prev, "chain") + check_previous_oi(fut_i, prev, "futures")
        f += check_change(chain_i, today, prev, "chain") + check_change(fut_i, today, prev, "futures")
        f += check_source_change(today, prev) + check_chart_change(buildup, today, prev, day)
        f += check_change_pct(chain_i, today, prev, lot, "chain", small_base_lots)
        f += check_chart_change_pct(buildup, today, prev, day, small_base_lots)
    f += check_close_oi(chain_i, today, "chain") + check_close_oi(fut_i, today, "futures") + check_chart_close(buildup, today, day)
    last, none, reason = kite_last_on_day(buildup, options, day)
    f += check_kite_close(last, none, reason, today, day)
    f += check_intraday_windows(buildup) + check_options_series(options)
    f += check_chain_totals(chains, today) + check_consolidated(consolidated, chains) + check_chart_futures(buildup, futures)
    f += check_daily_segments(buildup) + check_window_segments(buildup) + check_options_segments(options)
    checks = summarise(f)
    return {"symbol": symbol, "day": day, "prev_day": prev_day, "status": overall(checks), "checks": checks, "findings": f}


def summarise(findings: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Per check: its status (FAIL over WARN over PASS; SKIP only when nothing was compared), counts, and up to
    EXAMPLES non-passing findings, FAIL first."""
    out: Dict[str, Dict[str, Any]] = {}
    for cid, title in CHECKS.items():
        mine = [x for x in findings if x["check"] == cid]
        counts = {s: sum(1 for x in mine if x["status"] == s) for s in (PASS, FAIL, WARN, SKIP)}
        status = max((x["status"] for x in mine), key=lambda s: _RANK[s], default=SKIP)
        examples = sorted((x for x in mine if x["status"] != PASS), key=lambda x: -_RANK[x["status"]])[:EXAMPLES]
        out[cid] = {"title": title, "status": status, "counts": counts, "examples": examples}
    return out


def overall(checks: Dict[str, Dict[str, Any]]) -> str:
    return max((c["status"] for c in checks.values()), key=lambda s: _RANK[s], default=SKIP)


def exit_code(reports: Sequence[Dict[str, Any]]) -> int:
    """0 nothing failed (warnings and skips allowed), 3 a check failed."""
    return 3 if any(r.get("status") == FAIL for r in reports) else 0


def _fmt(v: Any) -> str:
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return "-" if v is None else str(v)


def render(report: Dict[str, Any]) -> str:
    """The report as plain text: one block per check, with its counts and examples."""
    lines = [f"{report['symbol']}  {report['prev_day']} -> {report['day']}  overall {report['status']}"]
    for cid, c in report["checks"].items():
        n = c["counts"]
        lines.append(f"  {cid} {c['status']:<4} {c['title']}  (pass {n[PASS]}, fail {n[FAIL]}, warn {n[WARN]}, skip {n[SKIP]})")
        for x in c["examples"]:
            ea = f" expected {_fmt(x.get('expected'))} got {_fmt(x.get('actual'))}" if "expected" in x else ""
            lines.append(f"      {x['status']} [{x.get('source', '-')}] {x['item']}{ea}" + (f"  - {x['note']}" if x.get("note") else ""))
    return "\n".join(lines)
