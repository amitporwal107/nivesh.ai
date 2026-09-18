"""Inputs of a paper-engine run: frozen prediction sets (forward snapshots, replay walk-forward), Nifty 50 bars and names.

Forward sets are read only through publish.load_publishable (hash-verified; rehearsal, preview and non-counting
snapshots refused). A forward set counts toward the forward evaluation only if the model froze it after the rules were
registered (rules samples.forward).
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from ..design import MODEL_COLUMNS_V4
from ..publish import PublishRefused, load_publishable, manifest_sha
from .engine import PredictionSet

IST = timezone(timedelta(hours=5, minutes=30))
PRINT_CUTOFF = time(20, 30)            # v4 admits results filings broadcast up to 20:30 IST on the prediction date
FEATURE_VERSION = f"v4-{len(MODEL_COLUMNS_V4)}in"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def _cutoff(d: date) -> datetime:
    return datetime.combine(d, PRINT_CUTOFF, tzinfo=IST)


def forward_sets(root: Path, registered_at: datetime) -> tuple[list[PredictionSet], list[dict]]:
    """Every publishable v4 snapshot under `root`, oldest first, and the ones refused (with why)."""
    sets, refused = [], []
    for snap in sorted(p for p in Path(root).iterdir() if p.is_dir() and p.name[:2] == "20"):
        try:
            manifest, preds, _ = load_publishable(snap)
        except (PublishRefused, Exception) as e:           # noqa: BLE001 — every refusal is reported by name
            refused.append({"snapshot": snap.name, "reason": f"{type(e).__name__}: {e}"})
            continue
        wide = preds.pivot(index="symbol", columns="head", values="p_tpd3")
        gen = datetime.fromisoformat(manifest["generated_at"])
        D = date.fromisoformat(manifest["data_as_of"])
        sets.append(PredictionSet(
            sample="forward", prediction_date=D, next_session=date.fromisoformat(manifest["target_session"]), prediction_timestamp=gen,
            data_cutoff=_cutoff(D), model_version=f"v4@{manifest['git_sha'][:7]}", feature_version=FEATURE_VERSION,
            snapshot_sha256=manifest_sha(snap), wide=wide, counts=gen > registered_at,
            meta={"snapshot": str(snap), "fold_month": manifest.get("fold_month"), "universe_size": manifest.get("universe_size"),
                  "rows": manifest.get("rows"), "git_sha": manifest.get("git_sha"), "lock_sha256": manifest.get("lock_sha256")}))
    return sets, refused


def replay_sets(pkl: Path, lock: Path) -> list[PredictionSet]:
    """The v4 early-window walk-forward, one set per as_of_date. The model output was produced retrospectively (the run's
    file time is recorded as prediction_timestamp); each set only used data up to its as_of_date (monthly folds)."""
    df = pd.read_pickle(pkl)
    sha = hashlib.sha256(Path(pkl).read_bytes()).hexdigest()
    lock_sha = hashlib.sha256(Path(lock).read_bytes()).hexdigest()
    made = datetime.fromtimestamp(Path(pkl).stat().st_mtime, IST)
    out = []
    for (T, D), g in df.groupby(["as_of_date", "target_session"], sort=True):
        T, D = pd.Timestamp(T).date(), pd.Timestamp(D).date()
        wide = g.pivot(index="symbol", columns="head", values="p_tpd3")
        out.append(PredictionSet(sample="replay", prediction_date=T, next_session=D, prediction_timestamp=made, data_cutoff=_cutoff(T),
                                 model_version=f"v4-early@{lock_sha[:7]}", feature_version=FEATURE_VERSION, snapshot_sha256=sha,
                                 wide=wide, counts=True, meta={"month": str(g["month"].iloc[0]), "train_start": str(g["train_start"].iloc[0])}))
    return out


def yahoo_nifty(start: date, end: date) -> pd.DataFrame:
    p1 = int(datetime.combine(start - timedelta(days=5), time(0), tzinfo=IST).timestamp())
    p2 = int(datetime.combine(end + timedelta(days=5), time(0), tzinfo=IST).timestamp())
    req = urllib.request.Request(f"{YAHOO}?interval=1d&period1={p1}&period2={p2}", headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        res = json.loads(r.read())["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    rows = []
    for k, ts in enumerate(res.get("timestamp") or []):
        o, c = q["open"][k], q["close"][k]
        if o is None or c is None:
            continue
        rows.append({"as_of_date": pd.Timestamp(datetime.fromtimestamp(ts, IST).date()), "open_price": round(float(o), 2),
                     "close_price": round(float(c), 2), "source": "YAHOO_NSEI"})
    return pd.DataFrame(rows)


def nifty_bars(nse: pd.DataFrame, start: date, end: date, fetch_yahoo: bool) -> pd.DataFrame:
    """NSE's own Nifty 50 rows where present; Yahoo ^NSEI only for dates NSE rows do not cover (rules benchmarks.D)."""
    nse = nse.assign(as_of_date=pd.to_datetime(nse["as_of_date"]))
    have = set(nse["as_of_date"])
    frames = [nse[["as_of_date", "open_price", "close_price", "source"]]]
    if fetch_yahoo and (not have or pd.Timestamp(start) < min(have)):
        y = yahoo_nifty(start, end)
        frames.append(y[~y["as_of_date"].isin(have)])
    out = pd.concat(frames, ignore_index=True)
    out = out[(out["as_of_date"] >= pd.Timestamp(start)) & (out["as_of_date"] <= pd.Timestamp(end))]
    return out.drop_duplicates("as_of_date").set_index("as_of_date").sort_index()
