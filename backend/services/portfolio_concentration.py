"""Portfolio concentration analytics.

Computes AMC / Sector / Company exposure across a user's holdings,
including look-through into mutual-fund holdings using
`fund_holdings_cache`.

Per the Diversification & Concentration PRD (May 2026), this is the
shared compute used by the Insights tab's three exposure sections.

Inputs:
  holdings — list of dicts (Mongo `holdings` collection rows):
    { name, ticker, asset_type, quantity, current_price, sector, ... }

Outputs (single envelope, keyed by dimension):
  {
    "total_value": float,
    "amc":     { items: [...], hhi, largest_pct, effective_n, warning },
    "company": { items: [...], hhi, largest_pct, effective_n, warning,
                 top10_pct },
    "sector":  { items: [...], hhi, largest_pct, effective_n, warning }
  }

Each `items[i]` has: name, value_inr, pct, count (or via), and a
display-friendly sub_label where appropriate.
"""
from __future__ import annotations

import re
from typing import Any, Iterable
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


# ── AMC name extractor ────────────────────────────────────────────

# Drop these tokens from MF holding names — everything before the
# first "stopword" is treated as the AMC name.
_AMC_STOPWORDS = {
    "MUTUAL", "FUND", "MF", "DIRECT", "REGULAR", "PLAN", "GROWTH",
    "DIVIDEND", "IDCW", "PAYOUT", "REINVESTMENT", "INDEX", "ETF",
    "GOLD", "LIQUID", "ARBITRAGE", "BALANCED", "EQUITY", "DEBT",
    "HYBRID", "FLEXI", "MULTI", "LARGE", "MID", "SMALL", "MICRO",
    "CAP", "SHORT", "LONG", "MEDIUM", "TERM", "OVERNIGHT", "ULTRA",
    "FOCUSED", "VALUE", "QUANT", "BLUECHIP", "ELSS", "TAX", "SAVER",
    "BANKING", "PHARMA", "INFRASTRUCTURE", "TECHNOLOGY", "DIVIDEND",
    "MOMENTUM", "ALPHA", "OPPORTUNITIES", "ADVANTAGE", "BLUE", "CHIP",
    "SAVINGS", "FIXED", "MATURITY", "TOP", "100", "200", "250", "500",
}

# Common multi-word AMC prefixes we want to keep together (some have
# 3 words). Order matters — longest match wins.
_AMC_MULTIWORD_PREFIX = [
    ("PARAG", "PARIKH"),
    ("ICICI", "PRUDENTIAL"),
    ("SBI", "MAGNUM"),
    ("SBI", "CONTRA"),
    ("SBI", "PSU"),
    ("HDFC", "AMC"),
    ("NIPPON", "INDIA"),
    ("DSP", "BLACKROCK"),
    ("MIRAE", "ASSET"),
    ("TATA", "AIA"),
    ("BARODA", "BNP"),
    ("BANDHAN",),
    ("EDELWEISS",),
    ("INVESCO",),
    ("MOTILAL", "OSWAL"),
    ("FRANKLIN", "TEMPLETON"),
    ("ADITYA", "BIRLA", "SUN", "LIFE"),
    ("AXIS",),
    ("KOTAK", "MAHINDRA"),
    ("UTI",),
    ("CANARA", "ROBECO"),
    ("MAHINDRA", "MANULIFE"),
    ("UNION",),
    ("LIC",),
    ("PGIM", "INDIA"),
    ("PRINCIPAL",),
    ("PPFAS",),
    ("QUANT",),
    ("WHITEOAK", "CAPITAL"),
    ("HELIOS",),
    ("ITI",),
    ("NJ",),
    ("BAJAJ", "FINSERV"),
    ("ZERODHA",),
    ("SAMCO",),
    ("NAVI",),
    ("GROW", "GROWW"),
    ("JM", "FINANCIAL"),
    ("JM",),
    ("SHRIRAM",),
    ("SUNDARAM",),
    ("TRUST",),
    ("360", "ONE"),
    ("OLD", "BRIDGE"),
]

# Display-name normalisation (TITLE-cased)
_AMC_DISPLAY = {
    ("PARAG", "PARIKH"): "Parag Parikh",
    ("ICICI", "PRUDENTIAL"): "ICICI Prudential",
    ("SBI",): "SBI",
    ("SBI", "MAGNUM"): "SBI",
    ("HDFC",): "HDFC",
    ("NIPPON", "INDIA"): "Nippon India",
    ("DSP", "BLACKROCK"): "DSP",
    ("DSP",): "DSP",
    ("MIRAE", "ASSET"): "Mirae Asset",
    ("TATA",): "Tata",
    ("BARODA", "BNP"): "Baroda BNP Paribas",
    ("BANDHAN",): "Bandhan",
    ("EDELWEISS",): "Edelweiss",
    ("INVESCO",): "Invesco",
    ("MOTILAL", "OSWAL"): "Motilal Oswal",
    ("FRANKLIN", "TEMPLETON"): "Franklin Templeton",
    ("ADITYA", "BIRLA", "SUN", "LIFE"): "Aditya Birla Sun Life",
    ("AXIS",): "Axis",
    ("KOTAK", "MAHINDRA"): "Kotak",
    ("KOTAK",): "Kotak",
    ("UTI",): "UTI",
    ("CANARA", "ROBECO"): "Canara Robeco",
    ("MAHINDRA", "MANULIFE"): "Mahindra Manulife",
    ("UNION",): "Union",
    ("LIC",): "LIC",
    ("PGIM", "INDIA"): "PGIM India",
    ("PRINCIPAL",): "Principal",
    ("PPFAS",): "PPFAS",
    ("QUANT",): "Quant",
    ("WHITEOAK", "CAPITAL"): "WhiteOak Capital",
    ("HELIOS",): "Helios",
    ("ITI",): "ITI",
    ("NJ",): "NJ",
    ("BAJAJ", "FINSERV"): "Bajaj Finserv",
    ("ZERODHA",): "Zerodha",
    ("SAMCO",): "Samco",
    ("NAVI",): "Navi",
    ("GROW", "GROWW"): "Groww",
    ("HDFC", "AMC"): "HDFC",
    ("SBI", "CONTRA"): "SBI",
    ("SBI", "PSU"): "SBI",
    ("JM", "FINANCIAL"): "JM Financial",
    ("JM",): "JM Financial",
    ("SHRIRAM",): "Shriram",
    ("SUNDARAM",): "Sundaram",
    ("TRUST",): "Trust",
    ("360", "ONE"): "360 ONE",
    ("OLD", "BRIDGE"): "Old Bridge",
}


# MF category labels that leak into MF `sector` metadata but are NOT
# real economic sectors (Balanced, Mid Cap, etc. are fund categories).
# When we encounter these as a sector, bucket them as "Unclassified"
# so totals still reconcile to portfolio value without showing
# category names in the Sector Exposure widget.
_NON_SECTOR_LABELS = {
    "balanced", "hybrid", "arbitrage",
    "large cap", "mid cap", "small cap", "micro cap", "multi cap",
    "flexi cap", "focused", "elss", "tax saver",
    "debt", "liquid", "overnight", "short term", "ultra short",
    "fund of funds", "fof", "index", "etf",
}


def _normalize_sector(label: str | None) -> str:
    """Coerce category-style labels into 'Unclassified'. Real sector
    labels pass through unchanged."""
    raw = (label or "").strip()
    if not raw:
        return "Other"
    if raw.lower() in _NON_SECTOR_LABELS:
        return "Unclassified"
    return raw


def _amc_from_scheme_name(name: str | None) -> str:
    """Extract the AMC name from an MF holding `name` string.

    Falls back to the first capitalised token if nothing matches the
    known-AMC table.
    """
    if not name:
        return "Unknown AMC"
    tokens = [t for t in re.split(r"\s+", str(name).upper()) if t and t.isalnum()]
    # Try multi-word prefixes longest first
    for prefix in sorted(_AMC_MULTIWORD_PREFIX, key=lambda p: -len(p)):
        if tuple(tokens[:len(prefix)]) == prefix:
            return _AMC_DISPLAY.get(prefix, " ".join(t.title() for t in prefix))
    # Fallback — take leading tokens until a stopword
    head = []
    for t in tokens:
        if t in _AMC_STOPWORDS:
            break
        head.append(t)
        if len(head) >= 3:
            break
    if head:
        return _AMC_DISPLAY.get(tuple(head), " ".join(t.title() for t in head))
    return "Unknown AMC"


# ── Sector classification (cyclical vs defensive) ─────────────────

# Coarse Indian-market mapping. "Cyclical" = sensitive to economic cycle;
# "Defensive" = relatively stable through downturns. Unknowns → "other".
_CYCLICAL_SECTORS = {
    "financial", "financial services", "banking", "banking & financial",
    "energy", "metals", "mining", "auto", "automobile", "automotive",
    "real estate", "realty", "construction", "infrastructure", "cement",
    "capital goods", "chemicals", "industrials", "industrial",
    "media", "entertainment", "textiles", "consumer discretionary",
}
_DEFENSIVE_SECTORS = {
    "consumer staples", "fmcg", "consumer goods", "pharmaceuticals",
    "pharma", "healthcare", "utilities", "power", "telecom",
    "telecommunication", "it", "information technology", "technology",
    "services",
}


def _cycle_class(label: str) -> str:
    s = (label or "").strip().lower()
    if s in _CYCLICAL_SECTORS:
        return "cyclical"
    if s in _DEFENSIVE_SECTORS:
        return "defensive"
    return "other"


# ── Issuer-group mapping (HDFC group = bank + AMC + life, etc.) ──

_GROUP_RULES: list[tuple[str, str]] = [
    # (substring matched case-insensitively in company name, group label)
    ("hdfc",        "HDFC Group"),
    ("reliance",    "Reliance Group"),
    ("jio",         "Reliance Group"),
    ("tata",        "Tata Group"),
    ("adani",       "Adani Group"),
    ("bajaj",       "Bajaj Group"),
    ("aditya birla","Aditya Birla Group"),
    ("birla",       "Aditya Birla Group"),
    ("mahindra",    "Mahindra Group"),
    ("l&t",         "L&T Group"),
    ("larsen",      "L&T Group"),
    ("godrej",      "Godrej Group"),
    ("vedanta",     "Vedanta Group"),
    ("jindal",      "Jindal Group"),
    ("jsw",         "JSW Group"),
]


def _group_for(company_name: str) -> str | None:
    s = (company_name or "").lower()
    for needle, group in _GROUP_RULES:
        if needle in s:
            return group
    return None


# ── Concentration metrics ─────────────────────────────────────────

def _hhi(weights: Iterable[float]) -> float:
    """Herfindahl-Hirschman Index over weights summing to ~1.0.

    Returns 0..1; lower = more diversified.
    """
    wsum = sum(w for w in weights if w is not None) or 1.0
    return sum(((w or 0) / wsum) ** 2 for w in weights)


def _effective_n(weights: Iterable[float]) -> float:
    """Inverse HHI = effective number of equally-weighted holdings."""
    h = _hhi(weights)
    return (1.0 / h) if h > 0 else 0.0


def _build_section(
    items: list[dict],
    *,
    warn_largest_pct: float,
    warn_top_label: str,
    top_n: int = 10,
    extra_top10: bool = False,
    diversified_threshold: float | None = None,
) -> dict:
    """Common section builder. Sorts by value_inr desc, computes
    HHI / effective_n / largest_pct, attaches a warning string when
    concentration exceeds thresholds.

    `diversified_threshold` (optional) — when set, sections where
    `largest_pct` is below this number get a positive "diversified"
    hero insight. Used to differentiate Sector and Company widgets
    (which usually show healthy diversification) from AMC (which
    often shows concentration)."""
    items_sorted = sorted(items, key=lambda d: -d["value_inr"])
    total = sum(it["value_inr"] for it in items_sorted) or 0.0
    for it in items_sorted:
        it["pct"] = round((it["value_inr"] / total) * 100, 2) if total else 0.0

    weights = [it["value_inr"] for it in items_sorted]
    hhi = _hhi(weights)
    eff_n = _effective_n(weights)
    largest_pct = items_sorted[0]["pct"] if items_sorted else 0.0
    top_name = items_sorted[0]["name"] if items_sorted else "—"
    top10_pct = round(sum(it["pct"] for it in items_sorted[:10]), 2)

    # Acronyms (AMC) stay uppercased mid-sentence; other labels lowercase.
    label_inline = warn_top_label if warn_top_label.isupper() else warn_top_label.lower()

    warning = None
    if largest_pct >= warn_largest_pct:
        warning = (
            f"{top_name} accounts for {largest_pct:.1f}% of your "
            f"{warn_top_label} exposure — above {int(warn_largest_pct)}% raises "
            "concentration risk. Consider trimming or diversifying."
        )
    elif extra_top10 and top10_pct >= 60:
        warning = (
            f"Top 10 holdings = {top10_pct:.0f}% of {label_inline} exposure — "
            "diversification looks thin."
        )

    # Hero insight — structured tone + headline + detail.
    # Tone tiers: ok / warn / bad — drives banner colour on the frontend.
    if largest_pct >= warn_largest_pct + 10:
        tone = "bad"
    elif largest_pct >= warn_largest_pct:
        tone = "warn"
    elif diversified_threshold is not None and largest_pct < diversified_threshold:
        tone = "ok"
    elif extra_top10 and top10_pct >= 60:
        tone = "warn"
    else:
        tone = "ok"

    if tone == "bad":
        headline = f"High {warn_top_label} Concentration"
        detail = (
            f"{top_name} is {largest_pct:.1f}% of your {label_inline} "
            f"exposure — well above the {int(warn_largest_pct)}% risk threshold."
        )
    elif tone == "warn":
        headline = f"{warn_top_label} Concentration to Watch"
        detail = (
            f"{top_name} is {largest_pct:.1f}% of your {label_inline} "
            f"exposure — at or above the {int(warn_largest_pct)}% threshold."
        )
    else:
        if warn_top_label == "Sector":
            headline = "Excellent Sector Diversification"
        elif warn_top_label == "Single-company":
            headline = "No Significant Single-Stock Risk"
        elif warn_top_label == "AMC":
            headline = "Healthy AMC Diversification"
        else:
            headline = f"Well-Diversified {warn_top_label}"
        detail = (
            f"Largest is {top_name} at {largest_pct:.1f}% — comfortably "
            f"below the {int(warn_largest_pct)}% risk threshold."
        )

    # v4 additions (Modified Endpoint C.5)
    top5_pct = round(sum(i["pct"] for i in items_sorted[:5]), 2) if items_sorted else 0.0
    caution_pct = int(warn_largest_pct)  # policy constant, may become risk-band-derived later

    result = {
        "items": items_sorted[:top_n],
        "all_items_count": len(items_sorted),
        "hhi": round(hhi, 4),
        "hhi_x10000": round(hhi * 10000),    # v4 convenience — UI shows ×10000 form
        "effective_n": round(eff_n, 1),
        "largest_pct": largest_pct,
        "top5_pct": top5_pct,                # v4
        "caution_pct": caution_pct,          # v4
        "warning": warning,
        "hero_insight": {"tone": tone, "headline": headline, "detail": detail},
    }
    if extra_top10:
        result["top10_pct"] = top10_pct
    return result


# ── Public API ────────────────────────────────────────────────────

def compute_concentration(
    holdings: list[dict],
    *,
    fund_lookthrough: dict[str, dict] | None = None,
) -> dict:
    """Compute AMC / Sector / Company concentration from holdings.

    Args:
      holdings: list of holding docs with name, ticker, asset_type,
        quantity, current_price, sector.
      fund_lookthrough: optional dict keyed by `ticker` (ISIN) →
        { "holdings": [{name,sector,pct}, ...], "sectors": [{name,pct}, ...] }
        Used to dissolve mutual-fund weights into underlying companies
        and sectors. If missing for a given MF, the MF's own
        `sector` field is used as a coarse fallback.

    Returns the full envelope (see module docstring).
    """
    fund_lookthrough = fund_lookthrough or {}

    # 1. Total portfolio value
    def _hv(h: dict) -> float:
        q = float(h.get("quantity") or 0)
        p = float(h.get("current_price") or 0)
        return q * p

    total_value = sum(_hv(h) for h in holdings)

    # 2. AMC buckets — only MFs contribute (equity has no AMC)
    amc_buckets: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"value_inr": 0.0, "count": 0}
    )
    for h in holdings:
        if h.get("asset_type") not in {"mutual_fund", "etf"}:
            continue
        v = _hv(h)
        if v <= 0:
            continue
        amc = _amc_from_scheme_name(h.get("name"))
        amc_buckets[amc]["value_inr"] += v
        amc_buckets[amc]["count"] += 1
        amc_buckets[amc].setdefault("funds", [])
        fname = (h.get("name") or "")[:60]
        if fname and fname not in amc_buckets[amc]["funds"]:
            amc_buckets[amc]["funds"].append(fname)
    amc_items = [{"name": k, "value_inr": v["value_inr"], "count": v["count"], "funds": v.get("funds", [])} for k, v in amc_buckets.items()]
    amc_section = _build_section(amc_items, warn_largest_pct=30, warn_top_label="AMC",
                                 diversified_threshold=20)

    # 3. Sector buckets — equity uses its `sector`, MF dissolves via lookthrough
    sector_buckets: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"value_inr": 0.0, "via": defaultdict(float), "holdings": []}
    )
    for h in holdings:
        v = _hv(h)
        if v <= 0:
            continue
        atype = (h.get("asset_type") or "").lower()
        hname = (h.get("name") or "")[:50]
        if atype == "equity":
            sec = _normalize_sector(h.get("sector"))
            sector_buckets[sec]["value_inr"] += v
            sector_buckets[sec]["via"]["direct"] += v
            if hname and hname not in sector_buckets[sec]["holdings"]:
                sector_buckets[sec]["holdings"].append(hname)
        elif atype in {"mutual_fund", "etf"}:
            lookup = fund_lookthrough.get(h.get("ticker") or "")
            if lookup and (lookup.get("sectors") or []):
                for s in (lookup.get("sectors") or []):
                    name = _normalize_sector(s.get("name"))
                    pct = float(s.get("pct") or 0)
                    if pct <= 0:
                        continue
                    sector_buckets[name]["value_inr"] += v * (pct / 100.0)
                    sector_buckets[name]["via"]["mf"] += v * (pct / 100.0)
                    if hname and hname not in sector_buckets[name]["holdings"]:
                        sector_buckets[name]["holdings"].append(hname)
            else:
                sec = _normalize_sector(h.get("sector"))
                sector_buckets[sec]["value_inr"] += v
                sector_buckets[sec]["via"]["mf"] += v
                if hname and hname not in sector_buckets[sec]["holdings"]:
                    sector_buckets[sec]["holdings"].append(hname)
        elif atype == "gold":
            sector_buckets["Gold"]["value_inr"] += v
            sector_buckets["Gold"]["via"]["gold"] += v
            if hname and hname not in sector_buckets["Gold"]["holdings"]:
                sector_buckets["Gold"]["holdings"].append(hname)
    sector_items = []
    for k, vobj in sector_buckets.items():
        sector_items.append({
            "name": k,
            "value_inr": vobj["value_inr"],
            "via": dict(vobj["via"]),
            "holdings": list(vobj.get("holdings", []))[:10],
            "cycle": _cycle_class(k),
        })
    sector_section = _build_section(sector_items, warn_largest_pct=35, warn_top_label="Sector",
                                    diversified_threshold=20)

    # Cyclical vs Defensive vs Other split (summary pills)
    cycle_totals: dict[str, float] = defaultdict(float)
    for it in sector_items:
        cycle_totals[it["cycle"]] += it["value_inr"]
    cycle_grand = sum(cycle_totals.values()) or 1.0
    sector_section["cycle_split"] = {
        "cyclical_pct":  round(cycle_totals["cyclical"]  / cycle_grand * 100, 1),
        "defensive_pct": round(cycle_totals["defensive"] / cycle_grand * 100, 1),
        "other_pct":     round(cycle_totals["other"]     / cycle_grand * 100, 1),
    }

    # 4. Company buckets — direct equity 1:1, MFs dissolved via lookthrough
    company_buckets: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"value_inr": 0.0, "via_direct": 0.0, "via_funds": 0, "sector": None}
    )
    for h in holdings:
        v = _hv(h)
        if v <= 0:
            continue
        atype = (h.get("asset_type") or "").lower()
        if atype == "equity":
            name = (h.get("name") or "").title().strip() or h.get("ticker") or "Unknown"
            company_buckets[name]["value_inr"] += v
            company_buckets[name]["via_direct"] += v
            company_buckets[name]["sector"] = h.get("sector") or company_buckets[name]["sector"]
        elif atype in {"mutual_fund", "etf"}:
            lookup = fund_lookthrough.get(h.get("ticker") or "")
            if not lookup or not (lookup.get("holdings") or []):
                continue
            for sh in lookup["holdings"]:
                name = (sh.get("name") or "").strip()
                if not name:
                    continue
                pct = float(sh.get("pct") or 0)
                if pct <= 0:
                    continue
                # Title-case but preserve a couple of acronyms
                disp = name.replace(" Ltd.", " Ltd").replace(" Limited", " Ltd")
                company_buckets[disp]["value_inr"] += v * (pct / 100.0)
                company_buckets[disp]["via_funds"] += 1
                company_buckets[disp]["sector"] = sh.get("sector") or company_buckets[disp]["sector"]
    company_items = []
    for name, vobj in company_buckets.items():
        via_direct = vobj["via_direct"]
        via_funds  = vobj["via_funds"]
        # Cross-held = held in BOTH direct equity AND ≥1 mutual fund,
        # OR held across ≥2 mutual funds. Either way, this single name
        # is exposed through multiple routes — what the PRD calls
        # "hidden overlap".
        cross_routes = (1 if via_direct > 0 else 0) + via_funds
        company_items.append({
            "name": name,
            "value_inr": vobj["value_inr"],
            "via_direct_inr": via_direct,
            "via_funds_count": via_funds,
            "sector": vobj["sector"],
            "group": _group_for(name),
            "cross_held": cross_routes >= 2,
            "routes_count": cross_routes,
        })
    company_section = _build_section(company_items, warn_largest_pct=10,
                                     warn_top_label="Single-company",
                                     top_n=15, extra_top10=True,
                                     diversified_threshold=5)

    # Hidden Overlap — top companies held via multiple routes
    overlap_items = sorted(
        [c for c in company_items if c.get("cross_held")],
        key=lambda c: -c["value_inr"],
    )[:10]
    company_section["hidden_overlap"] = {
        "items": overlap_items,
        "count": len(overlap_items),
    }

    # Group Exposure — aggregate company buckets by issuer group
    group_buckets: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"value_inr": 0.0, "companies": []}
    )
    for c in company_items:
        g = c.get("group")
        if not g:
            continue
        group_buckets[g]["value_inr"] += c["value_inr"]
        if c["name"] not in group_buckets[g]["companies"]:
            group_buckets[g]["companies"].append(c["name"])
    group_items = [
        {"name": g, "value_inr": vobj["value_inr"],
         "companies": vobj["companies"][:10],
         "company_count": len(vobj["companies"])}
        for g, vobj in group_buckets.items()
    ]
    group_section = _build_section(
        group_items, warn_largest_pct=15, warn_top_label="Group",
        diversified_threshold=8, top_n=10,
    ) if group_items else {
        "items": [], "all_items_count": 0, "hhi": 0,
        "effective_n": 0, "largest_pct": 0, "warning": None,
        "hero_insight": {"tone": "ok", "headline": "No Group Concentration",
                         "detail": "No identifiable business groups in your portfolio."},
    }

    return {
        "total_value": round(total_value, 2),
        "amc": amc_section,
        "sector": sector_section,
        "company": company_section,
        "group": group_section,
    }


__all__ = ["compute_concentration", "_amc_from_scheme_name"]
