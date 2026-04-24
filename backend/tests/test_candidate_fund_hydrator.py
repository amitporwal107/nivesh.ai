"""Unit tests for the candidate-fund hydrator.

Uses a fake in-memory Mongo-like db to validate filters (AUM, track-record,
same sub_category) and scale conversions (% → decimal, 0-10 → 0-100).
"""
import asyncio
import pytest

from services import candidate_fund_hydrator as cfh


# ── Fake Motor-style collection/db ───────────────────────────────────────
class _Cursor:
    def __init__(self, rows):
        self._rows = list(rows)

    async def to_list(self, length=None):
        if length is None:
            return list(self._rows)
        return list(self._rows[:length])


class _Col:
    def __init__(self, rows):
        self._rows = list(rows)

    def _match(self, doc, query):
        for k, v in query.items():
            if isinstance(v, dict) and "$in" in v:
                if doc.get(k) not in v["$in"]:
                    return False
            elif isinstance(v, dict) and "$regex" in v:
                import re
                if not re.match(v["$regex"], str(doc.get(k) or ""), re.IGNORECASE):
                    return False
            else:
                if doc.get(k) != v:
                    return False
        return True

    def find(self, query, projection=None):
        return _Cursor([d for d in self._rows if self._match(d, query)])

    async def find_one(self, query, projection=None):
        for d in self._rows:
            if self._match(d, query):
                return dict(d)
        return None


class _DB:
    def __init__(self, metas, perfs, masters):
        self.pg_mirror_mutual_fund_metadata = _Col(metas)
        self.pg_mirror_mutual_fund_performance_ratios = _Col(perfs)
        self.pg_mirror_instrument_master = _Col(masters)


def _meta(iid, name_slug="fund", sub="Flexi Cap", aum=5000, age=5,
          exp_dir=1.0, exp_reg=1.8, dd=20.0, cons=5.0, category="Equity"):
    return {
        "instrument_id": iid,
        "groww_slug": name_slug,
        "aum_cr": aum,
        "expense_ratio": exp_reg,
        "expense_ratio_direct": exp_dir,
        "expense_ratio_regular": exp_reg,
        "max_drawdown_pct": dd,
        "consistency_score": cons,
        "fund_age_years": age,
        "sub_category": sub,
        "category": category,
    }


def _perf(iid, ret_5y=15.0, ret_3y=12.0, ret_1y=8.0):
    return {
        "instrument_id": iid,
        "ret_5y": ret_5y,
        "ret_3y": ret_3y,
        "ret_1y": ret_1y,
    }


def _master(iid, name="Test Fund"):
    return {"instrument_id": iid, "instrument_name": name}


# ── Tests ────────────────────────────────────────────────────────────────
def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def setup_function(_):
    cfh._invalidate_cache()


def test_filters_aum_floor():
    db = _DB(
        metas=[
            _meta("a", aum=1000),   # ok
            _meta("b", aum=400),    # dropped
        ],
        perfs=[_perf("a"), _perf("b")],
        masters=[_master("a", "Fund A"), _master("b", "Fund B")],
    )
    peers = _run(cfh.fetch_candidates_for_category(db, "Flexi Cap"))
    assert len(peers) == 1
    assert peers[0].name == "Fund A"
    assert peers[0].aum_cr == 1000


def test_filters_track_record_floor():
    db = _DB(
        metas=[
            _meta("a", age=5),
            _meta("b", age=2),   # <3yr → dropped
        ],
        perfs=[_perf("a"), _perf("b")],
        masters=[_master("a"), _master("b")],
    )
    peers = _run(cfh.fetch_candidates_for_category(db, "Flexi Cap"))
    assert len(peers) == 1


def test_filters_same_subcategory_only():
    db = _DB(
        metas=[
            _meta("a", sub="Flexi Cap"),
            _meta("b", sub="Small Cap"),
        ],
        perfs=[_perf("a"), _perf("b")],
        masters=[_master("a"), _master("b")],
    )
    peers = _run(cfh.fetch_candidates_for_category(db, "Flexi Cap"))
    assert len(peers) == 1
    assert peers[0].category == "Flexi Cap"


def test_scale_conversions():
    """Percentage units → decimal; 0-10 consistency → 0-100."""
    db = _DB(
        metas=[_meta("a", exp_dir=1.05, exp_reg=1.67, dd=20.83, cons=4.0, age=5)],
        perfs=[_perf("a", ret_5y=14.19)],
        masters=[_master("a")],
    )
    peers = _run(cfh.fetch_candidates_for_category(db, "Flexi Cap"))
    assert len(peers) == 1
    c = peers[0]
    assert c.expense == pytest.approx(0.0105, abs=1e-6)
    assert c.return_5y == pytest.approx(0.1419, abs=1e-6)
    assert c.drawdown == pytest.approx(0.2083, abs=1e-6)
    assert c.consistency == pytest.approx(40.0, abs=1e-3)


def test_ret_fallback_chain():
    """When ret_5y is missing, hydrator falls back to ret_3y then ret_1y."""
    db = _DB(
        metas=[
            _meta("a"),
            _meta("b"),
            _meta("c"),
        ],
        perfs=[
            _perf("a", ret_5y=15.0),
            _perf("b", ret_5y=None, ret_3y=12.0),
            {"instrument_id": "c", "ret_5y": None, "ret_3y": None, "ret_1y": 8.0},
        ],
        masters=[_master("a", "A"), _master("b", "B"), _master("c", "C")],
    )
    peers = _run(cfh.fetch_candidates_for_category(db, "Flexi Cap"))
    by_name = {p.name: p for p in peers}
    assert by_name["A"].return_5y == pytest.approx(0.15)
    assert by_name["B"].return_5y == pytest.approx(0.12)
    assert by_name["C"].return_5y == pytest.approx(0.08)


def test_drop_when_no_return_available():
    """A fund with zero return data is dropped (can't score)."""
    db = _DB(
        metas=[_meta("a"), _meta("b")],
        perfs=[
            _perf("a", ret_5y=15.0),
            {"instrument_id": "b"},    # no returns at all
        ],
        masters=[_master("a", "A"), _master("b", "B")],
    )
    peers = _run(cfh.fetch_candidates_for_category(db, "Flexi Cap"))
    assert [p.name for p in peers] == ["A"]


def test_exclude_instrument_id():
    """The current holding's own iid shouldn't come back as its peer."""
    db = _DB(
        metas=[_meta("a"), _meta("b")],
        perfs=[_perf("a"), _perf("b")],
        masters=[_master("a", "A"), _master("b", "B")],
    )
    peers = _run(cfh.fetch_candidates_for_category(
        db, "Flexi Cap", exclude_instrument_id="a"
    ))
    assert [p.name for p in peers] == ["B"]


def test_prefer_regular_plan_expense():
    """`prefer_direct=False` uses `expense_ratio_regular`."""
    db = _DB(
        metas=[_meta("a", exp_dir=0.7, exp_reg=1.8)],
        perfs=[_perf("a")],
        masters=[_master("a")],
    )
    peers_d = _run(cfh.fetch_candidates_for_category(db, "Flexi Cap", prefer_direct=True))
    cfh._invalidate_cache()
    peers_r = _run(cfh.fetch_candidates_for_category(db, "Flexi Cap", prefer_direct=False))
    assert peers_d[0].expense == pytest.approx(0.007)
    assert peers_r[0].expense == pytest.approx(0.018)


def test_none_values_do_not_crash():
    """Consistency / drawdown / expense None values should degrade gracefully."""
    db = _DB(
        metas=[{
            "instrument_id": "a",
            "groww_slug": "fund-a",
            "aum_cr": 1000,
            "sub_category": "Flexi Cap",
            "fund_age_years": 5,
            "expense_ratio_direct": 1.0,   # usable
            "expense_ratio_regular": None,
            "max_drawdown_pct": None,
            "consistency_score": None,
        }],
        perfs=[_perf("a")],
        masters=[_master("a")],
    )
    peers = _run(cfh.fetch_candidates_for_category(db, "Flexi Cap"))
    assert len(peers) == 1
    assert peers[0].drawdown == 0.0
    assert peers[0].consistency == 0.0


def test_cache_hit_avoids_second_query():
    """Same sub_category + plan preference within TTL should reuse results."""
    call_count = {"n": 0}

    class _CountingCol(_Col):
        def find(self, query, projection=None):
            call_count["n"] += 1
            return super().find(query, projection)

    db = _DB([_meta("a")], [_perf("a")], [_master("a")])
    db.pg_mirror_mutual_fund_metadata = _CountingCol(
        db.pg_mirror_mutual_fund_metadata._rows
    )
    _run(cfh.fetch_candidates_for_category(db, "Flexi Cap"))
    _run(cfh.fetch_candidates_for_category(db, "Flexi Cap"))
    assert call_count["n"] == 1   # second call served from cache


def test_fetch_current_fund_context_by_iid():
    db = _DB(
        metas=[_meta("a", exp_dir=1.05, exp_reg=1.67, dd=20.83, cons=4.0)],
        perfs=[_perf("a", ret_5y=14.19)],
        masters=[_master("a")],
    )
    ctx = _run(cfh.fetch_current_fund_context(db, instrument_id="a"))
    assert ctx["sub_category"] == "Flexi Cap"
    assert ctx["expense_current"] == pytest.approx(0.0167)
    assert ctx["expense_direct"] == pytest.approx(0.0105)
    assert ctx["current_return_5y"] == pytest.approx(0.1419)
    assert ctx["current_drawdown"] == pytest.approx(0.2083)
    assert ctx["current_consistency"] == pytest.approx(40.0)


def test_fetch_current_fund_context_returns_none_when_missing():
    db = _DB([], [], [])
    assert _run(cfh.fetch_current_fund_context(db, instrument_id="nope")) is None


def test_end_to_end_with_switch_engine():
    """Hydrated candidates flow into the decision engine and produce
    a STRONG_SWITCH_DIRECT or STRONG_SWITCH on a clearly inferior holding.
    """
    from services import switch_decision_engine as sde

    db = _DB(
        metas=[
            # Current (weak, Regular): high expense, low returns
            _meta("cur", "sundaram-value", sub="Value Oriented",
                  aum=1200, age=13, exp_dir=1.71, exp_reg=1.71,
                  dd=15.9, cons=3.6),
            # Peer 1 (strong): low expense, high returns
            _meta("p1", "sbi-contra-direct", sub="Value Oriented",
                  aum=43000, age=13, exp_dir=0.75, exp_reg=1.50,
                  dd=15.8, cons=4.0),
            _meta("p2", "icici-value-growth", sub="Value Oriented",
                  aum=55000, age=22, exp_dir=0.80, exp_reg=1.51,
                  dd=14.2, cons=4.0),
        ],
        perfs=[
            _perf("cur", ret_5y=13.5),
            _perf("p1", ret_5y=21.19),
            _perf("p2", ret_5y=19.45),
        ],
        masters=[
            _master("cur", "Sundaram Value Fund Regular Growth"),
            _master("p1", "SBI Contra Direct Plan Growth"),
            _master("p2", "ICICI Prudential Value Fund Growth"),
        ],
    )
    ctx = _run(cfh.fetch_current_fund_context(db, instrument_id="cur"))
    peers = _run(cfh.fetch_candidates_for_category(
        db, ctx["sub_category"], exclude_instrument_id="cur"
    ))
    assert len(peers) == 2

    inp = sde.DecisionInputs(
        quality=37, health=62, exit_s=54, add=38,
        invested_amount=200_000, current_value=240_000,
        holding_period_days=1200, is_equity=True,
        exit_load_pct=0.0,
        expense_current=ctx["expense_current"],
        expense_direct=ctx["expense_direct"],
        current_return_5y=ctx["current_return_5y"],
        current_drawdown=ctx["current_drawdown"],
        current_consistency=ctx["current_consistency"],
        current_category=ctx["sub_category"],
        current_fund_name="Sundaram Value Fund Regular",
        years_to_goal=10,
        direct_plan_available=True,
        candidate_funds=peers,
    )
    r = sde.decide(inp, plan_type="regular")
    # Direct-priority kicks in first (same fund, lower TER) — that's the
    # correct PRD behaviour.
    assert r.action in (sde.ACTION_STRONG_SWITCH_DIRECT, sde.ACTION_STRONG_SWITCH)
    # When we remove Direct-plan availability, it should switch to peer fund.
    inp.direct_plan_available = False
    inp.expense_direct = None
    r2 = sde.decide(inp, plan_type="regular")
    assert r2.action in (
        sde.ACTION_STRONG_SWITCH,
        sde.ACTION_PARTIAL_SWITCH,
        sde.ACTION_WATCHLIST,
    )
    assert r2.to_fund is not None
    assert "SBI Contra" in r2.to_fund or "ICICI" in r2.to_fund
