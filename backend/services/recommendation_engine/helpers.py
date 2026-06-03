"""
Pure helper functions shared by multiple engines.

These are standalone (no I/O, no class state) versions of methods that
previously lived as instance methods on ActionPlanManager. Engines import
from here; the old code in action_plan_manager.py is unchanged (Phase 4
will clean it up after the legacy rule body is removed).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


_KNOWN_SINGLE_AMCS = {
    "HDFC", "ICICI", "SBI", "AXIS", "KOTAK",
    "NIPPON", "FRANKLIN", "TEMPLETON", "MIRAE",
    "DSP", "TATA", "UTI", "INVESCO", "HSBC", "IDFC",
    "SUNDARAM", "MOTILAL", "EDELWEISS", "BARODA",
    "CANARA", "BANDHAN", "UNION", "BOI", "QUANTUM",
}

_CATEGORY_PATTERNS = [
    ("LARGE & MID CAP",    "Large & Mid Cap"),
    ("LARGE AND MID",      "Large & Mid Cap"),
    ("MID CAP",            "Mid Cap"),
    ("MIDCAP",             "Mid Cap"),
    ("SMALL CAP",          "Small Cap"),
    ("SMALLCAP",           "Small Cap"),
    ("LARGE CAP",          "Large Cap"),
    ("LARGECAP",           "Large Cap"),
    ("BLUECHIP",           "Large Cap"),
    ("FLEXI CAP",          "Flexi Cap"),
    ("FLEXICAP",           "Flexi Cap"),
    ("MULTI CAP",          "Multi Cap"),
    ("MULTICAP",           "Multi Cap"),
    ("FOCUSED",            "Focused"),
    ("VALUE",              "Value Oriented"),
    ("CONTRA",             "Contra"),
    ("ELSS",               "ELSS"),
    ("TAX SAV",            "ELSS"),
    ("INDEX",              "Index"),
    ("NIFTY",              "Index"),
    ("SENSEX",             "Index"),
    ("BALANCED ADVANTAGE", "Dynamic Asset Allocation"),
    ("BALANCED",           "Hybrid"),
    ("HYBRID",             "Hybrid"),
    ("AGGRESSIVE HYBRID",  "Hybrid"),
    ("CONSERVATIVE HYBRID","Hybrid"),
    ("ARBITRAGE",          "Arbitrage"),
    ("LIQUID",             "Liquid"),
    ("OVERNIGHT",          "Liquid"),
    ("GILT",               "Gilt"),
    ("CORPORATE BOND",     "Corporate Bond"),
    ("CREDIT RISK",        "Credit Risk"),
    ("SHORT DURATION",     "Short Duration"),
    ("MEDIUM DURATION",    "Medium Duration"),
    ("LONG DURATION",      "Long Duration"),
    ("ULTRA SHORT",        "Ultra Short Duration"),
    ("LOW DURATION",       "Low Duration"),
    ("MONEY MARKET",       "Money Market"),
    ("DEBT",               "Debt"),
    ("BOND",               "Debt"),
    ("GOLD",               "Gold"),
    ("SILVER",             "Commodity"),
    ("PHARMA",             "Sectoral - Pharma"),
    ("BANKING",            "Sectoral - Banking"),
    ("TECH",               "Sectoral - IT"),
    ("INFRA",              "Sectoral - Infra"),
    ("FMCG",               "Sectoral - FMCG"),
    ("EMERGING",           "Thematic"),
    ("INTERNATIONAL",      "International"),
    ("GLOBAL",             "International"),
]


def normalize_fund_name(name: str) -> str:
    """Lowercase, strip punctuation, remove broker/CAS prefixes and parentheticals."""
    n = name.lower()
    n = re.sub(r"\([^)]*\)", " ", n)
    n = n.replace(",", " ").replace("-", " ")
    n = re.sub(r"^\s*\b[a-z]{2,5}\b\s+(?=[a-z])", "", n)
    return " ".join(n.split())


def fuzzy_match_holding(
    scheme_name: str, holdings: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Find the Mongo holding whose name best matches a PG scheme_name."""
    if not scheme_name:
        return None
    target = normalize_fund_name(scheme_name)
    if not target:
        return None
    for h in holdings:
        if normalize_fund_name(h.get("name", "")) == target:
            return h
    t_tokens = set(target.split())
    if not t_tokens:
        return None
    best, best_score = None, 0.0
    for h in holdings:
        hn = normalize_fund_name(h.get("name", ""))
        if not hn:
            continue
        common = t_tokens & set(hn.split())
        score = len(common) / max(len(t_tokens), 1)
        if score >= 0.6 and score > best_score:
            best, best_score = h, score
    return best


def extract_amc_from_name(name: str) -> Optional[str]:
    """Extract AMC identifier from a fund scheme name."""
    if not name:
        return None
    words = name.upper().split()
    for word in words:
        if word in _KNOWN_SINGLE_AMCS:
            return word
    if "ADITYA" in words and "BIRLA" in words:
        return "ADITYA BIRLA"
    if "PARAG" in words and "PARIKH" in words:
        return "PARAG PARIKH"
    if "L" in words and "T" in words:
        if abs(words.index("L") - words.index("T")) == 1:
            return "L&T"
    return None


def infer_category_from_name(name: str) -> Optional[str]:
    """Best-effort SEBI category from scheme name. Returns None for ambiguous names."""
    if not name:
        return None
    n = name.upper()
    for pat, out in _CATEGORY_PATTERNS:
        if pat in n:
            return out
    return None


def classify_plan_type(name: str) -> str:
    """Return 'direct' or 'regular' from fund scheme name."""
    if not name:
        return "regular"
    lowered = name.lower()
    direct_phrases = [
        "direct plan", "direct growth", "direct - growth", "- direct -",
        "- direct", "(direct)", "dir plan", "dir growth",
    ]
    if any(p in lowered for p in direct_phrases):
        return "direct"
    tokens = lowered.replace(",", " ").replace("-", " ").replace("(", " ").replace(")", " ").split()
    if "direct" in tokens or "dir" in tokens:
        return "direct"
    return "regular"


def normalize_base_scheme_name(name: str) -> str:
    """Strip plan-type/option keywords to get the canonical base scheme name.

    Example: "HDFC Flexi Cap Fund - Direct Plan - Growth" → "hdfc flexi cap fund"
    """
    if not name:
        return ""
    stop_tokens = {
        "direct", "regular", "growth", "idcw", "dividend",
        "payout", "reinvestment", "plan", "option", "div",
        "g", "d", "dir", "reg",
    }
    cleaned = (
        name.lower()
        .replace(",", " ").replace("-", " ")
        .replace("(", " ").replace(")", " ")
    )
    return " ".join(t for t in cleaned.split() if t and t not in stop_tokens).strip()


def calc_amc_exposure(
    mf_investments: List[Dict[str, Any]], total_portfolio_value: float
) -> Dict[str, float]:
    """Return {AMC: pct_of_total_portfolio} from MF investment list."""
    if not total_portfolio_value:
        return {}
    amc_values: Dict[str, float] = {}
    for mf in mf_investments:
        amc = extract_amc_from_name(mf.get("scheme_name", ""))
        if amc:
            amc_values[amc] = amc_values.get(amc, 0.0) + float(mf.get("amount_rs") or 0)
    return {
        amc: round(val / total_portfolio_value * 100, 2)
        for amc, val in amc_values.items()
    }
