"""AI Trader Phase 2, the Strategy Architect (docs/prd/AI_TRADER_PHASES_2_5.prd.md F2.2-F2.6).

What it does: reads the Phase 1 market evidence, picks one of the repo's DSL templates from the market regime,
resolves a frozen `NiveshConfig`, versions the pair, runs backtests through an injected runner (production:
`services.strategy_engine.backtest.run_backtest`), splits the window into walk-forward folds, and scores the
promotion gates for the ladder draft -> backtested -> paper -> assisted (plus retired).

What it refuses to do:
  * no order, anywhere. This module imports no broker client and no execution code.
  * no default template. Without OK regime evidence it raises `StrategyError("regime_unavailable")` rather than
    guessing a market view.
  * no free-written rules (assumption B1). The AI chooses among the repo's templates; it does not invent predicates.
  * no reading of the sealed 2023-01-01..2024-07-31 research block, except through one explicit `holdout` run per
    strategy, which is recorded and can never be repeated (assumption B4). The dates come from
    `research.charting.research_window`, the project's single source of truth, never copied in here.
  * no stage skipped and no gate waived by a caller. `promote` moves exactly one stage and only on a clean sheet.

Gate thresholds are assumption B3 and are module constants below so one edit changes them everywhere.

Which numbers a gate may read is itself a rule, in `_gate_run`: the sealed-block holdout run is never promotion
evidence, and the move to assisted measures the win-rate gap against the run that earned paper rather than
against whatever ran last.

Four deliberate deviations from B3 as written, the first two because B3's wording would let a meaningless run
through, the last two because B3's wording does not hold against the engine that reports the numbers:
  * draft -> backtested asks for "a stored backtest run". A run that measured nothing is not evidence, so the gate
    also requires the stored metrics to carry a numeric `trade_count` of at least `MIN_RUN_TRADE_COUNT` and refuses
    a `reason="no_data"` run. B3 as written passes both of those.
  * the profit-factor criterion passes on a `None` profit factor in the one case where the engine means "there were
    no losses to divide by": zero losing trades and a positive total return (`_compute_metrics` returns None when
    total_loss is 0). Every other missing or non-numeric profit factor still fails.
  * B3's universe criterion is written as a single banned label. It is implemented as an allowlist of the bases the
    providers actually prove point-in-time, because the banned label is only one of several names the same
    survivorship bias goes by (see `ACCEPTED_UNIVERSE_BASIS`).
  * B3's drawdown and return thresholds are percentages of the portfolio, and the engine's percentages are not
    (see `_portfolio_pct_row`). The thresholds stand; the two rows refuse to pass until a run says its percentages
    are percentages of capital. Nothing says that today, so no strategy reaches paper on a real engine run, which
    is a hold the owner has to resolve (PRD section 11) rather than a number quietly moved to fit.
"""
from __future__ import annotations

import copy
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from services.strategy_engine.dsl import validate_strategy

from . import _research
from .config import resolve

STAGES = ("draft", "backtested", "paper", "assisted", "retired")
# The ladder a promotion walks. "retired" is off the ladder: it is an end state, not a rung.
LADDER = ("draft", "backtested", "paper", "assisted")

TEMPLATES_BY_REGIME = {"BULL": "momentum_breakout", "SIDEWAYS": "mean_reversion", "BEAR": "accumulation"}

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "strategy_engine" / "templates"

CREATED_BY = "ai"
VERSION_HASH_CHARS = 16

# ── Gate thresholds (PRD assumption B3; the owner has not confirmed them) ───────────────────────────────────────
FOLD_COUNT = 4
MIN_POSITIVE_FOLDS = 3
MIN_RUN_TRADE_COUNT = 1               # a stored run counts as a run only once it has measured at least this much
NO_DATA_REASON = "no_data"            # what the engine puts in metrics when the window had no feature snapshots
MIN_BACKTEST_TRADES = 100
MIN_PROFIT_FACTOR = 1.3
MIN_MAX_DRAWDOWN_PCT = -25.0          # drawdown is reported negative; -30 is worse than this floor
MIN_TOTAL_RETURN_PCT = 0.0
# An allowlist, not a denylist. `strategy_engine.market_data` can report exactly five universe bases:
# "point_in_time" and "present_day_fallback" (SqlMarketDataProvider.prepare), "latest_snapshot" and
# "custom_universe" (DaasMarketDataProvider.prepare) and the pre-prepare default "unknown" on both. Only two of
# them are free of membership look-ahead: "point_in_time" reads nidp.index_constituents as of each bar, and
# "custom_universe" is the caller's own stored symbol list, where the engine infers no membership at all.
# "latest_snapshot" is today's index membership applied across the whole window, the same survivorship bias as
# "present_day_fallback" under another name, and it is what staging and production report, so a denylist of one
# literal let every real run through. Anything unknown, empty or new fails until somebody proves what it means.
ACCEPTED_UNIVERSE_BASIS = ("point_in_time", "custom_universe")
# What `metrics["sizing_basis"]` must say before a percent-of-capital row can pass. See `_portfolio_pct_row`.
PORTFOLIO_SIZING_BASIS = "portfolio"
MIN_PAPER_CLOSED_TRADES = 20
MIN_PAPER_EXPECTANCY = 0.0
MIN_PAPER_PROFIT_FACTOR = 1.2
MAX_WIN_RATE_GAP_PTS = 15.0

Runner = Callable[..., Awaitable[Any]]


class StrategyError(ValueError):
    pass


class GateNotMet(ValueError):
    """A promotion refused by the gates. `.unmet` carries the failing rows exactly as `evaluate_gates` built them,
    so the caller can show the value and the threshold rather than a bare refusal."""

    def __init__(self, target_stage: str, unmet: List[Dict[str, Any]]):
        super().__init__(f"{target_stage}: " + ", ".join(str(r.get("code")) for r in unmet))
        self.target_stage = target_stage
        self.unmet = unmet


class SealedWindowRefused(ValueError):
    pass


class HoldoutUsed(ValueError):
    pass


@dataclass(frozen=True)
class Gate:
    code: str
    label: str
    threshold: Any


GATES: Dict[str, Tuple[Gate, ...]] = {
    "backtested": (
        Gate("backtest_run", "Trades measured by the stored backtest run, at least", MIN_RUN_TRADE_COUNT),
    ),
    "paper": (
        Gate("trade_count", "Backtest trades", MIN_BACKTEST_TRADES),
        Gate("profit_factor", "Backtest profit factor", MIN_PROFIT_FACTOR),
        Gate("max_drawdown_pct", "Backtest max drawdown, percent, no worse than", MIN_MAX_DRAWDOWN_PCT),
        Gate("total_return_pct", "Backtest total return, percent, above", MIN_TOTAL_RETURN_PCT),
        Gate("walk_forward_positive_folds", f"Walk-forward folds with a positive return, of {FOLD_COUNT}",
             MIN_POSITIVE_FOLDS),
        Gate("universe_basis", "Universe membership basis must be one of", ACCEPTED_UNIVERSE_BASIS),
    ),
    "assisted": (
        Gate("paper_closed_trades", "Closed paper trades", MIN_PAPER_CLOSED_TRADES),
        Gate("paper_expectancy", "Net paper expectancy above", MIN_PAPER_EXPECTANCY),
        Gate("paper_profit_factor", "Paper profit factor", MIN_PAPER_PROFIT_FACTOR),
        Gate("win_rate_gap", "Paper win rate within this many points of the backtest's", MAX_WIN_RATE_GAP_PTS),
    ),
}


# ── small helpers ───────────────────────────────────────────────────────────────────────────────────────────────
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gate(stage: str, code: str) -> Gate:
    for g in GATES[stage]:
        if g.code == code:
            return g
    raise KeyError(f"no gate {code!r} on stage {stage!r}")        # a programming error, not caller input


def _row(gate: Gate, value: Any, passed: bool) -> Dict[str, Any]:
    return {"code": gate.code, "label": gate.label, "value": value, "threshold": gate.threshold,
            "passed": bool(passed)}


def _num(value: Any) -> Optional[float]:
    """The value as a float, or None when it is missing or not a number. A missing metric never counts as a pass:
    booleans are rejected too, so a True cannot stand in for a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _get(item: Any, name: str) -> Any:
    """Evidence arrives either as the frozen record or as its `to_dict()` form (over the route layer), so read both."""
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError as e:
            raise StrategyError(f"bad_date: {value!r}") from e
    raise StrategyError(f"bad_date: {value!r}")


def _metrics_of(result: Any) -> Dict[str, Any]:
    """`run_backtest` returns a `BacktestResult`; an injected runner may return the same shape as a plain dict."""
    if isinstance(result, dict):
        return dict(result.get("metrics") or {})
    metrics = getattr(result, "metrics", None)
    if metrics is None:
        raise StrategyError("runner_returned_no_metrics")
    return dict(metrics)


def _gate_runs(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The stored runs a gate may read, oldest first. The one-shot sealed-block run is not one of them: it is a
    final report (assumption B4), and a promotion scored on it would make the sealed out-of-sample block the
    selection basis, which is exactly what sealing it prevents."""
    return [r for r in (doc.get("runs") or []) if isinstance(r, dict) and not r.get("holdout")]


# ── templates and proposals ────────────────────────────────────────────────────────────────────────────────────
def load_template(name: str) -> Dict[str, Any]:
    """The DSL template `name` from services/strategy_engine/templates. The name is checked rather than joined
    blindly: it reaches here from a regime label, and a path fragment must not be able to read another file."""
    if not isinstance(name, str) or not name.replace("_", "").isalnum():
        raise StrategyError("unknown_template")
    path = TEMPLATE_DIR / f"{name}.json"
    if not path.is_file():
        raise StrategyError("unknown_template")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _regime_evidence(market_evidence: Sequence[Any]) -> Tuple[Any, str]:
    """The first OK market-intelligence item that actually carries a regime value, with that value."""
    for item in market_evidence or ():
        if _get(item, "skill") != "market_intelligence" or _get(item, "status") != "OK":
            continue
        reg = (_get(item, "data") or {}).get("regime")
        if isinstance(reg, dict) and reg.get("value"):
            return item, str(reg["value"])
    raise StrategyError("regime_unavailable")


def _spec_name(base: str, regime: str, as_of: Any) -> str:
    return f"AI {base} ({regime} {as_of})"[:100]


def propose(market_evidence: Sequence[Any], *, symbols: Sequence[str], ui_config: Optional[Dict[str, Any]] = None,
            strategy_info: Optional[Callable[[Any], None]] = None) -> Dict[str, Any]:
    """A strategy proposal from the market evidence: template by regime, frozen config, and the evidence used.

    Raises `StrategyError("regime_unavailable")` when no OK regime evidence is present. There is deliberately no
    fallback template: a strategy proposed without a market view would be a guess wearing the evidence's clothes.
    """
    item, regime = _regime_evidence(market_evidence)
    template = TEMPLATES_BY_REGIME.get(regime)
    if template is None:
        raise StrategyError("unknown_regime")

    spec = load_template(template)
    as_of = _get(item, "as_of")
    spec["name"] = _spec_name(str(spec.get("name") or template), regime, as_of)

    # The template's own index universe is kept. `symbols` is the config's universe for sizing and reporting; the DSL
    # `custom` universe type takes a stored universe id, not a symbol list, so symbols cannot be inlined into a spec.
    # That gap is recorded in the provenance below rather than papered over: a caller who asked for two symbols must
    # be able to see that the backtest ran the template's whole index.
    cfg = resolve(symbols, ui_config, strategy_info)

    errs = validate_strategy(spec)
    if errs:
        raise StrategyError("invalid_spec: " + "; ".join(str(e) for e in errs))

    return {
        "spec": spec,
        "config": cfg.to_dict(),
        "template": template,
        "regime": regime,
        "provenance": {
            "as_of": as_of,
            "regime_evidence": {
                "skill": _get(item, "skill"), "as_of": as_of, "horizon": _get(item, "horizon"),
                "observation": _get(item, "observation"), "confidence": _get(item, "confidence"),
                "calibrated": _get(item, "calibrated"), "sources": _get(item, "sources") or [],
            },
            "evidence_considered": len(market_evidence or ()),
            "unavailable": [_get(e, "reason_code") for e in (market_evidence or ())
                            if _get(e, "status") == "UNAVAILABLE"],
            "universe": {
                "backtest_universe": copy.deepcopy(spec["universe"]),
                "requested_symbols": list(cfg.symbols),
                "note": ("The backtest and any screen run on the template's index universe shown here. The "
                         "requested symbols constrain NiveshConfig only and do not narrow the strategy: the DSL "
                         "custom universe takes a stored universe id, not a symbol list. Open question for the "
                         "product owner."),
            },
        },
    }


def spec_version(spec: Dict[str, Any], config: Dict[str, Any]) -> str:
    """A stable short hash of the spec and the resolved config. Canonical JSON with sorted keys, so the same pair
    always gives the same version and any edit to either gives a different one."""
    blob = json.dumps({"spec": spec, "config": config}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:VERSION_HASH_CHARS]


def new_strategy(user_id: str, proposal: Dict[str, Any], name: Optional[str] = None) -> Dict[str, Any]:
    """The Mongo document for a proposal, at stage draft. Written by the route; nothing here touches a database."""
    if not isinstance(user_id, str) or not user_id.strip():
        raise StrategyError("bad_user_id")
    if not isinstance(proposal, dict) or any(k not in proposal for k in ("spec", "config", "template", "regime")):
        raise StrategyError("bad_proposal")
    if name is not None and (not isinstance(name, str) or not name.strip()):
        raise StrategyError("bad_name")

    spec = copy.deepcopy(proposal["spec"])
    config = copy.deepcopy(proposal["config"])
    stamp = _now_iso()
    return {
        "_id": str(uuid.uuid4()),
        "user_id": user_id,
        "name": (name or spec.get("name") or proposal["template"]).strip(),
        "created_by": CREATED_BY,
        "stage": "draft",
        "version": spec_version(spec, config),
        "spec": spec,
        "config": config,
        "template": proposal["template"],
        "regime": proposal["regime"],
        "provenance": copy.deepcopy(proposal.get("provenance") or {}),
        "runs": [],
        "holdout_used": False,
        "paper_stats": None,
        "stage_history": [{"stage": "draft", "at": stamp, "by": CREATED_BY, "from": None, "gates": []}],
        "created_at": stamp,
        "updated_at": stamp,
    }


# ── walk-forward folds ─────────────────────────────────────────────────────────────────────────────────────────
def folds(from_date: date, to_date: date, n: int = FOLD_COUNT) -> List[Tuple[date, date]]:
    """`n` contiguous, non-overlapping date ranges covering from_date..to_date inclusive, oldest first.

    Days rarely divide evenly, so the remainder goes to the earliest folds, one day each. Nothing is dropped: the
    folds together are exactly the window, because a walk-forward report that quietly skipped days would overstate
    the cover it gives."""
    start, end = _as_date(from_date), _as_date(to_date)
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise StrategyError("bad_fold_count")
    if start > end:
        raise StrategyError("bad_window")
    span = (end - start).days + 1
    if span < n:
        raise StrategyError("window_too_short_for_folds")

    base, extra = divmod(span, n)
    out: List[Tuple[date, date]] = []
    cursor = start
    for i in range(n):
        length = base + (1 if i < extra else 0)
        stop = cursor + timedelta(days=length - 1)
        out.append((cursor, stop))
        cursor = stop + timedelta(days=1)
    return out


# ── backtesting ────────────────────────────────────────────────────────────────────────────────────────────────
def _resolved_config(config: Dict[str, Any]):
    """Re-resolve the stored config so the run records a validated, frozen config rather than a loose dict."""
    custom = dict(config.get("custom") or {})

    def strategy_info(cfg) -> None:
        for key, value in custom.items():
            setattr(cfg, key, value)

    ui = {k: config[k] for k in ("initial_capital", "commission_pct", "pyramiding", "short_margin_pct")
          if k in config}
    return resolve(config.get("symbols") or (), ui, strategy_info)


async def run_backtest_for(doc: Dict[str, Any], *, from_date: Any, to_date: Any, runner: Runner,
                           holdout: bool = False, pool: Any = None) -> Dict[str, Any]:
    """Run the full window and each walk-forward fold through `runner`, record the run on `doc`, return the summary.

    `runner` has the shape of `services.strategy_engine.backtest.run_backtest`, which is what production passes; a
    test passes a fake, so this module never needs a database of its own.

    A window overlapping the sealed research block is refused with `SealedWindowRefused` unless `holdout=True`, and
    then only once per strategy (`HoldoutUsed` afterwards). `holdout=True` on a window that does not touch the block
    is an ordinary run: the flag only matters where there is a seal to open, so it is recorded as holdout False.
    """
    start, end = _as_date(from_date), _as_date(to_date)
    if start > end:
        raise StrategyError("bad_window")
    _ctx, _regime, rw, _rs = _research.load()

    opens_seal = bool(rw.overlaps_sealed_gap(start, end))
    if opens_seal:
        if not holdout:
            raise SealedWindowRefused(
                f"{start}..{end} overlaps the sealed block "
                f"{rw.SEALED_GAP_START.date()}..{rw.SEALED_GAP_END.date()}")
        if doc.get("holdout_used"):
            raise HoldoutUsed("the sealed block has already been opened once for this strategy")

    spec = doc.get("spec")
    errs = validate_strategy(spec)
    if errs:
        raise StrategyError("invalid_spec: " + "; ".join(str(e) for e in errs))
    cfg = _resolved_config(doc.get("config") or {})
    fold_windows = folds(start, end, FOLD_COUNT)      # before anything runs, so a short window fails cleanly

    if opens_seal:
        # Marked before the run, not after: the block is read the moment the window is handed over, so a runner that
        # fails half way must not leave the holdout looking unused.
        doc["holdout_used"] = True
        doc["holdout_window"] = {"from_date": start.isoformat(), "to_date": end.isoformat()}

    # commission_pct is a per-side percentage (assumption B2 Q4) and the DSL backtester's own per-side cost is
    # slippage_pct as a fraction, so it goes in there rather than being charged a second time by us.
    kwargs = {"starting_capital": cfg.initial_capital, "slippage_pct": cfg.commission_pct / 100.0}

    metrics = _metrics_of(await runner(pool, spec, from_date=start, to_date=end, **kwargs))

    walk_forward: List[Dict[str, Any]] = []
    for i, (f_start, f_end) in enumerate(fold_windows, start=1):
        fold_metrics = _metrics_of(await runner(pool, spec, from_date=f_start, to_date=f_end, **kwargs))
        walk_forward.append({"fold": i, "from_date": f_start.isoformat(), "to_date": f_end.isoformat(),
                             "metrics": fold_metrics})

    run = {
        "run_id": str(uuid.uuid4()),
        "ran_at": _now_iso(),
        "strategy_version": doc.get("version"),
        "metrics": metrics,
        "resolved_config": cfg.to_dict(),
        "window": {"from_date": start.isoformat(), "to_date": end.isoformat()},
        "holdout": opens_seal,
        "walk_forward": walk_forward,
    }
    doc.setdefault("runs", []).append(run)
    doc["updated_at"] = _now_iso()
    return run


# ── gates and the stage machine ────────────────────────────────────────────────────────────────────────────────
def _positive_folds(walk_forward: Optional[Sequence[Dict[str, Any]]]) -> int:
    count = 0
    for fold in walk_forward or ():
        metrics = (fold.get("metrics") if isinstance(fold, dict) else None) or {}
        value = _num(metrics.get("total_return_pct"))
        if value is not None and value > MIN_TOTAL_RETURN_PCT:
            count += 1
    return count


def _backtested_row(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """A stored run only counts once it measured something. An empty metrics dict, the engine's no-data run, and a
    run that opened no trade all fail: none of the three is evidence about the strategy (deviation from B3)."""
    trades = _num(metrics.get("trade_count"))
    measured = (metrics.get("reason") != NO_DATA_REASON and trades is not None
                and trades >= MIN_RUN_TRADE_COUNT)
    return _row(_gate("backtested", "backtest_run"), metrics.get("trade_count"), measured)


def _profit_factor_row(gate: Gate, metrics: Dict[str, Any], minimum: float) -> Dict[str, Any]:
    """The profit-factor criterion. The engine reports None for "no losses to divide by", which is not a failure
    when the run was profitable, so that one case passes with the real None still shown as the value."""
    raw = metrics.get("profit_factor")
    pf = _num(raw)
    if pf is not None:
        return _row(gate, raw, pf >= minimum)
    # Only a literal None carries the engine's "no losses to divide by". Anything else non-numeric is bad data and
    # is never read as a pass.
    if raw is None and _no_losing_trades(metrics):
        row = _row(gate, raw, True)
        row["label"] = f"{gate.label} (undefined: no losing trades and a positive return)"
        return row
    return _row(gate, raw, False)


def _no_losing_trades(metrics: Dict[str, Any]) -> bool:
    """True when the run has trades, every one of them won, and the return is positive. The engine reports no loser
    count, so a 100 percent win rate is the signal that there was nothing to divide by."""
    trades = _num(metrics.get("trade_count"))
    win_rate = _num(metrics.get("win_rate"))
    total_return = _num(metrics.get("total_return_pct"))
    return (trades is not None and trades >= MIN_RUN_TRADE_COUNT and win_rate == 100.0
            and total_return is not None and total_return > MIN_TOTAL_RETURN_PCT)


def _portfolio_pct_row(gate: Gate, metrics: Dict[str, Any], key: str, meets_threshold: bool) -> Dict[str, Any]:
    """A row whose threshold is a percentage of the portfolio (B3's -25 % drawdown and >0 % return).

    `strategy_engine.backtest` books `pnl_abs = (exit_price - entry_price) - 2 * brokerage_inr` and carries no
    quantity anywhere, so the equity series `_compute_metrics` draws `max_drawdown_pct` and `total_return_pct`
    from is one-share rupees added to the starting capital. On a Rs 10,00,000 account a six percent stop on a
    Rs 1,400 share prints about -0.01 percent a trade, so twenty-five stop-outs read as -0.31 percent where a
    risk-sized book would be down about 15 percent: the -25 percent floor can never bind. The thresholds are not
    moved to fit that unit, because they are the sizes the product means. Instead a run has to declare that its
    percentages are percentages of capital, and nothing produces that declaration today, so these two rows report
    what they have and fail as unmeasured. An uncomputable value is never a pass.
    """
    sized = metrics.get("sizing_basis") == PORTFOLIO_SIZING_BASIS
    row = _row(gate, metrics.get(key), meets_threshold and sized)
    if not sized:
        row["label"] = f"{gate.label} (not measured: the run declares no portfolio sizing basis)"
    return row


def _paper_rows(metrics: Dict[str, Any],
                walk_forward: Optional[Sequence[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    trades = _num(metrics.get("trade_count"))
    dd = _num(metrics.get("max_drawdown_pct"))
    ret = _num(metrics.get("total_return_pct"))
    positive = _positive_folds(walk_forward)
    basis = metrics.get("universe_basis")
    return [
        _row(_gate("paper", "trade_count"), metrics.get("trade_count"),
             trades is not None and trades >= MIN_BACKTEST_TRADES),
        _profit_factor_row(_gate("paper", "profit_factor"), metrics, MIN_PROFIT_FACTOR),
        _portfolio_pct_row(_gate("paper", "max_drawdown_pct"), metrics, "max_drawdown_pct",
                           dd is not None and dd >= MIN_MAX_DRAWDOWN_PCT),
        _portfolio_pct_row(_gate("paper", "total_return_pct"), metrics, "total_return_pct",
                           ret is not None and ret > MIN_TOTAL_RETURN_PCT),
        _row(_gate("paper", "walk_forward_positive_folds"), positive, positive >= MIN_POSITIVE_FOLDS),
        # A missing basis fails as well as the biased one: an unproven universe is not a point-in-time universe.
        _row(_gate("paper", "universe_basis"), basis, basis in ACCEPTED_UNIVERSE_BASIS),
    ]


# The paper tally keys the assisted gate reads. `execution.paper_stats` produces them and checks itself against
# this tuple, so a rename on either side fails at once instead of silently reading None and refusing a promotion for
# the wrong reason.
PAPER_STATS_FIELDS = ("closed_trades", "expectancy", "profit_factor", "win_rate")


def _assisted_rows(metrics: Dict[str, Any], paper_stats: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    stats = dict(paper_stats or {})
    closed = _num(stats.get("closed_trades"))
    expectancy = _num(stats.get("expectancy"))
    pf = _num(stats.get("profit_factor"))
    paper_wr, backtest_wr = _num(stats.get("win_rate")), _num(metrics.get("win_rate"))
    gap = abs(paper_wr - backtest_wr) if (paper_wr is not None and backtest_wr is not None) else None
    return [
        _row(_gate("assisted", "paper_closed_trades"), stats.get("closed_trades"),
             closed is not None and closed >= MIN_PAPER_CLOSED_TRADES),
        _row(_gate("assisted", "paper_expectancy"), stats.get("expectancy"),
             expectancy is not None and expectancy > MIN_PAPER_EXPECTANCY),
        _row(_gate("assisted", "paper_profit_factor"), stats.get("profit_factor"),
             pf is not None and pf >= MIN_PAPER_PROFIT_FACTOR),
        _row(_gate("assisted", "win_rate_gap"), gap, gap is not None and gap <= MAX_WIN_RATE_GAP_PTS),
    ]


def evaluate_gates(target_stage: str, metrics: Optional[Dict[str, Any]], *,
                   walk_forward: Optional[Sequence[Dict[str, Any]]] = None,
                   paper_stats: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """One row per criterion for `target_stage`: the real value read, the threshold, and whether it passed.

    `metrics` is a backtest metrics dict (the keys `strategy_engine.backtest._compute_metrics` returns, plus the
    provider's `price_basis`/`universe_basis`, and `sizing_basis` where the producer can say its percentages are
    percentages of capital). `paper_stats` is the live paper tally and is read for the assisted stage:
    closed_trades, expectancy, profit_factor, win_rate. draft and retired have no gates.
    """
    if not isinstance(target_stage, str) or target_stage not in STAGES:
        raise StrategyError("invalid_stage")
    metrics = dict(metrics or {})
    if target_stage == "backtested":
        return [_backtested_row(metrics)]
    if target_stage == "paper":
        return _paper_rows(metrics, walk_forward)
    if target_stage == "assisted":
        return _assisted_rows(metrics, paper_stats)
    return []


def _gate_run(doc: Dict[str, Any], target_stage: str) -> Optional[Dict[str, Any]]:
    """The stored run a forward move to `target_stage` reads as its evidence, or None when the document has none.

    Two rules, both so that a gate cannot be met by numbers that were never this strategy's promotion evidence:
      * no holdout run, ever (see `_gate_runs`).
      * the move to assisted reads the run that earned paper, which is the newest stored run that still passes
        every paper criterion, not whatever ran last. Otherwise a short exploratory window run after the paper
        promotion silently becomes the baseline the win-rate gap is measured against: it can let a strategy whose
        paper record matches nothing through, and it can block one whose paper record genuinely matches its
        backtest. A later run can only change that baseline by being good enough to have earned paper itself.
    With no such run the caller gets no metrics, the rows carry a value of None and fail, and the promotion is
    refused as unmeasured rather than granted on a guess.
    """
    runs = _gate_runs(doc)
    if target_stage == "assisted":
        for run in reversed(runs):
            rows = evaluate_gates("paper", run.get("metrics"), walk_forward=run.get("walk_forward"))
            if all(r["passed"] for r in rows):
                return run
        return None
    return runs[-1] if runs else None


def _with_stage(doc: Dict[str, Any], target_stage: str, gates: List[Dict[str, Any]],
                evidence_run: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out = copy.deepcopy(doc)
    stamp = _now_iso()
    out["stage"] = target_stage
    out["stage_history"] = list(out.get("stage_history") or []) + [
        {"stage": target_stage, "at": stamp, "by": CREATED_BY, "from": doc.get("stage"), "gates": gates,
         # Which run the gate numbers came from, so a promotion can be audited back to its window instead of
         # reading like an ordinary in-sample result. None means no stored run backed it: the caller passed the
         # numbers in, or the move read no gates at all.
         "evidence_run": ({"run_id": evidence_run.get("run_id"), "window": evidence_run.get("window")}
                          if evidence_run else None)}]
    out["updated_at"] = stamp
    return out


def promote(doc: Dict[str, Any], target_stage: str, *, metrics: Optional[Dict[str, Any]] = None,
            walk_forward: Optional[Sequence[Dict[str, Any]]] = None,
            paper_stats: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One stage forward on a clean sheet, or any stage backward, or retired. Returns an updated copy of `doc`.

    Forward moves read the gates: `metrics` and `walk_forward` default to the run `_gate_run` picks and
    `paper_stats` to the document's tally, so a caller cannot promote on numbers it made up on the side without
    passing them in explicitly. The run that backed the gates is named on the stage-history entry.

    Which run that is, is a rule rather than "the last one", because "the last one" could be either of two runs
    that are not evidence for this promotion: the one-shot sealed-block holdout, and a short window run made after
    the strategy had already earned its current rung. Neither can satisfy a gate here. A document with no eligible
    run is refused with every row reading None: unmeasured is not met.

    Raises `StrategyError("invalid_stage")` for anything outside `STAGES` (there is no live stage),
    `StrategyError("stage_skip")` for a jump, and `GateNotMet` with the failing rows.
    """
    if not isinstance(target_stage, str) or target_stage not in STAGES:
        raise StrategyError("invalid_stage")
    current = doc.get("stage")
    if current not in STAGES:
        raise StrategyError("invalid_stage")
    if target_stage == current:
        raise StrategyError("stage_skip")
    if target_stage == "retired":
        return _with_stage(doc, target_stage, [])
    if current == "retired":
        raise StrategyError("stage_skip")          # a retired strategy is restarted as a new one, not promoted back

    step = LADDER.index(target_stage) - LADDER.index(current)
    if step < 0:
        return _with_stage(doc, target_stage, [])  # demotion is always allowed
    if step > 1:
        raise StrategyError("stage_skip")

    run = _gate_run(doc, target_stage) if (metrics is None or walk_forward is None) else None
    last = run or {}
    rows = evaluate_gates(
        target_stage,
        metrics if metrics is not None else last.get("metrics"),
        walk_forward=walk_forward if walk_forward is not None else last.get("walk_forward"),
        paper_stats=paper_stats if paper_stats is not None else doc.get("paper_stats"),
    )
    unmet = [r for r in rows if not r["passed"]]
    if unmet:
        raise GateNotMet(target_stage, unmet)
    return _with_stage(doc, target_stage, rows, run)
