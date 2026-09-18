"""Write a run to nidp_staging (migration 151) as ONE psql transaction, idempotent (TC-P14).

  * rule set          inserted once; a different hash under the same rules_id aborts the run (rules are immutable)
  * snapshots         insert-only; a re-run whose frozen content differs from the stored row aborts (TC-P2)
  * trades            upserted as the lifecycle advances; entry fields are written once and a later disagreement aborts
  * observations      insert-only; a later price that disagrees with a stored bar is logged as DATA_ERROR, never replaced
  * exits/benchmarks  upserted while OPEN, frozen once CLOSED
  * events            one row per (trade, state), first observation wins
  * evaluations       insert-only, keyed on the hash of the inputs
Bulk rows travel as CSV through COPY ... FROM STDIN into temp tables, then merge with plain SQL.
"""
from __future__ import annotations

import csv
import io
import json
import math
import subprocess
from datetime import date, datetime
from typing import Iterable, Optional, Sequence

import numpy as np
import pandas as pd

CONTAINER = "nidp-postgres-staging"
PSQL = ["psql", "-v", "ON_ERROR_STOP=1", "-q", "-U", "nidp_staging", "-d", "nidp_staging"]


def _plain(v):
    """numpy/pandas scalars as Python values (np.float64 subclasses float but reprs as 'np.float64(...)'); NA as None."""
    if isinstance(v, np.generic):
        v = v.item()
    return None if v is pd.NA or v is pd.NaT else v


def _cell(v) -> str:
    v = _plain(v)
    if v is None:
        return ""
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return ""
        return repr(round(v, 8))
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        items = [_plain(x) for x in v]
        return "{" + ",".join("NULL" if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))) else
                              (x.isoformat() if isinstance(x, (date, datetime)) else str(x)) for x in items) + "}"
    if isinstance(v, dict):
        return json.dumps(v, separators=(",", ":"), default=str)
    return str(v)


def copy_block(table: str, columns: Sequence[str], rows: Iterable[Sequence]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    for r in rows:
        w.writerow([_cell(v) for v in r])
    body = buf.getvalue()
    # empty strings are NULL in CSV COPY unless quoted; the writer never quotes an empty field
    return f"COPY {table} ({', '.join(columns)}) FROM STDIN WITH (FORMAT csv);\n{body}\\.\n"


SNAP_COLS = ["sample", "prediction_version", "prediction_date", "prediction_timestamp", "data_cutoff_timestamp", "next_trading_session",
             "symbol", "isin", "portfolio_type", "target_pct", "horizon_sessions", "movement_probability", "direction_probability",
             "expected_return", "predicted_regime", "p_opposite", "p_other_threshold", "model_rank", "rank", "selection_status",
             "exclusion_reason", "model_version", "feature_version", "snapshot_sha256", "rules_id", "counts_toward_evaluation",
             "eligibility_snapshot"]
KEY = ["sample", "prediction_date", "symbol", "portfolio_type", "model_version", "feature_version"]
TRADE_COLS = KEY + ["intended_entry_date", "entry_date", "entry_timestamp", "entry_price", "entry_source", "entry_price_adjustment_status",
                    "prev_close", "gap_from_previous_close", "entry_slippage", "quantity", "allocated_capital", "target_pct", "stop_pct",
                    "max_holding_sessions", "atr_14", "support_level", "resistance_level", "stop_loss_price", "stop_method",
                    "target_1_price", "target_2_price", "risk_percent", "reward_percent", "risk_reward_ratio", "status", "status_reason",
                    "flags", "sessions_observed", "exit_date", "exit_price", "exit_reason", "gross_return", "costs", "net_return", "mfe",
                    "mae", "max_drawdown", "target_hit", "target_before_stop", "counts_toward_evaluation"]
OBS_COLS = KEY + ["session_date", "days_held", "open_price", "high_price", "low_price", "close_price", "volume", "adjustment_factor",
                  "return_from_entry", "open_return", "high_return", "low_return", "high_watermark", "drawdown_from_entry", "mfe_to_date",
                  "mae_to_date", "target_hit", "stop_hit", "exit_status", "data_quality_status"]
EXIT_COLS = KEY + ["mode", "state", "exit_date", "exit_price", "exit_reason", "sessions_held", "gross_return", "cost_pct", "net_return",
                   "net_return_050", "net_return_100", "mfe", "mae", "target_hit", "stop_hit"]
EVENT_COLS = KEY + ["to_status", "from_status", "effective_at", "note"]
UNIV_COLS = KEY + ["entry_status", "entry_reason", "flags", "entry_price", "gap", "atr_14", "stop_loss_price", "stop_method", "target_price",
                   "sessions_observed", "session_dates", "r_open", "r_high", "r_low", "r_close", "model_label_hit", "ts_exit_index",
                   "ts_gross", "ts_reason", "size_group", "sector"]
BENCH_COLS = ["sample", "portfolio_type", "prediction_date", "entry_session", "benchmark", "mode", "state", "n", "members", "gross_mean",
              "net_mean", "target_hit_rate", "positive_rate", "source", "rules_id"]
INDEX_COLS = ["index_name", "as_of_date", "open_price", "close_price", "source"]

_JOIN = " AND ".join(f"s.{k} = x.{k}" for k in KEY)


def temp(name: str, like: str, cols: Sequence[str], types: dict) -> str:
    defs = ", ".join(f"{c} {types.get(c, 'TEXT')}" for c in cols)
    return f"CREATE TEMP TABLE {name} ({defs}) ON COMMIT DROP;\n"


T = {"prediction_version": "INTEGER", "prediction_date": "DATE", "prediction_timestamp": "TIMESTAMPTZ", "data_cutoff_timestamp": "TIMESTAMPTZ",
     "next_trading_session": "DATE", "target_pct": "NUMERIC", "horizon_sessions": "INTEGER", "movement_probability": "NUMERIC",
     "direction_probability": "NUMERIC", "expected_return": "NUMERIC", "p_opposite": "NUMERIC", "p_other_threshold": "NUMERIC",
     "model_rank": "INTEGER", "rank": "INTEGER", "counts_toward_evaluation": "BOOLEAN", "eligibility_snapshot": "JSONB",
     "intended_entry_date": "DATE", "entry_date": "DATE", "entry_timestamp": "TIMESTAMPTZ", "entry_price": "NUMERIC", "prev_close": "NUMERIC",
     "gap_from_previous_close": "NUMERIC", "entry_slippage": "NUMERIC", "quantity": "NUMERIC", "allocated_capital": "NUMERIC",
     "stop_pct": "NUMERIC", "max_holding_sessions": "INTEGER", "atr_14": "NUMERIC", "support_level": "NUMERIC", "resistance_level": "NUMERIC",
     "stop_loss_price": "NUMERIC", "target_1_price": "NUMERIC", "target_2_price": "NUMERIC", "risk_percent": "NUMERIC",
     "reward_percent": "NUMERIC", "risk_reward_ratio": "NUMERIC", "flags": "TEXT[]", "sessions_observed": "INTEGER", "exit_date": "DATE",
     "exit_price": "NUMERIC", "gross_return": "NUMERIC", "costs": "NUMERIC", "net_return": "NUMERIC", "mfe": "NUMERIC", "mae": "NUMERIC",
     "max_drawdown": "NUMERIC", "target_hit": "BOOLEAN", "target_before_stop": "BOOLEAN", "session_date": "DATE", "days_held": "INTEGER",
     "open_price": "NUMERIC", "high_price": "NUMERIC", "low_price": "NUMERIC", "close_price": "NUMERIC", "volume": "BIGINT",
     "adjustment_factor": "NUMERIC", "return_from_entry": "NUMERIC", "open_return": "NUMERIC", "high_return": "NUMERIC", "low_return": "NUMERIC",
     "high_watermark": "NUMERIC", "drawdown_from_entry": "NUMERIC", "mfe_to_date": "NUMERIC", "mae_to_date": "NUMERIC", "stop_hit": "BOOLEAN",
     "sessions_held": "INTEGER", "cost_pct": "NUMERIC", "net_return_050": "NUMERIC", "net_return_100": "NUMERIC", "effective_at": "TIMESTAMPTZ",
     "gap": "REAL", "target_price": "REAL", "session_dates": "DATE[]", "r_open": "REAL[]", "r_high": "REAL[]", "r_low": "REAL[]", "r_close": "REAL[]",
     "model_label_hit": "BOOLEAN", "ts_exit_index": "SMALLINT", "ts_gross": "REAL", "entry_session": "DATE", "n": "INTEGER", "members": "TEXT[]",
     "gross_mean": "DOUBLE PRECISION", "net_mean": "DOUBLE PRECISION", "target_hit_rate": "DOUBLE PRECISION", "positive_rate": "DOUBLE PRECISION",
     "as_of_date": "DATE"}


def rules_sql(rules_id: str, sha: str, git_sha: str, registered_at: str, rules: dict) -> str:
    j = json.dumps(rules).replace("'", "''")
    return (f"INSERT INTO nidp.tpd_paper_rule_sets (rules_id, rules_sha256, git_sha, registered_at, rules) VALUES "
            f"('{rules_id}', '{sha}', '{git_sha}', '{registered_at}', '{j}'::jsonb) ON CONFLICT (rules_id) DO NOTHING;\n"
            f"DO $$ BEGIN IF (SELECT rules_sha256 FROM nidp.tpd_paper_rule_sets WHERE rules_id = '{rules_id}') <> '{sha}' THEN "
            f"RAISE EXCEPTION 'rules {rules_id} are registered with a different hash: refusing to write'; END IF; END $$;\n")


def run_sql(rules_block: str, snaps: list, trades: list, obs: list, exits: list, events: list, univ: list, bench: list, index: list,
            evaluations: list) -> str:
    out = ["BEGIN;\n", rules_block]
    # ── snapshots (immutable) ──
    out.append(temp("x_snap", "", SNAP_COLS, T))
    out.append(copy_block("x_snap", SNAP_COLS, snaps))
    cols = ", ".join(SNAP_COLS)
    out.append(f"""INSERT INTO nidp.tpd_paper_prediction_snapshots ({cols}) SELECT {cols} FROM x_snap
ON CONFLICT (sample, prediction_date, symbol, portfolio_type, model_version, feature_version, prediction_version) DO NOTHING;
DO $$ DECLARE bad INTEGER; BEGIN
  SELECT COUNT(*) INTO bad FROM x_snap x JOIN nidp.tpd_paper_prediction_snapshots s ON {_JOIN} AND s.prediction_version = x.prediction_version
   WHERE (s.movement_probability, s.rank, s.selection_status, COALESCE(s.exclusion_reason, ''), s.snapshot_sha256, s.model_rank)
         IS DISTINCT FROM (x.movement_probability::NUMERIC(8,5), x.rank, x.selection_status, COALESCE(x.exclusion_reason, ''), x.snapshot_sha256, x.model_rank);
  IF bad > 0 THEN RAISE EXCEPTION 'immutable snapshot differs from the recomputation for % rows: refusing (insert a new prediction_version instead)', bad; END IF;
END $$;
""")
    # ── trades ──
    out.append(temp("x_trade", "", TRADE_COLS, T))
    out.append(copy_block("x_trade", TRADE_COLS, trades))
    tcols = [c for c in TRADE_COLS if c not in ("model_version", "feature_version", "sample", "prediction_date", "symbol", "portfolio_type")]
    ins = ", ".join(["prediction_id", "sample", "portfolio_type", "symbol", "prediction_date"] + tcols)
    sel = ", ".join(["s.prediction_id", "x.sample", "x.portfolio_type", "x.symbol", "x.prediction_date"] + [f"x.{c}" for c in tcols])
    mutable = [c for c in tcols if c not in ("intended_entry_date", "entry_date", "entry_timestamp", "entry_price", "entry_source",
                                                 "entry_price_adjustment_status", "prev_close", "gap_from_previous_close", "entry_slippage",
                                                 "quantity", "allocated_capital", "atr_14", "support_level", "resistance_level",
                                                 "stop_loss_price", "stop_method", "target_1_price", "target_2_price", "risk_percent",
                                                 "reward_percent", "risk_reward_ratio", "stop_pct", "target_pct", "max_holding_sessions",
                                                 "counts_toward_evaluation")]
    entry_once = ["entry_date", "entry_timestamp", "entry_price", "entry_source", "entry_price_adjustment_status", "prev_close",
                  "gap_from_previous_close", "entry_slippage", "quantity", "atr_14", "support_level", "resistance_level", "stop_loss_price",
                  "stop_method", "target_1_price", "target_2_price", "risk_percent", "reward_percent", "risk_reward_ratio", "stop_pct"]
    sets = ", ".join([f"{c} = EXCLUDED.{c}" for c in mutable] +
                     [f"{c} = CASE WHEN t.entry_price IS NULL THEN EXCLUDED.{c} ELSE t.{c} END" for c in entry_once] + ["updated_at = NOW()"])
    out.append(f"""DO $$ DECLARE bad INTEGER; BEGIN
  SELECT COUNT(*) INTO bad FROM x_trade x JOIN nidp.tpd_paper_prediction_snapshots s ON {_JOIN} AND s.prediction_version = 1
   JOIN nidp.tpd_paper_trades t ON t.prediction_id = s.prediction_id
   WHERE t.entry_price IS NOT NULL AND x.entry_price IS NOT NULL AND t.entry_price <> x.entry_price::NUMERIC(14,4);
  IF bad > 0 THEN RAISE EXCEPTION 'recorded entry prices differ from the recomputation for % trades: refusing to overwrite', bad; END IF;
END $$;
INSERT INTO nidp.tpd_paper_trades AS t ({ins}) SELECT {sel} FROM x_trade x
  JOIN nidp.tpd_paper_prediction_snapshots s ON {_JOIN} AND s.prediction_version = 1
ON CONFLICT (prediction_id) DO UPDATE SET {sets}
 WHERE (t.status, t.sessions_observed, t.net_return, t.flags) IS DISTINCT FROM (EXCLUDED.status, EXCLUDED.sessions_observed, EXCLUDED.net_return, EXCLUDED.flags)
    OR t.entry_price IS NULL;
""")
    trade_id = f"(SELECT t.trade_id FROM nidp.tpd_paper_trades t JOIN nidp.tpd_paper_prediction_snapshots s ON s.prediction_id = t.prediction_id WHERE {_JOIN} AND s.prediction_version = 1)"
    # ── observations (insert-only, disagreements logged) ──
    out.append(temp("x_obs", "", OBS_COLS, T))
    out.append(copy_block("x_obs", OBS_COLS, obs))
    ocols = [c for c in OBS_COLS if c not in KEY]
    out.append(f"""CREATE TEMP TABLE x_obs_id ON COMMIT DROP AS SELECT {trade_id} AS trade_id, x.* FROM x_obs x;
INSERT INTO nidp.tpd_paper_trade_events (trade_id, to_status, from_status, effective_at, note)
SELECT DISTINCT o.trade_id, 'DATA_ERROR', NULL, NOW(), 'a stored daily bar differs from the current price panel; the stored bar was kept'
  FROM x_obs_id o JOIN nidp.tpd_paper_trade_daily_observations d ON d.trade_id = o.trade_id AND d.session_date = o.session_date
 WHERE (d.open_price, d.high_price, d.low_price, d.close_price) IS DISTINCT FROM
       (o.open_price::NUMERIC(14,4), o.high_price::NUMERIC(14,4), o.low_price::NUMERIC(14,4), o.close_price::NUMERIC(14,4))
ON CONFLICT (trade_id, to_status) DO NOTHING;
INSERT INTO nidp.tpd_paper_trade_daily_observations (trade_id, {', '.join(ocols)})
SELECT trade_id, {', '.join(ocols)} FROM x_obs_id WHERE trade_id IS NOT NULL ON CONFLICT (trade_id, session_date) DO NOTHING;
""")
    # ── exits (frozen once CLOSED) ──
    out.append(temp("x_exit", "", EXIT_COLS, T))
    out.append(copy_block("x_exit", EXIT_COLS, exits))
    ecols = [c for c in EXIT_COLS if c not in KEY]
    eset = ", ".join(f"{c} = EXCLUDED.{c}" for c in ecols if c != "mode") + ", updated_at = NOW()"
    out.append(f"""INSERT INTO nidp.tpd_paper_trade_exits AS e (trade_id, {', '.join(ecols)})
SELECT {trade_id} AS trade_id, {', '.join('x.' + c for c in ecols)} FROM x_exit x
ON CONFLICT (trade_id, mode) DO UPDATE SET {eset} WHERE e.state <> 'CLOSED';
""")
    # ── events (first observation wins) ──
    out.append(temp("x_event", "", EVENT_COLS, T))
    out.append(copy_block("x_event", EVENT_COLS, events))
    out.append(f"""INSERT INTO nidp.tpd_paper_trade_events (trade_id, to_status, from_status, effective_at, note)
SELECT {trade_id}, x.to_status, x.from_status, x.effective_at, x.note FROM x_event x ON CONFLICT (trade_id, to_status) DO NOTHING;
""")
    # ── universe outcomes (advance while the window fills) ──
    out.append(temp("x_univ", "", UNIV_COLS, T))
    out.append(copy_block("x_univ", UNIV_COLS, univ))
    ucols = [c for c in UNIV_COLS if c not in KEY]
    uset = ", ".join(f"{c} = EXCLUDED.{c}" for c in ucols) + ", updated_at = NOW()"
    out.append(f"""INSERT INTO nidp.tpd_paper_universe_outcomes AS u (prediction_id, {', '.join(ucols)})
SELECT s.prediction_id, {', '.join('x.' + c for c in ucols)} FROM x_univ x
  JOIN nidp.tpd_paper_prediction_snapshots s ON {_JOIN} AND s.prediction_version = 1
ON CONFLICT (prediction_id) DO UPDATE SET {uset}
 WHERE u.sessions_observed < EXCLUDED.sessions_observed OR u.entry_status IS DISTINCT FROM EXCLUDED.entry_status;
""")
    # ── benchmarks (frozen once CLOSED), index bars, evaluations ──
    out.append(temp("x_bench", "", BENCH_COLS, T))
    out.append(copy_block("x_bench", BENCH_COLS, bench))
    bset = ", ".join(f"{c} = EXCLUDED.{c}" for c in ("state", "n", "members", "gross_mean", "net_mean", "target_hit_rate", "positive_rate", "source")) + ", updated_at = NOW()"
    out.append(f"""INSERT INTO nidp.tpd_paper_benchmark_results AS b ({', '.join(BENCH_COLS)}) SELECT {', '.join(BENCH_COLS)} FROM x_bench
ON CONFLICT (sample, portfolio_type, prediction_date, benchmark, mode, rules_id) DO UPDATE SET {bset} WHERE b.state <> 'CLOSED';
""")
    out.append(temp("x_index", "", INDEX_COLS, T))
    out.append(copy_block("x_index", INDEX_COLS, index))
    out.append(f"INSERT INTO nidp.tpd_paper_index_bars ({', '.join(INDEX_COLS)}) SELECT {', '.join(INDEX_COLS)} FROM x_index ON CONFLICT DO NOTHING;\n")
    for ev in evaluations:
        j = json.dumps(ev["payload"], default=str).replace("'", "''")
        out.append(f"INSERT INTO nidp.tpd_paper_evaluations (sample, portfolio_type, rules_id, as_of_session, inputs_sha256, payload) VALUES "
                   f"('{ev['sample']}', '{ev['portfolio']}', '{ev['rules_id']}', '{ev['as_of_session']}', '{ev['inputs_sha256']}', '{j}'::jsonb) "
                   f"ON CONFLICT (sample, portfolio_type, rules_id, inputs_sha256) DO NOTHING;\n")
    out.append("COMMIT;\n")
    return "".join(out)


def apply(sql: str, container: str = CONTAINER) -> str:
    r = subprocess.run(["docker", "exec", "-i", container, *PSQL], input=sql.encode(), capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"psql exited {r.returncode}: {r.stderr.decode()[-2000:]}")
    return r.stderr.decode()


def query_csv(sql: str, container: str = CONTAINER) -> list[dict]:
    r = subprocess.run(["docker", "exec", "-i", container, "psql", "-U", "nidp_staging", "-d", "nidp_staging", "-v", "ON_ERROR_STOP=1", "-At",
                        "-c", f"COPY ({sql}) TO STDOUT WITH CSV HEADER"], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"psql exited {r.returncode}: {r.stderr.decode()[-2000:]}")
    return list(csv.DictReader(io.StringIO(r.stdout.decode())))
