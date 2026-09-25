"""Columnar pattern-event rows — the fix for the one memory wall that tuning could not move.

WHY
---
A pattern-event row carries 5,228 nested leaf values. Measured 2026-09-25, two independent ways
(RSS delta over a bulk load, and `ru_maxrss` around the context join): **188 KB live per row against
2.7 KB of actual data**, a ~70x Python container overhead. 296 MB of gzipped rows on disk becomes
29 GB the moment it is unpickled.

That is what defeated six run attempts. The reference fix and the worker cap were real (the join's
own cost went 2.30 GB -> 0.65 GB, and two OOM kills became a clean 53 GB ceiling), but they moved a
2x factor against a 70x problem. `pair_table.py` already proves the remedy on control rows at 329x;
this is the same treatment for pattern rows, which need more fields because the report reads more
from them.

WHAT THE REPORT ACTUALLY READS FROM A PATTERN ROW
-------------------------------------------------
Derived by enumerating `study/report.py`, not guessed -- guessing the fields is how the context CSVs
came to be missing on the study VM:

  identity/grouping  event_id, signal_date, symbol, pattern_id, pattern_type, direction
  cost cells         costs.by_horizon[h].scenarios[s]  -> gross, net_before_tax, total_cost,
                                                          entry_slippage, exit_slippage
  target cells       targets[t].by_horizon[h]          -> first_exit_event, exit.holding_period,
                                                          exit.costs.scenarios[s].net_before_tax,
                                                          and the AMBIGUOUS as_if_* legs
  outcomes           outcomes.forward_returns[h]              -> mfe, mae   (median MFE/MAE, §7.4)
                     outcomes.forward_returns_directional[h]  -> close_return_directional ONLY.
                       §7.8's MFE/MAE for BEARISH rows come from forward_returns like every other
                       row, so there is no second MFE/MAE pair here -- a symmetric-looking
                       `dir_mfe` column would never be read and would invite a wrong join.
  segmentation       context.trend_class_class, context.market_trend_class_class,
                     context.regime_regime, liquidity.adv_inr_at_t,
                     atr_at_t / entry.primary.price  (the ATR bucket)

PRECISION, DELIBERATELY SPLIT
-----------------------------
Three dtypes, chosen per column by what it holds. A first version of `pair_table` put everything in
float32 and lost 2e-8 on `avg_cost`; float32 carries ~7 decimal digits and a rupee value has no
business in one.

  exact  float64  net_before_tax per (h, s) -- reduced with math.fsum so the reported mean is
                  bit-identical to statistics.fmean, which is what the equivalence gate asserts
  money  float64  every other rupee amount, and MFE/MAE. MFE/MAE are float64 on purpose: AUC is
                  sensitive to ties, and float32 rounding would MANUFACTURE ties that did not exist
  flag   float32  0/1 indicators, exit codes, holding periods -- small integers, represented
                  exactly in float32, so this costs nothing

Strings (pattern_type, direction, the three context labels) are dictionary-encoded to small integer
codes rather than repeated, because the report segments on them.
"""
from __future__ import annotations

import io
import json
import logging
import os
import zipfile
from pathlib import Path
from typing import Mapping, Optional, Sequence

import numpy as np

from research.charting.study import report

logger = logging.getLogger(__name__)

_EXIT_CODES = {"TARGET": 1.0, "STOP": 2.0, "AMBIGUOUS": 3.0, "NONE": 4.0}

#: The three §7.7 dimensions that come from the context block. A row whose context is absent gets
#: `NO_CONTEXT`, exactly as `report.context_label`'s own default does -- absence must stay
#: distinguishable from a real label, not collapse into one.
CONTEXT_KEYS = ("trend_class_class", "market_trend_class_class", "regime_regime")
NO_CONTEXT = "NO_CONTEXT"


class Dictionary:
    """Dictionary encoding for a low-cardinality string column.

    `pattern_type`, `direction` and the context labels repeat across every row; storing the string
    per row costs more than the numbers beside it. Codes are assigned in first-seen order and the
    mapping travels with the table, so a decode is exact rather than a guess.
    """

    __slots__ = ("_to_code", "_to_value")

    def __init__(self) -> None:
        self._to_code: dict = {}
        self._to_value: list = []

    def code(self, value: Optional[str]) -> float:
        key = NO_CONTEXT if value is None else value
        got = self._to_code.get(key)
        if got is None:
            got = len(self._to_value)
            self._to_code[key] = got
            self._to_value.append(key)
        return float(got)

    def value(self, code: float) -> str:
        i = int(code)
        return self._to_value[i] if 0 <= i < len(self._to_value) else NO_CONTEXT

    def __len__(self) -> int:
        return len(self._to_value)

    def as_list(self) -> list:
        return list(self._to_value)


class PatternLayout:
    """Which column holds which number, for pattern-event rows.

    Built once per run from the horizon/scenario/target lists, so a layout change cannot drift
    between the writer and the reader.
    """

    def __init__(self, horizons: Sequence[int], scenarios: Sequence[str], targets: Sequence[str]):
        self.horizons = tuple(horizons)
        self.scenarios = tuple(scenarios)
        self.targets = tuple(targets)

        # exact: the values whose MEAN is reported, reduced with math.fsum
        self.exact_index = {(h, s): i for i, (h, s) in
                            enumerate((h, s) for h in self.horizons for s in self.scenarios)}
        self.n_exact = len(self.exact_index)

        money: dict = {}
        flag: dict = {}

        def m(key):
            money[key] = len(money)

        def f(key):
            flag[key] = len(flag)

        for h in self.horizons:
            for s in self.scenarios:
                for field in ("gross", "cost", "slip", "win", "loss"):
                    m(("cost", h, s, field))
                for field in ("available", "is_win", "is_loss"):
                    f(("cost", h, s, field))
            # MFE/MAE in float64 -- see the module docstring on manufactured AUC ties
            for field in ("mfe", "mae", "dir_return"):
                m(("out", h, field))
            for field in ("fwd_available", "dir_available"):
                f(("out", h, field))

        for t in self.targets:
            for h in self.horizons:
                for field in ("present", "code", "has_exit", "hold"):
                    f(("tgt", t, h, field))
                for s in self.scenarios:
                    f(("tgt", t, h, s, "net_hit"))

        # row-level segmentation inputs
        m(("row", "atr_at_t"))
        m(("row", "entry_price"))
        m(("row", "adv_inr_at_t"))
        f(("row", "has_adv"))
        # `assert_statistics_are_not_vacuous` counts rows carrying ANY priced horizon, which is
        # not the same as any per-horizon `available` flag: a row can have a by_horizon map in
        # which every horizon is unavailable. Conflating them would turn a real pipeline defect
        # into a silent "the patterns did nothing".
        f(("row", "priceable"))

        self.money_index, self.n_money = money, len(money)
        self.flag_index, self.n_flag = flag, len(flag)

        # dictionary-encoded string columns, in a fixed order
        self.code_columns = ("pattern_type", "direction") + CONTEXT_KEYS
        self.code_index = {c: i for i, c in enumerate(self.code_columns)}
        self.n_code = len(self.code_columns)

    def bytes_per_row(self) -> int:
        return (self.n_exact + self.n_money) * 8 + (self.n_flag + self.n_code) * 4

    def __repr__(self) -> str:
        return (f"PatternLayout(exact={self.n_exact} f64, money={self.n_money} f64, "
                f"flag={self.n_flag} f32, codes={self.n_code}, "
                f"{self.bytes_per_row()} B/row)")


#: Columns whose natural absence-value is "no observation". NaN is used rather than 0.0 so that a
#: reader which forgets to consult the matching `available` flag gets a loud NaN instead of a
#: silent zero that would drag a mean toward it. The additive accumulators (`win`, `loss`) are
#: reduced with `np.nansum`, for which an all-NaN column is correctly 0.0.
_ABSENT = np.nan


def encode_pattern_row(row: Mapping, layout: "PatternLayout", dicts: Mapping[str, Dictionary]) -> tuple:
    """One pattern-event row -> (exact f64, money f64, flag f32, codes i16, date string).

    Every field read here is one `report.py` reads, and nothing else is kept. That is the whole
    reduction: 5,228 nested leaves at 188 KB live becomes ~2.7 KB of numbers.

    Reuses `report._horizon_cost_scenario` / `_target_horizon_block` / `_forward_return_block`
    rather than re-walking the nested dicts by hand, so the encoder cannot drift from the reader's
    own notion of what "available" means -- and inherits their `HorizonKeyError` guard against the
    int-vs-str key corruption that a JSON cache introduced once already.
    """
    exact = np.full(layout.n_exact, _ABSENT, dtype=np.float64)
    money = np.full(layout.n_money, _ABSENT, dtype=np.float64)
    flag = np.zeros(layout.n_flag, dtype=np.float32)
    codes = np.zeros(layout.n_code, dtype=np.int16)
    ei, mi, gi = layout.exact_index, layout.money_index, layout.flag_index

    for h in layout.horizons:
        for s in layout.scenarios:
            scen = report._horizon_cost_scenario(row, h, s)
            if scen is None:
                continue
            net = scen["net_before_tax"]
            exact[ei[(h, s)]] = net
            flag[gi[("cost", h, s, "available")]] = 1.0
            money[mi[("cost", h, s, "gross")]] = scen["gross"]
            money[mi[("cost", h, s, "cost")]] = scen["total_cost"]
            money[mi[("cost", h, s, "slip")]] = (scen.get("entry_slippage") or 0.0) + (scen.get("exit_slippage") or 0.0)
            if net > 0:
                flag[gi[("cost", h, s, "is_win")]] = 1.0
                money[mi[("cost", h, s, "win")]] = net
            elif net < 0:
                flag[gi[("cost", h, s, "is_loss")]] = 1.0
                money[mi[("cost", h, s, "loss")]] = net

        fwd = report._forward_return_block(row, h)
        if fwd is not None:
            flag[gi[("out", h, "fwd_available")]] = 1.0
            money[mi[("out", h, "mfe")]] = fwd["mfe"]
            money[mi[("out", h, "mae")]] = fwd["mae"]
        dirb = report._directional_return_block(row, h)
        if dirb is not None:
            flag[gi[("out", h, "dir_available")]] = 1.0
            money[mi[("out", h, "dir_return")]] = dirb["close_return_directional"]

    for t in layout.targets:
        for h in layout.horizons:
            block = report._target_horizon_block(row, t, h)
            if block is None:
                continue
            flag[gi[("tgt", t, h, "present")]] = 1.0
            flag[gi[("tgt", t, h, "code")]] = _EXIT_CODES.get(block.get("first_exit_event"), 0.0)
            exit_ = block.get("exit")
            if exit_ is None:
                continue
            flag[gi[("tgt", t, h, "has_exit")]] = 1.0
            flag[gi[("tgt", t, h, "hold")]] = exit_["holding_period_sessions"]
            for s in layout.scenarios:
                scen = ((exit_.get("costs") or {}).get("scenarios") or {}).get(s)
                if (scen is not None and scen.get("available", True)
                        and scen.get("net_before_tax") is not None and scen["net_before_tax"] > 0):
                    flag[gi[("tgt", t, h, s, "net_hit")]] = 1.0

    # row-level segmentation inputs
    atr_at_t = row.get("atr_at_t")
    if atr_at_t is not None:
        money[mi[("row", "atr_at_t")]] = float(atr_at_t)
    price = ((row.get("entry") or {}).get("primary") or {}).get("price")
    if price is not None:
        money[mi[("row", "entry_price")]] = float(price)
    adv = (row.get("liquidity") or {}).get("adv_inr_at_t")
    if adv is not None:
        money[mi[("row", "adv_inr_at_t")]] = float(adv)
        flag[gi[("row", "has_adv")]] = 1.0
    if (row.get("costs") or {}).get("by_horizon"):
        flag[gi[("row", "priceable")]] = 1.0

    ctx = row.get("context") or {}
    codes[layout.code_index["pattern_type"]] = dicts["pattern_type"].code(row.get("pattern_type"))
    codes[layout.code_index["direction"]] = dicts["direction"].code(row.get("direction"))
    for key in CONTEXT_KEYS:
        codes[layout.code_index[key]] = dicts[key].code(ctx.get(key))

    return exact, money, flag, codes


class PatternTable:
    """Encoded pattern rows for one segment, as five parallel arrays plus identity.

    Built per symbol by a worker and written to disk, so the parent collects PATHS rather than
    rows -- the whole reason the row path could not finish. `concat` merges them back, remapping
    each part's dictionary codes into one shared dictionary.
    """

    __slots__ = ("layout", "exact", "money", "flag", "codes", "dicts",
                 "event_id", "symbol", "pattern_id", "signal_date", "_n")

    def __init__(self, layout: "PatternLayout", capacity: int):
        self.layout = layout
        self.exact = np.full((capacity, layout.n_exact), _ABSENT, dtype=np.float64)
        self.money = np.full((capacity, layout.n_money), _ABSENT, dtype=np.float64)
        self.flag = np.zeros((capacity, layout.n_flag), dtype=np.float32)
        self.codes = np.zeros((capacity, layout.n_code), dtype=np.int16)
        self.dicts = {k: Dictionary() for k in ("pattern_type", "direction") + CONTEXT_KEYS}
        self.event_id: list = []
        self.symbol: list = []
        self.pattern_id: list = []
        self.signal_date: list = []
        self._n = 0

    def __len__(self) -> int:
        return self._n

    def add(self, row: Mapping) -> int:
        i = self._n
        e, m, g, c = encode_pattern_row(row, self.layout, self.dicts)
        self.exact[i], self.money[i], self.flag[i], self.codes[i] = e, m, g, c
        self.event_id.append(row.get("event_id"))
        self.symbol.append(row.get("symbol"))
        self.pattern_id.append(row.get("pattern_id"))
        self.signal_date.append(row.get("signal_date"))
        self._n = i + 1
        return i

    @classmethod
    def from_rows(cls, rows: Sequence[Mapping], layout: "PatternLayout") -> "PatternTable":
        table = cls(layout, len(rows))
        for row in rows:
            table.add(row)
        return table

    def order(self) -> np.ndarray:
        """Row indices in `return_stats`' equal-weight order: signal_date, then event_id.

        The maximum-drawdown figure is a property of this sequence, so the order is part of the
        result, not a presentation detail.
        """
        return np.asarray(sorted(range(self._n),
                                 key=lambda i: (self.signal_date[i] or "", self.event_id[i] or "")),
                          dtype=np.int64)

    def labels(self, column: str) -> list:
        """Decoded values for a dictionary-encoded column, one per row."""
        d = self.dicts[column]
        col = self.codes[:self._n, self.layout.code_index[column]]
        return [d.value(c) for c in col]


# ── reducers: the §7 statistics, computed from columns instead of dicts ──────────────────────────
#
# These deliberately reduce through `report._mean` / `report._median` over a PYTHON LIST rather than
# `ndarray.sum()`. `statistics.fmean` is `math.fsum(data)/n` -- exactly rounded -- while numpy sums
# pairwise. The two differ in the last bits, so a numpy reduction here would make the equivalence
# gate fail for a reason that has nothing to do with the encoding. One column at a time is
# materialised, never a row, which is where the memory win survives.


def _col(table: "PatternTable", array: np.ndarray, index: int, mask: np.ndarray) -> list:
    return array[:len(table), index][mask].tolist()


def table_return_stats(table: "PatternTable", horizon: int, *, scenario: str = "base") -> dict:
    """Columnar `report.return_stats`. Identical output, including `max_drawdown`, which depends on
    the equal-weight ORDER and so reuses `table.order()`."""
    n_rows = len(table)
    order = table.order()
    ei = table.layout.exact_index[(horizon, scenario)]
    gi = table.layout.flag_index
    mi = table.layout.money_index
    avail = table.flag[:n_rows, gi[("cost", horizon, scenario, "available")]][order] == 1.0

    net_vals = table.exact[:n_rows, ei][order][avail].tolist()
    gross_vals = table.money[:n_rows, mi[("cost", horizon, scenario, "gross")]][order][avail].tolist()
    cost_vals = table.money[:n_rows, mi[("cost", horizon, scenario, "cost")]][order][avail].tolist()
    slip_vals = table.money[:n_rows, mi[("cost", horizon, scenario, "slip")]][order][avail].tolist()

    n = len(net_vals)
    out = report.n_cell(n)
    if n == 0:
        out.update({
            "gross_return": {"median": None, "mean": None}, "net_return": {"median": None, "mean": None},
            "avg_cost": None, "avg_slippage": None, "net_expectancy": None, "profit_factor": None,
            "win_rate": None, "avg_win": None, "avg_loss": None, "max_drawdown": None,
        })
        return out

    wins = [v for v in net_vals if v > 0]
    losses = [v for v in net_vals if v < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = float("inf")
    else:
        profit_factor = None

    equity_curve = np.cumsum(np.asarray(net_vals, dtype=float))
    drawdown = equity_curve - np.maximum.accumulate(equity_curve)

    out.update({
        "gross_return": {"median": report._median(gross_vals), "mean": report._mean(gross_vals)},
        "net_return": {"median": report._median(net_vals), "mean": report._mean(net_vals)},
        "avg_cost": report._mean(cost_vals),
        "avg_slippage": report._mean(slip_vals),
        "net_expectancy": report._mean(net_vals),
        "profit_factor": profit_factor,
        "win_rate": len(wins) / n,
        "avg_win": report._mean(wins) if wins else None,
        "avg_loss": report._mean(losses) if losses else None,
        "max_drawdown": float(drawdown.min()),
    })
    return out


def table_hit_rate_table(table: "PatternTable", target_name: str, horizon: int,
                         *, scenario: str = "base") -> dict:
    """Columnar `report.hit_rate_table`."""
    n_rows = len(table)
    gi = table.layout.flag_index
    present = table.flag[:n_rows, gi[("tgt", target_name, horizon, "present")]] == 1.0
    n = int(present.sum())

    code = table.flag[:n_rows, gi[("tgt", target_name, horizon, "code")]][present]
    target_first = int((code == _EXIT_CODES["TARGET"]).sum())
    stop_first = int((code == _EXIT_CODES["STOP"]).sum())
    ambiguous = int((code == _EXIT_CODES["AMBIGUOUS"]).sum())
    neither = int((code == _EXIT_CODES["NONE"]).sum())

    has_exit = table.flag[:n_rows, gi[("tgt", target_name, horizon, "has_exit")]][present] == 1.0
    holding = table.flag[:n_rows, gi[("tgt", target_name, horizon, "hold")]][present][has_exit]
    net_hits = int(table.flag[:n_rows, gi[("tgt", target_name, horizon, scenario, "net_hit")]][present].sum())

    out = report.n_cell(n)
    out.update({
        "gross_hit_rate": (target_first / n) if n else None,
        "net_hit_rate": (net_hits / n) if n else None,
        "target_first_share": (target_first / n) if n else None,
        "stop_first_share": (stop_first / n) if n else None,
        "ambiguous_share": (ambiguous / n) if n else None,
        "neither_share": (neither / n) if n else None,
        "median_holding_period": report._median(holding.tolist()),
        "counts": {"target_first": target_first, "stop_first": stop_first,
                   "ambiguous": ambiguous, "neither": neither},
    })
    return out


def table_mfe_mae_stats(table: "PatternTable", horizon: int,
                        *, subset: Optional[np.ndarray] = None) -> dict:
    """Columnar `report.mfe_mae_stats`. `subset` is a boolean row mask, used by the §7.8 path."""
    n_rows = len(table)
    mask = table.flag[:n_rows, table.layout.flag_index[("out", horizon, "fwd_available")]] == 1.0
    if subset is not None:
        mask = mask & subset
    mi = table.layout.money_index
    out = report.n_cell(int(mask.sum()))
    out.update({
        "median_mfe": report._median(_col(table, table.money, mi[("out", horizon, "mfe")], mask)),
        "median_mae": report._median(_col(table, table.money, mi[("out", horizon, "mae")], mask)),
    })
    return out


def table_bearish_directional_report(table: "PatternTable", horizon: int) -> dict:
    """Columnar `report.bearish_directional_report` (§7.8).

    Note the asymmetry inherited from the report: `directional_return` is counted over BEARISH rows
    with a directional block, while the MFE/MAE `n` is counted over ALL bearish rows with a forward
    block. They are different denominators on purpose.
    """
    n_rows = len(table)
    codes = table.codes[:n_rows, table.layout.code_index["direction"]]
    bearish = np.array([table.dicts["direction"].value(c) == "BEARISH" for c in codes], dtype=bool)
    dir_avail = table.flag[:n_rows, table.layout.flag_index[("out", horizon, "dir_available")]] == 1.0
    mask = bearish & dir_avail
    vals = _col(table, table.money, table.layout.money_index[("out", horizon, "dir_return")], mask)
    out = report.n_cell(len(vals))
    out.update({
        "directional_return": {"median": report._median(vals), "mean": report._mean(vals)},
        **table_mfe_mae_stats(table, horizon, subset=bearish),
    })
    return out


# ── persistence: workers write files, the parent collects paths ──────────────────────────────────
#
# This is the point of the whole module. The row path had every worker RETURN its rows, so the
# parent held the entire dataset as nested dicts and died at 53 GB. Here a worker encodes its own
# symbol, writes one file, and returns a path -- a few hundred bytes.


#: Everything that is not a number travels as JSON beside the arrays, never as a pickled object
#: array. Two reasons: `allow_pickle=True` makes a data file executable, which a research artefact
#: has no business being; and a numpy `'U'` array would turn a missing symbol into the STRING
#: "None", which is a silent corruption rather than a visible gap.
_META = "meta.json"


def _meta_payload(table: "PatternTable") -> str:
    n = len(table)
    return json.dumps({
        "dicts": {k: d.as_list() for k, d in table.dicts.items()},
        "event_id": table.event_id[:n], "symbol": table.symbol[:n],
        "pattern_id": table.pattern_id[:n], "signal_date": table.signal_date[:n],
    })


def save_table(table: "PatternTable", path) -> "Path":
    """Write one symbol's table to `path`, atomically.

    Atomic because a study run is resumable: a half-written file from an OOM kill or a GCE reboot
    (both of which have happened here) must not be mistaken for a complete one on resume.

    `np.savez` APPENDS `.npz` to a filename that lacks it, which silently produced `...npz.tmp.npz`
    once and made the rename below fail -- so it is handed an open file object, which it leaves
    alone.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    n = len(table)
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        for name in ("exact", "money", "flag", "codes"):
            buf = io.BytesIO()
            np.lib.format.write_array(buf, getattr(table, name)[:n], allow_pickle=False)
            z.writestr(f"{name}.npy", buf.getvalue())
        z.writestr(_META, _meta_payload(table))
    with open(tmp, "rb+") as fh:
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    logger.debug("wrote %d rows to %s", n, path.name)
    return path


def load_table(path, layout: "PatternLayout") -> "PatternTable":
    """Read back a table written by `save_table`."""
    with zipfile.ZipFile(Path(path), "r") as z:
        arrays = {name: np.lib.format.read_array(io.BytesIO(z.read(f"{name}.npy")),
                                                 allow_pickle=False)
                  for name in ("exact", "money", "flag", "codes")}
        meta = json.loads(z.read(_META))
    n = int(arrays["exact"].shape[0])
    table = PatternTable(layout, n)
    for name, values in arrays.items():
        getattr(table, name)[:n] = values
    for name in ("event_id", "symbol", "pattern_id", "signal_date"):
        setattr(table, name, list(meta[name]))
    for key, values in meta["dicts"].items():
        d = Dictionary()
        for v in values:
            d.code(v)
        table.dicts[key] = d
    table._n = n
    return table


def concat_tables(parts: Sequence["PatternTable"], layout: "PatternLayout") -> "PatternTable":
    """Merge per-symbol tables into one, REMAPPING each part's dictionary codes.

    Each worker builds its own dictionary in first-seen order, so the same label is a different
    code in different parts. Concatenating the code columns without remapping would silently
    relabel rows -- BULLISH counted as BEARISH, one context bucket's rows landing in another. The
    numbers would all look plausible, which is what makes it worth a function of its own.
    """
    total = sum(len(p) for p in parts)
    out = PatternTable(layout, total)
    at = 0
    for part in parts:
        n = len(part)
        if n == 0:
            continue
        out.exact[at:at + n] = part.exact[:n]
        out.money[at:at + n] = part.money[:n]
        out.flag[at:at + n] = part.flag[:n]
        for column, col_i in layout.code_index.items():
            src, dst = part.dicts[column], out.dicts[column]
            remap = {c: dst.code(src.value(c)) for c in range(len(src))}
            out.codes[at:at + n, col_i] = [remap[int(c)] for c in part.codes[:n, col_i]]
        out.event_id.extend(part.event_id[:n])
        out.symbol.extend(part.symbol[:n])
        out.pattern_id.extend(part.pattern_id[:n])
        out.signal_date.extend(part.signal_date[:n])
        at += n
    out._n = at
    return out
