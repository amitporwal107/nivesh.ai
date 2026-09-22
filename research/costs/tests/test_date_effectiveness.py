"""A trade straddling a rate change must use each leg's OWN date -- never the round trip's sell
date (or buy date) applied uniformly to both legs.
"""
import datetime as dt
import json
from decimal import Decimal

import pytest

from research.costs.rule_loader import RuleError, resolve_record

SYNTHETIC_RECORDS = [
    {"pct": "0.10", "effective_from": "2021-01-01", "effective_to": "2023-01-01", "verified": True},
    {"pct": "0.20", "effective_from": "2023-01-01", "effective_to": "2025-01-01", "verified": True},
    {"pct": "0.30", "effective_from": "2025-01-01", "effective_to": None, "verified": True},
]


def test_resolve_record_picks_the_window_containing_the_date():
    assert resolve_record(SYNTHETIC_RECORDS, dt.date(2022, 6, 1)).record["pct"] == "0.10"
    assert resolve_record(SYNTHETIC_RECORDS, dt.date(2023, 1, 1)).record["pct"] == "0.20"  # boundary inclusive
    assert resolve_record(SYNTHETIC_RECORDS, dt.date(2024, 12, 31)).record["pct"] == "0.20"
    assert resolve_record(SYNTHETIC_RECORDS, dt.date(2025, 1, 1)).record["pct"] == "0.30"  # boundary inclusive


def test_resolve_record_raises_outside_coverage():
    with pytest.raises(RuleError):
        resolve_record(SYNTHETIC_RECORDS, dt.date(2020, 1, 1))


SYNTHETIC_STATUTORY_RULE_SET = {
    "rule_set_id": "synthetic-statutory-v1",
    "version": 7,
    "components": {
        "stt": {"records": [
            {"segment": "delivery", "side": "BOTH", "pct": "0.10", "effective_from": "2021-01-01",
             "effective_to": None, "verified": True, "source_url": "https://example.invalid/stt"},
        ]},
        "exchange_txn_charge": {"records": [
            {"exchange": "NSE", "segment": "delivery", "pct": "0.00325", "effective_from": "2021-01-01",
             "effective_to": "2024-10-01", "verified": True, "source_url": "https://example.invalid/txn-old"},
            {"exchange": "NSE", "segment": "delivery", "pct": "0.00297", "effective_from": "2024-10-01",
             "effective_to": None, "verified": True, "source_url": "https://example.invalid/txn-new"},
        ]},
        "sebi_fee": {"records": [
            {"per_crore_inr": "10", "effective_from": "2021-01-01", "effective_to": None, "verified": True,
             "source_url": "https://example.invalid/sebi"},
        ]},
        "gst": {"records": [
            {"pct": "18", "effective_from": "2021-01-01", "effective_to": None, "verified": True,
             "source_url": "https://example.invalid/gst"},
        ]},
        "stamp_duty": {"records": [
            {"segment": "delivery", "side": "BUY", "pct": "0.015", "effective_from": "2021-01-01",
             "effective_to": None, "verified": True, "source_url": "https://example.invalid/stamp"},
        ]},
        "dp_charge": {"records": [
            {"broker": "test-broker", "inr_per_scrip_per_sell_day": "0", "effective_from": "2021-01-01",
             "effective_to": None, "verified": True, "source_url": "https://example.invalid/dp"},
        ]},
    },
}


@pytest.fixture()
def synthetic_rules_dir(tmp_path):
    (tmp_path / "synthetic-statutory-v1.json").write_text(json.dumps(SYNTHETIC_STATUTORY_RULE_SET))
    return str(tmp_path)


def test_round_trip_uses_each_legs_own_exchange_txn_rate(synthetic_rules_dir):
    """buy_date falls in the synthetic rule set's pre-2024-10-01 exchange-charge record, sell_date
    in its post-2024-10-01 record -- the engine must NOT apply one date to both legs."""
    from research.costs.engine import statutory_fill_costs

    buy_date = dt.date(2024, 1, 1)
    sell_date = dt.date(2025, 1, 1)
    value = Decimal("1000000")
    plan = {"type": "flat", "flat_inr": "0"}
    kwargs = dict(statutory_rule_id="synthetic-statutory-v1", rules_dir=synthetic_rules_dir,
                  dp_applies=False, dp_broker=None)

    buy_out = statutory_fill_costs(plan, "NSE", "delivery", "BUY", value, on_date=buy_date, **kwargs)
    sell_out = statutory_fill_costs(plan, "NSE", "delivery", "SELL", value, on_date=sell_date, **kwargs)

    assert buy_out["exchange_txn"] == (value * Decimal("0.00325") / 100).quantize(Decimal("0.01"))
    assert sell_out["exchange_txn"] == (value * Decimal("0.00297") / 100).quantize(Decimal("0.01"))
    assert buy_out["exchange_txn"] != sell_out["exchange_txn"]
    # this synthetic table marks everything verified -- confirms the "no gap" case reports cleanly.
    assert buy_out["unverified_rates_used"] == ()
    assert sell_out["unverified_rates_used"] == ()


def test_round_trip_stt_stable_across_the_same_straddle(synthetic_rules_dir):
    """STT (unlike the exchange charge) has a single unbroken record for the whole window in the
    synthetic table, so both legs must agree even though their dates differ."""
    from research.costs.engine import statutory_fill_costs

    plan = {"type": "flat", "flat_inr": "0"}
    value = Decimal("1000000")
    kwargs = dict(statutory_rule_id="synthetic-statutory-v1", rules_dir=synthetic_rules_dir,
                  dp_applies=False, dp_broker=None)
    buy_out = statutory_fill_costs(plan, "NSE", "delivery", "BUY", value, on_date=dt.date(2022, 5, 1), **kwargs)
    sell_out = statutory_fill_costs(plan, "NSE", "delivery", "SELL", value, on_date=dt.date(2025, 5, 1), **kwargs)
    assert buy_out["stt"] == sell_out["stt"] == (value * Decimal("0.1") / 100).quantize(Decimal("0.01"))


def test_real_statutory_table_covers_every_day_with_no_gap_and_no_null_rate():
    """Every calendar day from 2021-01-01 to today resolves exactly one record per component, with a
    rate (e.g. no hole on 2024-09-30 between an exclusive effective_to and the next record)."""
    from research.costs.rule_loader import load_rule_file

    comps = load_rule_file("nse-equity-statutory-v1")["components"]
    queries = [("stt", "pct", dict(segment="delivery", side="BUY")), ("stt", "pct", dict(segment="delivery", side="SELL")),
               ("exchange_txn_charge", "pct", dict(exchange="NSE", segment="delivery")),
               ("exchange_txn_charge", "pct", dict(exchange="NSE", segment="intraday")),
               ("sebi_fee", "per_crore_inr", {}), ("gst", "pct", {}),
               ("stamp_duty", "pct", dict(segment="delivery", side="BUY")),
               ("dp_charge", "inr_per_scrip_per_sell_day", dict(broker="zerodha"))]
    day = dt.date(2021, 1, 1)
    while day <= dt.date.today():
        for comp, field, sel in queries:
            rec = resolve_record(comps[comp]["records"], day, **sel)
            assert rec.record.get(field) is not None, (comp, day)
        day += dt.timedelta(days=1)


def test_real_statutory_table_prices_a_research_era_trade_and_flags_unverified_legs():
    from research.costs.engine import statutory_fill_costs

    plan = {"type": "flat", "flat_inr": "0"}
    value = Decimal("1000000")
    out = statutory_fill_costs(plan, "NSE", "delivery", "SELL", value, dp_applies=True, dp_broker="zerodha",
                               on_date=dt.date(2022, 6, 1))
    assert out["exchange_txn"] == (value * Decimal("0.00345") / 100).quantize(Decimal("0.01"))
    assert out["sebi"] == (value * Decimal("10") / Decimal("10000000")).quantize(Decimal("0.01"))
    assert out["dp"] == Decimal("15.93")
    assert len(out["unverified_rates_used"]) == 1  # the secondary-source DP charge, reported not hidden
    q1_2021 = statutory_fill_costs(plan, "NSE", "delivery", "BUY", value, dp_applies=False, dp_broker=None,
                                   on_date=dt.date(2021, 2, 1))
    assert q1_2021["sebi"] == (value * Decimal("5") / Decimal("10000000")).quantize(Decimal("0.01"))  # COVID half fee


def test_a_null_rate_raises_loudly_instead_of_pricing_zero(tmp_path):
    from research.costs.engine import CostEngineError, statutory_fill_costs

    rules = json.loads(json.dumps(SYNTHETIC_STATUTORY_RULE_SET))
    rules["components"]["sebi_fee"]["records"][0]["per_crore_inr"] = None
    (tmp_path / "synthetic-statutory-v1.json").write_text(json.dumps(rules))
    with pytest.raises(CostEngineError, match="sebi_fee has no confirmed rate"):
        statutory_fill_costs({"type": "flat", "flat_inr": "0"}, "NSE", "delivery", "BUY", Decimal("1000000"),
                             dp_applies=False, dp_broker=None, on_date=dt.date(2024, 1, 1),
                             statutory_rule_id="synthetic-statutory-v1", rules_dir=str(tmp_path))
