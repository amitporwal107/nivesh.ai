"""Frozen inputs of the simulation framework (PRD §4). Every file is checked against its recorded sha256 before use;
the bars go through the same block-guarded path as the H#32 dataset build, plus a raw read that keeps duplicates so the
data-quality report can count them (dataset.load_bars drops them silently)."""
from __future__ import annotations

import glob
import hashlib
import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
MV5 = os.path.normpath(os.path.join(HERE, "..", "model_v5"))
sys.path.insert(0, MV5)
import dataset as DS  # noqa: E402
import walkforward as WF  # noqa: E402

DATA = DS.OUT                                          # /app/research/model_v5 (outputs are not in git)
RESULTS = "dev_results_20260919T214001.json"
PICKS = "dev_picks_M8_20260919T214001.csv"
PICKS_SHA256 = "d05cccc241be6a55217b2557dc82657befd1420894b8e5c339f387caa0d3281b"   # recorded 2026-09-20 (not in the results file)
MODEL, LABEL = "M8", "tbs_5_2"
LEDGER_SCORES = (("M8", "tbs_5_2"), ("M8", "dir_5_5d"), ("M4", "hit_high_10_5d"))
DEV = DS.BLOCKS["dev"]
YEAR_START = pd.Timestamp(WF.FOLDS[0][1])              # 2022-01-01: the out-of-fold predictions start here


class InputError(RuntimeError):
    pass


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verified(path: str, expected: str) -> str:
    got = sha256(path)
    if got != expected:
        raise InputError(f"{os.path.basename(path)}: sha256 {got} != frozen {expected}")
    return path


def prediction_id(commit: str, model: str, label: str, date, symbol: str, score: float) -> str:
    key = "|".join([commit, model, label, pd.Timestamp(date).date().isoformat(), symbol, repr(float(score))])
    return hashlib.sha256(key.encode()).hexdigest()


def load_frozen(data: str = DATA) -> dict:
    res = json.load(open(os.path.join(data, RESULTS)))
    ds_path = verified(os.path.join(data, res["dataset"]), res["dataset_sha256"])
    oof_path = verified(os.path.join(data, res["oof_file"]), res["oof_sha256"])
    picks_path = verified(os.path.join(data, PICKS), PICKS_SHA256)
    iso_path = verified(os.path.join(res["models_dir"], f"iso__{MODEL}__{LABEL}.pkl"),
                        res["model_files"][f"iso__{MODEL}__{LABEL}.pkl"])
    ds = WF.load(ds_path)
    # round_trip: pandas' default float parser can be one ulp off, which changes stored scores and tie draws
    oof = pd.read_csv(oof_path, parse_dates=["date"], float_precision="round_trip")
    key = ds[["date", "symbol"]].reset_index().rename(columns={"index": "row"})
    m = oof.merge(key, on=["date", "symbol"], how="left", validate="1:1")
    if m.row.isna().any():
        raise InputError(f"{int(m.row.isna().sum())} out-of-fold rows have no dataset row")
    scores = m.set_index(m.row.astype(int)).drop(columns=["row", "date", "symbol"]).sort_index()
    picks = pd.read_csv(picks_path, index_col=0, parse_dates=["date"], float_precision="round_trip")
    with open(iso_path, "rb") as fh:
        iso = pickle.load(fh)
    cal, idx_close = DS.load_calendar(DEV)
    return {"results": res, "ds": ds, "scores": scores, "picks": picks, "iso": iso, "cal": cal, "idx_close": idx_close,
            "commit": res["code_commit"],
            "files": {os.path.basename(p): sha256(p) for p in (ds_path, oof_path, picks_path, iso_path)}}


def predictions_ledger(ds: pd.DataFrame, scores: pd.DataFrame, commit: str) -> pd.DataFrame:
    """One immutable row per (model, label, date, symbol) score used by the framework."""
    parts = []
    for model, label in LEDGER_SCORES:
        s = scores[f"{model}|{label}"].dropna()
        d = ds.loc[s.index, ["date", "symbol"]]
        parts.append(pd.DataFrame({"row": s.index, "date": d.date.to_numpy(), "symbol": d.symbol.to_numpy(), "model": model,
                                   "label": label, "score": s.to_numpy(float)}))
    out = pd.concat(parts, ignore_index=True)
    out["prediction_id"] = [prediction_id(commit, m, lb, d, sy, sc)
                            for m, lb, d, sy, sc in zip(out.model, out.label, out.date, out.symbol, out.score)]
    return out


def universe_isin(path: str = DS.N500) -> pd.DataFrame:
    n = pd.read_csv(path).rename(columns={"Symbol": "symbol", "Industry": "industry", "ISIN Code": "isin"})
    uni, _ = DS.universe(path)
    return uni.merge(n[["symbol", "isin"]], on="symbol", how="left", validate="1:1")


def load_bars_raw(symbols: set, block=DEV, pattern: str = DS.DAILY) -> pd.DataFrame:
    """The same files and cut as dataset.load_bars, but duplicates are kept (file order preserved) and the instrument
    token is read, so the data-quality report can count duplicates and check one instrument per symbol."""
    end = pd.Timestamp(block.bar_end)
    parts = []
    for f in sorted(glob.glob(pattern)):
        cols = ["symbol", "instrument_token", "date", "open", "high", "low", "close", "volume"]
        for ch in pd.read_csv(f, usecols=cols, chunksize=1_000_000):
            ch = ch[ch.symbol.isin(symbols)]
            ch = ch.assign(date=pd.to_datetime(ch.date.astype(str).str[:10]))
            ch = ch[ch.date <= end]
            if len(ch):
                parts.append(ch.assign(source_file=os.path.basename(f)))
    d = pd.concat(parts, ignore_index=True)
    DS.guard_bars(d.date, block)
    return d


def bars_like_dataset(raw: pd.DataFrame, cal: pd.DatetimeIndex) -> pd.DataFrame:
    """Exactly the dataset build's bars: first occurrence per (symbol, date), sorted, calendar dates only, prepared."""
    d = raw.drop_duplicates(["symbol", "date"]).sort_values(["symbol", "date"]).reset_index(drop=True)
    d = d[["symbol", "date", "open", "high", "low", "close", "volume"]]
    return DS.prepare(d[d.date.isin(cal)])


def check_bars_match_dataset(bars: pd.DataFrame, ds: pd.DataFrame) -> dict:
    """D1 consistency: the re-read bars reproduce the dataset's close, value20 and s1 entry open for every row."""
    m = ds[["date", "symbol", "close", "value20", "entry_date", "entry_px"]].merge(
        bars[["date", "symbol", "close", "value20"]], on=["date", "symbol"], how="left", suffixes=("", "_bars"))
    s1 = bars[["date", "symbol", "open"]].rename(columns={"date": "entry_date", "open": "s1_open"})
    m = m.merge(s1, on=["entry_date", "symbol"], how="left")
    ok_px = m.entry_px.isna() | np.isclose(m.entry_px, m.s1_open, rtol=0, atol=1e-9)
    out = {"rows": int(len(m)), "missing_bar": int(m.close_bars.isna().sum()),
           "close_mismatch": int((~np.isclose(m.close, m.close_bars, rtol=0, atol=1e-9)).sum()),
           "value20_mismatch": int((~np.isclose(m.value20, m.value20_bars, rtol=1e-12, atol=1e-6, equal_nan=True)).sum()),
           "entry_open_mismatch": int((~ok_px).sum())}
    out["pass"] = out["missing_bar"] == out["close_mismatch"] == out["value20_mismatch"] == out["entry_open_mismatch"] == 0
    return out
