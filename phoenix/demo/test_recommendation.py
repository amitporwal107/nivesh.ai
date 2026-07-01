"""Self-contained validation suite for INC-1845. Loads recommendation.py BY PATH
(next to this file) so it needs no sys.path/package/live-server/.env — this keeps
validation output deterministic and byte-consistent on re-run (AC-5 / E-V2)."""
import importlib.util
import pathlib


def _load():
    p = pathlib.Path(__file__).with_name("recommendation.py")
    spec = importlib.util.spec_from_file_location("rec_demo", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_normal_weights_sum():
    rec = _load()
    assert rec.recommend_allocation([{"weight": 0.5}, {"weight": 0.25}]) == 0.75


def test_null_weight_treated_as_zero():
    # The fix: a None weight must be treated as 0.0, not raise TypeError.
    rec = _load()
    assert rec.recommend_allocation([{"weight": 0.5}, {"weight": None}]) == 0.5
