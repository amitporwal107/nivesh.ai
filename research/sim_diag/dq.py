"""Per-session data-quality report (PRD §8). A session FAILS on any integrity, duplicate, instrument-mapping or
feature-cutoff violation; corporate-action, circuit, volume and special-session findings are flags (PASS_WITH_FLAGS).
Nothing is removed here: every exclusion elsewhere carries its reason, and the report lists them.

Circuit flags use the same bands as execution.py (2/5/10/20%, 0.25pp) on floats; a flag is a prompt for review, while
fills use the Decimal functions. The heuristic's known false positive: a stock that opens exactly at a band and never
trades beyond it is flagged as locked."""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

import inputs as IN
from candidates import ineligible_reason

SPECIAL_SESSIONS = {pd.Timestamp("2021-11-04"): "DIWALI_MUHURAT", pd.Timestamp("2022-10-24"): "DIWALI_MUHURAT"}
BANDS = np.array([0.02, 0.05, 0.10, 0.20])
BAND_TOL = 0.0025
CA_MOVE, CA_VOLUME_X, GAP, LOW_VOLUME = 0.20, 10.0, 0.20, 0.05
FEATURE_TOL = 1e-12                                     # relative; the dataset CSV stores floats at full precision
FLAG_COLS = ["ca_move", "ca_volume", "gap20", "vol_zero", "vol_low", "locked_open_up", "locked_open_down",
             "locked_close_up", "locked_close_down"]


def _at_band(x: pd.Series, sign: int) -> pd.Series:
    return pd.Series(np.any(np.abs(x.to_numpy()[:, None] - sign * BANDS[None, :]) <= BAND_TOL, axis=1), index=x.index)


def bar_flags(bars: pd.DataFrame) -> pd.DataFrame:
    """One row per prepared bar: integrity failure and each review flag."""
    d = bars
    f = pd.DataFrame({"symbol": d.symbol, "date": d.date})
    f["ohlc_invalid"] = ~((d.high >= d[["open", "close"]].max(axis=1)) & (d.low <= d[["open", "close"]].min(axis=1)) &
                          (d[["open", "high", "low", "close"]] > 0).all(axis=1))
    move = d.close / d.prev_close - 1
    gap = d.open / d.prev_close - 1
    f["ca_move"] = move.abs() > CA_MOVE
    f["ca_volume"] = d.volume > CA_VOLUME_X * d.vol_med20
    f["gap20"] = gap.abs() > GAP
    f["vol_zero"] = d.volume.isna() | (d.volume <= 0)
    f["vol_low"] = d.volume < LOW_VOLUME * d.vol_med20
    has_pc = d.prev_close.notna() & (d.prev_close > 0)
    f["locked_open_up"] = has_pc & (d.open == d.high) & _at_band(gap.fillna(9), +1)
    f["locked_open_down"] = has_pc & (d.open == d.low) & _at_band(gap.fillna(9), -1)
    f["locked_close_up"] = has_pc & (d.close == d.high) & _at_band(move.fillna(9), +1)
    f["locked_close_down"] = has_pc & (d.close == d.low) & _at_band(move.fillna(9), -1)
    f["special_session"] = d.date.map(SPECIAL_SESSIONS)
    f["any_flag"] = f[FLAG_COLS].any(axis=1) | f.special_session.notna()
    return f


def raw_checks(raw: pd.DataFrame, cal: pd.DatetimeIndex) -> dict:
    """Checks only a raw read can make: duplicates (exact vs conflicting), off-calendar bars, one instrument per symbol."""
    key = ["symbol", "date"]
    dup = raw[raw.duplicated(key, keep=False)]
    px = ["open", "high", "low", "close", "volume"]
    conflicting = dup.groupby(key)[px].nunique().gt(1).any(axis=1) if len(dup) else pd.Series(dtype=bool)
    tokens = raw.groupby("symbol").instrument_token.nunique()
    return {"rows": int(len(raw)), "duplicate_rows": int(len(dup)), "duplicate_keys": int(dup[key].drop_duplicates().shape[0]),
            "conflicting_duplicate_keys": int(conflicting.sum()),
            "duplicate_dates": sorted({str(x.date()) for x in dup.date}),
            "off_calendar_bars": int((~raw.date.isin(cal)).sum()),
            "off_calendar_dates": sorted({str(x.date()) for x in raw.date[~raw.date.isin(cal)]})[:50],
            "symbols_with_several_instruments": sorted(tokens[tokens > 1].index)}


def missing_table(bars: pd.DataFrame, uni: pd.DataFrame, dates) -> pd.DataFrame:
    """Universe symbols without a bar on each date: MISSING (listed by then) or NOT_YET_LISTED / NO_DATA."""
    first = bars.groupby("symbol").date.min()
    have = set(zip(bars.symbol, bars.date))
    rows = []
    for d in dates:
        for s in uni.symbol:
            if (s, d) in have:
                continue
            kind = "NO_DATA" if s not in first.index else ("NOT_YET_LISTED" if first[s] > d else "MISSING")
            rows.append((d, s, kind))
    return pd.DataFrame(rows, columns=["date", "symbol", "kind"])


def feature_cutoff(bars: pd.DataFrame, cal: pd.DatetimeIndex, members: set, ds: pd.DataFrame, T: pd.Timestamp) -> dict:
    """Recomputes the 44 features of every symbol on T from bars CUT at T and compares them with the dataset: equality
    proves no bar after T entered the stored features (the future-shock test)."""
    from nidp.services.tpd_model.features_v4 import compute_features_v4
    panel = IN.DS.to_panel(bars[bars.date <= T])
    D = cal[cal.get_loc(T) + 1]
    f = compute_features_v4(panel, T.date(), financials=None, target_session=D.date(), market_members=members)
    f = f[list(IN.DS.FEATURES)]
    stored = ds[ds.date == T].set_index("symbol")[list(IN.DS.FEATURES)]
    common = stored.index.intersection(f.index)
    a, b = f.loc[common].to_numpy(float), stored.loc[common].to_numpy(float)
    both_nan = np.isnan(a) & np.isnan(b)
    diff = np.where(both_nan, 0.0, np.abs(a - b) / np.maximum(1.0, np.abs(b)))
    diff = np.where(np.isnan(diff), np.inf, diff)                     # NaN on one side only is a violation
    bad = diff > FEATURE_TOL
    worst = []
    for i, j in zip(*np.nonzero(bad)):
        worst.append({"symbol": common[i], "feature": IN.DS.FEATURES[j], "recomputed": float(a[i, j]), "stored": float(b[i, j])})
    return {"date": str(T.date()), "symbols_compared": int(len(common)), "symbols_only_stored": int(len(stored.index.difference(f.index))),
            "values_compared": int(a.size), "violations": int(bad.sum()), "max_rel_diff": float(diff.max()) if diff.size else 0.0,
            "examples": worst[:10]}


def session_report(D: pd.Timestamp, flags: pd.DataFrame, missing: pd.DataFrame, raw_dups: pd.DataFrame, uni: pd.DataFrame,
                   ds_day: pd.DataFrame, trade_bars: pd.DataFrame, picks_day: pd.DataFrame, cutoff: dict | None,
                   instrument_conflicts: list, store) -> dict:
    """The owner's per-session block. `trade_bars` = (symbol, date) of every bar the day's trades used."""
    uni_syms = set(uni.symbol)
    day = flags[(flags.date == D) & flags.symbol.isin(uni_syms)]
    tb = flags.merge(trade_bars, on=["symbol", "date"], how="inner")
    miss = missing[missing.date == D]
    dups_d = raw_dups[raw_dups.date == D]
    fails = []
    ohlc_bad = sorted(set(day.symbol[day.ohlc_invalid]) | set(tb.symbol[tb.ohlc_invalid]))
    if ohlc_bad:
        fails.append(f"OHLC_INVALID:{','.join(ohlc_bad)}")
    if len(dups_d):
        fails.append(f"DUPLICATE_BARS:{dups_d.symbol.nunique()}")
    inst = sorted(set(instrument_conflicts) & uni_syms)
    if inst:
        fails.append(f"SEVERAL_INSTRUMENTS:{','.join(inst)}")
    no_isin = sorted(uni.symbol[uni.isin.isna()])
    if no_isin:
        fails.append(f"NO_ISIN:{','.join(no_isin)}")
    if cutoff is not None and cutoff["violations"]:
        fails.append(f"FEATURE_CUTOFF:{cutoff['violations']}")
    flag_lists = {c: sorted(day.symbol[day[c]]) for c in FLAG_COLS}
    trade_flags = {c: sorted({f"{s}@{d.date()}" for s, d in zip(tb.symbol[tb[c]], tb.date[tb[c]])}) for c in FLAG_COLS}
    special = SPECIAL_SESSIONS.get(D)
    special_in_trades = sorted({str(d.date()) for d in tb.date if d in SPECIAL_SESSIONS})
    opens = []
    for _, p in picks_day.iterrows():
        s1 = store.sessions_after(D, 1)
        b = store.row(p.symbol, s1[0]) if s1 else None
        st = "NO_BAR_S1" if b is None else ("LOCKED_UPPER_OPEN" if p.entry_status == "LOCKED_UPPER_OPEN" else "OK")
        opens.append({"symbol": p.symbol, "s1": str(s1[0].date()) if s1 else None, "status": st})
    elig = ds_day[~ds_day.eligible.astype(bool)]
    reasons = pd.Series([ineligible_reason(h, v, c) for h, v, c in zip(elig.hist_n, elig.value20, elig.close)], dtype=object)
    has_flag = any(flag_lists.values()) or any(trade_flags.values()) or special or special_in_trades
    status = "FAIL" if fails else ("PASS_WITH_FLAGS" if has_flag else "PASS")
    return {
        "date": str(D.date()), "status": status, "fail_reasons": fails,
        "special_session": special, "special_sessions_in_trade_windows": special_in_trades,
        "universe": int(len(uni_syms)), "bars_on_date": int(len(day)),
        "valid_bar_pct": float(100 * (1 - day.ohlc_invalid.mean())) if len(day) else None,
        "missing": sorted(miss.symbol[miss.kind == "MISSING"]), "not_yet_listed": int((miss.kind == "NOT_YET_LISTED").sum()),
        "no_data": sorted(miss.symbol[miss.kind == "NO_DATA"]),
        "duplicate_bar_symbols": sorted(dups_d.symbol.unique()),
        "flags_universe": {k: v for k, v in flag_lists.items() if v},
        "flags_trade_bars": {k: v for k, v in trade_flags.items() if v},
        "trade_bars_checked": int(len(tb)), "trade_bars_expected": int(len(trade_bars)),
        "feature_cutoff": cutoff, "open_availability": opens,
        "exclusions": {"not_eligible": {k: int(v) for k, v in reasons.value_counts().items()},
                       "eligible": int(ds_day.eligible.astype(bool).sum()), "rows": int(len(ds_day)),
                       "top5_without_entry": [o for o in opens if o["status"] != "OK"]},
    }
