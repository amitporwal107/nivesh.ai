"""Random-entry control (PREREGISTRATION.md §6.1): on each session where the arm had filled entries, enter the same
number of randomly chosen eligible stocks not already held by the arm's own picks that day, by the same entry mechanism
(E1's buy-stop becomes MOO on its fill session), with the arm's own structural-stop formula, exits, sizing and config.
Seeds 1..200. The control's signal day is the session before the fill for next-open arms and the fill session itself
for the close-entry arms, so its stop uses only data known at that time."""
from __future__ import annotations

import numpy as np
import pandas as pd

import signals as S

STOP_FORMULA = {  # arm -> (ref column, structural stop) on the control's signal day
    "E1": lambda r: r.low10,
    "E2": lambda r: r.low5 - 0.5 * r.atr14,
    "E3": lambda r: r.close - 2 * r.atr14,
    "D1": lambda r: r.close - 2 * r.atr14,
    "C-E2": lambda r: r.low5 - 0.5 * r.atr14,
    "C-E3": lambda r: r.close - 2 * r.atr14,
}


def random_signals(arm: str, arm_trades: pd.DataFrame, panel: pd.DataFrame, sessions: list, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close_entry = arm.startswith("C-")
    pos = {d: i for i, d in enumerate(sessions)}
    by_day = {d: g for d, g in panel[panel.eligible].groupby(panel.date.dt.date)}
    filled = arm_trades[arm_trades.realised | (arm_trades.exit_reason == "OPEN_AT_END")]
    out = []
    for fill_day, grp in filled.groupby("entry_date"):
        sig_day = fill_day if close_entry else sessions[pos[fill_day] - 1] if pos.get(fill_day, 0) > 0 else None
        if sig_day is None or sig_day not in by_day:
            continue
        cand = by_day[sig_day]
        cand = cand[~cand.symbol.isin(set(grp.symbol))]
        n = min(len(grp), len(cand))
        pick = cand.iloc[rng.choice(len(cand), size=n, replace=False)] if n else cand.iloc[:0]
        for r in pick.itertuples(index=False):
            stop = float(S.clamp_stop(STOP_FORMULA[arm](r), r.close))
            out.append({"signal_id": f"R{seed}-{arm}-{r.symbol}-{sig_day:%Y%m%d}", "date": sig_day, "symbol": r.symbol,
                        "arm": f"RANDOM-{arm}", "order_type": "MOC" if close_entry else "MOO", "trigger": np.nan,
                        "valid_sessions": 1, "stop": stop, "reference_price": r.close, "atr": r.atr14,
                        "rank": float(rng.random())})
    s = pd.DataFrame(out)
    return s[np.isfinite(s.stop) & np.isfinite(s.atr)].reset_index(drop=True) if len(s) else s
