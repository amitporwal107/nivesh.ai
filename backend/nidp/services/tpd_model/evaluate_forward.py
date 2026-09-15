"""v2 forward verdict against thresholds_lock_v2_forward.json.

Reads frozen, graded snapshots (verify() first: a tampered snapshot aborts the whole evaluation), ignores
rehearsals, and reports an informational INTERIM read from 60 graded sessions and a verdict only from the locked minimum (250). Written before any real snapshot
had been graded.

    python -m nidp.services.tpd_model.evaluate_forward --root <snapshots> [--out verdict.json]
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .evaluate import _jsonable, calibration_verdict
from .forward import LOCK_V2, verify
from .metrics import (bootstrap_delta_p5, pr_auc, precision_at_k, recall_at_k, roc_auc, sessions_with_hit)
from .report import b3_verdict, load_lock

COMPARATORS = {"atr_only": "p_atr_only", "own_history_only": "p_own_history_only"}


GRADED_FILE = {"v2": "graded.csv", "v3": "graded_v3.csv"}


def load_graded(root: Path, model: str = "v2") -> tuple[pd.DataFrame, pd.DataFrame, int, int]:
    """(graded rows for `model`, baseline rows, rehearsal snapshots ignored, frozen-but-ungraded snapshots)."""
    frames, bases, rehearsals, ungraded = [], [], 0, 0
    graded_name = GRADED_FILE[model]
    for snap in sorted(p for p in Path(root).iterdir() if p.is_dir()):
        manifest = verify(snap)
        if manifest.get("rehearsal"):
            rehearsals += 1
            continue
        if not (snap / graded_name).exists():
            ungraded += 1
            continue
        g = pd.read_csv(snap / graded_name)
        g["target_session"] = pd.Timestamp(manifest["target_session"])
        g["as_of_date"] = pd.Timestamp(manifest["data_as_of"])
        frames.append(g)
        if (snap / "baseline_predictions.csv").exists():
            bases.append(pd.read_csv(snap / "baseline_predictions.csv").assign(target_session=pd.Timestamp(manifest["target_session"])))
    empty = pd.DataFrame(columns=["symbol", "head", "p_tpd3", "p_atr_only", "p_own_history_only", "p_base_rate", "y",
                                  "excluded_reason", "target_session", "as_of_date"])
    graded = pd.concat(frames, ignore_index=True) if frames else empty
    base = pd.concat(bases, ignore_index=True) if bases else pd.DataFrame(columns=["symbol", "p_baseline", "target_session"])
    return graded, base, rehearsals, ungraded


def months_beating(frame: pd.DataFrame, min_sessions: int) -> dict:
    """Calendar months with >= min_sessions graded sessions in which tpd3's AUC beats the best comparator's."""
    out = {"qualifying_months": 0, "beating": 0, "skipped_months": [], "months": {}}
    for month, g in frame.groupby(frame["target_session"].dt.strftime("%Y-%m")):
        if g["target_session"].nunique() < min_sessions:
            out["skipped_months"].append(month)
            continue
        auc = roc_auc(g["y"], g["p_tpd3"])
        best = max(roc_auc(g["y"], g[c]) for c in COMPARATORS.values())
        out["qualifying_months"] += 1
        out["beating"] += int(auc > best)
        out["months"][month] = {"sessions": int(g["target_session"].nunique()), "auc": auc, "best_comparator_auc": best}
    return out


def _summary(frame: pd.DataFrame) -> dict:
    y, p = frame["y"].to_numpy(float), frame["p_tpd3"].to_numpy(float)
    comps = {name: {"auc": roc_auc(y, frame[col]), "pr_auc": pr_auc(y, frame[col])} for name, col in COMPARATORS.items()}
    return {"n": int(len(frame)), "events": int(y.sum()), "base_rate": float(y.mean()), "auc": roc_auc(y, p), "pr_auc": pr_auc(y, p),
            "p5": precision_at_k(frame, "p_tpd3", "y", 5), "p10": precision_at_k(frame, "p_tpd3", "y", 10),
            "p20": precision_at_k(frame, "p_tpd3", "y", 20), "recall20": recall_at_k(frame, "p_tpd3", "y", 20),
            "sessions_top5_hit": sessions_with_hit(frame, "p_tpd3", "y", 5), "comparators": comps}


def _ship_verdict(s: dict, months: dict, lock: dict) -> dict:
    bar = lock["p_down10_1d_ship"]
    best_pr = max(c["pr_auc"] for c in s["comparators"].values())
    mb = bar["months_beating_best_comparator_auc"]
    checks = {
        "auc_min": s["auc"] >= bar["auc_min"],
        "pr_auc_vs_best_comparator": s["pr_auc"] >= bar["pr_auc_vs_best_comparator_min"] * best_pr,
        "p5_vs_base_rate": s["p5"] >= bar["p5_vs_base_rate_min"] * s["base_rate"],
        "months_beating_best_comparator": months["beating"] >= mb["min"],
    }
    return {"pass": bool(all(checks.values())), "checks": {k: bool(v) for k, v in checks.items()}, "months": months}


def _calibration_frame(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.rename(columns={})  # calibration_verdict reads y, p_tpd3, p_base_rate


def _bootstrap_by_week(frame: pd.DataFrame, lock: dict) -> dict:
    """Week-block bootstrap of the pooled p@5 difference, mirroring metrics.bootstrap_delta_p5's month version."""
    cfg = lock["p_up10_1d_vs_fixed_baseline"]["better"]["bootstrap"]
    weekly = frame.assign(week=frame["target_session"].dt.strftime("%G-W%V"))
    top_new = weekly.sort_values(["target_session", "p_tpd3", "symbol"], ascending=[True, False, True], kind="mergesort").groupby("target_session").head(5)
    top_old = weekly.sort_values(["target_session", "p_baseline", "symbol"], ascending=[True, False, True], kind="mergesort").groupby("target_session").head(5)
    n = top_new.groupby("week")["y"].agg(hits="sum", slots="size")
    o = top_old.groupby("week")["y"].agg(hits="sum", slots="size")
    weeks = n.index.intersection(o.index)
    hn, sn, ho, so = (n.loc[weeks, "hits"].to_numpy(float), n.loc[weeks, "slots"].to_numpy(float),
                      o.loc[weeks, "hits"].to_numpy(float), o.loc[weeks, "slots"].to_numpy(float))
    delta = hn.sum() / sn.sum() - ho.sum() / so.sum()
    rng = np.random.default_rng(7)
    draws = rng.integers(0, len(weeks), size=(cfg["resamples"], len(weeks)))
    boot = hn[draws].sum(1) / sn[draws].sum(1) - ho[draws].sum(1) / so[draws].sum(1)
    lo, hi = np.quantile(boot, [(1 - cfg["ci"]) / 2, 1 - (1 - cfg["ci"]) / 2])
    return {"delta": float(delta), "ci_lo": float(lo), "ci_hi": float(hi), "block": cfg["block"], "resamples": cfg["resamples"],
            "weeks": int(len(weeks))}


def evaluate_frames(graded: pd.DataFrame, base: pd.DataFrame, lock_path: Path = LOCK_V2,
                    extra: Optional[dict] = None) -> dict:
    """Judge graded prediction rows against a lock. Forward lock: NOT_EVALUATED / INTERIM / EVALUATED by graded
    sessions. Early-read lock (role early_read_only): NOT_EVALUATED / EARLY_READ — metrics reported, nothing
    ever served, because that read informs but does not decide."""
    lock, sha = load_lock(lock_path)
    labelled = graded[graded["y"].notna()]
    sessions = sorted(labelled["target_session"].dt.date.unique()) if len(labelled) else []
    early = lock.get("role") == "early_read_only"
    out = {"lock_sha256": sha, "lock_role": "early_read_only" if early else "forward", "graded_sessions": len(sessions),
           "first_session": str(sessions[0]) if sessions else None, "last_session": str(sessions[-1]) if sessions else None,
           "regimes": {"required": lock["regimes"]["required"], "note": lock["regimes"]["why"]},
           "policy": lock["failing_head"], **(extra or {})}
    if early:
        interim = need = lock["window"]["min_graded_sessions"]
    else:
        interim = lock["forward_window"]["interim_read_graded_sessions"]
        need = lock["forward_window"]["verdict_min_graded_sessions"]
    if len(sessions) < interim:
        out.update(status="NOT_EVALUATED", reason=f"{len(sessions)} graded sessions < {interim}", heads={}, g_valid=False,
                   exposure_blocked=True)
        return out
    heads = {}
    for head in lock["heads"]:
        h = labelled[labelled["head"] == head]
        s = _summary(h)
        entry = {"summary": s, "calibration": calibration_verdict(h, {"b5_calibration": lock["calibration_both_heads"]})}
        if head == "p_up10_1d":
            both = h.merge(base, on=["symbol", "target_session"], how="inner")
            new_m = {"auc": roc_auc(both["y"], both["p_tpd3"]), "p5": precision_at_k(both, "p_tpd3", "y", 5)}
            base_m = {"auc": roc_auc(both["y"], both["p_baseline"]), "p5": precision_at_k(both, "p_baseline", "y", 5)}
            boot = _bootstrap_by_week(both, lock)
            entry["b3"] = {"rows_compared": int(len(both)), "rows_tpd3": int(len(h)), "tpd3": new_m, "baseline": base_m,
                           "bootstrap": boot, **b3_verdict(new_m, base_m, boot, {"b3_p_up10_1d_vs_fixed_baseline": lock["p_up10_1d_vs_fixed_baseline"]})}
            required = [entry["b3"]["non_inferior"], entry["calibration"]["pass"]]
        else:
            mb = lock["p_down10_1d_ship"]["months_beating_best_comparator_auc"]
            entry["ship"] = _ship_verdict(s, months_beating(h, mb["qualifying_month_min_graded_sessions"]), lock)
            required = [entry["ship"]["pass"], entry["calibration"]["pass"]]
        entry["bars_met"] = bool(all(required))
        entry["served"] = bool(all(required))
        heads[head] = entry
    if early:
        for h in heads.values():
            h["served"] = False
            h["note"] = "early read: informs, does not decide; serving rests with the forward test"
        out.update(status="EARLY_READ", heads=heads, g_valid=False, exposure_blocked=True)
        return out
    if len(sessions) < need:
        # Lock v2.1 interim read: same metrics, but a 60-session window cannot resolve the non-inferiority margin,
        # so nothing is served and there is no verdict until the minimum is reached.
        for h in heads.values():
            h["served"] = False
            h["interim_note"] = f"informational: verdict needs >= {need} graded sessions"
        out.update(status="INTERIM", reason=f"{len(sessions)} graded sessions < {need} (verdict minimum)", heads=heads,
                   g_valid=False, exposure_blocked=True)
        return out
    blocked = not heads[lock["failing_head"]["block_exposure_if_fails"]]["served"]
    out.update(status="EVALUATED", heads=heads, exposure_blocked=blocked, g_valid=not blocked)
    return out


def evaluate_forward(root: Path, expected_sessions: Optional[list[date]] = None, lock_path: Path = LOCK_V2,
                     model: str = "v2") -> dict:
    graded, base, rehearsals, ungraded = load_graded(root, model)
    labelled = graded[graded["y"].notna()]
    sessions = set(labelled["target_session"].dt.date.unique()) if len(labelled) else set()
    return evaluate_frames(graded, base, lock_path, extra={
        "model": model, "rehearsal_sessions_ignored": rehearsals, "frozen_ungraded": ungraded,
        "missing_sessions": [str(d) for d in (expected_sessions or []) if d not in sessions]})


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--model", choices=("v2", "v3"), default="v2")
    a = ap.parse_args(argv)
    v = evaluate_forward(a.root, model=a.model)
    blob = json.dumps(_jsonable(v), indent=1)
    if a.out:
        a.out.write_text(blob)
    print(json.dumps({k: v[k] for k in ("status", "graded_sessions", "exposure_blocked", "g_valid")}, indent=1))


if __name__ == "__main__":
    main()
