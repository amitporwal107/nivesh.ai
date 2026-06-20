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


def test_same_fund_not_double_counted():
    """If the same scheme appears twice (e.g. two folios of one fund), the name
    is deduped so chips never repeat the identical scheme."""
    dup = "Mirae Asset Large Cap Fund Direct Growth"
    holdings = [_mf(dup, "INF020", qty=500), _mf(dup, "INF020", qty=700)]
    look = {"INF020": _look(("ICICI Bank Ltd", "Financials", 6.0))}
    env = compute_concentration(holdings, fund_lookthrough=look)
    top = env["company"]["items"][0]

    assert "ICICI Bank" in top["name"]
    assert top["fund_names"] == [dup]             # deduped to one


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
