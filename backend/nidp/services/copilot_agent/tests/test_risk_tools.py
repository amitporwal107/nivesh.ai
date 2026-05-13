"""TASK-041 integration tests: Risk suitability + VaR tools.

Tests:
  1. get_risk_suitability — rating, misalignment detection, profile alignment
  2. get_portfolio_var — VaR arithmetic, confidence levels, MF vol proxy, zero-value guard
  3. RiskResult.as_llm_context format

Run from /app/backend:
    PYTHONPATH=. python3 -m pytest nidp/services/copilot_agent/tests/test_risk_tools.py -v
"""
from __future__ import annotations

import asyncio
import math
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Stub deps (DB + DAAS) ─────────────────────────────────────────────────────

_HOLDINGS: list = []
_USER_PROFILE: dict = {}
_VOL_MAP: dict = {}   # symbol → float daily vol


class _AsyncIter:
    def __init__(self, items):
        self._it = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


def _make_db_stub():
    stub = types.ModuleType("deps")
    db = types.SimpleNamespace()

    def _holdings_find(*a, **kw):
        return _AsyncIter(list(_HOLDINGS))

    def _empty_find(*a, **kw):
        return _AsyncIter([])

    async def _profile_find_one(*a, **kw):
        return {"risk_profile": _USER_PROFILE} if _USER_PROFILE else None

    db.holdings = types.SimpleNamespace(find=_holdings_find)
    db.portfolio_holdings = types.SimpleNamespace(find=_empty_find)
    db.user_profiles = types.SimpleNamespace(find_one=_profile_find_one)
    stub.db = db
    sys.modules["deps"] = stub
    return stub


# Install deps stub at module load so risk.py can be imported (its functions
# do local imports of deps at call time, not at module level — but defensive).
_make_db_stub()


# Stub DAAS client so tests run offline.
# NOTE: NOT installed at module level — doing so would overwrite
# test_recommendation_engine.py's daas_client stub (collected before us) and
# cause those tests to see our DaasError class instead of theirs.
def _make_daas_stub():
    async def _fake_get_features(symbol):
        if symbol in _VOL_MAP:
            return {"volatility_20d": _VOL_MAP[symbol]}
        return None

    daas = types.ModuleType("services.copilot_tools.daas_client")
    daas.get_stock_features_latest = _fake_get_features

    class _DaasError(Exception):
        pass

    daas.DaasError = _DaasError
    sys.modules["services.copilot_tools.daas_client"] = daas
    return daas


from services.copilot_tools.risk import (
    get_risk_suitability,
    get_portfolio_var,
    RiskResult,
    _Z,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _holding(
    name="Test Fund",
    asset_type="MF",
    buy_price=100.0,
    current_price=150.0,
    quantity=1000.0,
    equity_allocation_pct=None,
    symbol=None,
    sector="Technology",
):
    h = {
        "name": name,
        "asset_type": asset_type,
        "buy_price": buy_price,
        "current_price": current_price,
        "quantity": quantity,
        "equity_allocation_pct": equity_allocation_pct,
        "sector": sector,
    }
    if symbol:
        h["symbol"] = symbol
    return h


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _install_stubs():
    """Install our stubs for each test; restore previous stubs on teardown.

    test_tax_engine_integration.py installs its own deps stub at module load,
    which overwrites ours. This fixture reinstalls ours for every risk_tools test
    and restores whatever was there before so other test files are unaffected.
    """
    prev_deps = sys.modules.get("deps")
    prev_daas = sys.modules.get("services.copilot_tools.daas_client")
    _make_db_stub()
    _make_daas_stub()
    yield
    if prev_deps is not None:
        sys.modules["deps"] = prev_deps
    else:
        sys.modules.pop("deps", None)
    if prev_daas is not None:
        sys.modules["services.copilot_tools.daas_client"] = prev_daas
    else:
        sys.modules.pop("services.copilot_tools.daas_client", None)


# ─────────────────────────────────────────────────────────────────────────────
# TASK-039: get_risk_suitability
# ─────────────────────────────────────────────────────────────────────────────

class TestRiskSuitabilityBasic:
    def setup_method(self):
        global _HOLDINGS, _USER_PROFILE, _VOL_MAP
        _HOLDINGS = [
            _holding("Equity Fund A", "MF", 100, 160, 1000, equity_allocation_pct=90.0),
            _holding("Debt Fund B",   "MF", 100, 120, 500,  equity_allocation_pct=10.0),
        ]
        _USER_PROFILE = {"category": "moderate", "score": 55, "loss_tolerance_pct": 20.0, "horizon_years": 7}
        _VOL_MAP = {}

    def test_returns_ok(self):
        result = _run(get_risk_suitability("u1"))
        assert result.ok is True

    def test_has_risk_rating(self):
        result = _run(get_risk_suitability("u1"))
        assert result.risk_rating in ("LOW", "MEDIUM", "HIGH", "VERY HIGH")

    def test_has_risk_score_in_range(self):
        result = _run(get_risk_suitability("u1"))
        assert 0.0 <= result.risk_score_0_to_10 <= 10.0

    def test_profile_category_propagated(self):
        result = _run(get_risk_suitability("u1"))
        assert result.user_profile_category == "moderate"

    def test_summary_is_non_empty(self):
        result = _run(get_risk_suitability("u1"))
        assert len(result.summary) > 10

    def test_data_has_equity_pct(self):
        result = _run(get_risk_suitability("u1"))
        assert "equity_pct" in result.data
        # Equity Fund A: 160*1000 = 160000; Total = 160000 + 60000 = 220000
        # Equity pct ≈ 72.7%
        assert result.data["equity_pct"] == pytest.approx(72.7, abs=0.5)

    def test_data_has_portfolio_value(self):
        result = _run(get_risk_suitability("u1"))
        assert "total_portfolio_value" in result.data
        assert result.data["total_portfolio_value"] == pytest.approx(220_000.0)

    def test_rows_present(self):
        result = _run(get_risk_suitability("u1"))
        assert len(result.rows) == 2


class TestRiskSuitabilityNoHoldings:
    def setup_method(self):
        global _HOLDINGS, _USER_PROFILE
        _HOLDINGS = []
        _USER_PROFILE = {}

    def test_no_holdings_returns_error(self):
        result = _run(get_risk_suitability("u_empty"))
        assert result.ok is False
        assert result.error is not None


class TestMisalignmentDetection:
    """Aggressive holdings for a conservative user → misalignments detected."""

    def setup_method(self):
        global _HOLDINGS, _USER_PROFILE, _VOL_MAP
        _HOLDINGS = [
            _holding(name="Nippon Small Cap Fund", asset_type="MF", buy_price=100,
                     current_price=150, quantity=2000, equity_allocation_pct=95.0),
            _holding(name="Axis Mid Cap Fund", asset_type="MF", buy_price=100,
                     current_price=130, quantity=1000, equity_allocation_pct=90.0),
        ]
        _USER_PROFILE = {
            "category": "conservative",
            "score": 20,
            "loss_tolerance_pct": 5.0,
            "horizon_years": 2,
        }
        _VOL_MAP = {}

    def test_equity_pct_misalignment_detected(self):
        result = _run(get_risk_suitability("u_cons"))
        # Both funds are ~90%+ equity — should exceed conservative 50% limit
        equity_mismatches = [m for m in result.misalignment if "Equity allocation" in m]
        assert len(equity_mismatches) >= 1

    def test_small_mid_misalignment_detected(self):
        result = _run(get_risk_suitability("u_cons"))
        # Fund names contain "small cap" / "mid cap"
        sm_mismatches = [m for m in result.misalignment if "Small/mid" in m]
        assert len(sm_mismatches) >= 1

    def test_rating_is_high_or_very_high_for_misaligned(self):
        result = _run(get_risk_suitability("u_cons"))
        assert result.risk_rating in ("HIGH", "VERY HIGH")

    def test_misalignment_list_non_empty(self):
        result = _run(get_risk_suitability("u_cons"))
        assert len(result.misalignment) >= 1

    def test_misalignment_count_in_data(self):
        result = _run(get_risk_suitability("u_cons"))
        assert result.data["misalignment_count"] == len(result.misalignment)


class TestBetaMisalignment:
    """Conservative user with high-beta stocks → beta misalignment."""

    def setup_method(self):
        global _HOLDINGS, _USER_PROFILE, _VOL_MAP
        _HOLDINGS = [
            _holding("Volatile Stock", "STOCK", 100, 120, 500, symbol="VOLSTOCK", sector="Technology"),
        ]
        _USER_PROFILE = {
            "category": "conservative",
            "score": 25,
            "loss_tolerance_pct": 5.0,
            "horizon_years": 2,
        }
        # Daily vol = 0.04 → annual vol = 0.04 × √252 ≈ 63.5% → beta proxy ≈ 3.97
        _VOL_MAP = {"VOLSTOCK": 0.04}

    def test_beta_misalignment_when_high_vol_stock(self):
        result = _run(get_risk_suitability("u_beta"))
        beta_mismatches = [m for m in result.misalignment if "beta" in m.lower()]
        assert len(beta_mismatches) >= 1

    def test_portfolio_beta_in_data(self):
        result = _run(get_risk_suitability("u_beta"))
        assert "portfolio_beta" in result.data
        assert result.data["portfolio_beta"] is not None
        assert result.data["portfolio_beta"] > 1.0


class TestAlignedPortfolio:
    """Aggressive user with high-equity portfolio → no misalignment."""

    def setup_method(self):
        global _HOLDINGS, _USER_PROFILE, _VOL_MAP
        _HOLDINGS = [
            _holding("Large Cap Fund", "MF", 100, 140, 1000, equity_allocation_pct=80.0),
        ]
        _USER_PROFILE = {
            "category": "aggressive",
            "score": 80,
            "loss_tolerance_pct": 40.0,
            "horizon_years": 10,
        }
        _VOL_MAP = {}

    def test_no_misalignment_for_aligned_portfolio(self):
        result = _run(get_risk_suitability("u_agg"))
        assert result.ok is True
        assert len(result.misalignment) == 0

    def test_summary_says_aligned(self):
        result = _run(get_risk_suitability("u_agg"))
        assert "aligned" in result.summary.lower()


class TestDefaultProfileFallback:
    """When user has no stored profile, defaults to moderate."""

    def setup_method(self):
        global _HOLDINGS, _USER_PROFILE, _VOL_MAP
        _HOLDINGS = [
            _holding("Equity Fund", "MF", 100, 130, 1000, equity_allocation_pct=70.0),
        ]
        _USER_PROFILE = {}  # no stored profile
        _VOL_MAP = {}

    def test_defaults_to_moderate(self):
        result = _run(get_risk_suitability("u_new"))
        assert result.ok is True
        assert result.user_profile_category == "moderate"


# ─────────────────────────────────────────────────────────────────────────────
# TASK-040: get_portfolio_var
# ─────────────────────────────────────────────────────────────────────────────

class TestPortfolioVarBasic:
    def setup_method(self):
        global _HOLDINGS, _USER_PROFILE, _VOL_MAP
        _HOLDINGS = [
            _holding("RELIANCE", "STOCK", 2500, 2700, 100, symbol="RELIANCE", sector="Energy"),
            _holding("TCS",      "STOCK", 3500, 3800, 50,  symbol="TCS",      sector="IT"),
        ]
        _USER_PROFILE = {}
        _VOL_MAP = {
            "RELIANCE": 0.015,  # daily vol
            "TCS":      0.018,
        }

    def test_returns_ok(self):
        result = _run(get_portfolio_var("u1"))
        assert result.ok is True

    def test_has_var_keys_in_data(self):
        result = _run(get_portfolio_var("u1"))
        assert "var_1d_95_rs" in result.data
        assert "var_1d_99_rs" in result.data
        assert "var_10d_95_rs" in result.data
        assert "var_10d_99_rs" in result.data

    def test_var_1d_positive(self):
        result = _run(get_portfolio_var("u1"))
        assert result.data["var_1d_95_rs"] > 0

    def test_99_var_greater_than_95_var(self):
        result = _run(get_portfolio_var("u1"))
        assert result.data["var_1d_99_rs"] > result.data["var_1d_95_rs"]

    def test_10d_var_is_sqrt10_of_1d(self):
        result = _run(get_portfolio_var("u1"))
        ratio = result.data["var_10d_95_rs"] / result.data["var_1d_95_rs"]
        assert ratio == pytest.approx(math.sqrt(10), abs=0.01)

    def test_risk_rating_present(self):
        result = _run(get_portfolio_var("u1"))
        assert result.risk_rating in ("LOW", "MEDIUM", "HIGH", "VERY HIGH")

    def test_portfolio_annual_vol_in_data(self):
        result = _run(get_portfolio_var("u1"))
        assert "portfolio_annual_vol_pct" in result.data
        assert result.data["portfolio_annual_vol_pct"] > 0

    def test_portfolio_value_in_data(self):
        result = _run(get_portfolio_var("u1"))
        # RELIANCE: 2700*100=270000, TCS: 3800*50=190000 → 460000
        assert result.data["total_portfolio_value_rs"] == pytest.approx(460_000.0)

    def test_confidence_level_stored(self):
        result = _run(get_portfolio_var("u1", confidence=0.99))
        assert result.data["confidence_level"] == 0.99

    def test_rows_contain_daily_vol(self):
        result = _run(get_portfolio_var("u1"))
        assert len(result.rows) == 2
        for row in result.rows:
            assert "daily_vol" in row
            assert row["daily_vol"] > 0


class TestVarMathVerification:
    """Verify VaR arithmetic with known inputs."""

    def setup_method(self):
        global _HOLDINGS, _VOL_MAP
        # Single stock: value=100000, daily_vol=0.01
        # Weighted vol = 0.01 (single position, weight=1)
        # 1d 95% VaR = 100000 × 0.01 × 1.645 = 1645
        _HOLDINGS = [
            _holding("TESTSTOCK", "STOCK", 1000, 1000, 100, symbol="TESTSTOCK"),
        ]
        _VOL_MAP = {"TESTSTOCK": 0.01}

    def test_1d_var_95_matches_formula(self):
        result = _run(get_portfolio_var("u_math", confidence=0.95))
        expected = 100_000 * 0.01 * 1.645
        assert result.data["var_1d_95_rs"] == pytest.approx(expected, rel=0.01)

    def test_1d_var_99_matches_formula(self):
        result = _run(get_portfolio_var("u_math", confidence=0.99))
        expected = 100_000 * 0.01 * 2.326
        assert result.data["var_1d_99_rs"] == pytest.approx(expected, rel=0.01)


class TestVarMfProxy:
    """MF holdings without symbols use equity_allocation_pct vol proxy."""

    def setup_method(self):
        global _HOLDINGS, _VOL_MAP
        _HOLDINGS = [
            _holding("Equity MF", "MF", 100, 100, 1000, equity_allocation_pct=100.0),
            _holding("Debt MF",   "MF", 100, 100, 1000, equity_allocation_pct=0.0),
        ]
        _VOL_MAP = {}

    def test_equity_mf_higher_vol_than_debt_mf(self):
        result = _run(get_portfolio_var("u_mf"))
        assert result.ok is True
        rows = result.rows
        eq_row = next(r for r in rows if "Equity" in r["name"])
        debt_row = next(r for r in rows if "Debt" in r["name"])
        assert eq_row["daily_vol"] > debt_row["daily_vol"]

    def test_equity_mf_vol_is_18pct_annual_proxy(self):
        result = _run(get_portfolio_var("u_mf"))
        eq_row = next(r for r in result.rows if "Equity" in r["name"])
        expected_daily = 0.18 / math.sqrt(252)
        assert eq_row["daily_vol"] == pytest.approx(expected_daily, rel=0.01)

    def test_debt_mf_vol_is_4pct_annual_proxy(self):
        result = _run(get_portfolio_var("u_mf"))
        debt_row = next(r for r in result.rows if "Debt" in r["name"])
        expected_daily = 0.04 / math.sqrt(252)
        assert debt_row["daily_vol"] == pytest.approx(expected_daily, rel=0.01)


class TestVarEdgeCases:
    def setup_method(self):
        global _HOLDINGS, _VOL_MAP
        _HOLDINGS = []
        _VOL_MAP = {}

    def test_no_holdings_returns_error(self):
        result = _run(get_portfolio_var("u_empty"))
        assert result.ok is False
        assert result.error is not None

    def test_zero_price_holdings_returns_error(self):
        global _HOLDINGS
        _HOLDINGS = [_holding("Fund", "MF", 0, 0, 1000, equity_allocation_pct=70.0)]
        result = _run(get_portfolio_var("u_zero"))
        assert result.ok is False

    def test_missing_daas_vol_falls_back_to_default(self):
        global _HOLDINGS, _VOL_MAP
        _HOLDINGS = [_holding("NIFTY", "STOCK", 200, 200, 100, symbol="NIFTY")]
        _VOL_MAP = {}  # no vol data for NIFTY
        result = _run(get_portfolio_var("u_nodata"))
        # Should still succeed using fallback vol
        assert result.ok is True
        assert result.data["var_1d_95_rs"] > 0


class TestVarRatingThresholds:
    """Annual vol → rating mapping."""

    def setup_method(self):
        global _HOLDINGS, _VOL_MAP
        # Pure debt MF → annual vol ≈ 4% → LOW
        _HOLDINGS = [_holding("Debt Fund", "MF", 100, 100, 1000, equity_allocation_pct=0.0)]
        _VOL_MAP = {}

    def test_low_vol_portfolio_rated_low(self):
        result = _run(get_portfolio_var("u_low"))
        assert result.risk_rating == "LOW"

    def test_high_vol_rated_high(self):
        global _HOLDINGS, _VOL_MAP
        # 100% equity with 30% daily vol stock
        _HOLDINGS = [_holding("Volatile", "STOCK", 100, 100, 1000, symbol="VLAT")]
        _VOL_MAP = {"VLAT": 0.03}  # 3% daily → ~47% annual
        result = _run(get_portfolio_var("u_high"))
        assert result.risk_rating in ("HIGH", "VERY HIGH")


# ─────────────────────────────────────────────────────────────────────────────
# RiskResult helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestRiskResultAsLlmContext:
    def setup_method(self):
        global _HOLDINGS, _USER_PROFILE, _VOL_MAP
        _HOLDINGS = [_holding("Fund", "MF", 100, 120, 500, equity_allocation_pct=70.0)]
        _USER_PROFILE = {"category": "moderate", "score": 55}
        _VOL_MAP = {}

    def test_as_llm_context_contains_rating(self):
        result = _run(get_risk_suitability("u1"))
        ctx = result.as_llm_context()
        assert "risk_rating=" in ctx
        assert result.risk_rating in ctx

    def test_as_llm_context_contains_score(self):
        result = _run(get_risk_suitability("u1"))
        ctx = result.as_llm_context()
        assert "risk_score=" in ctx

    def test_as_llm_context_contains_misalignment_when_present(self):
        global _HOLDINGS, _USER_PROFILE
        _HOLDINGS = [
            _holding(name="Nippon Small Cap Fund", asset_type="MF", buy_price=100,
                     current_price=150, quantity=2000, equity_allocation_pct=95.0),
        ]
        _USER_PROFILE = {"category": "conservative", "score": 20}
        result = _run(get_risk_suitability("u_mis"))
        ctx = result.as_llm_context()
        if result.misalignment:
            assert "misalignment:" in ctx


class TestZScoreConstants:
    def test_z_95_correct(self):
        assert _Z[0.95] == pytest.approx(1.645, abs=0.001)

    def test_z_99_correct(self):
        assert _Z[0.99] == pytest.approx(2.326, abs=0.001)
