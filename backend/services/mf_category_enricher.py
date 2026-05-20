"""MF SEBI Category Enricher.

Tags every mutual-fund holding with a real SEBI primary category +
sub-category. Used by services/fund_clusterer.py to prevent the
"Large Cap fund paired with Index fund" bug (2026-05-20).

Why this module exists
──────────────────────
The pre-existing `enrich_holdings_with_sectors` mapper sets each MF's
`sector` field to its **primary stock universe** ("Large Cap",
"Banking", …), not its SEBI category. So:

  Mirae Asset Large Cap Fund   → sector = "Large Cap"
  UTI Nifty 50 Index Fund      → sector = "Large Cap"   (holds Nifty 50 = large caps)
  HDFC NIFTY50 Equal Weight    → sector = "Large Cap"   (same)

When the overlap detector pairs by `sector`, all three look identical
and get flagged as duplicates. They aren't — they're three different
SEBI primary categories (Large Cap, Index Fund tracking Nifty 50, Index
Fund tracking Equal-Weight Nifty 50).

What this module does
─────────────────────
Adds two fields per holding:

  sebi_category      e.g. "Large Cap" / "Mid Cap" / "Flexi Cap" /
                          "Index Fund" / "Aggressive Hybrid" / …
  sebi_subcategory   e.g. "Nifty 50" / "Nifty Next 50" / "Banking" /
                          None when no finer grain applies

Source order (most authoritative first):
  1. holding["scheme_category"] if already populated by upstream NIDP
     enrichment (mf_analytics_engine writes this into the mongo
     holdings record after the data-lake fix merges)
  2. holding["category"] if set by the older insights enrichment path
  3. Name-parser fallback — uses the SEBI category vocabulary from the
     user's framework

Never raises. When no signal is available, both fields remain None
and `fund_clusterer.cluster_overlapping_funds` skips that holding
(can't safely pair it).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


# ── SEBI primary categories (per user's framework, 2026-05-20) ───────
# Order matters — longer / more-specific patterns first, since we
# stop at the first match.

# Equity Funds
_EQUITY_PATTERNS: List[Tuple[str, str]] = [
    (r"\blarge\s*&?\s*mid\s*cap\b", "Large & Mid Cap"),
    (r"\blarge\s*cap\b",             "Large Cap"),
    (r"\bmid\s*cap\b",               "Mid Cap"),
    (r"\bsmall\s*cap\b",             "Small Cap"),
    (r"\bmulti[\s-]?cap\b",          "Multi Cap"),
    (r"\bflexi[\s-]?cap\b",          "Flexi Cap"),
    (r"\bfocus(ed)?\b",              "Focused Fund"),
    (r"\bvalue\b",                   "Value Fund"),
    (r"\bcontra\b",                  "Contra Fund"),
    (r"\belss\b|tax\s*saver",        "ELSS"),
]

# Sectoral / Thematic
_SECTORAL_PATTERNS: List[Tuple[str, str]] = [
    (r"\bbank(ing)?\b",       "Banking"),
    (r"\bpharma\b",           "Pharma"),
    (r"\bit\b|\btechnolog",   "IT"),
    (r"\binfrastruct",        "Infrastructure"),
    # Split FMCG and Consumption — NSE publishes distinct indices for each
    # (NIFTY FMCG vs NIFTY India Consumption), so the SEBI master treats
    # them as separate Sectoral/Thematic sub-categories. The previous
    # combined pattern emitted "Consumption" for FMCG funds, which
    # mismatched the master seed.
    (r"\bfmcg\b",             "FMCG"),
    (r"\bconsum(er|ption)\b", "Consumption"),
    (r"\benerg(y|ie)",        "Energy"),
    (r"\bauto\b",             "Auto"),
    (r"\bmnc\b",              "MNC"),
    (r"\bpsu\b",              "PSU"),
]

# Debt Funds — labels must match nidp.sebi_category_master seed
# (migration 061). "Income" is intentionally absent: SEBI's 2017
# re-categorisation retired it; funds previously named "Income" got
# re-mapped to Dynamic Bond / Medium Duration / etc.
_DEBT_PATTERNS: List[Tuple[str, str]] = [
    (r"\bliquid\b",                          "Liquid"),
    (r"\bultra\s*short\b",                   "Ultra Short Duration"),
    (r"\blow\s*duration\b",                  "Low Duration"),
    (r"\bmoney\s*market\b",                  "Money Market"),
    (r"\bcorporate\s*bond\b",                "Corporate Bond"),
    (r"\bbanking\s*&?\s*psu\b",              "Banking & PSU"),
    # "Gilt 10Y Constant" / "Constant Maturity Gilt" — beats generic Gilt
    (r"\bgilt.*\b10\s*y\b|\bconstant\s+maturity\s+gilt\b", "Gilt 10Y Constant"),
    (r"\bgilt\b",                            "Gilt"),
    (r"\bdynamic\s*bond\b",                  "Dynamic Bond"),
    (r"\bcredit\s*risk\b",                   "Credit Risk"),
    (r"\bovernight\b",                       "Overnight"),
    # "Medium to Long" must beat plain "Medium Duration"
    (r"\bmedium\s+to\s+long[\s-]?duration\b", "Medium to Long Duration"),
    (r"\bmedium[\s-]?duration\b",            "Medium Duration"),
    (r"\bshort[\s-]?duration\b",             "Short Duration"),
    (r"\blong[\s-]?duration\b",              "Long Duration"),
    (r"\bfloater\b|\bfloating\s+rate\b",     "Floater"),
]

# Hybrid Funds — "Hybrid Equity" funds are SEBI-classified as
# Aggressive Hybrid (65-80% equity). Pattern lands here so it beats
# the generic Equity sub-categories.
_HYBRID_PATTERNS: List[Tuple[str, str]] = [
    (r"\baggressive\s*hybrid\b",    "Aggressive Hybrid"),
    (r"\bhybrid\s*equity\b",        "Aggressive Hybrid"),
    (r"\bbalanced\s*advantage\b|baf\b", "Balanced Advantage"),
    (r"\bdynamic\s*asset\s*allocation\b", "Balanced Advantage"),
    (r"\bequity\s*savings?\b",      "Equity Savings"),
    (r"\bmulti[\s-]?asset\b",       "Multi Asset Allocation"),
    (r"\barbitrage\b",              "Arbitrage"),
    (r"\bconservative\s*hybrid\b",  "Conservative Hybrid"),
    (r"\bbalanced\s*hybrid\b|\bbalanced\s*fund\b", "Balanced Hybrid"),
]

# Solution-Oriented
_SOLUTION_PATTERNS: List[Tuple[str, str]] = [
    (r"\bretirement\b",          "Retirement Fund"),
    (r"\bchildren\b|\bchild\b",  "Children's Fund"),
]

# Index sub-category map. (Regex, sub_label)
_INDEX_INDEX_NAMES: List[Tuple[str, str]] = [
    (r"\bnifty\s*50\b(?!\s*equal)",        "Nifty 50"),
    (r"\bnifty\s*50\s*equal\s*weight",      "Nifty 50 Equal Weight"),
    (r"\bnifty\s*next\s*50\b",              "Nifty Next 50"),
    (r"\bnifty\s*100\b",                    "Nifty 100"),
    (r"\bnifty\s*midcap\s*150\b",           "Nifty Midcap 150"),
    (r"\bnifty\s*smallcap\s*250\b",         "Nifty Smallcap 250"),
    (r"\bnifty\s*bank\b",                   "Nifty Bank"),
    (r"\bnifty\s*it\b",                     "Nifty IT"),
    (r"\bsensex\b",                         "Sensex"),
    (r"\bbse\s*500\b",                      "BSE 500"),
    (r"\bnifty\s*500\b",                    "Nifty 500"),
]

_INDEX_TRIGGER = re.compile(
    r"\bindex\b|\bnifty\b|\bsensex\b|\bbse\s*\d+\b|\bequal\s*weight\b",
    re.IGNORECASE,
)
_GOLD_TRIGGER = re.compile(r"\bgold\b", re.IGNORECASE)
_FOF_TRIGGER = re.compile(r"\bfund\s*of\s*funds?\b|\bfof\b", re.IGNORECASE)
_INTL_TRIGGER = re.compile(
    r"\bglobal\b|\binternational\b|\bus\s*equity\b|\bnasdaq\b|\bs&p\s*500\b|\bworld\b|\boverseas\b",
    re.IGNORECASE,
)


def _normalise(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").lower()).strip()


def _match_first(name_lc: str, patterns: List[Tuple[str, str]]) -> Optional[str]:
    for pattern, label in patterns:
        if re.search(pattern, name_lc):
            return label
    return None


def parse_sebi_from_name(name: str) -> Tuple[Optional[str], Optional[str]]:
    """Pure name-parser fallback. Returns (sebi_category, sebi_subcategory).

    Priority order — Index funds and FoFs MUST be detected before
    Equity sub-categories, because a "Nifty 50 Index Fund" contains
    the word "large cap" via its holdings but isn't a Large Cap fund.
    """
    name_lc = _normalise(name)
    if not name_lc:
        return None, None

    # ── International Fund (often "International FoF" — before generic FoF)
    if _INTL_TRIGGER.search(name_lc):
        return "International Fund", None

    # ── Index Fund / ETF (precedence over equity buckets) ──
    if _INDEX_TRIGGER.search(name_lc):
        subcat = None
        for pattern, label in _INDEX_INDEX_NAMES:
            if re.search(pattern, name_lc):
                subcat = label
                break

        # 2026-05-20 fallback: many AMFI / KFinTech names elide the "50"
        # ("UTI Nifty Index Fund" / "SBI Nifty Index Fund" in practice
        # track Nifty 50). If we couldn't pin a specific tracked index
        # but the name has "nifty" + "index", default to "Nifty 50" —
        # the canonical large-cap index and the most likely target.
        # Without this, these funds get None sub-category and
        # _sebi_buckets_match drops them, which makes them silently
        # disappear from duplicate detection.
        if subcat is None and re.search(r"\bnifty\b", name_lc) and re.search(r"\bindex\b", name_lc):
            subcat = "Nifty 50"
        # "Sensex Index" without a number → BSE Sensex
        elif subcat is None and re.search(r"\bsensex\b", name_lc):
            subcat = "Sensex"

        return "Index Fund", subcat

    if _GOLD_TRIGGER.search(name_lc):
        return "Gold ETF", None

    if _FOF_TRIGGER.search(name_lc):
        return "Fund of Funds", None

    sol = _match_first(name_lc, _SOLUTION_PATTERNS)
    if sol:
        return sol, None

    hyb = _match_first(name_lc, _HYBRID_PATTERNS)
    if hyb:
        return hyb, None

    dbt = _match_first(name_lc, _DEBT_PATTERNS)
    if dbt:
        return dbt, None

    eqt = _match_first(name_lc, _EQUITY_PATTERNS)
    if eqt:
        return eqt, None

    sec = _match_first(name_lc, _SECTORAL_PATTERNS)
    if sec:
        return "Sectoral/Thematic", sec

    return None, None


# ── NIDP scheme_category normaliser ──────────────────────────────────
_SCHEME_CATEGORY_REWRITES: List[Tuple[str, str]] = [
    (r"\blarge\s*&?\s*mid\s*cap\b",       "Large & Mid Cap"),
    (r"\blarge\s*cap\b",                  "Large Cap"),
    (r"\bmid\s*cap\b",                    "Mid Cap"),
    (r"\bsmall\s*cap\b",                  "Small Cap"),
    (r"\bmulti[\s-]?cap\b",               "Multi Cap"),
    (r"\bflexi[\s-]?cap\b",               "Flexi Cap"),
    (r"\bfocus(ed)?\b",                   "Focused Fund"),
    (r"\bvalue\b",                        "Value Fund"),
    (r"\bcontra\b",                       "Contra Fund"),
    (r"\belss\b|tax\s*saver",             "ELSS"),
    (r"\bdividend\s*yield\b",             "Dividend Yield"),
    (r"\bindex\s*fund|index\s*funds?/etf", "Index Fund"),
    (r"\bgold\s*etf|gold\s*fund\b",       "Gold ETF"),
    (r"\bfund\s*of\s*funds?\b|\bfof\b",   "Fund of Funds"),
    (r"\binternational\b|\bglobal\b|\boverseas\b", "International Fund"),
    (r"\baggressive\s*hybrid\b",          "Aggressive Hybrid"),
    (r"\bbalanced\s*advantage\b|baf\b",   "Balanced Advantage"),
    (r"\bequity\s*savings?\b",            "Equity Savings"),
    (r"\bmulti[\s-]?asset\b",             "Multi Asset Allocation"),
    (r"\barbitrage\b",                    "Arbitrage"),
    (r"\bconservative\s*hybrid\b",        "Conservative Hybrid"),
    (r"\bbalanced\s*hybrid\b|\bbalanced\s*fund\b", "Balanced Hybrid"),
    (r"\bliquid\b",                       "Liquid"),
    (r"\bultra\s*short",                  "Ultra Short Duration"),
    (r"\blow\s*duration\b",               "Low Duration"),
    (r"\bmoney\s*market\b",               "Money Market"),
    (r"\bcorporate\s*bond\b",             "Corporate Bond"),
    (r"\bbanking\s*&?\s*psu\b",           "Banking & PSU"),
    # Order: 10Y constant beats plain Gilt
    (r"\bgilt.*\b10\s*y\b|\bconstant\s+maturity\s+gilt\b", "Gilt 10Y Constant"),
    (r"\bgilt\b",                         "Gilt"),
    (r"\bdynamic\s*bond\b",               "Dynamic Bond"),
    (r"\bcredit\s*risk\b",                "Credit Risk"),
    (r"\bovernight\b",                    "Overnight"),
    (r"\bmedium\s+to\s+long",             "Medium to Long Duration"),
    (r"\bmedium\s+duration\b",            "Medium Duration"),
    (r"\bshort\s+duration\b",             "Short Duration"),
    (r"\blong\s+duration\b",              "Long Duration"),
    (r"\bfloater\b|\bfloating\s+rate\b",  "Floater"),
    (r"\bretirement\b",                   "Retirement Fund"),
    (r"\bchildren\b",                     "Children's Fund"),
    (r"\bsector\b|\bthematic\b",          "Sectoral/Thematic"),
]


def normalise_scheme_category(raw: Optional[str], fund_name: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    """Take a raw scheme_category string from NIDP and produce
    (sebi_category, sebi_subcategory). For Index Funds + Sectoral
    categories, calls the name-parser to extract the sub-category."""
    if not raw:
        return None, None
    raw_lc = _normalise(raw)
    cat: Optional[str] = None
    for pattern, label in _SCHEME_CATEGORY_REWRITES:
        if re.search(pattern, raw_lc):
            cat = label
            break

    subcat: Optional[str] = None
    if cat == "Index Fund" and fund_name:
        _, subcat = parse_sebi_from_name(fund_name)
    elif cat == "Sectoral/Thematic" and fund_name:
        _, subcat = parse_sebi_from_name(fund_name)

    return cat, subcat


# ── Public API ───────────────────────────────────────────────────────
def enrich_mf_with_sebi_category(holdings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Mutates each holding dict in place — sets `sebi_category` and
    `sebi_subcategory` for every `asset_type == "mutual_fund"` holding.

    Idempotent — runs that find an existing `sebi_category` skip the
    holding. Source preference per holding:
      1. holding["scheme_category"] (NIDP-populated)
      2. holding["category"]        (older path)
      3. Name-parser fallback on holding["name"]
    """
    for h in holdings:
        if (h.get("asset_type") or "").lower() not in ("mutual_fund", "mf", "etf"):
            continue
        if h.get("sebi_category"):
            continue

        name = h.get("name") or ""

        cat, subcat = normalise_scheme_category(h.get("scheme_category"), name)
        if not cat:
            cat, subcat = normalise_scheme_category(h.get("category"), name)
        if not cat:
            cat, subcat = parse_sebi_from_name(name)

        h["sebi_category"] = cat
        h["sebi_subcategory"] = subcat

    return holdings
