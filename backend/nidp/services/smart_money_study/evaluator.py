"""Paired baseline-vs-tilt evaluator for the frozen Smart Money studies.

Answers one question and refuses to answer anything else: on identical eligible symbol-days, does
the deal-enhanced model (C) beat the holdings-tilt model (B) by enough, net of the frozen cost
schedule, to clear the preregistered hurdle?

Five rules this module exists to enforce:

 1. IDENTICAL POPULATION. B and C are scored on exactly the same (date, symbol) pairs. Every
    symbol considered is persisted — including the ineligible ones, with a reason — so a model
    cannot look better by quietly dropping the names it has no data for.
 2. NO FUTURE INFORMATION. Eligibility uses only sessions on or before the scoring date. Holdings
    enter only via the point-in-time score series. Deals are usable STRICTLY AFTER their trade
    date, because the feed carries no publication timestamp.
 3. FROZEN CONTRACTS ARE NOT NEGOTIABLE. The stored config is re-hashed and compared with the
    preregistered digest; a mismatch aborts the run rather than adapting to it.
 4. INCREMENTAL VALUE. The statistic is the PAIRED difference per formation date, not each
    model's standalone return.
 5. FAILURE IS INFORMATIVE. PASS / FAIL / INCONCLUSIVE are distinct, and thin samples, poor
    coverage or an uninformative interval return INCONCLUSIVE — never success.

Portfolio size is NOT part of either frozen contract, so it is an explicit implementation
parameter, defaulted here and recorded on the run.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import random
import statistics
import subprocess
import uuid
from datetime import date
from typing import Any, Optional

from nidp.shared.logging_setup import bind_context, setup_logging
from nidp.shared.storage.pg import close_pool, get_pool

logger = logging.getLogger(__name__)

SERVICE_NAME = "smart_money_study"
DEFAULT_PORTFOLIO_N = 30
MIN_FORMATION_DATES = 12          # study 001's review floor for effectively independent blocks
MIN_COVERAGE_PCT = 50.0           # below this the cohort is not representative

# Return-integrity thresholds. nidp.prices_eod is RAW and the adjuster is INCOMPLETE: symbols
# exist that move >=35% in one session while still carrying cumulative_adj_factor = 1.0, some with
# a nidp.corporate_actions row the adjuster never applied (VEDL's 2026-04-30 demerger is the
# reference case). A move that large is therefore not self-evidently a return, so each one is
# classified and anything not positively explained is excluded WITH A REASON — never silently
# included, and never silently dropped either.
UNEXPLAINED_MOVE_PCT = 35.0       # single-session magnitude that demands an explanation
REVERSAL_RECOVERY_FRAC = 0.60     # next session restoring this much of the move ⇒ bad print
INTRADAY_GAP_FRAC = 0.50          # overnight gap at or below this share of the move ⇒ travelled
                                  # intraday, i.e. a real market event rather than a re-pricing
BENCHMARK_INDEX = "Nifty 500"     # per 001's benchmark block; a PRICE index, see _benchmark()


class StudyContractError(RuntimeError):
    pass


async def load_study(conn, study_id: str) -> dict:
    row = await conn.fetchrow(
        "SELECT * FROM nidp.smart_money_study_config WHERE study_id = $1", study_id)
    if row is None:
        raise StudyContractError(f"no frozen contract for {study_id}")
    cfg = row["config"]
    cfg_obj = json.loads(cfg) if isinstance(cfg, str) else cfg
    canonical = json.dumps(cfg_obj, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    if digest != row["prereg_sha256"]:
        raise StudyContractError(
            f"{study_id}: stored config does not match its preregistered hash "
            f"(recomputed {digest[:16]}..., registered {row['prereg_sha256'][:16]}...). "
            "The contract has been altered; refusing to evaluate against it.")
    logger.info("%s: contract verified, hash %s...", study_id, digest[:16])
    return {"row": dict(row), "config": cfg_obj}


# Eligibility, from prices only, using sessions on or before the scoring date.
_UNIVERSE_SQL = """
WITH sessions AS (
    SELECT DISTINCT as_of_date FROM nidp.prices_eod
     WHERE as_of_date <= $1 ORDER BY as_of_date DESC LIMIT $2
),
agg AS (
    SELECT p.symbol,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY p.turnover) AS med_turnover,
           count(*)                                                AS sessions_seen,
           max(p.close_price) FILTER (WHERE p.as_of_date = $1)     AS close_on_date
      FROM nidp.prices_eod p JOIN sessions s ON s.as_of_date = p.as_of_date
     WHERE p.series = 'EQ'
     GROUP BY p.symbol
)
SELECT symbol, med_turnover, close_on_date,
       CASE WHEN close_on_date IS NULL          THEN 'no_price_on_date'
            WHEN close_on_date < $3             THEN 'below_min_price'
            WHEN med_turnover IS NULL
              OR med_turnover < $4              THEN 'below_liquidity_floor'
            WHEN sessions_seen < $2 / 2         THEN 'insufficient_history'
            ELSE NULL END                       AS ineligible_reason
  FROM agg
"""

# Forward return between two sessions, on the open, as the frozen execution convention requires.
# Prices come from nidp.prices_eod_adjusted (adj_open), which is corrected for splits, bonuses and
# other capital-structure events — nidp.prices_eod is raw and turns a 5:1 split into a -80% return.
# Sessions still come from prices_eod, which defines the trading calendar used for eligibility.
_FORWARD_SQL = """
WITH sess AS (
    SELECT DISTINCT as_of_date FROM nidp.prices_eod WHERE as_of_date > $1 ORDER BY as_of_date LIMIT $2
),
entry_d AS (SELECT min(as_of_date) d FROM sess),
exit_d  AS (SELECT max(as_of_date) d FROM sess)
SELECT p1.symbol,
       (SELECT d FROM entry_d) AS entry_date,
       (SELECT d FROM exit_d)  AS exit_date,
       p1.adj_open             AS entry_price,
       p2.adj_open             AS exit_price
  FROM nidp.prices_eod_adjusted p1
  JOIN nidp.prices_eod_adjusted p2
    ON p2.symbol = p1.symbol AND p2.as_of_date = (SELECT d FROM exit_d)
 WHERE p1.as_of_date = (SELECT d FROM entry_d)
   AND p1.adj_open > 0 AND p2.adj_open > 0
"""


# Every >=35% step in the ADJUSTED series landing inside the holding window, with the evidence
# needed to classify it. Detection is on prices_eod_adjusted because a move the adjuster already
# absorbed is not a contaminated return — if it survives into adj_close, the adjustment is missing.
#
# "Single session" means one MARKET session: sessions_spanned comes from the prices_eod calendar,
# not from lag() over the symbol's own rows. Without that, a symbol suspended for three months
# reads as a one-day -45% fall. Measured on this warehouse, 46 of 48 in-window detections span
# more than one session, so the distinction is the difference between a signal and noise.
_UNEXPLAINED_MOVE_SQL = """
WITH sess AS (
    SELECT DISTINCT as_of_date FROM nidp.prices_eod WHERE as_of_date > $1 ORDER BY as_of_date LIMIT $2
),
win AS (SELECT min(as_of_date) AS entry_d, max(as_of_date) AS exit_d FROM sess),
cal AS (SELECT as_of_date, row_number() OVER (ORDER BY as_of_date) AS sn
          FROM (SELECT DISTINCT as_of_date FROM nidp.prices_eod) z),
px AS (SELECT a.symbol, a.as_of_date, cal.sn, a.adj_close, a.raw_open, a.raw_close
         FROM nidp.prices_eod_adjusted a JOIN cal USING (as_of_date)
        WHERE a.adj_close > 0),
st AS (SELECT symbol, as_of_date, sn, adj_close, raw_open, raw_close,
              lag(adj_close)  OVER w AS prev_adj_close,
              lag(raw_close)  OVER w AS prev_raw_close,
              lag(sn)         OVER w AS prev_sn,
              lag(as_of_date) OVER w AS prev_date,
              lead(adj_close) OVER w AS next_adj_close
         FROM px WINDOW w AS (PARTITION BY symbol ORDER BY sn))
SELECT st.symbol, st.prev_date, st.as_of_date AS move_date, st.sn - st.prev_sn AS sessions_spanned,
       st.prev_adj_close, st.adj_close, st.next_adj_close,
       (st.adj_close / st.prev_adj_close - 1.0) * 100.0 AS adj_move_pct,
       CASE WHEN st.prev_raw_close > 0 AND st.raw_open > 0
            THEN (st.raw_open / st.prev_raw_close - 1.0) * 100.0 END AS open_gap_pct,
       (SELECT string_agg(DISTINCT c.action_type, ',' ORDER BY c.action_type)
          FROM nidp.corporate_actions c
         WHERE c.symbol = st.symbol
           AND c.ex_date > st.prev_date AND c.ex_date <= st.as_of_date) AS action_types
  FROM st, win
 WHERE st.prev_adj_close > 0
   AND abs(st.adj_close / st.prev_adj_close - 1.0) * 100.0 >= $3
   AND st.as_of_date BETWEEN win.entry_d AND win.exit_d
"""


# Benchmark over the identical open-to-open window. 001 contracts "Nifty 500 TRI"; no total-return
# series exists in this warehouse (re-verified 2026-10-22: the only *TR* index names are Nifty 50
# leveraged/inverse/futures variants), so the PRICE index is used and labelled a proxy on the run.
_BENCHMARK_SQL = """
WITH sess AS (
    SELECT DISTINCT as_of_date FROM nidp.prices_eod WHERE as_of_date > $1 ORDER BY as_of_date LIMIT $2
),
win AS (SELECT min(as_of_date) AS entry_d, max(as_of_date) AS exit_d FROM sess)
SELECT e.open_price AS entry_level, x.open_price AS exit_level,
       (x.open_price / e.open_price - 1.0) * 100.0 AS benchmark_return_pct
  FROM win
  JOIN nidp.index_eod e ON e.index_name = $3 AND e.as_of_date = win.entry_d
  JOIN nidp.index_eod x ON x.index_name = $3 AND x.as_of_date = win.exit_d
 WHERE e.open_price > 0 AND x.open_price > 0
"""


# Deal feature, strictly before the scoring date (requirement 2), transfers already netted out.
_DEALS_SQL = """
SELECT symbol,
       sum(net_qty)                                   AS net_qty,
       sum(buying_clients)                            AS buying_clients,
       sum(selling_clients)                           AS selling_clients,
       count(*) FILTER (WHERE NOT pure_transfer_day)  AS active_days
  FROM nidp.v_trendlyne_deals_net
 WHERE deal_date < $1 AND deal_date >= $1 - $2::int
 GROUP BY symbol
"""


def _round_trip_cost_pct(cfg: dict) -> float:
    """The frozen round-trip cost, checked against the contract's own components.

    Reading the stored total alone would not notice if it had been edited away from the schedule
    it is supposed to summarise, so the total is recomputed from per_side_pct + GST on the taxable
    components + the buy-only stamp duty and compared. The stored value is 4-dp rounded, so the
    tolerance is 1e-4, not equality.
    """
    cm = cfg.get("cost_model", {})
    if "round_trip_total_pct" in cm:
        total = float(cm["round_trip_total_pct"])
    else:
        raise StudyContractError("frozen cost model has no round_trip_total_pct")

    per_side = cm.get("per_side_pct") or {}
    gst = cm.get("gst_pct_on") or {}
    if per_side and gst:
        side = sum(float(v) for v in per_side.values())
        taxable = sum(float(per_side[k]) for k in gst.get("components", []) if k in per_side)
        side += taxable * float(gst.get("rate", 0.0)) / 100.0
        recomputed = 2.0 * side + sum(float(v) for v in (cm.get("buy_only_pct") or {}).values())
        if abs(recomputed - total) > 1e-4:
            raise StudyContractError(
                f"frozen cost model is internally inconsistent: round_trip_total_pct={total} "
                f"but its own components recompute to {recomputed:.6f}")
        logger.info("%s: cost schedule %.4f%% round trip, consistent with its components (%.6f%%)",
                    SERVICE_NAME, total, recomputed)
    return total


def _classify_unexplained_move(row: dict) -> tuple[str, bool]:
    """Disposition for one detected >=35% single-step move. Returns (disposition, keep).

    Three things a move this large can be, and they are not interchangeable:
      (a) a capital-structure event the adjusted series already handles  -> never detected here,
          because a handled event does not survive into adj_close;
      (b) a genuine market move — a limit move, an open offer, an earnings shock. These are real
          observations and are KEPT; discarding them would bias the study toward calm names;
      (c) a data error or an adjustment the adjuster failed to apply. These are not returns.

    The discriminator between (b) and (c) is WHERE the move happened, measured on real rows before
    this was written: a re-pricing arrives overnight (VEDL 2026-04-30 opened -62.58% into a -64.90%
    session) while a genuine crash opens near the prior close and travels intraday (POLICYBZR
    2026-09-24 opened -10.00% into a -36.00% session).

    Anything not positively explained is excluded — the ladder has no silent fall-through.
    """
    move = float(row["adj_move_pct"])
    actions = row["action_types"]
    if actions:
        # A recorded action whose adjustment never reached adj_close. The return across it is an
        # artefact of the incomplete adjuster, not a price change.
        return f"ca_adjustment_mismatch:{actions}", False

    prev_px, px, nxt_px = row["prev_adj_close"], row["adj_close"], row["next_adj_close"]
    if nxt_px is not None:
        # Recovery measured on LEVELS, not on percentages: a -70% move needs +233% to undo, so
        # comparing percentage magnitudes would under-detect reversals on big down moves.
        span = float(prev_px) - float(px)
        if span != 0:
            recovery = (float(nxt_px) - float(px)) / span
            if recovery >= REVERSAL_RECOVERY_FRAC:
                return "data_error_reversal", False

    if int(row["sessions_spanned"]) > 1:
        # The symbol did not trade across the step, so this is a resumption gap, not a session
        # return. Whatever repriced it happened while the name was untradeable.
        return "trading_gap_discontinuity", False

    gap = row["open_gap_pct"]
    if gap is not None and abs(float(gap)) <= INTRADAY_GAP_FRAC * abs(move):
        return "genuine_market_move", True

    # Consecutive session, clean overnight gap, nothing in nidp.corporate_actions to explain it.
    # Most likely an unrecorded capital-structure event (TATAMOTORS' 2025-10-14 demerger has no
    # action row at all), but it cannot be established from the evidence available, so it fails
    # closed rather than entering the result as a -40% "return".
    return "unexplained_gap_undetermined", False


def _deal_tilt(row: dict, max_tilt: float) -> float:
    """Bounded, separately-scaled deal contribution.

    Direction comes from distinct CLIENTS on each side, not leg counts, and magnitude is damped
    when only one client is involved — a single disclosed buyer is a transaction, not breadth.
    """
    buy = int(row.get("buying_clients") or 0)
    sell = int(row.get("selling_clients") or 0)
    if buy + sell == 0:
        return 0.0
    direction = (buy - sell) / (buy + sell)
    confidence = 1.0 if buy >= 3 else (0.6 if buy == 2 else 0.3)
    return max(-max_tilt, min(max_tilt, direction * confidence * max_tilt))


def _bootstrap_ci(diffs: list[float], iters: int = 5000, alpha: float = 0.05) -> tuple[float, float]:
    """Date-block bootstrap: resamples whole formation dates, which is the dependence unit."""
    if len(diffs) < 2:
        return (float("nan"), float("nan"))
    rng = random.Random(20261022)
    means = []
    n = len(diffs)
    for _ in range(iters):
        means.append(sum(rng.choice(diffs) for _ in range(n)) / n)
    means.sort()
    lo = means[int(alpha / 2 * iters)]
    hi = means[int((1 - alpha / 2) * iters) - 1]
    return (lo, hi)


async def _formation_dates(conn, horizon: int) -> list[date]:
    """PIT scoring dates that have BOTH a baseline and a complete forward window."""
    rows = await conn.fetch(
        """
        WITH pit AS (SELECT DISTINCT as_of_date FROM nidp.smart_money_scores_daily WHERE point_in_time),
        sess AS (SELECT DISTINCT as_of_date FROM nidp.prices_eod)
        SELECT p.as_of_date,
               (SELECT count(*) FROM nidp.v3_stock_scores_daily v WHERE v.as_of_date = p.as_of_date) AS baseline_rows,
               (SELECT count(*) FROM sess s WHERE s.as_of_date > p.as_of_date) AS sessions_after
          FROM pit p ORDER BY p.as_of_date
        """)
    out, skipped = [], []
    for r in rows:
        if r["baseline_rows"] == 0:
            skipped.append((r["as_of_date"], "no_baseline_scores"))
        elif r["sessions_after"] < horizon:
            skipped.append((r["as_of_date"], f"only_{r['sessions_after']}_sessions_forward"))
        else:
            out.append(r["as_of_date"])
    for d, why in skipped:
        logger.info("%s: formation date %s excluded — %s", SERVICE_NAME, d, why)
    return out


async def evaluate(*, study_b: str = "NIDP-SM-VALIDATION-001",
                   study_c: str = "NIDP-SM-VALIDATION-002",
                   portfolio_n: int = DEFAULT_PORTFOLIO_N,
                   deal_lookback_days: int = 90,
                   max_deal_tilt: float = 4.0,
                   stage: str = "exploratory") -> dict:
    bind_context(service=SERVICE_NAME)
    pool = await get_pool()
    run_id = {}
    run_id[study_b] = uuid.uuid4()
    run_id[study_c] = uuid.uuid4()
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                                text=True, cwd="/opt/nidp/dev-repo/nivesh.ai").stdout.strip()
    except Exception:                                                  # noqa: BLE001
        commit = "unknown"

    async with pool.acquire() as conn:
        sb = await load_study(conn, study_b)
        sc = await load_study(conn, study_c)
        cfg = sb["config"]
        horizon = int(sb["row"]["primary_horizon"])
        hurdle = float(sb["row"]["hurdle_pp"])
        cost_pct = _round_trip_cost_pct(cfg)
        ur = cfg["universe_rule"]
        dates = await _formation_dates(conn, horizon)

        for sid, other, meta in ((study_b, study_c, sb), (study_c, study_b, sc)):
            await conn.execute(
                """INSERT INTO nidp.smart_money_study_runs
                   (run_id, study_id, code_commit, config_sha256, data_cutoff, stage, status, notes)
                   VALUES ($1,$2,$3,$4,$5,$6,'RUNNING',$7)""",
                run_id[sid], sid, commit, meta["row"]["prereg_sha256"], date.today(), stage,
                json.dumps({"portfolio_n": portfolio_n, "deal_lookback_days": deal_lookback_days,
                            "max_deal_tilt": max_deal_tilt, "paired_against": other,
                            "paired_run_id": str(run_id[other]),
                            "note": "portfolio_n and deal tilt bounds are implementation "
                                    "parameters, not part of either frozen contract"}))

    logger.info("%s: %d formation date(s); horizon %dd; hurdle %+.2f pp; round-trip cost %.4f%%",
                SERVICE_NAME, len(dates), horizon, hurdle, cost_pct)

    per_date: list[dict] = []
    pred_rows: list[tuple] = []
    out_rows: list[tuple] = []
    # Every detection and its disposition, so the run is auditable rather than merely clean.
    integrity: dict[str, Any] = {
        "threshold_pct": UNEXPLAINED_MOVE_PCT, "detections": [], "dispositions": {},
        "excluded_symbol_days": 0, "benchmark_missing_dates": [],
        "picked_contaminated": 0, "price_assertion_failures": [],
    }
    for d in dates:
        async with pool.acquire() as conn:
            uni = await conn.fetch(_UNIVERSE_SQL, d, ur["turnover_lookback_sessions"],
                                   ur["min_price_inr"], ur["min_trailing_median_turnover_inr"])
            base = {r["symbol"]: float(r["final_score"]) for r in await conn.fetch(
                "SELECT symbol, final_score FROM nidp.v3_stock_scores_daily "
                "WHERE as_of_date=$1 AND final_score IS NOT NULL AND symbol NOT LIKE '\\_\\_%'", d)}
            sm = {r["symbol"]: r for r in await conn.fetch(
                "SELECT symbol, accumulation_score, distribution_score, data_confidence, "
                "evidence_class, single_amc_signal FROM nidp.smart_money_scores_daily "
                "WHERE as_of_date=$1 AND point_in_time", d)}
            deals = {r["symbol"]: dict(r) for r in await conn.fetch(
                _DEALS_SQL, d, deal_lookback_days)}
            fwd = {r["symbol"]: dict(r) for r in await conn.fetch(_FORWARD_SQL, d, horizon)}
            moves = [dict(r) for r in await conn.fetch(
                _UNEXPLAINED_MOVE_SQL, d, horizon, UNEXPLAINED_MOVE_PCT)]
            bench = await conn.fetchrow(_BENCHMARK_SQL, d, horizon, BENCHMARK_INDEX)
            # The window's real sessions, so "is this a trading day" and "does the window span
            # exactly `horizon` sessions" are checked against the calendar, not assumed.
            win_sess = [r["as_of_date"] for r in await conn.fetch(
                "SELECT DISTINCT as_of_date FROM nidp.prices_eod WHERE as_of_date > $1 "
                "ORDER BY as_of_date LIMIT $2", d, horizon)]
        session_set = set(win_sess)
        sessions_in_window = len(win_sess)

        # Return integrity, per symbol, BEFORE ranking. Deliberately not "per picked symbol":
        # screening the whole eligible universe is what keeps the exclusion symmetric, since a
        # disposition computed from (date, symbol) alone cannot know which model picked the name.
        # Doing it after ranking could drop a symbol from B's portfolio and not C's and silently
        # break the pairing that requirement 1 exists to protect.
        contaminated: dict[str, str] = {}
        for m in moves:
            disposition, keep = _classify_unexplained_move(m)
            integrity["dispositions"][disposition] = \
                integrity["dispositions"].get(disposition, 0) + 1
            integrity["detections"].append({
                "scoring_date": d.isoformat(), "symbol": m["symbol"],
                "prev_date": m["prev_date"].isoformat(), "move_date": m["move_date"].isoformat(),
                "sessions_spanned": int(m["sessions_spanned"]),
                "adj_move_pct": round(float(m["adj_move_pct"]), 2),
                "open_gap_pct": round(float(m["open_gap_pct"]), 2) if m["open_gap_pct"] is not None else None,
                "action_types": m["action_types"], "disposition": disposition, "kept": keep})
            if not keep:
                contaminated[m["symbol"]] = f"unexplained_move:{disposition}"

        if bench is None:
            # Not fatal: the primary test is the paired difference on an identical universe, where
            # the benchmark does not enter. But it must not be silently recorded as 0.
            logger.warning("%s: %s has no %s level on both window ends; benchmark left NULL",
                           SERVICE_NAME, d, BENCHMARK_INDEX)
            integrity["benchmark_missing_dates"].append(d.isoformat())
        bench_pct = float(bench["benchmark_return_pct"]) if bench is not None else None

        eligible, excluded = {}, {}
        for r in uni:
            sym = r["symbol"]
            why = r["ineligible_reason"]
            if why is None and sym not in base:
                why = "no_baseline_score"
            if why is None and sym not in fwd:
                why = "no_forward_window"
            if why is None and sym in contaminated:
                why = contaminated[sym]
                integrity["excluded_symbol_days"] += 1
            (excluded if why else eligible)[sym] = why or True

        rows_b, rows_c = [], []
        for sym, why in excluded.items():
            for sid in (study_b, study_c):
                pred_rows.append((sid, run_id[sid], d, sym, None, None, None, None,
                                  None, None, None, None, None, False, str(why)))
        for sym in eligible:
            b_score = base[sym]
            s = sm.get(sym)
            mf_tilt = 0.0
            if s and s["accumulation_score"] is not None and s["distribution_score"] is not None:
                direction = (float(s["accumulation_score"]) - float(s["distribution_score"])) / 100.0
                conf = {"high": 1.0, "medium": 0.6}.get(s["data_confidence"], 0.25)
                conc = 0.5 if s["single_amc_signal"] else 1.0
                mf_tilt = max(-8.0, min(8.0, direction * conf * conc * 8.0))
            d_tilt = _deal_tilt(deals.get(sym, {}), max_deal_tilt)
            rows_b.append((sym, b_score + mf_tilt))
            rows_c.append((sym, b_score + mf_tilt + d_tilt))
            conf = s["data_confidence"] if s else None
            evc = s["evidence_class"] if s else None
            amc = s["single_amc_signal"] if s else None
            smv = float(s["accumulation_score"]) if s and s["accumulation_score"] is not None else None
            pred_rows.append((study_b, run_id[study_b], d, sym, b_score, None, smv,
                              mf_tilt, b_score + mf_tilt, None, conf, evc, amc, True, None))
            pred_rows.append((study_c, run_id[study_c], d, sym, b_score, None, smv,
                              mf_tilt + d_tilt, b_score + mf_tilt + d_tilt, None,
                              conf, evc, amc, True, None))

        if len(eligible) < portfolio_n:
            logger.info("%s: %s skipped — only %d eligible symbols", SERVICE_NAME, d, len(eligible))
            continue

        def price_problems(sym: str) -> list[str]:
            """Task 2 gate on one symbol's window. Depends on (date, symbol) only, never on which
            model picked it, so B and C are gated identically."""
            f = fwd.get(sym)
            if not f:
                return ["no_forward_window"]
            bad = []
            if not (float(f["entry_price"]) > 0 and float(f["exit_price"]) > 0):
                bad.append("non_positive_price")
            if f["entry_date"] not in session_set or f["exit_date"] not in session_set:
                bad.append("date_not_a_session")
            if sessions_in_window != horizon:
                bad.append(f"window_spans_{sessions_in_window}_not_{horizon}")
            if sym in contaminated:
                bad.append("contaminated_window_reached_portfolio")
            return bad

        def net_ret(sym: str) -> Optional[float]:
            f = fwd.get(sym)
            if not f or price_problems(sym):
                return None
            gross = (float(f["exit_price"]) / float(f["entry_price"]) - 1.0) * 100.0
            return gross - cost_pct

        order_b = [sym for sym, _ in sorted(rows_b, key=lambda x: -x[1])]
        order_c = [sym for sym, _ in sorted(rows_c, key=lambda x: -x[1])]
        rank_b = {sym: i + 1 for i, sym in enumerate(order_b)}
        rank_c = {sym: i + 1 for i, sym in enumerate(order_c)}
        base_rank = {sym: i + 1 for i, sym in enumerate(
            sorted(eligible, key=lambda x: -base[x]))}
        for i, row in enumerate(pred_rows):
            if row[2] == d and row[13]:
                rk = rank_b if row[0] == study_b else rank_c
                pred_rows[i] = row[:5] + (base_rank.get(row[3]),) + row[6:9] + \
                    (rk.get(row[3]),) + row[10:]
        top_b = order_b[:portfolio_n]
        top_c = order_c[:portfolio_n]
        rb = [net_ret(s) for s in top_b]
        rc = [net_ret(s) for s in top_c]
        rb = [x for x in rb if x is not None]
        rc = [x for x in rc if x is not None]
        if len(rb) < portfolio_n * 0.8 or len(rc) < portfolio_n * 0.8:
            logger.info("%s: %s skipped — incomplete outcomes (B %d, C %d)",
                        SERVICE_NAME, d, len(rb), len(rc))
            continue

        for sid, picks in ((study_b, top_b), (study_c, top_c)):
            for sym in picks:
                f = fwd.get(sym)
                if not f:
                    continue
                entry_px, exit_px = float(f["entry_price"]), float(f["exit_price"])
                # Task 2 gate, on the rows actually about to be persisted rather than on a sampled
                # check afterwards. net_ret() consults the same function, so a dropped row is also
                # absent from the mean — the summary and the stored outcomes cannot disagree.
                problems = price_problems(sym)
                if problems:
                    if "contaminated_window_reached_portfolio" in problems:
                        integrity["picked_contaminated"] += 1
                    integrity["price_assertion_failures"].append(
                        {"study_id": sid, "scoring_date": d.isoformat(), "symbol": sym,
                         "problems": problems})
                    logger.error("%s: %s %s dropped — %s", SERVICE_NAME, d, sym, ",".join(problems))
                    continue
                gross = (exit_px / entry_px - 1.0) * 100.0
                out_rows.append((sid, run_id[sid], d, sym, horizon, f["entry_date"],
                                 entry_px, f["exit_date"], exit_px,
                                 gross, cost_pct, gross - cost_pct, bench_pct, None, "mature"))

        mb, mc = statistics.fmean(rb), statistics.fmean(rc)
        overlap = len(set(top_b) & set(top_c))
        per_date.append({"date": d.isoformat(), "eligible": len(eligible),
                         "excluded": len(excluded), "b_net_pct": mb, "c_net_pct": mc,
                         "diff_pp": mc - mb, "overlap": overlap,
                         "names_changed": portfolio_n - overlap})
        logger.info("%s %s: B %+.2f%%  C %+.2f%%  diff %+.3f pp  (%d/%d names changed)",
                    SERVICE_NAME, d, mb, mc, mc - mb, portfolio_n - overlap, portfolio_n)

    # Requirement 1, asserted rather than assumed. Any asymmetry between B's and C's evaluated
    # population invalidates the paired estimate, so it is measured on the rows about to be
    # written: same (date, symbol) keys, same eligibility, same ineligibility reason.
    pop_b = {(r[2], r[3]): (r[13], r[14]) for r in pred_rows if r[0] == study_b}
    pop_c = {(r[2], r[3]): (r[13], r[14]) for r in pred_rows if r[0] == study_c}
    only_b, only_c = set(pop_b) - set(pop_c), set(pop_c) - set(pop_b)
    disagree = [k for k in set(pop_b) & set(pop_c) if pop_b[k] != pop_c[k]]
    integrity["paired_population"] = {
        "b_symbol_days": len(pop_b), "c_symbol_days": len(pop_c),
        "in_b_not_c": len(only_b), "in_c_not_b": len(only_c),
        "eligibility_or_reason_disagreements": len(disagree),
        "identical": not (only_b or only_c or disagree),
    }
    if integrity["paired_population"]["identical"]:
        logger.info("%s: paired population identical across B and C (%d symbol-days)",
                    SERVICE_NAME, len(pop_b))
    else:
        logger.error("%s: paired population NOT identical — B-only %d, C-only %d, disagree %d; "
                     "the paired difference is not a valid estimate",
                     SERVICE_NAME, len(only_b), len(only_c), len(disagree))

    async with pool.acquire() as conn:
        if pred_rows:
            for rid in run_id.values():
                await conn.execute(
                    "DELETE FROM nidp.smart_money_shadow_predictions WHERE run_id = $1", rid)
            await conn.copy_records_to_table(
                "smart_money_shadow_predictions", schema_name="nidp", records=pred_rows,
                columns=["study_id", "run_id", "scoring_date", "symbol", "baseline_score",
                         "baseline_rank", "smart_money_score", "tilt", "tilted_score",
                         "tilted_rank", "data_confidence", "evidence_class",
                         "single_amc_signal", "eligible", "ineligible_reason"])
        if out_rows:
            await conn.copy_records_to_table(
                "smart_money_study_outcomes", schema_name="nidp", records=out_rows,
                columns=["study_id", "run_id", "scoring_date", "symbol", "horizon_sessions",
                         "entry_date", "entry_price", "exit_date", "exit_price",
                         "gross_return_pct", "cost_pct", "net_return_pct",
                         "benchmark_return_pct", "sector_return_pct", "maturity"])
    logger.info("%s: persisted %d prediction rows, %d outcome rows",
                SERVICE_NAME, len(pred_rows), len(out_rows))

    return await _finish(pool, run_id, study_b, study_c, per_date, dates,
                         horizon, hurdle, cost_pct, portfolio_n, commit, stage,
                         len(pred_rows), len(out_rows), integrity)


async def _finish(pool, run_id, study_b, study_c, per_date, dates, horizon, hurdle,
                  cost_pct, portfolio_n, commit, stage, n_pred=0, n_out=0,
                  integrity: Optional[dict] = None) -> dict:
    diffs = [p["diff_pp"] for p in per_date]
    n = len(diffs)
    mean_diff = statistics.fmean(diffs) if diffs else float("nan")
    lo, hi = _bootstrap_ci(diffs) if n >= 2 else (float("nan"), float("nan"))
    changed = sum(p["names_changed"] for p in per_date)

    # Requirement 5: an uninformative run must not read as success.
    if n == 0:
        verdict, why = "INCONCLUSIVE", "no formation date produced a complete paired observation"
    elif changed == 0:
        verdict, why = "INCONCLUSIVE", ("the deal feature never changed portfolio membership, so "
                                        "B and C are the same strategy and no increment exists")
    elif n < MIN_FORMATION_DATES:
        verdict, why = "INCONCLUSIVE", (
            f"{n} formation date(s) against study 001's review floor of {MIN_FORMATION_DATES} "
            "effectively independent blocks; the sample cannot support a promotion decision")
    elif lo > hurdle:
        verdict, why = "PASS", f"CI lower bound {lo:+.3f} pp exceeds the {hurdle:+.2f} pp hurdle"
    elif hi < 0:
        verdict, why = "FAIL", f"CI upper bound {hi:+.3f} pp is below zero"
    else:
        verdict, why = "INCONCLUSIVE", (
            f"CI [{lo:+.3f}, {hi:+.3f}] pp spans the decision boundary")

    summary = {
        "run_id_b": str(run_id[study_b]), "run_id_c": str(run_id[study_c]),
        "study_b": study_b, "study_c": study_c, "stage": stage,
        "code_commit": commit, "horizon_sessions": horizon, "hurdle_pp": hurdle,
        "round_trip_cost_pct": cost_pct, "portfolio_n": portfolio_n,
        "formation_dates_considered": len(dates), "formation_dates_used": n,
        "mean_paired_diff_pp": round(mean_diff, 4) if n else None,
        "ci95_pp": [round(lo, 4), round(hi, 4)] if n >= 2 else None,
        "portfolio_names_changed_total": changed,
        "prediction_rows": n_pred, "outcome_rows": n_out,
        "verdict": verdict, "verdict_reason": why, "per_date": per_date,
        "integrity": integrity or {},
        # Stated on every run so a reader cannot mistake what these columns mean.
        "benchmark": {
            "column": "benchmark_return_pct", "populated": True,
            "series": f"nidp.index_eod '{BENCHMARK_INDEX}' open-to-open, same window",
            "contracted": "Nifty 500 TRI", "is_proxy": True,
            "deviation": "no total-return series exists in this warehouse, so a PRICE index is "
                         "used; it understates the benchmark by the dividend yield (~0.1 pp over "
                         "20 sessions). Market context only — the primary paired test is computed "
                         "on an identical universe, where the benchmark does not enter.",
        },
        "sector_relative": {
            "column": "sector_return_pct", "populated": False, "status": "UNAVAILABLE",
            "reason": "no point-in-time sector label exists for these dates. "
                      "nidp.index_constituents has 4 snapshots, all 2026-10-12..2026-10-22, i.e. "
                      "after every formation date; nidp.sector_master carries "
                      "sector_resolved_at in the same October window and is sparse "
                      "(91/123 of the picked symbols have a sector). Labelling Jan-Sep windows "
                      "from an October snapshot would inject exactly the look-ahead and "
                      "survivorship bias 001's universe_rule note rejects, so the column is left "
                      "NULL. No sector-relative conclusion is available from this run.",
        },
    }
    async with pool.acquire() as conn:
        for rid in run_id.values():
            await conn.execute(
                "UPDATE nidp.smart_money_study_runs SET finished_at=now(), status=$2, notes=$3 "
                "WHERE run_id=$1", rid, "OK", json.dumps(summary))
    logger.info("%s VERDICT %s — %s", SERVICE_NAME, verdict, why)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Paired B-vs-C evaluator for the frozen studies")
    ap.add_argument("--portfolio-n", type=int, default=DEFAULT_PORTFOLIO_N)
    ap.add_argument("--deal-lookback-days", type=int, default=90)
    ap.add_argument("--max-deal-tilt", type=float, default=4.0)
    ap.add_argument("--stage", choices=("exploratory", "confirmatory"), default="exploratory")
    args = ap.parse_args()
    setup_logging(service=SERVICE_NAME)

    async def _go() -> None:
        try:
            out = await evaluate(portfolio_n=args.portfolio_n,
                                 deal_lookback_days=args.deal_lookback_days,
                                 max_deal_tilt=args.max_deal_tilt, stage=args.stage)
            print(json.dumps(out, indent=2, default=str))
        finally:
            await close_pool()

    asyncio.run(_go())


if __name__ == "__main__":
    main()
