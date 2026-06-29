"""Historical "what-if" backtest tool for the Nivesh Copilot.

Answers: *"If I'd invested ₹X across these stocks / funds 1 year and 3 years ago,
what would it be worth today — lump-sum and as a monthly SIP?"*

The point of the feature is comparison: a per-instrument table of how each named
stock / fund actually performed over the lookback, so the user can draw a
reference for future decisions.

Design notes / honesty guarantees
---------------------------------
* **Total return.** Stocks use ``tret_close`` (split + bonus + dividend adjusted);
  MFs use NAV (distributions are already reflected in NAV). Never raw close.
* **Arbitrary entry dates, not pre-computed returns.** ``analytics.fund_category_rank``
  carries calendar-anchored ``return_1y/3y`` — those do NOT match a user's chosen
  entry date, so we compute point-to-point from the raw price / NAV series.
* **Trading-day snapping.** Markets are shut on weekends / holidays, so an entry
  date of "exactly 1 year ago" is snapped to the first available bar ON OR AFTER it.
* **Insufficient history is reported, never faked.** If an instrument's series does
  not reach back to the requested entry (e.g. a fund launched later, or the adjusted
  stock-price feed does not go back 3 years), that instrument is flagged for that
  period and excluded from the aggregate — we do not silently start it late.

Data sources (all via DaaS so this works from the app container):
    stocks → daas_client.get_adjusted_prices_bulk(symbols, start, end)
    funds  → daas_client.get_mf_nav_history(scheme_code, start, end)

Public entry point:
    get_historical_backtest(text, amount=None, periods=None, as_of=None) -> BacktestResult
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from services.portfolio_enrichment import xirr

logger = logging.getLogger(__name__)

DEFAULT_AMOUNT = 10_00_000.0          # ₹10 lakh
DEFAULT_PERIODS = (1, 3)              # years of lookback to report
DEFAULT_BENCHMARK = "Nifty 500"       # index the same ₹amount is benchmarked against
_MAX_INSTRUMENTS = 12
# How far AFTER the requested entry the first available bar may sit before we
# call the history insufficient (covers a long holiday stretch, not a missing year).
_SNAP_TOLERANCE_DAYS = 20


# ── Result dataclass (mirrors SipResult / PortfolioResult) ──────────────────

@dataclass
class BacktestResult:
    ok: bool
    summary: str
    data: Dict[str, Any] = field(default_factory=dict)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    def as_llm_context(self) -> str:
        if not self.ok:
            return f"BACKTEST status=error reason={self.error}"
        return f"BACKTEST | {self.summary}"


@dataclass
class Instrument:
    raw: str
    kind: str                      # "stock" | "mf"
    ident: str                     # NSE symbol (stock) | AMFI scheme_code (mf)
    name: str
    weight: float = 0.0            # filled after normalisation


# ── Formatting ──────────────────────────────────────────────────────────────

def _inr(v: Optional[float]) -> str:
    if v is None:
        return "—"
    if abs(v) >= 1e7:
        return f"₹{v/1e7:.2f}Cr"
    if abs(v) >= 1e5:
        return f"₹{v/1e5:.2f}L"
    return f"₹{v:,.0f}"


# ── Free-text parsing ────────────────────────────────────────────────────────

_AMOUNT_RE = re.compile(
    r"(?:₹|rs\.?|inr|rupees?)?\s*([\d,]+(?:\.\d+)?)\s*(cr(?:ore)?s?|l(?:akh|acs?)?|k|thousand)?",
    re.IGNORECASE,
)
_PERIOD_RE = re.compile(r"(\d+)\s*(?:year|yr|y)s?\b", re.IGNORECASE)

# Tokens that mean "this fragment names a fund, not a stock".
_FUND_CUE = re.compile(
    r"\bfund\b|flexi|\belss\b|index\s+fund|blue\s*chip|balanced\s+advantage|\bbaf\b|"
    r"(?:large|mid|small|multi|flexi)\s*cap|\bppfas\b|parag\s+parikh|mutual|\bnav\b|"
    r"\bgilt\b|liquid\s+fund|debt\s+fund|\bsip\b\s+in",
    re.IGNORECASE,
)

# Lead-in phrasing we strip before splitting the basket into instruments.
_BASKET_LEAD = re.compile(
    r".*?\b(?:invested|invest|put|bought|buy|split\s+(?:across|between)|across|into|in)\b\s+",
    re.IGNORECASE | re.DOTALL,
)
# A money amount (+ optional connector) left at the FRONT after the lead strip,
# e.g. "10L in HDFC Bank" → "HDFC Bank".
_BASKET_AMOUNT_LEAD = re.compile(
    r"^\s*(?:₹|rs\.?|inr|rupees?)?\s*[\d,]+(?:\.\d+)?\s*"
    r"(?:cr(?:ore)?s?|l(?:akh|acs?)?|k|thousand)?\s*"
    r"(?:equally|equal\s+amounts?|each)?\s*"
    r"(?:in|into|across|between|among|on|over|of)?\s+",
    re.IGNORECASE,
)
# Distribution filler with no amount ("invested equally in X, Y" → "X, Y").
_BASKET_FILLER_LEAD = re.compile(
    r"^\s*(?:equally|equal\s+amounts?|each)\s*(?:in|into|across|between|among|of)?\s+",
    re.IGNORECASE,
)
# Trailing connector left on a fragment after the tail strip ("TCS over" → "TCS").
_FRAG_TRAIL_CONNECTOR = re.compile(r"\b(?:over|for|during|across|in|on|of)$", re.IGNORECASE)
# Trailing time / question clause that is not part of an instrument name.
_BASKET_TAIL = re.compile(
    r"\b(?:\d+\s*(?:year|yr|y)s?\b.*|ago\b.*|back\b.*|today\b.*|now\b.*|"
    r"worth\b.*|what'?s.*|how\s+much.*)$",
    re.IGNORECASE | re.DOTALL,
)
_SPLIT_RE = re.compile(r"\s*(?:,|;|&|\band\b|\bplus\b|/)\s*", re.IGNORECASE)
_WEIGHT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def parse_amount(text: str) -> float:
    """Best-effort ₹ amount from free text; falls back to DEFAULT_AMOUNT.

    Understands lakh / crore / k suffixes ("10L", "₹10 lakh", "5,00,000", "2cr").
    """
    for m in _AMOUNT_RE.finditer(text or ""):
        num_s, unit = m.group(1), (m.group(2) or "").lower()
        # Skip bare numbers that are actually a period ("3 years") — those are
        # followed immediately by a year word; the amount regex won't capture the
        # year word, so guard by requiring a unit OR a reasonably large number.
        try:
            num = float(num_s.replace(",", ""))
        except ValueError:
            continue
        if unit.startswith("cr"):
            return num * 1e7
        if unit.startswith("l"):
            return num * 1e5
        if unit in ("k", "thousand"):
            return num * 1e3
        # No unit: only treat as an amount if it's plausibly money (≥ 1000) so
        # "1 year" / "3 stocks" don't get read as ₹1.
        if num >= 1000:
            return num
    return DEFAULT_AMOUNT


def parse_periods(text: str) -> List[int]:
    """Lookback years mentioned in the text (deduped, sorted); else DEFAULT_PERIODS."""
    yrs = sorted({int(m.group(1)) for m in _PERIOD_RE.finditer(text or "")
                  if 0 < int(m.group(1)) <= 30})
    return yrs or list(DEFAULT_PERIODS)


def parse_fragments(text: str) -> List[Tuple[str, Optional[float]]]:
    """Split the instrument-bearing portion of the message into (name, weight%) pairs.

    Weight is the explicit "30%" if present, else None (→ equal weight later).
    """
    s = (text or "").strip()
    lead = _BASKET_LEAD.match(s)
    if lead:
        s = s[lead.end():]
    s = _BASKET_AMOUNT_LEAD.sub("", s, count=1)
    s = _BASKET_FILLER_LEAD.sub("", s, count=1)
    s = _BASKET_TAIL.sub("", s).strip(" .?")
    out: List[Tuple[str, Optional[float]]] = []
    for frag in _SPLIT_RE.split(s):
        frag = frag.strip(" .?")
        if not frag:
            continue
        wm = _WEIGHT_RE.search(frag)
        weight = float(wm.group(1)) if wm else None
        name = _WEIGHT_RE.sub("", frag).strip(" .?:-")
        name = _FRAG_TRAIL_CONNECTOR.sub("", name).strip(" .?:-")
        # Drop residual filler-only fragments.
        if len(name) < 2 or name.lower() in ("the", "my", "some", "stocks", "funds", "mfs"):
            continue
        out.append((name, weight))
        if len(out) >= _MAX_INSTRUMENTS:
            break
    return out


async def resolve_instruments(
    fragments: List[Tuple[str, Optional[float]]],
) -> Tuple[List[Instrument], List[str]]:
    """Resolve each fragment to a stock symbol or an MF scheme_code.

    Returns (resolved, unresolved_names). Weights are normalised to sum to 1
    across the resolved set (explicit %s honoured where given, the remainder
    split equally).
    """
    from services.copilot_tools.symbol_resolver import resolve_symbol
    from services.copilot_tools.scheme_resolver import resolve_scheme

    resolved: List[Instrument] = []
    unresolved: List[str] = []
    raw_weights: List[Optional[float]] = []

    for name, weight in fragments:
        fundish = bool(_FUND_CUE.search(name))
        stock_res = None
        try:
            stock_res = resolve_symbol(name)
        except Exception:  # noqa: BLE001 — resolution must never raise
            stock_res = None
        scheme = None
        if fundish or not (stock_res and stock_res.symbol):
            try:
                scheme = await resolve_scheme(name)
            except Exception:  # noqa: BLE001
                scheme = None

        inst: Optional[Instrument] = None
        if fundish and scheme:
            inst = Instrument(name, "mf", scheme.scheme_code, scheme.scheme_name or name)
        elif stock_res and stock_res.symbol and not fundish:
            inst = Instrument(name, "stock", stock_res.symbol, stock_res.display_name or name)
        elif scheme:
            inst = Instrument(name, "mf", scheme.scheme_code, scheme.scheme_name or name)
        elif stock_res and stock_res.symbol:
            inst = Instrument(name, "stock", stock_res.symbol, stock_res.display_name or name)

        if inst is None:
            unresolved.append(name)
        else:
            resolved.append(inst)
            raw_weights.append(weight)

    # Normalise weights: honour explicit %s, split the rest equally.
    if resolved:
        explicit = sum(w for w in raw_weights if w is not None)
        n_implicit = sum(1 for w in raw_weights if w is None)
        remaining = max(0.0, 100.0 - explicit)
        implicit_each = (remaining / n_implicit) if n_implicit else 0.0
        weights = [(w if w is not None else implicit_each) for w in raw_weights]
        total = sum(weights) or 1.0
        for inst, w in zip(resolved, weights):
            inst.weight = w / total
    return resolved, unresolved


# ── Series helpers (pure) ────────────────────────────────────────────────────

def _to_date(v: Any) -> Optional[date]:
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    try:
        return date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        return None


def _snap(series: List[Tuple[date, float]], target: date) -> Optional[Tuple[date, float]]:
    """First (date, value) on or after `target` in an ascending series."""
    for d, v in series:
        if d >= target:
            return (d, v)
    return None


def _add_months(d: date, k: int) -> date:
    m = d.month - 1 + k
    y = d.year + m // 12
    mo = m % 12 + 1
    # clamp day to month length
    day = min(d.day, [31, 29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mo - 1])
    return date(y, mo, day)


def lump_sum(amount: float, entry_value: float, latest_value: float,
             entry_date: date, latest_date: date) -> Dict[str, Any]:
    """Single-shot investment: units bought at entry, valued today."""
    units = amount / entry_value
    current = units * latest_value
    years = max((latest_date - entry_date).days / 365.25, 1e-9)
    abs_ret = current / amount - 1.0
    cagr = (current / amount) ** (1.0 / years) - 1.0
    return {
        "invested": round(amount),
        "current_value": round(current),
        "abs_return_pct": round(abs_ret * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "entry_date": entry_date.isoformat(),
        "entry_value": round(entry_value, 4),
        "latest_value": round(latest_value, 4),
        "years": round(years, 2),
    }


def sip(amount: float, series: List[Tuple[date, float]],
        entry_date: date, latest_date: date, months: int) -> Optional[Dict[str, Any]]:
    """Monthly SIP of amount/months from entry to today, measured by XIRR.

    Each installment buys units at the first available price ON OR AFTER its
    month anchor; the final flow is the holding's value today. Returns None when
    fewer than two installments land (XIRR is undefined).
    """
    if months < 2 or amount <= 0:
        return None
    contrib = amount / months
    flows: List[Tuple[date, float]] = []
    units = 0.0
    n_installments = 0
    for i in range(months):
        anchor = _add_months(entry_date, i)
        if anchor > latest_date:
            break
        snapped = _snap(series, anchor)
        if snapped is None:
            continue
        _, value = snapped
        if value <= 0:
            continue
        units += contrib / value
        flows.append((anchor, -contrib))
        n_installments += 1
    if n_installments < 2 or units <= 0:
        return None
    latest_value = series[-1][1]
    invested = contrib * n_installments
    current = units * latest_value
    flows.append((latest_date, current))
    r = xirr(flows)
    return {
        "invested": round(invested),
        "current_value": round(current),
        "abs_return_pct": round((current / invested - 1.0) * 100, 2) if invested else None,
        "xirr_pct": round(r * 100, 2) if r is not None else None,
        "monthly": round(contrib),
        "installments": n_installments,
    }, flows


# ── Data fetch ───────────────────────────────────────────────────────────────

async def _fetch_series(
    instruments: List[Instrument], start: date, end: date,
) -> Dict[str, List[Tuple[date, float]]]:
    """Build {ident: ascending (date, value)} for every instrument.

    Stocks come from one bulk adjusted-price call (tret_close, falling back to
    adj_close); funds from one NAV-history call each, fetched concurrently.
    """
    from services.copilot_tools import daas_client

    out: Dict[str, List[Tuple[date, float]]] = {}
    start_s, end_s = start.isoformat(), end.isoformat()

    stock_syms = [i.ident for i in instruments if i.kind == "stock"]
    if stock_syms:
        try:
            bulk = await daas_client.get_adjusted_prices_bulk(stock_syms, start_s, end_s)
        except Exception as exc:  # noqa: BLE001
            logger.warning("backtest: adjusted price bulk failed: %s", exc)
            bulk = {}
        for sym, bars in (bulk or {}).items():
            series: List[Tuple[date, float]] = []
            for b in bars:
                d = _to_date(b.get("as_of_date"))
                val = b.get("tret_close")
                if val is None:
                    val = b.get("adj_close")
                if d is not None and val is not None:
                    try:
                        series.append((d, float(val)))
                    except (TypeError, ValueError):
                        continue
            series.sort(key=lambda t: t[0])
            if series:
                out[sym] = series

    mf_insts = [i for i in instruments if i.kind == "mf"]

    async def _one_mf(inst: Instrument) -> None:
        try:
            rows = await daas_client.get_mf_nav_history(inst.ident, start_s, end_s)
        except Exception as exc:  # noqa: BLE001
            logger.warning("backtest: nav history failed for %s: %s", inst.ident, exc)
            return
        series = []
        for r in rows:
            d = _to_date(r.get("nav_date"))
            val = r.get("nav")
            if d is not None and val is not None:
                try:
                    series.append((d, float(val)))
                except (TypeError, ValueError):
                    continue
        series.sort(key=lambda t: t[0])
        if series:
            out[inst.ident] = series

    if mf_insts:
        await asyncio.gather(*(_one_mf(i) for i in mf_insts))
    return out


# ── Orchestration ────────────────────────────────────────────────────────────

def _today() -> date:
    return datetime.now(timezone.utc).date()


async def _compute_benchmark(
    index_name: str, amount: float, periods: List[int],
    window_start: date, today: date,
) -> Dict[str, Any]:
    """Lump-sum + SIP of the same ₹amount into a benchmark index, per period.

    Returns {"index": name, "<n>": {...}} for each period, or
    {"index": name, "status": "unavailable"} when the index series can't be read
    (so the answer degrades to an instrument-only comparison rather than faking it).
    """
    from services.copilot_tools import daas_client
    try:
        rows = await daas_client.get_index_eod_history(
            index_name, window_start.isoformat(), today.isoformat())
    except Exception as exc:  # noqa: BLE001
        logger.warning("backtest: benchmark series failed for %s: %s", index_name, exc)
        rows = []
    series: List[Tuple[date, float]] = []
    for r in rows:
        d = _to_date(r.get("as_of_date"))
        val = r.get("close_price")
        if d is not None and val is not None:
            try:
                series.append((d, float(val)))
            except (TypeError, ValueError):
                continue
    series.sort(key=lambda t: t[0])
    if not series:
        return {"index": index_name, "status": "unavailable"}

    out: Dict[str, Any] = {"index": index_name}
    latest_date, latest_value = series[-1]
    first_date = series[0][0]
    for n in periods:
        target = _add_months(today, -(n * 12))
        entry = _snap(series, target)
        if entry is None or (entry[0] - target).days > _SNAP_TOLERANCE_DAYS:
            out[str(n)] = {"status": "insufficient_history",
                           "data_since": first_date.isoformat()}
            continue
        entry_date, entry_value = entry
        ls = lump_sum(amount, entry_value, latest_value, entry_date, latest_date)
        sip_res = sip(amount, series, entry_date, latest_date, n * 12)
        out[str(n)] = {
            "status": "ok",
            "lump_sum": {"cagr_pct": ls["cagr_pct"],
                         "current_value": ls["current_value"],
                         "abs_return_pct": ls["abs_return_pct"]},
            "sip": {"xirr_pct": (sip_res[0]["xirr_pct"] if sip_res else None)},
        }
    return out


async def get_historical_backtest(
    text: str,
    amount: Optional[float] = None,
    periods: Optional[List[int]] = None,
    as_of: Optional[date] = None,
    benchmark: Optional[str] = DEFAULT_BENCHMARK,
) -> BacktestResult:
    """Run the what-if backtest described in `text`.

    Args:
        text:      the user's message — basket, amount and lookback are parsed from it.
        amount:    override the ₹ amount (else parsed, else ₹10L).
        periods:   override the lookback years (else parsed, else 1y + 3y).
        as_of:     "today" for the valuation (defaults to current UTC date; tests pin it).
        benchmark: index name to benchmark the same ₹amount against (None to skip).
    """
    today = as_of or _today()
    amount = amount if amount is not None else parse_amount(text)
    periods = periods or parse_periods(text)

    fragments = parse_fragments(text)
    if not fragments:
        return BacktestResult(
            ok=False,
            summary="No instruments named — ask which stocks/funds to backtest.",
            error="no_instruments",
        )

    instruments, unresolved = await resolve_instruments(fragments)
    if not instruments:
        return BacktestResult(
            ok=False,
            summary=f"Could not resolve any instrument from: {', '.join(unresolved) or text[:60]}",
            error="unresolved",
            data={"unresolved": unresolved},
        )

    max_years = max(periods)
    # Buffer a fortnight before the earliest entry so snapping has room.
    window_start = _add_months(today, -(max_years * 12)).replace(day=1)
    series_by_ident = await _fetch_series(instruments, window_start, today)

    per_instrument: List[Dict[str, Any]] = []
    # Aggregates per period: invested / current for lump-sum + combined SIP flows.
    agg: Dict[int, Dict[str, Any]] = {
        n: {"ls_invested": 0.0, "ls_current": 0.0, "sip_flows": [], "covered": 0}
        for n in periods
    }

    for inst in instruments:
        series = series_by_ident.get(inst.ident)
        row: Dict[str, Any] = {
            "name": inst.name, "identifier": inst.ident, "kind": inst.kind,
            "weight_pct": round(inst.weight * 100, 1), "periods": {},
        }
        alloc = amount * inst.weight
        if not series:
            row["error"] = "no_data"
            per_instrument.append(row)
            continue
        first_date, _ = series[0]
        latest_date, latest_value = series[-1]
        for n in periods:
            target = _add_months(today, -(n * 12))
            entry = _snap(series, target)
            # Insufficient history: data does not reach back near the entry date.
            if entry is None or (entry[0] - target).days > _SNAP_TOLERANCE_DAYS:
                row["periods"][n] = {"status": "insufficient_history",
                                      "data_since": first_date.isoformat()}
                continue
            entry_date, entry_value = entry
            ls = lump_sum(alloc, entry_value, latest_value, entry_date, latest_date)
            sip_res = sip(alloc, series, entry_date, latest_date, n * 12)
            sip_data = None
            if sip_res is not None:
                sip_data, sip_flows = sip_res
                agg[n]["sip_flows"].extend(sip_flows)
            row["periods"][n] = {"status": "ok", "lump_sum": ls, "sip": sip_data}
            agg[n]["ls_invested"] += ls["invested"]
            agg[n]["ls_current"] += ls["current_value"]
            agg[n]["covered"] += 1
        per_instrument.append(row)

    # Portfolio-level rollup per period.
    portfolio: Dict[str, Any] = {}
    for n in periods:
        a = agg[n]
        if a["covered"] == 0 or a["ls_invested"] <= 0:
            portfolio[str(n)] = {"status": "insufficient_history"}
            continue
        years = float(n)
        ls_cagr = (a["ls_current"] / a["ls_invested"]) ** (1.0 / years) - 1.0
        sip_xirr = xirr(a["sip_flows"]) if len(a["sip_flows"]) >= 2 else None
        portfolio[str(n)] = {
            "status": "ok",
            "instruments_covered": a["covered"],
            "instruments_total": len(instruments),
            "lump_sum": {
                "invested": round(a["ls_invested"]),
                "current_value": round(a["ls_current"]),
                "abs_return_pct": round((a["ls_current"] / a["ls_invested"] - 1) * 100, 2),
                "cagr_pct": round(ls_cagr * 100, 2),
            },
            "sip": {"xirr_pct": round(sip_xirr * 100, 2) if sip_xirr is not None else None},
        }

    # Flatten per-instrument into widget-ready rows (one row per instrument×period).
    rows: List[Dict[str, Any]] = []
    for r in per_instrument:
        for n in periods:
            p = r["periods"].get(n)
            if not p:
                continue
            base = {"name": r["name"], "identifier": r["identifier"], "kind": r["kind"],
                    "weight_pct": r["weight_pct"], "period_years": n, "status": p["status"]}
            if p["status"] == "ok":
                ls = p["lump_sum"]
                base.update({
                    "invested": ls["invested"], "current_value": ls["current_value"],
                    "abs_return_pct": ls["abs_return_pct"], "cagr_pct": ls["cagr_pct"],
                    "entry_date": ls["entry_date"],
                    "sip_xirr_pct": (p["sip"] or {}).get("xirr_pct") if p.get("sip") else None,
                })
            else:
                base["data_since"] = p.get("data_since")
            rows.append(base)

    benchmark_data: Optional[Dict[str, Any]] = None
    if benchmark:
        benchmark_data = await _compute_benchmark(benchmark, amount, periods, window_start, today)

    summary = _build_summary(amount, periods, portfolio, instruments, unresolved, benchmark_data)
    data = {
        "amount": round(amount),
        "periods": periods,
        "as_of": today.isoformat(),
        "weighting": "equal" if all(f[1] is None for f in fragments) else "explicit",
        "instruments": [{"name": i.name, "identifier": i.ident,
                         "kind": i.kind, "weight_pct": round(i.weight * 100, 1)}
                        for i in instruments],
        "unresolved": unresolved,
        "portfolio": portfolio,
        "per_instrument": per_instrument,
        "benchmark": benchmark_data,
    }
    return BacktestResult(ok=True, summary=summary, data=data, rows=rows)


def _build_summary(amount: float, periods: List[int], portfolio: Dict[str, Any],
                   instruments: List[Instrument], unresolved: List[str],
                   benchmark: Optional[Dict[str, Any]] = None) -> str:
    parts = [f"₹{_inr(amount).lstrip('₹')} across {len(instruments)} instrument(s)"]
    for n in periods:
        p = portfolio.get(str(n))
        if not p or p.get("status") != "ok":
            parts.append(f"{n}y: insufficient history")
            continue
        ls = p["lump_sum"]
        sip_x = p["sip"].get("xirr_pct")
        seg = (f"{n}y lump-sum → {_inr(ls['current_value'])} "
               f"(CAGR {ls['cagr_pct']}%)")
        if sip_x is not None:
            seg += f"; SIP XIRR {sip_x}%"
        # Benchmark CAGR for the same period, when available.
        if benchmark:
            bp = benchmark.get(str(n))
            if bp and bp.get("status") == "ok":
                seg += f"; vs {benchmark['index']} {bp['lump_sum']['cagr_pct']}%"
        parts.append(seg)
    if benchmark and benchmark.get("status") == "unavailable":
        parts.append(f"{benchmark['index']} benchmark unavailable")
    if unresolved:
        parts.append(f"unresolved: {', '.join(unresolved)}")
    return " | ".join(parts)
