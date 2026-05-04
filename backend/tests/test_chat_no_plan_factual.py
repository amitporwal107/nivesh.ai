"""Smoke tests for chat behaviour when the user has NO active action plan.

Two regressions guarded:

1. (Prompt loosening) A factual question — "which funds overlap the most?" —
   used to be refused with "V2 hasn't flagged any actions yet" because the
   system prompt forbade ungrounded answers. The new prompt allows answering
   such questions directly from the Portfolio Intelligence block.

2. (Auto plan generation) An actionable question — "which fund should I
   exit with minimum tax impact?" — used to bottom out on the same refusal.
   The chat routes now auto-generate an action plan in-line when the
   message looks actionable and the user has none, so the AI can cite real
   actions on the very same turn.

Strategy: impersonate a real client (Ahaan porwal — 93 holdings, no active
plan) by writing `active_profile_id` onto the advisor's session row, fire
the chat call, then revert. This avoids needing a separate session fixture.
"""
from __future__ import annotations

import asyncio
import json
import os

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ.get("NIVESH_TEST_BASE_URL", "http://localhost:8001")
ADVISOR_TOKEN = os.environ.get(
    "NIVESH_TEST_USER_TOKEN", "5770bebb-8a9a-41f7-a7b9-e8152ac25daa"
)
HEADERS = {
    "Authorization": f"Bearer {ADVISOR_TOKEN}",
    "Content-Type": "application/json",
}

# Ahaan porwal — CLIENT profile under aporwal107's ADVISORY workspace.
# Has 93 holdings; we assert this in setup so the test fails loudly if
# the seed data ever moves.
AHAAN_PROFILE_NAME = "Ahaan porwal"


# ─────────────────────────────────────────────────────────────────────────
# Fixture: switch the advisor's session into impersonation of Ahaan, then
# put it back when the test is done. Clears any auto-generated plan so the
# next run starts from "no plan" again.
# ─────────────────────────────────────────────────────────────────────────
@pytest.fixture
def impersonate_ahaan():
    db_name = os.environ.get("DB_NAME", "test_database")
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")

    async def _setup():
        cli = AsyncIOMotorClient(mongo_url)
        db = cli[db_name]
        prof = await db.profiles.find_one(
            {"name": AHAAN_PROFILE_NAME, "type": "CLIENT"},
            {"_id": 0, "profile_id": 1, "shadow_user_id": 1},
        )
        assert prof, f"seed data missing: client profile {AHAAN_PROFILE_NAME}"
        shadow = prof["shadow_user_id"]
        n_holdings = await db.holdings.count_documents({"user_id": shadow})
        assert n_holdings >= 10, f"seed has only {n_holdings} holdings for {shadow}"
        # Wipe any pre-existing plan so we test the "no plan" path cleanly
        await db.action_plans.delete_many({"user_id": shadow})
        # Switch session into impersonation
        await db.user_sessions.update_one(
            {"session_token": ADVISOR_TOKEN},
            {"$set": {"active_profile_id": prof["profile_id"]}},
        )
        cli.close()
        return shadow

    async def _teardown(shadow):
        cli = AsyncIOMotorClient(mongo_url)
        db = cli[db_name]
        await db.user_sessions.update_one(
            {"session_token": ADVISOR_TOKEN},
            {"$set": {"active_profile_id": None}},
        )
        await db.action_plans.delete_many({"user_id": shadow})
        cli.close()

    shadow_uid = asyncio.get_event_loop().run_until_complete(_setup())
    yield shadow_uid
    asyncio.get_event_loop().run_until_complete(_teardown(shadow_uid))


def _post_send(message: str) -> str:
    r = requests.post(
        f"{BASE_URL}/api/chat/send",
        headers=HEADERS,
        json={"message": message},
        timeout=180,
    )
    assert r.status_code == 200, f"send failed: {r.status_code} {r.text[:300]}"
    payload = r.json()
    return ((payload.get("ai_message") or {}).get("content") or "").strip()


# ─────────────────────────────────────────────────────────────────────────
# (1) Factual prompt-loosening test: should NOT refuse with the old
#     "V2 hasn't flagged any actions" line on a factual question.
# ─────────────────────────────────────────────────────────────────────────
def test_factual_overlap_question_answered_without_plan(impersonate_ahaan):
    reply = _post_send(
        "Which mutual funds in my portfolio overlap the most? "
        "Just tell me the top pair and the overlap percentage — "
        "I'm not asking for a recommendation."
    )
    assert reply, "empty reply"
    lower = reply.lower()
    # Must NOT contain the old refusal phrasing
    assert "v2 hasn't flagged" not in lower, f"still using V2 refusal: {reply[:400]!r}"
    assert "v2 hasn't" not in lower, f"V2 brand leaked: {reply[:400]!r}"
    # Must look like a factual answer — either an overlap % or a fund-pair shape
    has_overlap_signal = any(tok in lower for tok in ("overlap", "%", "shared", "↔", "vs."))
    assert has_overlap_signal, f"reply doesn't read as a factual overlap answer: {reply[:400]!r}"


# ─────────────────────────────────────────────────────────────────────────
# (2) Auto-plan-gen test: actionable question + no plan should generate
#     a plan in-line so the answer can cite a concrete action, AND the DB
#     should end up with an active plan for that user.
# ─────────────────────────────────────────────────────────────────────────
def test_shared_companies_are_named_in_overlap_answer(impersonate_ahaan):
    """The AI must name actual shared companies (e.g. HDFC Bank, Reliance,
    Infosys) when asked which companies overlap between funds — not punt
    with 'I don't have specific company-level overlap data'."""
    reply = _post_send(
        "Can you name the actual companies / stocks that are shared between my "
        "most overlapping mutual funds?"
    )
    assert reply, "empty reply"
    lower = reply.lower()
    # Must NOT claim missing data — that's the bug we're guarding against
    assert "don't have" not in lower and "do not have" not in lower, (
        f"AI claimed missing data despite top_shared being in context: {reply[:600]!r}"
    )
    assert "isn't provided" not in lower and "is not provided" not in lower, (
        f"AI claimed missing data: {reply[:600]!r}"
    )
    # Must mention at least one common Indian large-cap likely to appear in
    # any large-cap MF overlap. We accept any of these as evidence the AI
    # surfaced real shared companies from top_shared.
    likely_companies = (
        "hdfc", "icici", "reliance", "infosys", "tcs", "axis", "kotak",
        "bharti", "itc", "sbi", "larsen", "l&t", "bajaj", "asian paint",
        "maruti", "wipro", "tata",
    )
    matched = [c for c in likely_companies if c in lower]
    assert matched, (
        "AI did not name any well-known company from top_shared; "
        f"reply was: {reply[:600]!r}"
    )


def test_actionable_question_triggers_plan_generation(impersonate_ahaan):
    shadow_uid = impersonate_ahaan
    reply = _post_send(
        "Which fund should I exit first with minimal tax impact?"
    )
    assert reply, "empty reply"
    # Plan should now exist for the impersonated user
    db_name = os.environ.get("DB_NAME", "test_database")
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")

    async def _check():
        cli = AsyncIOMotorClient(mongo_url)
        db = cli[db_name]
        plan = await db.action_plans.find_one(
            {"user_id": shadow_uid, "status": "active"}, {"_id": 0, "actions": 1, "plan_id": 1},
        )
        cli.close()
        return plan

    plan = asyncio.get_event_loop().run_until_complete(_check())
    assert plan is not None, "auto-plan-gen did not create an active plan"
    assert plan.get("actions"), f"generated plan has no actions: {plan}"
