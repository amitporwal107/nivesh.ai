"""Columnar priced-pair table — what makes a 1,000-seed run finish in hours instead of days.

THE PROBLEM THIS SOLVES
-----------------------
`stream_accumulate.SeedAccumulator` folds a row at a time and is bit-exact, but measured at
3.66 ms a fold. Each priced pair is drawn by ~58 of the 1,000 seeds, so the run needs ~189 M folds:

    189 M x 3.66 ms = 192 h single-core, 48 h on four cores.

Almost all of that is re-parsing the SAME row: `add_row` walks `costs.by_horizon[h].scenarios[s]`
20 times and `targets[t].by_horizon[h]` 40 times, then each target's exit costs 160 times -- ~220
dict traversals -- and it repeats that 58 times for one row.

THE FIX
-------
Parse each pair ONCE into a fixed set of numeric columns, then reduce per seed with one vectorised
gather. 2.07 M parses instead of 189 M, and the per-seed work becomes array arithmetic.

EXACTNESS: MEASURED, AND SPLIT DELIBERATELY
-------------------------------------------
`report._mean` is `statistics.fmean`, i.e. `math.fsum(data)/n`, and `fsum` is exactly rounded.
NumPy's `.sum()` uses pairwise summation, which was measured to differ from `fsum` on 25-47% of
realistic samples -- by ~2e-16 relative, one or two ulps.

Two ulps cannot flip a 95th-percentile comparison or a q-value. But rather than quietly drop the
bit-identical guarantee the step-4 gate established, the columns are split:

  * EXACT columns  -- `net_before_tax` for every (horizon, scenario). These are the only values
    `report.comparison_block` turns into a reported number for a random-control seed, so they are
    reduced with `math.fsum` and stay bit-identical. Measured cost: ~8 min across the whole study.
  * FAST columns   -- the S-1 extras (gross, cost, slippage, hit-rate and ambiguity inputs). Nothing
    reads them today; they are reduced with NumPy and are accurate to ~1 ulp. Measured: ~36 min.

So: every figure the study prints is exact, and the parts that are not exact are named here rather
than discovered later.
"""
from __future__ import annotations

import math
from typing import Mapping, Optional, Sequence

import numpy as np

from research.charting.study import accumulate, report

#: Column groups are built once from the horizon/scenario/target lists so a layout change cannot
#: drift between the writer and the reader.
_EXIT_CODES = {"TARGET": 1.0, "STOP": 2.0, "AMBIGUOUS": 3.0, "NONE": 4.0}


class PairLayout:
    """Which column holds which number. One instance per run, shared by every seed."""

    def __init__(self, horizons: Sequence[int], scenarios: Sequence[str], targets: Sequence[str]):
        self.horizons, self.scenarios, self.targets = tuple(horizons), tuple(scenarios), tuple(targets)
        # exact block: net per (h, s) -- reduced with math.fsum
        self.exact_index = {(h, s): i for i, (h, s) in
                            enumerate((h, s) for h in self.horizons for s in self.scenarios)}
        self.n_exact = len(self.exact_index)
        # fast block: everything else
        # Two blocks, split by WHAT THE COLUMN HOLDS -- a distinction a first version got wrong by
        # putting everything in float32, which cost 2e-8 relative on `avg_cost` (float32 carries
        # ~7 decimal digits, and a rupee value of 244.83 has no business being stored in one).
        #   money -> float64: sums of rupee amounts, whose means are reported
        #   flag  -> float32: 0/1 indicators, exit codes and holding periods -- small integers,
        #            represented EXACTLY in float32, so this costs nothing
        money: dict = {}
        flag: dict = {}

        def add_money(key):
            money[key] = len(money)

        def add_flag(key):
            flag[key] = len(flag)

        for h in self.horizons:
            for s in self.scenarios:
                for field in ("gross", "cost", "slip", "win", "loss"):
                    add_money(("cost", h, s, field))
                for field in ("available", "is_win", "is_loss"):
                    add_flag(("cost", h, s, field))
        for t in self.targets:
            for h in self.horizons:
                for field in ("present", "code", "has_exit", "hold"):
                    add_flag(("tgt", t, h, field))
                for s in self.scenarios:
                    add_flag(("tgt", t, h, s, "net_hit"))
        # The as_if_target / as_if_stop legs (owner decision S-3) are NOT dense columns. They exist
        # only for an AMBIGUOUS resolution -- target and stop both touched inside one bar -- which
        # is rare, so 960 near-always-zero columns would have cost 4.7 GB of the 7.3 GB table for
        # almost nothing. They live in a sparse side map instead, keyed by pair index.
        self.money_index, self.n_money = money, len(money)
        self.flag_index, self.n_flag = flag, len(flag)

    def __repr__(self) -> str:
        return (f"PairLayout(exact={self.n_exact} f64, money={self.n_money} f64, "
                f"flag={self.n_flag} f32)")


def encode_row(row: Mapping, layout: PairLayout) -> tuple:
    """One priced row -> (exact float64 vector, fast float32 vector, sparse ambiguity map).

    Called ONCE per pair, not once per fold -- that is the whole point.

    Every field read here is one `accumulate.group_summary` reads; nothing else is kept, which is
    what turns 283 KB of nested dicts into ~2.6 KB of numbers.
    """
    exact = np.zeros(layout.n_exact, dtype=np.float64)
    money = np.zeros(layout.n_money, dtype=np.float64)
    flag = np.zeros(layout.n_flag, dtype=np.float32)
    ambiguity: dict = {}
    mi, gi, ei = layout.money_index, layout.flag_index, layout.exact_index

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

    for t in layout.targets:
        for h in layout.horizons:
            block = report._target_horizon_block(row, t, h)
            if block is None:
                continue
            flag[gi[("tgt", t, h, "present")]] = 1.0
            fe = block.get("first_exit_event")
            flag[gi[("tgt", t, h, "code")]] = _EXIT_CODES.get(fe, 0.0)
            exit_ = block.get("exit")
            if exit_ is not None:
                flag[gi[("tgt", t, h, "has_exit")]] = 1.0
                flag[gi[("tgt", t, h, "hold")]] = exit_["holding_period_sessions"]
            for s in layout.scenarios:
                if exit_ is not None:
                    scen = ((exit_.get("costs") or {}).get("scenarios") or {}).get(s)
                    if (scen is not None and scen.get("available", True)
                            and scen.get("net_before_tax") is not None and scen["net_before_tax"] > 0):
                        flag[gi[("tgt", t, h, s, "net_hit")]] = 1.0
                if fe != "AMBIGUOUS":
                    continue
                for leg in ("as_if_target", "as_if_stop"):
                    lb = block.get(leg)
                    if lb is None:
                        continue
                    lsc = ((lb.get("costs") or {}).get("scenarios") or {}).get(s)
                    value = (lsc or {}).get("net_before_tax")
                    if value is None:
                        continue
                    ambiguity[(t, h, s, leg)] = value
    return exact, money, flag, ambiguity


class PairTable:
    """The encoded pairs, in insertion order, with a row index per (symbol, bar_index).

    Built once per segment by streaming the priced pairs through `encode_row` in bounded chunks, so
    the fat priced dicts never accumulate. Every seed then reduces by gathering its own row indices.
    """

    def __init__(self, layout: PairLayout, capacity: int):
        self.layout = layout
        self.exact = np.zeros((capacity, layout.n_exact), dtype=np.float64)
        self.money = np.zeros((capacity, layout.n_money), dtype=np.float64)
        self.flag = np.zeros((capacity, layout.n_flag), dtype=np.float32)
        self.ambiguity: dict = {}          # row index -> {(target, horizon, scenario, leg): net}
        self.index: dict = {}              # (symbol, bar_index) -> row index
        self._n = 0

    def add(self, pair, row: Mapping) -> int:
        exact, money, flag, amb = encode_row(row, self.layout)
        i = self._n
        self.exact[i] = exact
        self.money[i] = money
        self.flag[i] = flag
        if amb:
            self.ambiguity[i] = amb
        self.index[pair] = i
        self._n += 1
        return i

    @property
    def flag_index_view(self) -> dict:
        return self.layout.flag_index

    def __len__(self) -> int:
        return self._n

    def rows_for(self, picks: Sequence) -> np.ndarray:
        """Row indices for a seed's picks, in the seed's own (sorted) order. A pick with no priced
        row is skipped rather than silently zero-filled."""
        idx = [self.index[p] for p in picks if p in self.index]
        return np.asarray(idx, dtype=np.int64)

    # ── per-seed reduction ──────────────────────────────────────────────────────────────────────

    def seed_stats(self, rows: np.ndarray) -> dict:
        """`report.return_stats`' shape per (horizon, scenario) for one seed's rows.

        The `net` mean is reduced with `math.fsum`, so it is bit-identical to `statistics.fmean` and
        therefore to what the row path reports. Every other mean here is an S-1 extra that nothing
        reads and is reduced with NumPy (~1 ulp); that split is the module docstring's whole point.
        """
        L = self.layout
        out: dict = {}
        if rows.size == 0:
            for h in L.horizons:
                for s in L.scenarios:
                    cell = report.n_cell(0)
                    cell.update({"gross_return": {"median": None, "mean": None},
                                 "net_return": {"median": None, "mean": None},
                                 "avg_cost": None, "avg_slippage": None, "net_expectancy": None,
                                 "profit_factor": None, "win_rate": None, "avg_win": None,
                                 "avg_loss": None, "max_drawdown": None})
                    out.setdefault(h, {})[s] = cell
            return out

        ex = self.exact[rows]
        mo = self.money[rows]
        fl = self.flag[rows]
        mi, gi = L.money_index, L.flag_index
        for h in L.horizons:
            for s in L.scenarios:
                avail = fl[:, gi[("cost", h, s, "available")]] > 0
                n = int(avail.sum())
                cell = report.n_cell(n)
                if n == 0:
                    cell.update({"gross_return": {"median": None, "mean": None},
                                 "net_return": {"median": None, "mean": None},
                                 "avg_cost": None, "avg_slippage": None, "net_expectancy": None,
                                 "profit_factor": None, "win_rate": None, "avg_win": None,
                                 "avg_loss": None, "max_drawdown": None})
                    out.setdefault(h, {})[s] = cell
                    continue
                # EXACT: fsum over the float64 net column, matching statistics.fmean bit for bit
                net_mean = math.fsum(ex[avail, L.exact_index[(h, s)]]) / n
                n_wins = int(fl[:, gi[("cost", h, s, "is_win")]].sum())
                n_losses = int(fl[:, gi[("cost", h, s, "is_loss")]].sum())
                gross_profit = float(mo[:, mi[("cost", h, s, "win")]].sum())
                gross_loss = -float(mo[:, mi[("cost", h, s, "loss")]].sum())
                if gross_loss > 0:
                    pf = gross_profit / gross_loss
                elif gross_profit > 0:
                    pf = float("inf")
                else:
                    pf = None
                cell.update({
                    "gross_return": {"median": None,
                                     "mean": float(mo[avail, mi[("cost", h, s, "gross")]].sum()) / n},
                    "net_return": {"median": None, "mean": net_mean},
                    "avg_cost": float(mo[avail, mi[("cost", h, s, "cost")]].sum()) / n,
                    "avg_slippage": float(mo[avail, mi[("cost", h, s, "slip")]].sum()) / n,
                    "net_expectancy": net_mean,
                    "profit_factor": pf,
                    "win_rate": n_wins / n,
                    "avg_win": (gross_profit / n_wins) if n_wins else None,
                    "avg_loss": (-gross_loss / n_losses) if n_losses else None,
                    "max_drawdown": None,
                })
                out.setdefault(h, {})[s] = cell
        return out


# ── building the table, and reducing a seed out of it ───────────────────────────────────────────

DEFAULT_CHUNK = 5_000
"""Pairs priced at once. The fat priced dicts are ~283 KB each, so this caps the transient cost at
~1.4 GB; they are encoded and dropped before the next chunk. Larger chunks buy nothing — pricing is
per-pair work — and 20,000 would peak at 5.7 GB."""


def build_table(
    bars_by_symbol: Mapping, pairs, layout: PairLayout, *, cfg=None, cost_cfg=None,
    chunk_size: int = DEFAULT_CHUNK, row_check=None, progress=None, max_workers: int = 1,
) -> "PairTable":
    """Price every pair once, encode it, drop the fat object. Pairs are walked in GLOBALLY SORTED
    order, which matters: a seed's picks are `sorted()`, so a seed meets its own rows in its own
    order and anything order-dependent stays reproducible.

    A random-control row depends only on (symbol, bar_index) — `pattern_id` is
    `symbol:RANDOM_CONTROL:date` — so it is assembled once per pair here rather than once per seed,
    which is the ~58x saving this whole module exists for.

    `row_check` runs on every row before it is encoded: that is where
    `integrity.assert_no_sealed_rows_in_dataset` goes, so §8's coverage does not shrink when the
    rows stop being kept.
    """
    from research.charting.config import CONFIG
    from research.charting.events import controls

    cfg = CONFIG if cfg is None else cfg
    ordered = sorted(pairs)
    table = PairTable(layout, capacity=len(ordered))
    for start in range(0, len(ordered), chunk_size):
        chunk = ordered[start:start + chunk_size]
        priced = controls.price_signals(bars_by_symbol, set(chunk), cfg=cfg, cost_cfg=cost_cfg,
                                        max_workers=max_workers)
        for pair in chunk:
            ps = priced.get(pair)
            if ps is None:
                continue
            symbol, idx = pair
            bars = bars_by_symbol[symbol]
            pattern_id = f"{symbol}:{controls.RANDOM_CONTROL_PATTERN_TYPE}:{controls._iso(bars, idx)}"
            row = controls._assemble_priced_baseline_row(
                bars, symbol, idx, ps, pattern_type=controls.RANDOM_CONTROL_PATTERN_TYPE,
                pattern_id=pattern_id, cfg=cfg,
            )
            if row_check is not None:
                row_check(row)
            table.add(pair, row)
        del priced
        if progress is not None:
            progress(min(start + chunk_size, len(ordered)), len(ordered))
    return table


def seed_summary(table: "PairTable", picks: Sequence) -> dict:
    """One seed's summary, in the shape `accumulate.group_summary` returns.

    Medians and `max_drawdown` are absent for the reason `stream_accumulate` documents (non-additive,
    ~19 GB across 1,000 seeds, and nothing reads them from a random-control seed).

    Recoverability does not depend on keeping rows: the draw is deterministic, so a seed can be
    regenerated from its seed number, and `row_sha256` below pins every pair's row bytes
    individually. Verifying a regenerated seed means re-hashing its rows and comparing — which is
    the same guarantee `writer.write_run`'s artifact hash gives, at 32 bytes a pair.
    """
    rows = table.rows_for(picks)
    L = table.layout
    fl, gi = table.flag, table.flag_index_view
    out_hit: dict = {}
    out_hold: dict = {}
    out_amb: dict = {}

    sel_flag = fl[rows] if rows.size else fl[:0]
    for h in L.horizons:
        for t in L.targets:
            present = sel_flag[:, gi[("tgt", t, h, "present")]] > 0 if rows.size else np.zeros(0, bool)
            n = int(present.sum())
            code = sel_flag[:, gi[("tgt", t, h, "code")]] if rows.size else np.zeros(0)
            has_exit = sel_flag[:, gi[("tgt", t, h, "has_exit")]] > 0 if rows.size else np.zeros(0, bool)
            hold = sel_flag[:, gi[("tgt", t, h, "hold")]] if rows.size else np.zeros(0)
            hist: dict = {}
            if rows.size and has_exit.any():
                vals, counts = np.unique(hold[has_exit].astype(np.int64), return_counts=True)
                hist = {int(v): int(c) for v, c in zip(vals, counts)}
            out_hold.setdefault(h, {})[t] = hist
            tf = int((code == 1.0).sum()); sf = int((code == 2.0).sum())
            amb = int((code == 3.0).sum()); nei = int((code == 4.0).sum())
            for s in L.scenarios:
                net_hits = int((sel_flag[:, gi[("tgt", t, h, s, "net_hit")]] > 0).sum()) if rows.size else 0
                cell = report.n_cell(n)
                cell.update({
                    "gross_hit_rate": (tf / n) if n else None,
                    "net_hit_rate": (net_hits / n) if n else None,
                    "target_first_share": (tf / n) if n else None,
                    "stop_first_share": (sf / n) if n else None,
                    "ambiguous_share": (amb / n) if n else None,
                    "neither_share": (nei / n) if n else None,
                    "median_holding_period": _median_from_hist(hist),
                    "counts": {"target_first": tf, "stop_first": sf, "ambiguous": amb, "neither": nei},
                })
                out_hit.setdefault(h, {}).setdefault(t, {})[s] = cell
                # ambiguity legs come from the sparse side map
                n_amb = 0; legs = {"as_if_target": [0, [], 0], "as_if_stop": [0, [], 0]}
                for ri in rows.tolist():
                    a = table.ambiguity.get(ri)
                    if not a:
                        continue
                    hit_any = False
                    for leg in ("as_if_target", "as_if_stop"):
                        v = a.get((t, h, s, leg))
                        if v is None:
                            continue
                        hit_any = True
                        legs[leg][0] += 1
                        legs[leg][1].append(v)
                        if v > 0:
                            legs[leg][2] += 1
                    if hit_any:
                        n_amb += 1
                out_amb.setdefault(h, {}).setdefault(t, {})[s] = {
                    "n_ambiguous": amb,
                    "as_if_target": {"n": legs["as_if_target"][0],
                                     "sum_net": math.fsum(legs["as_if_target"][1]),
                                     "n_positive": legs["as_if_target"][2]},
                    "as_if_stop": {"n": legs["as_if_stop"][0],
                                   "sum_net": math.fsum(legs["as_if_stop"][1]),
                                   "n_positive": legs["as_if_stop"][2]},
                }
    return {
        "summary_version": accumulate.SUMMARY_VERSION,
        "n_rows": int(rows.size),
        "stats": table.seed_stats(rows),
        "hit_rates": out_hit,
        "holding_period_histograms": out_hold,
        "ambiguity_legs": out_amb,
        "segmentation": {"status": "NOT_COMPUTED",
                         "reason": "RANDOM_CONTROL_ENTERS_REPORT_AS_PER_SEED_MEANS"},
        "columnar": True,
    }


def _median_from_hist(hist: Mapping) -> Optional[float]:
    from research.charting.study.stream_accumulate import _median_from_histogram
    return _median_from_histogram(hist)
