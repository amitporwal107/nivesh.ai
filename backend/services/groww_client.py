"""Groww MF data fetcher — JSON-first parser using embedded __NEXT_DATA__.

Strategy:
  1. Fetch /mutual-funds/{slug}
  2. Extract Next.js server-rendered JSON at <script id="__NEXT_DATA__">
  3. Pull structured holdings, return_stats (alpha/beta/sharpe/sortino/stddev),
     metadata (scheme_code, direct_scheme_code, isin, aum, nav, expense_ratio,
     category, risk, rating, launch_date).
  4. Fallback to HTML regex parse only if JSON is absent.
"""
from __future__ import annotations
import re
import json
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from html import unescape
import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "nivesh.ai portfolio tracker (contact: support@nivesh.ai)"
BASE_URL = "https://groww.in/mutual-funds"
TIMEOUT_S = 15.0

_search_locks: Dict[str, asyncio.Lock] = {}
_search_cache: Dict[str, Optional[str]] = {}


# ── Slug helpers ─────────────────────────────────────────────────────────
def scheme_name_to_slug(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"\bplan\b", " ", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


# ── HTTP ────────────────────────────────────────────────────────────────
async def fetch_page(slug: str) -> Optional[str]:
    url = f"{BASE_URL}/{slug}"
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=True) as c:
            r = await c.get(url, headers=headers)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.text
    except Exception as e:  # noqa: BLE001
        logger.warning("groww fetch failed for %s: %s", slug, e)
        return None


async def search_slug(scheme_name: str) -> Optional[str]:
    """Resolve scheme_name → Groww slug via public st_query API (coalesced + cached)."""
    key = (scheme_name or "").strip().lower()
    if not key:
        return None
    if key in _search_cache:
        return _search_cache[key]
    lock = _search_locks.setdefault(key, asyncio.Lock())
    async with lock:
        if key in _search_cache:
            return _search_cache[key]
        url = "https://groww.in/v1/api/search/v3/query/global/st_query"
        params = {"q": scheme_name, "from": "0", "size": "5"}
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        slug: Optional[str] = None
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_S) as c:
                r = await c.get(url, params=params, headers=headers)
                r.raise_for_status()
                data = r.json()
            for h in (data.get("data") or {}).get("content") or []:
                if h.get("sub_entity_type") == "Scheme" and h.get("search_id"):
                    slug = h["search_id"]
                    break
        except Exception as e:  # noqa: BLE001
            logger.warning("groww search failed for %s: %s", scheme_name, e)
        _search_cache[key] = slug
        return slug


# ── Parsers ─────────────────────────────────────────────────────────────
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', re.DOTALL
)


def _extract_next_data(html: str) -> Optional[Dict[str, Any]]:
    m = _NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
        return (
            data.get("props", {})
                .get("pageProps", {})
                .get("mfServerSideData")
        )
    except (ValueError, AttributeError):
        return None


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_launch_date(s: Optional[str]) -> Optional[str]:
    """'31-Dec-2012' → '2012-12-31' (ISO). Returns None on parse failure."""
    if not s:
        return None
    try:
        return datetime.strptime(s, "%d-%b-%Y").date().isoformat()
    except ValueError:
        return None


def _parse_iso_date(s: Optional[str]) -> Optional[str]:
    """'2013-01-01' or '2022-07-28T18:30:00.788Z' → '2013-01-01'. None on failure."""
    if not s:
        return None
    s = str(s).split("T")[0]
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except ValueError:
        return None


def _years_between(iso_from: Optional[str], iso_to: Optional[str] = None) -> Optional[float]:
    """Years between two ISO dates (or iso_from → today) to 1 decimal place."""
    if not iso_from:
        return None
    try:
        start = datetime.strptime(iso_from, "%Y-%m-%d").date()
        end = (
            datetime.strptime(iso_to, "%Y-%m-%d").date() if iso_to
            else datetime.now(timezone.utc).date()
        )
        days = (end - start).days
        if days < 0:
            return 0.0
        return round(days / 365.25, 1)
    except ValueError:
        return None


def _extract_v3_primitives(nd: Dict[str, Any], holdings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """V3 Phase 0b: pull every primitive Groww already exposes.

    Feeds Quality / Health / Portfolio-Fit composite scores directly — no LLM,
    no compute. Deterministic parse from __NEXT_DATA__.
    """
    # Fund age from allotment_date (preferred) or launch_date
    allotment_iso = _parse_iso_date(nd.get("allotment_date")) or _parse_launch_date(
        nd.get("launch_date")
    )
    fund_age_years = _years_between(allotment_iso) if allotment_iso else None

    # Fund managers — shape: list of {person_name, date_from, education, experience, funds_managed[]}
    managers: List[Dict[str, Any]] = []
    for m in nd.get("fund_manager_details") or []:
        since_iso = _parse_iso_date(m.get("date_from"))
        managers.append({
            "name": m.get("person_name"),
            "since": since_iso,
            "tenure_years": _years_between(since_iso),
            "education": m.get("education"),
            "experience": m.get("experience"),
            "funds_managed_count": len(m.get("funds_managed") or []),
        })
    # Primary manager = longest current tenure
    primary = max(
        (m for m in managers if m["tenure_years"] is not None),
        key=lambda m: m["tenure_years"],
        default=None,
    )

    # Historic expense — latest vs ~3y ago. Groww sorts newest → oldest.
    hfe = nd.get("historic_fund_expense") or []
    latest_exp: Optional[Dict[str, Any]] = hfe[0] if hfe else None
    # Find the entry closest to 3 years ago
    exp_3y_ago: Optional[Dict[str, Any]] = None
    if latest_exp and _parse_iso_date(latest_exp.get("as_on_date")):
        try:
            latest_date = datetime.strptime(
                _parse_iso_date(latest_exp["as_on_date"]), "%Y-%m-%d"
            ).date()
            target_days = 3 * 365
            best = None
            best_delta = None
            for e in hfe:
                eiso = _parse_iso_date(e.get("as_on_date"))
                if not eiso:
                    continue
                d = (latest_date - datetime.strptime(eiso, "%Y-%m-%d").date()).days
                # target 3y ago (±90 days tolerance, else closest)
                delta = abs(d - target_days)
                if best_delta is None or delta < best_delta:
                    best, best_delta = e, delta
            exp_3y_ago = best
        except ValueError:
            exp_3y_ago = None

    expense_trend_delta: Optional[float] = None
    if latest_exp and exp_3y_ago:
        a, b = _num(latest_exp.get("expense_ratio")), _num(exp_3y_ago.get("expense_ratio"))
        if a is not None and b is not None:
            expense_trend_delta = round(a - b, 2)

    # Turnover — first non-null in historic_fund_expense (top-level `portfolio_turnover`
    # is stale; the rows array is the authoritative history).
    turnover_latest: Optional[float] = None
    turnover_as_of: Optional[str] = None
    for e in hfe:
        t = _num(e.get("turn_over_ratio"))
        if t is not None:
            turnover_latest = t
            turnover_as_of = _parse_iso_date(e.get("as_on_date"))
            break
    if turnover_latest is None:
        turnover_latest = _num(nd.get("portfolio_turnover"))

    # Category peer stats & rank
    cat_avg = {"1y": None, "3y": None, "5y": None}
    cat_rank = {"1y": None, "3y": None, "5y": None}
    for s in nd.get("stats") or []:
        if s.get("type") == "CATEGORY_AVG_RETURN":
            cat_avg = {"1y": _num(s.get("stat_1y")), "3y": _num(s.get("stat_3y")), "5y": _num(s.get("stat_5y"))}
        elif s.get("type") == "RANK_WITHIN_CATEGORY":
            cat_rank = {
                "1y": int(s["stat_1y"]) if s.get("stat_1y") is not None else None,
                "3y": int(s["stat_3y"]) if s.get("stat_3y") is not None else None,
                "5y": int(s["stat_5y"]) if s.get("stat_5y") is not None else None,
            }

    # Top-10 concentration
    top10_concentration = round(
        sum(h.get("pct", 0.0) or 0.0 for h in holdings[:10]), 2
    ) if holdings else None

    # Sibling plan slug (opposite plan type)
    plan_type = (nd.get("plan_type") or "").strip().lower()
    sibling_slug: Optional[str] = None
    if plan_type == "direct":
        sibling_slug = nd.get("regular_search_id")
    elif plan_type == "regular":
        sibling_slug = nd.get("direct_search_id")

    # Analysis (PROS / CONS bullets)
    analysis = [
        {
            "type": a.get("analysis_type"),
            "subject": a.get("analysis_subject"),
            "desc": a.get("analysis_desc"),
            "rating": _num(a.get("rating")),
        }
        for a in (nd.get("analysis") or [])
    ]

    # Truncate historic expense to last 36 monthly entries for persistence
    historic_expense_trunc = [
        {
            "expense_ratio": _num(e.get("expense_ratio")),
            "turnover_ratio": _num(e.get("turn_over_ratio")),
            "as_on_date": _parse_iso_date(e.get("as_on_date")),
            "frequency": e.get("frequency"),
        }
        for e in hfe[:36]
    ]

    return {
        "allotment_date": allotment_iso,
        "fund_age_years": fund_age_years,
        "fund_managers": managers,
        "primary_manager": primary,
        "expense_ratio_latest": _num(latest_exp.get("expense_ratio")) if latest_exp else None,
        "expense_ratio_3y_ago": _num(exp_3y_ago.get("expense_ratio")) if exp_3y_ago else None,
        "expense_trend_delta": expense_trend_delta,
        "historic_expense": historic_expense_trunc,
        "turnover_ratio": turnover_latest,
        "turnover_as_of": turnover_as_of,
        "category_avg_returns": cat_avg,
        "rank_within_category": cat_rank,
        "top10_concentration_pct": top10_concentration,
        "sibling_slug": sibling_slug,
        "plan_type": nd.get("plan_type"),
        "analysis": analysis,
    }


def parse_next_data(nd: Dict[str, Any]) -> Dict[str, Any]:
    """Structured parse from __NEXT_DATA__.mfServerSideData."""
    # Holdings
    holdings: List[Dict[str, Any]] = []
    seen: set = set()
    for rank, h in enumerate(nd.get("holdings") or [], start=1):
        name = h.get("company_name") or ""
        if not name or name in seen:
            continue
        seen.add(name)
        holdings.append({
            "name": name,
            "stock_slug": h.get("stock_search_id"),
            "sector": h.get("sector_name") or "",
            "instrument_type": h.get("instrument_name") or "",
            "pct": _num(h.get("corpus_per")) or 0,
            "market_value_cr": _num(h.get("market_value")),
            "rank": rank,
        })

    # Sector aggregate
    sector_map: Dict[str, float] = {}
    for h in holdings:
        sec = h["sector"] or "Unclassified"
        sector_map[sec] = sector_map.get(sec, 0.0) + h["pct"]
    sectors = sorted(
        [{"name": k, "pct": round(v, 2)} for k, v in sector_map.items()],
        key=lambda x: x["pct"], reverse=True,
    )

    # Equity/Debt/Cash split
    split_map: Dict[str, float] = {}
    for h in holdings:
        t = (h["instrument_type"] or "Other").strip()
        split_map[t] = split_map.get(t, 0.0) + h["pct"]
    equity = split_map.get("Equity", 0.0)
    debt = sum(v for k, v in split_map.items()
               if k in ("Debt", "Corporate Bonds", "Government Securities", "Treasury Bills"))
    cash = split_map.get("Cash", 0.0) + split_map.get("Cash Equivalents", 0.0)
    split = {"equity": round(equity, 2), "debt": round(debt, 2), "cash": round(cash, 2)}

    # Ratios
    rs = (nd.get("return_stats") or [{}])[0] if nd.get("return_stats") else {}
    ratios = {
        "alpha": _num(rs.get("alpha")),
        "beta": _num(rs.get("beta")),
        "sharpe": _num(rs.get("sharpe_ratio")),
        "sortino": _num(rs.get("sortino_ratio")),
        "std_dev": _num(rs.get("standard_deviation")),
        "information_ratio": _num(rs.get("information_ratio")),
        "mean_return": _num(rs.get("mean_return")),
        "ret_1y": _num(rs.get("return1y")),
        "ret_3y": _num(rs.get("return3y")),
        "ret_5y": _num(rs.get("return5y")),
        "ret_10y": _num(rs.get("return10y")),
        "risk_rating": _num(rs.get("risk_rating")),
        "risk_label": rs.get("risk"),
    }

    # Metadata
    metadata = {
        "scheme_code": nd.get("scheme_code"),
        "direct_scheme_code": nd.get("direct_scheme_code"),
        "isin": nd.get("isin"),
        "scheme_name": nd.get("scheme_name"),
        "fund_house": nd.get("fund_house"),
        "amc": nd.get("amc"),
        "category": nd.get("category"),
        "sub_category": nd.get("sub_category"),
        "super_category": nd.get("super_category"),
        "benchmark": nd.get("benchmark_name") or nd.get("benchmark"),
        "plan_type": nd.get("plan_type"),
        "scheme_type": nd.get("scheme_type"),
        "risk_label": rs.get("risk"),
        "groww_rating": _num(nd.get("groww_rating")),
        "crisil_rating": _num(nd.get("crisil_rating")),
        "aum_cr": _num(nd.get("aum")),
        "nav": _num(nd.get("nav")),
        "nav_date": (nd.get("nav_date") or "").split("T")[0] or None,
        "expense_ratio": _num(nd.get("expense_ratio")),
        "launch_date": _parse_launch_date(nd.get("launch_date")),
        "min_sip": _num(nd.get("min_sip_investment")),
        "portfolio_turnover": _num(nd.get("portfolio_turnover")),
    }

    return {
        "holdings": holdings,
        "sectors": sectors,
        "split": split,
        "ratios": ratios,
        "metadata": metadata,
        "v3_primitives": _extract_v3_primitives(nd, holdings),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "groww",
    }


# Fallback HTML regex parser (legacy — kept for resilience if NEXT_DATA breaks) ─
_ROW_RE = re.compile(r'<tr[^>]*class="[^"]*holdings_row__[^"]*"[^>]*>(.*?)</tr>', re.DOTALL)
_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
_STOCK_LINK_RE = re.compile(r'href="(/stocks/[^"]+)"[^>]*>(?:<span[^>]*>)?([^<]+)', re.IGNORECASE)
_TAG_STRIP = re.compile(r"<[^>]+>")


def _clean(s: str) -> str:
    return unescape(_TAG_STRIP.sub("", s)).strip()


def parse_html_fallback(html: str) -> Optional[Dict[str, Any]]:
    holdings: List[Dict[str, Any]] = []
    seen: set = set()
    for row_html in _ROW_RE.findall(html):
        cells = _CELL_RE.findall(row_html)
        if len(cells) < 4:
            continue
        c_name, c_sector, c_type, c_pct = cells[:4]
        m = _STOCK_LINK_RE.search(c_name)
        if m:
            slug = m.group(1).strip("/")
            name = unescape(m.group(2)).strip()
        else:
            slug = None
            name = _clean(c_name)
        if not name or name in seen or name.lower() in ("name", "total"):
            continue
        seen.add(name)
        try:
            pct = float(_clean(c_pct).replace("%", ""))
        except ValueError:
            continue
        holdings.append({
            "name": name, "stock_slug": slug, "sector": _clean(c_sector),
            "instrument_type": _clean(c_type), "pct": pct,
            "rank": len(holdings) + 1,
        })
    if not holdings:
        return None
    return {
        "holdings": holdings, "sectors": [], "split": {},
        "ratios": {}, "metadata": {},
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "groww-html",
    }


def parse_page(html: str) -> Optional[Dict[str, Any]]:
    """Try JSON first, then HTML regex fallback."""
    if not html:
        return None
    nd = _extract_next_data(html)
    if nd:
        try:
            return parse_next_data(nd)
        except Exception as e:  # noqa: BLE001
            logger.warning("parse_next_data failed: %s; falling back to HTML", e)
    return parse_html_fallback(html)


def validate(parsed: Dict[str, Any]) -> Dict[str, Any]:
    reasons: List[str] = []
    h = parsed.get("holdings", [])
    if not h:
        reasons.append("no holdings parsed")
    tot = sum(x["pct"] for x in h)
    if not (70 <= tot <= 115):
        reasons.append(f"holdings sum {tot:.1f}% out of expected 70-115 range")
    if len(h) < 5:
        reasons.append(f"only {len(h)} holdings")
    meta = parsed.get("metadata") or {}
    aum, nav = meta.get("aum_cr"), meta.get("nav")
    if aum is not None and aum <= 0:
        reasons.append(f"AUM non-positive: {aum}")
    if nav is not None and nav <= 0:
        reasons.append(f"NAV non-positive: {nav}")
    parsed["valid"] = not reasons
    parsed["validation_issues"] = reasons
    return parsed


async def fetch_fund(scheme_name: str, explicit_slug: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Deterministic slug → HTML fetch → search_slug fallback → parse → validate."""
    slug = explicit_slug or scheme_name_to_slug(scheme_name)
    html = await fetch_page(slug)
    if not html and not explicit_slug:
        resolved = await search_slug(scheme_name)
        if resolved and resolved != slug:
            slug = resolved
            html = await fetch_page(slug)
    if not html:
        return None
    parsed = parse_page(html)
    if not parsed:
        return None
    parsed["slug"] = slug
    parsed["scheme_name"] = parsed.get("metadata", {}).get("scheme_name") or scheme_name
    return validate(parsed)


async def fetch_fund_with_sibling(
    scheme_name: str, explicit_slug: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """V3 Phase 0b: fetch the primary plan, then its sibling (regular ⇄ direct)
    to populate BOTH expense ratios natively (no compute).

    Returns the primary scrape with two extra fields stitched in:
      parsed["metadata"]["expense_ratio_direct"]
      parsed["metadata"]["expense_ratio_regular"]

    The sibling scrape itself is attached at parsed["sibling"] for callers
    that want to persist both rows.
    """
    primary = await fetch_fund(scheme_name, explicit_slug)
    if not primary:
        return None

    v3 = primary.get("v3_primitives") or {}
    sibling_slug = v3.get("sibling_slug")
    plan_type = (v3.get("plan_type") or "").strip().lower()
    primary_expense = _num((primary.get("metadata") or {}).get("expense_ratio"))

    meta = primary.setdefault("metadata", {})
    # Seed with whichever plan we fetched
    if plan_type == "direct":
        meta["expense_ratio_direct"] = primary_expense
    elif plan_type == "regular":
        meta["expense_ratio_regular"] = primary_expense

    if sibling_slug:
        sibling = await fetch_fund(primary.get("scheme_name") or scheme_name, explicit_slug=sibling_slug)
        if sibling:
            primary["sibling"] = sibling
            sib_meta = sibling.get("metadata") or {}
            sib_expense = _num(sib_meta.get("expense_ratio"))
            sib_plan = (sib_meta.get("plan_type") or "").strip().lower()
            if sib_plan == "direct":
                meta["expense_ratio_direct"] = sib_expense
            elif sib_plan == "regular":
                meta["expense_ratio_regular"] = sib_expense

    return primary
