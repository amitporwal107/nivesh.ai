"""Shared helpers for tests that create positions through the universal risk service.

MOCK — not real data. The desk, journal and AI-trader MECHANICS suites (fills, exits, marks, idempotency, the ledger)
predate the Phase 1 risk policy; their fixture trades are small (10 shares of a Rs 100 stock, 1-lot index spreads)
and the owner's default profile (0.5% per trade, reward:risk 1.5 after costs) rightly refuses many of them. Those
suites store `loose_profile_doc` for their users — the loosest values the audited setter allows (an admin could set
exactly this) — so they keep testing their mechanics through the REAL service. The policy itself, under the owner
defaults, is tested in tests/test_risk_service.py and tests/test_risk_entry_paths.py.
"""
from __future__ import annotations

from typing import Any, Dict

from services import risk_profile

LOOSE_LIMITS = {field: (risk_profile.RANGES[field][0] if field in risk_profile.HIGHER_IS_TIGHTER
                        else risk_profile.RANGES[field][1]) for field in risk_profile.FIELDS}


def loose_profile_doc(user_id: str) -> Dict[str, Any]:
    """MOCK — a stored risk profile at the loosest allowed values, for a mechanics suite's user."""
    return {"_id": f"mock-loose-profile-{user_id}", "user_id": user_id, "profile": "custom",
            "limits": dict(LOOSE_LIMITS), "version": 1, "starting_capital_rs": risk_profile.SIMULATION_STARTING_CAPITAL_RS,
            "effective_from": "2026-10-01T00:00:00+00:00", "set_by": "mock-admin", "set_at": "2026-10-01T00:00:00+00:00",
            "reason": "MOCK: mechanics suite under the loosest allowed profile", "policy_version": "risk-profile-v1"}


def mock_bars(close: float, *, days, volume: float = 1_000_000.0):
    """MOCK — end-of-day bars (desk_trading.session_bars shape) at a flat price, one per day given."""
    return [{"date": d, "open": close, "high": round(close * 1.01, 2), "low": round(close * 0.99, 2), "close": close,
             "volume": volume, "series": "EQ"} for d in days]
