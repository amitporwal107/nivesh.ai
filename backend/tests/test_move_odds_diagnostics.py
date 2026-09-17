"""GET /api/move-odds/diagnostics (TC-39..TC-41 in test_reports/move_odds_diagnostics_20260917_1221.md). The gate runs for
real through the route test harness; the snapshot is the committed file."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from tests.test_move_odds_routes import _DB, _client, _get, _reset_flags  # noqa: F401  (autouse fixture)

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs" / "ai_research" / "tpd3" / "entry_setups"
ALLOW = {"move_odds": {"mode": "allowlist", "allowlist": ["invited@example.com"]}}


def _generator():
    spec = importlib.util.spec_from_file_location("make_page_diagnostics", EVIDENCE / "make_page_diagnostics.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def test_tc39_payload_is_the_committed_snapshot_and_equals_the_backtest(monkeypatch):
    rb = (EVIDENCE / "entry_setups_result.json").read_bytes()
    result = json.loads(rb)
    built = _generator().build(rb)
    snapshot = json.loads((ROOT / "backend" / "services" / "move_odds_setup_diagnostics.json").read_text())
    assert snapshot == built                                                     # regenerating gives the committed file
    c, calls = _client(monkeypatch, _DB(flags=ALLOW))
    r = _get(c, "/api/move-odds/diagnostics", "invited")
    assert r.status_code == 200 and calls == []                                  # no DaaS call
    d = r.json()["data"]
    assert d["source_sha256"] == hashlib.sha256(rb).hexdigest() and "_comment" not in d
    assert [s["id"] for s in d["setups"]] == ["A", "B", "C", "D"]
    assert [s["status"] for s in d["setups"]] == ["not_validated", "not_validated", "research_only_insufficient_sample", "research_only_insufficient_sample"]
    assert d["study"]["tested"] == 8 and d["study"]["validated"] == 0
    for s, key in zip(d["setups"], "abcd"):
        for t in s["trades"]:
            src = result["setups"][f"{key}_{t['trade']}"]
            assert (t["trades"], t["mean_net"], t["half1_mean_net"], t["half2_mean_net"]) == (src["trades"], src["mean_net"], src["half1"].get("mean_net"), src["half2"].get("mean_net"))
            assert t["baseline_mean_net"] == result["baseline"][t["trade"]]["mean_net"] and t["validation"] == "failed"


def test_tc40_not_allowlisted_is_denied(monkeypatch):
    c, _ = _client(monkeypatch, _DB(flags=ALLOW))
    for who in ("other", "admin"):
        r = _get(c, "/api/move-odds/diagnostics", who)
        assert r.status_code == 403 and r.json()["detail"] == "feature_not_enabled"


@pytest.mark.parametrize("breakage", ["missing", "not_json", "reordered", "validated", "no_sha"])
def test_tc41_a_missing_or_malformed_snapshot_is_503_without_numbers(monkeypatch, tmp_path, breakage):
    import services.move_odds_diagnostics as md

    good = json.loads(md.SNAPSHOT.read_text())
    bad = tmp_path / "snap.json"
    if breakage == "not_json":
        bad.write_text("{not json")
    elif breakage == "reordered":
        good["setups"] = sorted(good["setups"], key=lambda s: s["trades"][1]["mean_net"]); bad.write_text(json.dumps(good))
    elif breakage == "validated":
        good["setups"][0]["trades"][0]["validation"] = "passed"; bad.write_text(json.dumps(good))
    elif breakage == "no_sha":
        good["source_sha256"] = "x"; bad.write_text(json.dumps(good))
    monkeypatch.setattr(md, "SNAPSHOT", bad)
    monkeypatch.setattr(md.load_setup_diagnostics, "__defaults__", (bad,))
    c, _ = _client(monkeypatch, _DB(flags=ALLOW))
    r = _get(c, "/api/move-odds/diagnostics", "invited")
    assert r.status_code == 503 and r.json() == {"detail": "diagnostics_unavailable"}
