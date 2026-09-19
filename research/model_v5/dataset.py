"""Roadmap v2 Phases 2-3 dataset builder (docs/ai_research/tpd3/model_v5/PREREGISTRATION_P2_P3.md, FROZEN at 50fe02fd).
One row per (symbol, decision day D) with a Kite bar on D inside the block's feature dates: the 44 v4 features at the
close of D (computed by the v4 code itself, `tpd_model.features_v4`), the §4 labels over s1..s5, eligibility, the
entry status and the columns the §7 evaluation needs.

Period guards (§2, §9): bars are cut at the block's last label date as each chunk is read and the result is asserted;
every label asserts that the bars it read end on or before that date; the test block refuses to build unless the
commit that froze the models is supplied. Output files are written outside git (OUT) with a sha256 manifest.

Readings of the frozen text (also in labels.py, recorded in RESULTS.md):
- Data are Kite's split/bonus/dividend-adjusted bars, so the v4 corporate-action step gets no actions, `close_raw`
  is the adjusted close and turnover = adjusted close x adjusted volume.
- mkt_ret1/breadth are measured over the universe (current Nifty 500 minus ETFs), the v4 `market_members` argument.
- The NSE calendar is the Nifty 500 index's Kite session list for the block.
run (from this directory): /app/research/tpd3_forward/venv/bin/python dataset.py dev
"""
from __future__ import annotations

import datetime as dt
import glob
import hashlib
import json
import multiprocessing as mp
import os
import subprocess
import sys
import warnings
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.normpath(os.path.join(HERE, "..", "..", "backend"))
sys.path.insert(0, BACKEND)
sys.path.insert(0, HERE)

from nidp.services.tpd_model.features import MARKET_FEATURES, PRICE_FEATURES  # noqa: E402
from nidp.services.tpd_model.features_v4 import compute_features_v4  # noqa: E402
from nidp.services.tpd_model.risk import costs as CC  # noqa: E402
from nidp.services.tpd_model.risk.execution import Bar, locked_upper  # noqa: E402
from nidp.services.tpd_model.technical_ext import TECHNICAL_EXT_FEATURES  # noqa: E402

import labels as LB  # noqa: E402

DAILY = "/app/research/kite_history/day_2021/part-*.csv.gz"
N500 = "/app/research/screener/ref/ind_nifty500list.csv"
OUT = "/app/research/model_v5"
FEATURES = PRICE_FEATURES + TECHNICAL_EXT_FEATURES + MARKET_FEATURES          # §5: 25 + 17 + 2 = 44
COST_MODEL = "zerodha-equity-v1"
SLIPPAGE_SCENARIOS = {"opt": Decimal("0.5"), "base": Decimal("1"), "cons": Decimal("2")}
MIN_HISTORY, MIN_VALUE20, MIN_CLOSE = 60, 5e7, 50.0


class SealedDataError(RuntimeError):
    """A bar or label date outside the block, or the test block without frozen models."""


@dataclass(frozen=True)
class Block:
    name: str
    feat_start: dt.date
    feat_end: dt.date
    bar_end: dt.date                 # the last date any bar may carry (labels complete by then)
    index_blocks: tuple              # index_{name}.csv files that form the calendar


BLOCKS = {
    "dev": Block("dev", dt.date(2021, 1, 1), dt.date(2022, 12, 22), dt.date(2022, 12, 30), ("dev",)),
    "test": Block("test", dt.date(2023, 1, 2), dt.date(2024, 7, 24), dt.date(2024, 7, 31), ("dev", "test")),
}


def check_block(block: Block, frozen_commit: Optional[str]) -> None:
    if block.name != "dev" and not frozen_commit:
        raise SealedDataError(f"the {block.name} block may be built only after the models are frozen (pass the commit)")


def guard_bars(dates: pd.Series, block: Block, what: str = "bars") -> None:
    if len(dates) and pd.Timestamp(dates.max()) > pd.Timestamp(block.bar_end):
        raise SealedDataError(f"{what} dated {pd.Timestamp(dates.max()).date()} is after the {block.name} block end {block.bar_end}")


def universe(path: str = N500) -> tuple[pd.DataFrame, list]:
    """§3: current Nifty 500 members minus ETFs (name contains 'ETF', or an ETF-type symbol)."""
    n = pd.read_csv(path).rename(columns={"Symbol": "symbol", "Company Name": "name", "Industry": "industry"})
    etf = n.name.str.upper().str.contains("ETF") | n.symbol.str.upper().str.contains("ETF|BEES")
    return n.loc[~etf, ["symbol", "name", "industry"]].reset_index(drop=True), sorted(n.loc[etf, "symbol"])


def load_bars(symbols: set, block: Block, pattern: str = DAILY) -> pd.DataFrame:
    """Kite daily bars for `symbols`, cut at the block end as each chunk is read (nothing later is kept)."""
    end = pd.Timestamp(block.bar_end)
    parts = []
    for f in sorted(glob.glob(pattern)):
        for ch in pd.read_csv(f, usecols=["symbol", "date", "open", "high", "low", "close", "volume"], chunksize=1_000_000):
            ch = ch[ch.symbol.isin(symbols)]
            ch = ch.assign(date=pd.to_datetime(ch.date.astype(str).str[:10]))
            ch = ch[ch.date <= end]
            if len(ch):
                parts.append(ch)
    d = pd.concat(parts).drop_duplicates(["symbol", "date"]).sort_values(["symbol", "date"]).reset_index(drop=True)
    guard_bars(d.date, block)
    return d


def load_calendar(block: Block, out: str = OUT) -> tuple[pd.DatetimeIndex, pd.Series]:
    x = pd.concat([pd.read_csv(os.path.join(out, f"index_{b}.csv")) for b in block.index_blocks])
    x = x[x["index"] == "NIFTY 500"].assign(date=lambda y: pd.to_datetime(y.date)).drop_duplicates("date").sort_values("date")
    guard_bars(x.date, block, "index bars")
    return pd.DatetimeIndex(x.date), pd.Series(x.close.to_numpy(), index=pd.DatetimeIndex(x.date))


def prepare(bars: pd.DataFrame) -> pd.DataFrame:
    """Eligibility inputs at the close of each bar (same definitions as the positional study)."""
    d = bars.sort_values(["symbol", "date"]).reset_index(drop=True)
    g = d.groupby("symbol", sort=False)
    d["prev_close"] = g.close.shift(1)
    d["hist_n"] = g.cumcount()
    d["value20"] = (d.close * d.volume).groupby(d.symbol, sort=False).transform(lambda s: s.rolling(20).mean())
    d["eligible"] = (d.hist_n >= MIN_HISTORY) & (d.value20 >= MIN_VALUE20) & (d.close >= MIN_CLOSE)
    return d


def to_panel(bars: pd.DataFrame) -> pd.DataFrame:
    """The v4 panel schema (tpd_model conftest): delivery is not in the Kite data, so deliverable_pct is NaN."""
    return pd.DataFrame({
        "symbol": bars.symbol.to_numpy(), "as_of_date": pd.to_datetime(bars.date).to_numpy(), "series": "EQ", "source": "kite",
        "open": bars.open.to_numpy(float), "high": bars.high.to_numpy(float), "low": bars.low.to_numpy(float),
        "close": bars.close.to_numpy(float), "prev_close": bars.prev_close.to_numpy(float),
        "volume": bars.volume.to_numpy(float), "turnover": (bars.close * bars.volume).to_numpy(float),
        "deliverable_pct": np.nan,
    })


def _dec(x) -> Decimal:
    return Decimal(repr(float(x)))          # repr(np.float64) is 'np.float64(...)' under numpy 2


def _window(bars: pd.DataFrame, cal: pd.DatetimeIndex, rows: pd.DataFrame, col: str) -> np.ndarray:
    """(n, 5) array of `col` on the five calendar sessions after each row's date; NaN where the stock has no bar."""
    wide = bars.pivot(index="symbol", columns="date", values=col).reindex(columns=cal)
    si = wide.index.get_indexer(rows.symbol)
    ci = cal.get_indexer(rows.date)
    return wide.to_numpy(float)[si[:, None], ci[:, None] + np.arange(1, LB.SESSIONS + 1)]


def build_labels(bars: pd.DataFrame, cal: pd.DatetimeIndex, block: Block, cost_model) -> pd.DataFrame:
    guard_bars(bars.date, block)
    guard_bars(pd.Series(cal), block, "calendar")
    lo, hi = pd.Timestamp(block.feat_start), pd.Timestamp(block.feat_end)
    rows = bars[(bars.date >= lo) & (bars.date <= hi)].reset_index(drop=True)
    pos = cal.get_indexer(rows.date)
    if (pos < 0).any():
        raise ValueError(f"{int((pos < 0).sum())} bars fall on dates missing from the calendar")
    if len(rows) and pos.max() + LB.SESSIONS >= len(cal):
        raise SealedDataError("a label window runs past the end of the block calendar")
    last_read = cal[pos + LB.SESSIONS]
    guard_bars(pd.Series(last_read), block, "a label window")

    O, H, L, C = (_window(bars, cal, rows, c) for c in ("open", "high", "low", "close"))
    entry = O[:, 0]
    status = np.where(np.isnan(entry), "NO_BAR_S1", "OK").astype(object)
    ok_idx = np.flatnonzero(status == "OK")
    for i in ok_idx:
        b = Bar(*(_dec(x) for x in (entry[i], H[i, 0], L[i, 0], C[i, 0])), 1, _dec(rows.close.iat[i]))
        if locked_upper(b):
            status[i] = "LOCKED_UPPER_OPEN"
    ok = status == "OK"
    out = rows[["symbol", "date", "close", "hist_n", "value20", "eligible"]].copy()
    out["entry_status"] = status
    out["entry_date"] = cal[pos + 1]
    out["label_end_date"] = last_read
    out["entry_px"] = np.where(ok, entry, np.nan)
    out["gap_s1"] = np.where(ok, entry / rows.close.to_numpy(float) - 1, np.nan)

    e = np.where(ok, entry, np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)          # all-NaN windows of rows without an entry
        lab = {
            "hit_high_5_1d": LB.hit_high(e, H, 1.05, 1), "hit_high_5_3d": LB.hit_high(e, H, 1.05, 3),
            "hit_high_5_5d": LB.hit_high(e, H, 1.05, 5), "hit_high_10_5d": LB.hit_high(e, H, 1.10, 5),
            "hit_low_10_5d": LB.hit_low(e, L, 0.90, 5),
            "hit_close_5_5d": LB.hit_close(e, C, 1.05, 5), "hit_close_10_5d": LB.hit_close(e, C, 1.10, 5),
        }
    for k, v in lab.items():
        out[k] = np.where(ok, v, np.nan)
    for name, (tm, sm) in (("tbs_5_2", (1.05, 0.98)), ("tbs_10_4", (1.10, 0.96))):
        t = LB.target_before_stop(e, O, H, L, C, tm, sm)
        out[name] = np.where(ok, t["outcome"], None)
        out[f"{name}_exit_px"] = np.where(ok, t["exit_px"], np.nan)
        out[f"{name}_exit_date"] = pd.DatetimeIndex([cal[p + 1 + k] if good else pd.NaT
                                                     for p, k, good in zip(pos, t["exit_k"], ok)])
    out["gross_ret_5_2"] = out.tbs_5_2_exit_px / out.entry_px - 1
    out["dir_5_5d"] = np.where(ok, LB.direction(e, H, L), None)

    tradable = ok & out.eligible.to_numpy(bool)
    slip = {i: CC.slippage_pct(cost_model, float(out.value20.iat[i])) for i in np.flatnonzero(tradable)}
    out["slip_pct"] = [float(slip[i]) if i in slip else np.nan for i in range(len(out))]
    for tag, mult in SLIPPAGE_SCENARIOS.items():
        col = "net_ret_5_2" if tag == "base" else f"net_ret_5_2_{tag}"
        vals = np.full(len(out), np.nan)
        for i, s in slip.items():
            vals[i] = LB.net_return(out.entry_px.iat[i], out.tbs_5_2_exit_px.iat[i], s * mult, cost_model, CC.fill_costs,
                                    out.entry_date.iat[i].date(), out.tbs_5_2_exit_date.iat[i].date())
        out[col] = vals
    out["net_pos_5_2"] = np.where(np.isnan(out.net_ret_5_2), np.nan, (out.net_ret_5_2 > 0).astype(float))
    return out


_G: dict = {}


def _features_on(T: pd.Timestamp) -> pd.DataFrame:
    cal = _G["cal"]
    D = cal[cal.get_loc(T) + 1]
    f = compute_features_v4(_G["panel"], T.date(), financials=None, target_session=D.date(), market_members=_G["members"])
    return f[list(FEATURES)].reset_index().assign(date=T)


def build_features(panel: pd.DataFrame, cal: pd.DatetimeIndex, block: Block, members: set, workers: int = 3) -> pd.DataFrame:
    """The 44 v4 features for every symbol with a bar on each session T of the block's feature dates. The v4 code
    itself cuts the panel at T, so the pool may share the whole (already block-guarded) panel."""
    guard_bars(panel.as_of_date, block, "panel")
    days = [T for T in cal if block.feat_start <= T.date() <= block.feat_end]
    _G.update(panel=panel, cal=cal, members=members)
    if workers <= 1:
        parts = [_features_on(T) for T in days]
    else:
        with mp.get_context("fork").Pool(workers) as pool:
            parts = list(pool.imap(_features_on, days, chunksize=4))
    return pd.concat(parts, ignore_index=True)[["symbol", "date", *FEATURES]]


def regime(idx_close: pd.Series) -> pd.Series:
    """§7 conditional matrix: Nifty 500 close above its 200-session average (NaN until 200 sessions exist)."""
    ma = idx_close.rolling(200).mean()
    return (idx_close > ma).astype(float).where(ma.notna())


def _git(*args) -> str:
    return subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True, check=True).stdout.strip()


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(block_name: str = "dev", frozen_commit: Optional[str] = None, workers: int = 3, out: str = OUT) -> str:
    block = BLOCKS[block_name]
    check_block(block, frozen_commit)
    dirty = _git("status", "--porcelain", "--", ".", os.path.join(BACKEND, "nidp", "services", "tpd_model"))
    if dirty:
        raise RuntimeError(f"uncommitted changes in the builder or tpd_model; commit first:\n{dirty}")
    commit = _git("rev-parse", "HEAD")
    uni, etfs = universe()
    raw = load_bars(set(uni.symbol), block)
    cal, idx_close = load_calendar(block, out)
    off_cal = int((~raw.date.isin(cal)).sum())          # reported in the manifest, never silently kept
    bars = prepare(raw[raw.date.isin(cal)])
    cm = CC.load_cost_model(COST_MODEL)
    lab = build_labels(bars, cal, block, cm)
    feats = build_features(to_panel(bars), cal, block, set(uni.symbol), workers)
    ds = lab.merge(feats, on=["symbol", "date"], how="left", validate="1:1", indicator=True)
    if (ds._merge != "both").any():
        raise RuntimeError(f"{int((ds._merge != 'both').sum())} rows have labels but no feature row")
    ds = ds.drop(columns="_merge").merge(uni[["symbol", "industry"]], on="symbol", how="left")
    reg = regime(idx_close)
    ds["mkt_above200"] = ds.date.map(reg)

    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    path = os.path.join(out, f"dataset_{block.name}_{stamp}.csv.gz")
    ds.to_csv(path, index=False, compression={"method": "gzip", "mtime": 0})
    manifest = {
        "preregistration": "docs/ai_research/tpd3/model_v5/PREREGISTRATION_P2_P3.md (FROZEN 50fe02fd)",
        "block": block.name, "feature_dates": [str(block.feat_start), str(block.feat_end)], "bar_end": str(block.bar_end),
        "code_commit": commit, "frozen_commit": frozen_commit, "built_at": stamp, "file": os.path.basename(path),
        "sha256": _sha256(path), "rows": int(len(ds)), "symbols": int(ds.symbol.nunique()),
        "sessions": int(ds.date.nunique()), "first_date": str(ds.date.min().date()), "last_date": str(ds.date.max().date()),
        "max_bar_date_read": str(bars.date.max().date()), "max_label_date": str(ds.label_end_date.max().date()),
        "features": list(FEATURES), "etfs_excluded": etfs, "bars_off_calendar_dropped": off_cal,
        "entry_status": ds.entry_status.value_counts().to_dict(), "eligible_rows": int(ds.eligible.sum()),
        "eligible_and_entered": int((ds.eligible & (ds.entry_status == "OK")).sum()),
        "cost_model": COST_MODEL, "costs_retroactive": True, "position_inr": str(LB.POSITION_INR),
    }
    with open(path.replace(".csv.gz", "_manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=1, default=str)
    print(json.dumps({k: manifest[k] for k in ("file", "sha256", "rows", "symbols", "sessions", "first_date", "last_date",
                                               "max_bar_date_read", "max_label_date", "entry_status", "eligible_and_entered")},
                     default=str))
    return path


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "dev")
