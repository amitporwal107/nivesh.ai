"""Results signal in the AI scanner — docs/EARNINGS_SURPRISE_TRACKER.md §4d (services/results_week/signal.py) and its
read-time use in GET /api/positional/picks and /watchlist (routes/positional.py).

Thresholds at their edges, loss → profit, the decay counted from the first reaction session (after-close filings react
the next session), the figures-pending path, the weak path, the red-flag veto, the routes keeping their order consistent
with the adjusted final_score, the adjustment applied before the limit, and a failed source meaning no adjustment and a
gap. No network and no database. Every fixture is MOCK — not real data.
"""
from __future__ import annotations

import asyncio
import copy
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.positional as route
from services.positional_engine import setup_rules
from services.results_week import signal as rs

SESSIONS = [date(2026, 9, 1) + timedelta(days=i) for i in range(120) if (date(2026, 9, 1) + timedelta(days=i)).weekday() < 5]


def run(coro):
    return asyncio.run(coro)


def utc(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean():
    rs.clear_cache()
    yield
    rs.clear_cache()


def facts(**kw) -> Dict[str, Any]:
    f = {"quarter": date(2026, 9, 30), "pat_yoy": None, "loss_to_profit": False, "revenue_yoy": None, "margin_bps": None,
         "red_flags": [], "above": [], "below": []}
    f.update(kw)
    return f


# ── the figures rule ─────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kw,want", [
    ({"pat_yoy": 20.0, "revenue_yoy": 10.0}, "strong"),                  # both exactly at their thresholds
    ({"pat_yoy": 19.99, "revenue_yoy": 10.0}, None),
    ({"pat_yoy": 20.0, "revenue_yoy": 9.99}, None),
    ({"revenue_yoy": 10.0, "margin_bps": 50.0}, "strong"),               # +50 bps counts
    ({"revenue_yoy": 10.0, "margin_bps": 49.9}, None),
    ({"pat_yoy": 25.0, "above": ["revenue"]}, "strong"),                 # a rated "above" is one of the two
    ({"loss_to_profit": True, "revenue_yoy": 12.0}, "strong"),           # loss → profit meets the PAT condition
    ({"pat_yoy": -10.0, "revenue_yoy": 4.9}, "weak"),
    ({"pat_yoy": -10.0, "revenue_yoy": 5.0}, None),
    ({"pat_yoy": 40.0, "revenue_yoy": 30.0, "below": ["revenue"]}, None),    # a rated below with PAT strongly up: mixed
    ({"pat_yoy": 247.0, "below": ["revenue"]}, None),                         # staging 27 Oct GAEL-like: not "weak"
    ({"pat_yoy": 5.0, "below": ["pat"]}, "weak"),                             # a rated below without a strong PAT rise
    ({"pat_yoy": -48.0, "revenue_yoy": 15.0, "margin_bps": 100.0}, None),    # staging 27 Oct MGEL-like: profit fell
    ({"pat_yoy": -1.0, "revenue_yoy": 12.0, "margin_bps": 60.0}, None),      # any profit fall blocks "strong"
])
def test_figures_rule_at_its_edges(kw, want):
    assert rs.classify_figures(facts(**kw))[0] == want


def test_a_red_flag_vetoes_strong():
    flag = [{"code": "other_income", "text": "other income is 31 % of PBT (over 30 %)"}]
    assert rs.classify_figures(facts(pat_yoy=40.0, revenue_yoy=30.0, margin_bps=200.0, red_flags=flag)) == (None, [])
    assert rs.classify_figures(facts(pat_yoy=40.0, revenue_yoy=30.0))[0] == "strong"


def test_filing_analysis_rule():
    assert rs.classify_filing({"net_band": "moderately_positive", "confidence_score": 75}) == "strong"
    assert rs.classify_filing({"net_band": "extremely_positive", "confidence_score": 74.9}) is None
    assert rs.classify_filing({"net_band": "slightly_positive", "confidence_score": 90}) is None
    assert rs.classify_filing({"net_band": "moderately_negative", "confidence_score": 80}) == "weak"
    assert rs.classify_filing(None) is None


# ── the decay, from the first reaction session ───────────────────────────────────────────────────────────────────

def test_decay_from_full_to_nothing_over_five_sessions():
    assert [round(rs.decayed(10.0, n), 6) for n in range(6)] == [10.0, 8.0, 6.0, 4.0, 2.0, 0.0]
    assert rs.decayed(-5.0, 1) == -4.0


def test_after_close_filing_counts_from_the_next_session():
    filed = utc(2026, 10, 26, 15, 29)                                    # 20:59 IST Mon 26 Oct, after the close
    assert rs.sessions_since(filed, SESSIONS, date(2026, 10, 26)) == 0   # its session (27 Oct) is still ahead
    assert rs.sessions_since(filed, SESSIONS, date(2026, 10, 27)) == 0   # full points on 27 Oct
    assert rs.sessions_since(filed, SESSIONS, date(2026, 10, 28)) == 1   # 8 on 28 Oct
    assert rs.sessions_since(filed, SESSIONS, date(2026, 11, 3)) == 5    # nothing from the 5th session after 27 Oct
    before_close = utc(2026, 10, 26, 8, 30)                              # 14:00 IST: reacts on 26 Oct itself
    assert rs.sessions_since(before_close, SESSIONS, date(2026, 10, 27)) == 1


# ── one meeting end to end (signal_for) ──────────────────────────────────────────────────────────────────────────

def fin(pat, pat4, rev, rev4, ebitda=None, ebitda4=None, oi=1.0, pbt=None):
    ends = ["2026-09-30", "2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"]
    rows = [{"period_end": e, "pat_cr": pat, "revenue_from_ops_cr": rev, "ebitda_cr": ebitda or rev * 0.2,
             "other_income_cr": oi, "pbt_cr": pbt or max(pat, 1.0) * 1.3} for e in ends]
    rows[4].update(pat_cr=pat4, revenue_from_ops_cr=rev4, ebitda_cr=ebitda4 or rev4 * 0.2)
    return rows


def meeting(status="declared", filed_state="figures", at="2026-10-26T15:29:10+00:00", day="2026-10-26"):
    m = [{"key": "revenue", "expected": None, "reliable": False, "filed": {"value": 1, "broadcast_at": at} if filed_state == "figures" else None},
         {"key": "pat", "expected": None, "reliable": False, "filed": {"value": 1, "broadcast_at": at} if filed_state == "figures" else None}]
    return {"symbol": "MOCKCO", "event_date": day, "status": status, "filed_state": filed_state,
            "period_label": "Q2 FY27 (Jul–Sep 2026)", "metrics": m, "filing": None}


def test_strong_figures_full_on_the_first_reaction_session_then_decaying():
    rows = fin(140.0, 100.0, 1173.0, 1000.0, ebitda=316.0, ebitda4=250.0)      # PAT +40 %, revenue +17.3 %, margin +194 bps
    s = rs.signal_for(meeting(), rows, [], SESSIONS, utc(2026, 10, 27, 10, 0))
    assert s["strength"] == "strong" and s["points"] == 10.0 and s["basis"] == "figures" and s["sessions_since"] == 0
    assert s["reasons"][0] == "Q2 FY27 PAT +40.0 % YoY, revenue +17.3 %, EBITDA margin +194 bps (filed 26 Oct)"
    assert set(s) == {"strength", "points", "basis", "reasons", "filed_at", "sessions_since"}
    assert rs.signal_for(meeting(), rows, [], SESSIONS, utc(2026, 10, 28, 10, 0))["points"] == 8.0
    assert rs.signal_for(meeting(), rows, [], SESSIONS, utc(2026, 11, 3, 10, 0)) is None


def test_not_broadcast_yet_is_nothing_and_loss_to_profit_reads_so():
    rows = fin(5.0, -3.0, 1150.0, 1000.0)
    assert rs.signal_for(meeting(), rows, [], SESSIONS, utc(2026, 10, 26, 12, 0)) is None     # before its 15:29 UTC broadcast
    s = rs.signal_for(meeting(), rows, [], SESSIONS, utc(2026, 10, 27, 10, 0))
    assert s["strength"] == "strong" and "PAT turned to a profit from a loss a year earlier" in s["reasons"][0]


def test_figures_pending_uses_the_filing_analysis_at_half_weight():
    doc = {"symbol": "MOCKCO", "mode": "single_full", "event_type": "RESULTS", "event_ts": datetime(2026, 10, 26, 11, 0),
           "analyzed_at": datetime(2026, 10, 26, 12, 0), "net_band": "moderately_positive", "confidence_score": 82}
    s = rs.signal_for(meeting(filed_state="pending"), None, [doc], SESSIONS, utc(2026, 10, 27, 10, 0))
    assert s["basis"] == "filing_analysis" and s["points"] == 5.0 and s["sessions_since"] == 0
    assert s["reasons"] == ["Filing analysis: moderately positive, confidence 82 % (figures not filed yet)"]
    neg = dict(doc, net_band="moderately_negative")
    w = rs.signal_for(meeting(filed_state="pending"), None, [neg], SESSIONS, utc(2026, 10, 28, 10, 0))
    assert w["strength"] == "weak" and w["points"] == -4.0
    assert rs.signal_for(meeting(status="upcoming", filed_state=None), None, [doc], SESSIONS, utc(2026, 10, 27, 10, 0)) is None


def test_weak_figures():
    rows = fin(80.0, 100.0, 1020.0, 1000.0)                                  # PAT −20 %, revenue +2 %
    s = rs.signal_for(meeting(), rows, [], SESSIONS, utc(2026, 10, 27, 10, 0))
    assert s["strength"] == "weak" and s["points"] == -10.0


def test_apply_adjusts_final_score_and_keeps_the_base():
    rows = [{"nse_symbol": "AAA", "final_score": 0.50}, {"nse_symbol": "BBB", "final_score": 0.95}, {"nse_symbol": "CCC", "final_score": 0.04}]
    sig = {"AAA": {"points": 10.0}, "BBB": {"points": 10.0}, "CCC": {"points": -10.0}}
    rs.apply(rows, sig)
    assert [(r["base_final_score"], r["final_score"]) for r in rows] == [(0.5, 0.6), (0.95, 1.0), (0.04, 0.0)]


# ── a failed source: no adjustment, a gap, never a crash ─────────────────────────────────────────────────────────

def test_a_failed_computation_means_no_adjustment_and_a_gap(monkeypatch):
    async def boom(now, db=None):
        raise RuntimeError("DaaS down")
    monkeypatch.setattr(rs, "compute", boom)
    sigs, gap = run(rs.current())
    assert sigs == {} and gap.startswith("results signal not applied: RuntimeError")
    monkeypatch.setattr(rs, "compute", lambda now, db=None: (_ for _ in ()).throw(AssertionError("not called again")))
    assert run(rs.current()) == (sigs, gap)                                 # the failure is cached for a minute


# ── the scanner routes: adjusted before sort, min_score and limit ────────────────────────────────────────────────

class _Conn:
    def __init__(self, handler):
        self.handler = handler

    async def fetch(self, sql, *args):
        return self.handler(sql, args)

    async def fetchrow(self, sql, *args):
        r = self.handler(sql, args)
        return r[0] if r else None


class _Acq:
    def __init__(self, c):
        self.c = c

    async def __aenter__(self):
        return self.c

    async def __aexit__(self, *e):
        return False


class _Pool:
    def __init__(self, h):
        self.c = _Conn(h)

    def acquire(self):
        return _Acq(self.c)


SIG = {"strength": "strong", "points": 10.0, "basis": "figures", "reasons": ["MOCK"], "filed_at": "2026-10-26T15:29:10+00:00", "sessions_since": 0}


def scanner(monkeypatch, handler, signals, gap=None):
    async def get_pool():
        return _Pool(handler)

    async def user(request: Request):
        return {"user_id": "u1"}

    async def current(*a, **k):
        return copy.deepcopy(signals), gap

    async def no_basis(d):
        return None

    monkeypatch.setattr(route.pg_client, "get_pool", get_pool)
    monkeypatch.setattr(route, "get_current_user", user)
    monkeypatch.setattr(route.results_signal, "current", current)
    monkeypatch.setattr(route, "_scan_basis", no_basis)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app)


def picks_handler(rows: List[Dict[str, Any]], seen: List[tuple]):
    def h(sql, args):
        seen.append((sql, args))
        if "MAX(signal_date)" in sql:
            return [{"d": date(2026, 10, 27)}]
        if "FROM positional_signals ps" in sql:
            if "ANY(" in sql:
                want = set(args[-2])
                return [dict(r) for r in rows if r["nse_symbol"] in want][: args[-1]]
            keep = sorted((r for r in rows if r["final_score"] >= args[1]), key=lambda r: -r["final_score"])
            return [dict(r) for r in keep][: args[-1]]
        if "FROM stock_ohlcv" in sql:
            return []
        raise AssertionError(sql)
    return h


def pick(sym, score, rr=2.0):
    return {"nse_symbol": sym, "signal_date": date(2026, 10, 27), "final_score": score, "risk_reward": rr, "stage": "BREAKOUT",
            "engine_version": "positional.v1.1", "pre_breakout": None, "features_raw": None, "price_basis": "warehouse_adjusted"}


def test_picks_a_boosted_stock_at_base_rank_31_enters_the_top_30(monkeypatch):
    rows = [pick(f"S{i:02d}", round(0.95 - 0.01 * i, 2)) for i in range(31)]     # S30 is 31st at 0.65
    seen: List[tuple] = []
    c = scanner(monkeypatch, picks_handler(rows, seen), {"S30": SIG})
    d = c.get("/api/positional/picks?limit=30&min_score=0.55").json()
    syms = [p["nse_symbol"] for p in d["picks"]]
    assert len(syms) == 30 and "S30" in syms and "S29" not in syms                # 0.65 + 0.10 = 0.75 > S29's 0.66
    s30 = next(p for p in d["picks"] if p["nse_symbol"] == "S30")
    assert s30["final_score"] == 0.75 and s30["base_final_score"] == 0.65 and s30["results_signal"]["points"] == 10.0
    scores = [p["final_score"] for p in d["picks"]]
    assert scores == sorted(scores, reverse=True)                                  # the order follows the adjusted score
    assert d["results_signal"]["applied"] == 1 and d["results_signal"]["tested"] is False
    assert "this adjustment has not been tested yet" in d["results_signal"]["rule"]
    assert any("LIMIT" in q and a[-1] == 31 for q, a in seen if "positional_signals" in q and "ANY(" not in q)


def test_picks_a_stock_below_min_score_enters_when_boosted_and_a_weak_one_leaves(monkeypatch):
    rows = [pick("AAA", 0.70), pick("BBB", 0.50), pick("CCC", 0.60)]
    weak = dict(SIG, strength="weak", points=-10.0)
    c = scanner(monkeypatch, picks_handler(rows, []), {"BBB": SIG, "CCC": weak})
    d = c.get("/api/positional/picks?min_score=0.55").json()
    assert [(p["nse_symbol"], p["final_score"]) for p in d["picks"]] == [("AAA", 0.7), ("BBB", 0.6)]


def test_picks_without_a_signal_keep_their_order_and_say_why(monkeypatch):
    rows = [pick("AAA", 0.70), pick("BBB", 0.80)]
    c = scanner(monkeypatch, picks_handler(rows, []), {}, gap="results signal not applied: RuntimeError: DaaS down")
    d = c.get("/api/positional/picks").json()
    assert [p["nse_symbol"] for p in d["picks"]] == ["BBB", "AAA"]
    assert all(p["results_signal"] is None and p["base_final_score"] == p["final_score"] for p in d["picks"])
    assert d["results_signal"]["gap"].startswith("results signal not applied")


def test_watchlist_candidates_are_adjusted_before_the_cut(monkeypatch):
    from tests.test_positional_scan_universe import _bars, _candidate
    monkeypatch.setitem(setup_rules.WATCHLIST["candidates"], "top_by_score", 2)
    cands = [_candidate(nse_symbol=s, final_score=f) for s, f in (("AAA", 0.90), ("CCC", 0.80), ("DDD", 0.78), ("BBB", 0.75))]
    seen: List[tuple] = []

    def h(sql, args):
        seen.append((sql, args))
        if "MAX(as_of_date)" in sql:
            return [{"d": date(2026, 10, 13)}]
        if "FROM stock_technical_features stf" in sql:
            if "ANY($5" in sql:
                return [dict(c) for c in cands if c["nse_symbol"] in set(args[4])][: args[3]]
            return [dict(c) for c in cands][: args[3]]
        if "FROM stock_ohlcv" in sql:
            out = []
            for sym in args[0]:
                out += [dict(b, nse_symbol=sym) for b in _bars()]
            return out
        raise AssertionError(sql)

    c = scanner(monkeypatch, h, {"BBB": SIG})
    d = c.get("/api/positional/watchlist").json()
    rows = [it for v in d["buckets"].values() for it in v]
    assert sorted(it["nse_symbol"] for it in rows) == ["AAA", "BBB"]              # BBB (base rank 4) enters; CCC, DDD are cut
    bbb = next(it for it in rows if it["nse_symbol"] == "BBB")
    assert bbb["final_score"] == 0.85 and bbb["base_final_score"] == 0.75 and bbb["results_signal"]["strength"] == "strong"
    assert any("ANY($5" in q for q, _ in seen)                                     # the signalled stock was read by name
    assert d["results_signal"]["applied"] == 1
