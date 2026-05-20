"""Unit tests for tax_engine.card_tax_block — the contract consumed by
the Performance & Benchmark dashboard's Action Matrix (Tax Watch bucket
and inline STCG/LTCG badges).

Covers the user-visible failure modes the dashboard must handle gracefully:

  1. Missing buy_date → block returns UNKNOWN (or proxy) without crashing.
  2. Loss-state holding → is_loss=True so the UI shows a "Loss" badge
     (harvestable, no STCG cost on exit).
  3. STCG-soon (days_to_ltcg in 0..60) → days_to_ltcg correct; powers the
     "LTCG in Nd" amber badge.
  4. Already LTCG-eligible → days_to_ltcg == 0; no badge fires.
  5. Recently-bought STCG with gain → STCG tier + days_to_ltcg > 60.
"""
import sys
import types
from datetime import datetime, timedelta, timezone

# Stub heavyweight transitive deps so this unit test stays pure-Python.
# tax_engine imports `from deps import db`, and deps.py wires up FastAPI,
# Mongo and the LLM client — none of which `card_tax_block` actually uses.
if "deps" not in sys.modules:
    deps_stub = types.ModuleType("deps")
    deps_stub.db = None  # noqa: E501 — placeholder; card_tax_block never touches db
    sys.modules["deps"] = deps_stub

from services.tax_engine import card_tax_block  # noqa: E402


def _holding(days_ago: int | None, asset_type: str = "equity",
             buy_price: float = 100.0, current_price: float = 120.0,
             name: str = "Test Fund") -> dict:
    h: dict = {
        "name": name,
        "asset_type": asset_type,
        "buy_price": buy_price,
        "current_price": current_price,
        "quantity": 10,
    }
    if days_ago is not None:
        h["buy_date"] = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return h


def test_missing_buy_date_returns_unknown_block():
    h = _holding(days_ago=None)
    block = card_tax_block(h, invested=1000.0, current_value=1200.0)
    assert block is not None
    # No buy_date + no proxy timestamp → UNKNOWN, but block must still be valid
    assert block["tier"] == "UNKNOWN"
    assert block["days_held"] is None
    assert block["is_loss"] is False


def test_loss_state_flags_is_loss():
    # Recently bought, current price below buy price
    h = _holding(days_ago=30, buy_price=100, current_price=80)
    block = card_tax_block(h, invested=1000.0, current_value=800.0)
    assert block is not None
    assert block["is_loss"] is True
    assert block["tier"] == "LIKELY_STCG"


def test_stcg_approaching_ltcg_threshold():
    # Equity held 320 days — 45 days away from 365d LTCG threshold
    h = _holding(days_ago=320)
    block = card_tax_block(h, invested=1000.0, current_value=1200.0)
    assert block is not None
    assert block["tier"] == "LIKELY_STCG"
    assert block["threshold_days"] == 365
    # 45 days remaining (±1 for clock drift)
    assert 43 <= block["days_to_ltcg"] <= 46
    assert block["is_loss"] is False


def test_already_ltcg_eligible():
    # Equity held 400 days
    h = _holding(days_ago=400)
    block = card_tax_block(h, invested=1000.0, current_value=1500.0)
    assert block is not None
    assert block["tier"] == "LIKELY_LTCG"
    # Past threshold → days_to_ltcg clamped to 0 (UI hides "wait N days" badge)
    assert block["days_to_ltcg"] == 0


def test_recently_bought_stcg_with_gain():
    # Equity held 60 days, big gain — classic STCG-tax-cost case
    h = _holding(days_ago=60, buy_price=100, current_price=130)
    block = card_tax_block(h, invested=1000.0, current_value=1300.0)
    assert block is not None
    assert block["tier"] == "LIKELY_STCG"
    assert block["days_to_ltcg"] > 60  # too far for "LTCG-soon" badge
    assert block["is_loss"] is False


def test_debt_fund_uses_longer_threshold():
    # Debt fund held 700 days — past equity 365d but still inside debt 1095d
    h = _holding(days_ago=700, asset_type="mutual_fund", name="ICICI Liquid Fund")
    block = card_tax_block(h, invested=1000.0, current_value=1100.0)
    assert block is not None
    assert block["threshold_days"] == 1095
    assert block["tier"] == "LIKELY_STCG"
