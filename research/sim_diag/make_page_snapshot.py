"""One compact JSON page snapshot for the Simulation Lab UI (schema `sim-lab-1`).

Reads a finished comparison-matrix run folder (run_matrix.py output) plus the D1-D4 run folder (run.py output) and
writes a single file a product API can serve. Nothing here computes a result: every number is copied from the run
artifacts, or is a count/round of a column that is in them. A field the artifacts do not carry is left out (and listed
in `notes.omitted_fields` / `notes.unavailable`), never substituted.

Presentation rules that must survive into the page are carried verbatim from
docs/ai_research/tpd3/sim_diag/PREREGISTRATION_SIM_MATRIX.md sections 5 and 5a (see NOTES_* below): fixed-notional runs
are reported per trade and in rupees only, `max_drawdown` is portfolio-only, the paired comparison is descriptive, and
every tax figure is an illustrative annex.

The heavy parts (`trades`, `candidates`) are the replay window only:
- `trades`: every configuration the run folder holds, restricted to replay-window decision dates.
- `candidates`: every candidate that was picked or traded, plus the top 20 by rank per session.

A smoke run (`"smoke": true` in matrix_results.json) is a plumbing check, not a result; the flag is copied to the top
level so the UI can show its banner.

Usage: python make_page_snapshot.py <matrix_run_dir> <d1_d4_run_dir> [<output_path>]
       (default output: <matrix_run_dir>/sim_lab_snapshot.json)
"""
from __future__ import annotations

import datetime as dt
import glob
import gzip
import hashlib
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
MV5 = os.path.normpath(os.path.join(HERE, "..", "model_v5"))
sys.path.insert(0, MV5)
import dataset as DS  # noqa: E402  (the same Nifty-500 list and ETF cut the run itself used, via inputs.universe_isin)

SCHEMA = "sim-lab-1"
SIZE_LIMIT_BYTES = 8 * 1024 * 1024

# ---- presentation rules, copied verbatim from PREREGISTRATION_SIM_MATRIX.md (frozen at ffa0a139) ----
NOTES_PERCENT_OF_CAPITAL = (
    "§5: Fixed-notional runs report per trade and in rupees only. A \"% of ₹5,00,000\" figure is invalid for "
    "them (config A alone needs up to ₹8.98 lakh at once) and is not reported."
)
NOTES_DRAWDOWN = (
    "§5: max_drawdown: portfolio runs only (D, F), on the engine's daily equity curve, peak-to-trough, in ₹ "
    "and % of ₹5,00,000. For fixed-notional runs the equivalent is reported as the worst cumulative net over the "
    "trade sequence in rupees, labelled worst_cumulative_net, and not called a drawdown."
)
NOTES_PAIRED = (
    "§5: Paired comparison to A over the common trades: mean difference in net per trade with a date-clustered "
    "bootstrap (2,000 resamples, dates as clusters) and a 95% interval. Descriptive: no p-value, no accept/reject, "
    "because the baseline has already been shown to lose and nothing here is being selected."
)
NOTES_TAX = (
    "§5a: Pre-tax is primary. The tax line is an annex, computed only where the run's net is positive, at both "
    "regimes, because the trades are 2022 and the cost model is 2026: STCG 15% + 4% cess (the law in 2022) and "
    "20% + 4% cess (after 2024-07-23). No surcharge, no set-off, no carry-forward. Every tax figure is labelled "
    "illustrative."
)

# ---- reconciliation class descriptions, copied verbatim from reconcile.py's module docstring ----
RECON_CLASS_WHAT = {
    "NET_PAISA_ROUNDING": "the simulator's unrounded path (fills not rounded to the paisa, same quantity) agrees "
                          "within 1e-6",
    "NET_QTY_BOUNDARY": "the unrounded path agrees, and its quantity differs from the rounded fill's",
    "LOCKED_LOWER_FULL_DAY": "the simulator could not sell because every blocked bar was locked all day "
                             "(high == low); labels.py sold at that bar's open, a price at which nothing could be "
                             "sold (a labels.py defect)",
    "LOCKED_LOWER_HEURISTIC": "at least one blocked bar traded away from its open, so the lock test "
                              "(execution.locked_lower: open == low at a band) was a false positive and a sale at "
                              "the open was possible (a simulator defect)",
    "UNEXPLAINED": "no recomputation that removes one known difference makes the two agree",
}

# ---- rounding (heavy blocks only; the copied metric blocks are written through unchanged) ----
RUPEES_2DP = {"entry_price", "stop", "target", "exit_price", "buy_value", "sell_value", "gross_inr", "slippage_inr",
              "charges_inr", "net_inr", "initial_risk_inr", "risk_per_trade", "stop_price", "target_price", "value20"}
RATIOS_6DP = {"net_ret", "gross_ret", "r_multiple", "mfe_pct", "mae_pct", "stop_distance_atr", "gap_pct", "score",
              "atr_pct", "movement_probability", "tbs_probability", "tbs_probability_calibrated_in_sample",
              "direction_probability", "tradeability_score"}
NEVER_ROUND = {"prediction_id", "trade_id", "symbol", "isin", "company", "rank", "qty", "position_size"}

# ---- the trade row contract; the source column in the matrix run's trades CSVs, or None when it is joined ----
TRADE_FIELDS = [
    ("trade_id", None), ("symbol", "symbol"), ("company", None), ("decision_date", "decision_date"),
    ("entry_date", "entry_date"), ("exit_date", "exit_date"), ("exit_reason", "exit_reason"), ("rank", None),
    ("score", None), ("qty", "qty"), ("entry_price", "entry_price"), ("stop", "stop"), ("target", "target"),
    ("exit_price", "exit_price"), ("gross_inr", "gross_inr"), ("slippage_inr", "slippage_inr"),
    ("charges_inr", "charges_inr"), ("net_inr", "net_inr"), ("net_ret", "net_ret"), ("r_multiple", "r_multiple"),
    ("mfe_pct", "mfe_pct"), ("mae_pct", "mae_pct"), ("stop_distance_atr", "stop_distance_atr"),
    ("rc1_primary", "rc1_primary"), ("flags", "flags"), ("dq_status", None),
]
TRADE_STRINGS = {"trade_id", "symbol", "company", "decision_date", "entry_date", "exit_date", "exit_reason",
                 "rc1_primary", "flags", "dq_status"}
CANDIDATE_TOP_N = 20


class SnapshotError(RuntimeError):
    pass


# ---------------- small helpers ----------------

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def clean(o):
    """NaN and infinity are not JSON. Anything non-finite becomes null; nothing is dropped or guessed."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (np.floating,)):
        o = float(o)
    if isinstance(o, float) and not np.isfinite(o):
        return None
    if isinstance(o, (dt.date, pd.Timestamp)):
        return str(pd.Timestamp(o).date())
    return o


def round_field(name: str, value):
    """6 decimals for ratios, 2 for rupees, everything else untouched. Hashes and ids are never rounded."""
    if name in NEVER_ROUND or not isinstance(value, float) or not np.isfinite(value):
        return value
    if name in RUPEES_2DP:
        return round(value, 2)
    if name in RATIOS_6DP:
        return round(value, 6)
    return value


def cell(name: str, value):
    """One output cell: strings keep their text (missing becomes ""), numbers are rounded, NaN becomes null."""
    if name in TRADE_STRINGS:
        if value is None or (isinstance(value, float) and not np.isfinite(value)):
            return ""
        return str(value)
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    return round_field(name, value)


def read_json(path: str):
    with open(path) as fh:
        return json.load(fh)


def read_csv(path: str) -> pd.DataFrame:
    """round_trip keeps the stored decimal exactly; the run wrote these numbers and we must not shift them."""
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt") as fh:
        return pd.read_csv(fh, float_precision="round_trip")


def datestr(s: pd.Series) -> pd.Series:
    return s.astype(str).str.slice(0, 10)


# ---------------- inputs ----------------

def company_names() -> dict:
    """symbol -> company, from the Nifty-500 list through dataset.universe (the ETF cut inputs.universe_isin uses)."""
    uni, _ = DS.universe()
    return dict(zip(uni.symbol, uni.name))


# The pool run's own 85,000 rows are not shipped: the page needs its aggregates (they are in the matrix block and
# the rank bands), and its replay slice alone is 3.8 MB of a 4.4 MB file.
TRADES_NOT_SHIPPED = ("S5_POOL",)


def config_files(matrix_dir: str) -> dict:
    """Configuration key -> trades file. The key is the file stem after `trades_`, because several engine files share
    the same `config` column value (D or F) and would otherwise collide."""
    out = {}
    for path in sorted(glob.glob(os.path.join(matrix_dir, "trades_*.csv")) +
                       glob.glob(os.path.join(matrix_dir, "trades_*.csv.gz"))):
        name = os.path.basename(path)
        key = name[len("trades_"):].removesuffix(".gz").removesuffix(".csv")
        if key in TRADES_NOT_SHIPPED:
            continue
        out[key] = path
    if not out:
        raise SnapshotError(f"no trades_*.csv in {matrix_dir}")
    return out


def _blocks():
    """The authoritative block definitions: the same dataset.BLOCKS the run's guarded loader enforces."""
    sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "model_v5")))
    import dataset as DS
    return DS.BLOCKS


def _block_text() -> str:
    b = _blocks()["dev"]
    return (f"{b.name}: decision sessions {b.feat_start}..{b.feat_end}, bars to {b.bar_end} "
            f"(model_v5/dataset.BLOCKS, enforced by the guarded loader)")


def _sealed_text() -> str:
    t = _blocks()["test"]
    return (f"the {t.name} block {t.feat_start}..{t.feat_end} (bars to {t.bar_end}) is SEALED: it was not read by "
            f"this run, it may be used once, and only after the models are frozen (dataset.check_block / guard_bars)")


# ---------------- blocks ----------------

def run_block(mres: dict, matrix_path: str, d1d4: dict) -> tuple:
    """The run header. `block` and `sealed_note` are not written into either run folder, so they are read from the
    block definitions the run itself used (model_v5/dataset.BLOCKS) rather than left out or typed in here."""
    inputs = mres.get("inputs", {})

    def only(pred, what):
        hits = [v for k, v in inputs.items() if pred(k)]
        if len(hits) != 1:
            missing.append(f"run.{what}: {len(hits)} input files matched in matrix_results.json['inputs']")
            return None
        return hits[0]

    missing = []
    run = {"id": mres.get("run"), "code_commit": mres.get("code_commit"), "prereg": mres.get("prereg"),
           "cost_model": mres.get("cost_model"), "capital_inr": mres.get("capital_inr"),
           "prediction_commit": mres.get("prediction_commit"),
           "dataset_sha256": only(lambda k: k.startswith("dataset"), "dataset_sha256"),
           "oof_sha256": only(lambda k: "_oof" in k, "oof_sha256"),
           "picks_sha256": only(lambda k: "_picks" in k, "picks_sha256"),
           "smoke": bool(mres.get("smoke")), "baseline_vs_d3": mres.get("baseline_vs_d3"),
           "block": _block_text(), "sealed_note": _sealed_text(),
           # extras kept because they are in the artifacts and the page would otherwise lose them
           "inputs": inputs, "matrix_results_path": matrix_path,
           "bars_vs_dataset": mres.get("bars_vs_dataset"), "picks_reproduced": mres.get("picks_reproduced"),
           "specs": mres.get("specs"), "exits": mres.get("exits"),
           "d1_d4_code_commit": d1d4.get("code_commit"), "d1_d4_config": d1d4.get("config"),
           "intrabar_policy": d1d4.get("intrabar_policy"), "rc1_rule_set": d1d4.get("rc1")}
    for k in ("block", "sealed_note"):
        missing.append(f"run.{k}: neither run folder records it")
    return {k: v for k, v in run.items() if v is not None}, missing


def sessions_block(mres: dict, d1d4_dir: str) -> tuple:
    """Session counts from the matrix run. The year scope stores only a count, so `first`/`last` are filled from the
    D1-D4 year DQ sessions only when that file describes the same number of sessions."""
    missing = []
    replay = [str(d) for d in mres.get("replay_dates", [])]
    year_count = mres["scopes"]["year"]["sessions"]
    year = {"count": year_count}
    dq_year_path = os.path.join(d1d4_dir, "dq_sessions_2022.json")
    if os.path.exists(dq_year_path):
        days = sorted(read_json(dq_year_path))
        if len(days) == year_count:
            year["first"], year["last"] = days[0], days[-1]
        else:
            missing.append(f"sessions.year.first/last: the matrix year scope has {year_count} sessions but "
                           f"dq_sessions_2022.json describes {len(days)}, so they are not the same session set")
    else:
        missing.append("sessions.year.first/last: dq_sessions_2022.json is not in the D1-D4 run folder")
    if mres["scopes"]["replay"]["sessions"] != len(replay):
        raise SnapshotError("scopes.replay.sessions does not match the length of replay_dates")
    return {"year": year, "replay": {"count": len(replay), "dates": replay}}, missing


def reconciliation_block(d1d4: dict) -> tuple:
    """D3 baseline reconciliation. `classes` is the replay scope (the scope the page's trades are on); the year
    summary is carried beside it so nothing is lost."""
    missing = []
    rep = d1d4.get("reconciliation_replay")
    year = d1d4.get("reconciliation_2022")
    if rep is None:
        missing.append("reconciliation: results.json has no reconciliation_replay")
        return None, missing
    classes = []
    side = rep.get("defect_side", {})
    for name, n in (rep.get("mismatch_classes") or {}).items():
        row = {"class": name, "trades": n, "side": side.get(name)}
        if name in RECON_CLASS_WHAT:
            row["what"] = RECON_CLASS_WHAT[name]
        else:
            missing.append(f"reconciliation.classes[{name}].what: reconcile.py documents no description for it")
        classes.append({k: v for k, v in row.items() if v is not None})
    return {"summary": {"replay": rep, "year": year}, "classes": classes}, missing


def data_quality_block(scorecard: dict, d1d4_dir: str, replay_dates: list) -> tuple:
    missing = []
    dq = {"year": scorecard.get("year", {}).get("A_data_quality"),
          "replay": scorecard.get("replay", {}).get("A_data_quality")}
    sessions = []
    path = os.path.join(d1d4_dir, "dq_sessions_replay.json")
    if not os.path.exists(path):
        missing.append("data_quality.sessions: dq_sessions_replay.json is not in the D1-D4 run folder")
    else:
        raw = read_json(path)
        if sorted(raw) != sorted(replay_dates):
            missing.append("data_quality.sessions: the D1-D4 replay DQ dates are not the matrix run's replay dates; "
                           "the sessions listed are the D1-D4 ones")
        for date in sorted(raw):
            s = raw[date]
            sessions.append({"date": s.get("date", date), "status": s.get("status"),
                             "fail_reasons": s.get("fail_reasons", []), "special_session": s.get("special_session"),
                             "missing_count": len(s.get("missing", [])),
                             "flags": {"universe": s.get("flags_universe", {}),
                                       "trade_bars": s.get("flags_trade_bars", {})}})
    dq["sessions"] = sessions
    return dq, missing


def rc1_block(d1d4: dict, d1d4_dir: str) -> tuple:
    """RC-1 primary-cause counts. The year scope has both cuts in results.json; the replay scope has only the primary
    cut there, so the excl-flags cut is counted off the audit_replay.csv column that results.json counted for the year."""
    missing = []
    out = {"year": {"primary": d1d4.get("rc1_primary_2022"),
                    "primary_excl_unreviewed_flags": d1d4.get("rc1_primary_excl_flags_2022"),
                    "rule_set": d1d4.get("rc1"), "source": "results.json"},
           "replay": {"primary": d1d4.get("rc1_primary_replay"), "rule_set": d1d4.get("rc1"),
                      "source": "results.json"}}
    path = os.path.join(d1d4_dir, "audit_replay.csv")
    if os.path.exists(path):
        col = read_csv(path).get("rc1_primary_excl_unreviewed_flags")
        if col is not None:
            counts = col.value_counts().to_dict()
            out["replay"]["primary_excl_unreviewed_flags"] = {str(k): int(v) for k, v in counts.items()}
            out["replay"]["source"] = "results.json; primary_excl_unreviewed_flags counted from audit_replay.csv"
        else:
            missing.append("rc1.replay.primary_excl_unreviewed_flags: audit_replay.csv has no such column")
    else:
        missing.append("rc1.replay.primary_excl_unreviewed_flags: audit_replay.csv is not in the D1-D4 run folder")
    return {k: {kk: vv for kk, vv in v.items() if vv is not None} for k, v in out.items()}, missing


def trades_block(matrix_dir: str, d1d4_dir: str, replay: set, names: dict) -> tuple:
    """Replay-window trades of every configuration in the run folder. A contract field whose column is not in this
    run's CSV - or is empty for every row of that configuration - is left out for that configuration."""
    cands = read_csv(os.path.join(d1d4_dir, "candidates_replay.csv"))
    cands["date"] = datestr(cands["date"])
    rank_by = cands.set_index(["date", "symbol"])["rank"].to_dict()
    # `score` is the M8|tbs_5_2 ranking score; candidates.py stores that same series as `tbs_probability`
    score_by = cands.set_index(["date", "symbol"])["tbs_probability"].to_dict()

    audit_path = os.path.join(d1d4_dir, "audit_replay.csv")
    trade_id_by, dq_by = {}, {}
    audit_configs = set()
    if os.path.exists(audit_path):
        au = read_csv(audit_path)
        au["signal_date"] = datestr(au["signal_date"])
        audit_configs = set(au["config"].astype(str))
        trade_id_by = au.set_index(["config", "signal_date", "symbol"])["trade_id"].to_dict()
        dq_by = au.set_index(["config", "signal_date", "symbol"])["dq_status"].to_dict()

    out, omitted, empty, joins = {}, {}, {}, {}
    for key, path in sorted(config_files(matrix_dir).items()):
        df = read_csv(path)
        df["decision_date"] = datestr(df["decision_date"])
        for c in ("entry_date", "exit_date"):
            if c in df.columns:
                df[c] = datestr(df[c])
        df = df[df.decision_date.isin(replay)].reset_index(drop=True)
        cfg = str(df["config"].iloc[0]) if len(df) and "config" in df.columns else key
        joinable = cfg in audit_configs and key == cfg   # the audit ledger is one configuration's; never borrow it

        built, gone = [], []
        for field, src in TRADE_FIELDS:
            if src is not None and src not in df.columns:
                gone.append(field)
        if not joinable:
            gone += ["trade_id", "dq_status"]
        for _, r in df.iterrows():
            row = {}
            k = (r.decision_date, r.symbol)
            for field, src in TRADE_FIELDS:
                if field in gone:
                    continue
                if src is not None:
                    row[field] = cell(field, r[src])
                elif field == "company":
                    row[field] = cell(field, names.get(r.symbol))
                elif field == "rank":
                    row[field] = cell(field, rank_by.get(k))
                elif field == "score":
                    row[field] = cell(field, score_by.get(k))
                elif field == "trade_id":
                    row[field] = cell(field, trade_id_by.get((cfg, *k)) if joinable else None)
                elif field == "dq_status":
                    row[field] = cell(field, dq_by.get((cfg, *k)) if joinable else None)
            built.append(row)

        # a column that is present but empty for every row of this configuration carries nothing; drop it too
        blanks = []
        for field, _ in TRADE_FIELDS:
            if field in gone or not built:
                continue
            blank = "" if field in TRADE_STRINGS else None
            if all(r.get(field) == blank for r in built):
                blanks.append(field)
                for r in built:
                    r.pop(field, None)
        out[key] = built
        if gone:
            omitted[key] = sorted(gone)
        if blanks:
            empty[key] = sorted(blanks)
        joins[key] = {"config_column": cfg, "trade_id_and_dq_status_joined": bool(joinable), "rows": len(built)}
    return out, omitted, empty, joins


def candidates_block(d1d4_dir: str, replay: set, traded: set, names: dict) -> tuple:
    """Replay-window candidate ledger, truncated: every candidate that was picked or traded, plus the top 20 by rank
    per session. `traded` is the set of (decision_date, symbol) traded by any configuration except the whole-pool run
    S5_POOL, which trades the entire eligible pool by construction and would defeat the truncation."""
    df = read_csv(os.path.join(d1d4_dir, "candidates_replay.csv"))
    df["date"] = datestr(df["date"])
    df = df[df.date.isin(replay)].reset_index(drop=True)
    picked = df.selection_status.astype(str).eq("SELECTED")
    in_traded = pd.Series([(d, s) in traded for d, s in zip(df.date, df.symbol)], index=df.index)
    top = df["rank"].le(CANDIDATE_TOP_N).fillna(False)
    keep = df[picked | in_traded | top].copy()
    keep["company"] = keep.symbol.map(names)
    rows = []
    for _, r in keep.iterrows():
        row = {}
        for col, val in r.items():
            if isinstance(val, float) and not np.isfinite(val):
                row[col] = None
            elif isinstance(val, (np.integer,)):
                row[col] = int(val)
            elif isinstance(val, (np.floating,)):
                row[col] = round_field(col, float(val))
            elif isinstance(val, float):
                row[col] = round_field(col, val)
            else:
                row[col] = val
        rows.append(row)
    stats = {"rows_in_replay_ledger": int(len(df)), "kept": int(len(keep)),
             "picked": int(picked.sum()), "traded": int(in_traded.sum()), "top_by_rank": int(top.sum())}
    return rows, stats


# ---------------- assembly ----------------

def build(matrix_dir: str, d1d4_dir: str) -> dict:
    matrix_path = os.path.join(matrix_dir, "matrix_results.json")
    mres = read_json(matrix_path)
    source_sha = sha256_file(matrix_path)
    manifest_path = os.path.join(matrix_dir, "manifest.json")
    manifest_sha = read_json(manifest_path).get("matrix_results.json") if os.path.exists(manifest_path) else None

    d1d4 = read_json(os.path.join(d1d4_dir, "results.json"))
    scorecard = read_json(os.path.join(d1d4_dir, "scorecard.json"))
    names = company_names()

    replay_dates = [str(d) for d in mres["replay_dates"]]
    replay = set(replay_dates)

    unavailable = []
    run, miss = run_block(mres, matrix_path, d1d4)
    unavailable += miss
    sessions, miss = sessions_block(mres, d1d4_dir)
    unavailable += miss
    recon, miss = reconciliation_block(d1d4)
    unavailable += miss
    dq, miss = data_quality_block(scorecard, d1d4_dir, replay_dates)
    unavailable += miss
    rc1, miss = rc1_block(d1d4, d1d4_dir)
    unavailable += miss

    trades, omitted, empty, joins = trades_block(matrix_dir, d1d4_dir, replay, names)
    traded = {(r["decision_date"], r["symbol"]) for key, rows in trades.items() if key != "S5_POOL" for r in rows}
    candidates, cand_stats = candidates_block(d1d4_dir, replay, traded, names)

    snap = {
        "schema": SCHEMA,
        "generated_at": dt.datetime.now().astimezone().isoformat(),
        "source_sha256": source_sha,
        "smoke": bool(mres.get("smoke")),
        "run": run,
        "sessions": sessions,
        "matrix": mres["scopes"],
        "reconciliation": recon,
        "data_quality": dq,
        "scorecard": {"year": scorecard.get("year"), "replay": scorecard.get("replay")},
        "rc1": rc1,
        "trades": trades,
        "candidates": candidates,
        "notes": {
            "internal_only": True,
            "percent_of_capital_rule": NOTES_PERCENT_OF_CAPITAL,
            "drawdown_rule": NOTES_DRAWDOWN,
            "paired_comparison_rule": NOTES_PAIRED,
            "tax": "illustrative",
            "tax_rule": NOTES_TAX,
            "prereg": mres.get("prereg"),
            "source_runs": {
                "matrix": {"dir": matrix_dir, "run": mres.get("run"), "smoke": bool(mres.get("smoke")),
                           "matrix_results_sha256": source_sha, "manifest_sha256": manifest_sha,
                           "manifest_agrees": None if manifest_sha is None else manifest_sha == source_sha,
                           "code_commit": mres.get("code_commit")},
                "d1_d4": {"dir": d1d4_dir, "run": d1d4.get("run"), "code_commit": d1d4.get("code_commit")},
                "company_names": {"file": DS.N500, "via": "model_v5/dataset.universe (ETFs cut), as "
                                                          "sim_diag/inputs.universe_isin does"},
            },
            "trades_scope": "replay-window decision dates only; the whole-year runs are not carried",
            "config_keys": "the trades file stem after `trades_`; several engine files share the `config` value "
                           "D or F, so the stem is the key",
            "omitted_fields": omitted,
            "omitted_fields_meaning": "contract fields this run's trades file does not carry a column for (and, for "
                                      "trade_id/dq_status, configurations the audit ledger does not cover)",
            "empty_fields": empty,
            "empty_fields_meaning": "contract fields whose column is present but blank for every replay-window trade "
                                    "of that configuration, so they are left out rather than written as all-null",
            "join_status": joins,
            "score_source": "score is the M8|tbs_5_2 ranking score, read from the candidate ledger column "
                            "`tbs_probability` (candidates.py stores that same series); rank is the ledger `rank`",
            "trade_id_and_dq_status": "joined from audit_replay.csv, which is configuration A's ledger only; both are "
                                      "left out for every other configuration rather than being reconstructed",
            "candidates_truncation": f"kept: selection_status == SELECTED, or traded by any configuration except "
                                     f"S5_POOL, or rank <= {CANDIDATE_TOP_N} in that session",
            "candidates_counts": cand_stats,
            "reconciliation_classes_scope": "replay",
            "rounding": "trades and candidates only: rupee fields to 2 decimals (this includes price levels, so a "
                        "stop or target may differ from the raw artifact in the third decimal), ratio fields to 6 "
                        "decimals; hashes, ids, ranks and quantities are untouched. matrix, scorecard, "
                        "data_quality, reconciliation and rc1 are copied through unrounded.",
            "non_finite": "NaN and infinity are written as null; the file parses with a strict parse_constant",
            "unavailable": unavailable,
        },
    }
    return clean(snap)


def raise_constant(name):
    raise SnapshotError(f"non-JSON constant {name!r} in the output")


def write(snap: dict, path: str) -> tuple:
    with open(path, "w") as fh:
        json.dump(snap, fh, separators=(",", ":"), allow_nan=False)
    size = os.path.getsize(path)
    with open(path) as fh:
        json.load(fh, parse_constant=raise_constant)     # strict: NaN/Infinity would raise here
    return size, sha256_file(path)


def main(argv: list) -> int:
    if not 2 <= len(argv) <= 3:
        print(__doc__)
        return 2
    matrix_dir, d1d4_dir = os.path.abspath(argv[0]), os.path.abspath(argv[1])
    out = os.path.abspath(argv[2]) if len(argv) == 3 else os.path.join(matrix_dir, "sim_lab_snapshot.json")
    snap = build(matrix_dir, d1d4_dir)
    size, digest = write(snap, out)
    print(f"output: {out}")
    print(f"bytes : {size} ({size / 1024 / 1024:.2f} MiB)")
    print(f"sha256: {digest}")
    if snap["smoke"]:
        print("SMOKE RUN - the matrix run behind this snapshot is a plumbing check, not a result.")
    if size > SIZE_LIMIT_BYTES:
        print(f"ERROR: {size} bytes is over the {SIZE_LIMIT_BYTES}-byte limit", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
