"""GET /api/copilot/suggested-prompts: the app's mode picks the prompt set.

Bug (owner screenshot, 31 Oct 2026): a Trader-mode screen showed "Which clients should I call today?" and "ranked for your
client book" in the ask box, because the route chose the advisor list from the account alone (it owns an advisory
workspace) and the app sent no mode. The owner's rule: an advisor-workspace account in Investor or Trader mode works on
its own holdings and positions; the client book belongs to Advisor mode only. Trader mode gets the Daily Trader questions.

The route function is called directly; the workspace lookup and the user are stubbed (no DB, no LLM).
"""
from __future__ import annotations

import asyncio
import re

import pytest

try:
    import routes.copilot_prompts as cp
    from services.copilot_visual import resolve_intent
except Exception as exc:  # noqa: BLE001
    pytest.skip(f"app runtime not importable here: {exc}", allow_module_level=True)


class _Reached(Exception):
    """Raised by the stubbed investor path: the route fell through to the portfolio prompts."""


@pytest.fixture
def route(monkeypatch):
    async def user(_request):
        return {"user_id": "u1", "email": "x@example.com"}

    async def build_context(_uid):
        raise _Reached()
    monkeypatch.setattr(cp, "get_current_user", user)
    monkeypatch.setattr(cp, "_build_context", build_context)

    def call(mode, advisory):
        async def is_advisor(_uid, _pid):
            return advisory
        monkeypatch.setattr(cp, "_is_advisor_mode", is_advisor)
        return asyncio.run(cp.suggested_prompts(object(), persona=None, category=None, mode=mode))
    return call


@pytest.mark.parametrize("mode", ["trader", "TRADER", " trader "])
def test_pm1_an_advisor_workspace_owner_in_trader_mode_gets_the_trader_questions(route, mode):
    out = route(mode, advisory=True)
    assert out["mode"] == "trader"
    assert not any(p["id"].startswith("advisor_") for p in out["prompts"])
    assert out["prompts"][0]["label"] == "What is the market view today?"


def test_pm2_trader_mode_for_an_ordinary_account_is_the_trader_list_too(route):
    assert route("trader", advisory=False)["mode"] == "trader"


def test_pm3_the_client_book_is_for_advisor_mode_or_an_older_client_with_no_mode(route):
    assert route("advisor", advisory=True)["mode"] == "advisor"
    assert route(None, advisory=True)["mode"] == "advisor"
    assert route("nonsense", advisory=True)["mode"] == "advisor"          # an unknown mode is no mode


@pytest.mark.parametrize("mode,advisory", [("investor", True), ("investor", False), ("advisor", False), (None, False)])
def test_pm4_everything_else_reaches_the_investors_own_portfolio_prompts(route, mode, advisory):
    with pytest.raises(_Reached):
        route(mode, advisory)


def test_pm5_every_trader_question_opens_its_visual_answer(route):
    out = route("trader", advisory=False)
    seen = set()
    for p in out["prompts"]:
        name = p["id"].removeprefix("trader_")
        got = resolve_intent(p["query"], "trader", None)
        if name == "avoid_today":                      # Q14 has no visual answer yet: it takes the usual chat path
            assert got is None
        else:
            assert got is not None and got.name == name, (p["query"], got)
            seen.add(name)
        assert p["badge"] is None and p["viz"] is None          # no figure is made up here
        assert not re.search(r"\b(buy now|strong buy|recommended|pick)\b", p["label"] + p["outcome"] + p["query"], re.I)
    assert len({p["id"] for p in out["prompts"]}) == len(out["prompts"])


def test_pm6_the_top_five_cover_the_five_entry_points(route):
    first = route("trader", advisory=False)["prompts"][:5]
    assert [p["intent_category"] for p in first] == ["market_pulse", "opportunities", "positions", "fno", "risk"]
