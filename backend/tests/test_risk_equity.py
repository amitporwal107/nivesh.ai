"""Drawdown: the limit the system advertised and never once checked.

`risk_governor.py:118-119` has always been able to halt on `portfolio.drawdown_pct`, and
`_portfolio()` never supplied one, so every evaluation reported DRAWDOWN_UNKNOWN and the 15% limit
was decoration. These cover the three things the Definition of Done asks for — threshold crossing,
recovery, and session reset — plus the property that matters more than any of them: an equity that
cannot be known says so instead of reading as "no drawdown".
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import pytest

from services import risk_equity as req
from services.ai_trader.risk_governor import DEFAULT_LIMITS, Intent, Market, Portfolio, evaluate


class FakeCollection:
    def __init__(self) -> None:
        self.docs: List[Dict[str, Any]] = []

    async def find_one(self, q):
        return next((d for d in self.docs if all(d.get(k) == v for k, v in q.items())), None)

    async def update_one(self, q, update, upsert=False):
        doc = await self.find_one(q)
        if doc is None:
            if not upsert:
                return
            doc = dict(update.get("$setOnInsert") or {})
            self.docs.append(doc)
        doc.update(update.get("$set") or {})


class FakeDB:
    def __init__(self) -> None:
        self.cols: Dict[str, FakeCollection] = {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, FakeCollection())


@pytest.fixture
def db():
    return FakeDB()


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def summary(realized=None, unrealized=None, unmarked=0):
    return {"net_realized_pnl_rs": realized, "net_unrealized_pnl_rs": unrealized,
            "unmarked_open": unmarked}


# ── equity ──────────────────────────────────────────────────────────────────

def test_equity_is_capital_plus_realised_plus_unrealised():
    assert req.equity_from(1_000_000, -20_000, 5_000, 0) == 985_000.0


def test_equity_is_unknown_when_any_open_position_is_unmarked():
    """A sum of marked and unmarked positions belongs to no portfolio, and the drawdown computed
    from it would understate the real one."""
    assert req.equity_from(1_000_000, -20_000, 5_000, 1) is None


def test_equity_is_unknown_without_positive_capital():
    assert req.equity_from(0, 0, 0, 0) is None
    assert req.equity_from(None, 0, 0, 0) is None


# ── the drawdown number ─────────────────────────────────────────────────────

def test_drawdown_is_measured_from_the_peak():
    assert req.drawdown_pct(900_000, 1_000_000) == 10.0


def test_at_or_above_the_peak_the_drawdown_is_zero_never_negative():
    assert req.drawdown_pct(1_000_000, 1_000_000) == 0.0
    assert req.drawdown_pct(1_200_000, 1_000_000) == 0.0


def test_an_unknown_side_gives_an_unknown_drawdown():
    assert req.drawdown_pct(None, 1_000_000) is None
    assert req.drawdown_pct(900_000, None) is None


# ── the peak is a high-water mark ───────────────────────────────────────────

def test_the_peak_rises_with_equity(db):
    run(req.observe(db, "u1", 1_000_000))
    assert run(req.observe(db, "u1", 1_100_000)) == 1_100_000


def test_the_peak_never_falls(db):
    run(req.observe(db, "u1", 1_100_000))
    assert run(req.observe(db, "u1", 900_000)) == 1_100_000, "a peak that drops hides the drawdown"


def test_an_unknown_equity_does_not_reset_the_peak(db):
    """A session where the marks were missing must not quietly reset the mark a real drawdown is
    measured against."""
    run(req.observe(db, "u1", 1_100_000))
    assert run(req.observe(db, "u1", None)) == 1_100_000


# ── the DoD: crossing, recovery ─────────────────────────────────────────────

def _intent():
    return Intent(symbol="TCS", quantity=1, entry_price=100.0, stop_price=95.0,
                  target_price=110.0, sector="IT")


def _codes(portfolio):
    return [r.code for r in evaluate(_intent(), portfolio, Market(vix=12.0), DEFAULT_LIMITS).reasons]


def test_crossing_the_threshold_halts(db):
    """15% is the default limit; 16% below the peak must halt and approve nothing."""
    run(req.observe(db, "u1", 1_000_000))
    snap = run(req.snapshot(db, "u1", 1_000_000, summary(realized=-160_000, unrealized=0)))
    assert snap["drawdown_pct"] == pytest.approx(16.0)
    p = Portfolio(capital=1_000_000, positions=[], drawdown_pct=snap["drawdown_pct"])
    d = evaluate(_intent(), p, Market(vix=12.0), DEFAULT_LIMITS)
    assert "DRAWDOWN_HALT" in [r.code for r in d.reasons]
    assert d.approved_qty == 0, d.to_dict()


def test_just_under_the_threshold_does_not_halt(db):
    run(req.observe(db, "u1", 1_000_000))
    snap = run(req.snapshot(db, "u1", 1_000_000, summary(realized=-140_000, unrealized=0)))
    assert snap["drawdown_pct"] == pytest.approx(14.0)
    assert "DRAWDOWN_HALT" not in _codes(Portfolio(capital=1_000_000, positions=[],
                                                   drawdown_pct=snap["drawdown_pct"]))


def test_recovery_clears_the_halt_but_the_peak_stands(db):
    run(req.observe(db, "u1", 1_000_000))
    run(req.snapshot(db, "u1", 1_000_000, summary(realized=-160_000)))          # halted
    back = run(req.snapshot(db, "u1", 1_000_000, summary(realized=-50_000)))    # recovered to 950k
    assert back["peak_equity"] == 1_000_000, "recovery must not lower the peak"
    assert back["drawdown_pct"] == pytest.approx(5.0)
    assert "DRAWDOWN_HALT" not in _codes(Portfolio(capital=1_000_000, positions=[],
                                                   drawdown_pct=back["drawdown_pct"]))


def test_a_new_high_resets_the_drawdown_to_zero(db):
    run(req.observe(db, "u1", 1_000_000))
    run(req.snapshot(db, "u1", 1_000_000, summary(realized=-160_000)))
    high = run(req.snapshot(db, "u1", 1_000_000, summary(realized=200_000)))
    assert high["peak_equity"] == 1_200_000 and high["drawdown_pct"] == 0.0


def test_an_unmarked_position_makes_the_drawdown_unknown_not_zero(db):
    run(req.observe(db, "u1", 1_000_000))
    snap = run(req.snapshot(db, "u1", 1_000_000, summary(realized=-160_000, unmarked=1)))
    assert snap["equity"] is None and snap["drawdown_pct"] is None
    assert "could not be marked" in snap["unknown_reason"]
    codes = _codes(Portfolio(capital=1_000_000, positions=[], drawdown_pct=None))
    assert "DRAWDOWN_UNKNOWN" in codes and "DRAWDOWN_HALT" not in codes


# ── the DoD: session reset (the DAILY loss limit, which already worked) ─────

def test_the_daily_loss_limit_halts_and_is_a_separate_control():
    """`realized_pnl_today` is summed over trades closed TODAY in IST by _portfolio, so this limit
    resets with the session. Pinned here because the Definition of Done asks for it, and because it
    is a different control from the drawdown: one is intraday, one is peak-to-trough."""
    p = Portfolio(capital=1_000_000, positions=[], realized_pnl_today=-40_000, drawdown_pct=0.0)
    codes = _codes(p)
    assert "DAILY_LOSS_HALT" in codes          # -4% against a 3% limit
    assert "DRAWDOWN_HALT" not in codes


def test_a_fresh_session_has_no_daily_loss_halt():
    """The reset itself: yesterday's loss is not in realized_pnl_today, so a new session starts clean
    even though the drawdown from the peak is unchanged."""
    p = Portfolio(capital=1_000_000, positions=[], realized_pnl_today=0.0, drawdown_pct=4.0)
    codes = _codes(p)
    assert "DAILY_LOSS_HALT" not in codes
    assert "DRAWDOWN_HALT" not in codes        # 4% is under the 15% limit


def test_the_two_halts_are_independent():
    both = Portfolio(capital=1_000_000, positions=[], realized_pnl_today=-40_000, drawdown_pct=20.0)
    codes = _codes(both)
    assert "DAILY_LOSS_HALT" in codes and "DRAWDOWN_HALT" in codes
