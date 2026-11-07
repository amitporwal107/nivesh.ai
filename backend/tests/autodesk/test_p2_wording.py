"""AD-P2-122: what a simulation stores as its limitations says what is true of THAT run.

With the execution gateway on, approved plans are filled in simulation, so no limitation may say they are not; the one
that is still true (the loss and drawdown limits act on P&L from Phase 3) must stay. With no gateway the run has no
fills and says so. TEST DATA (stubs.py), not real market data."""
from __future__ import annotations

import re

from autodesk import store
from tests.autodesk.conftest import run
from tests.autodesk.test_p2_simulation import build, start
from tests.autodesk.test_safety import ADVICE
from tests.autodesk.test_simulator import tenant

UNFILLED = re.compile(r"not filled|no execution|no paper execution|nothing is executed|no orders|Phase 1 has", re.IGNORECASE)


async def stored_limitations(pool, with_gateway: bool) -> tuple[list[str], dict]:
    t = tenant()
    m, _ = build(pool, with_gateway=with_gateway)
    sim = await start(pool, t, m)
    await m.run_to_end(tenant_id=t, sid=sim["simulation_id"])
    async with pool.acquire() as c:
        res = (await store.get_simulation(c, t, sim["simulation_id"]))["results"]
    return res["limitations"], res


def test_adp2_122_gateway_on_limitations_do_not_say_plans_are_unfilled(pg_pool):
    async def go():
        lim, res = await stored_limitations(pg_pool, with_gateway=True)
        text = " ".join(lim)
        assert "execution_summary" in res, "the run was made with paper execution"
        assert not UNFILLED.search(text), [l for l in lim if UNFILLED.search(l)]
        assert ADVICE.search(text) is None
        # still true, so still said: the loss and drawdown limits do not act on P&L before Phase 3
        assert any("Daily-loss, weekly-loss and drawdown limits are not enforced" in l and "Phase 3" in l for l in lim), lim
        assert res["execution"].startswith("paper execution")
    run(go())


def test_adp2_122_no_gateway_still_says_plans_are_unfilled(pg_pool):
    async def go():
        lim, res = await stored_limitations(pg_pool, with_gateway=False)
        assert "execution_summary" not in res
        assert any("approved plans are not filled" in l and "no paper execution" in l for l in lim), lim
        assert ADVICE.search(" ".join(lim)) is None
    run(go())
