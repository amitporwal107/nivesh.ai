"""Reconciliation-style tests for the look-through `fund_names` field that
feeds the "Most-Owned Stock" widget (PortfolioXray → FundChips).

The widget used to render dummy "Fund 1 … Fund N" chips because the backend
only emitted a *count* (`via_funds_count`), never which funds held the stock.
`compute_concentration` now also emits `fund_names` — the deduped scheme names
of the user's MF holdings that contain each underlying company.

These tests assert the contract the frontend relies on, and exercise the real
production failure modes (blank / duplicate / garbled holding names) the chip
fallback has to survive — deterministic assertions only, no network.
"""
from services.portfolio_concentration import compute_concentration


def _mf(name, ticker, qty=1000, price=100):
    return {"name": name, "ticker": ticker, "asset_type": "mutual_fund",
            "quantity": qty, "current_price": price}


def _hdfc_look():
    return _look(("HDFC Bank Ltd", "Financials", 7.0))


def _look(*companies):
    """companies: list of (name, sector, pct)."""
    return {"holdings": [{"name": n, "sector": s, "pct": p} for n, s, p in companies]}


def test_fund_names_match_count_and_are_real():
    """The top stock held across two funds reports both real scheme names,
    and len(fund_names) reconciles exactly to via_funds_count."""
    holdings = [
        _mf("Acme Bluechip Fund Direct Growth", "INF001"),
        _mf("Zen Largecap Fund Direct Growth", "INF002"),
    ]
    look = {
        "INF001": _look(("HDFC Bank Ltd", "Financials", 8.0), ("Infosys Ltd", "IT", 5.0)),
        "INF002": _look(("HDFC Bank Ltd", "Financials", 6.0), ("TCS Ltd", "IT", 4.0)),
    }
    env = compute_concentration(holdings, fund_lookthrough=look)
    top = env["company"]["items"][0]

    assert "HDFC Bank" in top["name"]
    assert top["via_funds_count"] == 2
    assert top["fund_names"] == [
        "Acme Bluechip Fund Direct Growth",
        "Zen Largecap Fund Direct Growth",
    ]
    # The exact invariant the frontend depends on: one real chip per fund.
    assert len(top["fund_names"]) == top["via_funds_count"]


def test_blank_holding_name_falls_back_without_breaking_count():
    """A real portfolio can carry an MF holding with an empty `name`.
    That fund must NOT contribute a blank chip, but it must still be counted —
    so the frontend (which fills count - len(names) with 'Fund N') stays honest."""
    holdings = [
        _mf("Parag Parikh Flexi Cap Fund Direct Growth", "INF010"),
        _mf("", "INF011"),  # garbled / missing scheme name in source data
    ]
    look = {
        "INF010": _look(("Reliance Industries Ltd", "Energy", 7.0)),
        "INF011": _look(("Reliance Industries Ltd", "Energy", 9.0)),
    }
    env = compute_concentration(holdings, fund_lookthrough=look)
    top = env["company"]["items"][0]

    assert "Reliance" in top["name"]
    assert top["via_funds_count"] == 2            # both funds counted
    assert top["fund_names"] == ["Parag Parikh Flexi Cap Fund Direct Growth"]
    # Frontend renders 1 real name + 1 numbered fallback chip = 2 chips total.
    assert len(top["fund_names"]) <= top["via_funds_count"]


def test_same_fund_multiple_folios_counts_once():
    """Same fund (same ticker) across two folios is ONE fund, not two — both
    the count and the chip collapse. This is the real bug: counting folios
    overstated "held across N funds" and orphaned the surplus chips."""
    dup = "Mirae Asset Large Cap Fund Direct Growth"
    holdings = [_mf(dup, "INF020", qty=500), _mf(dup, "INF020", qty=700)]
    look = {"INF020": _look(("ICICI Bank Ltd", "Financials", 6.0))}
    env = compute_concentration(holdings, fund_lookthrough=look)
    top = env["company"]["items"][0]

    assert "ICICI Bank" in top["name"]
    assert top["via_funds_count"] == 1
    assert top["fund_names"] == [dup]


def test_count_matches_named_chips_with_folios_and_collisions():
    """Mirrors the real portfolio: folios of one fund + two genuinely different
    funds that truncate to the same display name. via_funds_count must equal
    the number of name chips (no orphan 'Fund N'), counting distinct funds by
    ticker — so the two same-named-but-different-ticker funds both show."""
    holdings = [
        _mf("Parag Parikh Flexi Cap Fund Direct Growth", "INF100", qty=300),
        _mf("Parag Parikh Flexi Cap Fund Direct Growth", "INF100", qty=400),  # 2nd folio
        _mf("Nippon India", "INF200"),   # truncated name, distinct fund
        _mf("Nippon India", "INF201"),   # truncated name, DIFFERENT fund
    ]
    look = {k: _hdfc_look() for k in ("INF100", "INF200", "INF201")}
    env = compute_concentration(holdings, fund_lookthrough=look)
    top = env["company"]["items"][0]

    assert "HDFC Bank" in top["name"]
    # 3 distinct funds (1 Parag folio-collapsed + 2 distinct Nippon tickers)
    assert top["via_funds_count"] == 3
    # Every fund yields a real name → chips == count, zero numbered fallbacks.
    assert len(top["fund_names"]) == top["via_funds_count"]
    assert top["fund_names"].count("Nippon India") == 2  # distinct funds, same label


def test_direct_only_stock_has_empty_fund_names():
    """A directly-held equity (not inside any fund) carries no fund names and
    via_funds_count == 0 — the widget hides the chip row entirely in this case."""
    holdings = [
        {"name": "Tata Motors Ltd", "ticker": "TATAMOTORS", "asset_type": "equity",
         "quantity": 100, "current_price": 900, "sector": "Auto"},
    ]
    env = compute_concentration(holdings, fund_lookthrough={})
    top = env["company"]["items"][0]

    assert "Tata Motors" in top["name"]
    assert top["via_funds_count"] == 0
    assert top["fund_names"] == []
    assert top["fund_breakdown"] == []


def test_fund_breakdown_is_ranked_and_pct_sums_to_100():
    """The donut data: one slice per fund, sorted by ₹ exposure desc, pct as a
    share of the look-through total (slices sum to ~100%)."""
    # Fund A contributes more HDFC exposure than fund B (higher weight).
    holdings = [
        _mf("Big HDFC Holder Fund Direct", "INFA", qty=1000, price=100),   # ₹100k
        _mf("Small HDFC Holder Fund Direct", "INFB", qty=1000, price=100),  # ₹100k
    ]
    look = {
        "INFA": _look(("HDFC Bank Ltd", "Financials", 10.0)),  # ₹10k exposure
        "INFB": _look(("HDFC Bank Ltd", "Financials", 4.0)),   # ₹4k exposure
    }
    env = compute_concentration(holdings, fund_lookthrough=look)
    top = env["company"]["items"][0]
    bd = top["fund_breakdown"]

    assert [s["name"] for s in bd] == ["Big HDFC Holder Fund Direct",
                                       "Small HDFC Holder Fund Direct"]
    assert bd[0]["value_inr"] == 10000.0 and bd[1]["value_inr"] == 4000.0
    assert round(sum(s["pct"] for s in bd)) == 100


def test_fund_breakdown_caps_at_top_10_plus_others():
    """With >10 funds holding the stock, the donut shows the top 10 by exposure
    and rolls the remainder into a single 'Others (N funds)' slice."""
    holdings, look = [], {}
    for i in range(13):
        tk = f"INF{i:03d}"
        # Descending weights so fund i ranks at position i.
        holdings.append(_mf(f"Fund Number {i} Direct Growth", tk, qty=1000, price=100))
        look[tk] = _look(("HDFC Bank Ltd", "Financials", 13.0 - i))
    env = compute_concentration(holdings, fund_lookthrough=look)
    top = env["company"]["items"][0]
    bd = top["fund_breakdown"]

    assert top["via_funds_count"] == 13
    assert len(bd) == 11                       # 10 funds + 1 Others
    assert bd[-1]["name"] == "Others (3 funds)"
    assert bd[0]["name"] == "Fund Number 0 Direct Growth"   # highest weight
    assert round(sum(s["pct"] for s in bd)) == 100
