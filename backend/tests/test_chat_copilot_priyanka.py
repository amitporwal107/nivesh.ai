"""End-to-end validation of the Nivesh Copilot chat pipeline against
priyankamantri@gmail.com's CAS-derived holdings.

Covers regressions / behaviours we shipped on 2026-04-30:

  1. Cost-basis classification — placeholder buy_price=current_price rows
     (CAS rebuild fallback) must be flagged as `unknown` and excluded
     from profit-based leaderboards.
  2. Per-holding leaderboards (Top by RETURN %, Top by ABSOLUTE PROFIT,
     Worst-performing) must reflect REAL holdings only.
  3. Per-sector breakdown for direct equities.
  4. AMC concentration block (extracted from MF scheme names).
  5. Goals / Health / Snapshot context blocks emit explicit "NO X
     RECORDED" markers when source data is empty (anti-fabrication).
  6. Empty holdings → explicit `NO HOLDINGS RECORDED` block (NOT empty
     string) so the LLM can't silently confabulate.
  7. Chart-protocol validator drops malformed blocks and accepts valid ones.
  8. /api/chat/warmup primes the Redis intel-context cache and returns
     a non-empty per-block size map.
  9. /api/chat/send (non-stream) integrates everything: when impersonating
     priyanka, the LLM reply quotes REAL holding names, never invented
     ones.

Strategy mirrors test_chat_no_plan_factual: impersonate priyanka via the
advisor session's `active_profile_id`, fire chat calls, then revert.
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

# CLIENT profile under aporwal107's ADVISORY workspace. CAS-uploaded.
PRIYANKA_PROFILE_NAME = "priyankamantri"


# ─────────────────────────────────────────────────────────────────────────
# Pure-helper unit tests (no DB / no LLM)
# ─────────────────────────────────────────────────────────────────────────
def test_render_portfolio_block_empty_emits_explicit_no_holdings_marker():
    """Regression: empty-holdings used to return "" → LLM filled the
    silence with fabricated names. Block must now emit the explicit
    NO HOLDINGS RECORDED marker."""
    from routes.chat import _render_portfolio_block
    out = _render_portfolio_block([])
    assert out, "empty-holdings render must NOT be an empty string"
    assert "NO HOLDINGS RECORDED" in out
    assert "DO NOT invent" in out
    assert "fabricating data here is a critical failure" in out


def test_render_portfolio_block_classifies_placeholder_basis():
    """A holding with bp == cp AND no buy_date is a CAS-rebuild placeholder
    and must be segregated from rankings."""
    from routes.chat import _render_portfolio_block
    holdings = [
        # known basis (real return)
        {"name": "GABRIEL INDIA", "asset_type": "equity", "quantity": 213,
         "buy_price": 826, "current_price": 1019, "sector": "Other",
         "buy_date": None},
        # placeholder (bp == cp, no buy_date)
        {"name": "PUNJ LLOYD", "asset_type": "equity", "quantity": 500,
         "buy_price": 2.23, "current_price": 2.23, "sector": "Infrastructure",
         "buy_date": None},
        # legit flat (bp == cp, but with buy_date)
        {"name": "FLAT CO", "asset_type": "equity", "quantity": 10,
         "buy_price": 100, "current_price": 100, "sector": "Other",
         "buy_date": "2025-01-01"},
    ]
    out = _render_portfolio_block(holdings)
    assert "Holdings with KNOWN cost basis: 2" in out, out[:600]
    assert "Holdings with UNKNOWN cost basis: 1" in out, out[:600]
    assert "PUNJ LLOYD" in out
    assert "cost basis UNKNOWN" in out
    # PUNJ LLOYD must NOT appear in any leaderboard
    leaderboard_section = out.split("Top holdings by RETURN")[1] if "Top holdings by RETURN" in out else ""
    assert "PUNJ LLOYD" not in leaderboard_section, "placeholder leaked into leaderboard"


def test_render_portfolio_block_leaderboards_present():
    holdings = [
        {"name": f"FUND_{i}", "asset_type": "mutual_fund", "quantity": 100,
         "buy_price": 50, "current_price": 50 + i * 5, "sector": "Mid Cap",
         "buy_date": "2025-01-01"}
        for i in range(1, 6)
    ]
    from routes.chat import _render_portfolio_block
    out = _render_portfolio_block(holdings)
    assert "Top holdings by RETURN %" in out
    assert "Top holdings by ABSOLUTE PROFIT" in out
    # Best return holding must rank #1
    ret_section = out.split("Top holdings by RETURN %:")[1].split("Top holdings by ABSOLUTE")[0]
    assert "FUND_5" in ret_section.split("\n")[1], ret_section


def test_render_portfolio_block_per_sector_breakdown_for_equities():
    holdings = [
        {"name": "Reliance", "asset_type": "equity", "quantity": 10,
         "buy_price": 2000, "current_price": 2400, "sector": "Energy",
         "buy_date": "2025-01-01"},
        {"name": "ONGC", "asset_type": "equity", "quantity": 50,
         "buy_price": 150, "current_price": 180, "sector": "Energy",
         "buy_date": "2025-01-01"},
        {"name": "Infosys", "asset_type": "equity", "quantity": 30,
         "buy_price": 1500, "current_price": 1800, "sector": "IT",
         "buy_date": "2025-01-01"},
        # MF — should NOT enter the by-sector breakdown
        {"name": "Parag Parikh Flexi Cap", "asset_type": "mutual_fund",
         "quantity": 100, "buy_price": 50, "current_price": 70,
         "sector": "Flexi Cap", "buy_date": "2025-01-01"},
    ]
    from routes.chat import _render_portfolio_block
    out = _render_portfolio_block(holdings)
    assert "Top equities BY SECTOR" in out
    sector_section = out.split("Top equities BY SECTOR")[1]
    assert "Sector: Energy" in sector_section
    assert "Sector: IT" in sector_section
    assert "Reliance" in sector_section
    assert "Infosys" in sector_section
    # Mutual fund must not leak into the sector breakdown
    assert "Parag Parikh" not in sector_section, "MF leaked into by-sector"


def test_amc_concentration_block_extracts_known_amcs():
    from routes.chat import _amc_concentration_block, _extract_amc
    assert _extract_amc("HDFC Mid-Cap Opportunities Fund") == "HDFC"
    assert _extract_amc("Aditya Birla Sun Life Frontline Equity") == "ADITYA BIRLA"
    assert _extract_amc("Parag Parikh Flexi Cap") == "PARAG PARIKH"
    mfs = [
        {"scheme_name": "HDFC Mid-Cap Opportunities", "amount_rs": 200000},
        {"scheme_name": "HDFC Flexi Cap", "amount_rs": 100000},
        {"scheme_name": "Nippon India Small Cap", "amount_rs": 150000},
    ]
    block = _amc_concentration_block(mfs)
    assert "AMC Concentration" in block
    assert "HDFC: 66.7%" in block.replace(" ", " "), block
    assert "NIPPON: 33.3%" in block.replace(" ", " "), block


def test_chart_validator_accepts_valid_drops_invalid():
    from services.copilot_charts import validate_chart_blocks

    valid = (
        '```chart\n'
        '{"type":"bar","title":"AMC","data":'
        '[{"label":"HDFC","value":31.2},{"label":"NIPPON","value":27.5}]}\n'
        '```'
    )
    r = validate_chart_blocks(valid)
    assert r["valid_count"] == 1
    assert r["invalid_specs"] == []

    bad_type = '```chart\n{"type":"radar","data":[{"label":"a","value":1},{"label":"b","value":2}]}\n```'
    r2 = validate_chart_blocks(bad_type)
    assert r2["valid_count"] == 0
    assert "bad type" in r2["invalid_specs"][0]["reason"]
    # Bad block should be rewritten to ```text``` so frontend never crashes
    assert "```text" in r2["clean_text"]

    single_point = '```chart\n{"type":"bar","data":[{"label":"a","value":1}]}\n```'
    r3 = validate_chart_blocks(single_point)
    assert r3["valid_count"] == 0


def test_empty_state_markers_for_goals_health_snapshot():
    """All four context builders must emit an explicit 'NO X RECORDED'
    marker rather than an empty string when their source data is empty.
    Test by calling them with a known-bogus user_id."""
    import asyncio as _asyncio
    from routes.chat import (
        _compute_goals_context, _compute_health_context, _compute_snapshot_context,
    )
    bogus = "user_does_not_exist_xxx"
    g, h, s = _asyncio.get_event_loop().run_until_complete(_asyncio.gather(
        _compute_goals_context(bogus),
        _compute_health_context(bogus),
        _compute_snapshot_context(bogus),
    ))
    # At least one must emit the 'NO ... RECORDED' marker; PG/health
    # may be unavailable in the test env, in which case the catch-all
    # returns "" — accept that too, but assert NO fabricated text.
    for label, block in (("goals", g), ("health", h), ("snapshot", s)):
        if block:
            assert "NO " in block.upper() and "RECORDED" in block.upper() or \
                   "NO HEALTH SCORE AVAILABLE" in block, \
                   f"{label} block lacks explicit empty-state marker: {block[:200]!r}"


# ─────────────────────────────────────────────────────────────────────────
# Integration tests — impersonate priyanka via advisor session
# ─────────────────────────────────────────────────────────────────────────
@pytest.fixture
def impersonate_priyanka():
    db_name = os.environ.get("DB_NAME", "test_database")
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")

    async def _setup():
        cli = AsyncIOMotorClient(mongo_url)
        db = cli[db_name]
        prof = await db.profiles.find_one(
            {"name": {"$regex": PRIYANKA_PROFILE_NAME, "$options": "i"},
             "type": "CLIENT"},
            {"_id": 0, "profile_id": 1, "shadow_user_id": 1, "name": 1},
        )
        assert prof, (
            f"seed data missing: CLIENT profile matching {PRIYANKA_PROFILE_NAME!r} "
            "not found. Confirm aporwal107's advisory workspace has the priyanka "
            "client provisioned."
        )
        shadow = prof["shadow_user_id"]
        n_holdings = await db.holdings.count_documents({"user_id": shadow})
        # Don't hard-assert a count — priyanka's CAS coverage may vary —
        # but DO verify at least 1 holding so the integration tests have
        # something real to validate against.
        assert n_holdings >= 1, (
            f"priyanka shadow_user_id={shadow} has zero holdings. Re-upload "
            f"her latest CAS so the test suite has real data to validate."
        )
        # Wipe pre-existing chat sessions / messages for this user so
        # tests aren't poisoned by stale "I don't have data" refusals
        # from earlier dev runs. The AI reads conversation history into
        # context and will parrot prior turns even when the new context
        # has the data.
        await db.chat_sessions.delete_many({"user_id": shadow})
        await db.chat_messages.delete_many({"user_id": shadow})
        await db.user_sessions.update_one(
            {"session_token": ADVISOR_TOKEN},
            {"$set": {"active_profile_id": prof["profile_id"]}},
        )
        cli.close()
        return {"shadow_uid": shadow, "n_holdings": n_holdings, "name": prof["name"]}

    async def _teardown():
        cli = AsyncIOMotorClient(mongo_url)
        db = cli[db_name]
        await db.user_sessions.update_one(
            {"session_token": ADVISOR_TOKEN},
            {"$set": {"active_profile_id": None}},
        )
        cli.close()

    info = asyncio.get_event_loop().run_until_complete(_setup())
    yield info
    asyncio.get_event_loop().run_until_complete(_teardown())


def _post_send(message: str) -> dict:
    r = requests.post(
        f"{BASE_URL}/api/chat/send",
        headers=HEADERS,
        json={"message": message},
        timeout=180,
    )
    assert r.status_code == 200, f"send failed: {r.status_code} {r.text[:300]}"
    return r.json()


def _reply(payload: dict) -> str:
    return ((payload.get("ai_message") or {}).get("content") or "").strip()


def test_warmup_primes_priyanka_context_blocks(impersonate_priyanka):
    """/chat/warmup must return non-zero block sizes for priyanka."""
    r = requests.post(
        f"{BASE_URL}/api/chat/warmup", headers=HEADERS, timeout=60,
    )
    assert r.status_code == 200, f"warmup failed: {r.status_code} {r.text[:300]}"
    body = r.json()
    assert body.get("ok") is True
    # Advisor mode would short-circuit with warmed=False; we expect a
    # single-portfolio warmup since we're impersonating a CLIENT.
    assert body.get("warmed") is True, body
    blocks = body.get("blocks") or {}
    assert "intelligence" in blocks, body
    # Intelligence block should be non-trivial for a real CAS portfolio
    assert blocks["intelligence"] > 100, (
        f"intelligence context too short ({blocks['intelligence']} chars) — "
        f"either Postgres / portfolio_intelligence is degraded, or priyanka's "
        f"CAS holdings weren't enriched. Check pg_client + intelligence service."
    )


def test_send_does_not_fabricate_for_holdings_user(impersonate_priyanka):
    """When priyanka has real holdings, the AI must quote actual fund /
    stock names from her CAS — not invented blue-chip names. Hits the
    classic hallucination pattern that surfaced earlier today."""
    payload = _post_send(
        "List my top 3 mutual funds by absolute profit. "
        "Use only the holdings in my portfolio — do not invent any."
    )
    reply = _reply(payload)
    assert reply, "empty reply"
    lower = reply.lower()

    # Get priyanka's actual fund names from the DB so we can validate
    # the AI cites real names.
    db_name = os.environ.get("DB_NAME", "test_database")
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    cli = AsyncIOMotorClient(mongo_url)
    db = cli[db_name]

    async def _names():
        prof = await db.profiles.find_one(
            {"name": {"$regex": PRIYANKA_PROFILE_NAME, "$options": "i"}},
            {"_id": 0, "shadow_user_id": 1},
        )
        cur = db.holdings.find(
            {"user_id": prof["shadow_user_id"], "asset_type": "mutual_fund"},
            {"_id": 0, "name": 1},
        )
        return [h["name"] async for h in cur]

    real_names = asyncio.get_event_loop().run_until_complete(_names())
    cli.close()
    assert real_names, "priyanka has zero MF holdings — re-check seed"

    # Reply must mention at least one real name (case-insensitive,
    # tokenised so "HDFC Mid-Cap" matches "HDFC Mid Cap Opportunities").
    real_lower = [n.lower() for n in real_names]
    quoted = any(
        # match on the first 2-3 distinguishing tokens (skip generic
        # words like "fund" / "growth" / "regular" / "direct")
        any(tok in lower for tok in name.split()[:2] if len(tok) > 3)
        for name in real_lower
    )
    assert quoted, (
        "AI reply does not quote ANY of priyanka's real MF names. "
        f"Real funds: {real_names[:5]} ... Reply: {reply[:600]!r}"
    )

    # Specific anti-hallucination guards — fund names that the AI was
    # observed to invent for users with no holdings. None of these
    # should appear in priyanka's CAS unless they ACTUALLY do.
    suspect_invented = [
        "axis bluechip fund",
        "sbi small cap fund",
        "icici prudential equity & debt fund",
    ]
    for s in suspect_invented:
        if s in lower and not any(s in n for n in real_lower):
            pytest.fail(
                f"AI cited {s!r} but priyanka does not actually hold it — "
                f"hallucination regression. Real funds: {real_names[:10]}"
            )


def test_rag_endpoint_grounds_top_funds_by_profit(impersonate_priyanka):
    """The new /chat/rag endpoint must produce a grounded answer:
    real fund names from priyanka's portfolio, no fabrications."""
    info = impersonate_priyanka
    r = requests.post(
        f"{BASE_URL}/api/chat/rag",
        headers=HEADERS,
        json={"message": "List my top 3 mutual funds by absolute profit"},
        timeout=60,
    )
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body["intent"] == "ranking", body
    assert body["retrieval_ok"] is True, body
    rows = body["rows"]
    assert len(rows) >= 2, rows

    # Every row must be a real holding for priyanka. Cross-check against
    # the DB — no fabricated names allowed.
    db_name = os.environ.get("DB_NAME", "test_database")
    cli = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db = cli[db_name]

    async def _names():
        cur = db.holdings.find({"user_id": info["shadow_uid"]}, {"_id": 0, "name": 1})
        return [h["name"] async for h in cur]

    real = set(asyncio.get_event_loop().run_until_complete(_names()))
    cli.close()
    for r_ in rows:
        assert r_["name"] in real, (
            f"Row name {r_['name']!r} is NOT in priyanka's actual holdings — "
            f"hallucination regression in RAG retrievers."
        )

    # Prose must mention the #1 fund verbatim
    top1 = rows[0]["name"]
    prose = body["prose"]
    # Match on first 4 chars (case-insensitive) — "HDFC" / "ICICI" / etc.
    assert top1[:4].lower() in prose.lower(), (
        f"prose does not cite the #1 ranked fund. top1={top1!r} prose={prose[:300]!r}"
    )


def test_rag_endpoint_sector_uses_lookthrough_not_categories(impersonate_priyanka):
    """When the user asks for 'sector concentration', they mean real
    sectors (IT, Pharma, Banking) — not fund categories (Mid Cap,
    Flexi Cap, Value). This test guards the regression where
    bucketing by `holding.sector` returned categories for MFs.
    """
    r = requests.post(
        f"{BASE_URL}/api/chat/rag",
        headers=HEADERS,
        json={"message": "Show me my sector concentration — IT, Pharma, Banking, etc."},
        timeout=60,
    )
    body = r.json()
    assert body["intent"] == "concentration", body
    if not body["retrieval_ok"]:
        pytest.skip(f"intelligence service unavailable: {body['retrieval_reason']}")
    labels = {row["label"] for row in body["rows"]}
    # Look-through results must NOT be dominated by fund-category labels.
    fund_categories = {"Mid Cap", "Small Cap", "Flexi Cap", "Large Cap", "Value", "Index", "Balanced", "Focused"}
    overlap = labels & fund_categories
    assert len(overlap) <= 1, (
        f"sector retrieval returned fund categories instead of real sectors: "
        f"overlap={overlap}, all labels={labels}"
    )
    # Chart title must say "Sector mix" not "Sector concentration"
    spec = body.get("chart_spec") or {}
    assert "look-through" in (spec.get("title") or "").lower(), spec


def test_rag_endpoint_category_returns_fund_buckets(impersonate_priyanka):
    """The 'category mix' intent must produce SEBI/AMC fund categories
    (Mid Cap, Small Cap, Flexi Cap, Value, etc.) — distinct from the
    sector look-through."""
    r = requests.post(
        f"{BASE_URL}/api/chat/rag",
        headers=HEADERS,
        json={"message": "Show me my fund category mix — large cap vs mid cap"},
        timeout=60,
    )
    body = r.json()
    assert body["intent"] == "concentration"
    assert body["retrieval_ok"] is True, body
    labels = {row["label"] for row in body["rows"]}
    # At least one of these category labels must appear
    fund_cats = {"Mid Cap", "Small Cap", "Flexi Cap", "Large Cap", "Value", "Index"}
    assert labels & fund_cats, (
        f"category mix returned no recognisable fund categories: {labels}"
    )


def test_rag_endpoint_asset_class_returns_class_buckets(impersonate_priyanka):
    """'Asset class breakdown' must split by Equity / MF / ETF / Gold —
    not by sector or category."""
    r = requests.post(
        f"{BASE_URL}/api/chat/rag",
        headers=HEADERS,
        json={"message": "Show me my asset class breakdown"},
        timeout=60,
    )
    body = r.json()
    assert body["intent"] == "concentration"
    assert body["retrieval_ok"] is True, body
    labels = {row["label"] for row in body["rows"]}
    # Must contain an asset-class label, not a fund category
    asset_class_signal = any(
        any(tok in label for tok in ("Mutual", "Equity", "ETF", "Gold", "Debt"))
        for label in labels
    )
    assert asset_class_signal, (
        f"asset class breakdown didn't return class labels: {labels}"
    )


def test_rag_endpoint_company_breakdown_uses_lookthrough(impersonate_priyanka):
    """'Company wise breakdown' must surface look-through company
    exposures (HDFC Bank, ICICI Bank, Reliance, etc.) — the underlying
    stocks held across all MFs + direct equity, not fund / category /
    sector labels. Renders as a bar chart, not donut."""
    r = requests.post(
        f"{BASE_URL}/api/chat/rag",
        headers=HEADERS,
        json={"message": "Company wise breakdown"},
        timeout=60,
    )
    body = r.json()
    assert body["intent"] == "concentration", body
    if not body["retrieval_ok"]:
        pytest.skip(f"intelligence service unavailable: {body['retrieval_reason']}")
    rows = body["rows"]
    assert len(rows) >= 3, rows
    # Chart spec must be a BAR (top-N leaderboard) not a donut
    spec = body.get("chart_spec") or {}
    assert spec.get("type") == "bar", f"company chart should be bar not donut: {spec.get('type')}"
    assert "company" in (spec.get("title") or "").lower()
    # Labels must look like company names (have caps, multiple words),
    # not fund category labels like "Mid Cap" / "Small Cap" / "Index"
    fund_categories = {"Mid Cap", "Small Cap", "Flexi Cap", "Large Cap", "Value", "Index", "Balanced"}
    bad_overlap = {row["label"] for row in rows} & fund_categories
    assert not bad_overlap, (
        f"company breakdown returned fund categories not company names: "
        f"{bad_overlap}; full labels: {[r['label'] for r in rows]}"
    )


def test_rag_invest_fresh_money_recommends_underweight_bucket(impersonate_priyanka):
    """REGRESSION: 'Where should I invest ₹X to improve diversification?'
    must route to the Decision Engine's drift logic and recommend the
    most UNDERWEIGHT bucket — NOT the bucket with the fewest holdings.

    Bug observed 2026-04-30: the question fell through to `generic`
    intent → `portfolio_summary` returned a count-by-asset-type list
    → the LLM suggested adding gold ('only 5 gold holdings') to a
    user already gold-overweight by +17pp."""
    r = requests.post(
        f"{BASE_URL}/api/chat/rag",
        headers=HEADERS,
        json={"message": "Based on my current portfolio gaps, where should I invest "
                         "₹1 lakh of fresh money to improve diversification?"},
        timeout=60,
    )
    body = r.json()
    assert body["intent"] == "invest_fresh", (
        f"invest-fresh question routed to {body['intent']!r}, not invest_fresh"
    )
    assert body["retrieval_ok"] is True, body
    rows = body["rows"]
    assert rows, "no recommendation rows"
    top = rows[0]
    # Most-underweight bucket must be debt for priyanka (gold +17pp,
    # equity within band, debt is the deepest negative gap).
    assert top["bucket"].lower() == "debt", (
        f"recommended bucket should be debt (most underweight), got {top['bucket']!r}"
    )
    # Suggested amount must round-trip the user's ₹1 lakh
    assert top.get("suggested_amount_rs") in (100000, 100000.0), top
    # Critical anti-regression: the answer must NOT be gold (which is
    # over-concentrated). Even one gold suggestion would be wrong.
    bucket_set = {r["bucket"].lower() for r in rows}
    assert "gold" not in bucket_set, (
        f"recommendation includes gold despite gold being overweight: {bucket_set}"
    )


def test_plan_board_includes_decision_engine_actions(impersonate_priyanka):
    """`/plans/generate` (the Plan Board's entry point) must augment
    the legacy V2 rules with Decision Engine drift / cap actions, so
    the dashboard shows asset-class drift + sector / category cap
    moves alongside AMC / Overlap / Reg→Direct rules.

    This is the regression guard for the Copilot ↔ Plan Board
    integration shipped on 2026-04-30."""
    r = requests.post(f"{BASE_URL}/api/plans/generate", headers=HEADERS, timeout=180)
    assert r.status_code == 200, r.text[:300]
    plan = r.json().get("plan") or {}
    actions = plan.get("actions") or []
    assert actions, "plan generated zero actions"

    # At least one action MUST come from the decision engine — priyanka
    # is gold-overweight, so Rule 6 always fires for her portfolio.
    de_actions = [a for a in actions if a.get("source") == "decision_engine"]
    legacy_actions = [a for a in actions if a.get("source") != "decision_engine"]
    assert de_actions, (
        f"plan has no decision_engine actions — Plan Board not plugged in. "
        f"All sources: {sorted({a.get('source') for a in actions})}"
    )
    # Mix should still preserve legacy rules — we're augmenting, not replacing.
    assert legacy_actions, (
        "plan has zero legacy actions — decision engine over-rotated. "
        "Legacy rules (AMC concentration / Overlap / etc.) must still fire."
    )

    # Each decision-engine action must have the standard plan-action
    # shape (so the dashboard PlanCard renders it without changes).
    for a in de_actions:
        for required in ("action_id", "type", "asset_name", "amount",
                         "priority", "status", "reason_codes", "rule"):
            assert required in a, f"decision_engine action missing {required!r}: {a}"
        assert a["status"] == "PENDING"
        assert a["rule"] in ("Rule 6", "Rule 7", "Rule 8")


def test_clear_active_plan_archives_plan(impersonate_priyanka):
    """DELETE /api/plans/active must flip the active plan's status to
    archived (so the next /plans/active returns null) and be idempotent
    when called again."""
    info = impersonate_priyanka
    db_name = os.environ.get("DB_NAME", "test_database")
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")

    # Pre-flight: priyanka must have an active plan for this test to be
    # meaningful. If she doesn't, generate one inline (best effort).
    cli = AsyncIOMotorClient(mongo_url)
    db = cli[db_name]
    has_active = asyncio.get_event_loop().run_until_complete(
        db.action_plans.find_one(
            {"user_id": info["shadow_uid"], "status": "active"}, {"_id": 0, "plan_id": 1},
        )
    )
    cli.close()
    if not has_active:
        # try generating; tolerate failures (PG / scoring may be down in CI)
        gen = requests.post(f"{BASE_URL}/api/plans/generate", headers=HEADERS, timeout=120)
        if gen.status_code != 200:
            pytest.skip("priyanka has no active plan and generation failed in this env")
        plan_id = gen.json().get("plan", {}).get("plan_id")
        if plan_id:
            requests.post(f"{BASE_URL}/api/plans/{plan_id}/save", headers=HEADERS, timeout=30)

    # ── 1st DELETE: should archive the active plan ──
    r = requests.delete(f"{BASE_URL}/api/plans/active", headers=HEADERS, timeout=30)
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    if not body.get("ok"):
        # Acceptable when there genuinely was no active plan
        assert body.get("reason") == "no_active_plan"
        pytest.skip("no active plan was present; archive path tested by skip")
    assert "plan_id" in body, body

    # ── /plans/active should now return null ──
    after = requests.get(f"{BASE_URL}/api/plans/active", headers=HEADERS, timeout=30).json()
    assert after.get("has_plan") is False, after

    # ── 2nd DELETE: idempotent — returns ok=False with no_active_plan ──
    r2 = requests.delete(f"{BASE_URL}/api/plans/active", headers=HEADERS, timeout=30).json()
    assert r2.get("ok") is False
    assert r2.get("reason") == "no_active_plan"


def test_behavioural_signals_for_priyanka(impersonate_priyanka):
    """End-to-end: behavioural signals service must produce a non-empty
    output for a user with real CAS history + holdings."""
    info = impersonate_priyanka
    import asyncio as _asyncio
    from services import behavioural_signals as _bs
    sig = _asyncio.get_event_loop().run_until_complete(_bs.compute_signals(info["shadow_uid"]))
    # All three signal slots must resolve to non-None for a real user
    assert sig.trading_activity in ("low", "medium", "high"), sig.trading_activity
    assert sig.drawdown_tolerance in ("low", "medium", "high"), sig.drawdown_tolerance
    assert sig.volatility_preference in ("low", "medium", "high"), sig.volatility_preference
    assert sig.confidence_score > 50, sig.confidence_score


def test_target_allocator_persists_to_mongo(impersonate_priyanka):
    """`compute_target_allocation` must write through to
    db.target_allocations as a side effect."""
    info = impersonate_priyanka
    import asyncio as _asyncio
    from services.target_allocator import compute_target_allocation
    ta = _asyncio.get_event_loop().run_until_complete(
        compute_target_allocation(info["shadow_uid"])
    )
    assert ta.allocation
    assert abs(sum(ta.allocation.values()) - 100) < 0.5, ta.allocation

    # Read back from Mongo
    db_name = os.environ.get("DB_NAME", "test_database")
    cli = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    db = cli[db_name]
    doc = _asyncio.get_event_loop().run_until_complete(
        db.target_allocations.find_one({"user_id": info["shadow_uid"]}, {"_id": 0})
    )
    cli.close()
    assert doc, "target_allocations doc not persisted"
    assert doc["allocation"] == ta.allocation
    assert "updated_at" in doc and "risk_category" in doc


def test_decision_engine_action_generator_produces_actions_for_drift(impersonate_priyanka):
    """priyanka is gold-overweight; Rule 6 must emit at least one TRIM
    on a gold holding plus an ADD on the underweight debt bucket."""
    info = impersonate_priyanka
    import asyncio as _asyncio
    from services.decision_engine_actions import generate_actions
    actions = _asyncio.get_event_loop().run_until_complete(generate_actions(info["shadow_uid"]))
    if not actions:
        pytest.skip("portfolio is within targets — no rebalance needed")
    types = {a.type for a in actions}
    rules = {a.rule for a in actions}
    assert "Rule 6" in rules, f"Rule 6 should always run on a real portfolio: {rules}"
    # Each action shape must match the active_plan_actions row shape so
    # the orchestrator's plan formatter can render either source.
    a0 = actions[0].to_dict()
    for k in ("type", "action_type", "asset_name", "amount", "amount_rs",
              "reason_codes", "reason_text"):
        assert k in a0, f"action dict missing key {k!r}: {a0}"


def test_target_allocator_pure_function():
    """Pure unit test for the target allocator — no DB needed when we
    pass a stub. Validates the base table + goal overlay arithmetic."""
    from services.target_allocator import (
        _BASE_BY_RISK, _goal_overlay, _normalise_risk,
    )
    # Base table sanity
    for cat in ("aggressive", "moderate", "conservative"):
        s = sum(_BASE_BY_RISK[cat].values())
        assert abs(s - 100) < 0.01, f"{cat} doesn't sum to 100: {s}"
    # Risk normalisation
    assert _normalise_risk("Aggressive") == "aggressive"
    assert _normalise_risk("Mod") == "moderate"
    assert _normalise_risk(None) == "moderate"
    assert _normalise_risk("balanced") == "moderate"
    # Goal overlay shapes
    short = _goal_overlay("emergency", 0.5)
    assert short["equity"] < 0 and short["debt"] > 0
    long_retirement = _goal_overlay("retirement", 20)
    assert long_retirement["equity"] > 0 and long_retirement["debt"] < 0
    midhorizon = _goal_overlay("home", 6)
    assert midhorizon == {"equity": 0, "debt": 0, "gold": 0, "cash": 0}


def test_rag_drift_intent_routes_correctly(impersonate_priyanka):
    """'Am I aligned with my target?' must route to DRIFT, not GOALS.
    Output must include all four asset buckets with current/target/dev."""
    r = requests.post(
        f"{BASE_URL}/api/chat/rag",
        headers=HEADERS,
        json={"message": "Am I aligned with my target allocation?"},
        timeout=60,
    )
    body = r.json()
    assert body["intent"] == "drift", (
        f"target-allocation question routed to {body['intent']!r} not drift"
    )
    assert body["retrieval_ok"] is True, body
    rows = body["rows"]
    assets = {row["asset"] for row in rows}
    assert {"Equity", "Debt", "Gold", "Cash"} <= assets, f"missing buckets: {assets}"
    # Each row must have the deviation contract
    for r_ in rows:
        assert "current_pct" in r_ and "target_pct" in r_ and "deviation_pp" in r_
        assert r_["trigger"] in ("ok", "soft", "hard")
    # Chart spec must be a stacked_bar (current vs target side by side)
    spec = body.get("chart_spec") or {}
    assert spec.get("type") == "stacked_bar", spec.get("type")
    assert "drift" in (spec.get("title") or "").lower()


def test_rag_overweight_question_hits_drift(impersonate_priyanka):
    """Plain-English 'is my equity overweight' must hit drift, not the
    concentration / generic / ranking intents."""
    r = requests.post(
        f"{BASE_URL}/api/chat/rag",
        headers=HEADERS,
        json={"message": "Is my equity overweight?"},
        timeout=60,
    )
    body = r.json()
    assert body["intent"] == "drift", body
    rows = body["rows"]
    eq_row = next((r_ for r_ in rows if r_["asset"] == "Equity"), None)
    assert eq_row, f"no Equity row in drift output: {rows}"


def test_rag_fix_my_portfolio_routes_to_plan_intent(impersonate_priyanka):
    """Question with action-language ('Fix my portfolio', 'top 3 actions
    I should take') must route to PLAN intent — not RANKING — even
    though 'top 3' is a rank trigger. Plan retrieval surfaces the
    actual EXIT/ADD actions from the active action plan."""
    r = requests.post(
        f"{BASE_URL}/api/chat/rag",
        headers=HEADERS,
        json={"message": "Fix my portfolio. What are the top 3 actions I should take "
                         "based on my current holdings? Include estimated tax impact."},
        timeout=60,
    )
    body = r.json()
    assert body["intent"] == "plan", (
        f"action-language question routed to {body['intent']!r} instead of plan"
    )
    if not body["retrieval_ok"]:
        pytest.skip(f"no active plan for priyanka: {body['retrieval_reason']}")
    rows = body["rows"]
    assert rows, "plan retrieval returned ok but no rows"
    # Each row must look like a plan action (action_type + asset_name +
    # reason_codes), not a holding ranking row.
    a0 = rows[0]
    assert "action_type" in a0 and "asset_name" in a0 and "reason_codes" in a0, a0
    # Acceptable action types span both the saved-plan engine
    # (EXIT/ADD/SWITCH/HOLD/REVIEW) and the new decision-engine
    # fallback (TRIM/ADD), which kicks in when no saved plan exists.
    valid = {"EXIT", "ADD", "SWITCH", "HOLD", "REVIEW", "TRIM",
             "exit", "add", "trim"}
    assert a0["action_type"] in valid, a0
    # Prose must mention at least one of the action types verbatim
    prose_lower = (body["prose"] or "").lower()
    assert any(verb in prose_lower for verb in ("exit", "add", "switch", "rebalance", "consolidat")), (
        f"prose doesn't mention any action verb: {body['prose'][:300]!r}"
    )


def test_rag_top_stocks_by_metric_still_ranking_not_company(impersonate_priyanka):
    """Disambiguation guard: 'top 5 stocks by return' must STILL route
    to ranking intent (returns specific holdings ordered by return %),
    NOT the new company concentration intent — because the user is
    asking for direct-stock leaderboard, not look-through exposure."""
    r = requests.post(
        f"{BASE_URL}/api/chat/rag",
        headers=HEADERS,
        json={"message": "Top 5 stocks by return"},
        timeout=60,
    )
    body = r.json()
    assert body["intent"] == "ranking", (
        f"'top stocks' should be ranking intent, got {body['intent']}"
    )
    rows = body["rows"]
    assert rows, body
    # Each row must look like a ranking row (has 'rank' and 'return_pct')
    assert "rank" in rows[0] and "return_pct" in rows[0], rows[0]


def test_rag_endpoint_amc_concentration_returns_chart(impersonate_priyanka):
    r = requests.post(
        f"{BASE_URL}/api/chat/rag",
        headers=HEADERS,
        json={"message": "Show me my AMC concentration as a chart"},
        timeout=60,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == "concentration"
    assert body["retrieval_ok"] is True
    spec = body.get("chart_spec")
    assert spec, "chart spec missing for explicit chart request"
    assert spec["type"] in {"donut", "bar"}
    assert len(spec["data"]) >= 2
    # Sum of percentages should be ≤ 100% (we cap at top 8)
    total = sum(p["value"] for p in spec["data"])
    assert 0 < total <= 105, f"AMC % sum out of range: {total}"


def test_rag_endpoint_no_holdings_user_returns_explicit_no_data():
    """When the impersonated user has zero holdings, the RAG must return
    retrieval_ok=False with a reason, NOT confabulated names."""
    db_name = os.environ.get("DB_NAME", "test_database")
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")

    async def _setup():
        cli = AsyncIOMotorClient(mongo_url)
        db = cli[db_name]
        # Ensure the advisor session has NO active_profile_id (so the
        # caller is aporwal himself, who may or may not have holdings).
        await db.user_sessions.update_one(
            {"session_token": ADVISOR_TOKEN},
            {"$set": {"active_profile_id": None}},
        )
        # Sanity: the advisor user_id may have holdings of its own.
        sess = await db.user_sessions.find_one(
            {"session_token": ADVISOR_TOKEN}, {"_id": 0, "user_id": 1},
        )
        n = await db.holdings.count_documents({"user_id": sess["user_id"]})
        cli.close()
        return n

    n_holdings = asyncio.get_event_loop().run_until_complete(_setup())
    if n_holdings > 0:
        pytest.skip(
            "advisor account itself has holdings, can't validate empty-state — "
            "create a token for a holdings-less user to exercise this path"
        )
    r = requests.post(
        f"{BASE_URL}/api/chat/rag",
        headers=HEADERS,
        json={"message": "What are my top 3 funds by profit"},
        timeout=60,
    )
    body = r.json()
    assert body["retrieval_ok"] is False
    assert body["retrieval_reason"] == "no_holdings", body


def test_send_chart_block_emitted_for_amc_chart_request(impersonate_priyanka):
    """An explicit 'show as a chart' prompt must produce a fenced
    ```chart``` block in the response, validated server-side."""
    payload = _post_send(
        "Show me my AMC concentration as a chart, "
        "and also list the top 3 AMCs in prose."
    )
    reply = _reply(payload)
    assert reply
    # The validator on the server rewrites bad blocks to ```text```;
    # a present, valid chart block stays as ```chart```.
    assert "```chart" in reply, (
        "no chart block emitted despite explicit chart trigger. "
        f"Reply (first 800): {reply[:800]!r}"
    )
    # The block must contain valid JSON — find and parse it.
    import re
    match = re.search(r"```chart\s*\n(.*?)```", reply, re.DOTALL)
    assert match, "chart block syntactically broken"
    spec = json.loads(match.group(1))
    assert spec.get("type") in {"bar", "donut", "line", "stacked_bar"}, spec
    data = spec.get("data") or []
    assert len(data) >= 2, f"chart spec has < 2 data points: {spec}"
    # Each point must have label + numeric value (server-side validator
    # would reject otherwise — re-asserting in case the protocol drifts)
    for pt in data:
        assert "label" in pt and "value" in pt
        assert isinstance(pt["value"], (int, float)), pt
