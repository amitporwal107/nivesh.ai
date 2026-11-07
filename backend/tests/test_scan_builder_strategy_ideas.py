"""Strategy ideas for the scan dashboard (services/scan_builder/strategy_ideas.py).

The real summarizing (ideas.strategies_of, ideas.meets_min_reward_risk, the risk service's credit_terms) runs on hand-made
plans; the plan builder, the clock and the shared store are injected. Every plan, price and figure below is invented
(MOCK — not real data)."""
import asyncio
from datetime import datetime, timezone


from services.scan_builder import intraday as I
from services.scan_builder import strategy_ideas as SI

DAY = datetime(2026, 11, 3, 6, 0, tzinfo=timezone.utc)          # 11:30 IST


def run(coro):
    return asyncio.run(coro)


# ── hand-made plans in the builder's shape ──────────────────────────────────────────────────────────────────────────

def opt(side, strike, otype, price, lots=1, lot=100, expiry="2026-11-24"):
    return {"kind": "option", "side": side, "quantity": lots, "lot_size": lot, "entry_price": price, "expiry": expiry,
            "strike": strike, "option_type": otype}


def cand(cid, label, status="candidate", net=2.0, gross=2.2, legs=None, segment="options", family="bull_call_spread",
         max_loss=-500.0, car=600.0, gate_basis=None):
    rr = {"net": net, "gross": gross, "level": "conservative"}
    if gate_basis:
        rr["gate_basis"] = gate_basis
    c = {"id": cid, "segment": segment, "family": family, "label": label, "status": status, "reasons": [],
         "why_qualifies": ["MOCK reason"], "legs": legs or [], "payoff": {"expiry": {"max_profit": 1000.0}}, "risk_reward": rr,
         "sizing": {"status": "incomplete"}, "warnings": [], "trade_plan": {"plan_id": f"tp_{cid}"}}
    alt = {"id": cid, "max_loss": max_loss, "max_loss_basis": "defined max loss at expiry (gross)", "capital_at_risk": car,
           "breakeven": [710.0], "reward_risk_net": net, "reward_risk_gross": gross, "liquidity_flags": []}
    return c, alt


def plan(*pairs, status="plan", preferred=None, min_rr=1.5):
    return {"plan_id": "plan_mock", "status": status, "preferred": preferred,
            "inputs": {"min_reward_risk": min_rr, "horizon": "positional", "horizon_days": 10},
            "data_as_of": {"price": "2026-11-02", "fno": "2026-11-02"},
            "candidates": [c for c, _ in pairs], "alternatives": [a for _, a in pairs]}


SPREAD = [opt("buy", 700, "call", 12.0), opt("sell", 730, "call", 4.0)]


def test_a_favorable_structure_is_shown_with_its_own_figures_in_neutral_words():
    p = plan(cand("options:bull_call_spread", "Bull call spread", legs=SPREAD, net=1.72, gross=1.77),
             cand("cash:breakout", "Cash long", segment="cash", family="breakout", net=1.6, gross=1.7,
                  legs=[{"kind": "cash", "side": "buy", "quantity": 250, "lot_size": 1, "entry_price": 700.0}]),
             preferred="options:bull_call_spread")
    idea, why = SI.summarize(p, "HDFCBANK")
    assert why is None
    assert idea["structure"] == "Bull call spread" and idea["reward_risk"] == 1.72 and idea["reward_risk_basis"] == "net of estimated costs"
    assert idea["legs_text"] == "Long 1 lot 700 CE + Short 1 lot 730 CE, 24 Nov"
    assert idea["max_loss_inr"] == 500.0 and idea["capital_at_risk_inr"] == 600.0 and idea["other_favorable"] == 1
    assert idea["plan_inputs"] == {"underlying": "HDFCBANK", "direction": "bullish", "instrument": "all", "include_chartink": False}
    assert idea["data_as_of"] == "2026-11-02" and idea["trade_plan_id"] == "tp_options:bull_call_spread"


def test_preferred_wins_else_the_best_ratio():
    a = cand("options:a", "Bull call spread", legs=SPREAD, net=1.6)
    b = cand("cash:b", "Cash long", segment="cash", net=3.0, legs=[{"kind": "cash", "side": "buy", "quantity": 10, "lot_size": 1, "entry_price": 1.0}])
    assert SI.summarize(plan(a, b, preferred="options:a"), "X")[0]["structure"] == "Bull call spread"
    assert SI.summarize(plan(a, b, preferred=None), "X")[0]["structure"] == "Cash long"


def test_under_the_minimum_or_not_viable_shows_none_with_a_reason():
    low = plan(cand("options:a", "Bull call spread", legs=SPREAD, net=1.2, gross=1.3))
    assert SI.summarize(low, "X") == (None, SI.WHY["unfavorable"])
    blocked = plan(cand("options:a", "Bull call spread", status="no_trade", legs=SPREAD), status="no_trade")
    assert SI.summarize(blocked, "X") == (None, SI.WHY["no_trade"])
    assert SI.summarize(plan(status="wait"), "X") == (None, SI.WHY["wait"])
    assert SI.summarize(plan(status="insufficient_data"), "X") == (None, SI.WHY["insufficient_data"])


def test_the_net_ratio_decides_and_shows_whenever_the_builder_has_one():
    c = cand("futures:long", "Long future", segment="futures", family="long_future", net=1.1, gross=2.4,
             gate_basis="gross: the position is not sized",
             legs=[{"kind": "future", "side": "buy", "quantity": 1, "lot_size": 550, "entry_price": 700.0, "expiry": "2026-11-24"}])
    p = plan(c)
    # the builder's own flag decides: meets_min_reward_risk reads net first, so this one does NOT pass at 1.1 net
    assert SI.summarize(p, "X") == (None, SI.WHY["unfavorable"])
    c2 = cand("futures:long", "Long future", segment="futures", family="long_future", net=None, gross=2.4,
              gate_basis="gross: the position is not sized",
              legs=[{"kind": "future", "side": "buy", "quantity": 1, "lot_size": 550, "entry_price": 700.0, "expiry": "2026-11-24"}])
    idea, _ = SI.summarize(plan(c2), "X")
    assert idea["reward_risk"] == 2.4 and idea["reward_risk_basis"] == "before costs"
    assert idea["legs_text"] == "Long 1 lot future, 24 Nov"


def test_a_credit_spread_needs_a_third_of_its_width():
    thin = [opt("sell", 700, "put", 12.0), opt("buy", 650, "put", 2.0)]        # credit 10 on width 50: under 1/3
    fat = [opt("sell", 700, "put", 22.0), opt("buy", 650, "put", 2.0)]         # credit 20 on width 50: at least 1/3
    assert not SI.credit_ok(thin) and SI.credit_ok(fat) and SI.credit_ok(SPREAD)   # a debit spread is not a credit structure
    p = plan(cand("options:bps", "Bull put spread", family="bull_put_spread", legs=thin, net=1.6))
    assert SI.summarize(p, "X") == (None, SI.WHY["credit"])
    idea, _ = SI.summarize(plan(cand("options:bps", "Bull put spread", family="bull_put_spread", legs=fat, net=1.6)), "X")
    assert idea["structure"] == "Bull put spread" and idea["legs_text"] == "Short 1 lot 700 PE + Long 1 lot 650 PE, 24 Nov"


# ── the shared, non-blocking cache ──────────────────────────────────────────────────────────────────────────────────

class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def wall(self):
        return self.t

    def now(self):
        return DAY


FAV = plan(cand("options:a", "Bull call spread", legs=SPREAD, net=2.0), preferred="options:a")


class Builder:
    def __init__(self, plans=None, fail=(), gate=None):
        self.plans, self.fail, self.gate, self.calls = plans or {}, set(fail), gate, []

    async def __call__(self, sym):
        self.calls.append(sym)
        if self.gate is not None:
            await self.gate.wait()
        if sym in self.fail:
            raise RuntimeError("MOCK source down")
        return self.plans.get(sym, plan(status="wait"))


def svc(clock, builder, store=None):
    return SI.IdeasService(store=store if store is not None else I.LocalStore(clock.wall), builder=builder, wall=clock.wall,
                           now=clock.now, system_user={"user_id": "system:test", "role": "user"})


def test_first_answer_is_pending_then_the_built_verdicts_come_from_cache():
    async def go():
        clock = Clock()
        b = Builder({"AAA": FAV})
        s = svc(clock, b)
        r1 = await s.ideas_for(["AAA", "BBB"])
        assert r1.pending == ["AAA", "BBB"] and r1.values == {}
        assert r1.warnings == ["Strategy ideas are still being built for 2 of 2 stocks."]
        await s._task
        r2 = await s.ideas_for(["AAA", "BBB"])
        assert r2.pending == [] and r2.values["AAA"]["structure"] == "Bull call spread" and r2.values["BBB"] is None
        assert r2.reasons == {"BBB": SI.WHY["wait"]} and r2.as_of == "2026-11-02"
        assert sorted(b.calls) == ["AAA", "BBB"]
        await s.ideas_for(["AAA", "BBB"])
        assert len(b.calls) == 2                                  # fresh: nothing rebuilt
        return True
    assert run(go())


def test_a_second_worker_reads_the_first_workers_verdicts_without_building():
    async def go():
        clock = Clock()
        store = I.LocalStore(clock.wall)
        b1, b2 = Builder({"AAA": FAV}), Builder({"AAA": FAV})
        w1, w2 = svc(clock, b1, store), svc(clock, b2, store)
        await w1.ideas_for(["AAA"])
        await w1._task
        r = await w2.ideas_for(["AAA"])
        assert r.values["AAA"]["structure"] == "Bull call spread" and b2.calls == [] and w2._task is None
        return True
    assert run(go())


def test_a_stock_another_worker_is_building_is_not_built_twice():
    async def go():
        clock = Clock()
        store = I.LocalStore(clock.wall)
        gate = asyncio.Event()
        b1, b2 = Builder({"AAA": FAV}, gate=gate), Builder({"AAA": FAV})
        w1, w2 = svc(clock, b1, store), svc(clock, b2, store)
        await w1.ideas_for(["AAA"])
        await asyncio.sleep(0.01)                                  # w1 holds the claim, its build waits on the gate
        await w2.ideas_for(["AAA"])
        await w2._task
        assert b2.calls == []
        gate.set()
        await w1._task
        assert (await w2.ideas_for(["AAA"])).values["AAA"] is not None
        return True
    assert run(go())


def test_after_three_hours_a_verdict_is_rebuilt_in_the_background_and_the_old_one_answers_meanwhile():
    async def go():
        clock = Clock()
        b = Builder({"AAA": FAV})
        s = svc(clock, b)
        await s.ideas_for(["AAA"])
        await s._task
        clock.t += SI.FRESH_S - 1
        await s.ideas_for(["AAA"])
        assert len(b.calls) == 1
        clock.t += 2
        r = await s.ideas_for(["AAA"])
        assert r.pending == [] and r.values["AAA"] is not None     # the old verdict answers while it is rebuilt
        await s._task
        assert len(b.calls) == 2
        return True
    assert run(go())


def test_a_failed_build_is_no_idea_for_ten_minutes_then_tried_again():
    async def go():
        clock = Clock()
        b = Builder(fail={"AAA"})
        s = svc(clock, b)
        await s.ideas_for(["AAA"])
        await s._task
        r = await s.ideas_for(["AAA"])
        assert r.values["AAA"] is None and r.reasons["AAA"] == SI.WHY["failed"] and s.failures == 1
        clock.t += SI.RETRY_S + 1
        await s.ideas_for(["AAA"])
        await s._task
        assert b.calls == ["AAA", "AAA"]
        return True
    assert run(go())


def test_builds_run_at_most_concurrency_at_a_time():
    async def go():
        clock = Clock()
        live = {"now": 0, "max": 0}

        async def slow(sym):
            live["now"] += 1
            live["max"] = max(live["max"], live["now"])
            await asyncio.sleep(0.01)
            live["now"] -= 1
            return plan(status="wait")
        s = svc(clock, slow)
        await s.ideas_for([f"S{i}" for i in range(10)])
        await s._task
        assert live["max"] == SI.CONCURRENCY
        assert len((await s.ideas_for([f"S{i}" for i in range(10)])).values) == 10
        return True
    assert run(go())


def test_the_build_runs_as_the_system_caller():
    async def go():
        from deps import _SYSTEM_CALLER
        clock = Clock()
        seen = []

        async def who(sym):
            seen.append((_SYSTEM_CALLER.get() or {}).get("user_id"))
            return plan(status="wait")
        s = svc(clock, who)
        await s.ideas_for(["AAA"])
        assert _SYSTEM_CALLER.get() is None                      # the caller's own context is untouched
        await s._task
        assert seen == ["system:test"]
        return True
    assert run(go())


def test_nothing_this_module_writes_uses_a_barred_word():
    texts = [SI.note_text(), SI.note_text(2.0), SI.SOURCE, *SI.WHY.values(), "Strategy ideas are still being built for 3 of 9 stocks.",
             SI.legs_text(SPREAD), SI.legs_text([opt("sell", 700, "put", 22.0), opt("buy", 650, "put", 2.0)]),
             SI.legs_text([{"kind": "cash", "side": "buy", "quantity": 250}])]
    idea, _ = SI.summarize(FAV, "AAA")
    texts += [str(v) for v in idea.values()]
    assert [t for t in texts if SI.BARRED.search(t)] == []
    # a builder label that ever carried a barred word is replaced, never shown
    bad = plan(cand("options:a", "Buy the dip call", legs=SPREAD, net=2.0, family="long_call"), preferred="options:a")
    assert SI.summarize(bad, "X")[0]["structure"] == "Long call"


def test_a_net_ratio_is_shown_even_when_the_gross_one_is_higher():
    c = cand("futures:long", "Long future", segment="futures", family="long_future", net=8.1, gross=13.19,
             gate_basis="gross: the position is not sized",
             legs=[{"kind": "future", "side": "buy", "quantity": 1, "lot_size": 550, "entry_price": 700.0, "expiry": "2026-11-23"}])
    idea, _ = SI.summarize(plan(c), "X")
    assert idea["reward_risk"] == 8.1 and idea["reward_risk_basis"] == "net of estimated costs"
