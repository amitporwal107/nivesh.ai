"""Moneycontrol MF scraper — debt-fund primitives.

Moneycontrol's fund pages embed a structured JSON blob under
`<script id="__NEXT_DATA__">`. Unlike Value Research, there's no JS-challenge
wall and simple curl-style GETs work.

Extracts:
  - Morningstar-style `investmentStyle` (e.g. "Moderate Sensitivity High Quality")
    → mapped to `credit_quality_score` (0–10) and `duration_risk_score` (0–10).
  - aum_cr, expense_ratio, sharpe, std_dev, beta, turnover_ratio, top10_stk_wt,
    manager_tenure_years, launch_date, benchmark, categoryName, subCategoryName,
    cagr_3y / 5y / 7y / 10y, rating (Morningstar 1-5★).

Public entrypoint:
  fetch_by_imid(imid: str)              → dict | None
  fetch_by_url(url: str)                → dict | None
"""
from __future__ import annotations
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/121.0.0.0 Safari/537.36"
)
TIMEOUT_S = 20.0
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>',
    re.DOTALL,
)


# ── Morningstar-style quality/sensitivity mapping ────────────────────────
_QUALITY_MAP = {"High": 9.0, "Medium": 6.0, "Low": 3.0}
_SENSITIVITY_MAP = {  # Lower sensitivity = less interest-rate risk = higher score
    "Limited": 9.0,
    "Moderate": 6.0,
    "Extensive": 3.0,
}
_QUALITY_RE = re.compile(r"\b(High|Medium|Low)\s+Quality\b", re.IGNORECASE)
_SENSITIVITY_RE = re.compile(r"\b(Limited|Moderate|Extensive)\s+Sensitivity\b", re.IGNORECASE)


def parse_investment_style(style: Optional[str]) -> Dict[str, Optional[float]]:
    """Convert Morningstar style string → numeric scores."""
    if not style:
        return {"credit_quality_score": None, "duration_risk_score": None}
    qm = _QUALITY_RE.search(style)
    sm = _SENSITIVITY_RE.search(style)
    return {
        "credit_quality_score": _QUALITY_MAP.get(qm.group(1).title()) if qm else None,
        "duration_risk_score": _SENSITIVITY_MAP.get(sm.group(1).title()) if sm else None,
    }


# ── HTTP ─────────────────────────────────────────────────────────────────
async def _fetch_html(url: str) -> Optional[str]:
    async with httpx.AsyncClient(
        timeout=TIMEOUT_S,
        follow_redirects=True,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        },
    ) as c:
        try:
            r = await c.get(url)
            if r.status_code == 200 and "<html" in r.text[:500].lower():
                return r.text
            logger.warning("moneycontrol %s → HTTP %s", url, r.status_code)
        except Exception as e:  # noqa: BLE001
            logger.warning("moneycontrol fetch failed: %s — %s", url, e)
    return None


def _parse_next_data(html: str) -> Optional[Dict[str, Any]]:
    m = _NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


# ── Transform ────────────────────────────────────────────────────────────
def _to_float(v: Any) -> Optional[float]:
    if v is None or v == "" or v == "None":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _parse_launch_date(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    for fmt in ("%d %b, %Y", "%d %B, %Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _years_since(iso_date: Optional[str]) -> Optional[float]:
    if not iso_date:
        return None
    try:
        dt = datetime.fromisoformat(iso_date).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return round((datetime.now(timezone.utc) - dt).days / 365.25, 2)


def _primary_manager_tenure(managers: list) -> Optional[float]:
    if not managers:
        return None
    start = managers[0].get("startDate")
    return _years_since(_parse_launch_date(start))


def _build_payload(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        d = data["props"]["pageProps"]["data"]
    except (KeyError, TypeError):
        return None
    overview = d.get("overview") or {}
    about = d.get("about") or {}
    imid = overview.get("imid") or d.get("imid")
    if not imid or not overview.get("schemeName"):
        return None

    investment_style = overview.get("investmentStyle")
    style_scores = parse_investment_style(investment_style)
    launch_iso = _parse_launch_date(about.get("lanch_date"))

    return {
        "moneycontrol_imid": imid,
        "scheme_name": overview.get("schemeName"),
        "scheme_short_name": overview.get("schemeNameShort"),
        "plan_type": (overview.get("planName") or "").lower(),
        "isin": d.get("isin") or overview.get("isin"),
        "category": overview.get("categoryName"),
        "sub_category": overview.get("subCategoryName"),
        "amc_name": overview.get("companyName"),
        "nav": _to_float(overview.get("latestNAV")),
        "aum_cr": _to_float(overview.get("aum")),
        "expense_ratio": _to_float(overview.get("expenseRatio")),
        "sharpe": _to_float(overview.get("sharpeRatio")),
        "std_dev": _to_float(overview.get("stadardDeviation")),
        "beta_3y": _to_float(overview.get("beta_3_year")),
        "turnover_ratio": _to_float(overview.get("turnoverRatio")),
        "top5_concentration_pct": _to_float(overview.get("top5StkWt")),
        "top10_concentration_pct": _to_float(overview.get("top10StkWt")),
        "ret_3y": _to_float(overview.get("cagr_3y")),
        "ret_5y": _to_float(overview.get("cagr_5y")),
        "ret_7y": _to_float(overview.get("cagr_7y")),
        "ret_10y": _to_float(overview.get("cagr_10y")),
        "cagr_inception": _to_float(overview.get("cagr_since_inception")),
        "benchmark": about.get("benchmark"),
        "risk_label": about.get("riskometer"),
        "investment_style": investment_style,
        "credit_quality_score": style_scores["credit_quality_score"],
        "duration_risk_score": style_scores["duration_risk_score"],
        "morningstar_rating": overview.get("rating"),
        "launch_date": launch_iso,
        "fund_age_years": _years_since(launch_iso),
        "manager_name": (about.get("fund_managers_details") or [{}])[0].get("name"),
        "manager_tenure_years": _primary_manager_tenure(about.get("fund_managers_details") or []),
        "asset_allocation": overview.get("assetAllocation"),
        "source": "moneycontrol",
    }


# ── Public API ───────────────────────────────────────────────────────────
async def fetch_by_url(url: str) -> Optional[Dict[str, Any]]:
    html = await _fetch_html(url)
    if not html:
        return None
    data = _parse_next_data(html)
    if not data:
        return None
    return _build_payload(data)


async def fetch_by_imid(imid: str, slug_hint: Optional[str] = None) -> Optional[Dict[str, Any]]:
    slug = slug_hint or ""
    url = f"https://www.moneycontrol.com/mutual-funds/nav/{slug}/{imid}" if slug else \
          f"https://www.moneycontrol.com/mutual-funds/nav/{imid}/{imid}"
    return await fetch_by_url(url)


async def search_fund(scheme_name: str) -> Optional[Dict[str, str]]:
    """Search MC autosuggest for a mutual fund scheme.

    Returns {"imid": str, "url": str, "display_name": str} on the first
    matching `/mutual-funds/nav/...` result, else None. Prefers Direct-plan
    matches when the query contains "direct".
    """
    url = "https://www.moneycontrol.com/mccode/common/autosuggestion_solr.php"
    params = {"classic": "true", "query": scheme_name, "type": "2", "format": "json",
              "callback": ""}
    async with httpx.AsyncClient(timeout=TIMEOUT_S,
                                 headers={"User-Agent": USER_AGENT}) as c:
        try:
            r = await c.get(url, params=params)
            r.raise_for_status()
            txt = r.text.strip()
            if txt.startswith("(") and txt.endswith(")"):
                txt = txt[1:-1]
            data = json.loads(txt)
        except Exception as e:  # noqa: BLE001
            logger.warning("search_fund(%s) failed: %s", scheme_name, e)
            return None

    hits = data if isinstance(data, list) else (data.get("data") or [])
    mf_hits = [h for h in hits if "/mutual-funds/nav/" in (h.get("link_src") or "")]

    wants_direct = "direct" in scheme_name.lower()
    if wants_direct:
        direct_hits = [
            h for h in mf_hits
            if "direct" in (h.get("pdt_dis_nm") or h.get("link_src") or "").lower()
        ]
        if direct_hits:
            mf_hits = direct_hits

    for h in mf_hits[:5]:
        link = h.get("link_src") or ""
        m = re.search(r"/([A-Z]{2,4}\d+)(?:$|[/?])", link)
        if m:
            return {
                "imid": m.group(1),
                "url": link,
                "display_name": (h.get("pdt_dis_nm") or "").strip(),
            }
    return None


async def search_imid(scheme_name: str) -> Optional[str]:
    """Backward-compatible wrapper: returns only the imid."""
    hit = await search_fund(scheme_name)
    return hit["imid"] if hit else None
