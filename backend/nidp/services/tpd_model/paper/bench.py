"""Benchmarks A-D (rules_v1.json benchmarks), defined before any analysis. Deterministic: every random draw is seeded
from sha256 of a fixed string, so a re-run selects the same members (TC-P10)."""
from __future__ import annotations

import hashlib
from typing import Optional

import numpy as np
import pandas as pd

from . import sim

BENCHMARKS = ("MODEL", "A_ALL", "A_RANDOM5", "B_MATCHED", "C_MOVEMENT", "D_NIFTY50")
RULES_ID = "paper-v1"


def seed_of(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:16], 16)


def _entered(u: pd.DataFrame) -> pd.Series:
    return u["status"].isin(["ENTERED"])


def members_model(u: pd.DataFrame) -> list[str]:
    return list(u.loc[(u["selection_status"] == "SELECTED") & _entered(u), "symbol"])


def members_a_all(u: pd.DataFrame) -> list[str]:
    return list(u.loc[_entered(u), "symbol"])


def members_a_random5(u: pd.DataFrame, portfolio: str, entry_session: str) -> list[str]:
    pool = sorted(u.loc[_entered(u), "symbol"])
    if len(pool) < 5:
        return pool
    rng = np.random.default_rng(seed_of(f"A|{portfolio}|{entry_session}|{RULES_ID}"))
    return sorted(rng.choice(pool, size=5, replace=False).tolist())


def members_c_movement(u: pd.DataFrame, n: int = 5) -> list[str]:
    """Top n eligible by movement probability (head + opposite head), no direction split; unfilled stay idle like the model."""
    e = u.assign(_mv=u["p_head"] + u["p_opposite"].fillna(0.0))
    top = e.sort_values(["_mv", "symbol"], ascending=[False, True], kind="mergesort").head(n)
    return list(top.loc[_entered(top), "symbol"])


def _feature_frame(u: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=u.index)
    close = u["eligibility"].map(lambda e: e.get("close"))
    to = u["eligibility"].map(lambda e: e.get("med_turnover_20"))
    f["log_atr_pct"] = np.log((u["atr_14"] / close).astype(float).clip(lower=1e-6))
    f["log_close"] = np.log(close.astype(float).clip(lower=1e-6))
    f["log_turnover"] = np.log(to.astype(float).clip(lower=1.0))
    return f


def members_b_matched(u: pd.DataFrame, portfolio: str, entry_session: str) -> list[tuple[str, str]]:
    """(selected symbol, its match) for each entered selected stock, in rank order (rules benchmarks.B_MATCHED)."""
    sel = u[(u["selection_status"] == "SELECTED") & _entered(u)].sort_values("rank")
    cand_all = u[(u["selection_status"] == "NOT_SELECTED") & _entered(u)]
    feats = _feature_frame(u)
    used: set[str] = set()
    pairs = []
    for ix, s in sel.iterrows():
        c = cand_all[~cand_all["symbol"].isin(used)]
        same_sector = c[c["sector"] == s["sector"]]
        if len(same_sector) >= 3:
            c = same_sector
        same_size = c[c["size_group"] == s["size_group"]]
        if len(same_size) >= 3:
            c = same_size
        if c.empty:
            continue
        block = feats.loc[list(c.index) + [ix]]
        z = (block - block.mean()) / block.std(ddof=0).replace(0, 1.0)
        d = np.sqrt(((z.loc[c.index] - z.loc[ix]) ** 2).sum(axis=1))
        nearest = d.sort_values(kind="mergesort").head(5).index
        options = sorted(c.loc[nearest, "symbol"])
        rng = np.random.default_rng(seed_of(f"B|{portfolio}|{entry_session}|{s['symbol']}|{RULES_ID}"))
        pick = options[int(rng.integers(len(options)))]
        used.add(pick)
        pairs.append((s["symbol"], pick))
    return pairs


def summarise(u: pd.DataFrame, members: list[str], mode: str, cost_pct: float, sessions_present: int) -> dict:
    """Mean over the members whose exit for `mode` has closed. The row is CLOSED once the mode's horizon has passed
    (TARGET_STOP: s6), so a group is never reported while some of its members are still open."""
    g = u[u["symbol"].isin(members)]
    closed = g[f"{mode}|state"] == "CLOSED"
    gc = g[closed]
    gross = gc[f"{mode}|gross_return"].astype(float)
    netr = gross - cost_pct / 100.0
    return {"n": int(len(gc)), "members": sorted(members), "gross_mean": float(gross.mean()) if len(gc) else None,
            "net_mean": float(netr.mean()) if len(gc) else None,
            "target_hit_rate": float(gc[f"{mode}|target_hit"].astype(bool).mean()) if len(gc) else None,
            "positive_rate": float((netr > 0).mean()) if len(gc) else None,
            "state": "CLOSED" if sessions_present >= sim.MODE_SESSION[mode] else "OPEN"}


def index_return(idx: pd.DataFrame, sessions: list, mode: str) -> Optional[dict]:
    """Nifty 50 from s1 open to the mode's exit close; None until that close exists."""
    s = sim.MODE_SESSION[mode]
    if len(sessions) < s:
        return None
    a, b = pd.Timestamp(sessions[0]), pd.Timestamp(sessions[s - 1])
    if a not in idx.index or b not in idx.index:
        return None
    o, c = float(idx.loc[a, "open_price"]), float(idx.loc[b, "close_price"])
    return {"gross": c / o - 1.0, "source": ",".join(sorted({str(idx.loc[a, "source"]), str(idx.loc[b, "source"])}))}


def benchmark_rows(u: pd.DataFrame, portfolio: str, entry_session: str, sessions: list, idx: pd.DataFrame, cost_pct: float) -> list[dict]:
    rows = []
    mem = {"MODEL": members_model(u), "A_ALL": members_a_all(u), "A_RANDOM5": members_a_random5(u, portfolio, entry_session),
           "B_MATCHED": [p for _, p in members_b_matched(u, portfolio, entry_session)], "C_MOVEMENT": members_c_movement(u)}
    for mode in sim.MODES:
        for b, ms in mem.items():
            s = summarise(u, ms, mode, cost_pct, len(sessions))
            s["members"] = ms if b != "A_ALL" else []          # A_ALL is "everyone": not listed
            rows.append({"benchmark": b, "mode": mode, **s, "source": None})
        ir = index_return(idx, sessions, mode)
        rows.append({"benchmark": "D_NIFTY50", "mode": mode, "state": "CLOSED" if ir else "OPEN", "n": 1 if ir else 0, "members": ["NIFTY 50"],
                     "gross_mean": ir["gross"] if ir else None, "net_mean": ir["gross"] if ir else None, "target_hit_rate": None,
                     "positive_rate": (1.0 if ir["gross"] > 0 else 0.0) if ir else None, "source": ir["source"] if ir else None})
    return rows
