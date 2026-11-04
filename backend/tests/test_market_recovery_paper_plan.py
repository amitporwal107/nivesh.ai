"""Market Recovery › the paper-trade plan: TC-P1 / TC-P2 of docs/market_recovery/DESIGN.md §10 A.

Hand-made candidates, quotes, strategies and risk-gate answers (MOCK — not real data). The planner's own rules run: live-only
candidates, shares levels, option legs re-priced live, the gate's sizing, the ranking (reward : risk after costs, ties to the
lower maximum loss) and the exact desk bodies with their tags and Idempotency-Keys."""
import asyncio
from datetime import datetime, timezone

import pytest

from services.market_recovery import paper_plan as P

NOW = datetime(2026, 11, 4, 4, 10, tzinfo=timezone.utc)          # 09:40 IST
PLAN = {"entry_low": 98.0, "entry_high": 100.0, "stop_loss": 92.0, "target_1": 112.0, "target_2": 118.0}


def cand(rank, sym, plan=PLAN):
    return {"rank": rank, "symbol": sym, "name": f"{sym} Ltd", "sector": "Healthcare", "score": 80.0 - rank, "plan": dict(plan)}


class Page:
    def __init__(self, cands): self.cands = cands
    async def get(self): return {"as_of": "2026-11-03", "candidates": self.cands}
    async def stock_context(self, sym): return {"close": 100.0, "plan": PLAN, "beta": 1.0}


def strategy(key, label, legs, status="passes"):
    return {"key": key, "label": label, "status": status, "why": None if status == "passes" else "Reward : risk at least 1.5: 0.3 : 1",
            "legs": legs}


BCS = strategy("bull_call_spread", "Bull Call Spread", [
    {"action": "Buy", "instrument": "Call", "strike": 100.0, "lots": 1, "units": 100},
    {"action": "Sell", "instrument": "Call", "strike": 110.0, "lots": 1, "units": 100}])
BPS = strategy("bull_put_spread", "Bull Put Credit Spread", [
    {"action": "Sell", "instrument": "Put", "strike": 95.0, "lots": 1, "units": 100},
    {"action": "Buy", "instrument": "Put", "strike": 90.0, "lots": 1, "units": 100}], status="fails")


class Strats:
    def __init__(self, strategies): self.s = strategies
    async def for_stock(self, request, sym, ctx, has_options, eod):
        return {"expiry": "2026-11-23", "lot_size": 100, "strategies": self.s}


def run(monkeypatch, cands, *, quotes, option_quotes=None, gate=None, strategies=(BCS, BPS), fno=("AAA",), open_trades=()):
    monkeypatch.setattr(P.page_service, "get_service", lambda: Page(cands))
    monkeypatch.setattr(P.strat_svc, "get_service", lambda: Strats(list(strategies)))

    async def fno_set(): return set(fno)
    monkeypatch.setattr(P, "_fno_set", fno_set)

    async def sq(symbols): return quotes

    async def oq(legs):
        return option_quotes if option_quotes is not None else {"available": True, "quotes": {"0": {"last_price": 4.0}, "1": {"last_price": 1.0}}}

    async def g(user, body, cid):
        return gate(body) if gate else ({"outcome": "reduce", "approved_qty": 400} if body.get("symbol") else {"outcome": "allow", "approved_lots": 1})

    async def ot(uid): return list(open_trades)

    async def acct(uid): return {"starting_capital_rs": 1e7, "cash_rs": 1e7, "blocked_rs": 0.0, "available_rs": 1e7}
    return asyncio.run(P.build_plan(None, {"user_id": "u1"}, gate=g, stock_quotes=sq, option_quotes=oq, open_trades=ot, account=acct,
                                    now=lambda: NOW))


LIVE = {"source": "kite_live", "as_of": "2026-11-04T04:09:30Z", "quotes": {"AAA": {"ltp": 100.0}, "BBB": {"ltp": 100.0}}}


# ── TC-P1 ranking, eligibility, skips ────────────────────────────────────────────────────────────────────────────────

def test_tc_p1_best_by_net_reward_risk(monkeypatch):
    out = run(monkeypatch, [cand(1, "AAA")], quotes=LIVE)
    it = out["items"][0]
    # bull call spread at live 4.0 / 1.0: debit 300, max gain 700 -> R:R ~2.3 net; shares: (12 - costs) / (8 + costs) ~1.5
    assert it["chosen"]["key"] == "bull_call_spread"
    keys = [a["key"] for a in it["alternatives"]]
    assert keys[0] == "shares" and "bull_put_spread" in keys
    bps = next(a for a in it["alternatives"] if a["key"] == "bull_put_spread")
    assert not bps["eligible"] and bps["why"].startswith("Failed its checks")
    sh = next(a for a in it["alternatives"] if a["key"] == "shares")
    assert sh["eligible"] and sh["body"]["quantity"] == 400 and sh["reward_risk_net"] < it["chosen"]["reward_risk_net"]
    assert out["market"]["live"] is True and out["capital"]["starting_capital_rs"] == 1e7


def test_tc_p1_tie_goes_to_the_lower_max_loss():
    a = {"key": "x", "eligible": True, "reward_risk_net": 2.0, "max_loss_rs": -9000.0}
    b = {"key": "y", "eligible": True, "reward_risk_net": 2.0, "max_loss_rs": -4000.0}
    c = {"key": "z", "eligible": False, "reward_risk_net": 9.0, "max_loss_rs": -100.0}
    d = {"key": "w", "eligible": True, "reward_risk_net": None, "max_loss_rs": -100.0}
    assert [x["key"] for x in P.rank([a, c, d, b])][:2] == ["y", "x"]


def test_tc_p1_not_live_skips_everything(monkeypatch):
    out = run(monkeypatch, [cand(1, "AAA")], quotes={"source": None, "why": "feed_not_live", "quotes": {}})
    it = out["items"][0]
    assert it["chosen"] is None and "Kite live feed is not running" in it["skipped_reason"] and out["market"]["live"] is False


def test_tc_p1_gate_block_and_missing_option_quotes(monkeypatch):
    def gate(body):
        if body.get("symbol"):
            return {"outcome": "block", "approved_qty": 0, "reasons": [{"code": "sector_limit", "message": "Sector at its 25% cap."}]}
        return {"outcome": "allow", "approved_lots": 1}
    out = run(monkeypatch, [cand(1, "AAA")], quotes=LIVE, gate=gate,
              option_quotes={"available": False, "reason": "no Kite access token is stored for the platform feed", "quotes": {}})
    it = out["items"][0]
    assert it["chosen"] is None
    whys = " | ".join(a.get("why") or "" for a in it["alternatives"])
    assert "Sector at its 25% cap." in whys and "No live option quotes: no Kite access token" in whys
    assert it["skipped_reason"].startswith("Nothing qualifies")


def test_tc_p1_live_price_outside_the_plan(monkeypatch):
    below = {"source": "kite_live", "quotes": {"AAA": {"ltp": 91.0}}}
    it = run(monkeypatch, [cand(1, "AAA")], quotes=below, strategies=())["items"][0]
    assert it["chosen"] is None and "at or below the Stop loss" in it["alternatives"][0]["why"]
    above = {"source": "kite_live", "quotes": {"AAA": {"ltp": 113.0}}}
    it = run(monkeypatch, [cand(1, "AAA")], quotes=above, strategies=())["items"][0]
    assert "already at or above Target 1" in it["alternatives"][0]["why"]


def test_tc_p1_stock_without_options_and_already_open(monkeypatch):
    out = run(monkeypatch, [cand(1, "BBB")], quotes=LIVE, fno=(), open_trades=[{"_id": "t1", "symbol": "BBB", "status": "open"}])
    it = out["items"][0]
    assert it["chosen"]["key"] == "shares" and it["open_trade"] == {"id": "t1", "status": "open"}


def test_tc_p1_top_10_only(monkeypatch):
    out = run(monkeypatch, [cand(i, f"S{i}") for i in range(1, 13)], quotes={"source": "kite_live", "quotes": {}}, fno=())
    assert len(out["items"]) == 10


# ── TC-P2 bodies ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_tc_p2_shares_body(monkeypatch):
    it = run(monkeypatch, [cand(1, "BBB")], quotes=LIVE, fno=())["items"][0]
    b = it["chosen"]["body"]
    assert b == {"symbol": "BBB", "quantity": 400, "entry_price": 100.0, "stop_price": 92.0, "target_price": 112.0,
                 "entry_rule": "at_once", "source": {"kind": "market_recovery", "bucket": "shares", "signal_date": "2026-11-03"},
                 "price_source": {"kind": "kite_live", "at": NOW.isoformat()}, "rationale": b["rationale"]}
    assert "Target 2 118.00" in b["rationale"] and it["chosen"]["idempotency_key"] == "mr-2026-11-04-BBB"
    assert it["chosen"]["max_loss_rs"] < 0 < it["chosen"]["max_gain_rs"]


def test_tc_p2_structure_body(monkeypatch):
    it = run(monkeypatch, [cand(1, "AAA")], quotes=LIVE)["items"][0]
    b = it["chosen"]["body"]
    assert b["kind"] == "strategy" and b["underlying"] == "AAA" and b["family"] == "bull_call_spread" and b["direction"] == "bullish"
    assert b["reference_price"] == 100.0 and b["stop_underlying"] == 92.0 and b["target_underlying"] == 112.0
    assert [(l["side"], l["option_type"], l["strike"], l["entry_price"], l["lots"], l["lot_size"], l["expiry"]) for l in b["legs"]] == [
        ("buy", "call", 100.0, 4.0, 1, 100, "2026-11-23"), ("sell", "call", 110.0, 1.0, 1, 100, "2026-11-23")]
    assert all(l["price_source"] == "Kite live 09:40 IST" for l in b["legs"])
    assert b["signal"]["source_refs"] == [{"kind": "market_recovery", "ref": "AAA:bull_call_spread", "as_of": "2026-11-03"}]
    assert b["signal"]["rule_version"] == "recovery-plan-v1"


def test_tc_p2_wording():
    import re
    from tests.test_compliance_wording_lint import hits
    plan_words = re.compile(r"\b(?:entry zone|stop loss|target 1|target 2)\b", re.I)     # the owner's words for this page
    texts = [P.RULE, *P.NOTES]
    assert [t for t in texts if hits(plan_words.sub(" ", t))] == []


def test_tc_p2_share_costs_scale_with_quantity():
    small, big = P.shares_costs(1, 100.0, 112.0), P.shares_costs(400, 100.0, 112.0)
    assert 0 < small < big < 400 * 12                      # never more than the gain of 400 shares
