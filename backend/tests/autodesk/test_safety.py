"""AD-91, AD-92 (AD-90 is tests/test_order_path_guard.py, run alongside): the desk touches no paper/live trading store
and no order path, and the text its agents write avoids advice words (owner rule 3 Nov)."""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from autodesk import contracts as C
from autodesk.agents.trading_assistant import TradingAssistant
from tests.autodesk import marketdata as md
from tests.autodesk.conftest import run
from tests.autodesk.test_middle_office_policy import _review
from tests.autodesk.test_risk_engine import assess, book, bull_call

PKG = Path(__file__).resolve().parents[2] / "autodesk"

# AD-91: other features' stores and the write paths of the existing paper / risk services
FORBIDDEN = [r"\bpaper_accounts\b", r"\bpaper_account_ledger\b", r"\bdesk_paper_trades\b", r"\brisk_decisions\b",
             r"\bspt_\w+", r"risk_gate\.service\b", r"\bservice\.(enter|gather|enforce)\b", r"\brisk_book\b",
             r"\bplan_sizing\b", r"\b(place|modify|cancel)_order\b", r"\b(place|modify|cancel)_gtt\b",
             r"\bkiteconnect\b", r"\bbreeze_connect\b"]

# AD-92: words generated text must not use (whole words, case-insensitive; plurals included)
ADVICE = re.compile(r"\b(buys?|sells?|stop[- ]?loss(es)?|sl|targets?|entry|entries|exits?|accumulat\w*|book(ing)? "
                    r"profits?|upside|price targets?|recommend\w*|picks?)\b", re.IGNORECASE)


def test_ad91_no_foreign_stores_or_order_paths():
    hits = []
    for f in sorted(PKG.rglob("*.py")):
        text = f.read_text()
        for pat in FORBIDDEN:
            for m in re.finditer(pat, text):
                line = text[:m.start()].count("\n") + 1
                hits.append(f"{f.relative_to(PKG)}:{line}: {m.group(0)}")
    # the design document names what is NOT called; the code must not
    assert hits == [], hits


def _texts(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [t for v in obj.values() for t in _texts(v)]
    if isinstance(obj, (list, tuple)):
        return [t for v in obj for t in _texts(v)]
    return []


def _narrative_of_plan(p: C.TradePlanBody) -> list[str]:
    return ([p.thesis] + p.rationale + p.risk_warnings + _texts(p.expected_payoff.get("assumptions"))
            + [str(p.invalidation.get("rule", ""))] + _texts(p.exit_rules) + _texts(p.margin_estimate.get("method"))
            + _texts(p.volatility.get("iv_source")) + _texts(p.liquidity.get("note")))


def test_ad92_generated_text_has_no_advice_words():
    S, D = C.Segment, C.Direction
    signals = [md.signal("PLAINCO", S.CASH, D.BULLISH, ref="500", inv="480", targets=["550"]),
               md.signal("ACME", S.FUTURES, D.BULLISH, ref="1000", inv="960", targets=["1080", "1120"]),
               md.signal("ACME", S.FUTURES, D.BEARISH, ref="1000", inv="1040", targets=["920"],
                         category=C.SignalCategory.SHORT_BUILDUP),
               md.signal("IDX", S.INDEX, D.NEUTRAL, ref="24000", inv=None, category=C.SignalCategory.RANGE_BOUND),
               md.signal("ACME", S.FUTURES, D.BULLISH, ref="1000", inv="960", targets=["1080"])]
    texts: list[str] = []
    for i, sig in enumerate(signals):
        acct = md.account(starting_capital_rs=Decimal("100000")) if i == 4 else md.account()     # → NO_TRADE
        ctx = md.ctx(md.view(), {"session_date": md.SD.isoformat(), "signal": sig.model_dump(mode="json")}, acct=acct)
        res = run(TradingAssistant().run(md.task(C.TaskType.GENERATE_STRATEGY), ctx))
        prop = C.StrategyProposal.model_validate(res.output)
        texts += [res.summary] + prop.reasons + [a.get("skip") or "" for a in prop.alternatives] \
            + [a.get("rule_note") or "" for a in prop.alternatives]
        if prop.plan:
            texts += _narrative_of_plan(prop.plan)
    plan = bull_call()
    for a in (assess(plan), assess(plan, bk=book(6_000_000)), assess(plan, facts={"data_age_sessions": 3}),
              assess(plan, acct=md.account(status="SUSPENDED"))):
        texts += [c.detail for c in a.checks] + a.warnings + [str(a.sizing.get("method")),
                                                              str(a.sizing.get("capital_method"))]
    for kw in ({}, {"mode": "ASSISTED"}, {"mode": "RESEARCH"}, {"score": "60"}):
        d, _ = _review(**kw)
        texts += d.reasons
    bad = sorted({f"{m.group(0)!r} in: {t}" for t in texts for m in ADVICE.finditer(t)})
    assert len(texts) > 80 and bad == [], bad


def test_production_agents_are_the_real_ones():
    from autodesk.agents.registry import default_agents
    from autodesk.market.pit import PitMarketView
    agents = default_agents()
    assert set(agents) == set(C.AgentKey)
    for key, a in agents.items():
        d = a.descriptor
        assert d.agent_key == key and d.version.startswith("autodesk-") and d.kind == "DETERMINISTIC"
        for tool in a.market_tools():
            assert callable(getattr(PitMarketView, tool, None)), f"{key.value} lists unknown tool {tool}"
