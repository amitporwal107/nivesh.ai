"""App-side /api/movers proxy: forwarding, status pass-through and route order. `deps`, `feature_gate` and
`daas_client` are stubbed (MOCK — not real data) so this proves the wiring only; the live answer comes from
the staging HTTP run in test_reports/."""
import asyncio
import importlib.util
import sys
import types
from datetime import date
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parent.parent / "routes" / "movers.py"


@pytest.fixture()
def px():
    mp = pytest.MonkeyPatch()
    deps = types.ModuleType("deps")

    async def get_current_user(request=None):
        return {"id": "t"}
    deps.get_current_user = get_current_user
    gate = types.ModuleType("feature_gate")
    gate.require_feature = lambda flag: (lambda: {"features": {flag: True}})
    dc = types.ModuleType("services.copilot_tools.daas_client")

    class DaasError(Exception):
        pass
    dc.DaasError = DaasError
    dc.calls = []
    dc.reply = (200, {"ok": True})
    dc.configured = True
    dc.is_configured = lambda: dc.configured

    async def get_raw(path, params=None, timeout=0):
        dc.calls.append((path, params, timeout))
        if isinstance(dc.reply, Exception):
            raise dc.reply
        return dc.reply
    dc.get_raw = get_raw
    for name, m in (("deps", deps), ("feature_gate", gate), ("services", types.ModuleType("services")),
                    ("services.copilot_tools", types.ModuleType("services.copilot_tools")),
                    ("services.copilot_tools.daas_client", dc)):
        mp.setitem(sys.modules, name, m)
    sys.modules["services.copilot_tools"].daas_client = dc
    spec = importlib.util.spec_from_file_location("movers_proxy_under_test", PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._dc = dc
    yield mod
    mp.undo()


def run(c):
    return asyncio.run(c)


def test_static_routes_before_symbol_catchall(px):
    paths = [r.path for r in px.router.routes]
    sym = "/api/movers/{symbol}"
    for p in ("/api/movers/calibration", "/api/movers/flag-lift", "/api/movers/flagged"):
        assert paths.index(p) < paths.index(sym)
        first = next(r for r in px.router.routes if r.path_regex.match(p))
        assert first.path == p


def test_forward_serialises_dates_and_drops_none(px):
    px._dc.reply = (200, {"rows": []})
    out = run(px._forward("/movers", {"from": date(2026, 9, 1), "to": date(2026, 9, 30), "x": None}))
    assert out == {"rows": []}
    path, params, _ = px._dc.calls[0]
    assert path == "/movers" and params == {"from": "2026-09-01", "to": "2026-09-30"}


@pytest.mark.parametrize("status", [400, 404, 422])
def test_client_errors_pass_through(px, status):
    from fastapi import HTTPException
    px._dc.reply = (status, {"detail": "nope"})
    with pytest.raises(HTTPException) as e:
        run(px._forward("/movers/X", {}))
    assert e.value.status_code == status and e.value.detail == "nope"


@pytest.mark.parametrize("reply", [(500, {"detail": "boom"}), (503, None), (200, None)])
def test_upstream_failure_is_502_never_empty_success(px, reply):
    from fastapi import HTTPException
    px._dc.reply = reply
    with pytest.raises(HTTPException) as e:
        run(px._forward("/movers", {}))
    assert e.value.status_code == 502


def test_connectivity_error_and_unconfigured_are_502(px):
    from fastapi import HTTPException
    px._dc.reply = px._dc.DaasError("down")
    with pytest.raises(HTTPException) as e:
        run(px._forward("/movers", {}))
    assert e.value.status_code == 502
    px._dc.configured = False
    with pytest.raises(HTTPException) as e2:
        run(px._forward("/movers", {}))
    assert e2.value.status_code == 502


def test_symbol_is_normalised_and_heavy_timeout_applied(px):
    px._dc.reply = (200, {})
    run(px.mover_detail(request=None, symbol=" tcs ", user={}, session=date(2026, 9, 30), range_="T7",
                        frm=None, to=None, horizon=3))
    assert px._dc.calls[-1][0] == "/movers/TCS"
    run(px.calibration(request=None, user={}, frm=date(2026, 9, 1), to=date(2026, 9, 30), head="p_up5_1d", horizon=3))
    assert px._dc.calls[-1][0] == "/movers/calibration" and px._dc.calls[-1][2] == 120.0
