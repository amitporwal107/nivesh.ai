"""Tickertape MF scraper — extracts V3 primitives from the public HTML page.

Tickertape's Next.js pages embed a structured JSON blob under
`<script id="__NEXT_DATA__">` — no public API, no auth, just HTML fetch.

The output shape matches `groww_client.fetch_fund()` so that the existing
`pg_writer.persist_scrape()` pipeline can ingest it without changes.

Usage:
    result = await tickertape_client.fetch_fund_by_url(
        "https://www.tickertape.in/mutualfunds/hdfc-large-cap-fund-M_HDCTP"
    )
"""
from __future__ import annotations
import json
import logging
import re
import urllib.parse
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
TIMEOUT_S = 25.0
_BASE = "https://www.tickertape.in"
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>',
    re.DOTALL,
)


# ── HTTP ─────────────────────────────────────────────────────────────────
async def _fetch_html(url: str) -> Optional[str]:
    async with httpx.AsyncClient(
        timeout=TIMEOUT_S,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
    ) as c:
        try:
            r = await c.get(url)
            if r.status_code == 200 and "<html" in r.text[:500].lower():
                return r.text
            logger.warning("tickertape fetch %s → HTTP %s", url, r.status_code)
            return None
        except Exception as e:  # noqa: BLE001
            logger.warning("tickertape fetch %s failed: %s", url, e)
            return None


def _parse_next_data(html: str) -> Optional[Dict[str, Any]]:
    m = _NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


# ── Conversion helpers ───────────────────────────────────────────────────
def _label_map(items: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Tickertape uses [{backL, value, info}] arrays — flatten to dict."""
    out: Dict[str, Any] = {}
    for row in items or []:
        k = row.get("backL")
        if k is not None:
            out[k] = row.get("value")
    return out


def _years_between(iso_from: Optional[str]) -> Optional[float]:
    if not iso_from:
        return None
    try:
        dt = datetime.fromisoformat(iso_from.replace("Z", "+00:00"))
    except ValueError:
        return None
    now = datetime.now(timezone.utc)
    return round((now - dt).days / 365.25, 2)


# ── Transformer: Tickertape JSON → persist_scrape-compatible dict ────────
def _build_scrape(data: Dict[str, Any], fallback_url: str) -> Optional[Dict[str, Any]]:
    try:
        p = data["props"]["pageProps"]
    except (KeyError, TypeError):
        return None

    si = p.get("securityInfo") or {}
    ss = p.get("securitySummary") or {}
    meta_tt = ss.get("meta") or {}
    key_ratios = _label_map(ss.get("keyRatios"))
    scheme_info = _label_map(ss.get("schemeInfo"))
    faq = p.get("mfPageFaq") or {}
    faq_ratios = faq.get("ratios") or {}
    fund_managers = p.get("fundManagers") or []

    launch_iso = faq.get("launchDate")
    launch_date = None
    if launch_iso:
        try:
            launch_date = datetime.fromisoformat(
                launch_iso.replace("Z", "+00:00")
            ).date().isoformat()
        except ValueError:
            launch_date = None

    plan_type = (meta_tt.get("plan") or si.get("option") or "").strip().lower()
    if "direct" in plan_type:
        plan_type = "direct"
    elif "regular" in plan_type:
        plan_type = "regular"
    else:
        plan_type = "direct"  # Tickertape defaults to Direct

    expense_ratio = key_ratios.get("expRatio") or faq_ratios.get("expRatio")
    aum_cr = faq_ratios.get("aum")
    if aum_cr is None:
        # Some pages bury AUM in schemeInfo or meta
        aum_cr = scheme_info.get("aum") or meta_tt.get("aum")

    # Fund manager primary
    pm = fund_managers[0] if fund_managers else {}
    manager_name = pm.get("name")
    try:
        manager_tenure = float(pm.get("exp")) if pm.get("exp") else None
    except (TypeError, ValueError):
        manager_tenure = None

    # Top-10 concentration from currentAllocation (filter equity only)
    allocations = (p.get("holdingsGraph") or {}).get("currentAllocation") or []
    equity_rows = [a for a in allocations if (a.get("type") or "").lower() == "equity"]
    top10_conc = None
    if equity_rows:
        top_sorted = sorted(equity_rows, key=lambda x: -(x.get("latest") or 0))[:10]
        top10_conc = round(sum(float(r.get("latest") or 0) for r in top_sorted), 2)

    holdings: List[Dict[str, Any]] = []
    for a in allocations:
        if not a.get("title"):
            continue
        holdings.append({
            "name": a["title"],
            "stock_slug": (a.get("slug") or "").lstrip("/") or None,
            "weight_pct": round(float(a.get("latest") or 0), 4),
            "sector": None,
        })

    # Ratios (PE, Sharpe, Sortino, Std-dev)
    ratios_date = date.today().isoformat()
    ratios = {
        "ratios_date": ratios_date,
        "pe_ratio": key_ratios.get("pe") or faq_ratios.get("pe"),
        "pb_ratio": None,
        "alpha": faq_ratios.get("alpha"),
        "beta": faq_ratios.get("beta"),
        "sharpe": key_ratios.get("sharpe") or faq_ratios.get("sharpe"),
        "sortino": faq_ratios.get("sortino"),
        "ytm": faq_ratios.get("ytm"),
        "std_dev": faq_ratios.get("stdDev"),
        "track_err": faq_ratios.get("trackErr"),
    }

    # Category + sub-category
    category = si.get("subsector") or meta_tt.get("subsector")
    sub_category = si.get("sector") or meta_tt.get("sector")

    # Category averages from keyRatios
    category_avg = {
        "cat_exp_ratio": key_ratios.get("catExpRatio"),
        "cat_pe": key_ratios.get("catPe"),
        "cat_sharpe": key_ratios.get("catSharpe"),
    }

    scheme_name = meta_tt.get("fullName") or si.get("name") or ""
    mf_id = si.get("mfId") or ""
    # Tickertape slug used as our groww_slug equivalent for dedup
    tt_slug = (si.get("slug") or "").lstrip("/") or None
    # Strip `/mutualfunds/` prefix
    if tt_slug and tt_slug.startswith("mutualfunds/"):
        tt_slug = tt_slug[len("mutualfunds/"):]
    # Prefix with tt_ so we never collide with Groww slugs
    canonical_slug = f"tt_{tt_slug}" if tt_slug else f"tt_{mf_id.lower()}"

    v3_primitives = {
        "aum_cr": aum_cr,
        "fund_age_years": _years_between(launch_iso),
        "expense_ratio_direct": expense_ratio if plan_type == "direct" else None,
        "expense_ratio_regular": expense_ratio if plan_type == "regular" else None,
        "manager_tenure_years": manager_tenure,
        "primary_manager": {
            "name": manager_name,
            "qualification": pm.get("qualification"),
            "tenure_years": manager_tenure,
            "total_aum_cr": pm.get("aumInCr"),
        } if manager_name else None,
        "category_avg_returns": category_avg,
        "rank_within_category": {},
        "top10_concentration_pct": top10_conc,
        "turnover_ratio": None,  # Tickertape doesn't expose this publicly
        "sibling_slug": None,
        "plan_type": plan_type,
        "source": "tickertape",
    }

    payload = {
        "scheme_name": scheme_name,
        "slug": canonical_slug,
        "source": "tickertape",
        "valid": True,
        "metadata": {
            "scheme_name": scheme_name,
            "scheme_code": mf_id,
            "isin": meta_tt.get("isin"),
            "aum_cr": aum_cr,
            "nav": si.get("navClose") or faq_ratios.get("navClose"),
            "nav_date": date.today().isoformat(),
            "expense_ratio": expense_ratio,
            "rating": None,
            "risk_label": meta_tt.get("riskClassification"),
            "category": category,
            "sub_category": sub_category,
            "launch_date": launch_date,
            "allotment_date": launch_date,
            "fund_age_years": _years_between(launch_iso),
            "plan_type": plan_type,
            "manager_name": manager_name,
            "manager_since": None,
            "manager_tenure_years": manager_tenure,
            "manager_education": pm.get("qualification"),
            "manager_funds_count": len(pm.get("funds") or []) or None,
            "fund_managers": fund_managers,
            "expense_ratio_direct": expense_ratio if plan_type == "direct" else None,
            "expense_ratio_regular": expense_ratio if plan_type == "regular" else None,
            "expense_ratio_3y_ago": None,
            "expense_trend_delta": None,
            "historic_expense_json": None,
            "turnover_ratio": None,
            "turnover_as_of": None,
            "category_avg_1y": None,
            "category_avg_3y": None,
            "category_avg_5y": None,
            "rank_within_category_1y": None,
            "rank_within_category_3y": None,
            "rank_within_category_5y": None,
            "top10_concentration_pct": top10_conc,
            "sibling_slug": None,
            "analysis_json": {"tickertape_keyRatios": key_ratios,
                              "tickertape_faqRatios": faq_ratios},
        },
        "holdings": holdings,
        "ratios": ratios,
        "v3_primitives": v3_primitives,
        "sectors": [],
    }
    return payload


# ── Public API ───────────────────────────────────────────────────────────
async def fetch_fund_by_url(url: str) -> Optional[Dict[str, Any]]:
    """Scrape a Tickertape mutualfunds URL → persist_scrape-compatible dict."""
    html = await _fetch_html(url)
    if not html:
        return None
    data = _parse_next_data(html)
    if not data:
        logger.warning("tickertape: no __NEXT_DATA__ in %s", url)
        return None
    payload = _build_scrape(data, url)
    if not payload or not payload.get("scheme_name"):
        return None
    return payload


async def fetch_fund_by_mfid(mf_id: str, slug_hint: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fetch by Tickertape mfId (e.g., 'M_HDCTP'). Uses slug_hint if provided."""
    if slug_hint:
        url = f"{_BASE}/mutualfunds/{slug_hint}"
    else:
        # Tickertape accepts the ID alone, redirects to canonical URL.
        url = f"{_BASE}/mutualfunds/{mf_id}"
    return await fetch_fund_by_url(url)
