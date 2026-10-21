"""AI Trader Phase 2, the Strategy Architect (services/ai_trader/strategy.py; PRD F2.2-F2.6 and the Phase 2
bullets of docs/prd/AI_TRADER_PHASES_2_5.prd.md section 5).

No network, no Postgres and no Mongo. Replaced, and by what:
  * `strategy_engine.backtest.run_backtest`   a fake async runner that records every call and answers with the
                                              metrics the test wants (one test binds those recorded calls against
                                              the real `run_backtest` signature, so the injected shape is proven)
  * the strategy document                     a plain dict, the way `new_strategy` builds it

Everything else runs for real: the repo's own DSL templates are loaded from disk and validated by the real
`strategy_engine.dsl.validate_strategy`, the real `ai_trader.config.resolve` freezes the config, and the sealed
window dates come from the real `research.charting.research_window` through `_research.load()`.

MOCK - not real data: every metrics dict, paper tally and evidence record below is made up. No number here is a
measured backtest result.

Worked examples
  folds     2021-01-01..2021-12-31 is 365 days over 4 folds, 365 = 4*91 + 1, so the first fold takes the spare day:
            92 days (01-01..04-02), then 91, 91, 91, ending exactly on 12-31
  gates     backtest win rate 55 and paper win rate 40 gives a gap of 15, which passes at the threshold of 15;
            paper 39.9 gives 15.1 and fails
  run gate  a stored run of {"reason": "no_data"}, or one with trade_count 0, fails draft -> backtested: it measured
            nothing. trade_count 1 is the least that counts
  evidence  the gates never default to the one-shot sealed-block run, and the assisted win-rate gap is measured
            against the run that earned paper, so a 2-trade window run afterwards changes no baseline
  basis     only a universe basis the providers prove point-in-time passes; "latest_snapshot" (the DaaS label on
            staging and prod) and "unknown" fail. Only a run that declares sizing_basis "portfolio" can satisfy
            the two gates whose thresholds are percentages of capital
  no losers profit_factor None with win rate 100 and a return of 18 % passes the profit-factor criterion, because
            the engine divides by a total loss of 0 there; the same None at a return of 0 % or with a 99.9 % win
            rate fails
  version   spec_version is the first 16 hex chars of sha256 over canonical JSON, so {"a":1,"b":2} and {"b":2,"a":1}
            hash the same while a single changed threshold does not
"""
from __future__ import annotations

import ast
import asyncio
import copy
import inspect
import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from services.ai_trader import _research
from services.ai_trader import strategy as st
from services.ai_trader.config import ConfigFrozenError, ConfigValidationError
from services.strategy_engine import market_data
from services.strategy_engine.backtest import run_backtest
from services.strategy_engine.dsl import validate_strategy

_ctx, _regime, rw, _rs = _research.load()

SEALED_START = rw.SEALED_GAP_START.date()
SEALED_END = rw.SEALED_GAP_END.date()

SYMBOLS = ["RELIANCE", "TCS"]
AS_OF = "2022-12-30"


# ── evidence builders (MOCK - not real data) ─────────────────────────────────
def regime_item(value: str = "BULL", *, as_of: str = AS_OF) -> Dict[str, Any]:
    """The shape `ai_trader.context.market_context` returns for the regime item. MOCK - not real data."""
    return {"skill": "market_intelligence", "symbol": None, "as_of": as_of, "horizon": "market",
            "observation": f"NIFTY 500 regime is {value}.", "interpretation": "...", "confidence": 0.5,
            "decision_impact": "neutral", "status": "OK", "reason_code": None, "calibrated": False,
            "contradictions": [], "conditions": [], "sources": [{"name": "NIFTY_500.csv", "timestamp": as_of}],
            "data": {"regime": {"value": value, "status": "OK", "reason": None}}}


def vix_item() -> Dict[str, Any]:
    """An OK market-intelligence item with no regime in it. MOCK - not real data."""
    item = regime_item()
    item["data"] = {"india_vix": 14.2}
    item["observation"] = "India VIX closed at 14.20."
    return item


def unavailable_regime_item() -> Dict[str, Any]:
    item = regime_item()
    item.update({"status": "UNAVAILABLE", "reason_code": "SEALED_GAP", "confidence": 0.0, "data": {}})
    return item


def evidence_for(value: str = "BULL") -> List[Dict[str, Any]]:
    return [regime_item(value), vix_item()]


# ── metrics builders (MOCK - not real data) ──────────────────────────────────
def metrics(**over: Any) -> Dict[str, Any]:
    """A passing backtest metrics dict with the keys `_compute_metrics` returns plus the provider's basis.
    MOCK - not real data."""
    base = {"trade_count": 120, "win_rate": 55.0, "avg_win_pct": 4.0, "avg_loss_pct": -2.0, "profit_factor": 1.6,
            "max_drawdown_pct": -12.0, "total_return_pct": 18.0, "starting_capital": 1_000_000.0,
            "ending_capital": 1_180_000.0, "avg_holding_days": 11.0,
            "price_basis": "adjusted", "universe_basis": "point_in_time",
            # `strategy_engine.backtest` does not report this key: its drawdown and return are per-share rupees
            # against the starting capital. The fixture declares the basis so the other criteria can be exercised;
            # test_the_percent_of_capital_gates_hold_an_engine_run_with_no_sizing_basis covers the engine's shape.
            "sizing_basis": st.PORTFOLIO_SIZING_BASIS}
    base.update(over)
    return base


def walk(*returns: float) -> List[Dict[str, Any]]:
    """A walk-forward list with one fold per return given. MOCK - not real data."""
    return [{"fold": i, "from_date": "2021-01-01", "to_date": "2021-04-02",
             "metrics": {"trade_count": 30, "total_return_pct": r}}
            for i, r in enumerate(returns, start=1)]


def paper_stats(**over: Any) -> Dict[str, Any]:
    """A passing paper tally. MOCK - not real data."""
    base = {"closed_trades": 25, "expectancy": 350.0, "profit_factor": 1.4, "win_rate": 50.0}
    base.update(over)
    return base


# ── the injected runner ──────────────────────────────────────────────────────
class FakeResult:
    def __init__(self, m: Dict[str, Any]):
        self.metrics = m
        self.trades: List[Any] = []
        self.equity_curve: List[Any] = []


class FakeRunner:
    """Same call shape as `strategy_engine.backtest.run_backtest`, answering from a queue of metrics dicts.
    The first answer serves the full window, the rest serve the folds in order."""

    def __init__(self, *answers: Dict[str, Any]):
        self.answers = list(answers) or [metrics()]
        self.calls: List[Dict[str, Any]] = []

    async def __call__(self, pool, spec, *, from_date, to_date, **kwargs):
        self.calls.append({"pool": pool, "spec": spec, "from_date": from_date, "to_date": to_date, **kwargs})
        i = len(self.calls) - 1
        return FakeResult(copy.deepcopy(self.answers[i] if i < len(self.answers) else self.answers[-1]))


@pytest.fixture
def loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


def draft(regime_value: str = "BULL", **over: Any) -> Dict[str, Any]:
    doc = st.new_strategy("user_a", st.propose(evidence_for(regime_value), symbols=SYMBOLS))
    doc.update(over)
    return doc


def stored_run(run_id: str, m: Dict[str, Any], *, holdout: bool = False,
               returns: Any = (5.0, 4.0, 3.0, -1.0),
               window: Any = ("2021-01-01", "2021-12-31")) -> Dict[str, Any]:
    """A run in the shape `run_backtest_for` stores on the document. MOCK - not real data."""
    return {"run_id": run_id, "metrics": m, "walk_forward": walk(*returns),
            "window": {"from_date": window[0], "to_date": window[1]}, "holdout": holdout}


def backtested(**over: Any) -> Dict[str, Any]:
    doc = draft()
    doc["stage"] = "backtested"
    doc["runs"] = [stored_run("r1", metrics())]
    doc.update(over)
    return doc


def at_paper(*runs: Dict[str, Any], **over: Any) -> Dict[str, Any]:
    doc = draft()
    doc["stage"] = "paper"
    doc["runs"] = list(runs)
    doc.update(over)
    return doc


# ── F2.2 regime to template, DSL validity ────────────────────────────────────
@pytest.mark.parametrize("regime_value,template", [("BULL", "momentum_breakout"), ("SIDEWAYS", "mean_reversion"),
                                                   ("BEAR", "accumulation")])
def test_regime_picks_template_and_spec_is_dsl_valid(regime_value, template):
    out = st.propose(evidence_for(regime_value), symbols=SYMBOLS)
    assert out["template"] == template
    assert out["regime"] == regime_value
    assert st.TEMPLATES_BY_REGIME[regime_value] == template
    assert validate_strategy(out["spec"]) == []
    assert out["spec"]["name"].startswith("AI ")
    assert len(out["spec"]["name"]) <= 100


def test_every_mapped_template_on_disk_validates():
    for name in st.TEMPLATES_BY_REGIME.values():
        assert validate_strategy(st.load_template(name)) == [], name


def test_propose_records_the_evidence_it_used():
    ev = evidence_for("BULL") + [unavailable_regime_item()]
    out = st.propose(ev, symbols=SYMBOLS)
    prov = out["provenance"]
    assert prov["as_of"] == AS_OF
    assert prov["regime_evidence"]["skill"] == "market_intelligence"
    assert prov["regime_evidence"]["sources"] == [{"name": "NIFTY_500.csv", "timestamp": AS_OF}]
    assert prov["evidence_considered"] == 3
    assert prov["unavailable"] == ["SEALED_GAP"]


def test_provenance_says_the_backtest_universe_is_the_template_index_not_the_symbols():
    # The requested symbols cannot narrow the spec: the DSL custom universe takes a stored universe id, not a symbol
    # list. The proposal has to say so out loud rather than let the caller assume it bought a two-symbol strategy.
    out = st.propose(evidence_for("BULL"), symbols=SYMBOLS)
    uni = out["provenance"]["universe"]
    assert uni["backtest_universe"] == {"type": "index", "ref": "NIFTY500"} == out["spec"]["universe"]
    assert uni["requested_symbols"] == SYMBOLS
    assert "NiveshConfig only" in uni["note"] and "do not narrow the strategy" in uni["note"]

    sideways = st.propose(evidence_for("SIDEWAYS"), symbols=["INFY"])
    assert sideways["provenance"]["universe"]["backtest_universe"]["ref"] == "NIFTY200"
    assert sideways["provenance"]["universe"]["requested_symbols"] == ["INFY"]


@pytest.mark.parametrize("ev", [
    [],
    [unavailable_regime_item()],
    [vix_item()],                                                  # OK, but carries no regime
    [dict(regime_item(), skill="technical")],                      # a regime from the wrong skill is not the regime
    [dict(regime_item(), data={"regime": {"value": None, "status": "UNAVAILABLE", "reason": "NO_DATA"}})],
])
def test_no_regime_means_no_strategy(ev):
    with pytest.raises(st.StrategyError) as e:
        st.propose(ev, symbols=SYMBOLS)
    assert str(e.value) == "regime_unavailable"


def test_unknown_regime_never_falls_back_to_a_template():
    with pytest.raises(st.StrategyError) as e:
        st.propose(evidence_for("CHOPPY"), symbols=SYMBOLS)
    assert str(e.value) == "unknown_regime"


def test_propose_accepts_evidence_objects_as_well_as_dicts():
    from services.ai_trader.evidence import Evidence

    item = Evidence(skill="market_intelligence", symbol=None, as_of=AS_OF, horizon="market",
                    observation="NIFTY 500 regime is BEAR.", interpretation="...", confidence=0.5,
                    decision_impact="opposes", data={"regime": {"value": "BEAR", "status": "OK", "reason": None}})
    assert st.propose([item], symbols=SYMBOLS)["template"] == "accumulation"


def test_load_template_refuses_a_path_fragment_or_unknown_name():
    for name in ["../config", "missing_template", "", "a/b", None]:
        with pytest.raises(st.StrategyError) as e:
            st.load_template(name)
        assert str(e.value) == "unknown_template"


# ── F2.1 config is resolved, validated and frozen ────────────────────────────
def test_proposal_stores_the_frozen_resolved_config():
    out = st.propose(evidence_for(), symbols=SYMBOLS, ui_config={"initial_capital": 250_000.0})
    cfg = out["config"]
    assert cfg["symbols"] == SYMBOLS
    assert cfg["initial_capital"] == 250_000.0
    assert cfg["commission_pct"] == 0.05 and cfg["pyramiding"] == 0 and cfg["short_margin_pct"] == 100.0
    assert cfg["schema_version"] == 1
    json.dumps(cfg)                                   # the doc is stored in Mongo, so it must serialise


def test_strategy_info_may_set_capital_and_custom_keys_only():
    out = st.propose(evidence_for(), symbols=SYMBOLS,
                     strategy_info=lambda c: (setattr(c, "initial_capital", 500_000.0),
                                              setattr(c, "lookback", 20)))
    assert out["config"]["initial_capital"] == 500_000.0
    assert out["config"]["custom"] == {"lookback": 20}

    with pytest.raises(ConfigFrozenError):
        st.propose(evidence_for(), symbols=SYMBOLS, strategy_info=lambda c: setattr(c, "pyramiding", 3))
    with pytest.raises(ConfigValidationError):
        st.propose(evidence_for(), symbols=SYMBOLS, strategy_info=lambda c: setattr(c, "bad", {1, 2}))


# ── F2.3 the record and its version hash ─────────────────────────────────────
def test_version_hash_is_stable_and_16_hex():
    out = st.propose(evidence_for(), symbols=SYMBOLS)
    v = st.spec_version(out["spec"], out["config"])
    assert len(v) == 16 and all(c in "0123456789abcdef" for c in v)
    assert v == st.spec_version(out["spec"], out["config"])
    assert v == st.spec_version(copy.deepcopy(out["spec"]), copy.deepcopy(out["config"]))

    reordered = {k: out["spec"][k] for k in reversed(list(out["spec"]))}
    assert st.spec_version(reordered, out["config"]) == v, "key order must not change the version"

    tuned = copy.deepcopy(out["spec"])
    tuned["exit"]["stoploss_pct"] = 7
    assert st.spec_version(tuned, out["config"]) != v

    other_cfg = dict(out["config"], initial_capital=2_000_000.0)
    assert st.spec_version(out["spec"], other_cfg) != v


def test_new_strategy_document():
    out = st.propose(evidence_for("SIDEWAYS"), symbols=SYMBOLS)
    doc = st.new_strategy("user_a", out)
    assert doc["user_id"] == "user_a" and doc["created_by"] == "ai"
    assert doc["stage"] == "draft" and doc["stage"] in st.STAGES
    assert doc["version"] == st.spec_version(out["spec"], out["config"])
    assert doc["template"] == "mean_reversion" and doc["regime"] == "SIDEWAYS"
    assert doc["runs"] == [] and doc["holdout_used"] is False
    assert doc["stage_history"][0]["stage"] == "draft" and doc["stage_history"][0]["from"] is None
    assert doc["name"] == out["spec"]["name"]
    assert st.new_strategy("user_a", out, "My breakout")["name"] == "My breakout"
    assert st.new_strategy("user_a", out)["_id"] != doc["_id"]

    for bad in [{}, {"spec": {}}, {"config": {}, "template": "x", "regime": "BULL"}, None, "x"]:
        with pytest.raises(st.StrategyError):
            st.new_strategy("user_a", bad)
    with pytest.raises(st.StrategyError):
        st.new_strategy("  ", out)
    with pytest.raises(st.StrategyError):
        st.new_strategy("user_a", out, "  ")


# ── F2.6 folds ───────────────────────────────────────────────────────────────
def test_folds_cover_the_window_exactly():
    start, end = date(2021, 1, 1), date(2021, 12, 31)
    fs = st.folds(start, end)
    assert len(fs) == 4
    assert fs[0][0] == start and fs[-1][1] == end
    assert fs[0] == (date(2021, 1, 1), date(2021, 4, 2))          # 365 = 4*91 + 1, the spare day goes first
    lengths = [(b - a).days + 1 for a, b in fs]
    assert lengths == [92, 91, 91, 91]
    assert sum(lengths) == (end - start).days + 1
    for (_, prev_end), (next_start, _) in zip(fs, fs[1:]):
        assert (next_start - prev_end).days == 1                   # contiguous and non-overlapping


@pytest.mark.parametrize("n", [1, 2, 3, 4, 7, 12])
def test_folds_for_any_count(n):
    start, end = date(2020, 2, 3), date(2022, 11, 17)
    fs = st.folds(start, end, n)
    assert len(fs) == n
    assert fs[0][0] == start and fs[-1][1] == end
    assert all(b >= a for a, b in fs)
    assert sum((b - a).days + 1 for a, b in fs) == (end - start).days + 1


def test_folds_refuse_a_window_too_short_or_backwards():
    with pytest.raises(st.StrategyError) as e:
        st.folds(date(2021, 1, 1), date(2021, 1, 3), 4)            # 3 days cannot make 4 folds of a day each
    assert str(e.value) == "window_too_short_for_folds"
    assert len(st.folds(date(2021, 1, 1), date(2021, 1, 4), 4)) == 4
    with pytest.raises(st.StrategyError):
        st.folds(date(2021, 12, 31), date(2021, 1, 1))
    with pytest.raises(st.StrategyError):
        st.folds(date(2021, 1, 1), date(2021, 12, 31), 0)


@pytest.mark.parametrize("start,end", [(date(2019, 1, 1), date(2022, 12, 31)),
                                       (date(2024, 8, 1), date(2026, 9, 30)),
                                       (date(2021, 6, 1), date(2022, 12, 31))])
def test_no_fold_lands_inside_the_sealed_block(start, end):
    for a, b in st.folds(start, end):
        assert not rw.overlaps_sealed_gap(a, b), f"fold {a}..{b} touches the sealed block"


def test_folds_of_the_sealed_window_are_all_inside_it():
    # The only window whose folds may touch the block is the holdout window itself.
    for a, b in st.folds(SEALED_START, SEALED_END):
        assert rw.overlaps_sealed_gap(a, b)


# ── F2.4 backtests, the sealed block and the one-shot holdout ────────────────
def test_run_backtest_for_returns_the_run_summary(loop):
    doc = draft()
    runner = FakeRunner(metrics(), *[{"trade_count": 30, "total_return_pct": r} for r in (5.0, 4.0, 3.0, -1.0)])
    out = loop.run_until_complete(st.run_backtest_for(
        doc, from_date="2021-01-01", to_date="2021-12-31", runner=runner))

    assert set(out) >= {"metrics", "resolved_config", "window", "holdout", "walk_forward"}
    assert out["window"] == {"from_date": "2021-01-01", "to_date": "2021-12-31"}
    assert out["holdout"] is False
    assert out["metrics"]["trade_count"] == 120
    assert [f["fold"] for f in out["walk_forward"]] == [1, 2, 3, 4]
    assert [f["metrics"]["total_return_pct"] for f in out["walk_forward"]] == [5.0, 4.0, 3.0, -1.0]
    assert out["walk_forward"][0]["from_date"] == "2021-01-01"
    assert out["walk_forward"][-1]["to_date"] == "2021-12-31"
    assert out["resolved_config"]["initial_capital"] == 1_000_000.0
    assert out["resolved_config"]["schema_version"] == 1
    assert len(runner.calls) == 5                                   # the full window plus one call per fold
    assert runner.calls[0]["from_date"] == date(2021, 1, 1) and runner.calls[0]["to_date"] == date(2021, 12, 31)
    assert runner.calls[1]["to_date"] == date(2021, 4, 2)
    assert runner.calls[0]["starting_capital"] == 1_000_000.0
    assert runner.calls[0]["slippage_pct"] == pytest.approx(0.0005)  # commission_pct 0.05 per side as a fraction
    assert doc["runs"][-1]["run_id"] == out["run_id"]               # recorded on the document for the gates
    assert doc["holdout_used"] is False


def test_run_backtest_for_keeps_the_custom_config_keys(loop):
    doc = st.new_strategy("user_a", st.propose(evidence_for(), symbols=SYMBOLS,
                                              ui_config={"initial_capital": 300_000.0},
                                              strategy_info=lambda c: setattr(c, "lookback", 20)))
    out = loop.run_until_complete(st.run_backtest_for(
        doc, from_date=date(2021, 1, 1), to_date=date(2021, 12, 31), runner=FakeRunner()))
    assert out["resolved_config"]["initial_capital"] == 300_000.0
    assert out["resolved_config"]["custom"] == {"lookback": 20}


def test_the_injected_runner_call_matches_run_backtest(loop):
    doc = draft()
    runner = FakeRunner()
    loop.run_until_complete(st.run_backtest_for(doc, from_date="2021-01-01", to_date="2021-12-31", runner=runner))
    sig = inspect.signature(run_backtest)
    for call in runner.calls:
        kwargs = {k: v for k, v in call.items() if k not in ("pool", "spec")}
        sig.bind(call["pool"], call["spec"], **kwargs)              # raises if production would reject the call


@pytest.mark.parametrize("start,end", [
    ("2022-06-01", "2023-02-01"),          # starts clear, runs into the block
    ("2023-01-01", "2024-07-31"),          # exactly the block
    ("2023-05-01", "2023-06-01"),          # wholly inside
    ("2024-07-31", "2025-01-01"),          # starts on the last sealed day
    ("2022-01-01", "2026-01-01"),          # spans it
])
def test_a_window_overlapping_the_sealed_block_is_refused(loop, start, end):
    doc = draft()
    runner = FakeRunner()
    with pytest.raises(st.SealedWindowRefused):
        loop.run_until_complete(st.run_backtest_for(doc, from_date=start, to_date=end, runner=runner))
    assert runner.calls == [], "nothing may be run on a refused window"
    assert doc["holdout_used"] is False
    assert doc["runs"] == []


@pytest.mark.parametrize("start,end", [("2022-11-01", "2022-12-31"), ("2024-08-01", "2025-08-01")])
def test_a_window_beside_the_block_is_allowed(loop, start, end):
    doc = draft()
    out = loop.run_until_complete(st.run_backtest_for(doc, from_date=start, to_date=end, runner=FakeRunner()))
    assert out["holdout"] is False


def test_the_holdout_opens_the_block_exactly_once(loop):
    doc = draft()
    out = loop.run_until_complete(st.run_backtest_for(
        doc, from_date=SEALED_START, to_date=SEALED_END, runner=FakeRunner(), holdout=True))
    assert out["holdout"] is True
    assert doc["holdout_used"] is True
    assert doc["holdout_window"] == {"from_date": "2023-01-01", "to_date": "2024-07-31"}

    with pytest.raises(st.HoldoutUsed):
        loop.run_until_complete(st.run_backtest_for(
            doc, from_date="2023-03-01", to_date="2023-09-01", runner=FakeRunner(), holdout=True))
    assert len(doc["runs"]) == 1

    # The seal being spent does not block an ordinary window.
    loop.run_until_complete(st.run_backtest_for(
        doc, from_date="2021-01-01", to_date="2021-12-31", runner=FakeRunner()))
    assert len(doc["runs"]) == 2


def test_holdout_flag_outside_the_block_is_an_ordinary_run(loop):
    doc = draft()
    out = loop.run_until_complete(st.run_backtest_for(
        doc, from_date="2021-01-01", to_date="2021-12-31", runner=FakeRunner(), holdout=True))
    assert out["holdout"] is False
    assert doc["holdout_used"] is False


def test_a_bad_window_or_spec_runs_nothing(loop):
    runner = FakeRunner()
    with pytest.raises(st.StrategyError):
        loop.run_until_complete(st.run_backtest_for(
            draft(), from_date="2021-12-31", to_date="2021-01-01", runner=runner))
    with pytest.raises(st.StrategyError) as e:
        loop.run_until_complete(st.run_backtest_for(
            draft(), from_date="2021-01-01", to_date="2021-01-03", runner=runner))
    assert str(e.value) == "window_too_short_for_folds"

    broken = draft()
    broken["spec"]["ranking"]["by"] = "made_up_field"
    with pytest.raises(st.StrategyError) as e:
        loop.run_until_complete(st.run_backtest_for(
            broken, from_date="2021-01-01", to_date="2021-12-31", runner=runner))
    assert str(e.value).startswith("invalid_spec")
    assert runner.calls == []


# ── F2.5 gates, one failing and one passing case per criterion ───────────────
def rows_by_code(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {r["code"]: r for r in rows}


def test_every_gate_row_has_the_value_and_the_threshold():
    for stage, gates in st.GATES.items():
        rows = st.evaluate_gates(stage, metrics(), walk_forward=walk(1.0, 1.0, 1.0, 1.0),
                                 paper_stats=paper_stats())
        assert [r["code"] for r in rows] == [g.code for g in gates]
        for r, g in zip(rows, gates):
            assert set(r) == {"code", "label", "value", "threshold", "passed"}
            assert r["threshold"] == g.threshold and r["label"].startswith(g.label)
            assert isinstance(r["passed"], bool)


@pytest.mark.parametrize("m,passed,value", [
    (None, False, None),                                            # nothing stored at all
    ({}, False, None),                                              # a run document with empty metrics
    ({"reason": "no_data"}, False, None),                           # the engine's no-session window
    ({"reason": "no_data", "trade_count": 5}, False, 5),            # no_data wins even if a count rode along
    ({"trade_count": 0}, False, 0),                                 # a run that opened no trade measured nothing
    ({"trade_count": None}, False, None),
    ({"trade_count": "lots"}, False, "lots"),
    ({"trade_count": 1}, True, 1),                                  # the minimum that counts as measured
    (metrics(), True, 120),
])
def test_backtested_gate_needs_a_run_that_measured_something(m, passed, value):
    # Deviation from B3, which asks only for "a stored backtest run": a run that measured nothing is not evidence.
    row = st.evaluate_gates("backtested", m)[0]
    assert row["code"] == "backtest_run"
    assert row["passed"] is passed and row["value"] == value
    assert row["threshold"] == st.MIN_RUN_TRADE_COUNT == 1


def test_a_no_data_run_cannot_promote_a_draft(loop):
    doc = draft()
    loop.run_until_complete(st.run_backtest_for(
        doc, from_date="2021-01-01", to_date="2021-12-31", runner=FakeRunner({"reason": "no_data"})))
    assert doc["runs"][-1]["metrics"] == {"reason": "no_data"}       # the run is stored, honestly
    with pytest.raises(st.GateNotMet) as e:
        st.promote(doc, "backtested")
    assert [r["code"] for r in e.value.unmet] == ["backtest_run"]


@pytest.mark.parametrize("code,fail_metrics,pass_metrics", [
    ("trade_count", {"trade_count": 99}, {"trade_count": 100}),
    ("trade_count", {"trade_count": None}, {"trade_count": 100}),
    ("profit_factor", {"profit_factor": 1.29}, {"profit_factor": 1.3}),
    ("profit_factor", {"profit_factor": None}, {"profit_factor": 1.3}),
    ("max_drawdown_pct", {"max_drawdown_pct": -25.01}, {"max_drawdown_pct": -25.0}),
    ("total_return_pct", {"total_return_pct": 0.0}, {"total_return_pct": 0.01}),
    ("universe_basis", {"universe_basis": "present_day_fallback"}, {"universe_basis": "point_in_time"}),
    # Rewritten: this pair used to assert that "latest_snapshot" PASSES, which was the defect. That is the label
    # DaasMarketDataProvider puts on today's index membership applied across the whole window, the same
    # survivorship bias as present_day_fallback under another name, so it is a failing case now.
    ("universe_basis", {"universe_basis": "latest_snapshot"}, {"universe_basis": "custom_universe"}),
])
def test_paper_gate_criterion_fails_and_passes(code, fail_metrics, pass_metrics):
    wf = walk(5.0, 4.0, 3.0, -1.0)
    failing = rows_by_code(st.evaluate_gates("paper", metrics(**fail_metrics), walk_forward=wf))[code]
    passing = rows_by_code(st.evaluate_gates("paper", metrics(**pass_metrics), walk_forward=wf))[code]
    assert failing["passed"] is False and failing["value"] == fail_metrics[code]
    assert passing["passed"] is True and passing["value"] == pass_metrics[code]


def provider_universe_bases() -> List[str]:
    """Every `universe_basis` label `strategy_engine.market_data` can report, read out of that module so the gate's
    allowlist cannot drift away from the providers that feed it."""
    tree = ast.parse(Path(market_data.__file__).read_text(encoding="utf-8"))
    out: set = set()

    def literals(node: Any) -> set:
        return {n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)}

    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "universe_basis":
                    out |= literals(value)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if (isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant)
                        and target.slice.value == "universe_basis"):
                    out |= literals(node.value)
    return sorted(out)


def test_the_universe_basis_gate_decides_every_label_the_providers_can_report():
    # An allowlist, so a label nobody has proven point-in-time fails by default. The equality below is deliberate:
    # a new provider label must be classified here, not quietly let through the gate.
    assert provider_universe_bases() == ["custom_universe", "latest_snapshot", "point_in_time",
                                         "present_day_fallback", "unknown"]
    wf = walk(5.0, 4.0, 3.0, -1.0)
    for label in provider_universe_bases():
        row = rows_by_code(st.evaluate_gates("paper", metrics(universe_basis=label), walk_forward=wf))[
            "universe_basis"]
        assert row["passed"] is (label in st.ACCEPTED_UNIVERSE_BASIS), label
        assert row["value"] == label
    assert "latest_snapshot" not in st.ACCEPTED_UNIVERSE_BASIS   # the staging/prod DaaS label: same bias
    assert "present_day_fallback" not in st.ACCEPTED_UNIVERSE_BASIS
    assert "unknown" not in st.ACCEPTED_UNIVERSE_BASIS           # the providers' pre-prepare default


@pytest.mark.parametrize("basis", [None, "", "unknown", "latest_snapshot", "present_day_fallback", "POINT_IN_TIME",
                                   "something_new", 1, True])
def test_an_unproven_universe_basis_never_passes(basis):
    row = rows_by_code(st.evaluate_gates("paper", metrics(universe_basis=basis),
                                         walk_forward=walk(5.0, 4.0, 3.0, -1.0)))["universe_basis"]
    assert row["passed"] is False and row["value"] == basis
    assert row["threshold"] == st.ACCEPTED_UNIVERSE_BASIS


def test_the_percent_of_capital_gates_hold_an_engine_run_with_no_sizing_basis():
    # The engine now sizes positions and declares `sizing_basis = "portfolio"`, but the check stays for any run that
    # does not: a caller injecting its own runner, or a run stored before the engine was fixed, whose percentages
    # may still be the old per-share rupees over the full capital rather than percentages of capital. B3's -25 %
    # and >0 % thresholds speak about the latter, so an undeclared run cannot satisfy those two rows.
    engine_metrics = {k: v for k, v in metrics().items() if k != "sizing_basis"}
    rows = rows_by_code(st.evaluate_gates("paper", engine_metrics, walk_forward=walk(5.0, 4.0, 3.0, -1.0)))
    for code in ("max_drawdown_pct", "total_return_pct"):
        assert rows[code]["passed"] is False, code
        assert rows[code]["value"] == engine_metrics[code], "the number it does have is still shown"
        assert "not measured" in rows[code]["label"]
    assert rows["trade_count"]["passed"] is True, "only the percent-of-capital rows are held back"
    assert rows["profit_factor"]["passed"] is True


@pytest.mark.parametrize("basis,passed", [(st.PORTFOLIO_SIZING_BASIS, True), ("per_share", False),
                                          (None, False), ("", False), ("PORTFOLIO", False)])
def test_only_a_portfolio_sizing_basis_satisfies_a_percent_of_capital_gate(basis, passed):
    rows = rows_by_code(st.evaluate_gates("paper", metrics(sizing_basis=basis),
                                          walk_forward=walk(5.0, 4.0, 3.0, -1.0)))
    assert rows["max_drawdown_pct"]["passed"] is passed
    assert rows["total_return_pct"]["passed"] is passed


@pytest.mark.parametrize("over,passed,why", [
    ({"profit_factor": None, "win_rate": 100.0, "total_return_pct": 18.0}, True, "no losses to divide by"),
    ({"profit_factor": None, "win_rate": 100.0, "total_return_pct": 0.0}, False, "flat, so not a winning run"),
    ({"profit_factor": None, "win_rate": 100.0, "total_return_pct": -3.0}, False, "negative return"),
    ({"profit_factor": None, "win_rate": 99.9, "total_return_pct": 18.0}, False, "losers present"),
    ({"profit_factor": None, "win_rate": 55.0, "total_return_pct": 18.0}, False, "losers present"),
    ({"profit_factor": None, "win_rate": None, "total_return_pct": 18.0}, False, "win rate unknown"),
    ({"profit_factor": None, "win_rate": 100.0, "total_return_pct": None}, False, "return unknown"),
    ({"profit_factor": None, "win_rate": 100.0, "total_return_pct": 18.0, "trade_count": 0}, False, "no trades"),
    ({"profit_factor": "n/a", "win_rate": 100.0, "total_return_pct": 18.0}, False, "not a number"),
])
def test_an_undefined_profit_factor_passes_only_with_zero_losers_and_a_profit(over, passed, why):
    # `_compute_metrics` returns None for profit_factor when total_loss is 0, which means "nothing to divide by",
    # not "bad". That one case passes; the value stays the real None so nobody reads a number that was never there.
    row = rows_by_code(st.evaluate_gates("paper", metrics(**over), walk_forward=walk(5.0, 4.0, 3.0, -1.0)))[
        "profit_factor"]
    assert row["passed"] is passed, why
    assert row["value"] == over["profit_factor"]
    assert row["threshold"] == st.MIN_PROFIT_FACTOR
    assert ("no losing trades" in row["label"]) is passed


def test_all_paper_gates_pass_for_a_flawless_run():
    rows = st.evaluate_gates("paper", metrics(profit_factor=None, win_rate=100.0, avg_loss_pct=0.0),
                             walk_forward=walk(5.0, 4.0, 3.0, -1.0))
    assert all(r["passed"] for r in rows), [r for r in rows if not r["passed"]]


def test_an_undefined_paper_profit_factor_still_fails_the_assisted_gate():
    # The assisted gate reads our own paper tally, which carries no return to prove a None means "no losses".
    row = rows_by_code(st.evaluate_gates("assisted", metrics(), paper_stats=paper_stats(profit_factor=None)))[
        "paper_profit_factor"]
    assert row["passed"] is False and row["value"] is None


@pytest.mark.parametrize("returns,positive,passed", [
    ((5.0, 4.0, 3.0, -1.0), 3, True),
    ((5.0, 4.0, 3.0, 2.0), 4, True),
    ((5.0, 4.0, -3.0, -1.0), 2, False),
    ((0.0, 0.0, 0.0, 0.0), 0, False),
    ((), 0, False),
])
def test_walk_forward_fold_gate(returns, positive, passed):
    row = rows_by_code(st.evaluate_gates("paper", metrics(), walk_forward=walk(*returns)))[
        "walk_forward_positive_folds"]
    assert row["value"] == positive and row["passed"] is passed
    assert row["threshold"] == 3


def test_walk_forward_gate_fails_when_no_folds_were_reported():
    row = rows_by_code(st.evaluate_gates("paper", metrics()))["walk_forward_positive_folds"]
    assert row["value"] == 0 and row["passed"] is False


def test_all_paper_gates_pass_together():
    rows = st.evaluate_gates("paper", metrics(), walk_forward=walk(5.0, 4.0, 3.0, -1.0))
    assert all(r["passed"] for r in rows), [r for r in rows if not r["passed"]]


@pytest.mark.parametrize("code,fail_stats,pass_stats", [
    ("paper_closed_trades", {"closed_trades": 19}, {"closed_trades": 20}),
    ("paper_expectancy", {"expectancy": 0.0}, {"expectancy": 0.01}),
    ("paper_expectancy", {"expectancy": -10.0}, {"expectancy": 10.0}),
    ("paper_profit_factor", {"profit_factor": 1.19}, {"profit_factor": 1.2}),
])
def test_assisted_gate_criterion_fails_and_passes(code, fail_stats, pass_stats):
    failing = rows_by_code(st.evaluate_gates("assisted", metrics(), paper_stats=paper_stats(**fail_stats)))[code]
    passing = rows_by_code(st.evaluate_gates("assisted", metrics(), paper_stats=paper_stats(**pass_stats)))[code]
    assert failing["passed"] is False and failing["value"] == fail_stats[code.replace("paper_", "")]
    assert passing["passed"] is True


def test_win_rate_gap_gate():
    # backtest win rate 55: paper 40 is a gap of exactly 15 and passes, 39.9 is 15.1 and fails.
    rows = rows_by_code(st.evaluate_gates("assisted", metrics(win_rate=55.0),
                                          paper_stats=paper_stats(win_rate=40.0)))
    assert rows["win_rate_gap"]["value"] == pytest.approx(15.0) and rows["win_rate_gap"]["passed"] is True
    rows = rows_by_code(st.evaluate_gates("assisted", metrics(win_rate=55.0),
                                          paper_stats=paper_stats(win_rate=39.9)))
    assert rows["win_rate_gap"]["value"] == pytest.approx(15.1) and rows["win_rate_gap"]["passed"] is False
    rows = rows_by_code(st.evaluate_gates("assisted", metrics(win_rate=55.0),
                                          paper_stats=paper_stats(win_rate=70.0)))
    assert rows["win_rate_gap"]["value"] == pytest.approx(15.0) and rows["win_rate_gap"]["passed"] is True
    # A gap cannot be computed without both numbers, and an unknown is never a pass.
    for m, s in [(metrics(win_rate=None), paper_stats()), (metrics(), paper_stats(win_rate=None)), (metrics(), None)]:
        row = rows_by_code(st.evaluate_gates("assisted", m, paper_stats=s))["win_rate_gap"]
        assert row["value"] is None and row["passed"] is False


def test_assisted_gates_fail_with_no_paper_history():
    rows = st.evaluate_gates("assisted", metrics(), paper_stats=None)
    assert [r["passed"] for r in rows] == [False, False, False, False]


def test_gates_for_draft_and_retired_are_empty_and_other_stages_are_rejected():
    assert st.evaluate_gates("draft", metrics()) == []
    assert st.evaluate_gates("retired", metrics()) == []
    for bad in ["live", "LIVE", "", "paper_trading", None, 3]:
        with pytest.raises(st.StrategyError) as e:
            st.evaluate_gates(bad, metrics())
        assert str(e.value) == "invalid_stage"


# ── F2.5 the stage machine ───────────────────────────────────────────────────
def test_one_stage_forward_when_the_gates_pass():
    doc = draft()
    out = st.promote(doc, "backtested", metrics=metrics())
    assert out["stage"] == "backtested"
    assert doc["stage"] == "draft", "promote returns a copy and leaves the caller's document alone"
    assert out["stage_history"][-1]["from"] == "draft"
    assert [r["code"] for r in out["stage_history"][-1]["gates"]] == ["backtest_run"]

    out = st.promote(out, "paper", metrics=metrics(), walk_forward=walk(5.0, 4.0, 3.0, -1.0))
    assert out["stage"] == "paper"
    out = st.promote(out, "assisted", metrics=metrics(), paper_stats=paper_stats())
    assert out["stage"] == "assisted"
    assert [h["stage"] for h in out["stage_history"]] == ["draft", "backtested", "paper", "assisted"]


def test_promotion_reads_the_last_stored_run_when_nothing_is_passed(loop):
    doc = draft()
    runner = FakeRunner(metrics(), *[{"trade_count": 30, "total_return_pct": r} for r in (5.0, 4.0, 3.0, -1.0)])
    loop.run_until_complete(st.run_backtest_for(doc, from_date="2021-01-01", to_date="2021-12-31", runner=runner))
    doc = st.promote(doc, "backtested")
    doc = st.promote(doc, "paper")
    assert doc["stage"] == "paper"


# ── F2.5 which run may back a gate (assumption B4, and B3's "the backtest") ──
def fold_answers(*returns: float) -> List[Dict[str, Any]]:
    """The per-fold answers a FakeRunner gives after the full-window one. MOCK - not real data."""
    return [{"trade_count": 30, "total_return_pct": r} for r in returns]


def test_the_sealed_block_run_is_never_the_default_gate_evidence(loop):
    # The one-shot holdout is a final report, not promotion evidence (assumption B4). A strategy whose only run is
    # the holdout has nothing a gate may read, so it is refused as unmeasured rather than promoted on sealed numbers.
    doc = draft()
    loop.run_until_complete(st.run_backtest_for(
        doc, from_date=SEALED_START, to_date=SEALED_END, holdout=True,
        runner=FakeRunner(metrics(), *fold_answers(5.0, 4.0, 3.0, 2.0))))
    assert doc["runs"][-1]["holdout"] is True

    with pytest.raises(st.GateNotMet) as e:
        st.promote(doc, "backtested")
    assert [r["code"] for r in e.value.unmet] == ["backtest_run"]
    assert e.value.unmet[0]["value"] is None


def test_a_weak_in_sample_run_is_not_rescued_by_the_sealed_block_run(loop):
    doc = draft()
    loop.run_until_complete(st.run_backtest_for(
        doc, from_date="2019-01-01", to_date="2022-12-31",
        runner=FakeRunner(metrics(trade_count=60, profit_factor=1.1), *fold_answers(5.0, 4.0, 3.0, 2.0))))
    doc = st.promote(doc, "backtested")
    loop.run_until_complete(st.run_backtest_for(
        doc, from_date=SEALED_START, to_date=SEALED_END, holdout=True,
        runner=FakeRunner(metrics(trade_count=140, profit_factor=1.45), *fold_answers(5.0, 4.0, 3.0, 2.0))))

    with pytest.raises(st.GateNotMet) as e:
        st.promote(doc, "paper")
    unmet = {r["code"]: r for r in e.value.unmet}
    assert set(unmet) == {"trade_count", "profit_factor"}
    assert unmet["trade_count"]["value"] == 60, "the in-sample run, not the holdout's 140"
    assert unmet["profit_factor"]["value"] == 1.1


def test_a_later_throwaway_run_does_not_become_the_win_rate_baseline():
    # The run that earned paper is the baseline the win-rate gap is measured against. A short exploratory window run
    # afterwards must not replace it, in either direction.
    throwaway = stored_run("r2", metrics(trade_count=2, win_rate=33.33, profit_factor=0.4,
                                         max_drawdown_pct=-40.0, total_return_pct=-2.0),
                           returns=(-1.0, -1.0, -1.0, -1.0), window=("2024-09-02", "2024-09-06"))
    doc = at_paper(stored_run("r1", metrics(win_rate=65.0)), throwaway,
                   paper_stats=paper_stats(win_rate=30.0))
    with pytest.raises(st.GateNotMet) as e:
        st.promote(doc, "assisted")
    gap = {r["code"]: r for r in e.value.unmet}["win_rate_gap"]
    assert gap["value"] == pytest.approx(35.0), "65 against the paper 30, not the throwaway's 33.33"

    flattering = stored_run("r2", metrics(trade_count=2, win_rate=90.0, profit_factor=0.4,
                                          max_drawdown_pct=-40.0, total_return_pct=-2.0),
                            returns=(-1.0, -1.0, -1.0, -1.0), window=("2024-09-02", "2024-09-06"))
    doc = at_paper(stored_run("r1", metrics(win_rate=55.0)), flattering,
                   paper_stats=paper_stats(win_rate=50.0))
    out = st.promote(doc, "assisted")
    assert out["stage"] == "assisted"
    rows = rows_by_code(out["stage_history"][-1]["gates"])
    assert rows["win_rate_gap"]["value"] == pytest.approx(5.0)
    assert out["stage_history"][-1]["evidence_run"]["run_id"] == "r1"


@pytest.mark.parametrize("runs,why", [
    ([stored_run("r1", metrics(trade_count=60, win_rate=55.0))], "no stored run ever met the paper criteria"),
    ([stored_run("h1", metrics(win_rate=65.0), holdout=True)], "the only qualifying run is the sealed one"),
    ([], "no run at all"),
])
def test_the_assisted_win_rate_gap_is_unavailable_without_the_run_that_earned_paper(runs, why):
    doc = at_paper(*runs, paper_stats=paper_stats(win_rate=50.0))
    with pytest.raises(st.GateNotMet) as e:
        st.promote(doc, "assisted")
    gap = {r["code"]: r for r in e.value.unmet}["win_rate_gap"]
    assert gap["value"] is None and gap["passed"] is False, why


def test_the_promotion_record_names_the_run_its_gates_were_read_from():
    doc = backtested()
    out = st.promote(doc, "paper")
    assert out["stage_history"][-1]["evidence_run"] == {
        "run_id": "r1", "window": {"from_date": "2021-01-01", "to_date": "2021-12-31"}}

    # Numbers the caller passed in are nobody's stored run, and the record says so rather than naming one.
    passed_in = st.promote(doc, "paper", metrics=metrics(), walk_forward=walk(5.0, 4.0, 3.0, -1.0))
    assert passed_in["stage_history"][-1]["evidence_run"] is None
    assert st.promote(out, "backtested")["stage_history"][-1]["evidence_run"] is None   # a demotion reads no gates


def test_a_caller_who_passes_metrics_still_gets_the_stored_runs_folds():
    # Each default stands on its own: passing `metrics` does not withdraw the stored run's walk-forward folds, which
    # would otherwise fail the fold criterion for a reason that has nothing to do with the strategy.
    out = st.promote(backtested(), "paper", metrics=metrics(trade_count=101))
    rows = rows_by_code(out["stage_history"][-1]["gates"])
    assert rows["trade_count"]["value"] == 101                   # the caller's number
    assert rows["walk_forward_positive_folds"]["value"] == 3     # the stored run's folds
    assert out["stage_history"][-1]["evidence_run"]["run_id"] == "r1"


def test_promotion_refused_by_a_gate_lists_what_was_unmet():
    doc = backtested()
    with pytest.raises(st.GateNotMet) as e:
        st.promote(doc, "paper", metrics=metrics(trade_count=40, profit_factor=0.9),
                   walk_forward=walk(-1.0, -2.0, 1.0, 1.0))
    unmet = {r["code"]: r for r in e.value.unmet}
    assert set(unmet) == {"trade_count", "profit_factor", "walk_forward_positive_folds"}
    assert unmet["trade_count"]["value"] == 40 and unmet["trade_count"]["threshold"] == 100
    assert all(r["passed"] is False for r in e.value.unmet)
    assert e.value.target_stage == "paper"
    assert doc["stage"] == "backtested", "a refused promotion changes nothing"


def test_a_draft_cannot_jump_a_stage():
    doc = draft()
    for target in ["paper", "assisted"]:
        with pytest.raises(st.StrategyError) as e:
            st.promote(doc, target, metrics=metrics(), walk_forward=walk(5.0, 4.0, 3.0, 1.0),
                       paper_stats=paper_stats())
        assert str(e.value) == "stage_skip"
    with pytest.raises(st.StrategyError) as e:
        st.promote(backtested(), "assisted", metrics=metrics(), paper_stats=paper_stats())
    assert str(e.value) == "stage_skip"


def test_promoting_to_the_same_stage_is_not_a_move():
    with pytest.raises(st.StrategyError) as e:
        st.promote(draft(), "draft")
    assert str(e.value) == "stage_skip"


@pytest.mark.parametrize("target", ["live", "LIVE", "autonomous", "", " ", "draft ", None, 7, ["paper"]])
def test_only_the_five_stages_exist(target):
    with pytest.raises(st.StrategyError) as e:
        st.promote(backtested(), target)
    assert str(e.value) == "invalid_stage"
    assert "live" not in st.STAGES


def test_a_document_with_an_unknown_stage_is_rejected():
    with pytest.raises(st.StrategyError) as e:
        st.promote(draft(stage="live"), "paper")
    assert str(e.value) == "invalid_stage"


def test_demotion_and_retirement_need_no_gates():
    doc = draft()
    doc["stage"] = "assisted"
    for target in ["paper", "backtested", "draft"]:
        out = st.promote(doc, target)
        assert out["stage"] == target
        assert out["stage_history"][-1]["gates"] == []
    for stage in st.LADDER:
        out = st.promote(draft(stage=stage), "retired")
        assert out["stage"] == "retired"


def test_a_retired_strategy_is_not_promoted_back():
    for target in ["draft", "backtested", "paper", "assisted"]:
        with pytest.raises(st.StrategyError) as e:
            st.promote(draft(stage="retired"), target, metrics=metrics())
        assert str(e.value) == "stage_skip"
    with pytest.raises(st.StrategyError):
        st.promote(draft(stage="retired"), "retired")


# ── the hard boundary ────────────────────────────────────────────────────────
def test_the_module_imports_nothing_that_can_place_an_order():
    src = Path(st.__file__).read_text(encoding="utf-8")
    names: List[str] = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
    banned = ("broker", "kite", "upstox", "angel", "fyers", "zerodha", "order", "dhan", "motilal", "icici")
    assert not [n for n in names if any(b in n.lower() for b in banned)], names
