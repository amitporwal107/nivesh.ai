"""Desk audit wave 1 (2026-10-28), B1: the two backend faults the audit of the live desk found.

  B1-OWN  GET /api/markets/ownership/reaction was 502 on every Smart Money load. The data platform's
          /v1/desk/ownership/reaction answered 500 (staging DaaS log, 2026-10-27 23:01-23:17 UTC):
          `asyncpg.exceptions.IndeterminateDatatypeError: could not determine data type of parameter $2`
          at routers/ownership.py `conn.fetchrow(_COVERAGE_SQL, cur_end, prev_end, UNIVERSE)`.
          _COVERAGE_SQL used $1 and $3 but never $2, and Postgres cannot type a parameter the text
          never uses. The fake connection below enforces the same rule Postgres does, so the old
          call fails here exactly as it failed on staging.
  B1-SC   GET /api/desk/idea-scorecard opened three docs/ files that the backend image does not ship,
          and the Sources table printed "not readable here (FileNotFoundError)". The documents are now
          references the route lists and never opens; a wrongly shaped result.json is 503, never 500.

No database and no network: MOCK — not real data. The fake pool returns canned rows (shaped like the
real ones in test_ownership_reaction.py); what is under test is the SQL/argument contract and the
route's handling, not the figures.
"""
from __future__ import annotations

import asyncio
import builtins
import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nidp.services.daas_api.routers import ownership as own  # noqa: E402
from services import idea_scorecard as scorecard  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


# ── B1-OWN: every SQL parameter passed is one the text uses ──────────────────

def _placeholders(sql: str) -> List[int]:
    return sorted({int(n) for n in re.findall(r"\$(\d+)", sql)})


class StrictConn:
    """MOCK — not real data. A connection that refuses what Postgres refuses: an argument whose $n the
    text never mentions (IndeterminateDatatypeError), or a $n with no argument."""

    def __init__(self) -> None:
        self.calls: List[str] = []

    def _check(self, sql: str, args: tuple) -> None:
        used = _placeholders(sql)
        expected = list(range(1, len(args) + 1))
        if used != expected:
            missing = sorted(set(expected) - set(used))
            raise RuntimeError(f"could not determine data type of parameter ${missing[0]}" if missing
                               else f"bind message supplies {len(args)} parameters, the text uses {used}")

    def _name(self, sql: str) -> str:
        for name in ("_QUARTERS_SQL", "_CUTS_SQL", "_COVERAGE_SQL", "_ROWS_SQL", "_SESSIONS_SQL"):
            if sql == getattr(own, name):
                return name
        return "other"

    async def fetch(self, sql: str, *args):
        self._check(sql, args)
        name = self._name(sql)
        self.calls.append(name)
        if name == "_QUARTERS_SQL":
            return [{"period_end": date(2026, 9, 30)}, {"period_end": date(2026, 6, 30)}]
        if name == "_ROWS_SQL":
            return [_row("AAA", 1.2, 0.4, 9.0, 1.4), _row("BBB", -1.1, -0.3, -16.0, 1.1), _row("CCC", 0.1, 0.0, 1.0, 0.7)]
        return []

    async def fetchrow(self, sql: str, *args):
        self._check(sql, args)
        name = self._name(sql)
        self.calls.append(name)
        if name == "_CUTS_SQL":
            return {"ref_n": 488, "ret_p20": -13.54, "ret_p80": 7.66, "ret_p50": -2.1, "vol_p50": 0.757, "deliv_p50": 0.8}
        if name == "_COVERAGE_SQL":
            return {"universe_total": 500, "with_current_quarter": 444, "trend_renderable": 176, "single_quarter_only": 267}
        return None

    async def fetchval(self, sql: str, *args):
        self._check(sql, args)
        self.calls.append(self._name(sql))
        return 64 if sql == own._SESSIONS_SQL else False


def _row(symbol: str, fii: float, dii: float, ret: float, vol: float) -> Dict[str, Any]:
    return {
        "symbol": symbol, "industry": "Capital Goods", "delta_basis": "same_source", "delta_source": "screener_in",
        "fii_delta_pp": fii, "dii_delta_pp": dii, "inst_delta_pp": round(fii + dii, 2),
        "fii_pct_now": 20.0, "dii_pct_now": 15.0, "delta_alt_pp": None, "fii_spread_pp": 0.1,
        "mf_pct": None, "bank_fi_pct": None, "split_source": None,
        "ret_pct": ret, "vol_ratio": vol, "deliv_shift_pp": 0.5, "sessions_cur": 64, "sessions_prev": 63,
        "ret_percentile": 50.0, "dist_52w_high_pct": -8.0, "dist_52w_low_pct": 30.0,
        "filed_at": None, "quarters_available": 2,
    }


class _Pool:
    def __init__(self, conn: StrictConn) -> None:
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False
        return _Ctx()


def test_b1_own_1_every_sql_numbers_its_parameters_from_one_without_gaps():
    """A gap ($1, $3) is the staging fault: the unused $2 has no type."""
    for name in ("_CUTS_SQL", "_COVERAGE_SQL", "_ROWS_SQL", "_SESSIONS_SQL"):
        used = _placeholders(getattr(own, name))
        assert used == list(range(1, len(used) + 1)), f"{name} uses {used}"
    assert _placeholders(own._COVERAGE_SQL) == [1, 2]


def test_b1_own_2_the_reaction_route_runs_against_a_connection_that_enforces_postgres_typing(monkeypatch):
    conn = StrictConn()

    async def get_pool():
        return _Pool(conn)

    monkeypatch.setattr(own, "get_pool", get_pool)
    body = asyncio.run(own.ownership_reaction(view="reduced", reaction="any", status="any", basis="any",
                                              sort="inst_delta", limit=100))
    assert "_COVERAGE_SQL" in conn.calls and "_ROWS_SQL" in conn.calls
    assert body["as_of"] == "2026-09-30" and body["previous_period"] == "2026-06-30"
    # The coverage figures reach the answer (the query that used to fail now feeds it).
    assert body["coverage"]["universe_total"] == 500 and body["coverage"]["with_current_quarter"] == 444
    assert body["coverage"]["trend_renderable"] == 176 and body["coverage"]["single_quarter_only"] == 267
    assert isinstance(body["rows"], list)
    assert body["counts"]["cohort"] == 3 and body["counts"]["status_reconciles"] is True


def test_b1_own_3_the_strict_connection_does_catch_the_old_call():
    """Guard on the guard: the old argument list against the new text is refused the way staging refused it."""
    conn = StrictConn()
    with pytest.raises(RuntimeError, match="could not determine data type of parameter"):
        asyncio.run(conn.fetchrow(own._COVERAGE_SQL, date(2026, 9, 30), date(2026, 6, 30), own.UNIVERSE))
    old_text = own._COVERAGE_SQL.replace("$2", "$3")
    with pytest.raises(RuntimeError, match=r"parameter \$2"):
        asyncio.run(conn.fetchrow(old_text, date(2026, 9, 30), date(2026, 6, 30), own.UNIVERSE))


# ── B1-SC: the scorecard lists its documents and never opens them ─────────────

def _study_root(tmp_path: Path, mutate=None) -> Path:
    """Only research/…/result.json, as on staging: no docs/ directory at all."""
    dest = tmp_path / scorecard.RESULT_PATH
    dest.parent.mkdir(parents=True)
    data = json.loads((REPO / scorecard.RESULT_PATH).read_text())
    if mutate:
        mutate(data)
    dest.write_text(json.dumps(data))
    return tmp_path


def test_b1_sc_1_documents_are_references_and_are_never_opened(tmp_path, monkeypatch):
    root = _study_root(tmp_path)
    opened: List[str] = []
    real_read_bytes, real_open = Path.read_bytes, builtins.open

    def spy_read_bytes(self):
        opened.append(str(self))
        return real_read_bytes(self)

    def spy_open(file, *a, **kw):
        opened.append(str(file))
        return real_open(file, *a, **kw)

    monkeypatch.setattr(Path, "read_bytes", spy_read_bytes)
    monkeypatch.setattr(builtins, "open", spy_open)
    body = scorecard.load(root)
    monkeypatch.undo()

    assert not any("/docs/" in p or p.endswith(".md") for p in opened), opened
    srcs = body["sources"]
    assert srcs[0] == {**srcs[0], "path": scorecard.RESULT_PATH, "kind": "data", "present": True}
    assert len(srcs[0]["sha256"]) == 64
    refs = srcs[1:]
    assert [(s["path"], s["role"]) for s in refs] == list(scorecard.DOCUMENTS)
    for s in refs:
        assert s["kind"] == "reference" and s["present"] is None and s["sha256"] is None and s["bytes"] is None
    text = json.dumps(srcs)
    assert "FileNotFoundError" not in text and "not readable" not in text


def test_b1_sc_2_the_answer_is_the_same_whether_or_not_the_documents_are_on_disk(tmp_path):
    without = scorecard.load(_study_root(tmp_path / "a"))
    root = _study_root(tmp_path / "b")
    for rel, _ in scorecard.DOCUMENTS:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("# a document the route must not read\n")
    with_docs = scorecard.load(root)
    assert without == with_docs


@pytest.fixture
def client(monkeypatch):
    from routes import desk_trading as desk_route

    async def current_user(request: Request):  # MOCK — not real data: a signed-in user
        return {"id": "u1"}

    monkeypatch.setattr(desk_route, "get_current_user", current_user)
    app = FastAPI()
    app.include_router(desk_route.router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("mutate, why", [
    (None, "as committed"),
    (lambda d: d["splits"]["discovery"]["arms"]["B0"].__setitem__("ic", [1, 2]), "ic is a list"),
    (lambda d: d["splits"].__setitem__("test", ["not", "an", "object"]), "a split is a list"),
    (lambda d: d.__setitem__("decision", "keep B0"), "decision is a string"),
])
def test_b1_sc_3_the_route_never_answers_500(client, tmp_path, monkeypatch, mutate, why):
    monkeypatch.setattr(scorecard, "REPO_ROOT", _study_root(tmp_path, mutate))
    r = client.get("/api/desk/idea-scorecard")
    assert r.status_code in (200, 503), (why, r.status_code, r.text[:200])
    if mutate is None:
        assert r.status_code == 200 and [s["kind"] for s in r.json()["sources"]] == ["data"] + ["reference"] * 3
    else:
        assert r.status_code == 503 and r.json()["detail"]["code"] == "scorecard_unavailable", why
