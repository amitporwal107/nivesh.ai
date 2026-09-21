"""Paper trades — Ten-Percent Days paper trade simulation engine v1 (migration 151, tpd_model.paper).

    GET /v1/paper-trades/portfolio?sample=forward&portfolio=P5-NEXT[&prediction_date=]
        one session's frozen selection: provenance, the five positions with entry, pre-registered levels, daily path and
        every exit mode, the top of the stored ranked universe with its outcomes, exceptions, benchmarks, and the list of
        recorded prediction dates
    GET /v1/paper-trades/trades/{trade_id}
        one trade: snapshot fields, six daily observations, lifecycle log, all exit modes
    GET /v1/paper-trades/evaluation?sample=forward&portfolio=P5-NEXT
        the latest stored evaluation for that sample and portfolio (never forward and replay pooled)

Internal-plan keys only: the app is the one caller, and it gates end users with the move_odds allowlist flag.

Everything is read back exactly as the engine stored it; nothing here recomputes an outcome. A session whose entry has not
happened yet comes back with its trades PENDING_ENTRY and no prices, never an estimate.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

import nidp.shared.storage.pg as pg
from nidp.services.daas_api.auth import require_api_key

Sample = Literal["forward", "replay"]
Portfolio = Literal["P5-NEXT", "P10-NEXT"]
MODES = ("EOD-1", "EOD-3", "EOD-5", "FIXED", "TARGET_STOP")
EXCEPTION_STATUSES = ("ENTRY_UNAVAILABLE", "DATA_ERROR", "CORPORATE_ACTION_REVIEW", "SUSPENDED", "CANCELLED_BY_RULE")
LIFECYCLE = ("PREDICTED", "SELECTED", "PENDING_ENTRY", "ENTERED", "ENTRY_UNAVAILABLE", "SUSPENDED", "DATA_ERROR", "CORPORATE_ACTION_REVIEW",
             "CANCELLED_BY_RULE", "MONITORING", "EXITED", "EVALUATED")


def require_internal_plan(request: Request, _key=Depends(require_api_key)) -> None:
    rec = getattr(request.state, "daas_key", None)
    if rec is None or rec.plan != "internal":
        raise HTTPException(status_code=403, detail="paper-trades is available to internal keys only")


router = APIRouter(prefix="/paper-trades", tags=["paper_trades"], dependencies=[Depends(require_internal_plan)])


def _v(x: Any) -> Any:
    """asyncpg values as JSON: Decimal → float, dates → ISO strings, arrays element-wise."""
    if isinstance(x, Decimal):
        return float(x)
    if isinstance(x, (date, datetime)):
        return x.isoformat()
    if isinstance(x, (list, tuple)):
        return [_v(y) for y in x]
    return x


def _row(r, keys=None) -> dict:
    return {k: _v(r[k]) for k in (keys or r.keys())}


def _json(x):
    return json.loads(x) if isinstance(x, str) else x


TRADE_KEYS = ("trade_id", "prediction_id", "sample", "portfolio_type", "symbol", "prediction_date", "intended_entry_date", "entry_date",
              "entry_timestamp", "entry_price", "entry_source", "entry_method", "entry_price_adjustment_status", "prev_close",
              "gap_from_previous_close", "entry_slippage", "quantity", "allocated_capital", "target_pct", "stop_pct", "max_holding_sessions",
              "atr_14", "support_level", "resistance_level", "stop_loss_price", "stop_method", "target_1_price", "target_2_price",
              "risk_percent", "reward_percent", "risk_reward_ratio", "status", "status_reason", "flags", "sessions_observed", "exit_mode",
              "exit_date", "exit_price", "exit_reason", "gross_return", "costs", "net_return", "mfe", "mae", "max_drawdown", "target_hit",
              "target_before_stop", "counts_toward_evaluation")
SNAP_KEYS = ("rank", "model_rank", "movement_probability", "p_opposite", "p_other_threshold", "prediction_close", "company_name", "sector", "size_group")
LEVEL_KEYS = ("beta_1y", "swing_high_20", "swing_low_20", "sma20", "sma50", "sma200", "rsi14",
              "pivot_point", "resistance_1", "resistance_2", "support_1", "support_2")
OBS_KEYS = ("session_date", "days_held", "open_price", "high_price", "low_price", "close_price", "volume", "adjustment_factor", "return_from_entry",
            "open_return", "high_return", "low_return", "high_watermark", "drawdown_from_entry", "mfe_to_date", "mae_to_date", "target_hit",
            "stop_hit", "exit_status", "data_quality_status")
EXIT_KEYS = ("mode", "state", "exit_date", "exit_price", "exit_reason", "sessions_held", "gross_return", "cost_pct", "net_return", "net_return_050",
             "net_return_100", "mfe", "mae", "target_hit", "stop_hit")
# Levels shown beside each position for research: the classic pivot set and beta, computed from the
# prediction date's own bar (point-in-time — nothing after the cutoff is read). They are DISPLAY ONLY: the
# pivot breakout tested at 2.5x lift on the +5% move but -0.54% net after costs, so nothing trades on them
# (docs/ai_research/tpd3/v5_net_return/).
TRADE_SQL = """
    SELECT t.*, s.rank, s.model_rank, s.movement_probability, s.p_opposite, s.p_other_threshold,
           (s.eligibility_snapshot->>'close')::numeric AS prediction_close, sm.company_name,
           COALESCE(u.sector, sm.sector) AS sector, u.size_group,
           f.beta_1y, f.swing_high_20, f.swing_low_20, f.sma20, f.sma50, f.sma200, f.rsi14,
           (p.high_price + p.low_price + p.close_price) / 3.0                                  AS pivot_point,
           2*((p.high_price + p.low_price + p.close_price)/3.0) - p.low_price                  AS resistance_1,
           ((p.high_price + p.low_price + p.close_price)/3.0) + (p.high_price - p.low_price)   AS resistance_2,
           2*((p.high_price + p.low_price + p.close_price)/3.0) - p.high_price                 AS support_1,
           ((p.high_price + p.low_price + p.close_price)/3.0) - (p.high_price - p.low_price)   AS support_2
      FROM nidp.tpd_paper_trades t
      JOIN nidp.tpd_paper_prediction_snapshots s ON s.prediction_id = t.prediction_id
      LEFT JOIN nidp.tpd_paper_universe_outcomes u ON u.prediction_id = t.prediction_id
      LEFT JOIN nidp.sector_master sm ON sm.symbol = t.symbol
      LEFT JOIN nidp.stock_features_daily f ON f.symbol = t.symbol AND f.as_of_date = t.prediction_date
      LEFT JOIN nidp.prices_eod p ON p.symbol = t.symbol AND p.as_of_date = t.prediction_date
                                 AND p.series = 'EQ' AND p.source = 'NSE_BHAVCOPY'
"""


async def _paths(conn, trade_ids: list[int]) -> tuple[dict, dict]:
    obs = await conn.fetch("SELECT trade_id, " + ", ".join(OBS_KEYS) + " FROM nidp.tpd_paper_trade_daily_observations "
                           "WHERE trade_id = ANY($1::bigint[]) ORDER BY trade_id, session_date", trade_ids)
    exits = await conn.fetch("SELECT trade_id, " + ", ".join(EXIT_KEYS) + " FROM nidp.tpd_paper_trade_exits WHERE trade_id = ANY($1::bigint[])", trade_ids)
    by_obs: dict[int, list] = {}
    for o in obs:
        by_obs.setdefault(o["trade_id"], []).append(_row(o, OBS_KEYS))
    by_exit: dict[int, dict] = {}
    for e in exits:
        by_exit.setdefault(e["trade_id"], {})[e["mode"]] = _row(e, EXIT_KEYS[1:])
    return by_obs, by_exit


def _trade(r, obs: list, exits: dict) -> dict:
    keys = TRADE_KEYS + SNAP_KEYS + tuple(k for k in LEVEL_KEYS if k in r.keys())
    out = _row(r, keys)
    out["flags"] = out["flags"] or []
    out["observations"] = obs
    out["exits"] = {m: exits.get(m) for m in MODES}
    return out


@router.get("/portfolio", summary="One session's frozen paper portfolio with its paths, exceptions and benchmarks")
async def portfolio(sample: Sample = Query("forward"), portfolio: Portfolio = Query("P5-NEXT"), prediction_date: Optional[date] = Query(None),
                    top: int = Query(25, ge=5, le=100)):
    pool = await pg.get_pool()
    async with pool.acquire() as conn:
        dates = await conn.fetch(
            "SELECT prediction_date, next_trading_session, bool_or(counts_toward_evaluation) AS counts FROM nidp.tpd_paper_prediction_snapshots "
            "WHERE sample = $1 AND portfolio_type = $2 AND prediction_version = 1 GROUP BY 1, 2 ORDER BY 1 DESC", sample, portfolio)
        if not dates:
            return {"data": {"status": "empty", "sample": sample, "portfolio": portfolio, "dates": []}}
        d = prediction_date or dates[0]["prediction_date"]
        if d not in {x["prediction_date"] for x in dates}:
            raise HTTPException(status_code=404, detail=f"no {sample} {portfolio} snapshot for {d.isoformat()}")
        prov = await conn.fetchrow(
            """SELECT model_version, feature_version, snapshot_sha256, prediction_timestamp, data_cutoff_timestamp, next_trading_session, rules_id,
                      bool_or(counts_toward_evaluation) AS counts_toward_evaluation, COUNT(*) AS scored,
                      COUNT(*) FILTER (WHERE selection_status <> 'EXCLUDED') AS eligible
                 FROM nidp.tpd_paper_prediction_snapshots
                WHERE sample = $1 AND portfolio_type = $2 AND prediction_date = $3 AND prediction_version = 1
                GROUP BY 1, 2, 3, 4, 5, 6, 7""", sample, portfolio, d)
        excluded = await conn.fetch("SELECT exclusion_reason, COUNT(*) AS n FROM nidp.tpd_paper_prediction_snapshots WHERE sample = $1 AND "
                                    "portfolio_type = $2 AND prediction_date = $3 AND selection_status = 'EXCLUDED' GROUP BY 1 ORDER BY 2 DESC",
                                    sample, portfolio, d)
        rules = await conn.fetchrow("SELECT rules_id, rules_sha256, git_sha, registered_at, rules FROM nidp.tpd_paper_rule_sets WHERE rules_id = $1",
                                    prov["rules_id"])
        trades = await conn.fetch(TRADE_SQL + " WHERE t.sample = $1 AND t.portfolio_type = $2 AND t.prediction_date = $3 ORDER BY s.rank",
                                  sample, portfolio, d)
        obs, exits = await _paths(conn, [t["trade_id"] for t in trades])
        univ = await conn.fetch(
            """SELECT s.rank, s.symbol, s.movement_probability, s.p_opposite, s.p_other_threshold, s.selection_status,
                      (s.eligibility_snapshot->>'close')::numeric AS prediction_close, sm.company_name,
                      COALESCE(u.sector, sm.sector) AS sector, u.size_group, u.entry_status, u.entry_reason, u.flags, u.entry_price, u.gap, u.atr_14,
                      u.stop_loss_price, u.stop_method, u.target_price, u.sessions_observed, u.session_dates, u.r_open, u.r_high, u.r_low, u.r_close,
                      u.model_label_hit
                 FROM nidp.tpd_paper_prediction_snapshots s
                 LEFT JOIN nidp.tpd_paper_universe_outcomes u ON u.prediction_id = s.prediction_id
                 LEFT JOIN nidp.sector_master sm ON sm.symbol = s.symbol
                WHERE s.sample = $1 AND s.portfolio_type = $2 AND s.prediction_date = $3 AND s.prediction_version = 1 AND s.rank IS NOT NULL
                ORDER BY s.rank LIMIT $4""", sample, portfolio, d, top)
        bench = await conn.fetch("SELECT benchmark, mode, state, n, members, gross_mean, net_mean, target_hit_rate, positive_rate, source "
                                 "FROM nidp.tpd_paper_benchmark_results WHERE sample = $1 AND portfolio_type = $2 AND prediction_date = $3 "
                                 "ORDER BY benchmark, mode", sample, portfolio, d)
    rj = (_json(rules["rules"]) if rules else None) or {}
    cfg = (rj.get("portfolios") or {}).get(portfolio, {})
    costs = rj.get("costs") or {}
    positions = [_trade(t, obs.get(t["trade_id"], []), exits.get(t["trade_id"], {})) for t in trades]
    return {"data": {
        "status": "ok", "sample": sample, "portfolio": portfolio, "prediction_date": d.isoformat(),
        "dates": [{"prediction_date": x["prediction_date"].isoformat(), "entry_session": x["next_trading_session"].isoformat(), "counts": bool(x["counts"])}
                  for x in dates],
        "provenance": {**_row(prov), "excluded": {r["exclusion_reason"]: int(r["n"]) for r in excluded},
                       "rules": ({"rules_id": rules["rules_id"], "rules_sha256": rules["rules_sha256"], "git_sha": (rules["git_sha"] or "")[:7],
                                  "registered_at": _v(rules["registered_at"])} if rules else None)},
        "config": {"target_pct": cfg.get("target_pct"), "atr_multiplier": cfg.get("atr_multiplier"), "head": cfg.get("head"),
                   "other_threshold": cfg.get("other_threshold"), "capital_inr": (rj.get("allocation") or {}).get("capital_inr"),
                   "positions": rj.get("positions_per_portfolio"), "cost_pct": costs.get("base_round_trip_pct"),
                   "cost_sensitivity_pct": costs.get("sensitivity_round_trip_pct") or [], "stop_cap_pct": 8.0, "headline_mode": "EOD-1"},
        "positions": positions,
        "universe": [_row(u) for u in univ],
        "exceptions": [{"symbol": p["symbol"], "status": p["status"], "reason": p["status_reason"], "flags": p["flags"]}
                       for p in positions if p["status"] in EXCEPTION_STATUSES or p["flags"]],
        "benchmarks": [_row(b) for b in bench],
    }}


@router.get("/trades/{trade_id}", summary="One paper trade: snapshot, daily path, lifecycle log and every exit mode")
async def trade(trade_id: int = Path(..., ge=1)):
    pool = await pg.get_pool()
    async with pool.acquire() as conn:
        t = await conn.fetchrow(TRADE_SQL + " WHERE t.trade_id = $1", trade_id)
        if t is None:
            raise HTTPException(status_code=404, detail=f"no paper trade {trade_id}")
        obs, exits = await _paths(conn, [trade_id])
        # lifecycle order, not time: stages recorded in one run share a timestamp, and a pre-registration session was selected only
        # when the rules were registered (after its entry) — each event keeps its own effective_at for the page to show
        events = await conn.fetch("SELECT to_status, from_status, effective_at, recorded_at, note FROM nidp.tpd_paper_trade_events WHERE trade_id = $1 "
                                  "ORDER BY array_position($2::text[], to_status), effective_at", trade_id, list(LIFECYCLE))
        snap = await conn.fetchrow("SELECT prediction_timestamp, data_cutoff_timestamp, model_version, feature_version, snapshot_sha256, rules_id "
                                   "FROM nidp.tpd_paper_prediction_snapshots WHERE prediction_id = $1", t["prediction_id"])
    return {"data": {**_trade(t, obs.get(trade_id, []), exits.get(trade_id, {})), "snapshot": _row(snap) if snap else None,
                     "events": [_row(e) for e in events]}}


@router.get("/evaluation", summary="The latest stored evaluation for one sample and portfolio")
async def evaluation(sample: Sample = Query("forward"), portfolio: Portfolio = Query("P5-NEXT")):
    pool = await pg.get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT as_of_session, computed_at, inputs_sha256, payload FROM nidp.tpd_paper_evaluations WHERE sample = $1 AND "
                                "portfolio_type = $2 ORDER BY as_of_session DESC, computed_at DESC LIMIT 1", sample, portfolio)
    if r is None:
        return {"data": {"status": "none", "sample": sample, "portfolio": portfolio}}
    return {"data": {"status": "ok", "sample": sample, "portfolio": portfolio, "as_of_session": _v(r["as_of_session"]),
                     "computed_at": _v(r["computed_at"]), "inputs_sha256": r["inputs_sha256"], "evaluation": _json(r["payload"])}}
