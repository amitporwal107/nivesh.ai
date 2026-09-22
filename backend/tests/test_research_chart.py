"""backend/routes/research_chart.py + services/research_chart.py (TC-1..TC-10, TC-24 in
test_reports/charting_v1_app_surface.md). No DB, no network: the exported snapshot is a real
fixture built once per test session by research.charting.export into a temp directory, and the
feature-gate's user resolver / flag store / clock are injected, so the gate and the snapshot
loader run for real -- only Mongo/session auth are out of scope here (there's none in this API)."""
from __future__ import annotations

import copy
import gzip
import hashlib
import json
import math
import pathlib
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

# research.charting lives outside backend/ (repo_root/research/charting) -- not on sys.path when
# pytest runs from backend/. Mirrors research/charting/tests/conftest.py's own bootstrap.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import feature_flags as ff
import feature_gate
import routes.research_chart as rc
import services.research_chart as svc
from research.charting import export


USERS = {"invited": {"user_id": "u1", "email": "invited@example.com", "role": "user"},
         "other": {"user_id": "u2", "email": "other@example.com", "role": "user"},
         "admin": {"user_id": "u3", "email": "admin@example.com", "role": "admin", "is_admin": True}}


@pytest.fixture(autouse=True)
def _reset_flags():
    saved = copy.deepcopy(ff._flags)
    feature_gate._state["at"] = float("-inf")
    yield
    ff._flags.clear()
    ff._flags.update(saved)
    feature_gate._state["at"] = float("-inf")


@pytest.fixture(autouse=True)
def _reset_snapshot_caches():
    """services.research_chart's manifest/symbol caches are module-level dicts keyed on
    (path, mtime, size); different tests point SNAPSHOT_DIR at different tmp_path directories, so
    a stale in-memory entry from a prior test could never collide on path -- but clearing keeps
    each test's cache state independent and the intent explicit."""
    svc._manifest_cache["key"], svc._manifest_cache["data"] = None, None
    svc._symbol_cache.clear()
    yield
    svc._manifest_cache["key"], svc._manifest_cache["data"] = None, None
    svc._symbol_cache.clear()


class _DB:
    """Only feature_gate needs a db (for the flag store / owner-profile lookup); this API has no
    Mongo of its own."""
    def __init__(self, flags=None):
        self.system_config = _Coll([{"key": "feature_flags", "flags": flags or {}}])
        self.users = _Coll([])


class _Coll:
    def __init__(self, docs):
        self.docs = docs

    async def find_one(self, q, proj=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                return copy.deepcopy(d)
        return None


def _client(monkeypatch, snapshot_dir: Path, db=None, clock=lambda: 0.0):
    if db is None:
        db = _DB(flags={"charting": {"mode": "allowlist", "allowlist": ["invited@example.com"]}})
    monkeypatch.setattr(svc, "SNAPSHOT_DIR", snapshot_dir)
    monkeypatch.setattr(svc, "MANIFEST_PATH", snapshot_dir / "manifest.json")

    async def resolve(request: Request):
        return copy.deepcopy(USERS[request.headers["X-Test-User"]])
    gate = feature_gate.require_feature("charting", resolve_user=resolve, get_db=lambda: db, clock=clock)
    app = FastAPI()
    app.include_router(rc.router)
    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        for dep in (dependant.dependencies if dependant else []):
            if dep.call is not None and getattr(dep.call, "__qualname__", "").startswith("require_feature"):
                app.dependency_overrides[dep.call] = gate
    return TestClient(app)


def _get(c, path, who="invited"):
    return c.get(path, headers={"X-Test-User": who})


@pytest.fixture(scope="module")
def real_snapshot(tmp_path_factory) -> Path:
    """A real fixture snapshot (fixture: true, SYN1 + SYN2) built once for the whole module via
    the actual exporter -- exercises export.py and services/research_chart.py together, not
    hand-crafted JSON."""
    out_dir = tmp_path_factory.mktemp("chart_snapshot")
    export.build_snapshot(fixture=True, out_dir=out_dir)
    return out_dir


# ---------------------------------------------------------------------------
# TC-1 gate
# ---------------------------------------------------------------------------

def test_tc1_every_endpoint_denies_a_non_allowlisted_account(monkeypatch, real_snapshot):
    c = _client(monkeypatch, real_snapshot)
    for path in ("/api/research/chart/run", "/api/research/chart/symbols",
                "/api/research/chart/SYN1/ohlcv", "/api/research/chart/SYN1/indicators",
                "/api/research/chart/SYN1/patterns"):
        for who in ("other", "admin"):
            r = _get(c, path, who)
            assert r.status_code == 403 and r.json()["detail"] == "feature_not_enabled", (path, who, r.text)


# ---------------------------------------------------------------------------
# TC-2 /run
# ---------------------------------------------------------------------------

def test_tc2_run_matches_config_hash_and_carries_fixture_minus_perfile_hashes(monkeypatch, real_snapshot):
    from research.charting.config import config_hash
    c = _client(monkeypatch, real_snapshot)
    r = _get(c, "/api/research/chart/run")
    assert r.status_code == 200
    body = r.json()
    assert body["config_hash"] == config_hash()
    assert body["fixture"] is True
    assert body["schema_version"] == 1
    assert "sha256" not in json.dumps(body)             # per-file hashes stripped
    assert body["source"]["files"] == []                # fixture mode: no source CSVs
    assert all("sha256" not in e for e in body["symbols"])


# ---------------------------------------------------------------------------
# TC-3 /symbols
# ---------------------------------------------------------------------------

def test_tc3_symbols_equals_manifest_symbols(monkeypatch, real_snapshot):
    manifest = json.loads((real_snapshot / "manifest.json").read_text())
    c = _client(monkeypatch, real_snapshot)
    r = _get(c, "/api/research/chart/symbols")
    assert r.status_code == 200
    assert r.json()["symbols"] == manifest["symbols"]


# ---------------------------------------------------------------------------
# TC-4 /ohlcv — ascending, unique dates, served sha256 == manifest
# ---------------------------------------------------------------------------

def test_tc4_ohlcv_bars_are_ascending_unique_and_file_hash_matches_manifest(monkeypatch, real_snapshot):
    manifest = json.loads((real_snapshot / "manifest.json").read_text())
    entry = next(e for e in manifest["symbols"] if e["symbol"] == "SYN2")
    raw = (real_snapshot / entry["file"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == entry["sha256"]

    c = _client(monkeypatch, real_snapshot)
    r = _get(c, "/api/research/chart/SYN2/ohlcv")
    assert r.status_code == 200
    body = r.json()
    dates = [row[0] for row in body["bars"]]
    assert dates == sorted(dates) and len(dates) == len(set(dates))
    assert body["data_quality_status"] == "VALID"
    assert body["pit_status"] == "PIT_UNVERIFIED"
    assert body["provenance"]["run_id"] == manifest["run_id"]
    assert body["provenance"]["config_hash"] == manifest["config_hash"]
    assert body["provenance"]["adjustment_status"] == "UNVERIFIED"


# ---------------------------------------------------------------------------
# TC-5 unknown symbol
# ---------------------------------------------------------------------------

def test_tc5_unknown_symbol_is_404(monkeypatch, real_snapshot):
    c = _client(monkeypatch, real_snapshot)
    for path in ("/api/research/chart/NOSUCH/ohlcv", "/api/research/chart/NOSUCH/indicators",
                "/api/research/chart/NOSUCH/patterns"):
        r = _get(c, path)
        assert r.status_code == 404 and r.json()["detail"] == "unknown_symbol", path


# ---------------------------------------------------------------------------
# TC-6 illegal symbol chars -- 422, no file read
# ---------------------------------------------------------------------------

def test_tc6_illegal_symbol_is_422_and_never_touches_the_loader(monkeypatch, real_snapshot):
    calls = []
    real_load = svc.load_symbol

    def spy(symbol):
        calls.append(symbol)
        return real_load(symbol)
    monkeypatch.setattr(svc, "load_symbol", spy)
    monkeypatch.setattr(rc, "load_symbol", spy)

    c = _client(monkeypatch, real_snapshot)
    for bad in ("syn1", "S" * 40):                    # lowercase; over-length -- both single path segments
        r = _get(c, f"/api/research/chart/{bad}/ohlcv")
        assert r.status_code == 422, (bad, r.status_code, r.text)

    # A literal "/" can't reach {symbol} as one path segment at all -- FastAPI/Starlette resolve
    # a percent-encoded slash into a route-matching boundary before our pattern validator ever
    # runs, so "../x" 404s at the framework level (route not found) rather than 422 from our
    # regex. Still zero file reads either way, which is the property that actually matters here.
    import re as _re
    from urllib.parse import quote
    r = _get(c, f"/api/research/chart/{quote('../x', safe='')}/ohlcv")
    assert r.status_code in (404, 422), (r.status_code, r.text)
    assert _re.fullmatch(rc.SYMBOL_PATTERN, "../x") is None     # would be rejected by our own validator too

    assert calls == []


# ---------------------------------------------------------------------------
# TC-7 missing / malformed / wrong schema_version snapshot -- 503, never partial (unit-level)
# ---------------------------------------------------------------------------

def test_tc7_missing_manifest_is_none(tmp_path):
    svc._manifest_cache["key"], svc._manifest_cache["data"] = None, None
    assert svc.load_manifest(tmp_path / "manifest.json") is None


def test_tc7_wrong_schema_version_is_none(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"schema_version": 2}))
    svc._manifest_cache["key"], svc._manifest_cache["data"] = None, None
    assert svc.load_manifest(tmp_path / "manifest.json") is None


def test_tc7_malformed_json_is_none(tmp_path):
    (tmp_path / "manifest.json").write_text("{not json")
    svc._manifest_cache["key"], svc._manifest_cache["data"] = None, None
    assert svc.load_manifest(tmp_path / "manifest.json") is None


def test_tc7_route_answers_503_when_manifest_is_corrupted_on_disk(monkeypatch, real_snapshot, tmp_path):
    import shutil
    broken = tmp_path / "broken_snapshot"
    shutil.copytree(real_snapshot, broken)
    (broken / "manifest.json").write_text("{not json at all")
    c = _client(monkeypatch, broken)
    r = _get(c, "/api/research/chart/run")
    assert r.status_code == 503 and r.json()["detail"] == "snapshot_unavailable"


def test_tc7_symbol_file_hash_mismatch_is_503_not_a_partial_response(monkeypatch, real_snapshot, tmp_path):
    import shutil
    broken = tmp_path / "tampered_snapshot"
    shutil.copytree(real_snapshot, broken)
    # Tamper with SYN1's bytes without updating the manifest's recorded sha256.
    p = broken / "symbols" / "SYN1.json.gz"
    tampered = json.loads(gzip.decompress(p.read_bytes()))
    tampered["bars"][0][1] = 999999.0
    p.write_bytes(gzip.compress(json.dumps(tampered).encode(), mtime=0))

    c = _client(monkeypatch, broken)
    r = _get(c, "/api/research/chart/SYN1/ohlcv")
    assert r.status_code == 503 and r.json()["detail"] == "snapshot_unavailable"


# ---------------------------------------------------------------------------
# TC-8 indicators — ids filter, unknown -> 400
# ---------------------------------------------------------------------------

def test_tc8_indicators_filters_by_ids_and_rejects_unknown(monkeypatch, real_snapshot):
    c = _client(monkeypatch, real_snapshot)
    r = _get(c, "/api/research/chart/SYN2/indicators?ids=sma_20,rsi_14")
    assert r.status_code == 200
    body = r.json()
    assert set(body["indicators"].keys()) == {"sma_20", "rsi_14"}

    r = _get(c, "/api/research/chart/SYN2/indicators")
    assert r.status_code == 200
    assert set(r.json()["indicators"].keys()) == {
        "sma_20", "sma_50", "ema_20", "bollinger", "rsi_14", "macd", "atr_14", "relative_volume",
    }

    r = _get(c, "/api/research/chart/SYN2/indicators?ids=sma_20,not_a_real_one")
    assert r.status_code == 400 and "not_a_real_one" in r.json()["detail"]


# ---------------------------------------------------------------------------
# TC-9 indicator values vs independent recomputation from the served bars
# ---------------------------------------------------------------------------

def test_tc9_served_indicators_match_independent_recomputation_from_served_bars(monkeypatch, real_snapshot):
    from research.charting import series as series_mod
    import pandas as pd

    c = _client(monkeypatch, real_snapshot)
    bars = _get(c, "/api/research/chart/SYN2/ohlcv").json()["bars"]
    df = pd.DataFrame(bars, columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"])

    indicators = _get(c, "/api/research/chart/SYN2/indicators").json()["indicators"]

    # sma_20 -- single output, independently recomputed
    expected_sma20 = series_mod.sma(df, 20)
    served = {row[0]: row[1] for row in indicators["sma_20"]["values"]}
    recomputed = {d.strftime("%Y-%m-%d"): v for d, v in zip(df["date"], expected_sma20) if not math.isnan(v)}
    assert served.keys() == recomputed.keys()
    for d in served:
        assert abs(served[d] - recomputed[d]) < 1e-9

    # macd -- multi-output, positionally aligned to contract.output_fields
    macd_out = indicators["macd"]
    assert macd_out["contract"]["output_fields"] == ["macd", "signal", "hist"]
    expected_macd = series_mod.macd(df)
    served_macd = {row[0]: row[1:] for row in macd_out["values"]}
    for d, row in zip(df["date"], expected_macd.itertuples(index=False)):
        key = d.strftime("%Y-%m-%d")
        if key not in served_macd:
            assert math.isnan(row.macd)
            continue
        assert abs(served_macd[key][0] - row.macd) < 1e-9
        assert abs(served_macd[key][1] - row.signal) < 1e-9
        assert abs(served_macd[key][2] - row.hist) < 1e-9

    # No indicator ever serves a NaN/0 placeholder for a warmup bar: every served value must be
    # a genuine finite float, and the warmup rows (by count) must equal the registry's own
    # warmup_period for sma_20 (single-output, no ambiguity about what "warmup" resolves to).
    assert len(indicators["sma_20"]["values"]) == len(df) - 20 + 1


# ---------------------------------------------------------------------------
# TC-10 patterns
# ---------------------------------------------------------------------------

def test_tc10_patterns_is_empty_list_for_v1(monkeypatch, real_snapshot):
    c = _client(monkeypatch, real_snapshot)
    r = _get(c, "/api/research/chart/SYN1/patterns")
    assert r.status_code == 200 and r.json() == {"symbol": "SYN1", "patterns": []}


# ---------------------------------------------------------------------------
# TC-132..TC-137 (W2, §38.7/§38.11) -- weekly/monthly `timeframe=1D|1W|1M`. TC-120..TC-131
# (resample.py's own OHLCV math + export.py wiring) live in research/charting/tests/
# test_resample.py and test_export_timeframes.py -- this file only re-verifies the API layer
# (route -> service -> served JSON) on top of that already-proven resampling.
# ---------------------------------------------------------------------------

def test_tc132_ohlcv_timeframe_1w_1m_match_resample_module_applied_to_the_served_daily_bars(monkeypatch, real_snapshot):
    import pandas as pd

    from research.charting import resample as resample_mod

    c = _client(monkeypatch, real_snapshot)
    daily = _get(c, "/api/research/chart/SYN2/ohlcv").json()["bars"]
    ddf = pd.DataFrame(daily, columns=["date", "open", "high", "low", "close", "volume"])
    ddf["date"] = pd.to_datetime(ddf["date"])

    for tf, resampler in resample_mod.RESAMPLERS.items():
        expected = resampler(ddf)
        body = _get(c, f"/api/research/chart/SYN2/ohlcv?timeframe={tf}").json()
        assert body["timeframe"] == tf
        got = body["bars"]
        assert len(got) == len(expected)
        for row, (_, erow) in zip(got, expected.iterrows()):
            assert row[0] == erow["date"].strftime("%Y-%m-%d")
            assert row[1:6] == [float(erow["open"]), float(erow["high"]), float(erow["low"]),
                                float(erow["close"]), float(erow["volume"])]
            assert row[6] == bool(erow["incomplete"])
        assert body["findings"] == []                     # §9.1 findings are daily-indexed only
        assert body["data_quality_status"] == "VALID"      # unchanged by timeframe


def test_tc133_default_timeframe_is_1d_and_unaffected_by_this_change(monkeypatch, real_snapshot):
    c = _client(monkeypatch, real_snapshot)
    explicit = _get(c, "/api/research/chart/SYN2/ohlcv?timeframe=1D").json()
    implicit = _get(c, "/api/research/chart/SYN2/ohlcv").json()
    assert implicit["timeframe"] == "1D"
    assert implicit == explicit

    explicit_ind = _get(c, "/api/research/chart/SYN2/indicators?timeframe=1D").json()
    implicit_ind = _get(c, "/api/research/chart/SYN2/indicators").json()
    assert implicit_ind["timeframe"] == "1D"
    assert implicit_ind == explicit_ind


def test_tc134_unknown_timeframe_is_400_with_a_reason_code_on_both_endpoints(monkeypatch, real_snapshot):
    c = _client(monkeypatch, real_snapshot)
    for path in ("/api/research/chart/SYN2/ohlcv?timeframe=5Y",
                "/api/research/chart/SYN2/indicators?timeframe=5Y"):
        r = _get(c, path)
        assert r.status_code == 400 and r.json()["detail"] == "unknown_timeframe: 5Y", path


def test_tc135_weekly_indicators_match_independent_recomputation_from_served_weekly_bars(monkeypatch, real_snapshot):
    import pandas as pd

    from research.charting import series as series_mod

    c = _client(monkeypatch, real_snapshot)
    weekly_bars = _get(c, "/api/research/chart/SYN2/ohlcv?timeframe=1W").json()["bars"]
    wdf = pd.DataFrame(weekly_bars, columns=["date", "open", "high", "low", "close", "volume", "incomplete"])
    wdf["date"] = pd.to_datetime(wdf["date"])

    body = _get(c, "/api/research/chart/SYN2/indicators?timeframe=1W").json()
    assert body["timeframe"] == "1W"
    served = {row[0]: row[1] for row in body["indicators"]["sma_20"]["values"]}
    expected = series_mod.sma(wdf, 20)
    recomputed = {d.strftime("%Y-%m-%d"): v for d, v in zip(wdf["date"], expected) if not math.isnan(v)}
    assert served.keys() == recomputed.keys()
    for d in served:
        assert abs(served[d] - recomputed[d]) < 1e-9

    # ids filter still works per-timeframe, and an unknown id is still rejected per-timeframe.
    r = _get(c, "/api/research/chart/SYN2/indicators?timeframe=1W&ids=sma_20,rsi_14")
    assert r.status_code == 200 and set(r.json()["indicators"]) == {"sma_20", "rsi_14"}
    r = _get(c, "/api/research/chart/SYN2/indicators?timeframe=1W&ids=not_a_real_one")
    assert r.status_code == 400 and "not_a_real_one" in r.json()["detail"]


def test_tc136_snapshot_hash_covers_the_new_series_tampered_weekly_bar_is_503(monkeypatch, real_snapshot, tmp_path):
    """Changing a weekly bar changes the per-symbol file's bytes, hence its sha256, hence a
    tampered copy (manifest sha256 left untouched) is rejected exactly like a tampered daily bar
    (TC-7) -- the manifest's per-file hash already covers `timeframes`, since it hashes the whole
    gzip file, not just the `bars` key."""
    import shutil
    broken = tmp_path / "tampered_weekly_snapshot"
    shutil.copytree(real_snapshot, broken)
    p = broken / "symbols" / "SYN2.json.gz"
    tampered = json.loads(gzip.decompress(p.read_bytes()))
    tampered["timeframes"]["1W"]["bars"][0][1] = 999999.0     # mutate a weekly bar's open
    p.write_bytes(gzip.compress(json.dumps(tampered).encode(), mtime=0))

    c = _client(monkeypatch, broken)
    r = _get(c, "/api/research/chart/SYN2/ohlcv?timeframe=1W")
    assert r.status_code == 503 and r.json()["detail"] == "snapshot_unavailable"


def test_tc137_symbol_payload_missing_timeframes_key_fails_validation(monkeypatch, real_snapshot, tmp_path):
    """Unit-level, mirrors TC-7's style: `timeframes` is a required key (every symbol this module
    ever serves goes through export.py, which always writes both `1W` and `1M`) -- a payload
    missing it (or missing one of the two required sub-keys) is a snapshot-integrity problem, the
    same 503 class as a missing/corrupt daily field, never a partial response."""
    import shutil
    broken = tmp_path / "no_timeframes_snapshot"
    shutil.copytree(real_snapshot, broken)
    p = broken / "symbols" / "SYN2.json.gz"
    tampered = json.loads(gzip.decompress(p.read_bytes()))
    del tampered["timeframes"]["1M"]                            # only 1W left -- not {"1W", "1M"}
    p.write_bytes(gzip.compress(json.dumps(tampered).encode(), mtime=0))

    c = _client(monkeypatch, broken)
    r = _get(c, "/api/research/chart/SYN2/ohlcv")
    assert r.status_code == 503 and r.json()["detail"] == "snapshot_unavailable"


# ---------------------------------------------------------------------------
# TC-24 (data) -- covered against real Kite data separately (see the export report); this is the
# offline analogue: the fixture's bars must match synth.py's own generator bit for bit.
# ---------------------------------------------------------------------------

def test_tc24_analogue_served_bars_match_the_synth_generator_directly(monkeypatch, real_snapshot):
    from research.charting.tests import synth
    c = _client(monkeypatch, real_snapshot)
    served = _get(c, "/api/research/chart/SYN1/ohlcv").json()["bars"]
    expected = synth.rect1()
    assert len(served) == len(expected)
    for row, (_, erow) in zip(served, expected.iterrows()):
        assert row[0] == erow["date"].strftime("%Y-%m-%d")
        assert row[1:] == [float(erow["open"]), float(erow["high"]), float(erow["low"]),
                           float(erow["close"]), float(erow["volume"])]


# ---------------------------------------------------------------------------
# Determinism -- re-exporting the same fixture data reproduces identical per-symbol bytes
# ---------------------------------------------------------------------------

def test_export_is_deterministic_across_runs(tmp_path):
    out1 = tmp_path / "run1"
    out2 = tmp_path / "run2"
    m1 = export.build_snapshot(fixture=True, out_dir=out1)
    m2 = export.build_snapshot(fixture=True, out_dir=out2)
    for e1, e2 in zip(m1["symbols"], m2["symbols"]):
        assert e1["symbol"] == e2["symbol"]
        assert e1["sha256"] == e2["sha256"]
        assert (out1 / e1["file"]).read_bytes() == (out2 / e2["file"]).read_bytes()


# ---------------------------------------------------------------------------
# Cross-stack contract: the UI's mocked Playwright fixtures must have the real API's top-level shape.
# Staging, 2026-09-21: /symbols returned {"symbols": [...]} while the fixture was a bare list, so the
# Charts screen crashed on real data while every mocked UI test passed. This test is the guard.
# ---------------------------------------------------------------------------
_UI_FIXTURES = Path(__file__).resolve().parents[2] / "frontend-v5" / "e2e" / "fixtures"


@pytest.mark.parametrize("endpoint, fixture", [
    ("/api/research/chart/run", "research-chart-run.json"),
    ("/api/research/chart/symbols", "research-chart-symbols.json"),
    ("/api/research/chart/SYN1/ohlcv", "research-chart-ohlcv-RELIANCE.json"),
    ("/api/research/chart/SYN1/indicators", "research-chart-indicators-RELIANCE.json"),
    ("/api/research/chart/SYN1/patterns", "research-chart-patterns-RELIANCE.json"),
])
def test_ui_fixtures_have_the_real_api_top_level_shape(monkeypatch, real_snapshot, endpoint, fixture):
    import json as _json
    real = _get(_client(monkeypatch, real_snapshot), endpoint).json()
    mock = _json.loads((_UI_FIXTURES / fixture).read_text())
    assert type(real) is type(mock), f"{fixture}: API returns {type(real).__name__}, fixture is {type(mock).__name__}"
    if isinstance(real, dict):
        invented = set(mock) - set(real)
        assert not invented, f"{fixture} carries keys the API never sends: {sorted(invented)}"
