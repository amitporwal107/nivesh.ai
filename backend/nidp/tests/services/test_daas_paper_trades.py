"""DaaS /v1/paper-trades (TC-P20 in test_reports/paper_trades_engine_20260918_1338.md). No live Postgres: a fake connection
answers each query by the table it reads. Real-data checks of the same endpoints are in the report (staging)."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

IST = timezone(timedelta(hours=5, minutes=30))
RULES = {"portfolios": {"P5-NEXT": {"head": "p_up5_1d", "target_pct": 5.0, "atr_multiplier": 1.5, "other_threshold": "p_up10_1d"}},
         "allocation": {"capital_inr": 100000}, "positions_per_portfolio": 5, "costs": {"base_round_trip_pct": 0.25, "sensitivity_round_trip_pct": [0.5, 1.0]}}


def _trade(tid, rank, sym, status, entry=None, flags=None):
    return {"trade_id": tid, "prediction_id": 100 + tid, "sample": "forward", "portfolio_type": "P5-NEXT", "symbol": sym, "prediction_date": date(2026, 9, 16),
            "intended_entry_date": date(2026, 9, 17), "entry_date": date(2026, 9, 17) if entry else None, "entry_timestamp": None,
            "entry_price": Decimal(str(entry)) if entry else None, "entry_source": "NSE_BHAVCOPY" if entry else None, "entry_method": "next_session_official_open",
            "entry_price_adjustment_status": None, "prev_close": Decimal("134.44"), "gap_from_previous_close": Decimal("-0.014579") if entry else None,
            "entry_slippage": None, "quantity": Decimal("150.966184") if entry else None, "allocated_capital": Decimal("20000"), "target_pct": Decimal("5"),
            "stop_pct": Decimal("8") if entry else None, "max_holding_sessions": 6, "atr_14": Decimal("9.592995"), "support_level": None, "resistance_level": None,
            "stop_loss_price": Decimal("121.8816") if entry else None, "stop_method": "CAP_8PCT" if entry else None,
            "target_1_price": Decimal("139.104") if entry else None, "target_2_price": None, "risk_percent": None, "reward_percent": None,
            "risk_reward_ratio": Decimal("0.625") if entry else None, "status": status, "status_reason": "UPPER_CIRCUIT_OPEN" if status == "ENTRY_UNAVAILABLE" else None,
            "flags": flags, "sessions_observed": 1 if entry else 0, "exit_mode": "EOD-1", "exit_date": None, "exit_price": None, "exit_reason": None,
            "gross_return": None, "costs": None, "net_return": None, "mfe": None, "mae": None, "max_drawdown": None, "target_hit": None, "target_before_stop": None,
            "counts_toward_evaluation": False, "rank": rank, "model_rank": rank, "movement_probability": Decimal("0.366"), "p_opposite": Decimal("0.31"),
            "p_other_threshold": Decimal("0.104"), "prediction_close": Decimal("134.44"), "company_name": f"{sym} Limited", "sector": "Construction", "size_group": "S"}


class _Conn:
    def __init__(self, db):
        self.db = db
        self.queries = []

    async def fetch(self, q, *a):
        self.queries.append((q, a))
        if "GROUP BY 1, 2 ORDER BY 1 DESC" in q: return self.db["dates"]
        if "selection_status = 'EXCLUDED' GROUP BY" in q: return self.db.get("excluded", [])
        if "FROM nidp.tpd_paper_trades t" in q: return self.db.get("trades", [])
        if "tpd_paper_trade_daily_observations" in q: return self.db.get("obs", [])
        if "tpd_paper_trade_exits" in q: return self.db.get("exits", [])
        if "s.rank IS NOT NULL" in q: return self.db.get("universe", [])
        if "tpd_paper_benchmark_results" in q: return self.db.get("bench", [])
        if "tpd_paper_trade_events" in q: return self.db.get("events", [])
        return []

    async def fetchrow(self, q, *a):
        self.queries.append((q, a))
        if "FROM nidp.tpd_paper_trades t" in q: return self.db.get("trade")
        if "tpd_paper_rule_sets" in q: return self.db.get("rules")
        if "tpd_paper_evaluations" in q: return self.db.get("evaluation")
        if "FILTER (WHERE selection_status" in q: return self.db.get("prov")
        if "tpd_paper_prediction_snapshots WHERE prediction_id" in q: return self.db.get("snap")
        return None


class _Pool:
    def __init__(self, db):
        self.conn = _Conn(db)

    def acquire(self):
        conn = self.conn
        class _CM:
            async def __aenter__(self): return conn
            async def __aexit__(self, *a): return False
        return _CM()


def _db(**over):
    db = {"dates": [{"prediction_date": date(2026, 9, 16), "next_trading_session": date(2026, 9, 17), "counts": False}],
          "prov": {"model_version": "v4@0dc20f9", "feature_version": "v4-84in", "snapshot_sha256": "a" * 64, "prediction_timestamp": datetime(2026, 9, 16, 20, 50, tzinfo=IST),
                   "data_cutoff_timestamp": datetime(2026, 9, 16, 20, 30, tzinfo=IST), "next_trading_session": date(2026, 9, 17), "rules_id": "paper-v1",
                   "counts_toward_evaluation": False, "scored": 994, "eligible": 992},
          "excluded": [{"exclusion_reason": "min_price", "n": 1}, {"exclusion_reason": "min_traded_value", "n": 1}],
          "rules": {"rules_id": "paper-v1", "rules_sha256": "ea4bf382", "git_sha": "c3a9fc7e0000", "registered_at": datetime(2026, 9, 18, 13, 37, 49, tzinfo=IST),
                    "rules": json.dumps(RULES)},
          "trades": [_trade(1, 1, "PNCINFRA", "ENTERED", 132.48), _trade(2, 2, "RAYMOND", "ENTRY_UNAVAILABLE"), _trade(3, 3, "TRIVENI", "ENTERED", 239.45, ["GAP_RECORDED"])],
          "obs": [{"trade_id": 1, "session_date": date(2026, 9, 17), "days_held": 0, "open_price": Decimal("132.48"), "high_price": Decimal("141.78"),
                   "low_price": Decimal("132.2"), "close_price": Decimal("139.55"), "volume": 1, "adjustment_factor": Decimal("1"), "return_from_entry": Decimal("0.053367"),
                   "open_return": Decimal("0"), "high_return": Decimal("0.0702"), "low_return": Decimal("-0.0021"), "high_watermark": Decimal("0.053367"),
                   "drawdown_from_entry": Decimal("0"), "mfe_to_date": Decimal("0.0702"), "mae_to_date": Decimal("-0.0021"), "target_hit": True, "stop_hit": False,
                   "exit_status": "OPEN", "data_quality_status": "OK"}],
          "exits": [{"trade_id": 1, "mode": "EOD-1", "state": "CLOSED", "exit_date": date(2026, 9, 17), "exit_price": Decimal("139.55"), "exit_reason": "close of s1",
                     "sessions_held": 1, "gross_return": Decimal("0.053367"), "cost_pct": Decimal("0.25"), "net_return": Decimal("0.050867"),
                     "net_return_050": Decimal("0.048367"), "net_return_100": Decimal("0.043367"), "mfe": Decimal("0.0702"), "mae": Decimal("-0.0021"),
                     "target_hit": True, "stop_hit": False}],
          "universe": [{"rank": 1, "symbol": "PNCINFRA", "movement_probability": Decimal("0.366"), "p_opposite": Decimal("0.31"), "p_other_threshold": Decimal("0.104"),
                        "selection_status": "SELECTED", "company_name": "PNC Infratech Limited", "sector": "Construction", "size_group": "S", "entry_status": "ENTERED",
                        "entry_reason": None, "flags": [], "entry_price": 132.48, "gap": -0.0146, "atr_14": 9.593, "stop_loss_price": 121.88, "stop_method": "CAP_8PCT",
                        "target_price": 139.1, "sessions_observed": 1, "session_dates": [date(2026, 9, 17)], "r_open": [0.0], "r_high": [0.0702], "r_low": [-0.0021],
                        "r_close": [0.0534], "model_label_hit": True}],
          "bench": [{"benchmark": "A_ALL", "mode": "EOD-1", "state": "CLOSED", "n": 980, "members": [], "gross_mean": Decimal("0.001"), "net_mean": Decimal("-0.0015"),
                     "target_hit_rate": Decimal("0.07"), "positive_rate": Decimal("0.4"), "source": None}],
          "trade": None, "events": [], "snap": None, "evaluation": None}
    db.update(over)
    return db


@pytest.fixture
def make_client(monkeypatch):
    from nidp.services.daas_api import auth, keys, ratelimit
    import nidp.shared.storage.pg as pg_mod
    import nidp.services.daas_api.middleware as mw

    def _make(db, plan="internal"):
        pool = _Pool(db)
        async def _get_pool(): return pool
        async def _close_pool(): return None
        monkeypatch.setattr(pg_mod, "get_pool", _get_pool); monkeypatch.setattr(pg_mod, "close_pool", _close_pool)
        rec = keys.KeyRecord(key_id="00000000-0000-0000-0000-000000000009", key_prefix="nvd_t", name="t", owner_email="t@nivesh", plan=plan,
                             rate_limit_rpm=1500, daily_quota=None, status="active", expires_at=None)
        async def _resolve(_t): return rec
        monkeypatch.setattr(auth, "_resolve", _resolve)
        async def _consume(key_id, *, limit_rpm, daily_quota):
            return ratelimit.LimitDecision(allowed=True, limit_rpm=limit_rpm, remaining_rpm=limit_rpm - 1, reset_seconds=60, daily_quota=daily_quota,
                                           daily_used=1, daily_remaining=None, reason=None)
        monkeypatch.setattr(ratelimit, "consume", _consume)
        mw._LOG_REQUESTS = False
        from nidp.services.daas_api.app import app
        return TestClient(app), pool
    return _make


H = {"X-API-Key": "nvd_t_token"}


def test_internal_plan_only(make_client):
    c, _ = make_client(_db(), plan="pro")
    for path in ("/v1/paper-trades/portfolio", "/v1/paper-trades/trades/1", "/v1/paper-trades/evaluation"):
        r = c.get(path, headers=H)
        assert r.status_code == 403, (path, r.text)


def test_portfolio_shape_values_and_exceptions(make_client):
    c, pool = make_client(_db())
    r = c.get("/v1/paper-trades/portfolio?sample=forward&portfolio=P5-NEXT", headers=H)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["status"] == "ok" and d["prediction_date"] == "2026-09-16"
    assert d["dates"] == [{"prediction_date": "2026-09-16", "entry_session": "2026-09-17", "counts": False}]
    assert d["provenance"]["scored"] == 994 and d["provenance"]["excluded"] == {"min_price": 1, "min_traded_value": 1}
    assert d["provenance"]["rules"]["git_sha"] == "c3a9fc7" and d["provenance"]["model_version"] == "v4@0dc20f9"
    assert d["config"] == {"target_pct": 5.0, "atr_multiplier": 1.5, "head": "p_up5_1d", "other_threshold": "p_up10_1d", "capital_inr": 100000, "positions": 5,
                           "cost_pct": 0.25, "cost_sensitivity_pct": [0.5, 1.0], "stop_cap_pct": 8.0, "headline_mode": "EOD-1"}
    p = d["positions"]
    assert [x["symbol"] for x in p] == ["PNCINFRA", "RAYMOND", "TRIVENI"]
    assert p[0]["entry_price"] == 132.48 and p[0]["stop_loss_price"] == 121.8816 and p[0]["stop_method"] == "CAP_8PCT"
    assert set(p[0]["exits"]) == {"EOD-1", "EOD-3", "EOD-5", "FIXED", "TARGET_STOP"}
    assert p[0]["exits"]["EOD-1"]["net_return"] == pytest.approx(0.050867) and p[0]["exits"]["EOD-3"] is None       # not recorded: null, never guessed
    assert p[0]["observations"][0]["session_date"] == "2026-09-17" and p[0]["observations"][0]["close_price"] == 139.55
    assert p[1]["entry_price"] is None and p[1]["observations"] == [] and p[1]["flags"] == [] and p[1]["prediction_close"] == 134.44
    assert d["exceptions"] == [{"symbol": "RAYMOND", "status": "ENTRY_UNAVAILABLE", "reason": "UPPER_CIRCUIT_OPEN", "flags": []},
                               {"symbol": "TRIVENI", "status": "ENTERED", "reason": None, "flags": ["GAP_RECORDED"]}]
    assert d["universe"][0]["session_dates"] == ["2026-09-17"] and d["universe"][0]["r_close"] == [0.0534]
    assert d["benchmarks"][0]["net_mean"] == pytest.approx(-0.0015)
    trade_q = next(a for q, a in pool.conn.queries if "FROM nidp.tpd_paper_trades t" in q)
    assert trade_q == ("forward", "P5-NEXT", date(2026, 9, 16))


def test_portfolio_empty_unknown_date_and_bad_params(make_client):
    c, _ = make_client(_db(dates=[]))
    d = c.get("/v1/paper-trades/portfolio?sample=replay", headers=H).json()["data"]
    assert d == {"status": "empty", "sample": "replay", "portfolio": "P5-NEXT", "dates": []}
    c, _ = make_client(_db())
    assert c.get("/v1/paper-trades/portfolio?prediction_date=2026-09-15", headers=H).status_code == 404
    # the DaaS app's validation handler answers 400, not FastAPI's default 422
    assert c.get("/v1/paper-trades/portfolio?portfolio=P20-NEXT", headers=H).status_code == 400
    assert c.get("/v1/paper-trades/portfolio?sample=live", headers=H).status_code == 400
    assert c.get("/v1/paper-trades/trades/0", headers=H).status_code == 400


def test_trade_detail_and_lifecycle_order(make_client):
    c, _ = make_client(_db())
    assert c.get("/v1/paper-trades/trades/1", headers=H).status_code == 404
    ev = [{"to_status": s, "from_status": f, "effective_at": datetime(2026, 9, 17, 15, 30, tzinfo=IST), "recorded_at": datetime(2026, 9, 18, 14, 5, tzinfo=IST), "note": "n"}
          for s, f in (("PREDICTED", None), ("SELECTED", "PREDICTED"), ("ENTERED", "PENDING_ENTRY"))]
    snap = {"prediction_timestamp": datetime(2026, 9, 16, 20, 50, tzinfo=IST), "data_cutoff_timestamp": datetime(2026, 9, 16, 20, 30, tzinfo=IST),
            "model_version": "v4@0dc20f9", "feature_version": "v4-84in", "snapshot_sha256": "a" * 64, "rules_id": "paper-v1"}
    c, pool = make_client(_db(trade=_trade(1, 1, "PNCINFRA", "ENTERED", 132.48), events=ev, snap=snap))
    r = c.get("/v1/paper-trades/trades/1", headers=H)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["symbol"] == "PNCINFRA" and d["snapshot"]["model_version"] == "v4@0dc20f9"
    assert [e["to_status"] for e in d["events"]] == ["PREDICTED", "SELECTED", "ENTERED"]
    q, args = next((q, a) for q, a in pool.conn.queries if "tpd_paper_trade_events" in q)
    assert "array_position" in q and args[1][:3] == ["PREDICTED", "SELECTED", "PENDING_ENTRY"]          # ordered by lifecycle, not timestamp


def test_evaluation_none_and_payload(make_client):
    c, _ = make_client(_db())
    assert c.get("/v1/paper-trades/evaluation?sample=forward", headers=H).json()["data"] == {"status": "none", "sample": "forward", "portfolio": "P5-NEXT"}
    ev = {"as_of_session": date(2026, 9, 17), "computed_at": datetime(2026, 9, 18, 14, 5, tzinfo=IST), "inputs_sha256": "b" * 64,
          "payload": json.dumps({"sessions": {"counted": 0}, "statement": {"established": False, "text": "Not established"}})}
    c, pool = make_client(_db(evaluation=ev))
    d = c.get("/v1/paper-trades/evaluation?sample=replay&portfolio=P5-NEXT", headers=H).json()["data"]
    assert d["status"] == "ok" and d["evaluation"]["statement"]["established"] is False and d["as_of_session"] == "2026-09-17"
    q, args = next((q, a) for q, a in pool.conn.queries if "tpd_paper_evaluations" in q)
    assert args == ("replay", "P5-NEXT")                                                                  # one sample per payload, never pooled
