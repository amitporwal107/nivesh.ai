"""MF detail-card builders for the copilot chat (overview / returns / holdings / peers).

Each builder is the MF analogue of `instrument_research.build_stock_widget`: it takes
already-fetched DaaS payloads and returns ONE pure `mf_detail` widget dict that the
V5 chat renders (ChatWidget.tsx → MfDetailWidget). The async `get_mf_card` orchestrator
fetches only what a given view needs, concurrently.

CONTEXT.md rules honoured here:
  * Every value is read from DaaS; a field DaaS does not return is OMITTED, never faked.
  * Builders are pure (dict in → dict out) so they unit-test without the network.
  * The Holdings view is gated on real rows by the caller — the AMC-holdings feed is
    currently unreliable, and we render no empty holdings card.
  * Short-horizon returns (1M/3M/6M) are deliberately not surfaced — the feed values
    are implausible (see get_mf_card / build_mf_returns).
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import daas_client as _daas
from .instrument_research import (
    _SOURCE,
    _compact,
    _money,
    _num,
    _pct,
    _pick,
    _quality_label_tone,
    _row,
    build_mf_widget,
)

logger = logging.getLogger(__name__)

_DISCLAIMER_NOTE = "Not investment advice."
_VIEWS = ("overview", "returns", "holdings", "peers")


@dataclass
class MfCardResult:
    ok: bool
    view: str
    widget: Dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    error: Optional[str] = None


# ── shared helpers ───────────────────────────────────────────────────────────

_PLAN_TOKENS = re.compile(
    r"\b(direct|regular|growth|idcw|dividend|payout|reinvest\w*|bonus|plan|option|"
    r"daily|weekly|monthly|quarterly|annual|fortnightly|half[\s-]?yearly)\b",
    re.IGNORECASE,
)


def _clean_name(scheme_name: str) -> str:
    """'HDFC Balanced Advantage Fund - Growth Plan' -> 'HDFC Balanced Advantage Fund'.
    Cuts at the first plan/option token (separator-independent), falling back to the
    pre-dash segment, then the raw name."""
    s = (scheme_name or "")
    m = _PLAN_TOKENS.search(s)
    if m:
        cut = s[: m.start()].strip(" -–")
        if cut:
            return cut
    return s.split(" - ")[0].strip() or s


def _fund_key(scheme_name: str) -> str:
    """Plan/option-agnostic identity key for grouping variants of the same fund.
    Strips every plan/option token regardless of separator so 'X Regular Plan' and
    'X Direct Plan' (no dash) collapse together."""
    k = _PLAN_TOKENS.sub(" ", (scheme_name or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", k).strip()


def _plan_of(scheme_name: str) -> Optional[str]:
    n = (scheme_name or "").lower()
    if "direct" in n:
        return "Direct"
    if "regular" in n or "growth" in n:
        return "Growth"
    return None


def _fmt_date(d: Optional[str]) -> Optional[str]:
    """'2026-06-18' -> '18 Jun 2026'."""
    if not d:
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(d)[:10]).strftime("%-d %b %Y")
    except (ValueError, TypeError):
        return str(d)[:10]


def _nav_block(scheme: Dict[str, Any], nav_series: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """NAV + derived daily change from the two most recent NAV rows."""
    nav = _num((scheme or {}).get("latest_nav"))
    if nav is None and nav_series:
        nav = _num(nav_series[0].get("nav"))
    if nav is None:
        return None
    block: Dict[str, Any] = {
        "value": _money(nav),
        "asof": _fmt_date((scheme or {}).get("latest_nav_date") or (nav_series[0].get("nav_date") if nav_series else None)),
    }
    if len(nav_series) >= 2:
        cur, prev = _num(nav_series[0].get("nav")), _num(nav_series[1].get("nav"))
        if cur is not None and prev:
            chg = (cur - prev) / prev * 100.0
            block["change"] = _pct(chg, signed=True, decimals=2)
            block["change_positive"] = chg >= 0
    return block


def _subtitle(sc: Dict[str, Any], scheme: Dict[str, Any]) -> Optional[str]:
    cat = (sc or {}).get("category") or (scheme or {}).get("scheme_category")
    sub = (sc or {}).get("sub_category")
    parts = [p for p in (cat, sub) if p and p not in ("", None)]
    # de-dupe when category already contains the sub-category text
    out: List[str] = []
    for p in parts:
        if not any(p in o or o in p for o in out):
            out.append(p)
    return " · ".join(out) or None


def _tabs(name: str, active: str) -> List[Dict[str, Any]]:
    spec = [
        ("overview", "Overview", f"Show the overview of {name}."),
        ("returns",  "Returns",  f"Show the returns of {name} across periods."),
        ("holdings", "Holdings", f"Show the holdings of {name}."),
        ("peers",    "Peers",    f"Compare {name} with its peers."),
    ]
    return [{"key": k, "label": lbl, "prompt": p, "active": k == active} for k, lbl, p in spec]


def _envelope(view: str, sc: Dict[str, Any], scheme: Dict[str, Any],
              nav_series: List[Dict[str, Any]]) -> Dict[str, Any]:
    name = _clean_name((scheme or {}).get("scheme_name") or (sc or {}).get("scheme_name") or "")
    code = str((sc or {}).get("scheme_code") or (scheme or {}).get("scheme_code") or "")
    w: Dict[str, Any] = {
        "view": view,
        "kind": "mf",
        "scheme_code": code,
        "name": name,
        "badge": "MUTUAL FUND",
        "subtitle": _subtitle(sc, scheme),
        "tabs": _tabs(name, view),
        "source": _SOURCE,
        "disclaimer_note": _DISCLAIMER_NOTE,
    }
    plan = _plan_of((scheme or {}).get("scheme_name") or "")
    if plan:
        w["plan"] = plan
    risk = (scheme or {}).get("risk_o_meter")
    if risk:
        w["risk"] = risk
    nb = _nav_block(scheme, nav_series)
    if nb:
        w["nav"] = nb
    return w


def quartile_insights(sc: Dict[str, Any]) -> tuple[str, List[str], List[str]]:
    """Deterministic prose + reasons-to-consider / watch-outs from quartile ranks.

    Quartile fields (1 = best quartile in category, 4 = worst). Nothing is invented:
    each bullet maps directly to a quartile the scorecard reports.
    """
    sc = sc or {}

    def q(*keys: str) -> Optional[int]:
        for k in keys:
            v = sc.get(k)
            if v is not None:
                try:
                    return int(v)
                except (TypeError, ValueError):
                    return None
        return None

    consider: List[str] = []
    watch: List[str] = []
    if (v := q("qtile_ret3y")) is not None and v <= 1:
        consider.append("Top-quartile 3-year returns in its category")
    if (v := q("qtile_ret5y")) is not None and v <= 1:
        consider.append("Top-quartile 5-year returns")
    if (v := q("qtile_maxdd")) is not None and v <= 1:
        consider.append("Among the best at limiting drawdowns")
    if (v := q("qtile_ter")) is not None and v <= 1:
        consider.append("Low expense ratio versus peers")
    if (v := q("qtile_consistency")) is not None and v <= 1:
        consider.append("Highly consistent return profile")

    if (v := q("qtile_ret1y")) is not None and v >= 3:
        watch.append("Below-median 1-year returns lately")
    if (v := q("qtile_sharpe")) is not None and v >= 3:
        watch.append("Weak risk-adjusted returns (Sharpe) recently")
    if (v := q("qtile_alpha")) is not None and v >= 3:
        watch.append("Trailing the benchmark on alpha")
    if (v := q("qtile_ter")) is not None and v >= 3:
        watch.append("Expense ratio is high versus peers")

    # Headline prose from the 3Y/5Y vs 1Y picture.
    q3, q5, q1 = q("qtile_ret3y"), q("qtile_ret5y"), q("qtile_ret1y")
    summary = ""
    long_strong = (q3 is not None and q3 <= 2) or (q5 is not None and q5 <= 2)
    short_weak = q1 is not None and q1 >= 3
    if long_strong and short_weak:
        summary = "A long-term outperformer going through a short-term rough patch."
    elif long_strong:
        summary = "A consistent long-term performer in its category."
    elif short_weak:
        summary = "Recent returns lag the category; the longer record is mixed."
    return summary, consider, watch


# ── OVERVIEW ─────────────────────────────────────────────────────────────────

def build_mf_overview(sc: Dict[str, Any], scheme: Dict[str, Any],
                      nav_series: List[Dict[str, Any]], prim: Dict[str, Any]) -> Dict[str, Any]:
    w = _envelope("overview", sc, scheme, nav_series)
    sc, scheme, prim = sc or {}, scheme or {}, prim or {}

    # Quality score (derive label+tone from the score so they never disagree).
    q_score = _pick(sc, "composite_score", "quality_score")
    if q_score is not None:
        label, tone = _quality_label_tone(q_score)
        w["quality"] = {"score": int(round(q_score)), "label": label, "tone": tone}
        rank = _pick(sc, "composite_rank", "category_rank")
        size = _pick(sc, "total_in_category", "category_size")
        if rank is not None and size:
            w["quality"]["rank"] = int(rank)
            w["quality"]["of"] = int(size)

    summary, consider, watch = quartile_insights(sc)
    if summary:
        w["summary"] = summary
    if consider:
        w["consider"] = consider
    if watch:
        w["watch"] = watch

    # Key facts — every line omitted if its source value is null.
    aum = _pick(sc, "aum_cr") or _pick(prim, "aum_cr")
    ter = _pick(sc, "ter") or _pick(prim, "expense_ratio_regular", "expense_ratio")
    ter_direct = _pick(prim, "expense_ratio_direct")
    expense_val = None
    if ter is not None and ter_direct is not None:
        expense_val = f"{ter:.2f}% · direct {ter_direct:.2f}%"
    elif ter is not None:
        expense_val = f"{ter:.2f}%"
    facts = _compact([
        _row("Category", _subtitle(sc, scheme)),
        _row("Benchmark", scheme.get("benchmark_name")),
        _row("Launched", _fmt_date(scheme.get("launch_date") or sc.get("scheme_launch_date"))),
        _row("Risk", scheme.get("risk_o_meter")),
        _row("AUM", f"₹{aum:,.0f} Cr" if aum is not None else None),
        _row("Expense ratio", expense_val),
    ])
    if facts:
        w["facts"] = facts

    # Returns snapshot (CAGR) — sane horizons only.
    snap = _compact([
        _row("1Y", _pct(_pick(sc, "return_1y"))),
        _row("3Y", _pct(_pick(sc, "return_3y"))),
        _row("5Y", _pct(_pick(sc, "return_5y"))),
        _row("Since launch", _pct(_pick(sc, "return_since_launch_cagr"))),
    ])
    if snap:
        w["returns_snapshot"] = snap

    mgr = scheme.get("primary_manager") or prim.get("primary_manager")
    if mgr:
        secondary = scheme.get("secondary_manager")
        w["managers"] = f"{mgr}" + (f" · {secondary}" if secondary else "")

    w["actions"] = [
        {"label": "See holdings", "prompt": f"Show the holdings of {w['name']}."},
        {"label": "Compare peers", "prompt": f"Compare {w['name']} with its peers."},
    ]
    return w


# ── RETURNS ──────────────────────────────────────────────────────────────────

def build_mf_returns(sc: Dict[str, Any], scheme: Dict[str, Any],
                     nav_series: List[Dict[str, Any]], prim: Dict[str, Any]) -> Dict[str, Any]:
    w = _envelope("returns", sc, scheme, nav_series)
    sc, prim = sc or {}, prim or {}

    summary, _c, _wt = quartile_insights(sc)
    if summary:
        w["summary"] = summary

    # CAGR fund vs category average. Benchmark series is not in the feed → omitted.
    cat = {
        "1Y": _pick(prim, "category_avg_1y"),
        "3Y": _pick(prim, "category_avg_3y"),
        "5Y": _pick(prim, "category_avg_5y"),
    }
    cagr: List[Dict[str, Any]] = []
    for label, key in (("3 years", "return_3y"), ("5 years", "return_5y"), ("1 year", "return_1y")):
        fund = _pick(sc, key)
        if fund is None:
            continue
        row: Dict[str, Any] = {"label": label, "fund": round(fund, 2)}
        cval = cat.get({"3 years": "3Y", "5 years": "5Y", "1 year": "1Y"}[label])
        if cval is not None:
            row["category"] = round(cval, 2)
        cagr.append(row)
    if cagr:
        w["cagr"] = cagr

    has_cat = any("category" in r for r in cagr)
    w["note"] = (
        "Fund CAGR vs category average. Benchmark series isn't available."
        if has_cat else
        "Annualised (CAGR) fund returns. 1M/3M/6M omitted pending a data fix."
    )
    w["actions"] = [{"label": "Compare peers", "prompt": f"Compare {w['name']} with its peers."}]
    return w


# ── HOLDINGS ─────────────────────────────────────────────────────────────────

def _aggregate(rows: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    totals: Dict[str, float] = {}
    for h in rows:
        k = h.get(key) or "Other"
        totals[k] = totals.get(k, 0.0) + (_num(h.get("weight_pct")) or 0.0)
    return sorted(
        ({"label": k, "pct": round(v, 2)} for k, v in totals.items()),
        key=lambda x: x["pct"], reverse=True,
    )


def build_mf_holdings(sc: Dict[str, Any], scheme: Dict[str, Any],
                      nav_series: List[Dict[str, Any]],
                      holdings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Built only when `holdings` is non-empty (caller gates this)."""
    w = _envelope("holdings", sc, scheme, nav_series)
    holdings = holdings or []

    as_of = None
    for h in holdings:
        if h.get("as_of_month"):
            as_of = _fmt_date(h.get("as_of_month"))
            break
    if as_of:
        w["asof"] = as_of

    # Asset allocation by instrument_type.
    alloc = _aggregate(holdings, "instrument_type")
    # Normalise the common labels for display.
    label_map = {"EQUITY": "Equity", "DEBT": "Debt", "CASH": "Cash", "DERIVATIVE": "Derivatives", "REIT": "REITs"}
    for a in alloc:
        a["label"] = label_map.get(str(a["label"]).upper(), str(a["label"]).title())
    if alloc:
        w["asset_allocation"] = alloc

    equity = [h for h in holdings if str(h.get("instrument_type") or "").upper() == "EQUITY"]
    top = _compact([
        {
            "name": h.get("security_name"),
            "sector": h.get("sector"),
            "weight": round(_num(h.get("weight_pct")) or 0.0, 2),
        } if h.get("security_name") else None
        for h in equity[:10]
    ])
    if top:
        w["top_holdings"] = top

    sectors = [s for s in _aggregate(equity, "sector") if s["label"] not in (None, "Other") or s["pct"] > 0]
    if sectors:
        w["sectors"] = sectors[:8]

    debt = [h for h in holdings if str(h.get("instrument_type") or "").upper() == "DEBT"]
    dq = [d for d in _aggregate(debt, "rating") if d["pct"] > 0]
    if dq:
        w["debt_quality"] = dq[:6]

    # Stats.
    equity_wt = sum(_num(h.get("weight_pct")) or 0.0 for h in equity)
    top10 = sum(round(_num(h.get("weight_pct")) or 0.0, 4) for h in equity[:10])
    stats = _compact([
        _row("Stocks held", str(len({h.get("security_isin") or h.get("security_name") for h in equity})) if equity else None),
        _row("Top-10 weight", _pct(top10, decimals=1) if equity else None),
        _row("Equity exposure", _pct(equity_wt, decimals=1) if equity else None),
    ])
    if stats:
        w["stats"] = stats

    w["actions"] = [{"label": "Compare peers", "prompt": f"Compare {w['name']} with its peers."}]
    return w


# ── PEERS ────────────────────────────────────────────────────────────────────

def _peer_pref(p: Dict[str, Any]) -> tuple:
    """Sort key for choosing a fund's representative plan — lower is better.
    Prefer Growth over IDCW (IDCW returns are payout-reduced), then Regular over
    Direct (matches the card), then larger AUM, then higher score."""
    nm = (p.get("scheme_name") or "").lower()
    is_idcw = any(w in nm for w in ("idcw", "dividend", "payout", "reinvest"))
    is_direct = "direct" in nm
    return (
        0 if not is_idcw else 1,
        0 if not is_direct else 1,
        -(_num(p.get("aum_cr")) or -1.0),
        -(_num(p.get("composite_score")) or -1.0),
    )


def build_mf_peers(sc: Dict[str, Any], scheme: Dict[str, Any],
                   nav_series: List[Dict[str, Any]], peers: List[Dict[str, Any]]) -> Dict[str, Any]:
    w = _envelope("peers", sc, scheme, nav_series)
    peers = peers or []
    current = str((sc or {}).get("scheme_code") or "")

    # Collapse plan variants (Reg/Direct/IDCW) to one row per fund family. CRITICAL:
    # prefer the Growth plan — IDCW/dividend NAVs are payout-reduced, so their
    # trailing returns are wrong (often negative). Within Growth, prefer the
    # Regular plan to match the card's looked-up scheme. Always keep the subject fund.
    by_family: Dict[str, Dict[str, Any]] = {}
    for p in peers:
        fam = _fund_key(p.get("scheme_name") or "")
        if not fam:
            continue
        prev = by_family.get(fam)
        if prev is None:
            by_family[fam] = p
            continue
        if str(prev.get("scheme_code")) == current:
            continue  # never displace the subject fund's own row
        if str(p.get("scheme_code")) == current or _peer_pref(p) < _peer_pref(prev):
            by_family[fam] = p

    fams = list(by_family.values())
    # Ensure the current fund is present even if it wasn't in the leaderboard page.
    if current and not any(str(p.get("scheme_code")) == current for p in fams):
        fams.append({
            "scheme_code": current,
            "scheme_name": (scheme or {}).get("scheme_name") or (sc or {}).get("scheme_name"),
            "aum_cr": _pick(sc or {}, "aum_cr"),
            "return_1y": _pick(sc or {}, "return_1y"),
            "return_3y": _pick(sc or {}, "return_3y"),
            "ter": _pick(sc or {}, "ter"),
            "composite_score": _pick(sc or {}, "composite_score"),
        })

    # Pin the subject fund first, then the rest by Nivesh score (AUM is largely
    # unavailable from the disclosure feed, so it's not a reliable sort key) —
    # so the comparison always includes the fund the user asked about.
    cur_fam = next((p for p in fams if str(p.get("scheme_code")) == current), None)
    others = [p for p in fams if p is not cur_fam]
    others.sort(key=lambda p: (_num(p.get("composite_score")) or -1, _num(p.get("aum_cr")) or -1), reverse=True)
    ordered = ([cur_fam] if cur_fam else []) + others
    rows = []
    for p in ordered[:6]:
        rows.append(_compact_row({
            "name": _clean_name(p.get("scheme_name") or ""),
            "aum": _num(p.get("aum_cr")),
            "ret1y": _num(p.get("return_1y")),
            "ret3y": _num(p.get("return_3y")),
            "ter": _num(p.get("ter")),
            "is_current": str(p.get("scheme_code")) == current,
        }))
    if rows:
        w["rows"] = rows
        w["highlight_code"] = current

    sub = (sc or {}).get("sub_category")
    w["caption"] = (f"Top funds in the {sub} category by Nivesh score" if sub else "Category peers") + \
                   ", Growth plan. 3Y blank where the fund is under three years old."
    w["actions"] = [{"label": "Back to overview", "prompt": f"Show the overview of {w['name']}."}]
    return w


def _compact_row(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


# ── orchestrator ─────────────────────────────────────────────────────────────

async def get_mf_card(scheme_code: str, view: str) -> MfCardResult:
    """Fetch + assemble the MF detail card for `view`. Holdings is gated on real rows."""
    code = str(scheme_code or "").strip()
    view = view if view in _VIEWS else "overview"
    if not code:
        return MfCardResult(ok=False, view=view, error="no_scheme_code")

    try:
        sc, scheme, nav_series = await asyncio.gather(
            _daas.get_mf_scorecard(code),
            _daas.get_mf_scheme(code),
            _daas.get_mf_nav_series(code, limit=2),
        )
    except Exception as exc:  # noqa: BLE001
        return MfCardResult(ok=False, view=view, error=str(exc))
    sc = sc or {}
    scheme = scheme or {}
    nav_series = nav_series or []
    if not sc and not scheme:
        return MfCardResult(ok=False, view=view, error="not_found")

    isin = scheme.get("isin_growth") or sc.get("isin")

    if view == "returns":
        prim_map = await _daas.get_v3_mf_primitives_bulk([isin]) if isin else {}
        prim = (prim_map.get(isin) if isinstance(prim_map, dict) else None) or {}
        widget = build_mf_returns(sc, scheme, nav_series, prim)
        ok = bool(widget.get("cagr"))
        summary = f"{widget.get('name')}: returns 1Y={_pct(_pick(sc,'return_1y'))} 3Y={_pct(_pick(sc,'return_3y'))} 5Y={_pct(_pick(sc,'return_5y'))}"

    elif view == "holdings":
        holdings = await _daas.get_mf_holdings(code, limit=400)
        if not holdings:
            return MfCardResult(ok=False, view=view, error="holdings_unavailable")
        widget = build_mf_holdings(sc, scheme, nav_series, holdings)
        ok = bool(widget.get("top_holdings") or widget.get("asset_allocation"))
        summary = f"{widget.get('name')}: {len(holdings)} holdings loaded"

    elif view == "peers":
        sub = sc.get("sub_category") or ""
        peers = await _daas.get_mf_category_scorecard(sub, sort_by="aum", limit=20) if sub else []
        widget = build_mf_peers(sc, scheme, nav_series, peers)
        ok = bool(widget.get("rows"))
        summary = f"{widget.get('name')}: {len(widget.get('rows', []))} peers in {sub}"

    else:  # overview
        prim_map = await _daas.get_v3_mf_primitives_bulk([isin]) if isin else {}
        prim = (prim_map.get(isin) if isinstance(prim_map, dict) else None) or {}
        widget = build_mf_overview(sc, scheme, nav_series, prim)
        ok = bool(widget.get("quality") or widget.get("returns_snapshot") or widget.get("facts"))
        summary = f"{widget.get('name')}: overview (quality={_pick(sc,'composite_score')})"

    return MfCardResult(ok=ok, view=view, widget=widget, summary=summary,
                        error=None if ok else "insufficient_data")


# ── combined single-card (all tabs in one widget) ───────────────────────────

# Envelope keys are shared by the card header — they're stripped from each view
# payload so the view dict carries only its own body fields.
_ENV_KEYS = {
    "view", "kind", "scheme_code", "name", "badge", "subtitle", "tabs",
    "source", "disclaimer_note", "plan", "risk", "nav", "actions",
}


def _view_only(w: Dict[str, Any], view: str) -> Dict[str, Any]:
    d = {k: v for k, v in (w or {}).items() if k not in _ENV_KEYS}
    d["view"] = view
    return d


def build_mf_summary_view(scheme_code: str, sc: Dict[str, Any],
                          scheme: Dict[str, Any], nav_series: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The Summary tab body: quality donut + prose, Returns and Risk & cost columns."""
    sc = sc or {}
    w = build_mf_widget(str(scheme_code), sc)
    view: Dict[str, Any] = {"view": "summary"}

    if w.get("quality"):
        q = dict(w["quality"])
        rank = _pick(sc, "composite_rank", "category_rank")
        size = _pick(sc, "total_in_category", "category_size")
        if rank is not None and size:
            q["rank"], q["of"] = int(rank), int(size)
        view["quality"] = q

    prose, _consider, _watch = quartile_insights(sc)
    if prose:
        view["summary"] = prose

    if w.get("returns"):
        view["returns"] = w["returns"]
    q3 = sc.get("qtile_ret3y")
    if q3 is not None:
        try:
            q3 = int(q3)
            view["returns_badge"] = (
                {"text": "Top quartile", "tone": "pos"} if q3 <= 1 else
                {"text": "Above category", "tone": "pos"} if q3 == 2 else
                {"text": "Below category", "tone": "neg"}
            )
        except (TypeError, ValueError):
            pass

    if w.get("ratios"):
        ratios = dict(w["ratios"])
        ratios["title"] = "Risk & cost"
        beta = _pick(sc, "beta_3y", "beta_1y", "beta")
        if beta is not None and beta < 0.85:
            ratios["badge"] = {"text": "Low beta", "tone": "pos"}
        view["ratios"] = ratios

    if w.get("disclaimer"):
        view["disclaimer"] = w["disclaimer"]
    return view


_TAB_SPEC = [
    ("summary", "Summary"), ("overview", "Overview"), ("returns", "Returns"),
    ("holdings", "Holdings"), ("peers", "Peers"),
]


async def get_mf_full_card(scheme_code: str, active: str = "summary") -> MfCardResult:
    """Assemble ONE mf_detail widget holding every tab's data (client switches
    tabs locally — no re-fetch). Holdings/peers tabs appear only when they have
    real data; `active` is the initially-selected tab (falls back to summary)."""
    code = str(scheme_code or "").strip()
    if not code:
        return MfCardResult(ok=False, view="summary", error="no_scheme_code")

    try:
        sc, scheme, nav_series = await asyncio.gather(
            _daas.get_mf_scorecard(code),
            _daas.get_mf_scheme(code),
            _daas.get_mf_nav_series(code, limit=2),
        )
    except Exception as exc:  # noqa: BLE001
        return MfCardResult(ok=False, view="summary", error=str(exc))
    sc, scheme, nav_series = sc or {}, scheme or {}, nav_series or []
    if not sc and not scheme:
        return MfCardResult(ok=False, view="summary", error="not_found")

    isin = scheme.get("isin_growth") or sc.get("isin")
    sub = sc.get("sub_category") or ""
    prim_map, holdings, peers = await asyncio.gather(
        _daas.get_v3_mf_primitives_bulk([isin]) if isin else _noop_dict(),
        _daas.get_mf_holdings(code, limit=400),
        _daas.get_mf_category_scorecard(sub, sort_by="aum", limit=20) if sub else _noop_list(),
    )
    prim = (prim_map.get(isin) if isinstance(prim_map, dict) else None) or {}

    views: Dict[str, Any] = {"summary": build_mf_summary_view(code, sc, scheme, nav_series)}
    views["overview"] = _view_only(build_mf_overview(sc, scheme, nav_series, prim), "overview")
    rt = build_mf_returns(sc, scheme, nav_series, prim)
    if rt.get("cagr"):
        views["returns"] = _view_only(rt, "returns")
    if holdings:
        hd = build_mf_holdings(sc, scheme, nav_series, holdings)
        if hd.get("top_holdings") or hd.get("asset_allocation"):
            views["holdings"] = _view_only(hd, "holdings")
    pr = build_mf_peers(sc, scheme, nav_series, peers)
    if pr.get("rows"):
        views["peers"] = _view_only(pr, "peers")

    env = _envelope("summary", sc, scheme, nav_series)
    widget: Dict[str, Any] = {"kind": "mf"}
    for k in ("scheme_code", "name", "badge", "subtitle", "plan", "risk", "nav", "source", "disclaimer_note"):
        if k in env:
            widget[k] = env[k]
    widget["active"] = active if active in views else "summary"
    widget["tabs"] = [{"key": k, "label": lbl} for k, lbl in _TAB_SPEC if k in views]
    widget["views"] = views

    ok = bool(views.get("summary"))
    summary = f"{widget.get('name')}: MF card ({', '.join(views)})"
    return MfCardResult(ok=ok, view=widget["active"], widget=widget, summary=summary,
                        error=None if ok else "insufficient_data")


async def _noop_dict() -> Dict[str, Any]:
    return {}


async def _noop_list() -> List[Any]:
    return []
