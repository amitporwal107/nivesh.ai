"""PRD cost-sensitivity scenarios: optimistic 0.05% / base 0.15% / conservative 0.30% / stress
0.50% per-side slippage, each recomputing net-before-tax with everything else held fixed."""
import datetime as dt
from decimal import Decimal

from research.costs.sensitivity import SCENARIOS, run_scenarios


def test_scenario_ladder_matches_prd_percentages():
    names_and_pcts = {name: pct for name, pct in SCENARIOS}
    assert names_and_pcts == {
        "optimistic": Decimal("0.05"),
        "base": Decimal("0.15"),
        "conservative": Decimal("0.30"),
        "stress": Decimal("0.50"),
    }


def test_more_stressed_scenarios_never_produce_a_better_net_before_tax():
    kwargs = dict(
        buy_date=dt.date(2025, 1, 1), sell_date=dt.date(2025, 1, 2), qty=100, cost_path="bundled",
        cost_kwargs=dict(rule_id="prd-illustrative-v1", profile="delivery", exchange="NSE", dp_applies=False),
    )
    results = run_scenarios(entry_price=Decimal("1000"), exit_price=Decimal("1100"), round_trip_kwargs=kwargs)
    ordered = [results[name].net_before_tax for name, _ in SCENARIOS]
    assert ordered == sorted(ordered, reverse=True), "net_before_tax must strictly worsen as slippage increases"
    # every scenario shares the identical statutory cost breakdown -- only slippage moves
    totals = {results[name].total_cost for name, _ in SCENARIOS}
    assert len(totals) == 1


def test_stress_scenario_slippage_amount():
    kwargs = dict(
        buy_date=dt.date(2025, 1, 1), sell_date=dt.date(2025, 1, 2), qty=100, cost_path="bundled",
        cost_kwargs=dict(rule_id="prd-illustrative-v1", profile="delivery", exchange="NSE", dp_applies=False),
    )
    results = run_scenarios(entry_price=Decimal("1000"), exit_price=Decimal("1100"), round_trip_kwargs=kwargs)
    stress = results["stress"]
    # 0.50% of price, per side, x 100 shares
    assert stress.entry_slippage == (Decimal("1000") * Decimal("0.50") / 100 * 100).quantize(Decimal("0.01"))
    assert stress.exit_slippage == (Decimal("1100") * Decimal("0.50") / 100 * 100).quantize(Decimal("0.01"))
