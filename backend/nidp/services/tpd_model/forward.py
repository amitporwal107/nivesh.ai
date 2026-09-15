"""v2 forward test (thresholds_lock_v2_forward.json): score the next session, freeze it before the open, grade it
after the session's bars land.

A snapshot directory <root>/<target_session>/ holds tpd3_predictions.csv, manifest.json and manifest.sha256. It is
written once, before 09:15 IST on the target session, and never overwritten; grading verifies both hashes first.

    python -m nidp.services.tpd_model.forward score --exports <dir> --ca-csv <csv> --root <dir> --store <dir>
    python -m nidp.services.tpd_model.forward grade --exports <dir> --ca-csv <csv> --root <dir>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
import time as _time
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .calendar import cm_holidays, next_trading_day
from .design import MODEL_COLUMNS, MODEL_COLUMNS_V3, OWN_HISTORY_COUNT, design_matrix
from .event_gate import IST
from .features import compute_features
from .features_v3 import compute_features_v3
from .labels import build_labels
from .panel_source import select_nse_eq
from .universe import pit_universe
from .walkforward import Fold, SingleFeatureLogit, fit_gbm, training_rows

logger = logging.getLogger(__name__)

HEADS = ("p_up10_1d", "p_down10_1d")
V3_FILE = "tpd3_v3_predictions.csv"  # v3 (v2 + PRD technical/fundamental/ownership blocks) frozen alongside v2
LOCK_V2 = Path(__file__).with_name("thresholds_lock_v2_forward.json")
OPEN = time(9, 15)
WARMUP_BARS = 60


class LateSnapshotError(RuntimeError):
    """The target session has already opened; a snapshot now would not be a forecast."""


class TamperError(RuntimeError):
    """A frozen snapshot no longer matches its manifest."""


class StaleDataError(RuntimeError):
    """The data for the prediction day is missing or incomplete."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def freeze(root: Path, preds: pd.DataFrame, meta: dict, now: datetime, rehearsal: bool = False,
           extra_files: Optional[dict[str, bytes]] = None) -> Path:
    """Write the snapshot once. `extra_files` (name -> bytes, e.g. the fixed baseline's predictions) are frozen
    alongside and hashed into the manifest."""
    D = date.fromisoformat(meta["target_session"])
    if not rehearsal and now >= datetime.combine(D, OPEN, tzinfo=IST):
        raise LateSnapshotError(f"{now.isoformat()} is at or after the {D} open")
    snap = Path(root) / str(D)
    snap.mkdir(parents=True, exist_ok=False)
    body = preds.sort_values(["head", "symbol"], kind="mergesort").to_csv(index=False).encode()
    (snap / "tpd3_predictions.csv").write_bytes(body)
    files = {}
    for name, data in (extra_files or {}).items():
        (snap / name).write_bytes(data)
        files[name] = _sha(data)
    manifest = {**meta, "sha256": _sha(body), "files": files, "rows": int(len(preds)), "generated_at": now.isoformat(),
                "rehearsal": bool(rehearsal)}
    text = json.dumps(manifest, indent=1, sort_keys=True).encode()
    (snap / "manifest.json").write_bytes(text)
    (snap / "manifest.sha256").write_text(_sha(text))
    return snap


def verify(snap: Path) -> dict:
    snap = Path(snap)
    text = (snap / "manifest.json").read_bytes()
    if _sha(text) != (snap / "manifest.sha256").read_text().strip():
        raise TamperError(f"{snap}: manifest.json changed after freezing")
    manifest = json.loads(text)
    if _sha((snap / "tpd3_predictions.csv").read_bytes()) != manifest["sha256"]:
        raise TamperError(f"{snap}: tpd3_predictions.csv changed after freezing")
    for name, digest in manifest.get("files", {}).items():
        if not (snap / name).exists() or _sha((snap / name).read_bytes()) != digest:
            raise TamperError(f"{snap}: {name} missing or changed after freezing")
    return manifest


def grade(snap: Path, panel: pd.DataFrame, exclusions: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Labels for a frozen snapshot, or None while the target session's bars are not in yet."""
    manifest = verify(snap)
    T, D = pd.Timestamp(manifest["data_as_of"]), pd.Timestamp(manifest["target_session"])
    if not (panel["as_of_date"] == D).any():
        return None
    preds = pd.read_csv(Path(snap) / "tpd3_predictions.csv")
    sub = panel[panel["symbol"].isin(set(preds["symbol"])) & panel["as_of_date"].isin([T, D])]
    labels = build_labels(sub, exclusions).set_index(["symbol", "as_of_date"])
    col = {"p_up10_1d": ("up_1d", "excl_1d"), "p_down10_1d": ("down_1d", "excl_1d")}

    def label(frame: pd.DataFrame) -> pd.DataFrame:
        out = frame.sort_values(["head", "symbol"], kind="mergesort").reset_index(drop=True)  # graded files share one order
        ys, reasons = [], []
        for head, sym in zip(out["head"], out["symbol"]):
            key = (sym, T)
            if key not in labels.index:
                ys.append(np.nan); reasons.append("no_bar_on_T")
                continue
            v, r = labels.loc[key, col[head][0]], labels.loc[key, col[head][1]]
            ys.append(np.nan if v is None or (isinstance(v, float) and np.isnan(v)) else float(v))
            reasons.append(None if r is None or (isinstance(r, float) and np.isnan(r)) else r)
        out["y"], out["excluded_reason"] = ys, reasons
        return out

    out = label(preds)
    out.to_csv(Path(snap) / "graded.csv", index=False)
    if (Path(snap) / V3_FILE).exists():  # same labels, the v3 model's probabilities
        label(pd.read_csv(Path(snap) / V3_FILE)).to_csv(Path(snap) / "graded_v3.csv", index=False)
    return out


def check_fresh(panel: pd.DataFrame, expected_T: date, lookback: int = 126, frac: float = 0.8) -> None:
    latest = panel["as_of_date"].max().date()
    if latest < expected_T:
        raise StaleDataError(f"latest session {latest} is before the expected {expected_T}")
    counts = panel.groupby("as_of_date").size().sort_index()
    t = pd.Timestamp(expected_T)
    prior = counts[counts.index < t].iloc[-lookback:]
    n = int(counts.get(t, 0))
    if len(prior) and n < frac * float(prior.median()):
        raise StaleDataError(f"rows on {expected_T}: {n} < {frac:.0%} of trailing median {prior.median():.0f}")


def month_fold(known_sessions: list[date], month_first_session: date, cap_months: int = 18) -> Fold:
    s = pd.DatetimeIndex(sorted(known_sessions))
    first = pd.Timestamp(month_first_session)
    train_start = s[s >= first - pd.DateOffset(months=cap_months)].min().date()
    last_day = (first + pd.offsets.MonthEnd(0)).date()
    return Fold(first.strftime("%Y-%m"), train_start, month_first_session, last_day)


def train_bundle(rows: pd.DataFrame, fold: Fold, heads=HEADS, columns: tuple = MODEL_COLUMNS) -> dict:
    priors = {h: float(training_rows(rows, fold, h)["y_" + h].mean()) for h in ("p_up10_1d", "p_down10_1d")}
    models = {}
    for head in heads:
        tr = training_rows(rows, fold, head)
        y = tr[f"y_{head}"].astype(int)
        X = design_matrix(tr, priors, columns)
        models[head] = {"gbm": fit_gbm(X, y), "atr": SingleFeatureLogit("log_atr_pct").fit(X, y),
                        "own": SingleFeatureLogit(f"lr_{OWN_HISTORY_COUNT[head]}").fit(X, y),
                        "base_rate": float(y.mean()), "train_rows": int(len(tr)), "train_events": int(y.sum()),
                        "train_end_max_horizon": str(tr["horizon_end_1d"].max().date())}
    return {"fold": fold, "priors": priors, "models": models, "columns": list(columns)}


def score_session(features_T: pd.DataFrame, members: list[str], bundle: dict, heads=HEADS) -> pd.DataFrame:
    f = features_T[features_T.index.isin(members) & (features_T["nbars"] >= WARMUP_BARS)]
    X = design_matrix(f, bundle["priors"], tuple(bundle.get("columns", MODEL_COLUMNS)))
    parts = []
    for head in heads:
        m = bundle["models"][head]
        parts.append(pd.DataFrame({"symbol": f.index, "head": head, "p_tpd3": m["gbm"].predict_proba(X.astype(np.float64))[:, 1],
                                   "p_atr_only": m["atr"].predict(X), "p_own_history_only": m["own"].predict(X),
                                   "p_base_rate": m["base_rate"]}))
    return pd.concat(parts, ignore_index=True)


def git_state() -> tuple[str, bool]:
    here = Path(__file__).parent
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=here, capture_output=True, text=True, check=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", "."], cwd=here, capture_output=True, text=True,
                                check=True).stdout.strip())
    return sha, dirty


# ── CLI ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _load(exports: Path):
    raw = pd.read_csv(exports / "panel.csv.gz", parse_dates=["as_of_date"])
    panel = select_nse_eq(raw, set(pd.read_csv(exports / "etfs.csv")["symbol"]))
    events = pd.read_csv(exports / "events.csv", parse_dates=["event_date"])
    events["intimated_at"] = pd.to_datetime(events["intimated_at"], utc=True).dt.tz_convert("Asia/Kolkata")
    hol = pd.read_csv(exports / "holidays.csv", parse_dates=["holiday_date"])
    hol["holiday_date"] = hol["holiday_date"].dt.date
    return panel, events, hol


def _feature_store(store: Path, panel, events, factors, pairs, members_by_D, workers: int):
    """Per-session v2 feature files, computed once. A session's features never change once its bars exist."""
    store.mkdir(parents=True, exist_ok=True)
    todo = [(T, D) for T, D in pairs if not (store / f"{T}.pkl").exists()]
    if todo:
        from . import backtest as bt
        bt._G.update(panel=panel, events=events, factors=factors, members=members_by_D)
        import multiprocessing as mp
        with mp.get_context("fork").Pool(workers) as pool:
            for (T, _), f in zip(todo, pool.imap(_features_v2, todo, chunksize=4)):
                f.to_pickle(store / f"{T}.pkl")
        logger.info("feature store: computed %d sessions", len(todo))
    return pd.concat([pd.read_pickle(store / f"{T}.pkl") for T, _ in pairs], ignore_index=True)


def _features_v2(args):
    from . import backtest as bt
    T, D = args
    f = compute_features(bt._G["panel"], T, events=bt._G["events"], actions=bt._G["factors"], target_session=D,
                         market_members=set(bt._G["members"][D]))
    return f.reset_index().assign(as_of_date=pd.Timestamp(T))


def _features_v3(args):
    from . import backtest as bt
    T, D = args
    f = compute_features_v3(bt._G["panel"], T, events=bt._G["events"], actions=bt._G["factors"], target_session=D,
                            market_members=set(bt._G["members"][D]), financials=bt._G["fin"], shareholding=bt._G["shp"])
    return f.reset_index().assign(as_of_date=pd.Timestamp(T))


def _feature_store_v3(store: Path, panel, events, factors, fin, shp, pairs, members_by_D, workers: int):
    store.mkdir(parents=True, exist_ok=True)
    todo = [(T, D) for T, D in pairs if not (store / f"{T}.pkl").exists()]
    if todo:
        from . import backtest as bt
        bt._G.update(panel=panel, events=events, factors=factors, members=members_by_D, fin=fin, shp=shp)
        import multiprocessing as mp
        with mp.get_context("fork").Pool(workers) as pool:
            for (T, _), f in zip(todo, pool.imap(_features_v3, todo, chunksize=2)):
                f.to_pickle(store / f"{T}.pkl")
        logger.info("v3 feature store: computed %d sessions", len(todo))
    return pd.concat([pd.read_pickle(store / f"{T}.pkl") for T, _ in pairs], ignore_index=True)


def _load_v3_inputs(exports: Path):
    fin = pd.read_csv(exports / "financials.csv.gz", parse_dates=["period_end"])
    fin["broadcast_at"] = pd.to_datetime(fin["broadcast_at"], utc=True)
    shp = pd.read_csv(exports / "shareholding.csv", parse_dates=["period_end"])
    shp["broadcast_at"] = pd.to_datetime(shp["broadcast_at"], utc=True)
    return fin, shp


def cmd_score(a) -> int:
    from .backtest import assemble_rows, corporate_actions_from_archive, suspected_actions, universe_by_session
    from .report import load_lock

    lock, lock_sha = load_lock(LOCK_V2)
    sha, dirty = git_state()
    if dirty and not a.rehearsal_T:
        logger.error("refusing: uncommitted changes in tpd_model (snapshots must be reproducible from a commit)")
        return 3
    panel, events, hol = _load(a.exports)
    holidays = cm_holidays(hol.to_dict("records"))
    sessions = sorted(panel["as_of_date"].dt.date.unique())
    now = datetime.now(IST)
    if a.rehearsal_T:
        T = date.fromisoformat(a.rehearsal_T)
        panel = panel[panel["as_of_date"] <= pd.Timestamp(T)]
        sessions = [s for s in sessions if s <= T]
    else:
        today = now.date()
        T = max(s for s in sessions if s <= today)
        expected = today if (today.weekday() < 5 and today not in holidays) else T
        try:
            check_fresh(panel, expected)
        except StaleDataError as e:
            logger.error("refusing: %s", e)
            return 4
    D, skipped = next_trading_day(T, holidays, known_until=max(holidays))
    if D < date.fromisoformat(lock["forward_window"]["first_target_session"]) and not a.rehearsal_T:
        logger.info("target %s is before the forward window; nothing to do", D)
        return 0
    if (Path(a.root) / str(D)).exists():
        logger.info("snapshot for %s already frozen", D)
        return 0

    factors, known = corporate_actions_from_archive(pd.read_csv(a.ca_csv))
    exclusions = pd.concat([known, suspected_actions(panel, known)], ignore_index=True)
    labels = build_labels(panel, exclusions)
    # The month's model trains only on labels that ended before the month's first session (lock v2 retrain rule).
    in_month = [s for s in [*sessions, D] if s >= D.replace(day=1)]
    fold = month_fold(sessions, in_month[0])
    train_T = [sessions[i] for i in range(WARMUP_BARS - 1, len(sessions) - 1) if sessions[i + 1] < fold.first_scored]
    pairs = [(t, sessions[i + 1]) for i, t in enumerate(sessions[:-1]) if t in set(train_T)] + [(T, D)]
    members = universe_by_session(panel, [d for _, d in pairs[:-1]])
    members[D] = pit_universe(panel, D)  # D has no bars yet; pit_universe reads only sessions before it
    feats = _feature_store(Path(a.store), panel, events, factors, pairs, members, a.workers)
    rows = assemble_rows(feats[feats["as_of_date"] < pd.Timestamp(T)], labels, members, [*sessions, D])
    t0 = _time.time()
    bundle = train_bundle(rows, fold)
    ft = feats[feats["as_of_date"] == pd.Timestamp(T)].set_index("symbol")
    preds = score_session(ft, members[D], bundle)
    v3_extra, v3_meta = {}, None
    if a.with_v3:
        fin, shp = _load_v3_inputs(a.exports)
        feats3 = _feature_store_v3(Path(a.store_v3), panel, events, factors, fin, shp, pairs, members, a.workers)
        rows3 = assemble_rows(feats3[feats3["as_of_date"] < pd.Timestamp(T)], labels, members, [*sessions, D])
        bundle3 = train_bundle(rows3, fold, columns=MODEL_COLUMNS_V3)
        ft3 = feats3[feats3["as_of_date"] == pd.Timestamp(T)].set_index("symbol")
        preds3 = score_session(ft3, members[D], bundle3)
        v3_extra = {V3_FILE: preds3.sort_values(["head", "symbol"], kind="mergesort").to_csv(index=False).encode()}
        v3_meta = {"columns": len(MODEL_COLUMNS_V3), "rows": int(len(preds3)),
                   "train": {h: {k: v for k, v in m.items() if k not in ("gbm", "atr", "own")} for h, m in bundle3["models"].items()}}
    meta = {"data_as_of": str(T), "target_session": str(D), "skipped_holidays": [str(h) for h in skipped],
            "fold_month": fold.month, "train_start": str(fold.train_start), "lock_sha256": lock_sha, "git_sha": sha,
            "git_dirty": dirty, "universe_size": len(members[D]),
            "train": {h: {k: v for k, v in m.items() if k not in ("gbm", "atr", "own")} for h, m in bundle["models"].items()},
            "v3": v3_meta}
    # The lock judges p_up10_1d against the fixed baseline on the same sessions, so a snapshot without the
    # baseline's predictions would be ungradeable for that head: refuse rather than freeze half a test.
    baseline = pd.read_csv(a.baseline_csv)
    if set(baseline.columns) != {"symbol", "p_baseline"} or baseline.empty:
        logger.error("refusing: %s is not a baseline prediction file", a.baseline_csv)
        return 6
    extra = {"baseline_predictions.csv": baseline.sort_values("symbol").to_csv(index=False).encode(), **v3_extra}
    meta["baseline_rows"] = int(len(baseline))
    try:
        snap = freeze(Path(a.root), preds, meta, now=now, rehearsal=bool(a.rehearsal_T), extra_files=extra)
    except LateSnapshotError as e:
        logger.error("refusing: %s", e)
        return 5
    logger.info("froze %s: %d rows, fold %s, trained in %.0fs", snap, len(preds), fold.month, _time.time() - t0)
    return 0


def cmd_grade(a) -> int:
    from .backtest import corporate_actions_from_archive, suspected_actions

    panel, _, _ = _load(a.exports)
    factors, known = corporate_actions_from_archive(pd.read_csv(a.ca_csv))
    exclusions = pd.concat([known, suspected_actions(panel, known)], ignore_index=True)
    graded = pending = 0
    for snap in sorted(p for p in Path(a.root).iterdir() if p.is_dir()):
        if (snap / "graded.csv").exists():
            continue
        out = grade(snap, panel, exclusions)
        if out is None:
            pending += 1
        else:
            graded += 1
            logger.info("graded %s: %d rows, %d events", snap.name, out["y"].notna().sum(), int(out["y"].sum()))
    logger.info("graded %d, still waiting for bars %d", graded, pending)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("score", "grade"):
        p = sub.add_parser(name)
        p.add_argument("--exports", type=Path, required=True)
        p.add_argument("--ca-csv", type=Path, required=True)
        p.add_argument("--root", type=Path, required=True)
        if name == "score":
            p.add_argument("--store", type=Path, required=True)
            p.add_argument("--baseline-csv", type=Path, required=True, help="fixed baseline predictions for the same T")
            p.add_argument("--workers", type=int, default=3)
            p.add_argument("--rehearsal-T", default=None, help="score as of this past session into a rehearsal root")
            p.add_argument("--with-v3", action="store_true", help="also freeze the v3 model (PRD technical/fundamental blocks)")
            p.add_argument("--store-v3", type=Path, default=None, help="v3 feature store (default: <store>_v3)")
    a = ap.parse_args(argv)
    if a.cmd == "score" and a.store_v3 is None:
        a.store_v3 = Path(str(a.store) + "_v3")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return cmd_score(a) if a.cmd == "score" else cmd_grade(a)


if __name__ == "__main__":
    raise SystemExit(main())
