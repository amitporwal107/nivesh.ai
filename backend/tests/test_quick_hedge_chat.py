"""Quick Hedge in Copilot chat: the portfolio_hedge intent (which questions it takes and which it must not), what a question states, the
payload built from the real service result, and the flag gate in prepare(). The three service reads are faked; the calculator,
the cost card and the visual-answer contract check (validate) run for real."""
import asyncio
from datetime import date

import pytest

from services import market_freshness
from services.copilot_visual import builders, intents, prepare, readers as rd
from services.copilot_visual.intents import Intent, hedge_params, resolve_intent
from services.copilot_visual.payload import facts, validate
from services.quick_hedge import service

TODAY, FLOOR = date(2026, 10, 31), date(2026, 10, 30)
WINDOW = market_freshness.Window(today=TODAY, floor=FLOOR, calendar_checked=True)
SPOT = 23_000.0


def _puts():
    p = {float(k): round(120 * 4 ** (-((SPOT - k) / 50 - 23) / 46), 2) for k in range(19_000, 23_001, 50)}
    p[21_850.0], p[19_550.0] = 120.0, 30.0
    return p


PF = {"portfolio_value_rs": 2_500_000.0, "hedgeable_value_rs": 2_000_000.0, "beta": 1.0, "beta_coverage": 1.0,
      "excluded_rs": {"hybrid": 300_000.0, "debt": 0.0, "gold": 200_000.0, "overseas": 0.0, "other": 0.0, "unclassified": 0.0},
      "holdings": [{"key": "A", "value_rs": 2_000_000.0}], "reasons": [], "as_of": "2026-10-30"}
MARKET = {"ok": True, "as_of": "2026-10-30", "spot": SPOT, "lot": 65, "expiry": "2026-12-01", "days_to_expiry": 32, "tenor": "1m",
          "expiries": ["2026-11-03", "2026-12-01"], "puts": _puts(), "source": "NSE"}
FIT = {"r2": 0.83, "correlation": 0.91, "regression_beta": 1.0, "observations": 252, "coverage": 0.95, "series_used": 3,
       "window_start": "2025-10-31", "window_end": "2026-10-30", "reason": None}


class Fake:
    def __init__(self, pf=None, market=None, fit=None):
        self._pf, self._market, self._fit = pf or PF, market or MARKET, fit or FIT

    async def portfolio(self, db, uid):
        return self._pf

    async def market(self, tenor):
        return self._market

    async def fit(self, pf):
        return self._fit


@pytest.fixture
def world(monkeypatch):
    state = {"fake": Fake(), "fail": False, "calls": []}

    async def window():
        return WINDOW

    async def quick_hedge(uid, **kw):
        state["calls"].append((uid, kw))
        if state["fail"]:
            raise RuntimeError("MOCK quick hedge down")
        return await service.run(None, uid, readers=state["fake"], **kw)
    monkeypatch.setattr(rd, "window", window)
    monkeypatch.setattr(rd, "quick_hedge", quick_hedge)
    return state


def build(params=None, **kw):
    p = asyncio.run(builders.build(Intent("portfolio_hedge", params=params or {}), {"user_id": "u1"}, request="REQ", **kw))
    assert validate(p) == [], validate(p)
    return p


def blk(p, bid):
    return next((b for b in p["blocks"] if b.get("id") == bid), None)


# ── which questions are ours ───────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("message", [
    "Should I consider protecting my portfolio?", "Protect my portfolio against a 15% fall", "Hedge my portfolio",
    "I don't want to lose more than ₹1 lakh", "What happens if Nifty falls 10%?", "What happens if the market falls?",
    "Show me different hedge ideas.", "What type of hedge addresses my biggest risk?", "What is the cheapest protection option?",
    "How much protection should I consider?", "How much of my portfolio would this hedge protect?", "What happens when the hedge expires?",
    "Make my portfolio hedge cheaper", "downside protection for my holdings",
])
def test_hedge_questions_are_taken(message):
    assert resolve_intent(message).name == "portfolio_hedge"


@pytest.mark.parametrize("message,name", [
    ("What is the expected move in Nifty?", "expected_move"), ("How much should I risk?", "position_size"),
    ("What is the market view today?", "market_view"),
    ("How is my portfolio doing?", None), ("Is my portfolio too risky?", None), ("What are my biggest risks?", None),
    ("Are hedge funds a good investment?", None), ("Hedge my TCS position", None), ("Should I exit INFY, my stop loss is hit", "exit_options"),
])
def test_other_questions_keep_their_own_path(message, name):
    got = resolve_intent(message)
    assert (got.name if got else None) == name


def test_the_hedge_check_does_not_open_the_portfolio_gate_for_other_portfolio_questions():
    assert resolve_intent("What is my portfolio XIRR?") is None and resolve_intent("Rebalance my portfolio") is None


# ── what a question states ─────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("message,expected", [
    ("Protect my portfolio against a 15% fall", {"expected_fall_pct": 15.0}),
    ("What happens if Nifty falls 20%?", {"expected_fall_pct": 20.0}),
    ("I don't want to lose more than ₹1 lakh", {"tolerance_rs": 100_000.0}),
    ("I can afford to lose 2 crore, protect my portfolio", {"tolerance_rs": 20_000_000.0}),
    ("hedge my portfolio, I can lose up to 50k", {"tolerance_rs": 50_000.0}),
    ("protect my portfolio, I can lose at most 3%", {"tolerance_pct": 3.0}),
    ("protect my holdings against a 12% correction for two weeks", {"expected_fall_pct": 12.0, "tenor": "2w"}),
    ("protect my portfolio for 3 months", {"tenor": "3m"}), ("hedge my portfolio for a month", {"tenor": "1m"}),
    ("Make my portfolio hedge cheaper", {"mode": "lowest_cost"}), ("Show the scenarios for the maximum protection hedge", {"mode": "maximum"}),
    ("hedge my portfolio against a 60% fall", {}),                       # beyond the 50% the engine accepts: not read, so a default is said
    ("hedge my portfolio", {}),
])
def test_what_the_question_states(message, expected):
    assert hedge_params(message) == expected


# ── the answer ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_default_answer_has_size_choices_a_scenario_table_and_says_what_it_assumed(world):
    p = build()
    assert p["intent"] == "portfolio_hedge" and p["as_of"] == "2026-10-30"
    assert [b["type"] for b in p["blocks"] if b["type"] != "notice"] == ["kpis", "kpis", "ranked", "ranked"]
    assert "Balanced" in p["headline"]["text"] and "21,850 put" in p["headline"]["text"] and "₹100,000.00 loss" in p["headline"]["text"]
    choices, scen = blk(p, "choices"), blk(p, "scenarios")
    assert [r["cells"]["choice"] for r in choices["rows"]] == ["Balanced", "Maximum protection", "Lowest cost"]
    assert all(r["ask"] for r in choices["rows"])
    assert len(scen["rows"]) == 7 and sum(1 for r in scen["rows"] if r["tone"] == "warn") == 1
    flat = next(r for r in scen["rows"] if r["cells"]["move"] == "+0.00%")
    assert flat["cells"]["hedge"].startswith("−₹7,") and flat["cells"]["without"] == "₹0.00"
    assumed = blk(p, "assumed")["text"]
    assert "10% fall" in assumed and "5% of your equity-linked holdings" in assumed and "about a month" in assumed
    assert "Paper only" in blk(p, "paper-only")["text"]
    assert p["data_quality"]["missing"] == [] and not p["data_quality"]["stale"]


def test_everything_stated_means_nothing_is_assumed(world):
    p = build({"expected_fall_pct": 15.0, "tolerance_rs": 100_000.0, "tenor": "1m"})
    assert blk(p, "assumed") is None
    assert world["calls"][0][1] == {"expected_fall_pct": 15.0, "tenor": "1m", "tolerance_rs": 100_000.0, "tolerance_pct": None}


def test_asking_about_the_cheaper_choice_shows_its_scenarios_and_its_two_legs(world):
    p = build({"mode": "lowest_cost", "expected_fall_pct": 15.0, "tolerance_rs": 100_000.0})
    assert blk(p, "scenarios")["title"].startswith("Lowest cost")
    assert "sell the 19,550 put" in p["headline"]["text"]


def test_a_portfolio_under_one_lot_says_so_and_shows_no_hedge(world):
    world["fake"] = Fake(pf={**PF, "portfolio_value_rs": 1_100_000.0, "hedgeable_value_rs": 1_000_000.0})
    p = build()
    assert "smaller than one efficient index-option hedge lot" in p["headline"]["text"]
    assert blk(p, "scenarios") is None and blk(p, "choices") is None and blk(p, "portfolio") is not None


def test_a_poor_fit_shows_the_scenarios_but_says_the_hedge_cannot_be_placed(world):
    world["fake"] = Fake(fit={**FIT, "r2": 0.18, "correlation": 0.42})
    p = build()
    assert blk(p, "scenarios") is not None and p["headline"]["tone"] == "warn"
    assert "poor hedge" in blk(p, "no-place")["text"]


def test_missing_market_data_is_said_first_and_no_hedge_figure_appears(world):
    world["fake"] = Fake(market={"ok": False, "reason": {"code": "market_data_unavailable", "message": "The data platform is unavailable."}})
    p = build()
    assert "data platform is unavailable" in p["headline"]["text"] and p["headline"]["tone"] == "warn"
    assert blk(p, "scenarios") is None and blk(p, "choices") is None


def test_a_failed_service_gives_a_valid_payload_that_names_the_missing_source(world):
    world["fail"] = True
    p = build()
    assert p["data_quality"]["missing"] and "Quick Hedge" in p["data_quality"]["missing"][0]
    assert not [b for b in p["blocks"] if b["type"] in ("kpis", "ranked")]


def test_the_engine_is_given_figures_and_the_no_recommendation_rule(world):
    text = facts(build())
    assert "never say" in text and "Balanced" in text and "21,850" in text


# ── the flag gate ──────────────────────────────────────────────────────────────────────────────────────────────
def test_with_the_flag_off_the_question_takes_the_usual_chat_path(world, monkeypatch):
    async def off(user):
        return False
    monkeypatch.setattr(rd, "hedge_enabled", off)
    assert asyncio.run(prepare("REQ", {"user_id": "u1", "email": "x@example.com"}, "Protect my portfolio against a 15% fall", None, None, None)) is None
    assert world["calls"] == []


def test_with_the_flag_on_the_answer_is_pinned_to_the_portfolio_analyst(world, monkeypatch):
    async def on(user):
        return True
    monkeypatch.setattr(rd, "hedge_enabled", on)
    v = asyncio.run(prepare("REQ", {"user_id": "u1", "email": "x@example.com"}, "Protect my portfolio against a 15% fall", None, None, None))
    assert v is not None and v.intent.name == "portfolio_hedge" and v.agent == "portfolio_analyst"
    assert v.widget["data"]["intent"] == "portfolio_hedge" and "VISUAL_ANSWER" in v.facts
