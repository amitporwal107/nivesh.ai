"""Streaming, bounded-memory comparison-group accumulation — study-v2 step 8.

WHY THIS EXISTS
---------------
`study/accumulate.py` summarises a seed's rows after they have been built. That works, and it is
proved exact (`tests/test_study_accumulate.py`), but it still needs the rows to exist. At full
universe they cannot:

    measured 2026-09-24, refreshed corpus, 2,936 symbols
      eligible pairs        pre_sealed 839,569 | post_sealed 1,235,326
      priced signal RSS     283 KB each
      union over 1,000 seeds ~100% of the eligible population
      => 227 GB / 333 GB held at once, on a 15 GB box

The union is not a V-3 artefact: at v1's 200 seeds it is still 93-98% of the population. A full-
universe run has never been memory-feasible; TC-113 hit the disk wall first and stopped there.

WHAT MAKES IT FIT
-----------------
1. **Rows are never collected.** Pairs are priced in bounded chunks and each row is folded into the
   accumulators of the seeds that drew it, then dropped. Peak memory is one chunk, not one union.
2. **The statistics are additive.** Counts and sums fold one row at a time.
3. **The means stay EXACT.** `report._mean` is `statistics.fmean`, which is literally
   `math.fsum(data)/n`, and `fsum` is exactly rounded — so a naive running sum would differ in the
   last bits and the study's numbers would quietly change. `ExactSum` below is Shewchuk's partials
   algorithm, the one `fsum` itself uses, run online: O(1) memory and bit-identical, verified
   against `math.fsum`/`statistics.fmean` over random and catastrophic-cancellation samples.

WHAT IS DELIBERATELY NOT CARRIED (owner decision S-1, narrowed 2026-09-24)
--------------------------------------------------------------------------
Medians and `max_drawdown` are NOT additive: a median needs every value, a drawdown needs them in
chronological order. Carrying them per seed costs `rows/seed x 20 (horizon x scenario) x 2 floats`
-- at the measured 72,444 rows/seed for RECTANGLE that is ~19 MB a seed, ~19 GB across 1,000 seeds.

Nothing reads them. `report.comparison_block` takes exactly two numbers from a random-control seed:
`n` and mean `net_before_tax`. So for the RANDOM CONTROL's per-seed summaries they are reported as
an explicit `NOT_COMPUTED` with a reason, never as a silent `None` that would read as "no data"
(the §39.13a availability discipline, same as S-2's control-context marker).

The report is therefore unchanged, exactly -- `comparison_block_from_summaries` reads only `n` and
the mean. The ATR-decile and buy-next-open groups keep the full summary: they are one row set per
family, not one per seed, so they cost nothing.

This narrowing is irreversible in the sense that recovering per-seed medians later means
regenerating every seed. It is recorded here and in the run manifest so that is never a surprise.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Iterable, Mapping, Optional, Sequence

from research.charting.events import writer
from research.charting.study import accumulate, report


class ExactSum:
    """Online exactly-rounded summation (Shewchuk's partials, as used by `math.fsum`).

    `total()` is bit-identical to `math.fsum` over the same values in the same order, and
    `mean()` to `statistics.fmean`, which matters because the study's reported means come from
    `fmean` and a redesign that shifts them in the 16th digit is not a storage change.
    """
    __slots__ = ("_partials", "n")

    def __init__(self) -> None:
        self._partials: list = []
        self.n = 0

    def add(self, x: float) -> None:
        x = float(x)
        self.n += 1
        partials = self._partials
        i = 0
        for y in partials:
            if abs(x) < abs(y):
                x, y = y, x
            hi = x + y
            lo = y - (hi - x)
            if lo:
                partials[i] = lo
                i += 1
            x = hi
        del partials[i:]
        partials.append(x)

    def total(self) -> float:
        return math.fsum(self._partials)

    def mean(self) -> Optional[float]:
        return self.total() / self.n if self.n else None


NOT_COMPUTED_MEDIAN = {
    "status": "NOT_COMPUTED",
    "reason": "NON_ADDITIVE_STATISTIC_OMITTED_FOR_PER_SEED_SUMMARIES",
    "detail": ("median and max_drawdown need every value (and, for drawdown, their order). At the "
               "measured rows/seed that is ~19 GB across 1,000 seeds, and report.comparison_block "
               "reads only n and mean net from a random-control seed. Owner decision S-1, narrowed "
               "2026-09-24."),
}


class SeedAccumulator:
    """One seed's comparison-group statistics, folded a row at a time and never storing rows.

    Mirrors what `accumulate.group_summary` produces, field for field, except the two non-additive
    statistics documented above. Memory is O(horizons x scenarios x targets) -- about 25 KB -- and
    independent of how many rows the seed drew.
    """

    __slots__ = ("horizons", "scenarios", "targets", "n_rows", "_cost", "_hit", "_hold", "_amb",
                 "_hasher")

    def __init__(self, *, horizons: Sequence[int] = accumulate.DEFAULT_HORIZONS,
                 scenarios: Sequence[str] = accumulate.DEFAULT_SCENARIOS,
                 targets: Sequence[str] = report.DEFAULT_TARGET_NAMES) -> None:
        self.horizons, self.scenarios, self.targets = tuple(horizons), tuple(scenarios), tuple(targets)
        self.n_rows = 0
        # The §8 kill-switch property, kept without keeping the rows: `writer.write_run` hashes
        # `_dump_jsonl(rows)`, which is each row's JSON line followed by a newline, so hashing each
        # line as it goes past produces the IDENTICAL sha256 -- provided rows arrive in the seed's
        # own order, which they do: a seed's picks are `sorted()`, and the streaming driver walks
        # pairs in globally sorted order.
        self._hasher = hashlib.sha256()
        # (h, s) -> the pieces report.return_stats derives every additive figure from
        self._cost = {
            (h, s): {"n": 0, "gross": ExactSum(), "net": ExactSum(), "cost": ExactSum(),
                     "slip": ExactSum(), "n_wins": 0, "wins": ExactSum(),
                     "n_losses": 0, "losses": ExactSum()}
            for h in self.horizons for s in self.scenarios
        }
        # (target, h, s) -> report.hit_rate_table's counters
        self._hit = {
            (t, h, s): {"n": 0, "target_first": 0, "stop_first": 0, "ambiguous": 0,
                        "neither": 0, "gross_hits": 0, "net_hits": 0}
            for t in self.targets for h in self.horizons for s in self.scenarios
        }
        # (target, h) -> exact histogram; holding period is a bounded small integer, so this
        # reproduces the median exactly rather than approximating it
        self._hold = {(t, h): {} for t in self.targets for h in self.horizons}
        # (target, h, s) -> owner decision S-3, the ambiguity legs
        self._amb = {
            (t, h, s): {"n_ambiguous": 0,
                        "as_if_target": {"n": 0, "sum": ExactSum(), "n_positive": 0},
                        "as_if_stop": {"n": 0, "sum": ExactSum(), "n_positive": 0}}
            for t in self.targets for h in self.horizons for s in self.scenarios
        }

    def add_row(self, row: Mapping) -> None:
        """Fold one control row in, then the caller may drop it."""
        self.n_rows += 1
        self._hasher.update(writer._dump_jsonl([row]))
        for h in self.horizons:
            for s in self.scenarios:
                scen = report._horizon_cost_scenario(row, h, s)
                if scen is None:
                    continue
                c = self._cost[(h, s)]
                c["n"] += 1
                net = scen["net_before_tax"]
                c["gross"].add(scen["gross"])
                c["net"].add(net)
                c["cost"].add(scen["total_cost"])
                c["slip"].add((scen.get("entry_slippage") or 0.0) + (scen.get("exit_slippage") or 0.0))
                if net > 0:
                    c["n_wins"] += 1
                    c["wins"].add(net)
                elif net < 0:
                    c["n_losses"] += 1
                    c["losses"].add(net)

        for t in self.targets:
            for h in self.horizons:
                block = report._target_horizon_block(row, t, h)
                if block is None:
                    continue
                fe = block.get("first_exit_event")
                exit_ = block.get("exit")
                if exit_ is not None:
                    hp = exit_["holding_period_sessions"]
                    hist = self._hold[(t, h)]
                    hist[hp] = hist.get(hp, 0) + 1
                for s in self.scenarios:
                    cell = self._hit[(t, h, s)]
                    cell["n"] += 1
                    if fe == "TARGET":
                        cell["target_first"] += 1
                        cell["gross_hits"] += 1
                    elif fe == "STOP":
                        cell["stop_first"] += 1
                    elif fe == "AMBIGUOUS":
                        cell["ambiguous"] += 1
                    elif fe == "NONE":
                        cell["neither"] += 1
                    if exit_ is not None:
                        scen = ((exit_.get("costs") or {}).get("scenarios") or {}).get(s)
                        if (scen is not None and scen.get("available", True)
                                and scen.get("net_before_tax") is not None and scen["net_before_tax"] > 0):
                            cell["net_hits"] += 1
                    if fe == "AMBIGUOUS":
                        a = self._amb[(t, h, s)]
                        a["n_ambiguous"] += 1
                        for leg_name in ("as_if_target", "as_if_stop"):
                            leg = block.get(leg_name)
                            if leg is None:
                                continue
                            lsc = ((leg.get("costs") or {}).get("scenarios") or {}).get(s)
                            value = (lsc or {}).get("net_before_tax")
                            if value is None:
                                continue
                            a[leg_name]["n"] += 1
                            a[leg_name]["sum"].add(value)
                            if value > 0:
                                a[leg_name]["n_positive"] += 1

    # ── finalise ────────────────────────────────────────────────────────────────────────────────

    def _stats_cell(self, h: int, s: str) -> dict:
        """`report.return_stats`' shape, with the additive figures exact and the two non-additive
        ones reported as NOT_COMPUTED rather than a `None` that would read as 'no data'."""
        c = self._cost[(h, s)]
        n = c["n"]
        out = report.n_cell(n)
        if n == 0:
            out.update({
                "gross_return": {"median": None, "mean": None}, "net_return": {"median": None, "mean": None},
                "avg_cost": None, "avg_slippage": None, "net_expectancy": None, "profit_factor": None,
                "win_rate": None, "avg_win": None, "avg_loss": None, "max_drawdown": None,
                "not_computed": dict(NOT_COMPUTED_MEDIAN),
            })
            return out
        gross_profit = c["wins"].total()
        gross_loss = -c["losses"].total()
        if gross_loss > 0:
            profit_factor = gross_profit / gross_loss
        elif gross_profit > 0:
            profit_factor = float("inf")
        else:
            profit_factor = None
        out.update({
            "gross_return": {"median": None, "mean": c["gross"].mean()},
            "net_return": {"median": None, "mean": c["net"].mean()},
            "avg_cost": c["cost"].mean(),
            "avg_slippage": c["slip"].mean(),
            "net_expectancy": c["net"].mean(),
            "profit_factor": profit_factor,
            "win_rate": c["n_wins"] / n,
            "avg_win": c["wins"].mean() if c["n_wins"] else None,
            "avg_loss": c["losses"].mean() if c["n_losses"] else None,
            "max_drawdown": None,
            "not_computed": dict(NOT_COMPUTED_MEDIAN),
        })
        return out

    def finalise(self) -> dict:
        """The same shape `accumulate.group_summary` returns, so a consumer cannot tell which path
        produced it apart from the explicit NOT_COMPUTED marker."""
        stats = {h: {s: self._stats_cell(h, s) for s in self.scenarios} for h in self.horizons}
        hit_rates: dict = {}
        holding: dict = {}
        ambiguity: dict = {}
        for h in self.horizons:
            for t in self.targets:
                holding.setdefault(h, {})[t] = dict(self._hold[(t, h)])
                for s in self.scenarios:
                    c = self._hit[(t, h, s)]
                    n = c["n"]
                    cell = report.n_cell(n)
                    cell.update({
                        "gross_hit_rate": (c["gross_hits"] / n) if n else None,
                        "net_hit_rate": (c["net_hits"] / n) if n else None,
                        "target_first_share": (c["target_first"] / n) if n else None,
                        "stop_first_share": (c["stop_first"] / n) if n else None,
                        "ambiguous_share": (c["ambiguous"] / n) if n else None,
                        "neither_share": (c["neither"] / n) if n else None,
                        "median_holding_period": _median_from_histogram(self._hold[(t, h)]),
                        "counts": {"target_first": c["target_first"], "stop_first": c["stop_first"],
                                   "ambiguous": c["ambiguous"], "neither": c["neither"]},
                    })
                    hit_rates.setdefault(h, {}).setdefault(t, {})[s] = cell
                    a = self._amb[(t, h, s)]
                    ambiguity.setdefault(h, {}).setdefault(t, {})[s] = {
                        "n_ambiguous": a["n_ambiguous"],
                        "as_if_target": {"n": a["as_if_target"]["n"], "sum_net": a["as_if_target"]["sum"].total(),
                                         "n_positive": a["as_if_target"]["n_positive"]},
                        "as_if_stop": {"n": a["as_if_stop"]["n"], "sum_net": a["as_if_stop"]["sum"].total(),
                                       "n_positive": a["as_if_stop"]["n_positive"]},
                    }
        return {
            "summary_version": accumulate.SUMMARY_VERSION,
            "n_rows": self.n_rows,
            "stats": stats,
            "hit_rates": hit_rates,
            "holding_period_histograms": holding,
            "ambiguity_legs": ambiguity,
            "segmentation": {"status": "NOT_COMPUTED",
                             "reason": "RANDOM_CONTROL_ENTERS_REPORT_AS_PER_SEED_MEANS"},
            # Identical to `accumulate.rows_digest(rows)["sha256"]` without ever holding the rows.
            # This is what makes the discarded rows RECOVERABLE rather than merely gone: the draw is
            # deterministic (`controls._random_control_picks` is sorted-population + seeded RNG), so
            # any seed can be regenerated and checked against this hash.
            "digest": {"sha256": self._hasher.hexdigest(), "row_count": self.n_rows},
            "streamed": True,
        }


def _median_from_histogram(hist: Mapping) -> Optional[float]:
    """`statistics.median` of the values the histogram counts, computed from counts alone.

    Exact, not approximate: the holding period is a bounded small integer, so the histogram IS the
    multiset. Matches `statistics.median`'s own even-length rule (mean of the two middle values).
    """
    total = sum(hist.values())
    if not total:
        return None
    keys = sorted(hist)
    mid = total // 2
    if total % 2:
        seen = 0
        for k in keys:
            seen += hist[k]
            if seen > mid:
                return float(k)
    lo = hi = None
    seen = 0
    for k in keys:
        seen += hist[k]
        if lo is None and seen >= mid:
            lo = k
        if seen >= mid + 1:
            hi = k
            break
    return (lo + hi) / 2
