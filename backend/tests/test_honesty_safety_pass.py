"""Honesty + safety pass: the four defects found by the PRD gap analysis, pinned.

Each test fails against the code as it stood before this change. They are grouped by defect so a
regression names the thing that came back, not just a file.
"""
from __future__ import annotations

import inspect
from datetime import date
from typing import Any, Dict, List, Optional

import pytest

from services import desk_strategy_trades as strat
from services import desk_trading as desk


# ── Defect 1: fabricated sector data served as sourced data ─────────────────

def test_sector_rotation_has_no_hardcoded_fallback():
    """copilot_widgets substituted eight invented sectors when upstream was empty and stamped them
    source=["NIDP","NSE"] at confidence 80. CONTEXT.md: mock data is loud or it's a lie."""
    from routes import copilot_widgets

    src = inspect.getsource(copilot_widgets)
    for invented in ('SectorPoint(name="Banking", quadrant="Leading", rs_score=62',
                     'SectorPoint(name="Realty"', 'rs_score=38'):
        assert invented not in src, f"the fabricated sector fallback is back: {invented}"


def test_freshness_can_say_unavailable():
    """A widget with no reading must be able to say so rather than claim 'cached'."""
    from models_copilot_widgets import FreshnessChip

    chip = FreshnessChip(state="unavailable", source=[])
    assert chip.state == "unavailable"
    assert chip.source == []


# ── Defect 2: derivatives invisible to the risk governor ────────────────────

def _opt(side: str, strike: float, price: float, lots: int = 1, size: int = 50) -> Dict[str, Any]:
    return {"kind": "option", "side": side, "lots": lots, "lot_size": size, "entry_price": price,
            "expiry": "2026-11-24", "strike": strike, "option_type": "put", "price_source": "test"}


def test_exposure_of_a_vertical_is_bounded_by_the_strike_span():
    """A bear put spread's worst case is the span less the credit, so the span x quantity is a true
    upper bound. The governor must see a number, not nothing."""
    doc = {"legs": [_opt("buy", 2800, 60.0), _opt("sell", 2700, 25.0)]}
    assert strat.exposure_rs(doc) == pytest.approx((2800 - 2700) * 50)


def test_exposure_of_a_single_bought_option_is_the_premium():
    """check_defined_risk forbids naked shorts, so one option leg is always bought and the premium
    paid is the whole risk."""
    doc = {"legs": [_opt("buy", 2800, 60.0, lots=2, size=50)]}
    assert strat.exposure_rs(doc) == pytest.approx(60.0 * 2 * 50)


def test_exposure_counts_a_futures_leg_at_full_notional():
    """A futures loss is limited only by the price reaching zero, so notional is the honest measure."""
    doc = {"legs": [{"kind": "future", "side": "buy", "lots": 1, "lot_size": 25,
                     "entry_price": 1000.0, "expiry": "2026-11-24", "strike": None,
                     "option_type": None, "price_source": "test"}]}
    assert strat.exposure_rs(doc) == pytest.approx(25_000.0)


def test_exposure_is_none_when_a_leg_cannot_be_measured():
    """None must mean 'unknown' so the caller can refuse. Returning 0 would hide the position, which
    is the defect this whole fix exists to remove."""
    assert strat.exposure_rs({"legs": [_opt("buy", 2800, 60.0) | {"lot_size": None}]}) is None
    assert strat.exposure_rs({"legs": [_opt("buy", 2800, 60.0), _opt("sell", None, 25.0)]}) is None


def test_the_risk_book_no_longer_filters_strategies_out():
    """_portfolio kept only kind in (None, "cash"); strategy trades are stored with kind="strategy",
    so every F&O position was invisible and the book read as empty with a full risk budget."""
    # Phase 1: the book moved to services/risk_book.py (shared by every entry path); it reads strategies too and
    # measures an unreserved one by its exposure.
    from services import risk_book

    src = inspect.getsource(risk_book.read) + inspect.getsource(risk_book.legacy_estimate)
    # Cash and structures are split to be MARKED differently, never to drop the structures.
    assert 'struct_docs = [d for d in open_docs + recent_closed if d.get("kind") == strat.KIND]' in src
    assert "structure_value(" in src and "exposure_rs" in src
    assert 'p["kind"] == "strategy"' in inspect.getsource(risk_book.governor_positions)


# ── Defect 3: paper fills that cannot lose to a gap ─────────────────────────

def _bar(day: str, o: Optional[float], h: float, l: float, c: float) -> Dict[str, Any]:
    return {"date": date.fromisoformat(day), "open": o, "high": h, "low": l, "close": c}


def _trade(**over: Any) -> Dict[str, Any]:
    t = {"symbol": "FIXA", "quantity": 10, "entry_price": 100.0, "stop_price": 95.0,
         "target_price": 110.0, "entry_rule": "at_once", "entry_window_sessions": None,
         "max_hold_sessions": None, "opened_at": "2026-10-01T04:00:00+00:00"}
    t.update(over)
    return t


def test_a_stop_gapped_through_fills_at_the_open_not_the_stop():
    """The session opened at 90, below the 95 stop: the price never traded at 95. Filling at the stop
    made a paper stop-loss incapable of losing to a gap, and the promotion gates read these numbers."""
    bars = [_bar("2026-10-01", 100.0, 101.0, 99.0, 100.0),
            _bar("2026-10-02", 90.0, 92.0, 88.0, 89.0)]
    out = desk.simulate(_trade(), bars)
    assert out["exit"]["exit_reason"] == "stop"
    assert out["exit"]["exit_price"] == pytest.approx(90.0), "the fill must be the open, not the stop"
    codes = {f["code"] for f in out["flags"]}
    assert "gap_through_stop" in codes


def test_a_stop_touched_intraday_still_fills_at_the_stop():
    """The opposite case must not regress: the price traded through 95 during the session, so the
    stop is a real fill."""
    bars = [_bar("2026-10-01", 100.0, 101.0, 99.0, 100.0),
            _bar("2026-10-02", 99.0, 100.0, 94.0, 96.0)]
    out = desk.simulate(_trade(), bars)
    assert out["exit"]["exit_price"] == pytest.approx(95.0)
    assert "gap_through_stop" not in {f["code"] for f in out["flags"]}


def test_an_entry_gapped_through_fills_at_the_open_not_the_trigger():
    """Same defect on the entry side: the flag said a real order would fill near the open while the
    code recorded the trigger price."""
    bars = [_bar("2026-10-01", 100.0, 101.0, 99.0, 100.0),
            _bar("2026-10-02", 104.0, 106.0, 103.0, 105.0)]
    out = desk.simulate(_trade(entry_rule="break_above", entry_price=102.0, stop_price=95.0,
                               target_price=130.0), bars)
    assert out["entry_status"] == "reached"
    assert out["sim_entry_price"] == pytest.approx(104.0), "the fill must be the open, not the trigger"
    assert "entry_gap" in {f["code"] for f in out["flags"]}


# ── Defect 4: a false statement shown to users ──────────────────────────────

def test_disabled_patterns_do_not_claim_no_detector_exists():
    """pattern_registry told users "no detector implemented; specification only" for 16 families whose
    geometry engines exist and pass their own tests, and research_chart serves that string verbatim."""
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from research.charting import pattern_registry as reg

    reasons = {f.disabled_reason for f in reg.FAMILIES if f.disabled_reason}
    assert reasons, "the disabled families must still say why"
    for r in reasons:
        assert "no detector implemented" not in r, f"the false reason is back: {r!r}"
