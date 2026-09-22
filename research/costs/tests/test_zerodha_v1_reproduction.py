"""zerodha-equity-v1 must reproduce the OLD tpd_model/risk/costs.py:fill_costs() output to the
paisa, on a grid of trades. The old module is not on this branch (it lives on
feat/paper-trade-engine, 219 commits ahead of dev/unmerged) -- so this test fetches it live via
`git show` into a temp directory, alongside a copy of our rules/zerodha-equity-v1.json (a strict
superset of the original file's keys, so the old loader -- which only reads the keys it already
knew about -- behaves identically), and imports it as an ordinary module. Nothing under
research/costs/ imports the old module at runtime; this is test-only scaffolding, per the task
brief.
"""
import datetime as dt
import importlib.util
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
OLD_MODULE_GIT_PATH = "backend/nidp/services/tpd_model/risk/costs.py"
OLD_MODULE_REF = "feat/paper-trade-engine"
RULES_DIR = Path(__file__).resolve().parents[1] / "rules"


def _fetch_old_module(tmp_path: Path):
    proc = subprocess.run(["git", "-C", str(REPO_ROOT), "show", f"{OLD_MODULE_REF}:{OLD_MODULE_GIT_PATH}"],
                           capture_output=True, text=True, check=True)
    old_dir = tmp_path / "old_tpd_risk"
    old_dir.mkdir()
    (old_dir / "costs.py").write_text(proc.stdout)
    models_dir = old_dir / "cost_models"
    models_dir.mkdir()
    shutil.copy(RULES_DIR / "zerodha-equity-v1.json", models_dir / "zerodha-equity-v1.json")
    spec = importlib.util.spec_from_file_location("old_tpd_risk_costs", old_dir / "costs.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def old_costs(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("old_costs_fetch")
    try:
        return _fetch_old_module(tmp_path)
    except subprocess.CalledProcessError as e:
        pytest.skip(f"could not fetch {OLD_MODULE_REF}:{OLD_MODULE_GIT_PATH} via git show: {e.stderr}")


GRID = [
    # profile,   exchange, side,   value,        dp_applies
    ("delivery", "NSE",    "BUY",  Decimal("100000")),
    ("delivery", "NSE",    "SELL", Decimal("100000")),
    ("delivery", "BSE",    "BUY",  Decimal("57834.19")),
    ("delivery", "BSE",    "SELL", Decimal("57834.19")),
    ("intraday", "NSE",    "BUY",  Decimal("50000")),
    ("intraday", "NSE",    "SELL", Decimal("50000")),
    ("intraday", "NSE",    "BUY",  Decimal("500000")),   # large enough to hit the Rs 20 brokerage cap
    ("intraday", "NSE",    "SELL", Decimal("500000")),
    ("intraday", "BSE",    "SELL", Decimal("1")),        # tiny fill, rounding edge
    ("delivery", "NSE",    "SELL", Decimal("0")),        # zero-value edge
]


@pytest.mark.parametrize("profile,exchange,side,value", GRID)
def test_matches_old_module_on_grid(old_costs, profile, exchange, side, value):
    from research.costs.engine import bundled_fill_costs

    model = old_costs.load_cost_model("zerodha-equity-v1")
    on_date = model.effective_from
    dp_applies = side == "SELL"

    old_out = old_costs.fill_costs(model, profile, exchange, side, value, dp_applies=dp_applies, on_date=on_date)
    new_out = bundled_fill_costs("zerodha-equity-v1", profile, exchange, side, value,
                                  dp_applies=dp_applies, on_date=on_date)

    for component in ("brokerage", "stt", "exchange_txn", "sebi", "stamp", "gst", "dp", "total"):
        assert new_out[component] == old_out[component], (
            f"{component} mismatch for {profile}/{exchange}/{side}/{value}: "
            f"old={old_out[component]} new={new_out[component]}"
        )
    assert new_out["retroactive"] == old_out["retroactive"]


def test_matches_old_module_retroactive_flag(old_costs):
    from research.costs.engine import bundled_fill_costs

    model = old_costs.load_cost_model("zerodha-equity-v1")
    retro_date = model.effective_from - dt.timedelta(days=30)

    old_out = old_costs.fill_costs(model, "delivery", "NSE", "BUY", Decimal("100000"), dp_applies=False,
                                    on_date=retro_date, allow_retroactive=True)
    new_out = bundled_fill_costs("zerodha-equity-v1", "delivery", "NSE", "BUY", Decimal("100000"),
                                  dp_applies=False, on_date=retro_date, allow_retroactive=True)
    assert new_out["total"] == old_out["total"]
    assert new_out["retroactive"] is True and old_out["retroactive"] is True


def test_old_module_raises_without_allow_retroactive(old_costs):
    from research.costs.engine import CostEngineError, bundled_fill_costs

    model = old_costs.load_cost_model("zerodha-equity-v1")
    retro_date = model.effective_from - dt.timedelta(days=1)

    with pytest.raises(old_costs.CostModelError):
        old_costs.fill_costs(model, "delivery", "NSE", "BUY", Decimal("100000"), dp_applies=False, on_date=retro_date)
    with pytest.raises(CostEngineError):
        bundled_fill_costs("zerodha-equity-v1", "delivery", "NSE", "BUY", Decimal("100000"),
                            dp_applies=False, on_date=retro_date)


# Golden outputs of the old fill_costs(), pinned in zerodha_v1_golden.json (same grid + the retroactive case), so the exact
# reproduction is checked in every clone -- the git-show tests above skip wherever feat/paper-trade-engine is not present.
GOLDEN = __import__("json").loads((Path(__file__).parent / "zerodha_v1_golden.json").read_text())


@pytest.mark.parametrize("case", GOLDEN["cases"], ids=lambda c: f"{c['profile']}-{c['exchange']}-{c['side']}-{c['value']}")
def test_matches_pinned_golden_outputs_of_the_old_module(case):
    from research.costs.engine import bundled_fill_costs

    out = bundled_fill_costs("zerodha-equity-v1", case["profile"], case["exchange"], case["side"], Decimal(case["value"]),
                             dp_applies=case["dp_applies"], on_date=dt.date.fromisoformat(case["on_date"]),
                             allow_retroactive=case["allow_retroactive"])
    for component, expected in case["expected"].items():
        assert out[component] == Decimal(expected), (component, case)
