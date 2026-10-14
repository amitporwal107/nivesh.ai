"""An advisor who works in the Copilot app's investor or trader persona is
asking about their OWN holdings and positions, so `/chat/stream` answers from
their own portfolio with the tool-using engine. The cross-client book belongs
to the advisor persona only.

Regression guard for: an advisor on the Trader desk clicked a broker position
("Show the COLPAL chart with support and resistance…") and the chat answered
from the client book — "The workspace has no clients linked" — with no tool
step, because only the workspace type decided the path.
"""
from __future__ import annotations

import asyncio

import pytest

import routes.chat as chat

CHART_QUESTION = (
    "Show the COLPAL chart with support and resistance. "
    "My broker account has an open position of 550 at an average of ₹35.88."
)


# ── The rule ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("persona", ["investor", "trader", "Trader", " INVESTOR "])
def test_an_own_portfolio_persona_takes_an_advisor_off_the_client_book(persona):
    assert chat._advisor_mode_for(True, persona) is False


@pytest.mark.parametrize("persona", [None, "", "advisor", "ADVISOR", "mfd", "admin", 7, ["trader"], {"mode": "trader"}])
def test_any_other_persona_leaves_an_advisor_on_the_client_book(persona):
    # No persona is what the older chat surfaces send: nothing changes for them.
    assert chat._advisor_mode_for(True, persona) is True


@pytest.mark.parametrize("persona", [None, "advisor", "trader", "investor", "anything"])
def test_a_persona_never_puts_a_non_advisor_on_the_client_book(persona):
    assert chat._advisor_mode_for(False, persona) is False


def test_the_chart_question_is_not_a_research_phrase_so_the_persona_is_what_routes_it():
    # If this ever becomes True the route tests below stop proving the persona rule.
    assert chat._is_research_tool_intent(CHART_QUESTION) is False


# ── The route ────────────────────────────────────────────────────────────
class _Cursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def sort(self, *_a, **_k):
        return self

    async def to_list(self, _n=None):
        return list(self._rows)


class _Coll:
    def __init__(self, name, log, rows=()):
        self.name, self.log, self.rows = name, log, list(rows)

    async def find_one(self, query=None, *_a, **_k):
        self.log.append((f"{self.name}.find_one", query))
        return None

    async def insert_one(self, doc):
        self.log.append((f"{self.name}.insert_one", doc.get("role")))

    async def update_one(self, *_a, **_k):
        return None

    async def count_documents(self, *_a, **_k):
        return 2  # not the first message: no auto-title

    def find(self, query=None, *_a, **_k):
        self.log.append((f"{self.name}.find", query))
        return _Cursor(self.rows)


class _Db:
    def __init__(self, log):
        self.chat_sessions = _Coll("chat_sessions", log)
        self.chat_messages = _Coll("chat_messages", log)
        self.user_profiles = _Coll("user_profiles", log)
        self.holdings = _Coll("holdings", log, rows=[
            {"user_id": "advisor1", "name": "Own Share Ltd", "ticker": "OWNSHARE", "asset_type": "equity",
             "quantity": 10, "buy_price": 100, "current_price": 110},
        ])


class _Request:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


@pytest.fixture
def advisor_chat(monkeypatch):
    """`/chat/stream` for a caller who owns an advisory workspace and is at
    its root. Records which portfolio the route reads; the stream itself is
    never consumed, so no engine runs."""
    log = []

    async def current_user(_request):
        return {"user_id": "advisor1"}

    async def is_advisor(_session_user_id, _active_profile_id):
        return True

    async def book(owner_user_id):
        log.append(("advisor_book", owner_user_id))
        return "(no clients)"

    async def no_cache_bust(*_a, **_k):
        return None

    monkeypatch.setattr(chat, "get_current_user", current_user)
    monkeypatch.setattr(chat, "_is_advisor_caller", is_advisor)
    monkeypatch.setattr(chat, "_advisor_book_block", book)
    monkeypatch.setattr(chat, "_bust_chat_cache", no_cache_bust)
    monkeypatch.setattr(chat, "db", _Db(log))

    def ask(**extra):
        body = {"message": CHART_QUESTION, "session_id": "sess_fixture", **extra}
        asyncio.run(chat.stream_chat(_Request(body)))
        return log

    return ask


def _read_the_book(log):
    return ("advisor_book", "advisor1") in log


def _read_own_holdings(log):
    return ("holdings.find", {"user_id": "advisor1"}) in log


@pytest.mark.parametrize("persona", ["trader", "investor"])
def test_an_advisor_in_the_trader_or_investor_persona_is_answered_from_their_own_holdings(advisor_chat, persona):
    log = advisor_chat(persona=persona)
    assert _read_own_holdings(log) and not _read_the_book(log)


def test_an_advisor_in_the_advisor_persona_is_still_answered_from_the_client_book(advisor_chat):
    log = advisor_chat(persona="advisor")
    assert _read_the_book(log) and not _read_own_holdings(log)


def test_a_chat_surface_that_sends_no_persona_behaves_as_before(advisor_chat):
    log = advisor_chat()
    assert _read_the_book(log) and not _read_own_holdings(log)


def test_an_unknown_persona_is_ignored_rather_than_trusted(advisor_chat):
    log = advisor_chat(persona="superuser")
    assert _read_the_book(log) and not _read_own_holdings(log)
