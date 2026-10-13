"""POST /api/onboarding/gmail/auto-import — the default import, and the opt-in `all_statements` mode
that stores every CAS statement found in Gmail and shows the latest consolidated one.

Offline. Gmail, the statement extractors, Mongo and the model call are all fakes
(tests/test_cas_import_all_fakes.py — MOCK, not real data). What runs for real: the route, the Gmail
scanners, services.cas_history_import, the snapshot engine's store function, and
helpers.parsing.save_holdings with its broker-wins rule. No real statement, PAN or password is used;
`PASSWORD` below is a PAN-shaped placeholder.

The statements in these tests are month-end NSDL statements unless a test says otherwise:

    m-sep   emailed  3 Oct 2026   statement for 30-Sep-2026
    m-aug   emailed  3 Sep 2026   statement for 31-Aug-2026
    m-jul   emailed  4 Aug 2026   statement for 31-Jul-2026
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from helpers import holdings_reconcile as hr
from helpers import parsing
from routes import cas_snapshots as cas_routes
from routes import mfd as mfd_routes
from routes import onboarding_gmail as route
from routes import upload as upload_routes
from services import action_plan_manager as apm
from services import cas_snapshot_engine as eng
from services import cas_summary_vision, equity_sectors, gmail_service, masterdata, mfd_workspace
from services import portfolio_direct_push as pdp
from services import portfolio_health
from services import portfolio_snapshot as v1
from tests.test_cas_import_all_fakes import FakeDb, FakeGmail, holding, install_parsers, mail, statement

UID = "investor-1"
NOW = datetime(2026, 10, 14, 9, 0, tzinfo=timezone.utc)
PASSWORD = "AAAAA0000A"          # PAN-shaped placeholder
URL = "/api/onboarding/gmail/auto-import"
A, B, C, D = "INE000A01001", "INE000A01002", "INE000A01003", "INE000A01004"
MONTHLY = [{"month": "Aug 2026", "value_rs": 1900.0}, {"month": "Sep 2026", "value_rs": 2000.0}]
VISION_REPLY = {"current_value_rs": 9999.0, "statement_date": "30-Sep-2026",
                "monthly_values": [{"month": "Sep 2026", "value_rs": 9999.0}]}


def when(month: int, day: int) -> datetime:
    return datetime(2026, month, day, 8, 0, tzinfo=timezone.utc)


def nsdl(date: str, isins=(A, B), **kw) -> bytes:
    return statement("nsdl", date, isins, **kw)


SEP = nsdl("30-Sep-2026", (A, B), monthly=MONTHLY)
AUG = nsdl("31-Aug-2026", (A,))
JUL = nsdl("31-Jul-2026", (C,))


def three_months() -> List[Dict[str, Any]]:
    return [mail("m-sep", "nsdl", when(10, 3), SEP), mail("m-aug", "nsdl", when(9, 3), AUG),
            mail("m-jul", "nsdl", when(8, 4), JUL)]


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


# ── the world the route runs in ──────────────────────────────────────────────────────────────
@pytest.fixture()
def world(monkeypatch):
    db = FakeDb()
    db.gmail_tokens.docs.append({"user_id": UID, "access_token": "sealed-token", "refresh_token": "sealed-refresh"})
    db.user_profiles.docs.append({"user_id": UID, "pan": PASSWORD})
    db.users.docs.append({"user_id": UID, "email": "investor@example.com", "name": "Test Investor"})
    w = SimpleNamespace(
        db=db, gmail=FakeGmail(today=NOW), parsers=install_parsers(monkeypatch),
        vision=[], vision_reply=None, saves=[], save_error=None, plans=[], nidp=[], txn_bg=[],
        pg_mirror=[], forbidden=[],
    )

    for module in (route, parsing, eng, v1, cas_routes, mfd_routes, mfd_workspace):
        monkeypatch.setattr(module, "db", db)

    async def current_user(request):
        return {"user_id": UID, "_session_user_id": UID}
    monkeypatch.setattr(route, "get_current_user", current_user)
    monkeypatch.setattr(cas_routes, "get_current_user", current_user)
    monkeypatch.setattr(route, "get_gmail_credentials",
                        lambda token_doc: SimpleNamespace(token=token_doc.get("access_token"), expiry=None))
    monkeypatch.setattr(route, "build_gmail_service", lambda creds: w.gmail)

    # The paid model call. Both the route's wrapper and the function underneath are watched.
    def vision(content, password=""):
        w.vision.append(content)
        return w.vision_reply
    monkeypatch.setattr(route, "_extract_vision_summary", vision)
    monkeypatch.setattr(cas_summary_vision, "extract_portfolio_summary", vision)

    # save_holdings runs for real against the fake db; the wrapper only records the call.
    real_save = parsing.save_holdings

    async def save(user_id, holdings, file_type, task_id=None, portfolio_id=""):
        w.saves.append({"user_id": user_id, "file_type": file_type, "tickers": sorted(h["ticker"] for h in holdings)})
        if w.save_error:
            raise w.save_error
        return await real_save(user_id, holdings, file_type, task_id=task_id, portfolio_id=portfolio_id)
    monkeypatch.setattr(route, "save_holdings", save)

    async def no_enrichment(user_id, holdings_added):
        return None
    monkeypatch.setattr(parsing, "_enrich_after_upload", no_enrichment)
    monkeypatch.setattr(masterdata, "validate_and_enrich_holdings", lambda rows: rows)
    monkeypatch.setattr(equity_sectors, "enrich_holdings_with_sectors", lambda rows: rows)
    monkeypatch.setattr(hr, "_symbol_index", {})

    class Plans:
        async def refresh_plan(self, user_id):
            w.plans.append(user_id)
            return {"plan_id": "plan-1", "actions": []}
    monkeypatch.setattr(apm, "ActionPlanManager", Plans)

    async def nidp_pipeline(user_id):
        w.nidp.append(user_id)
    monkeypatch.setattr(upload_routes, "_trigger_nidp_pipeline_background", nidp_pipeline)

    async def nsdl_txns(user_id, pdf_bytes, password):
        w.txn_bg.append((user_id, pdf_bytes))
    monkeypatch.setattr(route, "_persist_nsdl_transactions_background", nsdl_txns)

    async def pg_mirror(**kw):
        w.pg_mirror.append(kw["snapshot_date"])
    monkeypatch.setattr(eng, "_persist_pg_snapshot", pg_mirror)

    # What the history path must never reach: a mount through the engine, a health run, an NIDP push.
    def tripwire(name):
        async def boom(*a, **k):
            w.forbidden.append(name)
            raise AssertionError(f"{name} must not be called")
        return boom
    monkeypatch.setattr(eng, "write_holdings_table", tripwire("write_holdings_table"))
    monkeypatch.setattr(eng, "create_cas_snapshot", tripwire("create_cas_snapshot"))
    monkeypatch.setattr(eng, "load_snapshot_into_holdings", tripwire("load_snapshot_into_holdings"))
    monkeypatch.setattr(portfolio_health, "build_portfolio_health", tripwire("build_portfolio_health"))
    monkeypatch.setattr(v1, "backfill_snapshot_health", tripwire("backfill_snapshot_health"))
    monkeypatch.setattr(pdp, "sync_portfolio_to_nidp", tripwire("sync_portfolio_to_nidp"))

    app = FastAPI()
    app.include_router(route.router)
    app.include_router(cas_routes.router)
    with TestClient(app) as client:      # one event loop for the test, so background tasks finish
        w.client = client
        yield w
    assert w.forbidden == []


def settle(w) -> None:
    """Let the tasks a handler started with asyncio.create_task run to the end before asserting on them."""
    async def idle():
        for _ in range(10):
            await asyncio.sleep(0)
    w.client.portal.call(idle)


def post(w, body: Any = None, raw: Optional[bytes] = None):
    if raw is not None:
        res = w.client.post(URL, content=raw, headers={"content-type": "application/json"})
    else:
        res = w.client.post(URL) if body is None else w.client.post(URL, json=body)
    settle(w)
    return res


def import_all(w) -> Dict[str, Any]:
    res = post(w, {"all_statements": True})
    assert res.status_code == 200, res.text
    return res.json()


def by_id(body) -> Dict[str, Dict[str, Any]]:
    return {s["message_id"]: s for s in body["statements"]}


def stored(w) -> Dict[str, Dict[str, Any]]:
    """Statement snapshots on file, by statement date."""
    return {d["snapshot_date"]: d for d in w.db.portfolio_snapshots.docs if d.get("statement_period_end")}


def live(w) -> List[str]:
    return sorted(d["ticker"] for d in w.db.holdings.docs if d["user_id"] == UID)


def profile(w) -> Dict[str, Any]:
    return next(d for d in w.db.user_profiles.docs if d["user_id"] == UID)


def on_file(w, date: str, period: str, tickers=(D,), **extra):
    """A statement already imported the usual way: profile fields + live rows, no snapshot."""
    profile(w).update({"cas_statement_date": date, "cas_statement_period": period,
                       "cas_portfolio_value_rs": 5000.0, "cas_monthly_values": [{"month": "x", "value_rs": 1.0}],
                       **extra})
    for t in tickers:
        w.db.holdings.docs.append({"holding_id": f"hold_{t}", "user_id": UID, "ticker": t, "name": t,
                                   "asset_type": "equity", "quantity": 1.0, "source": "cas"})


def fresh_calls(w):
    w.parsers.clear(), w.gmail.clear_calls(), w.db.writes.clear(), w.saves.clear()


# ══ the default import: unchanged ═════════════════════════════════════════════════════════════
DEFAULT_MAILBOX = [
    mail("m-nsdl", "nsdl", when(10, 5), statement("junk", tag="junk-nsdl")),
    mail("m-cdsl", "cdsl", when(10, 4), statement("cdsl", isins=(A, B), tag="cdsl-sep")),
    mail("m-cams", "cams", when(10, 3), statement("cams", "30-Sep-2026", (C,), tag="cams-sep")),
]
DEFAULT_RESPONSE = {
    "ok": True,
    "scanned": 3,
    "source_used": "cdsl",
    "sources_available": ["nsdl", "cdsl", "cams"],
    "imported_files": 1,
    "imported_holdings": 2,
    "imported_transactions": 0,
    "parse_errors": 1,
    "parse_error": None,
    "files": [
        {"message_id": "m-nsdl", "filename": "m-nsdl.pdf", "status": "error", "error": "parse_failed",
         "error_kind": "parse", "error_message": "The CAS statement couldn't be read (offline parser).",
         "error_detail": "not a statement", "holdings_count": 0},
        {"message_id": "m-cdsl", "filename": "m-cdsl.pdf", "status": "completed", "holdings_count": 2,
         "source": "cdsl", "statement_period": "Sep/2026", "portfolio_value_rs": 2000.0,
         "statement_date": "30-Sep-2026", "breakdown": {"equity": {"count": 2, "value_rs": 2000.0}},
         "monthly_values": [{"month": "Sep 2026", "value_rs": 9999.0}]},
    ],
}
DEFAULT_WRITES = [
    ("holdings", "delete_many"), ("holdings", "insert_one"), ("holdings", "insert_one"),
    ("mfd_profile_signal_cache", "delete_one"), ("upload_tasks", "update_one"),
    ("fund_performance_cache", "delete_many"), ("gmail_imports", "insert_one"),
    ("user_profiles", "update_one"), ("gmail_tokens", "update_one"),
]


@pytest.mark.parametrize("body, raw", [
    (None, None),                                   # what the Sync Gmail modal and onboarding send: no body
    ({}, None),                                     # what the legacy onboarding page sends
    ({"all_statements": False}, None),
    ({"all_statements": "true"}, None),             # only a JSON `true` opts in
    ({"all_statements": 1}, None),
    ({"other": True}, None),
    (None, b"not json at all"),
    (None, b"[true]"),
    (None, b"null"),
    (None, b"   "),
], ids=["no-body", "empty-object", "false", "string-true", "one", "other-key", "not-json", "list", "null", "blank"])
def test_default_call_stops_at_the_first_statement_that_parses_exactly_as_before(world, body, raw):
    w = world
    w.gmail.emails = list(DEFAULT_MAILBOX)
    w.vision_reply = VISION_REPLY

    res = post(w, body, raw)

    assert res.status_code == 200
    assert res.json() == DEFAULT_RESPONSE
    # The unreadable NSDL statement is tried, the CDSL one wins, the CAMS one is never opened.
    assert w.gmail.downloads == ["m-nsdl", "m-cdsl"]
    assert w.parsers.tags() == ["junk-nsdl", "cdsl-sep"]
    assert len(w.vision) == 1                        # the default import still makes its one model call
    assert w.db.writes == DEFAULT_WRITES
    assert w.saves == [{"user_id": UID, "file_type": "gmail_cas", "tickers": [A, B]}]
    assert live(w) == [A, B]
    assert stored(w) == {}                           # the default import stores no statement snapshot
    assert [q["maxResults"] for q in w.gmail.list_calls] == [3] * 8     # the one-per-source scan, not the history scan
    log = w.db.gmail_imports.docs
    assert [(d["message_id"], d["status"], d["source"], d["count"]) for d in log] == [("m-cdsl", "completed", "onboarding_gmail", 2)]
    p = profile(w)
    assert (p["cas_statement_period"], p["cas_statement_date"], p["cas_portfolio_value_rs"]) == ("Sep/2026", "30-Sep-2026", 2000.0)
    assert "cas_statement_source" not in p
    assert w.plans == [UID] and w.nidp == [UID]


@pytest.mark.parametrize("layout", ["nsdl", "cdsl", "cams", "offline"])
def test_the_history_reader_returns_the_holdings_the_default_import_saves(world, layout):
    """The extractor chain exists in two places (the default loop, and cas_history_import.parse_statement).
    This pins them together: for each layout, both read the same rows from the same statement."""
    from services import cas_history_import as history
    w = world
    content = statement(layout, "30-Sep-2026", (A, B, C), tag=f"parity-{layout}")
    w.gmail.emails = [mail("m-1", "nsdl", when(10, 3), content)]

    assert post(w).status_code == 200
    saved_by_default = sorted((d["ticker"], d["quantity"], d["current_price"]) for d in w.db.holdings.docs)

    parsed = history.parse_statement(content, PASSWORD)
    assert sorted((h["ticker"], float(h["quantity"]), float(h["current_price"])) for h in parsed.holdings) == saved_by_default
    assert parsed.layout == {"nsdl": "nsdl", "cdsl": "cdsl", "cams": "cams_kfin", "offline": "offline"}[layout]


# ══ all statements ════════════════════════════════════════════════════════════════════════════
def test_opt_in_imports_every_new_statement_and_shows_the_latest(world):
    w = world
    w.gmail.emails = three_months()

    body = import_all(w)

    assert {k: body[k] for k in ("ok", "mode", "months", "cap", "scanned", "attempted", "imported",
                                 "already_stored", "failed", "remaining")} == {
        "ok": True, "mode": "all_statements", "months": 12, "cap": 6, "scanned": 3, "attempted": 3,
        "imported": 3, "already_stored": 0, "failed": 0, "remaining": 0}
    assert [(s["message_id"], s["statement_date"], s["statement_period"], s["source"], s["status"], s["reason"], s["mounted"])
            for s in body["statements"]] == [
        ("m-sep", "2026-09-30", "Sep/2026", "nsdl", "imported", None, True),
        ("m-aug", "2026-08-31", "Aug/2026", "nsdl", "imported", None, False),
        ("m-jul", "2026-07-31", "Jul/2026", "nsdl", "imported", None, False),
    ]
    first = body["statements"][0]
    assert (first["consolidated"], first["date_source"], first["holdings_count"], first["filename"], first["email_date"]) == (
        True, "statement", 2, "m-sep.pdf", "2026-10-03")
    mounted = body["mounted"]
    assert {k: mounted[k] for k in ("changed", "statement_period", "statement_date", "source", "consolidated", "mf_only")} == {
        "changed": True, "statement_period": "Sep/2026", "statement_date": "2026-09-30", "source": "nsdl",
        "consolidated": True, "mf_only": False}
    assert isinstance(mounted["reason"], str) and "Sep/2026" in mounted["reason"]

    # One snapshot per statement, identified by email, file and date.
    snaps = stored(w)
    assert sorted(snaps) == ["2026-07-31", "2026-08-31", "2026-09-30"]
    sep = snaps["2026-09-30"]
    assert (sep["cas_source"], sep["gmail_message_id"], sep["file_sha256"], sep["cas_file_id"], sep["cas_filename"]) == (
        "nsdl", "m-sep", sha(SEP), "gmail:m-sep", "m-sep.pdf")
    assert (sep["statement_period_end"], sep["trigger"], sep["holdings_count"], sep["total_value"]) == ("2026-09-30", "cas_upload", 2, 2000.0)
    assert sorted(h["ticker"] for h in sep["holdings"]) == [A, B]
    assert "health_score" not in sep
    assert sorted(w.pg_mirror) == sorted(snaps)

    # The live portfolio is the September statement, written the way the default import writes it.
    assert w.saves == [{"user_id": UID, "file_type": "gmail_cas", "tickers": [A, B]}]
    assert live(w) == [A, B]
    assert {d["source"] for d in w.db.holdings.docs} == {"cas"}
    p = profile(w)
    assert (p["cas_statement_period"], p["cas_statement_date"], p["cas_portfolio_value_rs"], p["cas_monthly_values"]) == (
        "Sep/2026", "30-Sep-2026", 2000.0, MONTHLY)
    assert (p["cas_statement_source"], p["onboarding_completed"], p["journey_type"]) == ("nsdl", True, "existing_investor")
    assert w.db.gmail_tokens.docs[0]["auto_import_enabled"] is True
    assert w.plans == [UID] and w.nidp == [UID] and w.txn_bg == [(UID, SEP)]
    assert "cas_view_state" not in w.db.users.docs[0]        # nothing is mounted through the engine
    assert sorted((d["message_id"], d["status"], d["source"]) for d in w.db.gmail_imports.docs) == [
        ("m-aug", "completed", "cas_history"), ("m-jul", "completed", "cas_history"), ("m-sep", "completed", "cas_history")]
    assert w.vision == []


def test_a_second_identical_call_reads_nothing_and_writes_nothing(world):
    w = world
    w.gmail.emails = three_months()
    import_all(w)
    fresh_calls(w)

    body = import_all(w)

    assert (body["attempted"], body["imported"], body["already_stored"], body["failed"], body["remaining"]) == (0, 0, 3, 0, 0)
    assert [(s["message_id"], s["status"], s["statement_period"], s["source"]) for s in body["statements"]] == [
        ("m-sep", "already_stored", "Sep/2026", "nsdl"), ("m-aug", "already_stored", "Aug/2026", "nsdl"),
        ("m-jul", "already_stored", "Jul/2026", "nsdl")]
    assert w.parsers.calls == []                      # no parser call
    assert w.gmail.gets == [] and w.gmail.downloads == []   # not even opened in Gmail
    assert w.db.writes == [] and w.saves == []
    assert {k: body["mounted"][k] for k in ("changed", "statement_period", "statement_date", "source")} == {
        "changed": False, "statement_period": "Sep/2026", "statement_date": "2026-09-30", "source": "nsdl"}


def test_the_latest_statement_by_its_own_date_is_shown_even_when_emails_arrive_out_of_order(world):
    w = world
    on_file(w, "31-Jul-2026", "Jul/2026")
    # The August statement was re-sent after the September one, so it is the newer EMAIL.
    w.gmail.emails = [mail("m-aug-resent", "nsdl", when(10, 6), AUG), mail("m-sep", "nsdl", when(10, 3), SEP)]

    body = import_all(w)

    assert [(s["message_id"], s["mounted"]) for s in body["statements"]] == [("m-sep", True), ("m-aug-resent", False)]
    assert body["mounted"]["statement_date"] == "2026-09-30" and body["mounted"]["changed"] is True
    assert w.parsers.tags() == ["nsdl:31-Aug-2026", "nsdl:30-Sep-2026"]      # read in email order
    assert w.saves == [{"user_id": UID, "file_type": "gmail_cas", "tickers": [A, B]}]     # saved once, September
    assert live(w) == [A, B]
    assert profile(w)["cas_statement_date"] == "30-Sep-2026"


def test_an_older_statement_is_stored_but_never_touches_the_live_portfolio(world):
    w = world
    on_file(w, "30-Sep-2026", "Sep/2026")
    before = copy.deepcopy(profile(w))
    w.gmail.emails = [mail("m-aug", "nsdl", when(9, 3), AUG), mail("m-jul", "nsdl", when(8, 4), JUL)]

    body = import_all(w)

    assert [(s["status"], s["mounted"]) for s in body["statements"]] == [("imported", False), ("imported", False)]
    assert sorted(stored(w)) == ["2026-07-31", "2026-08-31"]
    assert w.saves == [] and live(w) == [D]
    assert profile(w) == before
    assert not [x for x in w.db.writes if x[0] in ("holdings", "user_profiles", "gmail_tokens")]
    assert w.plans == [] and w.nidp == [] and w.txn_bg == []
    assert {k: body["mounted"][k] for k in ("changed", "statement_period", "statement_date", "source", "consolidated")} == {
        "changed": False, "statement_period": "Sep/2026", "statement_date": "2026-09-30", "source": None, "consolidated": None}


def test_a_statement_with_the_same_date_as_the_one_on_file_is_stored_and_not_saved_again(world):
    w = world
    on_file(w, "30-Sep-2026", "Sep/2026", tickers=(A, B))
    w.gmail.emails = three_months()

    body = import_all(w)

    assert body["imported"] == 3 and body["mounted"]["changed"] is False
    assert w.saves == [] and live(w) == [A, B]
    # The stored snapshot tells us what kind of statement is on file.
    assert (body["mounted"]["source"], body["mounted"]["consolidated"]) == ("nsdl", True)


def test_one_failing_statement_is_reported_and_the_rest_continue(world):
    w = world
    w.gmail.emails = [mail("m-sep", "nsdl", when(10, 3), SEP),
                      mail("m-bad", "nsdl", when(9, 20), statement("junk", tag="bad"), filename="notice.pdf"),
                      mail("m-crash", "nsdl", when(9, 10), statement("crash", tag="crash")),
                      mail("m-gone", "nsdl", when(9, 5), AUG, download_error=True),
                      mail("m-inline", "nsdl", when(9, 4), None, inline_pdf=True),
                      mail("m-jul", "nsdl", when(8, 4), JUL)]

    body = import_all(w)

    rows = by_id(body)
    assert {m: (r["status"], r["error_kind"]) for m, r in rows.items()} == {
        "m-sep": ("imported", None), "m-jul": ("imported", None), "m-bad": ("failed", "parse"),
        "m-crash": ("failed", "service"), "m-gone": ("failed", "download"), "m-inline": ("failed", "no_pdf")}
    assert rows["m-bad"]["reason"] == "This PDF could not be read as a CAS statement."
    assert rows["m-crash"]["reason"] == "The statement reader hit an error. Try again."
    assert rows["m-gone"]["reason"] == "The statement could not be downloaded from Gmail."
    assert rows["m-inline"]["reason"] == "This email has no PDF statement that can be downloaded."
    assert (rows["m-bad"]["filename"], rows["m-bad"]["statement_date"], rows["m-bad"]["statement_period"]) == ("notice.pdf", None, None)
    assert (body["ok"], body["imported"], body["failed"], body["parse_errors"], body["parse_error"]) == (True, 2, 4, 4, None)
    assert sorted(stored(w)) == ["2026-07-31", "2026-09-30"]
    assert body["mounted"]["statement_date"] == "2026-09-30"
    failed_log = {d["message_id"]: d for d in w.db.gmail_imports.docs if d["status"] == "failed"}
    assert sorted(failed_log) == ["m-bad", "m-crash", "m-gone", "m-inline"]
    assert (failed_log["m-bad"]["reason"], failed_log["m-bad"]["error_kind"], failed_log["m-bad"]["source"]) == (
        "This PDF could not be read as a CAS statement.", "parse", "cas_history")


def test_the_cap_is_honoured_and_the_rest_is_reported_for_the_next_call(world):
    w = world
    months = [(2, "28-Feb-2026"), (3, "31-Mar-2026"), (4, "30-Apr-2026"), (5, "31-May-2026"),
              (6, "30-Jun-2026"), (7, "31-Jul-2026"), (8, "31-Aug-2026"), (9, "30-Sep-2026")]
    w.gmail.emails = [mail(f"m-{m:02d}", "nsdl", when(m + 1, 3), nsdl(d, (A,))) for m, d in months]

    first = import_all(w)

    assert (first["scanned"], first["cap"], first["attempted"], first["imported"], first["remaining"]) == (8, 6, 6, 6, 2)
    assert len(first["statements"]) == 6
    assert sorted(w.parsers.tags()) == sorted(f"nsdl:{d}" for _, d in months[2:])       # the six newest
    assert sorted(stored(w)) == ["2026-04-30", "2026-05-31", "2026-06-30", "2026-07-31", "2026-08-31", "2026-09-30"]
    assert first["mounted"]["statement_date"] == "2026-09-30"

    fresh_calls(w)
    second = import_all(w)

    assert (second["attempted"], second["imported"], second["already_stored"], second["remaining"]) == (2, 2, 6, 0)
    assert sorted(w.parsers.tags()) == ["nsdl:28-Feb-2026", "nsdl:31-Mar-2026"]          # only the two left over
    assert len(stored(w)) == 8
    assert w.saves == [] and second["mounted"]["changed"] is False                        # the older ones change nothing live


def test_statements_that_failed_before_do_not_hold_up_the_ones_not_yet_tried(world):
    w = world
    junk = [mail(f"m-junk{i}", "nsdl", when(10, 12 - i), statement("junk", tag=f"junk{i}")) for i in range(1, 7)]
    w.gmail.emails = junk + [mail("m-aug", "nsdl", when(9, 3), AUG), mail("m-jul", "nsdl", when(8, 4), JUL)]

    first = import_all(w)
    assert (first["attempted"], first["imported"], first["failed"], first["remaining"], first["ok"]) == (6, 0, 6, 2, False)
    assert first["parse_error"] == {"kind": "parse", "message": "This PDF could not be read as a CAS statement."}

    fresh_calls(w)
    second = import_all(w)

    # The two untried statements go first; the room left under the cap retries four of the failures.
    assert w.parsers.tags() == ["nsdl:31-Aug-2026", "nsdl:31-Jul-2026", "junk1", "junk2", "junk3", "junk4"]
    assert (second["attempted"], second["imported"], second["failed"], second["remaining"], second["ok"]) == (6, 2, 6, 0, True)
    rows = by_id(second)
    assert rows["m-junk6"]["status"] == "failed" and rows["m-junk6"]["reason"] == "This PDF could not be read as a CAS statement."
    assert w.gmail.downloads.count("m-junk6") == 0           # reported from the log, not read again
    attempts = {d["message_id"]: d["attempts"] for d in w.db.gmail_imports.docs if d["status"] == "failed"}
    assert (attempts["m-junk1"], attempts["m-junk6"]) == (2, 1)


def test_nothing_is_stored_or_shown_when_no_statement_parses(world):
    w = world
    on_file(w, "30-Jun-2026", "Jun/2026")
    before = copy.deepcopy(profile(w))
    w.gmail.emails = [mail("m-1", "nsdl", when(10, 3), statement("locked", tag="locked")),
                      mail("m-2", "nsdl", when(9, 3), statement("junk", tag="junk"))]

    body = import_all(w)

    assert (body["ok"], body["imported"], body["failed"]) == (False, 0, 2)
    assert body["parse_error"] == {"kind": "password", "message": "The password did not unlock this statement. "
                                   "Check the PAN or statement password under Sync Gmail."}
    assert by_id(body)["m-1"]["error_kind"] == "password"
    assert stored(w) == {} and w.saves == [] and live(w) == [D] and profile(w) == before
    assert w.pg_mirror == [] and w.plans == [] and w.nidp == []
    # The only writes are the two rows that remember which emails failed.
    assert w.db.writes == [("gmail_imports", "update_one"), ("gmail_imports", "update_one")]
    assert body["mounted"]["changed"] is False and body["mounted"]["statement_period"] == "Jun/2026"


def test_no_statements_in_gmail_is_an_empty_answer(world):
    w = world
    body = import_all(w)
    assert (body["ok"], body["scanned"], body["statements"], body["remaining"]) == (True, 0, [], 0)
    assert body["message"] == "No CAS statements were found in this Gmail account in the last 12 months."
    assert w.db.writes == []


# ── which statement is "the portfolio" ───────────────────────────────────────────────────────
def test_same_date_from_two_sources_in_one_call_keeps_the_higher_priority_source(world):
    w = world
    cams = statement("cams", "30-Sep-2026", (C,), tag="cams-sep")
    w.gmail.emails = [mail("m-cams", "cams", when(10, 4), cams), mail("m-nsdl", "nsdl", when(10, 3), SEP)]

    body = import_all(w)

    rows = by_id(body)
    assert (rows["m-nsdl"]["status"], rows["m-cams"]["status"]) == ("imported", "already_stored")
    assert rows["m-cams"]["reason"] == "The NSDL statement for the same date is kept instead."
    snap = stored(w)
    assert list(snap) == ["2026-09-30"] and snap["2026-09-30"]["cas_source"] == "nsdl"
    assert sorted(h["ticker"] for h in snap["2026-09-30"]["holdings"]) == [A, B]
    assert live(w) == [A, B]

    fresh_calls(w)
    again = import_all(w)
    assert w.parsers.calls == [] and w.gmail.downloads == []          # the CAMS email is remembered
    assert by_id(again)["m-cams"]["status"] == "already_stored"


def test_a_higher_priority_statement_replaces_a_stored_one_for_the_same_date_and_not_the_reverse(world):
    w = world
    cams = statement("cams", "30-Sep-2026", (C,), tag="cams-sep")
    w.gmail.emails = [mail("m-cams", "cams", when(10, 4), cams)]
    import_all(w)
    assert stored(w)["2026-09-30"]["cas_source"] == "cams"

    w.gmail.emails.append(mail("m-nsdl", "nsdl", when(10, 6), SEP))
    fresh_calls(w)
    body = import_all(w)

    assert by_id(body)["m-nsdl"]["status"] == "imported"
    snap = stored(w)["2026-09-30"]
    assert (snap["cas_source"], snap["gmail_message_id"], snap["holdings_count"]) == ("nsdl", "m-nsdl", 2)
    assert "m-cams" in snap["duplicate_message_ids"]
    assert w.parsers.tags() == ["nsdl:30-Sep-2026"]                    # the CAMS statement is not read again

    # A CDSL statement for that date arrives later: lower priority than NSDL, so nothing changes.
    w.gmail.emails.append(mail("m-cdsl", "cdsl", when(10, 7), statement("cdsl", isins=(D,), tag="cdsl-sep"),
                               filename="CDSL_CAS_SEP_2026.pdf"))
    fresh_calls(w)
    third = import_all(w)
    assert (by_id(third)["m-cdsl"]["status"], by_id(third)["m-cdsl"]["reason"]) == (
        "already_stored", "The NSDL statement for the same date is kept instead.")
    assert stored(w)["2026-09-30"]["cas_source"] == "nsdl"
    assert ("portfolio_snapshots", "update_one") in w.db.writes and w.pg_mirror.count("2026-09-30") == 2

    fresh_calls(w)
    import_all(w)
    assert w.parsers.calls == [] and w.gmail.downloads == [] and w.db.writes == []


def test_a_mutual_fund_statement_newer_than_the_consolidated_one_is_stored_and_does_not_replace_it(world):
    w = world
    w.gmail.emails = [mail("m-sep", "nsdl", when(10, 3), SEP)]
    import_all(w)
    assert live(w) == [A, B]

    w.gmail.emails.append(mail("m-cams", "cams", when(10, 11), statement("cams", "10-Oct-2026", (C, D), tag="cams-oct")))
    fresh_calls(w)
    before = copy.deepcopy(profile(w))
    body = import_all(w)

    row = by_id(body)["m-cams"]
    assert (row["status"], row["source"], row["consolidated"], row["statement_date"], row["mounted"]) == (
        "imported", "cams", False, "2026-10-10", False)
    assert stored(w)["2026-10-10"]["cas_source"] == "cams"
    assert w.saves == [] and live(w) == [A, B] and profile(w) == before
    m = body["mounted"]
    assert (m["changed"], m["statement_period"], m["source"], m["consolidated"], m["mf_only"]) == (False, "Sep/2026", "nsdl", True, False)
    assert m["reason"] == ("A newer mutual-fund statement (Oct/2026) was stored. It does not replace your "
                           "consolidated portfolio (Sep/2026).")


def test_a_mutual_fund_statement_does_not_replace_a_statement_on_file_of_unknown_kind(world):
    w = world
    on_file(w, "30-Sep-2026", "Sep/2026")              # imported the usual way: its source was never recorded
    w.gmail.emails = [mail("m-cams", "cams", when(10, 11), statement("cams", "10-Oct-2026", (C,), tag="cams-oct"))]

    body = import_all(w)

    assert by_id(body)["m-cams"]["status"] == "imported"
    assert w.saves == [] and live(w) == [D]
    assert body["mounted"]["changed"] is False and body["mounted"]["consolidated"] is None


def test_with_no_consolidated_statement_at_all_the_latest_mutual_fund_one_is_the_portfolio_and_says_so(world):
    w = world
    w.gmail.emails = [mail("m-cams-sep", "cams", when(10, 2), statement("cams", "30-Sep-2026", (C, D), tag="cams-sep")),
                      mail("m-kfin-aug", "kfintech", when(9, 2), statement("cams", "31-Aug-2026", (C,), tag="kfin-aug"))]

    body = import_all(w)

    m = body["mounted"]
    assert (m["changed"], m["statement_period"], m["source"], m["consolidated"], m["mf_only"]) == (True, "Sep/2026", "cams", False, True)
    assert m["reason"] == ("No consolidated (NSDL or CDSL) statement was found, so your portfolio shows the "
                           "latest mutual-fund statement (Sep/2026).")
    assert by_id(body)["m-kfin-aug"]["source"] == "kfintech"
    assert live(w) == [C, D] and profile(w)["cas_statement_source"] == "cams"
    assert w.txn_bg == []                               # the NSDL transaction pass is for NSDL statements only

    # A newer mutual-fund statement replaces a mutual-fund portfolio …
    w.gmail.emails.append(mail("m-cams-oct", "cams", when(10, 11), statement("cams", "10-Oct-2026", (C,), tag="cams-oct")))
    fresh_calls(w)
    assert import_all(w)["mounted"]["statement_date"] == "2026-10-10"
    assert live(w) == [C]

    # … and a consolidated statement that is newer still takes over from it.
    w.gmail.emails.append(mail("m-nsdl-oct", "nsdl", when(11, 3), nsdl("31-Oct-2026", (A,))))
    w.gmail.today = datetime(2026, 11, 14, tzinfo=timezone.utc)
    fresh_calls(w)
    third = import_all(w)
    assert (third["mounted"]["source"], third["mounted"]["mf_only"], third["mounted"]["changed"]) == ("nsdl", False, True)
    assert live(w) == [A]


def test_a_consolidated_statement_older_than_the_mutual_fund_one_on_file_is_stored_only(world):
    w = world
    on_file(w, "10-Oct-2026", "Oct/2026", cas_statement_source="cams")
    w.gmail.emails = [mail("m-sep", "nsdl", when(10, 3), SEP)]

    body = import_all(w)

    assert by_id(body)["m-sep"]["status"] == "imported" and w.saves == [] and live(w) == [D]
    m = body["mounted"]
    assert (m["changed"], m["source"], m["mf_only"]) == (False, "cams", True)
    assert m["reason"] == ("A consolidated statement (Sep/2026) was stored, but it is older than the mutual-fund "
                           "statement your portfolio shows (Oct/2026), so nothing was changed.")


def test_holdings_on_file_without_a_statement_date_are_never_replaced(world):
    w = world
    w.db.holdings.docs.append({"holding_id": "hold_x", "user_id": UID, "ticker": D, "source": "cas", "quantity": 1.0})
    w.gmail.emails = [mail("m-sep", "nsdl", when(10, 3), SEP)]

    body = import_all(w)

    assert body["imported"] == 1 and w.saves == [] and live(w) == [D]
    assert body["mounted"]["changed"] is False
    assert body["mounted"]["reason"] == ("The date of the statement your portfolio shows is not on record, so it "
                                         "was left as it is. Use Sync Gmail to show the latest statement.")


# ── statements whose date the reader cannot give ─────────────────────────────────────────────
def test_no_model_call_is_made_on_the_history_path(world, monkeypatch):
    w = world
    w.vision_reply = VISION_REPLY                       # the model would answer, if it were asked

    def no_key():
        raise AssertionError("the model key was read on the history path")
    monkeypatch.setattr(cas_summary_vision, "_get_openai_key", no_key)
    w.gmail.emails = [
        mail("m-cdsl", "cdsl", when(10, 3), statement("cdsl", isins=(A,), tag="cdsl-sep"), filename="CDSL_CAS_SEP_2026.pdf"),
        mail("m-off-cams", "cams", when(9, 3), statement("offline", "31-Aug-2026", (C,), tag="off-cams")),
        mail("m-off-nsdl", "nsdl", when(8, 3), statement("offline", "31-Jul-2026", (B,), tag="off-nsdl", file_type="NSDL")),
        mail("m-nsdl", "nsdl", when(7, 3), nsdl("30-Jun-2026", (D,))),
    ]

    body = import_all(w)

    assert body["imported"] == 4 and body["failed"] == 0
    assert w.vision == []
    # The default import of the same CDSL statement does make the call — the difference is the path.
    w.gmail.emails = w.gmail.emails[:1]
    assert post(w).status_code == 200
    assert len(w.vision) == 1


def test_a_statement_read_by_the_fallback_parser_takes_its_kind_and_date_from_the_statement(world):
    w = world
    w.gmail.emails = [
        mail("m-off-nsdl", "cams", when(10, 3), statement("offline", "30-Sep-2026", (A,), tag="off-nsdl", file_type="NSDL")),
        mail("m-off-cams", "nsdl", when(9, 3), statement("offline", "2026-08-31", (C,), tag="off-cams", file_type="CAMS")),
    ]

    rows = by_id(import_all(w))

    # The file says what it is, whoever sent the email.
    assert (rows["m-off-nsdl"]["source"], rows["m-off-nsdl"]["consolidated"], rows["m-off-nsdl"]["date_source"]) == ("nsdl", True, "statement")
    assert (rows["m-off-cams"]["source"], rows["m-off-cams"]["consolidated"], rows["m-off-cams"]["statement_date"]) == ("cams", False, "2026-08-31")
    assert rows["m-off-nsdl"]["mounted"] is True and w.txn_bg == []


def test_a_cdsl_statement_takes_its_date_from_the_file_name_or_the_subject_or_is_skipped(world):
    w = world
    cdsl = lambda tag, isin: statement("cdsl", isins=(isin,), tag=tag)   # noqa: E731 — the CDSL reader gives no date
    w.gmail.emails = [
        mail("m-file", "cdsl", when(10, 3), cdsl("c-sep", A), filename="CDSL_CAS_SEP_2026.pdf"),
        mail("m-subject", "cdsl", when(9, 4), cdsl("c-aug", B), filename="statement.pdf",
             subject="CDSL Consolidated Account Statement for Aug 2026"),
        mail("m-neither", "cdsl", when(8, 4), cdsl("c-jul", C), filename="statement.pdf", subject="Your CDSL statement"),
        # A file name for a month that had not ended when the email was sent cannot be the statement date.
        mail("m-future", "cdsl", when(7, 5), cdsl("c-future", D), filename="CAS_JUL_2026.pdf"),
    ]

    body = import_all(w)

    rows = by_id(body)
    assert (rows["m-file"]["status"], rows["m-file"]["statement_date"], rows["m-file"]["statement_period"], rows["m-file"]["date_source"]) == (
        "imported", "2026-09-30", "Sep/2026", "file_name")
    assert (rows["m-subject"]["status"], rows["m-subject"]["statement_date"], rows["m-subject"]["date_source"]) == (
        "imported", "2026-08-31", "email_subject")
    for m in ("m-neither", "m-future"):
        assert (rows[m]["status"], rows[m]["error_kind"], rows[m]["statement_date"]) == ("failed", "no_date", None)
        assert rows[m]["reason"] == "The statement date could not be read from the statement, its file name or the email subject."
    assert sorted(stored(w)) == ["2026-08-31", "2026-09-30"]
    assert stored(w)["2026-09-30"]["cas_source"] == "cdsl" and stored(w)["2026-09-30"]["statement_date_source"] == "file_name"
    assert w.vision == []


def test_a_statement_dated_from_its_file_name_is_stored_but_not_made_the_live_portfolio(world):
    w = world
    w.gmail.emails = [
        mail("m-cdsl", "cdsl", when(10, 3), statement("cdsl", isins=(C,), tag="c-sep"), filename="CDSL_CAS_SEP_2026.pdf"),
        mail("m-aug", "nsdl", when(9, 3), AUG),
    ]

    body = import_all(w)

    # Nothing was on file, so the August NSDL statement (whose date the statement itself gives) is shown …
    assert by_id(body)["m-cdsl"]["mounted"] is False and by_id(body)["m-aug"]["mounted"] is True
    assert live(w) == [A] and profile(w)["cas_statement_date"] == "31-Aug-2026"
    # … and the answer says a newer one is waiting.
    assert body["mounted"]["reason"] == (
        "Your portfolio now shows the NSDL statement for Aug/2026. A newer CDSL statement (Sep/2026) was stored, "
        "but its date was read from the file name, so it was not made your current portfolio. Use Sync Gmail to show it.")


def test_the_same_pdf_under_another_email_is_recognised_without_reading_it_again(world):
    w = world
    w.gmail.emails = [mail("m-copy", "nsdl", when(10, 6), SEP), mail("m-sep", "nsdl", when(10, 3), SEP)]

    body = import_all(w)

    rows = by_id(body)
    assert (rows["m-copy"]["status"], rows["m-sep"]["status"]) == ("imported", "already_stored")
    assert rows["m-sep"]["reason"] == "This file is already stored."
    assert [c for c in w.parsers.calls if c[0] == "nsdl"] == [("nsdl", "nsdl:30-Sep-2026")]      # read once
    assert len(stored(w)) == 1 and stored(w)["2026-09-30"]["duplicate_message_ids"] == ["m-sep"]

    # Stored earlier, found again under a new email later.
    w.gmail.emails.append(mail("m-forward", "nsdl", when(10, 9), SEP))
    fresh_calls(w)
    again = import_all(w)
    assert by_id(again)["m-forward"]["status"] == "already_stored"
    assert w.gmail.downloads == ["m-forward"] and w.parsers.calls == []       # downloaded to compare, never parsed

    fresh_calls(w)
    import_all(w)
    assert w.gmail.downloads == [] and w.gmail.gets == []


# ── showing the latest: the same save as the default import ──────────────────────────────────
def test_the_broker_wins_rule_still_applies_when_the_latest_statement_is_shown(world):
    w = world
    on_file(w, "31-Aug-2026", "Aug/2026", tickers=(D,))
    w.db.holdings.docs.append({"holding_id": "hold_broker", "user_id": UID, "ticker": "TESTCO", "isin": A,
                               "asset_type": "equity", "quantity": 7.0, "source": "broker_native",
                               "broker": "zerodha", "broker_account_id": "ba_1"})
    w.gmail.emails = [mail("m-sep", "nsdl", when(10, 3), SEP)]      # the statement holds A and B

    body = import_all(w)

    assert body["mounted"]["changed"] is True
    rows = {d["holding_id"] if d.get("broker_account_id") else d["ticker"]: d for d in w.db.holdings.docs}
    assert sorted(rows) == [B, "hold_broker"]          # the broker's A stays, the statement's A is left out, D is replaced
    assert rows["hold_broker"]["quantity"] == 7.0 and rows[B]["source"] == "cas"
    # The stored snapshot keeps the statement as printed, A included.
    assert sorted(h["ticker"] for h in stored(w)["2026-09-30"]["holdings"]) == [A, B]


def test_a_statement_that_cannot_be_saved_as_the_portfolio_is_reported_and_not_stored(world):
    w = world
    on_file(w, "31-Jul-2026", "Jul/2026")
    before = copy.deepcopy(profile(w))
    w.save_error = RuntimeError("mongo is down")
    w.gmail.emails = [mail("m-sep", "nsdl", when(10, 3), SEP), mail("m-aug", "nsdl", when(9, 3), AUG)]

    body = import_all(w)

    rows = by_id(body)
    assert (rows["m-sep"]["status"], rows["m-sep"]["error_kind"], rows["m-sep"]["mounted"]) == ("failed", "mount", False)
    assert rows["m-sep"]["reason"] == "The statement could not be saved as your current portfolio. Try again."
    assert rows["m-aug"]["status"] == "imported"
    assert sorted(stored(w)) == ["2026-08-31"]          # the September statement will be tried again next time
    assert profile(w) == before and live(w) == [D]
    assert body["mounted"]["changed"] is False and body["mounted"]["statement_period"] == "Jul/2026"


def test_a_statement_that_cannot_be_stored_is_reported_and_the_rest_continue(world, monkeypatch):
    w = world
    w.gmail.emails = [mail("m-sep", "nsdl", when(10, 3), SEP), mail("m-aug", "nsdl", when(9, 3), AUG)]
    real = eng.store_cas_snapshot

    async def flaky(**kw):
        if kw["period_end"] == "2026-08-31":
            raise RuntimeError("write failed")
        return await real(**kw)
    monkeypatch.setattr(eng, "store_cas_snapshot", flaky)

    rows = by_id(import_all(w))

    assert (rows["m-aug"]["status"], rows["m-aug"]["error_kind"]) == ("failed", "store")
    assert rows["m-aug"]["reason"] == "The statement was read but could not be stored. Try again."
    assert rows["m-sep"]["status"] == "imported" and sorted(stored(w)) == ["2026-09-30"]


# ── before any statement is read ─────────────────────────────────────────────────────────────
def test_the_opt_in_mode_makes_the_same_checks_as_the_default_before_it_reads_gmail(world):
    w = world
    w.gmail.emails = three_months()

    w.db.user_profiles.docs[0].pop("pan")
    res = post(w, {"all_statements": True})
    assert (res.status_code, res.json()["detail"]) == (400, "PAN missing — submit /api/onboarding/pan first.")

    w.db.gmail_tokens.docs.clear()
    res = post(w, {"all_statements": True})
    assert (res.status_code, res.json()["detail"]) == (400, "Gmail not connected — complete the OAuth step first.")
    assert w.gmail.list_calls == [] and w.db.writes == []


def test_an_expired_gmail_session_is_reported_as_one_and_not_as_no_statements(world):
    w = world
    w.gmail.emails = three_months()
    w.gmail.fail_lists = True

    res = post(w, {"all_statements": True})

    assert (res.status_code, res.json()["detail"]) == (401, "Gmail session expired — please reconnect.")
    assert w.db.gmail_tokens.docs == []                 # as the default import does
    assert stored(w) == {} and w.saves == []


def test_the_unlock_password_reaches_the_readers_and_nothing_else(world):
    w = world
    profile(w)["cas_pdf_password"] = "Custom-Pw-1"       # a statement password the user saved; wins over the PAN
    w.gmail.emails = [mail("m-sep", "nsdl", when(10, 3), SEP)]

    body = import_all(w)

    assert set(w.parsers.passwords) == {"Custom-Pw-1"}
    assert "Custom-Pw-1" not in repr(body) and PASSWORD not in repr(body)
    assert "Custom-Pw-1" not in repr(w.db.portfolio_snapshots.docs) + repr(w.db.gmail_imports.docs)


# ══ the Gmail history scan (services.gmail_service) ═══════════════════════════════════════════
def test_the_history_scan_lists_twelve_months_of_every_source_newest_first_across_pages(monkeypatch):
    box = FakeGmail(today=NOW)
    box.emails = [mail(f"n{i:03d}", "nsdl", datetime(2026, 10, 1, tzinfo=timezone.utc).replace(day=1 + i % 28, month=10 - i // 28), SEP)
                  for i in range(130)]
    box.emails += [mail("c1", "cams", when(9, 9), SEP), mail("k1", "kfintech", when(9, 8), SEP),
                   mail("old", "cdsl", datetime(2025, 9, 1, tzinfo=timezone.utc), SEP),      # 13 months back
                   mail("d1", "cdsl", when(10, 2), SEP)]

    found = gmail_service.list_cas_history(box)

    assert list(found) == ["nsdl", "cdsl", "cams", "kfintech"]
    assert found["cdsl"] == ["d1"] and found["cams"] == ["c1"] and found["kfintech"] == ["k1"]
    newest_first = [e["id"] for e in sorted(box.emails[:130], key=lambda e: e["when"], reverse=True)]
    assert found["nsdl"] == newest_first[:gmail_service.HISTORY_MAX_PER_SOURCE]
    assert all("newer_than:12m" in c["q"] and "has:attachment filename:pdf" in c["q"] for c in box.list_calls)
    assert any(c["pageToken"] for c in box.list_calls)                  # it followed the next page
    assert box.gets == []                                               # listing opens no email
    assert len({m for ids in found.values() for m in ids}) == sum(len(ids) for ids in found.values())   # each email once


def test_the_history_scan_reads_one_email_into_the_shape_the_existing_scan_returns():
    box = FakeGmail(today=NOW)
    box.emails = [mail("m-sep", "nsdl", when(10, 3), SEP, filename="NSDLe-CAS_SEP_2026.PDF", subject="NSDL CAS"),
                  mail("m-inline", "cams", when(10, 2), None, inline_pdf=True)]

    email = gmail_service.fetch_cas_email(box, "m-sep", "cams")       # filed under the wrong query on purpose

    assert (email["message_id"], email["source"], email["filename"], email["subject"]) == ("m-sep", "nsdl", "NSDLe-CAS_SEP_2026.PDF", "NSDL CAS")
    assert email["attachment_id"].startswith("att-m-sep-") and email["date_dt"] == when(10, 3)
    assert set(gmail_service.scan_for_cas_emails(box)[0]) <= set(email)     # every key the existing scan gives
    assert gmail_service.fetch_cas_email(box, "m-inline", "cams") is None  # no downloadable PDF


def test_the_history_scan_fails_loudly_when_gmail_answers_no_query():
    box = FakeGmail(today=NOW)
    box.fail_lists = True
    with pytest.raises(RuntimeError, match="invalid_grant"):
        gmail_service.list_cas_history(box)


# ══ the engine's store-only function ══════════════════════════════════════════════════════════
def _store(**over):
    kw = dict(user_id=UID, holdings=[holding(A, 2, 50.0), holding(B, 1, 10.0)], transactions=[], sips_detected=[],
              period_start=None, period_end="2026-09-30", cas_file_id="gmail:m-1", cas_filename="sep.pdf",
              cas_source="nsdl", gmail_message_id="m-1", file_sha256="abc")
    kw.update(over)
    return asyncio.run(eng.store_cas_snapshot(**kw))


def test_store_cas_snapshot_stores_one_statement_and_does_nothing_else(world):
    w = world
    w.db.holdings.docs.append({"holding_id": "hold_live", "user_id": UID, "ticker": D, "source": "cas"})

    snap = _store()

    doc = stored(w)["2026-09-30"]
    assert (doc["user_id"], doc["cas_source"], doc["gmail_message_id"], doc["file_sha256"]) == (UID, "nsdl", "m-1", "abc")
    assert (doc["total_value"], doc["holdings_count"], doc["statement_period_end"], doc["trigger"], doc["source"]) == (
        110.0, 2, "2026-09-30", "cas_upload", "cas_upload")
    assert snap["snapshot_date"] == "2026-09-30" and snap["is_latest"] is True
    assert w.db.writes == [("portfolio_snapshots", "update_one")]       # one write; the Postgres mirror is the fake below
    assert w.pg_mirror == ["2026-09-30"]
    assert live(w) == [D] and "cas_view_state" not in w.db.users.docs[0]
    # (the fixture's tripwires fail the test if a mount, a health run or an NIDP push is reached)

    older = _store(period_end="2026-08-31", gmail_message_id="m-0", file_sha256="def")
    assert older["is_latest"] is False and live(w) == [D]


@pytest.mark.parametrize("period_end", [None, "", "30-Sep-2026", "2026-13-01", "not a date"])
def test_store_cas_snapshot_requires_an_iso_period_end(world, period_end):
    with pytest.raises(ValueError, match="period_end"):
        _store(period_end=period_end)
    assert world.db.writes == []


def test_the_snapshot_list_carries_the_new_identity_fields(world):
    _store()
    world.db.portfolio_snapshots.docs.append({"user_id": UID, "snapshot_date": "2026-10-13", "trigger": "eod_cron", "total_value": 1.0})

    res = world.client.get("/api/portfolio/cas-snapshots")

    assert res.status_code == 200
    rows = {r["snapshot_date"]: r for r in res.json()["snapshots"]}
    assert (rows["2026-09-30"]["cas_source"], rows["2026-09-30"]["gmail_message_id"], rows["2026-09-30"]["file_sha256"]) == ("nsdl", "m-1", "abc")
    assert "holdings" not in rows["2026-09-30"]
    assert rows["2026-10-13"] == {"snapshot_date": "2026-10-13", "trigger": "eod_cron", "total_value": 1.0}   # older rows read as before


# ══ whose snapshots a caller may read ═════════════════════════════════════════════════════════
@pytest.fixture()
def book(world, monkeypatch):
    """Two advisors, each with one client. Snapshots exist for the caller, their client and the other's client."""
    w = world
    w.db.workspaces.docs += [{"workspace_id": "ws-mine", "owner_user_id": UID},
                             {"workspace_id": "ws-theirs", "owner_user_id": "advisor-2"}]
    w.db.profiles.docs += [
        {"profile_id": "p-mine", "workspace_id": "ws-mine", "shadow_user_id": "shadow-mine"},
        {"profile_id": "p-theirs", "workspace_id": "ws-theirs", "shadow_user_id": "shadow-theirs"},
    ]
    for uid in (UID, "shadow-mine", "shadow-theirs"):
        w.db.portfolio_snapshots.docs.append({"user_id": uid, "snapshot_date": "2026-09-30", "total_value": 1.0,
                                              "statement_period_end": "2026-09-30", "holdings": [holding(A)],
                                              "cas_filename": f"{uid}.pdf"})
    w.caller = {"user_id": UID, "_session_user_id": UID}

    async def current_user(request):
        return dict(w.caller)
    monkeypatch.setattr(cas_routes, "get_current_user", current_user)
    return w


READS = ["/api/portfolio/cas-snapshots", "/api/portfolio/cas-snapshot", "/api/portfolio/cas-performance",
         "/api/portfolio/cas-sip-summary", "/api/portfolio/cas-sip-breakdown?month=2026-09",
         "/api/portfolio/cas-top-transactions"]


def _with(path: str, profile_id: str) -> str:
    return f"{path}{'&' if '?' in path else '?'}profile_id={profile_id}"


def test_snapshots_without_a_profile_id_are_the_callers_own(book):
    res = book.client.get("/api/portfolio/cas-snapshots")
    assert res.status_code == 200 and [s["cas_filename"] for s in res.json()["snapshots"]] == [f"{UID}.pdf"]


def test_an_advisor_reads_a_client_of_their_own_workspace(book):
    res = book.client.get(_with("/api/portfolio/cas-snapshots", "p-mine"))
    assert res.status_code == 200 and [s["cas_filename"] for s in res.json()["snapshots"]] == ["shadow-mine.pdf"]
    # Still theirs while they are acting as that client: the session owner is what is checked.
    book.caller = {"user_id": "shadow-mine", "_session_user_id": UID}
    assert book.client.get(_with("/api/portfolio/cas-snapshots", "p-mine")).status_code == 200


@pytest.mark.parametrize("path", READS)
def test_another_workspaces_profile_id_is_refused_on_every_read(book, path):
    res = book.client.get(_with(path, "p-theirs"))
    assert (res.status_code, res.json()["detail"]) == (403, "Profile not in your workspace")
    assert "shadow-theirs" not in res.text


def test_another_workspaces_profile_id_is_refused_on_the_writes_too(book):
    for path in ("/api/portfolio/cas-snapshot/2026-09-30/activate", "/api/portfolio/cas-transactions/backfill"):
        res = book.client.post(_with(path, "p-theirs"))
        assert res.status_code == 403, path
    assert book.db.writes == []          # nothing was mounted or backfilled (the tripwires would also have fired)


def test_an_unknown_profile_id_is_refused_rather_than_read_as_the_caller(book):
    res = book.client.get(_with("/api/portfolio/cas-snapshots", "p-nobody"))
    assert (res.status_code, res.json()["detail"]) == (404, "Profile not found")


def test_a_client_session_cannot_reach_another_advisors_client(book):
    book.caller = {"user_id": "shadow-mine", "_session_user_id": "shadow-mine"}       # not a workspace owner at all
    assert book.client.get(_with("/api/portfolio/cas-snapshots", "p-theirs")).status_code == 403
    assert book.client.get(_with("/api/portfolio/cas-snapshots", "p-mine")).status_code == 403
