"""Report generator -- CHARTING_PREREGISTRATION_V1 §7 "What the report must contain (all of
it, whatever the sign)". A PURE aggregator over already-built rows: it never loads bars, never
calls the detector/cost/regime layers itself, and never runs anything over real data on its
own -- every number it produces is a deterministic function of the rows it is handed (real
rows from a real run, or the synthetic fixtures this package's own tests use exclusively).

-- Row shapes this module reads (never mutates) ---------------------------------------------
  - Pattern/control rows: `research.charting.events.extraction`/`controls`'s own nested
    schema (`entry`, `outcomes`, `costs`, `stop`, `targets`, `tradability`, ...), optionally
    with a `context` block (`research.charting.events.context_join`).
  - "Returns" (item 2's gross/net, item 3's expectancy/profit-factor/drawdown) are read from
    `row["costs"]["by_horizon"][h]["scenarios"][scenario]` -- the CLOSE-OF-HORIZON-h exit,
    independent of whether a target/stop resolved first. This is the row's own headline
    per-horizon P&L figure (extraction.py builds it from `forward_returns[h]["exit_close"]`
    directly), distinct from target/stop hit rates (item 1's "gross hit rate ... per target"),
    which are read from `row["targets"][target_name]["by_horizon"][h]`.
  - "Net hit rate after costs" (item 2) is read literally: a target/stop resolution counts as
    a NET hit only when the resolved exit's own net-of-cost P&L (`exit.costs.scenarios[
    scenario].net_before_tax`) was positive, not merely when the raw price touched the target
    (that raw fact is the GROSS hit rate) -- see `hit_rate_table`'s own docstring for the full
    reasoning; the prereg text names both figures but does not spell out the arithmetic for
    "net hit rate", so this is a documented interpretation, not a guess left silent.
  - BEARISH rows carry no `costs`/`stop`/`targets` at all (§37.4: no trade is priced) -- every
    function here that reads those blocks silently skips a row that does not have them, and
    `bearish_directional_report` is the ONLY table BEARISH rows contribute to (§7.8).

Every rate/statistic below returns its own `n` alongside it (task instruction: "keep counts
next to rates") and marks a cell `insufficient_n` when `n < 30` (§7's own sample-size rule) --
`insufficient_n` cells are INCLUDED in the report, never dropped, and never fed into a
headline conclusion by this module (this module draws no conclusions at all; it only reports).
"""
from __future__ import annotations

import statistics
from typing import Any, Mapping, Optional, Sequence

import numpy as np

from research.charting import movement
from research.charting.events.schema import HORIZONS, R_MULTIPLES, TARGET_PCTS

MIN_N = 30  # §7's own sample-size rule

DEFAULT_TARGET_NAMES: tuple = tuple(f"pct_{round(p * 100)}" for p in TARGET_PCTS) + tuple(
    f"r_{str(m).replace('.', '_')}" for m in R_MULTIPLES
)  # reproduces stops.py's own (private) naming convention without importing its privates

DEFAULT_COST_SCENARIOS: tuple = ("optimistic", "base", "conservative", "stress")  # §36.3 / §7.9


# ── Small, honest statistics helpers (never silently coerce an empty sample to 0) ───────


def _mean(values: Sequence[float]) -> Optional[float]:
    return float(statistics.fmean(values)) if values else None


def _median(values: Sequence[float]) -> Optional[float]:
    return float(statistics.median(values)) if values else None


def n_cell(n: int) -> dict:
    """§7's own sample-size rule, attached to every cell that reports a rate/statistic:
    `{"n": n, "insufficient_n": n < 30}` -- the cell is still reported with its real n, never
    dropped, and this flag is the reader's own signal not to draw a conclusion from it."""
    return {"n": n, "insufficient_n": n < MIN_N}


def percentile_rank(value: Optional[float], distribution: Sequence[float]) -> Optional[float]:
    """Empirical percentile rank (0-100) of `value` within `distribution`: the percentage of
    the distribution AT OR BELOW `value`. `None` when `value` is `None` or `distribution` is
    empty -- never a fabricated 50.0."""
    if value is None or not distribution:
        return None
    arr = np.asarray(distribution, dtype=float)
    return float(np.mean(arr <= value) * 100.0)


# ── Row-field accessors (defensive: a BEARISH / unavailable row returns None, never raises) ──


def _horizon_cost_scenario(row: Mapping, horizon: int, scenario: str = "base") -> Optional[dict]:
    costs = row.get("costs") or {}
    by_h = costs.get("by_horizon") or {}
    block = by_h.get(horizon)
    if not block or not block.get("available"):
        return None
    return (block.get("scenarios") or {}).get(scenario)


def _forward_return_block(row: Mapping, horizon: int) -> Optional[dict]:
    outcomes = row.get("outcomes") or {}
    fwd = (outcomes.get("forward_returns") or {}).get(horizon)
    if not fwd or not fwd.get("available"):
        return None
    return fwd


def _directional_return_block(row: Mapping, horizon: int) -> Optional[dict]:
    outcomes = row.get("outcomes") or {}
    fwd = (outcomes.get("forward_returns_directional") or {}).get(horizon)
    if not fwd or not fwd.get("available"):
        return None
    return fwd


def _target_horizon_block(row: Mapping, target_name: str, horizon: int) -> Optional[dict]:
    targets = row.get("targets")
    if not targets:
        return None
    t = targets.get(target_name)
    if not t:
        return None
    block = (t.get("by_horizon") or {}).get(horizon)
    if not block or not block.get("available"):
        return None
    return block


def atr_pct_for_row(row: Mapping) -> Optional[float]:
    """ATR(t) / primary entry price -- the same volatility proxy the ATR-decile-matched
    control (`events.controls`) ranks on, reused here for the ATR-bucket segmentation."""
    atr_at_t = row.get("atr_at_t")
    entry = ((row.get("entry") or {}).get("primary")) or {}
    price = entry.get("price")
    if atr_at_t is None or price is None or price <= 0:
        return None
    return float(atr_at_t) / float(price)


# ── Item 1: n and exclusion counts ────────────────────────────────────────────────────────


def exclusion_table(exclusion_counts: Mapping[str, int]) -> dict:
    """§7.1: "n (signals), and counts excluded by reason (data quality, demerger window,
    insufficient forward bars, AMBIGUOUS)." `exclusion_counts` is the caller's own tally for
    the PRE-ROW exclusions (data quality / demerger window -- decided before a row is even
    built, so this module cannot recompute them from rows alone); "insufficient forward bars"
    and "AMBIGUOUS" are PER-HORIZON/PER-TARGET facts already visible on each row and are
    reported alongside each horizon/target cell instead (see `hit_rate_table`/`return_stats`),
    not duplicated here as a second, potentially-inconsistent count.
    """
    counts = dict(exclusion_counts)
    return {"excluded_by_reason": counts, "total_excluded": sum(counts.values())}


# ── Item 2: hit rates + first-exit shares (per target x horizon) ────────────────────────


def hit_rate_table(rows: Sequence[Mapping], target_name: str, horizon: int, *, scenario: str = "base") -> dict:
    """§7.2: gross/net hit rate per target, target-first/stop-first/AMBIGUOUS/neither shares.

    GROSS hit = the walk's own `first_exit_event == "TARGET"` (a pure price fact, before any
    cost is applied). NET hit = a resolved TARGET or STOP exit whose OWN net-of-cost P&L
    (`exit.costs.scenarios[scenario].net_before_tax`) was still positive -- i.e. "hit rate
    after costs" is read as "fraction of resolved trades that were still profitable net of
    costs", not "fraction that happened to touch the target price" a second time (see module
    docstring for why this reading was chosen). An AMBIGUOUS resolution never counts as either
    a gross or a net hit (an ambiguous bar's exit price/side is unknown by construction).
    """
    n = 0
    gross_hits = 0
    net_hits = 0
    target_first = stop_first = ambiguous = neither = 0
    holding_periods: list = []
    for row in rows:
        block = _target_horizon_block(row, target_name, horizon)
        if block is None:
            continue
        n += 1
        fe = block["first_exit_event"]
        if fe == "TARGET":
            target_first += 1
            gross_hits += 1
        elif fe == "STOP":
            stop_first += 1
        elif fe == "AMBIGUOUS":
            ambiguous += 1
        elif fe == "NONE":
            neither += 1
        exit_ = block.get("exit")
        if exit_ is not None:
            holding_periods.append(exit_["holding_period_sessions"])
            scen = ((exit_.get("costs") or {}).get("scenarios") or {}).get(scenario)
            if scen is not None and scen.get("available", True) and scen.get("net_before_tax") is not None and scen["net_before_tax"] > 0:
                net_hits += 1

    out = n_cell(n)
    out.update({
        "gross_hit_rate": (gross_hits / n) if n else None,
        "net_hit_rate": (net_hits / n) if n else None,
        "target_first_share": (target_first / n) if n else None,
        "stop_first_share": (stop_first / n) if n else None,
        "ambiguous_share": (ambiguous / n) if n else None,
        "neither_share": (neither / n) if n else None,
        "median_holding_period": _median(holding_periods),
        "counts": {"target_first": target_first, "stop_first": stop_first, "ambiguous": ambiguous, "neither": neither},
    })
    return out


# ── Items 3 + 4: returns, expectancy, profit factor, drawdown, MFE/MAE ──────────────────


def return_stats(rows: Sequence[Mapping], horizon: int, *, scenario: str = "base") -> dict:
    """§7.3: median/mean gross and net return, average cost, average slippage, net
    expectancy, profit factor, win rate, average win, average loss, maximum drawdown of the
    equal-weight event sequence -- all read from `costs.by_horizon[horizon].scenarios[
    scenario]` (the close-of-horizon exit, target/stop-independent; see module docstring).

    "Equal-weight event sequence": rows are ordered by `signal_date` (ties broken by
    `event_id` for full determinism) and each contributes ONE unit-weighted net-return
    observation to a cumulative sum -- the maximum drawdown of that cumulative-return curve
    (a documented, standard reading of "equal-weight event sequence": no compounding, no
    position sizing beyond the row's own fixed notional, ordered chronologically).
    """
    ordered = sorted(rows, key=lambda r: (r.get("signal_date") or "", r.get("event_id") or ""))
    gross_vals: list = []
    net_vals: list = []
    cost_vals: list = []
    slippage_vals: list = []
    for row in ordered:
        scen = _horizon_cost_scenario(row, horizon, scenario)
        if scen is None:
            continue
        gross_vals.append(scen["gross"])
        net_vals.append(scen["net_before_tax"])
        cost_vals.append(scen["total_cost"])
        entry_slip = scen.get("entry_slippage") or 0.0
        exit_slip = scen.get("exit_slippage") or 0.0
        slippage_vals.append(entry_slip + exit_slip)

    n = len(net_vals)
    out = n_cell(n)
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
        profit_factor = float("inf")  # no losing trade at all -- an unbounded, not a fabricated, figure
    else:
        profit_factor = None  # no winning trade either -- undefined, never guessed as 0

    equity_curve = np.cumsum(np.asarray(net_vals, dtype=float))
    running_max = np.maximum.accumulate(equity_curve)
    drawdown = equity_curve - running_max
    max_dd = float(drawdown.min())

    out.update({
        "gross_return": {"median": _median(gross_vals), "mean": _mean(gross_vals)},
        "net_return": {"median": _median(net_vals), "mean": _mean(net_vals)},
        "avg_cost": _mean(cost_vals),
        "avg_slippage": _mean(slippage_vals),
        "net_expectancy": _mean(net_vals),
        "profit_factor": profit_factor,
        "win_rate": len(wins) / n,
        "avg_win": _mean(wins) if wins else None,
        "avg_loss": _mean(losses) if losses else None,
        "max_drawdown": max_dd,
    })
    return out


def mfe_mae_stats(rows: Sequence[Mapping], horizon: int) -> dict:
    """§7.4: median MFE and median MAE, from `outcomes.forward_returns[horizon]` (available
    for BULLISH and BEARISH rows alike -- this is a raw price-path fact, not a priced trade)."""
    mfe_vals: list = []
    mae_vals: list = []
    for row in rows:
        fwd = _forward_return_block(row, horizon)
        if fwd is None:
            continue
        mfe_vals.append(fwd["mfe"])
        mae_vals.append(fwd["mae"])
    out = n_cell(len(mfe_vals))
    out.update({"median_mfe": _median(mfe_vals), "median_mae": _median(mae_vals)})
    return out


# ── Item 9: four-scenario cost-sensitivity table ─────────────────────────────────────────


def cost_sensitivity_table(rows: Sequence[Mapping], horizon: int, *, scenarios: Sequence[str] = DEFAULT_COST_SCENARIOS) -> dict:
    """§7.9 / §36.3: `return_stats` (every headline net number) recomputed under each of the
    four PRD slippage scenarios (optimistic 0.05%, base 0.15%, conservative 0.30%, stress
    0.50%)."""
    return {scenario: return_stats(rows, horizon, scenario=scenario) for scenario in scenarios}


# ── Item 8: BEARISH rows -- directional forward returns + MFE/MAE only ──────────────────


def bearish_directional_report(rows: Sequence[Mapping], horizon: int) -> dict:
    """§7.8: BEARISH rows are validated on their directional forward returns and MFE/MAE
    only -- no trade is priced (§37.4), so no hit-rate/cost/expectancy table is built for
    them. `directional_return` is `forward_returns_directional[horizon]`'s own
    `close_return_directional` (already sign-flipped for a short-perspective "avoid new
    long" call -- see `events.outcomes` module docstring)."""
    bearish = [r for r in rows if r.get("direction") == "BEARISH"]
    directional_vals: list = []
    for row in bearish:
        d = _directional_return_block(row, horizon)
        if d is not None:
            directional_vals.append(d["close_return_directional"])
    out = n_cell(len(directional_vals))
    out.update({
        "directional_return": {"median": _median(directional_vals), "mean": _mean(directional_vals)},
        **mfe_mae_stats(bearish, horizon),
    })
    return out


# ── Item 6: comparison groups + percentile-within-distribution ──────────────────────────


def comparison_block(
    pattern_rows: Sequence[Mapping], horizon: int, *,
    random_batch: Optional[Mapping[int, Sequence[Mapping]]] = None,
    atr_decile_rows: Optional[Sequence[Mapping]] = None,
    buy_next_open_rows: Optional[Sequence[Mapping]] = None,
    nifty_500_return: Optional[float] = None,
    scenario: str = "base",
) -> dict:
    """§7.6: the pattern rows plus (ii) the 200-seed random control, (iii) buy-at-next-open,
    (iv) the ATR-decile-matched control, (v) NIFTY 500 -- "same measures", plus the pattern
    rows' own percentile within the random and ATR-matched distributions.

    The random control's distribution is taken PER-SEED (one mean net return per seed, 200
    values) -- matching the 200-seed batch's own purpose (a sampling distribution of the
    comparison, not one 200x-larger pooled sample). The ATR-decile control's distribution is
    taken PER-ROW (each matched control row's own net return) since it is already matched
    1:1 (or 1:n_per_event) to a specific pattern event, not resampled.
    """
    pattern_stats = return_stats(pattern_rows, horizon, scenario=scenario)
    out: dict = {"pattern": pattern_stats}

    if random_batch:
        seed_means: list = []
        for _seed, seed_rows in random_batch.items():
            st = return_stats(seed_rows, horizon, scenario=scenario)
            if st["n"] > 0:
                seed_means.append(st["net_return"]["mean"])
        out["random_200_seed"] = {
            "n_seeds_with_data": len(seed_means),
            "n_seeds_total": len(random_batch),
            "mean_of_seed_means": _mean(seed_means),
            "median_of_seed_means": _median(seed_means),
            "pattern_percentile_within_seed_distribution": (
                percentile_rank(pattern_stats["net_return"]["mean"], seed_means) if pattern_stats["n"] else None
            ),
        }

    if atr_decile_rows is not None:
        atr_stats = return_stats(atr_decile_rows, horizon, scenario=scenario)
        atr_row_net_returns = [
            v for v in (
                (_horizon_cost_scenario(r, horizon, scenario) or {}).get("net_before_tax") for r in atr_decile_rows
            ) if v is not None
        ]
        out["atr_decile_matched"] = {
            **atr_stats,
            "pattern_percentile_within_distribution": (
                percentile_rank(pattern_stats["net_return"]["mean"], atr_row_net_returns) if pattern_stats["n"] else None
            ),
        }

    if buy_next_open_rows is not None:
        out["buy_next_open"] = return_stats(buy_next_open_rows, horizon, scenario=scenario)

    if nifty_500_return is not None:
        out["nifty_500"] = {"return": nifty_500_return}

    return out


# ── Item 7: segmentation ─────────────────────────────────────────────────────────────────


def liquidity_bucket_label(adv_inr: Optional[float], buckets: Optional[Sequence] = None) -> str:
    """`LIQUIDITY_BUCKET_0` (most liquid) .. `LIQUIDITY_BUCKET_{n-1}` (least liquid), reusing
    the FROZEN ADV floor table the cost engine's own liquidity-bucket slippage model already
    uses (`events.schema.default_liquidity_buckets()`) -- not a new, independently-invented
    threshold. `"UNKNOWN"` when `adv_inr` itself is unavailable."""
    if adv_inr is None:
        return "UNKNOWN"
    if buckets is None:
        from research.charting.events import schema
        buckets = schema.default_liquidity_buckets()
    ordered = sorted(((float(floor), float(pct)) for floor, pct in buckets), key=lambda b: b[0], reverse=True)
    v = float(adv_inr)
    for i, (floor, _pct) in enumerate(ordered):
        if v >= floor:
            return f"LIQUIDITY_BUCKET_{i}"
    return f"LIQUIDITY_BUCKET_{len(ordered) - 1}"


def atr_bucket_labels(rows: Sequence[Mapping]) -> dict:
    """`{event_id: "LOW_VOL"|"MID_VOL"|"HIGH_VOL"|"UNKNOWN"}` -- IN-SAMPLE terciles of
    `atr_pct_for_row` computed across `rows` themselves. Unlike the liquidity buckets above,
    no PRD-frozen absolute ATR% band exists anywhere in this package (only the ATR-DECILE
    control's own per-date deciles, which are a matching mechanism, not a labelling scheme) --
    this is therefore a documented, per-report-cell in-sample split, not a universal frozen
    threshold. Fewer than 3 rows with a computable ATR% -> every row `"UNKNOWN"` (a tercile
    split is not meaningful below that)."""
    pairs = [(r.get("event_id"), atr_pct_for_row(r)) for r in rows]
    valid = [(eid, v) for eid, v in pairs if v is not None]
    if len(valid) < 3:
        return {eid: "UNKNOWN" for eid, _v in pairs}
    values = np.asarray([v for _eid, v in valid], dtype=float)
    edges = np.quantile(values, [1 / 3, 2 / 3])
    labels: dict = {}
    for eid, v in pairs:
        if v is None:
            labels[eid] = "UNKNOWN"
            continue
        idx = int(np.searchsorted(edges, v, side="right"))
        labels[eid] = ("LOW_VOL", "MID_VOL", "HIGH_VOL")[idx]
    return labels


def context_label(row: Mapping, key: str, *, default: str = "NO_CONTEXT") -> str:
    ctx = row.get("context") or {}
    val = ctx.get(key)
    return val if val is not None else default


def segment_rows(rows: Sequence[Mapping], *, dimension: str) -> dict:
    """Group `rows` by one segmentation dimension (§7.7): `"liquidity_bucket"`,
    `"atr_bucket"`, `"stock_trend_class"`, `"market_trend_class"`, or `"regime"`. Returns
    `{bucket_label: [rows]}`. A row missing the information a dimension needs (no
    `context` block attached, e.g.) goes into `"NO_CONTEXT"`/`"UNKNOWN"` rather than being
    silently dropped from the segmentation entirely."""
    if dimension == "liquidity_bucket":
        key_fn = lambda r: liquidity_bucket_label((r.get("liquidity") or {}).get("adv_inr_at_t"))
    elif dimension == "atr_bucket":
        labels = atr_bucket_labels(rows)
        key_fn = lambda r: labels.get(r.get("event_id"), "UNKNOWN")
    elif dimension == "stock_trend_class":
        key_fn = lambda r: context_label(r, "trend_class_class")
    elif dimension == "market_trend_class":
        key_fn = lambda r: context_label(r, "market_trend_class_class")
    elif dimension == "regime":
        key_fn = lambda r: context_label(r, "regime_regime")
    else:
        raise ValueError(f"unknown segmentation dimension {dimension!r}")

    out: dict = {}
    for row in rows:
        out.setdefault(key_fn(row), []).append(row)
    return out


SEGMENTATION_DIMENSIONS: tuple = ("liquidity_bucket", "atr_bucket", "stock_trend_class", "market_trend_class", "regime")


def segmentation_report(rows: Sequence[Mapping], horizon: int, *, target_name: Optional[str] = None) -> dict:
    """§7.7: every segmentation dimension for one (family, horizon) cell -- `return_stats`
    per bucket, plus `hit_rate_table` per bucket when `target_name` is given (target/stop
    measures are per-target; return measures are per-horizon only -- same split the rest of
    this module uses)."""
    out: dict = {}
    for dim in SEGMENTATION_DIMENSIONS:
        buckets = segment_rows(rows, dimension=dim)
        dim_out: dict = {}
        for label, bucket_rows in buckets.items():
            cell = {"returns": return_stats(bucket_rows, horizon)}
            if target_name is not None:
                cell["hit_rate"] = hit_rate_table(bucket_rows, target_name, horizon)
            dim_out[label] = cell
        out[dim] = dim_out
    return out


# ── Item 5: move_auc / direction_auc (reuse movement.py) ────────────────────────────────


def move_direction_auc_report(pattern_rows: Sequence[Mapping], bars_by_symbol: Mapping, horizons: Sequence[int] = HORIZONS) -> dict:
    """§7.5: `move_auc`/`direction_auc` per (family, horizon), reusing `movement.py` (task
    instruction: "reuse movement.py") rather than reimplementing the AUC computation. Each
    pattern row is adapted into the minimal `(symbol, snapshot_dict)` shape
    `movement.movement_vs_direction_report` already accepts (it only reads `pattern_type`,
    `direction`, and a `PRICE_CONFIRMED` event's `date` off the snapshot -- see that module's
    own `_normalize_item`), so this package's own richer row is never force-fit into a real
    `PatternSnapshot`, only the 3 fields that function actually reads.
    """
    items = [
        (row["symbol"], {
            "pattern_id": row["pattern_id"],
            "pattern_type": row["pattern_type"],
            "direction": row["direction"],
            "events": [{"event_type": "PRICE_CONFIRMED", "date": row["signal_date"]}],
        })
        for row in pattern_rows
    ]
    raw = movement.movement_vs_direction_report(items, bars_by_symbol, horizons=horizons)
    return {(fh.family, fh.horizon): fh.to_dict() for fh in raw.values()}


# ── Top-level assembly ────────────────────────────────────────────────────────────────────


def build_family_horizon_cell(
    pattern_rows: Sequence[Mapping], horizon: int, *,
    target_names: Sequence[str] = DEFAULT_TARGET_NAMES,
    comparisons: Optional[dict] = None,
    move_direction: Optional[dict] = None,
) -> dict:
    """One (family, horizon) cell for BULLISH (long-actionable) rows: returns, MFE/MAE,
    cost-sensitivity, per-target hit-rate tables, segmentation, comparisons, move/direction
    AUC -- items 2-4, 7 and 9 (item 6 passed in pre-computed; item 5 passed in pre-computed).
    """
    bullish = [r for r in pattern_rows if r.get("direction") == "BULLISH"]
    cell: dict = {
        "n": n_cell(len(bullish)),
        "returns": return_stats(bullish, horizon),
        "mfe_mae": mfe_mae_stats(bullish, horizon),
        "cost_sensitivity": cost_sensitivity_table(bullish, horizon),
        "targets": {name: hit_rate_table(bullish, name, horizon) for name in target_names},
        "segmentation": segmentation_report(bullish, horizon, target_name=target_names[0] if target_names else None),
    }
    if comparisons is not None:
        cell["comparisons"] = comparisons
    if move_direction is not None:
        cell["move_auc"] = move_direction.get("move_auc")
        cell["move_n"] = move_direction.get("move_n")
        cell["move_reason"] = move_direction.get("move_reason")
        cell["direction_auc"] = move_direction.get("direction_auc")
        cell["direction_n"] = move_direction.get("direction_n")
        cell["direction_reason"] = move_direction.get("direction_reason")
    return cell


def build_report(
    *, segment: str, pattern_rows: Sequence[Mapping], bars_by_symbol: Mapping,
    exclusion_counts: Mapping[str, int], horizons: Sequence[int] = HORIZONS,
    target_names: Sequence[str] = DEFAULT_TARGET_NAMES,
    comparison_groups_by_family: Optional[Mapping[str, dict]] = None,
    universe_caveats: Sequence[str] = (),
    unverified_cost_rates: Sequence[str] = (),
    input_hashes: Optional[Mapping[str, str]] = None,
    prereg_sha256: Optional[str] = None,
) -> dict:
    """Assemble the full §7 report for one segment, across every pattern family present in
    `pattern_rows`. `comparison_groups_by_family`: `{family: {"random_batch":..,
    "atr_decile_rows":.., "buy_next_open_rows":.., "nifty_500_return_by_horizon": {h: ret}}}`
    -- built by the caller (`study/run.py`, or a test) since assembling the comparison-group
    ROWS themselves needs bars/regime/cost machinery this module deliberately never touches
    (see module docstring: "a PURE aggregator").

    No family, horizon, target or sign is ever dropped for being unfavourable (prereg §1/§7:
    "never because a number is favourable") -- every family present in `pattern_rows`, BULLISH
    or BEARISH, gets a cell.
    """
    families = sorted({r["pattern_type"] for r in pattern_rows})
    families_out: dict = {}
    for family in families:
        family_rows = [r for r in pattern_rows if r["pattern_type"] == family]
        bullish_rows = [r for r in family_rows if r.get("direction") == "BULLISH"]
        bearish_rows = [r for r in family_rows if r.get("direction") == "BEARISH"]

        cg = (comparison_groups_by_family or {}).get(family, {})
        move_direction = move_direction_auc_report(family_rows, bars_by_symbol, horizons=horizons)

        horizons_out: dict = {}
        for h in horizons:
            comparisons = None
            if cg:
                comparisons = comparison_block(
                    bullish_rows, h,
                    random_batch=cg.get("random_batch"),
                    atr_decile_rows=cg.get("atr_decile_rows"),
                    buy_next_open_rows=cg.get("buy_next_open_rows"),
                    nifty_500_return=(cg.get("nifty_500_return_by_horizon") or {}).get(h),
                )
            cell = build_family_horizon_cell(
                bullish_rows, h, target_names=target_names, comparisons=comparisons,
                move_direction=move_direction.get((family, h)),
            )
            cell["bearish"] = bearish_directional_report(bearish_rows, h)
            horizons_out[h] = cell

        families_out[family] = {
            "n_total": n_cell(len(family_rows)),
            "n_bullish": len(bullish_rows),
            "n_bearish": len(bearish_rows),
            "horizons": horizons_out,
        }

    return {
        "segment": segment,
        "prereg_sha256": prereg_sha256,
        "universe_caveats": list(universe_caveats),
        "unverified_cost_rates": list(unverified_cost_rates),
        "input_hashes": dict(input_hashes) if input_hashes else {},
        "exclusions": exclusion_table(exclusion_counts),
        "families": families_out,
    }


# ── Output: JSON (strict, no NaN/Infinity) + Markdown rendering ─────────────────────────


def _json_safe(obj: Any) -> Any:
    """Strict-JSON-safe recursive copy: NaN/+-Infinity -> `null` (mirrors
    `events.writer._finite_or_none`'s identical contract, reimplemented locally rather than
    importing that module's private helper -- see item 3's own "strict JSON" requirement)."""
    if isinstance(obj, float) and not np.isfinite(obj):
        return None
    if isinstance(obj, dict):
        return {(str(k) if not isinstance(k, str) else k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


def to_json_dict(report: Mapping) -> dict:
    """`report` with every NaN/Infinity replaced by `null` and every dict key coerced to a
    string (horizon keys are plain ints in the in-memory report -- JSON object keys must be
    strings) -- ready for `json.dumps(..., allow_nan=False)`."""
    return _json_safe(report)


def _fmt(x: Any) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, float):
        if not np.isfinite(x):
            return "inf" if x > 0 else ("-inf" if x < 0 else "nan")
        return f"{x:.4f}"
    return str(x)


def render_markdown(report: Mapping) -> str:
    """A readable Markdown rendering of `build_report`'s own output -- every number traceable
    to the `n`/`insufficient_n` sitting right next to it (task instruction: "keep counts next
    to rates"). Not a substitute for the JSON (`to_json_dict`); a human-readable companion."""
    lines: list = []
    lines.append(f"# Chart-pattern validation report -- segment `{report.get('segment')}`")
    lines.append("")
    lines.append(f"prereg_sha256: `{report.get('prereg_sha256')}`")
    lines.append("")
    if report.get("universe_caveats"):
        lines.append("## Universe caveats")
        for c in report["universe_caveats"]:
            lines.append(f"- {c}")
        lines.append("")
    if report.get("unverified_cost_rates"):
        lines.append("## Unverified cost rates")
        for c in report["unverified_cost_rates"]:
            lines.append(f"- {c}")
        lines.append("")
    excl = report.get("exclusions") or {}
    lines.append("## Exclusions")
    lines.append(f"Total excluded: {excl.get('total_excluded')}")
    for reason, count in (excl.get("excluded_by_reason") or {}).items():
        lines.append(f"- {reason}: {count}")
    lines.append("")

    for family, family_report in (report.get("families") or {}).items():
        lines.append(f"## {family}")
        n_total = family_report["n_total"]
        lines.append(f"n = {n_total['n']} (insufficient_n={n_total['insufficient_n']}), "
                      f"bullish={family_report['n_bullish']}, bearish={family_report['n_bearish']}")
        lines.append("")
        for h, cell in (family_report.get("horizons") or {}).items():
            lines.append(f"### Horizon {h}")
            ret = cell["returns"]
            lines.append(f"- n={ret['n']} insufficient_n={ret['insufficient_n']}")
            lines.append(f"- gross return median/mean: {_fmt(ret['gross_return']['median'])} / {_fmt(ret['gross_return']['mean'])}")
            lines.append(f"- net return median/mean: {_fmt(ret['net_return']['median'])} / {_fmt(ret['net_return']['mean'])}")
            lines.append(f"- avg cost: {_fmt(ret['avg_cost'])}  avg slippage: {_fmt(ret['avg_slippage'])}")
            lines.append(f"- net expectancy: {_fmt(ret['net_expectancy'])}  profit factor: {_fmt(ret['profit_factor'])}")
            lines.append(f"- win rate: {_fmt(ret['win_rate'])}  avg win: {_fmt(ret['avg_win'])}  avg loss: {_fmt(ret['avg_loss'])}")
            lines.append(f"- max drawdown (equal-weight sequence): {_fmt(ret['max_drawdown'])}")
            mm = cell["mfe_mae"]
            lines.append(f"- median MFE/MAE: {_fmt(mm['median_mfe'])} / {_fmt(mm['median_mae'])} (n={mm['n']})")
            lines.append(f"- move_auc: {_fmt(cell.get('move_auc'))} (n={cell.get('move_n')})  "
                          f"direction_auc: {_fmt(cell.get('direction_auc'))} (n={cell.get('direction_n')})")
            lines.append("")
            lines.append("| target | n | insufficient_n | gross_hit | net_hit | target_first | stop_first | ambiguous | neither | median_holding |")
            lines.append("|---|---|---|---|---|---|---|---|---|---|")
            for name, t in (cell.get("targets") or {}).items():
                lines.append(
                    f"| {name} | {t['n']} | {t['insufficient_n']} | {_fmt(t['gross_hit_rate'])} | {_fmt(t['net_hit_rate'])} "
                    f"| {_fmt(t['target_first_share'])} | {_fmt(t['stop_first_share'])} | {_fmt(t['ambiguous_share'])} "
                    f"| {_fmt(t['neither_share'])} | {_fmt(t['median_holding_period'])} |"
                )
            lines.append("")
            bear = cell.get("bearish") or {}
            lines.append(f"BEARISH: n={bear.get('n')} insufficient_n={bear.get('insufficient_n')} "
                          f"directional_return median/mean={_fmt((bear.get('directional_return') or {}).get('median'))}"
                          f"/{_fmt((bear.get('directional_return') or {}).get('mean'))} "
                          f"MFE/MAE median={_fmt(bear.get('median_mfe'))}/{_fmt(bear.get('median_mae'))}")
            lines.append("")

    return "\n".join(lines)
