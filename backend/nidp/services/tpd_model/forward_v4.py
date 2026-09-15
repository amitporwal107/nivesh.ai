"""v4 forward test: the v2/v3 snapshot mechanics (freeze before the open, hashed manifest, grade after the bars) for
the four v4 heads, with the evening results capture as a required, hashed input and the >= 50% rows listed apart.

    python -m nidp.services.tpd_model.forward_v4 score --exports <dir> --ca-csv <csv> --root <dir> --store-v3 <dir> --live-dir <dir>
    python -m nidp.services.tpd_model.forward_v4 grade --exports <dir> --ca-csv <csv> --root <dir>

Scoring waits for the print window to close (20:30 IST on T) and refuses without that evening's capture file, so
a snapshot can never silently train on complete prints and score on missing ones.
"""
from __future__ import annotations

import argparse
import json
import logging
import time as _time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .calendar import cm_holidays, next_trading_day
from .design import HEADS_V4, MODEL_COLUMNS_V4
from .event_gate import IST, cutoff_ist
from .features_v4 import add_results_print
from .forward import (LateSnapshotError, StaleDataError, WARMUP_BARS, _feature_store_v3, _load, _load_v3_inputs, check_fresh, freeze,
                      git_state, month_fold, score_session, train_bundle, verify)
from .labels import build_labels
from .report import load_lock
from .results_live import merge_live
from .results_print import FREEZE_CUTOFF
from .universe import pit_universe

logger = logging.getLogger(__name__)
LOCK_V4 = Path(__file__).with_name("thresholds_lock_v4_forward.json")
HIGH_CONFIDENCE_FILE = "high_confidence.csv"
LABEL_COLUMNS = {"p_up10_1d": ("l10", "up_1d"), "p_down10_1d": ("l10", "down_1d"), "p_up5_1d": ("l5", "up_1d"), "p_down5_1d": ("l5", "down_1d")}


class PrintWindowOpenError(RuntimeError):
    """Results can still be broadcast inside the print window; scoring now would miss them."""


class MissingCaptureError(RuntimeError):
    """The evening results capture for T is not on disk."""


def check_print_window_closed(T: date, now: datetime) -> None:
    if now <= cutoff_ist(T, at=FREEZE_CUTOFF):
        raise PrintWindowOpenError(f"{now.isoformat()} is not after the {T} {FREEZE_CUTOFF} print cutoff")


def load_capture(live_dir: Path, T: date) -> tuple[pd.DataFrame, dict]:
    csv, stats = Path(live_dir) / f"{T}.csv", Path(live_dir) / f"{T}.csv.stats.json"
    if not csv.exists() or not stats.exists():
        raise MissingCaptureError(f"no results capture for {T} in {live_dir}")
    live = pd.read_csv(csv, parse_dates=["period_end"])
    live["broadcast_at"] = pd.to_datetime(live["broadcast_at"], utc=True)
    return live, json.loads(stats.read_text())


def window_decision(D: date, lock: dict, rehearsal: bool, preview: bool) -> tuple[str, Optional[dict]]:
    """('skip', None) for a real run targeting a session before the locked forward window; otherwise ('score', flags).
    A preview may score any target but never counts; a rehearsal never counts either."""
    in_window = D >= date.fromisoformat(lock["forward_window"]["first_target_session"])
    if not in_window and not (rehearsal or preview):
        return "skip", None
    return "score", {"preview": bool(preview), "counts_toward_verdict": bool(in_window and not rehearsal and not preview)}


def high_confidence_rows(preds: pd.DataFrame, threshold: float = 0.5) -> pd.DataFrame:
    hc = preds[preds["p_tpd3"] >= threshold].sort_values(["head", "p_tpd3", "symbol"], ascending=[True, False, True], kind="mergesort")
    return hc[["head", "symbol", "p_tpd3"] + [c for c in hc.columns if c not in ("head", "symbol", "p_tpd3")]].reset_index(drop=True)


def grade_v4(snap: Path, panel: pd.DataFrame, exclusions: pd.DataFrame) -> Optional[pd.DataFrame]:
    manifest = verify(snap)
    T, D = pd.Timestamp(manifest["data_as_of"]), pd.Timestamp(manifest["target_session"])
    if not (panel["as_of_date"] == D).any():
        return None
    preds = pd.read_csv(Path(snap) / "tpd3_predictions.csv")
    sub = panel[panel["symbol"].isin(set(preds["symbol"])) & panel["as_of_date"].isin([T, D])]
    labs = {"l10": build_labels(sub, exclusions).set_index(["symbol", "as_of_date"]),
            "l5": build_labels(sub, exclusions, pct=5).set_index(["symbol", "as_of_date"])}
    out = preds.sort_values(["head", "symbol"], kind="mergesort").reset_index(drop=True)
    ys, reasons = [], []
    for head, sym in zip(out["head"], out["symbol"]):
        which, col = LABEL_COLUMNS[head]
        L = labs[which]
        if (sym, T) not in L.index:
            ys.append(np.nan); reasons.append("no_bar_on_T"); continue
        v, r = L.loc[(sym, T), col], L.loc[(sym, T), "excl_1d"]
        ys.append(np.nan if v is None or (isinstance(v, float) and np.isnan(v)) else float(v))
        reasons.append(None if r is None or (isinstance(r, float) and np.isnan(r)) else r)
    out["y"], out["excluded_reason"] = ys, reasons
    out.to_csv(Path(snap) / "graded.csv", index=False)
    return out


def cmd_score(a) -> int:
    from .backtest import assemble_rows, corporate_actions_from_archive, suspected_actions, universe_by_session

    lock, lock_sha = load_lock(LOCK_V4)
    sha, dirty = git_state()
    if dirty and not a.rehearsal_T:
        logger.error("refusing: uncommitted changes in tpd_model"); return 3
    panel, events, hol = _load(a.exports)
    holidays = cm_holidays(hol.to_dict("records"))
    sessions = sorted(panel["as_of_date"].dt.date.unique())
    now = datetime.now(IST)
    if a.rehearsal_T:
        T = date.fromisoformat(a.rehearsal_T)
        panel = panel[panel["as_of_date"] <= pd.Timestamp(T)]; sessions = [s for s in sessions if s <= T]
    else:
        today = now.date()
        T = max(s for s in sessions if s <= today)
        try:
            check_fresh(panel, today if (today.weekday() < 5 and today not in holidays) else T)
            check_print_window_closed(T, now)
        except (StaleDataError, PrintWindowOpenError) as e:
            logger.error("refusing: %s", e); return 4
    D, skipped = next_trading_day(T, holidays, known_until=max(holidays))
    decision, flags = window_decision(D, lock, rehearsal=bool(a.rehearsal_T), preview=bool(a.preview))
    if decision == "skip":
        logger.info("target %s is before the v4 forward window; nothing to do (use --preview for a non-counting run)", D); return 0
    if (Path(a.root) / str(D)).exists():
        logger.info("v4 snapshot for %s already frozen", D); return 0
    try:
        live, cap = load_capture(a.live_dir, T)
    except MissingCaptureError as e:
        logger.error("refusing: %s", e); return 8
    factors, known = corporate_actions_from_archive(pd.read_csv(a.ca_csv))
    excl = pd.concat([known, suspected_actions(panel, known)], ignore_index=True)
    l10, l5 = build_labels(panel, excl), build_labels(panel, excl, pct=5)
    in_month = [s for s in [*sessions, D] if s >= D.replace(day=1)]
    fold = month_fold(sessions, in_month[0])
    train_T = [sessions[i] for i in range(WARMUP_BARS - 1, len(sessions) - 1) if sessions[i + 1] < fold.first_scored]
    pairs = [(t, sessions[i + 1]) for i, t in enumerate(sessions[:-1]) if t in set(train_T)] + [(T, D)]
    members = universe_by_session(panel, [d for _, d in pairs[:-1]])
    members[D] = pit_universe(panel, D)
    v3in = _load_v3_inputs(a.exports)
    feats3 = _feature_store_v3(Path(a.store_v3), panel, events, factors, v3in, pairs, members, a.workers)
    fin = merge_live(v3in["fin"], live)
    t0 = _time.time()
    frames = []
    for t, g in feats3.groupby("as_of_date", sort=True):
        frames.append(add_results_print(g.drop(columns=["as_of_date"]).set_index("symbol"), fin, t.date()).reset_index().assign(as_of_date=t))
    feats = pd.concat(frames, ignore_index=True)
    rows = assemble_rows(feats[feats["as_of_date"] < pd.Timestamp(T)], l10, members, [*sessions, D], labels5=l5)
    bundle = train_bundle(rows, fold, heads=HEADS_V4, columns=MODEL_COLUMNS_V4)
    ft = feats[feats["as_of_date"] == pd.Timestamp(T)].set_index("symbol")
    preds = score_session(ft, members[D], bundle, heads=HEADS_V4)
    hc = high_confidence_rows(preds, lock["high_confidence"]["threshold"])
    meta = {"data_as_of": str(T), "target_session": str(D), "skipped_holidays": [str(h) for h in skipped], "fold_month": fold.month,
            "train_start": str(fold.train_start), "lock_sha256": lock_sha, "git_sha": sha, "git_dirty": dirty, "universe_size": len(members[D]),
            "model": "v4", "columns": len(MODEL_COLUMNS_V4), "results_capture": cap, "filed_today_in_universe": int(ft.loc[ft.index.isin(members[D]), "filed_today"].sum()),
            "high_confidence_rows": int(len(hc)), **flags, "dropped_columns": {h: m["gbm"].dropped for h, m in bundle["models"].items()},
            "train": {h: {k: v for k, v in m.items() if k not in ("gbm", "atr", "own")} for h, m in bundle["models"].items()}}
    extra = {HIGH_CONFIDENCE_FILE: hc.to_csv(index=False).encode(), "results_live.csv": live.to_csv(index=False).encode()}
    try:
        snap = freeze(Path(a.root), preds, meta, now=now, rehearsal=bool(a.rehearsal_T), extra_files=extra)
    except LateSnapshotError as e:
        logger.error("refusing: %s", e); return 5
    logger.info("froze v4 %s: %d rows, %d at >= %.2f, print filings in universe %d, trained in %.0fs", snap, len(preds), len(hc),
                lock["high_confidence"]["threshold"], meta["filed_today_in_universe"], _time.time() - t0)
    return 0


def cmd_grade(a) -> int:
    from .backtest import corporate_actions_from_archive, suspected_actions

    panel, _, _ = _load(a.exports)
    _, known = corporate_actions_from_archive(pd.read_csv(a.ca_csv))
    excl = pd.concat([known, suspected_actions(panel, known)], ignore_index=True)
    graded = pending = 0
    for snap in sorted(p for p in Path(a.root).iterdir() if p.is_dir()):
        if (snap / "graded.csv").exists():
            continue
        out = grade_v4(snap, panel, excl)
        if out is None:
            pending += 1
        else:
            graded += 1
            logger.info("graded v4 %s: %d rows, %d events", snap.name, out["y"].notna().sum(), int(out["y"].sum()))
    logger.info("v4 graded %d, still waiting for bars %d", graded, pending)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("score", "grade"):
        p = sub.add_parser(name)
        p.add_argument("--exports", type=Path, required=True); p.add_argument("--ca-csv", type=Path, required=True); p.add_argument("--root", type=Path, required=True)
        if name == "score":
            p.add_argument("--store-v3", type=Path, required=True); p.add_argument("--live-dir", type=Path, required=True)
            p.add_argument("--workers", type=int, default=3); p.add_argument("--rehearsal-T", default=None)
            p.add_argument("--preview", action="store_true", help="real-clock snapshot that never counts toward the verdict (use a separate --root)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return cmd_score(a) if a.cmd == "score" else cmd_grade(a)


if __name__ == "__main__":
    raise SystemExit(main())
