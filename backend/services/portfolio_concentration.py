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
) -> dict:
    """Common section builder. Sorts by value_inr desc, computes
    HHI / effective_n / largest_pct, attaches a warning string when
    concentration exceeds thresholds."""
    items_sorted = sorted(items, key=lambda d: -d["value_inr"])
    total = sum(it["value_inr"] for it in items_sorted) or 0.0
    for it in items_sorted:
        it["pct"] = round((it["value_inr"] / total) * 100, 2) if total else 0.0

    weights = [it["value_inr"] for it in items_sorted]
    hhi = _hhi(weights)
    eff_n = _effective_n(weights)
    largest_pct = items_sorted[0]["pct"] if items_sorted else 0.0
    top10_pct = round(sum(it["pct"] for it in items_sorted[:10]), 2)

    warning = None
    if largest_pct >= warn_largest_pct:
        warning = (
            f"{items_sorted[0]['name']} accounts for {largest_pct:.1f}% of your "
            f"{warn_top_label} exposure — above {int(warn_largest_pct)}% raises "
            "concentration risk. Consider trimming or diversifying."
        )
    elif extra_top10 and top10_pct >= 60:
        warning = (
            f"Top 10 holdings = {top10_pct:.0f}% of {warn_top_label.lower()} exposure — "
            "diversification looks thin."
        )

    result = {
        "items": items_sorted[:top_n],
        "all_items_count": len(items_sorted),
        "hhi": round(hhi, 4),
        "effective_n": round(eff_n, 1),
        "largest_pct": largest_pct,
        "warning": warning,
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
    amc_items = [{"name": k, "value_inr": v["value_inr"], "count": v["count"]} for k, v in amc_buckets.items()]
    amc_section = _build_section(amc_items, warn_largest_pct=30, warn_top_label="AMC")

    # 3. Sector buckets — equity uses its `sector`, MF dissolves via lookthrough
    sector_buckets: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"value_inr": 0.0, "via": defaultdict(float)}
    )
    for h in holdings:
        v = _hv(h)
        if v <= 0:
            continue
        atype = (h.get("asset_type") or "").lower()
        if atype == "equity":
            sec = (h.get("sector") or "Other").strip() or "Other"
            sector_buckets[sec]["value_inr"] += v
            sector_buckets[sec]["via"]["direct"] += v
        elif atype in {"mutual_fund", "etf"}:
            lookup = fund_lookthrough.get(h.get("ticker") or "")
            if lookup and (lookup.get("sectors") or []):
                # Dissolve into underlying sectors by pct
                for s in (lookup.get("sectors") or []):
                    name = s.get("name") or "Other"
                    pct = float(s.get("pct") or 0)
                    if pct <= 0:
                        continue
                    sector_buckets[name]["value_inr"] += v * (pct / 100.0)
                    sector_buckets[name]["via"]["mf"] += v * (pct / 100.0)
            else:
                # Fallback — treat the whole MF value under its own sector field
                sec = (h.get("sector") or "Other").strip() or "Other"
                # MF "sector" is often broad like "Gold", "Liquid" — keep it
                sector_buckets[sec]["value_inr"] += v
                sector_buckets[sec]["via"]["mf"] += v
        elif atype == "gold":
            sector_buckets["Gold"]["value_inr"] += v
            sector_buckets["Gold"]["via"]["gold"] += v
    sector_items = []
    for k, vobj in sector_buckets.items():
        sector_items.append({
            "name": k,
            "value_inr": vobj["value_inr"],
            "via": dict(vobj["via"]),
        })
    sector_section = _build_section(sector_items, warn_largest_pct=35, warn_top_label="Sector")

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
        company_items.append({
            "name": name,
            "value_inr": vobj["value_inr"],
            "via_direct_inr": vobj["via_direct"],
            "via_funds_count": vobj["via_funds"],
            "sector": vobj["sector"],
        })
    company_section = _build_section(company_items, warn_largest_pct=10,
                                     warn_top_label="Single-company",
                                     top_n=15, extra_top10=True)

    return {
        "total_value": round(total_value, 2),
        "amc": amc_section,
        "sector": sector_section,
        "company": company_section,
    }


__all__ = ["compute_concentration", "_amc_from_scheme_name"]
