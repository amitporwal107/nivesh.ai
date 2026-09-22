"""Every TradeRecord carries the three PRD-required version tags, and rule_loader.unverified_records
can enumerate every rate marked verified=false across a rule file (used to produce the "list every
unverified rate" deliverable without hand-maintaining a separate list)."""
import datetime as dt
from decimal import Decimal

from research.costs.engine import compute_round_trip
from research.costs.rule_loader import load_rule_file, unverified_records


def test_trade_record_carries_all_three_version_tags():
    rec = compute_round_trip(
        buy_date=dt.date(2025, 1, 1), sell_date=dt.date(2025, 1, 2), qty=10,
        entry_price=Decimal("100"), exit_price=Decimal("110"), cost_path="bundled",
        cost_kwargs=dict(rule_id="prd-illustrative-v1", profile="delivery", exchange="NSE", dp_applies=False),
        slippage_model_version="fixed_pct_v1[0.15%]",
        compute_tax_flag=True,
    )
    assert rec.cost_rule_version == "prd-illustrative-v1@1"
    assert rec.tax_rule_version == "tax-equity-v1@1"
    assert rec.slippage_model_version == "fixed_pct_v1[0.15%]"


def test_unverified_records_enumerates_statutory_gaps():
    rs = load_rule_file("nse-equity-statutory-v1")
    unverified = unverified_records(rs)
    assert len(unverified) > 0
    # every entry is identifiable: which component, what window, why
    for rec in unverified:
        assert "component" in rec and "effective_from" in rec and "note" in rec
    components_with_gaps = {r["component"] for r in unverified}
    assert "exchange_txn_charge" in components_with_gaps
    assert "dp_charge" in components_with_gaps


def test_unverified_records_on_tax_rule_file():
    rs = load_rule_file("tax-equity-v1")
    unverified = unverified_records(rs)
    components = {r["component"] for r in unverified}
    assert "surcharge" in components  # the pre-2022 slab table is explicitly unverified


def test_zerodha_and_prd_illustrative_have_no_unverified_gaps():
    """The two bundled (reproduction/test-only) rule files are single verified snapshots, not
    time-series -- unverified_records() should find nothing to flag in either."""
    for rule_id in ("zerodha-equity-v1", "prd-illustrative-v1"):
        rs = load_rule_file(rule_id)
        assert unverified_records(rs) == []
