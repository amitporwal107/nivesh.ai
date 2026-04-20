"""Unit tests for deterministic insights builder — enforces no-hallucination
contract (every percentage must be ≤100, every ₹ grounded in real holdings).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from routes.insights import _deterministic_insights  # noqa: E402
from services import rules_config  # noqa: E402


def _h(name, price, qty=1000, sector=None, asset_type="mutual_fund", buy_price=None):
    return {
        "user_id": "u1", "name": name, "quantity": qty,
        "current_price": price, "buy_price": buy_price or price * 0.8,
        "asset_type": asset_type, "sector": sector,
    }


def test_no_percentage_exceeds_100_ever():
    """The hallucination bug was 818% Pharma. Regardless of inputs, every
    percentage emitted must be ≤100 (clamp applied in builder)."""
    # Extreme skew portfolio — all 10 holdings in HDFC Pharma
    holdings = [_h(f"HDFC Pharma Fund - Regular Growth {i}", 100, sector="Pharma") for i in range(10)]
    out = _deterministic_insights(holdings, None, None, rules_config.DEFAULTS)
    for ins in out["insights"]:
        for field in ("current_value", "target_value"):
            v = ins.get(field, "")
            import re
            for n in re.findall(r"(\d+(?:\.\d+)?)\s*%", str(v)):
                assert float(n) <= 100.0, f"pct > 100 in {field}: {v}"
        desc = ins.get("description", "")
        for n in re.findall(r"(\d+(?:\.\d+)?)\s*%", desc):
            assert float(n) <= 100.0, f"pct > 100 in description: {desc}"


def test_grounds_numbers_in_actual_holdings():
    """Total values cited must come from real holdings — no fabrication."""
    holdings = [
        _h("HDFC Large Cap Fund - Regular Growth", 100, qty=10000, sector="Financial"),
        _h("HDFC Mid Cap Fund - Regular Growth", 100, qty=5000, sector="Financial"),
    ]
    out = _deterministic_insights(holdings, None, None, rules_config.DEFAULTS)
    # Total = 15L. Both are HDFC so AMC = 100% — insight must cite "100.0%"
    # (clamped, never above). Actually since both are ₹15L total, AMC=100%.
    found_amc = [i for i in out["insights"] if "HDFC" in i["title"] and "AMC" in i["title"]]
    assert len(found_amc) == 1
    import re
    pcts = re.findall(r"(\d+(?:\.\d+)?)\s*%", found_amc[0]["description"])
    # Must cite ~100% for the AMC, not some fabricated fraction
    assert any(float(p) >= 95.0 and float(p) <= 100.0 for p in pcts), pcts


def test_rule_2b_fires_when_category_over_35():
    """Feed 100% Mid Cap via intelligence — expect warning insight."""
    holdings = [_h("DSP Midcap Fund", 100, qty=1000, sector="Other")]
    intel = {
        "mf_investments": [
            {"scheme_name": "DSP Midcap Fund", "amount_rs": 100000, "category": "Mid Cap"},
        ]
    }
    out = _deterministic_insights(holdings, None, None, rules_config.DEFAULTS, intelligence=intel)
    warnings = [i for i in out["insights"] if i["category"] == "allocation" and i["type"] == "warning"]
    assert any("Mid Cap" in i["title"] for i in warnings), (
        f"Expected Mid Cap warning; got: {[i['title'] for i in out['insights']]}"
    )


def test_heads_up_insight_appears_when_category_25_to_35():
    """Largest category between 25% and 35% should produce an info-tier insight."""
    holdings = [_h(f"Fund {i}", 100, qty=1000, sector="Other") for i in range(4)]
    intel = {
        "mf_investments": [
            {"scheme_name": "Fund 0", "amount_rs": 30000, "category": "Large Cap"},
            {"scheme_name": "Fund 1", "amount_rs": 25000, "category": "Flexi Cap"},
            {"scheme_name": "Fund 2", "amount_rs": 25000, "category": "Small Cap"},
            {"scheme_name": "Fund 3", "amount_rs": 20000, "category": "Value"},
        ]
    }
    out = _deterministic_insights(holdings, None, None, rules_config.DEFAULTS, intelligence=intel)
    info = [i for i in out["insights"]
            if i["category"] == "allocation" and i["type"] == "info" and "Large Cap" in i["title"]]
    assert len(info) == 1


def test_no_insights_for_clean_portfolio():
    """Balanced portfolio with no threshold breaches should produce minimal output."""
    holdings = [
        _h(f"{amc} Fund - Direct Growth", 100, qty=500, sector="Other")
        for amc in ["HDFC", "ICICI", "SBI", "Axis", "Kotak", "Nippon", "UTI"]
    ]
    # 7 AMCs, 14.3% each — all below 15% threshold
    # Also add small debt
    holdings.append(_h("SBI Debt Fund - Direct", 100, qty=100, sector="Debt", asset_type="bond"))
    out = _deterministic_insights(holdings, None, None, rules_config.DEFAULTS)
    # Should have NO AMC warnings (all <15%), NO cost leak (no regular funds),
    # possibly still a debt-gap warning (debt is tiny)
    amc_warnings = [i for i in out["insights"] if "AMC concentration" in i["title"]]
    assert len(amc_warnings) == 0
