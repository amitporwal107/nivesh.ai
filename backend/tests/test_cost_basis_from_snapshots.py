"""Unit tests for `services.cost_basis_from_snapshots._derive_running_avg`
— the pure function that walks per-period rows for one ISIN and produces
a weighted-average cost basis from share-count deltas.
"""
from __future__ import annotations

import pytest

from services.cost_basis_from_snapshots import (
    _derive_running_avg,
    _index_snapshot_rows,
    _merge_into_index,
    _qty_for,
    _price_for,
)


def _eq_entry(num_shares: float, market_price: float, value: float | None = None,
              pledged: float = 0) -> dict:
    return {
        "asset_type": "equity",
        "row": {
            "num_shares": num_shares,
            "pledged_shares": pledged,
            "market_price_inr": market_price,
            "value_inr": (num_shares * market_price) if value is None else value,
        },
    }


def _sgb_entry(num_units: float, market_price: float, value: float | None = None) -> dict:
    return {
        "asset_type": "gold",
        "row": {
            "num_units": num_units,
            "market_price_per_unit_inr": market_price,
            "value_inr": (num_units * market_price) if value is None else value,
            "face_value_per_unit_inr": 5000,
        },
    }


# ── _derive_running_avg ────────────────────────────────────────────────
def test_single_purchase_attributed_at_period_close():
    snaps = [
        _eq_entry(0, 100),       # held nothing
        _eq_entry(10, 250),      # bought 10 shares
    ]
    avg = _derive_running_avg("ISIN", snaps)
    assert avg == pytest.approx(250.0)


def test_multiple_purchases_yield_weighted_average():
    # 10 @ 100, then +10 @ 200 → (1000 + 2000) / 20 = 150
    snaps = [
        _eq_entry(10, 100),
        _eq_entry(20, 200),
    ]
    avg = _derive_running_avg("ISIN", snaps)
    assert avg == pytest.approx(150.0)


def test_partial_sale_reduces_position_at_running_avg():
    # 10 @ 100, +10 @ 200 (avg=150), -5 → cost = 15*150, qty=15, avg=150
    snaps = [
        _eq_entry(10, 100),
        _eq_entry(20, 200),
        _eq_entry(15, 250),       # sold 5; final qty 15
    ]
    avg = _derive_running_avg("ISIN", snaps)
    assert avg == pytest.approx(150.0)


def test_full_sale_returns_none():
    # All shares sold by end → no current cost basis.
    snaps = [
        _eq_entry(10, 100),
        _eq_entry(0, 110),
    ]
    assert _derive_running_avg("ISIN", snaps) is None


def test_no_movement_returns_none():
    # User held the same qty throughout — no delta means no signal.
    snaps = [
        _eq_entry(10, 100),
        _eq_entry(10, 110),
        _eq_entry(10, 95),
    ]
    # We DO see a delta on the first iter (prev_qty=0 → 10), so the
    # initial qty IS treated as a purchase at the first snapshot's price.
    avg = _derive_running_avg("ISIN", snaps)
    assert avg == pytest.approx(100.0)


def test_zero_qty_zero_price_rows_are_skipped():
    # 0/0 row in the middle (parser stub) must NOT trigger a phantom sale.
    snaps = [
        _eq_entry(10, 100),
        {"asset_type": "equity",
         "row": {"num_shares": 0, "pledged_shares": 0,
                 "market_price_inr": 0, "value_inr": 0}},
        _eq_entry(15, 200),
    ]
    # delta sequence after dropping the stub: +10 @ 100, +5 @ 200
    # cost = 1000 + 1000 = 2000, qty=15, avg = 133.33
    avg = _derive_running_avg("ISIN", snaps)
    assert avg == pytest.approx(2000 / 15)


def test_sgb_corrupt_first_snapshot_reinterpreted():
    # Real CAS bug: market_price_per_unit_inr=54090 with value_inr=0
    # actually means the TOTAL value was placed in the price column.
    # We expect _price_for to reinterpret it as 5409/unit (price/qty)
    # and produce a sane running average.
    snaps = [
        _sgb_entry(10, 54090, value=0),     # corrupted: 54090 = qty * face_val
        _sgb_entry(10, 13856.89),           # plausible per-unit price
    ]
    avg = _derive_running_avg("ISIN", snaps)
    # First-snapshot price reinterpreted to 5409, no further deltas, avg=5409
    assert avg == pytest.approx(5409.0)


# ── _merge_into_index (duplicate ISIN handling) ────────────────────────
def test_merge_prefers_higher_qty_row():
    # Parser sometimes emits a 0-share ghost duplicate. The ghost must
    # NOT overwrite the real row.
    out: dict = {}
    real = {"isin": "X", "num_shares": 1, "market_price_inr": 100, "value_inr": 100}
    ghost = {"isin": "X", "num_shares": 0, "market_price_inr": 0, "value_inr": 0}
    _merge_into_index(out, "X", "equity", real)
    _merge_into_index(out, "X", "equity", ghost)
    assert out["X"]["row"] is real


def test_merge_prefers_priced_row_when_qty_ties():
    out: dict = {}
    zero_priced = {"isin": "X", "num_shares": 5, "market_price_inr": 0, "value_inr": 0}
    priced = {"isin": "X", "num_shares": 5, "market_price_inr": 200, "value_inr": 1000}
    _merge_into_index(out, "X", "equity", zero_priced)
    _merge_into_index(out, "X", "equity", priced)
    assert out["X"]["row"] is priced


def test_index_skips_mf_folios():
    payload = {
        "holdings": {
            "equities": [{"isin": "EQUITY1", "num_shares": 10, "market_price_inr": 100, "value_inr": 1000}],
            "mutual_fund_folios": [{"isin": "MFFOLIO1", "num_units": 50, "current_nav_inr": 100,
                                    "avg_cost_per_unit_inr": 80}],
            "mutual_funds_demat": [{"isin": "MFDEMAT1", "num_units": 10, "nav_inr": 50, "value_inr": 500}],
        }
    }
    idx = _index_snapshot_rows(payload)
    assert "EQUITY1" in idx
    assert "MFDEMAT1" in idx
    # Folios carry their own avg cost — must NOT be in the index.
    assert "MFFOLIO1" not in idx


# ── _qty_for / _price_for ──────────────────────────────────────────────
def test_qty_for_equity_excludes_pledged():
    # Pledged is unreliable in the parsed payload — see service docstring.
    row = {"num_shares": 100, "pledged_shares": 50}
    assert _qty_for(row, "equity") == 100


def test_price_for_equity_falls_back_to_value_div_qty():
    row = {"num_shares": 10, "market_price_inr": 0, "value_inr": 1500}
    assert _price_for(row, "equity") == 150.0


def test_price_for_sgb_clamps_corrupt_per_unit_price():
    # 100,000/unit is impossible for an SGB. Combined with value_inr=0 it
    # signals the parser stuffed total value into the price column.
    row = {"num_units": 10, "market_price_per_unit_inr": 100_000, "value_inr": 0}
    assert _price_for(row, "gold") == 10_000.0  # 100_000 / 10
