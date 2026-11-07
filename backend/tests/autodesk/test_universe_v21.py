"""AD-SC-26..32 — wider scan universes (docs/autodesk/testcases_scoring_v21.md). TEST DATA in a FrozenMarketView, not real market data."""
from __future__ import annotations

from datetime import date

import pytest

from autodesk import contracts as C
from autodesk import store
from autodesk.agents.ai_trader import AITrader
from autodesk.market.view import DataUnavailable, FrozenMarketView
from tests.autodesk import marketdata as md
from tests.autodesk import test_ai_trader_ts as T
from tests.autodesk.conftest import run
from tests.autodesk.test_simulator import _sim, cfg, manager, tenant

# members: two F&O underlyings (LB long build-up, SB short build-up on falling bars), a non-F&O riser, a non-F&O faller,
# and one member with no bars. The breakout riser CASHUP is not an F&O underlying (no futures row).
MEMBERS = {"Nifty 500": ["CASHUP", "CASHDN", "LB", "SB", "NOBARS"], "Nifty Total Market": ["CASHUP", "CASHDN", "LB", "SB", "NOBARS", "EXTRA"]}


def data(**over) -> dict:
    d = T.data()
    d["bars"] = {**d["bars"], "CASHUP": T.breakout_bars(), "CASHDN": T.down_bars(), "EXTRA": T.breakout_bars()}
    d["members"] = MEMBERS
    d.update(over)
    return d


def scan(d: dict, universe: str, symbols=None) -> C.ScanReport:
    ctx = md.ctx(FrozenMarketView(T.AS_OF, d), {"session_date": T.SD.isoformat(), "universe": universe, "symbols": symbols,
                                                "min_score": "0"})
    res = run(AITrader().run(md.task(C.TaskType.SCAN_MARKET), ctx))
    return C.ScanReport.model_validate(res.output)


def test_adsc26_named_universe_scans_members():
    rep = scan(data(), "NIFTY500")
    assert rep.universe == "NIFTY500" and rep.universe_size == 5
    assert {s.instrument for s in rep.signals} <= set(MEMBERS["Nifty 500"])
    assert any(x["instrument"] == "NOBARS" and x["reason"].startswith("0 bars") for x in rep.suppressed)
    tm = scan(data(), "TOTAL_MARKET")
    assert tm.universe == "TOTAL_MARKET" and tm.universe_size == 6 and any(s.instrument == "EXTRA" for s in tm.signals)
    assert not any(s.instrument == "EXTRA" for s in rep.signals)


def test_adsc27_non_fno_members_are_cash_only():
    rep = scan(data(), "NIFTY500")
    up = [s for s in rep.signals if s.instrument == "CASHUP"]
    assert up and all(s.segment == C.Segment.CASH and s.direction == C.Direction.BULLISH and not s.fno_eligible for s in up)
    assert not [s for s in rep.signals if s.instrument == "CASHDN"]                # bearish needs F&O
    assert any(s.instrument == "SB" and s.segment == C.Segment.FUTURES for s in rep.signals)   # F&O member keeps futures


def test_adsc28_fno_default_unchanged_and_excludes_index_futures_elsewhere():
    fno = scan(data(), "FNO")
    assert fno.universe == "FNO" and any(s.segment == C.Segment.INDEX for s in fno.signals)
    assert {s.instrument for s in fno.signals} == {s.instrument for s in T.scan(T.data()).signals}
    assert not [s for s in scan(data(), "NIFTY500").signals if s.segment == C.Segment.INDEX]
    ctx = md.ctx(FrozenMarketView(T.AS_OF, data()), {"session_date": T.SD.isoformat(), "min_score": "0"})   # no universe key
    out = C.ScanReport.model_validate(run(AITrader().run(md.task(C.TaskType.SCAN_MARKET), ctx)).output)
    assert out.universe == "FNO" and out.universe_size == fno.universe_size


def test_adsc29_unknown_universe_refused():
    with pytest.raises(ValueError, match="unknown universe"):
        scan(data(), "BOGUS")


def test_adsc30_constituents_unavailable_fails_visibly():
    with pytest.raises(DataUnavailable):
        scan(data(members={}), "NIFTY500")


def test_adsc31_cap_lifted_only_for_named_universes(pg_pool):
    async def go():
        t = tenant()
        m = manager(pg_pool)
        sim = await m.create(tenant_id=t, cfg=cfg(universe="TOTAL_MARKET"), user_id="u")
        assert sim["config"]["universe"] == "TOTAL_MARKET" and not sim["config"].get("symbols")
        with pytest.raises(ValueError, match="1 to 50"):
            await m.create(tenant_id=t, cfg=cfg(symbols=[f"S{i}" for i in range(51)]), user_id="u")
    run(go())


def test_adsc32_survivorship_caveat(pg_pool):
    async def go():
        t = tenant()
        out = {}
        for key, kw in (("idx", dict(universe="NIFTY500")), ("fno", dict()), ("sym", dict(universe="NIFTY500", symbols=["LB"]))):
            m, sim = await _sim(pg_pool, t, **kw)
            await m.run_to_end(tenant_id=t, sid=sim["simulation_id"])
            async with pg_pool.acquire() as c:
                out[key] = (await store.get_simulation(c, t, sim["simulation_id"]))["results"]["limitations"]
        has = lambda lim: any("survivorship" in x.lower() for x in lim)           # noqa: E731
        assert has(out["idx"]) and not has(out["fno"]) and not has(out["sym"])
    run(go())
