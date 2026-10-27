"""Strategy backtest runner.

Sweeps a date range, runs the compiled entry rule once per trading
day, simulates entries with the spec's exit plan against forward bars,
and records every simulated trade in strategy_trades.

Data basis (Tier-2 / R1 applied — see metrics["price_basis"] /
metrics["universe_basis"] which the run records for audit):

  • Corp-action-adjusted prices. Entry uses nidp.prices_eod_adjusted
    .adj_close (falling back to f.close only where the adjusted row is
    missing); exits use adj_open/adj_high/adj_low/adj_close from the same
    table. Entry and exit share one adjusted basis, so a split/bonus during
    the hold no longer fabricates a gain/loss. The features-derived ATR is
    rescaled by cumulative_adj_factor onto that basis.

  • Universe (metrics["universe_basis"], ["universe_warning"], ["universe_rule"]; market_data.py):
    the market universe LIQUID_EQ (liquid_universe.py, liquid-eq-v1) is point-in-time and
    survivorship-free: each date's members come from that date's prices and the 29 sessions before
    it. An index universe on the DaaS backend applies the LATEST constituent snapshot to every date
    (universe_basis="latest_snapshot", with a survivorship-bias warning); on the SQL backend it is
    point-in-time when nidp.index_constituents has the index, else the legacy present-day set
    (universe_basis="present_day_fallback", warned too).

  • One trade per (symbol, entry_date) — once we open a position we
    don't re-enter on the next bar even if the rule still fires. Live
    semantics (Phase 3) follow the same rule.

EXITS (exit-rules-v1, services/exit_rules.py — the SAME step function the desk paper trades use):
  • Each open position is stepped once per session it has a bar for, in this order: the gap rule on the OPEN against
    the stop as it stood at the previous close (an open through the stop fills AT THE OPEN, not at the stop); a pending
    trend exit at the open; an intrabar touch of that same stop, then the target (both in one bar → the stop); the time
    exit at the close of the session `max_hold_days` SESSIONS held (counted in sessions, never calendar days); and only
    after the bar the trailing stop (when `trailing_atr_mult` is set): ATR_t by Wilder's recursion over the bars up to
    that close, seeded with the stored atr14 as of the entry, the high-water mark from the bar's HIGH, stop =
    max(stop, hw − k·ATR_t) in force from the next session. Before this version the bar's own high raised the stop
    before its low was tested (look-ahead), the ATR was frozen at entry (or a made-up 2% of the price when missing),
    gaps filled at the stop, time was calendar days, and a trailed exit was recorded as STOPLOSS.
  • Recorded reasons: STOPLOSS (the initial stop), TRAILING_STOP (a stop the trail raised), TARGET, TIME, TREND
    (`trend_ema_period`, opt-in: a close below the EMA exits at the next open), BACKTEST_END.
  • Slippage is applied to the fill prices: entries pay `slippage_pct` above, exits receive it below.

ENTRY TIMING (`entry_timing`, recorded in metrics):
  • "signal_close" (default, the engine's behaviour so far): entered at the signal bar's close plus slippage.
  • "next_open": entered at the next session's OPEN plus slippage; an order whose symbol has no bar or no open that
    session lapses (counted). The entry session is then stepped for exits too.

COSTS (`cost_model`, recorded in metrics):
  • "desk-cost-v2" (default): the desk cost card (services/desk_cost_card.py) for equity delivery per order side —
    brokerage (a ₹20 desk assumption, `brokerage_inr`), STT, exchange charge, SEBI fee, stamp duty, GST. Its slippage
    component is NOT charged here: slippage is already in the fill prices.
  • "desk-flat-v1": the old flat ₹`brokerage_inr` per side, kept selectable so older runs can be reproduced.

  • Position sizing — equal-weight slots against a tracked cash balance
    (metrics["sizing_basis"] == "portfolio"). One slot is
    `current_equity / max_positions` and `quantity = floor(slot / entry_price)`,
    so the run compounds: a slot grows as the book grows. Opening a
    position debits `quantity * entry_price + entry-side charges` from cash and
    closing credits `quantity * exit_price - exit-side charges`, so cash is a real
    constraint — a candidate the cash cannot afford, or one whose price
    exceeds a whole slot, is SKIPPED and counted in
    metrics["skipped_insufficient_cash"] / ["skipped_min_quantity"],
    never silently dropped. Candidates beyond the free slots are counted too
    (metrics["signals_dropped_no_slot"]; signals_seen vs signals_taken).

  • Daily mark-to-market equity — one equity point per trading day:
    cash plus `quantity * that day's adjusted close` for every open
    position. A symbol with no bar on a day carries its last observed mark
    forward (never an invented price). `max_drawdown_pct`, Sharpe and Sortino
    are taken from that series, so they include open-position drawdown.

  • Reproducibility — every run records `code_version` (the git SHA when the
    deployment exposes one, and a SHA-256 of the engine's own source files) and
    `data_watermark` (the newest session the data platform held when the run
    ended); persist_run writes the watermark to strategy_runs.snapshot_as_of.
    metrics["provenance"] (PROVENANCE_VERSION) gathers what reproduces a run: the data watermark,
    the code version, the rule version (DSL version, a SHA-256 of the canonical spec, the exit-rules
    version and — written by persist_run — the strategy_versions id), the cost model with its
    parameters, the universe and its rule, and the entry timing. `run_provenance` reads the same
    block from ANY stored run, older ones included: a field a run never recorded is null and listed
    in `not_recorded`, never guessed.

  • Pure-async + asyncpg — caller passes a pool; we never open our own
    connection so transaction boundaries stay with the caller.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from services import desk_cost_card as cost_card
from services import exit_rules as er

from .dsl import validate_strategy
from .market_data import get_provider
from .backtest_sql import EXIT_BARS_SQL as _EXIT_BARS_SQL  # re-exported for tests

logger = logging.getLogger(__name__)


# ── Cost defaults ───────────────────────────────────────────────────
DEFAULT_SLIPPAGE_PCT = 0.0005       # 5 bps per side
DEFAULT_BROKERAGE_INR = 20.0        # ₹20 flat per side

COST_CARD = cost_card.VERSION       # "desk-cost-v2"
COST_FLAT = "desk-flat-v1"
COST_MODELS = (COST_CARD, COST_FLAT)
ENTRY_TIMINGS = ("signal_close", "next_open")
SLIPPAGE_SWEEP_BPS: Tuple[int, ...] = (0, 5, 10, 20)
TRADING_DAYS_PER_YEAR = 252
DEFAULT_MAX_HOLD_SESSIONS = 30
REASON_CODE = {"stop": "STOPLOSS", "trailing_stop": "TRAILING_STOP", "target": "TARGET", "time": "TIME",
               "trend": "TREND", "expiry": "EXPIRY"}


@dataclass
class BacktestTrade:
    symbol: str
    entry_date: date
    entry_price: float
    score: Optional[float]
    stoploss_price: float
    target_price: float
    quantity: int = 0                   # whole shares held; sized off the equity slot at entry
    exit_date: Optional[date] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    pnl_pct: Optional[float] = None
    pnl_abs: Optional[float] = None
    holding_days: Optional[int] = None  # calendar days, as the column always held
    brokerage: float = 2 * DEFAULT_BROKERAGE_INR   # entry + exit charges (all of them under the cost card)
    slippage_pct: float = DEFAULT_SLIPPAGE_PCT
    # exit-rules-v1 detail (strategy_trades.metadata)
    initial_stop: Optional[float] = None
    base_entry_price: Optional[float] = None       # before slippage
    base_exit_price: Optional[float] = None
    entry_charges: float = 0.0
    exit_charges: float = 0.0
    holding_sessions: Optional[int] = None
    r_multiple: Optional[float] = None
    exit_fill: Optional[str] = None                 # gap_open | level | close | open
    stop_history: List[Dict[str, Any]] = field(default_factory=list)
    state: Any = field(default=None, repr=False, compare=False)
    rules: Any = field(default=None, repr=False, compare=False)


@dataclass
class BacktestResult:
    trades: List[BacktestTrade] = field(default_factory=list)
    equity_curve: List[Dict[str, Any]] = field(default_factory=list)  # [{date, equity, drawdown}]
    metrics: Dict[str, Any] = field(default_factory=dict)


# ── costs ───────────────────────────────────────────────────────────
def side_charges(cost_model: str, qty: int, price: float, side: str, brokerage_inr: float) -> float:
    """Charges on one order side, ₹, slippage excluded (it is in the fill price)."""
    if cost_model == COST_FLAT:
        return float(brokerage_inr)
    snap = {**cost_card.SNAPSHOT, "slippage_pct_per_side": 0.0, "brokerage_rs_per_side": float(brokerage_inr)}
    return cost_card.order_side("equity_delivery", side, qty * price, snap)["total"]


# ── reproducibility ─────────────────────────────────────────────────
_ENGINE_FILES = ("strategy_engine/backtest.py", "strategy_engine/market_data.py", "strategy_engine/backtest_sql.py",
                 "strategy_engine/liquid_universe.py", "strategy_engine/dsl.py", "strategy_engine/compiler_stock.py",
                 "strategy_engine/evaluator.py", "exit_rules.py", "desk_cost_card.py")
PROVENANCE_VERSION = "provenance-v1"


def _git_head(start: Path) -> Optional[str]:
    """The commit SHA of the checkout this file lives in, read from .git without running git; None when there is none
    (the staging container mounts only backend/)."""
    for d in [start, *start.parents]:
        dot = d / ".git"
        if not dot.exists():
            continue
        try:
            gitdir = dot
            if dot.is_file():                                   # a worktree: "gitdir: <path>"
                gitdir = Path(dot.read_text().split(":", 1)[1].strip())
            head = (gitdir / "HEAD").read_text().strip()
            if not head.startswith("ref:"):
                return head
            ref = head.split(":", 1)[1].strip()
            common = gitdir
            if (gitdir / "commondir").exists():
                common = (gitdir / (gitdir / "commondir").read_text().strip()).resolve()
            for base in (gitdir, common):
                if (base / ref).exists():
                    return (base / ref).read_text().strip()
            packed = common / "packed-refs"
            if packed.exists():
                for line in packed.read_text().splitlines():
                    if line.endswith(" " + ref):
                        return line.split(" ", 1)[0]
        except (OSError, IndexError):
            return None
        return None
    return None


def code_version() -> Dict[str, Any]:
    """{git_sha, git_sha_source, engine_sha256, exit_rules_version}: what code produced a run."""
    sha = os.environ.get("CODE_SHA") or os.environ.get("GIT_SHA")
    source = "env" if sha else None
    if not sha:
        sha = _git_head(Path(__file__).resolve().parent)
        source = "git" if sha else None
    h = hashlib.sha256()
    services_dir = Path(__file__).resolve().parents[1]
    for rel in _ENGINE_FILES:
        try:
            h.update(rel.encode() + b"\0" + (services_dir / rel).read_bytes())
        except OSError:
            h.update(rel.encode() + b"\0missing")
    return {"git_sha": sha, "git_sha_source": source, "engine_sha256": h.hexdigest(), "exit_rules_version": er.VERSION}


def spec_sha256(spec: Dict[str, Any]) -> str:
    """SHA-256 of the canonical JSON of a strategy spec (keys sorted, no whitespace): the same rules hash the same however
    the JSON was ordered or stored."""
    return hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _cost_model_record(cost_model: str, slippage_pct: float, brokerage_inr: float) -> Dict[str, Any]:
    out: Dict[str, Any] = {"version": cost_model, "slippage_pct_per_side": round(slippage_pct * 100.0, 6),
                           "slippage_basis": "in the fill prices", "brokerage_rs_per_side": float(brokerage_inr)}
    if cost_model == COST_CARD:
        out.update(statutory="STT, exchange transaction charge, SEBI fee, stamp duty and GST, equity delivery",
                   source=cost_card.SNAPSHOT["source"])
    else:
        out.update(statutory=None, source="services/strategy_engine/backtest.py (flat brokerage per side)")
    return out


def run_provenance(run: Dict[str, Any], definition: Any = None) -> Dict[str, Any]:
    """What reproduces a stored run (a strategy_runs row: metrics, snapshot_as_of, version_id), read the same way for every
    run. A run before provenance-v1 lacks some fields: they are null and named in `not_recorded`. `definition` (the run's
    strategy_versions row, immutable) lets the spec hash be derived at read time for such a run, and says so."""
    m = run.get("metrics") or {}
    if isinstance(m, str):
        try:
            m = json.loads(m)
        except ValueError:
            m = {}
    rec = m.get("provenance") or {}
    wm = rec.get("data_watermark") or m.get("data_watermark") or {}
    snap = run.get("snapshot_as_of")
    snap = snap.isoformat() if hasattr(snap, "isoformat") else snap
    data = {"snapshot_as_of": snap or wm.get("latest_session_available"),
            "window_last_session": wm.get("window_last_session")}
    rule = dict(rec.get("rule_version") or {})
    rule.setdefault("strategy_version_id", str(run["version_id"]) if run.get("version_id") is not None else None)
    if not rule.get("spec_sha256") and definition is not None:
        spec = json.loads(definition) if isinstance(definition, str) else definition
        rule.update(spec_sha256=spec_sha256(spec), dsl_version=(spec or {}).get("version"),
                    spec_sha256_source="derived at read time from the immutable strategy_versions row")
    rule.setdefault("exit_rules_version", m.get("exit_rules_version"))
    cost = rec.get("cost_model")
    if cost is None and m.get("cost_model"):
        cost = {"version": m.get("cost_model"), "slippage_pct_per_side": (m["slippage_pct_per_side"] * 100.0
                                                                          if m.get("slippage_pct_per_side") is not None else None)}
    universe = rec.get("universe") or ({"basis": m.get("universe_basis"), "warning": m.get("universe_warning"),
                                        "rule": m.get("universe_rule")} if m.get("universe_basis") else None)
    out = {"schema": rec.get("schema"), "data": data, "code_version": rec.get("code_version") or m.get("code_version"),
           "rule_version": rule, "cost_model": cost, "universe": universe,
           "entry_timing": rec.get("entry_timing") or m.get("entry_timing"),
           "price_basis": m.get("price_basis")}
    missing = []
    if not data["snapshot_as_of"]:
        missing.append("data_watermark")
    if not out["code_version"]:
        missing.append("code_version")
    if not rule.get("spec_sha256"):
        missing.append("rule_version.spec_sha256")
    if not rule.get("exit_rules_version"):
        missing.append("rule_version.exit_rules_version")
    if not cost:
        missing.append("cost_model")
    if not universe:
        missing.append("universe")
    if not out["entry_timing"]:
        missing.append("entry_timing")
    out["not_recorded"] = missing
    out["complete"] = not missing
    return out


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    try:
        out = float(v)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) and out > 0 else None


# ── Public entry ────────────────────────────────────────────────────
async def run_backtest(
    pool,
    spec: Dict[str, Any],
    *,
    from_date: date,
    to_date: date,
    starting_capital: float = 1_000_000.0,
    max_positions: int = 10,
    slippage_pct: float = DEFAULT_SLIPPAGE_PCT,
    brokerage_inr: float = DEFAULT_BROKERAGE_INR,
    cost_model: str = COST_CARD,
    entry_timing: str = "signal_close",
    slippage_sweep_bps: Sequence[int] = SLIPPAGE_SWEEP_BPS,
) -> BacktestResult:
    """Run a backtest of `spec` from from_date..to_date inclusive."""
    errs = validate_strategy(spec)
    if errs:
        raise ValueError("invalid spec: " + "; ".join(str(e) for e in errs))
    if cost_model not in COST_MODELS:
        raise ValueError(f"cost_model must be one of {COST_MODELS}")
    if entry_timing not in ENTRY_TIMINGS:
        raise ValueError(f"entry_timing must be one of {ENTRY_TIMINGS}")

    # Market data comes through a provider (SQL on co-located dev, NIDP DaaS API
    # on staging/prod). `prepare` prefetches the window; `screen`/`exit_bars`
    # serve per-date candidates and adjusted bars. R1's adjusted-price +
    # point-in-time-membership semantics live in the provider now.
    provider = get_provider(pool)
    await provider.prepare(spec, from_date, to_date)

    open_trades: Dict[str, BacktestTrade] = {}     # symbol → trade
    closed_trades: List[BacktestTrade] = []

    trading_dates = await provider.trading_dates(from_date, to_date)
    if not trading_dates:
        logger.warning("backtest window %s..%s has no feature snapshots", from_date, to_date)
        return BacktestResult(metrics={"reason": "no_data"})

    exit_spec = spec["exit"]
    sl_pct = float(exit_spec.get("stoploss_pct", 5)) / 100.0
    target_rr = float(exit_spec.get("target_rr", 2.0))
    max_hold = int(exit_spec.get("max_hold_days", DEFAULT_MAX_HOLD_SESSIONS))
    trailing_atr_mult = exit_spec.get("trailing_atr_mult")   # None = the trail is off
    trend_period = exit_spec.get("trend_ema_period")         # None = the trend exit is off

    def rules_for(target: float) -> er.Rules:
        return er.Rules(side="long", target=target, max_hold_sessions=max_hold,
                        trail_atr_mult=float(trailing_atr_mult) if trailing_atr_mult else None,
                        trend_ema_period=int(trend_period) if trend_period else None)

    # Cash is the real constraint; equity = cash + mark-to-market of the open book.
    cash = float(starting_capital)
    marks: Dict[str, float] = {}                 # symbol → last OBSERVED close (carried forward)
    equity_points: List[Dict[str, Any]] = []     # one per trading day, mark-to-market
    daily: List[Dict[str, float]] = []           # {equity, exposure, deployed} per trading day
    pending: Dict[str, Dict[str, Any]] = {}      # next_open orders: symbol → the signal row
    n = {"signals_seen": 0, "signals_taken": 0, "signals_dropped_no_slot": 0, "signals_already_held": 0,
         "skipped_cash": 0, "skipped_min_qty": 0, "entries_lapsed_no_open": 0, "stale_mark_closes": 0,
         "bars_high_low_from_close": 0, "bars_unusable": 0, "atr_unseeded_entries": 0}

    def _equity_now() -> float:
        return cash + sum(t.quantity * marks.get(sym, t.entry_price)
                          for sym, t in open_trades.items())

    def _open(sym: str, d: date, base_px: float, sig: Dict[str, Any], prev_close: Optional[float]) -> Optional[BacktestTrade]:
        nonlocal cash
        entry_price = base_px * (1.0 + slippage_pct)
        # features.atr14 is on a RAW-price basis; rescale to the adjusted
        # basis (adj_close = raw_close / cumulative_adj_factor) so the
        # trailing-stop distance is in the same units as price. A missing
        # ATR is NOT replaced by a guess: the trail waits for its own ATR.
        adj_factor = float(sig["adj_factor"]) if sig.get("adj_factor") else 1.0
        raw_atr = _num(sig.get("atr14"))
        atr = (raw_atr / adj_factor) if raw_atr else None
        raw_ema = _num(sig.get(f"ema{int(trend_period)}")) if trend_period else None
        ema = (raw_ema / adj_factor) if raw_ema else None
        stoploss = entry_price * (1.0 - sl_pct)
        target = entry_price + (entry_price - stoploss) * target_rr

        # ── Equal-weight slot sizing ──────────────────────────────
        # The slot is a share of CURRENT equity, recomputed per candidate so
        # the run compounds and so the charges already paid on this day's earlier
        # entries are reflected (sizing off a stale once-a-day equity can make
        # the last slot of a day unaffordable by exactly those charges).
        slot_value = _equity_now() / max_positions
        quantity = int(slot_value // entry_price)
        if quantity < 1:
            n["skipped_min_qty"] += 1
            logger.info("backtest %s on %s: 1 share (₹%.2f) exceeds the slot "
                        "(₹%.2f) — entry skipped", sym, d, entry_price, slot_value)
            return None
        charges = side_charges(cost_model, quantity, entry_price, "BUY", brokerage_inr)
        entry_cost = quantity * entry_price + charges
        if entry_cost > cash:
            n["skipped_cash"] += 1
            logger.info("backtest %s on %s: entry needs ₹%.2f but cash is ₹%.2f "
                        "— entry skipped", sym, d, entry_cost, cash)
            return None
        rules = rules_for(target)
        if rules.trailing and atr is None:
            n["atr_unseeded_entries"] += 1
        t = BacktestTrade(
            symbol=sym, entry_date=d, entry_price=entry_price,
            score=float(sig.get("accumulation_score") or 0.0),
            stoploss_price=stoploss, target_price=target, quantity=quantity,
            brokerage=charges, slippage_pct=slippage_pct,
            initial_stop=stoploss, base_entry_price=base_px, entry_charges=charges,
        )
        t.rules = rules
        t.state = er.start(base_px, stoploss, rules, session=d, atr=atr, prev_close=prev_close, ema=ema)
        t.stop_history = er.public_history(t.state)
        cash -= entry_cost
        n["signals_taken"] += 1
        return t

    def _close(t: BacktestTrade, d: date, base_exit: float, reason: str, fill: Optional[str]) -> None:
        nonlocal cash
        exit_price = base_exit * (1.0 - slippage_pct)
        charges = side_charges(cost_model, t.quantity, exit_price, "SELL", brokerage_inr)
        t.exit_date, t.exit_price, t.exit_reason, t.exit_fill = d, exit_price, reason, fill
        t.base_exit_price, t.exit_charges = base_exit, charges
        t.brokerage = t.entry_charges + charges
        # pnl_pct KEEPS its original meaning: the PER-SHARE percentage move between the
        # slipped entry and exit prices, gross of charges. pnl_abs is the portfolio-scale
        # rupee figure, net of BOTH sides' charges (slippage is already in the prices).
        t.pnl_pct = (exit_price - t.entry_price) / t.entry_price * 100.0
        t.pnl_abs = t.quantity * (exit_price - t.entry_price) - t.brokerage
        t.holding_days = (d - t.entry_date).days
        t.holding_sessions = t.state.sessions_held if t.state is not None else None
        risk = t.quantity * (t.entry_price - (t.initial_stop or t.entry_price))
        t.r_multiple = (t.pnl_abs / risk) if risk > 0 else None
        if t.state is not None:
            t.stoploss_price = t.state.stop if t.state.stop is not None else t.stoploss_price
            t.stop_history = er.public_history(t.state)
        cash += t.quantity * exit_price - charges

    def _step(t: BacktestTrade, d: date, row: Dict[str, Any]) -> bool:
        """Step one open trade on day d's bar; True when it closed."""
        close = _num(row.get("close"))
        high, low = _num(row.get("high")), _num(row.get("low"))
        if (high is None or low is None) and close is not None:
            # The engine has always read a missing high/low as the close; kept, and counted.
            n["bars_high_low_from_close"] += 1
            high, low = high or close, low or close
        bar = {"date": d, "open": row.get("open"), "high": high, "low": low, "close": close}
        try:
            state, ex = er.step(t.state, bar, t.rules)
        except er.IncompleteBar:
            n["bars_unusable"] += 1
            return False
        t.state = state
        if ex is None:
            t.stoploss_price = state.stop
            return False
        _close(t, d, float(ex["price"]), REASON_CODE[ex["reason"]], ex["fill"])
        return True

    for d in trading_dates:
        wanted = list(open_trades) + [s for s in pending if s not in open_trades]
        exit_map = await provider.exit_bars(wanted, d) if wanted else {}

        # 1) Process exits on currently-open positions first
        for sym in list(open_trades):
            row = exit_map.get(sym)
            if not row:
                continue
            # Mark first: today's close is this symbol's mark whether or not it exits.
            marks[sym] = float(row["close"])
            trade = open_trades[sym]
            if _step(trade, d, row):
                closed_trades.append(trade)
                del open_trades[sym]
                marks.pop(sym, None)

        # 2) next_open orders from yesterday's signals fill at today's open
        for sym, sig in list(pending.items()):
            del pending[sym]
            row = exit_map.get(sym)
            opn = _num((row or {}).get("open"))
            if opn is None:
                n["entries_lapsed_no_open"] += 1
                continue
            if len(open_trades) >= max_positions:
                n["signals_dropped_no_slot"] += 1
                continue
            sig_close = _num(sig.get("adj_close")) or _num(sig.get("close"))
            t = _open(sym, d, opn, sig, sig_close)
            if t is None:
                continue
            open_trades[sym] = t
            marks[sym] = float(row["close"])
            if _step(t, d, row):
                closed_trades.append(t)
                del open_trades[sym]
                marks.pop(sym, None)

        # 3) Look for new entries — the screen runs every day so signals are counted even with no free slot
        rows = await provider.screen(spec, d)
        n["signals_seen"] += len(rows)
        slots = max(max_positions - len(open_trades) - len(pending), 0)
        n["signals_dropped_no_slot"] += max(len(rows) - slots, 0)
        for r in rows[:slots]:
            sym = r["symbol"]
            if sym in open_trades or sym in pending:
                n["signals_already_held"] += 1
                continue
            if entry_timing == "next_open":
                pending[sym] = r
                continue
            # Trade on the corp-action-adjusted close (R1); fall back to raw
            # close only where the adjusted series is missing.
            adj_close = r.get("adj_close")
            base_px = float(adj_close) if adj_close is not None else float(r["close"])
            t = _open(sym, d, base_px, r, base_px)
            if t is not None:
                open_trades[sym] = t
                marks[sym] = base_px          # mark on the day's observed close, not the slipped fill

        eq = _equity_now()
        _record_equity(equity_points, d, eq)
        daily.append({"equity": eq,
                      "exposure": sum(t.quantity * marks.get(s, t.entry_price) for s, t in open_trades.items()),
                      "deployed": sum(t.quantity * t.entry_price for t in open_trades.values())})

    n["entries_lapsed_no_open"] += len(pending)        # orders signalled on the last day never had a next open
    pending.clear()

    # Force-close any still-open positions at the last available close
    if open_trades:
        last_lookup = await provider.exit_bars(list(open_trades), trading_dates[-1])
        for sym, trade in open_trades.items():
            row = last_lookup.get(sym)
            if row:
                close = float(row["close"])
            elif sym in marks:
                # No bar on the final day. Close on the last OBSERVED mark rather
                # than leave the position out of the ledger entirely. No price
                # is invented — this is the last close the feed actually carried.
                close = marks[sym]
                n["stale_mark_closes"] += 1
                logger.info("backtest %s: no bar on %s — force-closed on the last "
                            "observed mark ₹%.2f", sym, trading_dates[-1], close)
            else:
                continue
            _close(trade, trading_dates[-1], close, "BACKTEST_END", "close")
            closed_trades.append(trade)
        open_trades.clear()
        marks.clear()
        # The force-close happens ON the last trading day, so restate that day's
        # point instead of appending a second point for the same date.
        if equity_points:
            equity_points[-1]["equity"] = round(cash, 2)
            daily[-1].update(equity=cash, exposure=0.0, deployed=0.0)

    equity = _equity_now()          # open_trades is empty here → equity == cash
    equity_curve = _build_equity_curve(equity_points, starting_capital)
    sweep = slippage_sweep(closed_trades, starting_capital, cost_model=cost_model, brokerage_inr=brokerage_inr,
                           bps=slippage_sweep_bps)
    metrics = _compute_metrics(
        closed_trades, starting_capital, equity, equity_curve,
        max_positions=max_positions,
        skipped_insufficient_cash=n["skipped_cash"],
        skipped_min_quantity=n["skipped_min_qty"],
        stale_mark_closes=n["stale_mark_closes"],
        daily=daily, counters=n, slippage_sweep=sweep,
    )
    metrics.update({
        "entry_timing": entry_timing,
        "cost_model": cost_model,
        "slippage_pct_per_side": slippage_pct,
        "time_basis": "sessions",
        "gap_fill": "open",
        "exit_rules_version": er.VERSION,
        "exit_rules": {
            "trailing_atr": ({"k": float(trailing_atr_mult), "atr_period": er.DEFAULT_ATR_PERIOD,
                              "version": er.TRAIL_ATR_VERSION, "mark": "high", "atr": "Wilder, bars up to each close, "
                              "seeded with the stored atr14 at entry"} if trailing_atr_mult else None),
            "trend_ema": ({"period": int(trend_period), "version": er.TREND_EMA_VERSION} if trend_period else None),
            "max_hold_sessions": max_hold,
        },
        "code_version": code_version(),
    })
    try:
        latest = await provider.latest_date()
        metrics["data_watermark"] = {"latest_session_available": latest.isoformat() if latest else None,
                                     "window_last_session": trading_dates[-1].isoformat()}
    except Exception as exc:  # noqa: BLE001 — the run stands; the watermark is reported unknown, never guessed
        logger.warning("backtest: the data watermark could not be read: %r", exc)
        metrics["data_watermark"] = {"latest_session_available": None,
                                     "window_last_session": trading_dates[-1].isoformat(),
                                     "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
    # Self-describe the data basis so the readout / AC-7 data test can assert
    # what actually ran rather than trust a static claim (CONTEXT §1). The
    # provider reports the basis it actually used (price + universe membership).
    metrics.update(provider.basis)
    uni = spec.get("universe") or {}
    metrics["provenance"] = {
        "schema": PROVENANCE_VERSION,
        "data_watermark": metrics["data_watermark"],
        "code_version": metrics["code_version"],
        "rule_version": {"dsl_version": spec.get("version"), "spec_sha256": spec_sha256(spec),
                         "exit_rules_version": er.VERSION, "strategy_version_id": None},
        "cost_model": _cost_model_record(cost_model, slippage_pct, brokerage_inr),
        "universe": {"type": uni.get("type"), "ref": uni.get("ref"), "basis": metrics.get("universe_basis"),
                     "warning": metrics.get("universe_warning"), "rule": metrics.get("universe_rule")},
        "entry_timing": entry_timing,
    }

    return BacktestResult(trades=closed_trades, equity_curve=equity_curve, metrics=metrics)


# ── Internals ───────────────────────────────────────────────────────
def _record_equity(points: List[Dict[str, Any]], d: date, equity_now: float) -> None:
    """Append one mark-to-market equity point for trading day `d`.

    `equity_now` is cash + Σ(quantity × that symbol's latest observed close), so the
    series moves while positions are still open. Drawdowns are filled in later by
    `_build_equity_curve` (it needs the running peak over the whole series)."""
    points.append({"date": str(d), "equity": round(float(equity_now), 2)})


def _build_equity_curve(points: List[Dict[str, Any]], starting_capital: float) -> List[Dict[str, Any]]:
    """Daily mark-to-market equity curve with drawdown against the running peak.

    One point per trading day (the engine's own calendar), each the close-of-day
    total equity. The peak is seeded at `starting_capital` so a book that is under
    water from day one reports a drawdown rather than a flat 0%."""
    out: List[Dict[str, Any]] = []
    peak = float(starting_capital)
    for p in points:
        eq = float(p["equity"])
        peak = max(peak, eq)
        out.append({
            "date": p["date"],
            "equity": round(eq, 2),
            "drawdown": round((eq - peak) / peak * 100.0, 4) if peak else 0.0,
        })
    return out


def slippage_sweep(trades: List[BacktestTrade], start_cap: float, *, cost_model: str, brokerage_inr: float,
                   bps: Sequence[int] = SLIPPAGE_SWEEP_BPS) -> Dict[str, Any]:
    """The run's closed trades re-priced at each slippage (basis points a side): the same trades and quantities, the
    entry at base × (1 + s) and the exit at base × (1 − s), charges at those prices. Sizing and cash are NOT
    re-simulated, so this isolates the cost sensitivity of the trades the run took."""
    out: Dict[str, Any] = {"basis": "the same trades and quantities re-priced at each slippage per side; sizing and cash "
                                    "are not re-simulated", "by_bps": {}}
    for b in bps:
        s = b / 10_000.0
        pnls: List[float] = []
        for t in trades:
            if t.base_entry_price is None or t.base_exit_price is None:
                continue
            ent, ext = t.base_entry_price * (1 + s), t.base_exit_price * (1 - s)
            charges = (side_charges(cost_model, t.quantity, ent, "BUY", brokerage_inr)
                       + side_charges(cost_model, t.quantity, ext, "SELL", brokerage_inr))
            pnls.append(t.quantity * (ext - ent) - charges)
        wins = [p for p in pnls if p > 0]
        loss = abs(sum(p for p in pnls if p <= 0))
        out["by_bps"][str(b)] = {
            "net_pnl_rs": round(sum(pnls), 2),
            "expectancy_rs": round(sum(pnls) / len(pnls), 2) if pnls else None,
            "win_rate": round(len(wins) / len(pnls) * 100.0, 2) if pnls else None,
            "profit_factor": round(sum(wins) / loss, 2) if loss > 0 else None,
            "total_return_pct": round(sum(pnls) / start_cap * 100.0, 2) if start_cap else None,
        }
    return out


def _risk_adjusted(equity_curve: List[Dict[str, Any]], start_cap: float) -> Dict[str, Any]:
    """Sharpe and Sortino from the DAILY mark-to-market curve: daily returns (the first against the starting capital),
    risk-free rate 0, annualised with √252. None with fewer than two returns or no dispersion."""
    eq = [float(start_cap)] + [float(p["equity"]) for p in equity_curve]
    rets = [eq[i] / eq[i - 1] - 1.0 for i in range(1, len(eq)) if eq[i - 1] > 0]
    out: Dict[str, Any] = {"sharpe": None, "sortino": None, "daily_returns": len(rets),
                           "risk_adjusted_basis": "daily mark-to-market returns, risk-free 0, annualised ×√252"}
    if len(rets) < 2:
        return out
    mean = statistics.fmean(rets)
    sd = statistics.stdev(rets)
    ann = math.sqrt(TRADING_DAYS_PER_YEAR)
    if sd > 0:
        out["sharpe"] = round(mean / sd * ann, 3)
    downside = math.sqrt(sum(min(r, 0.0) ** 2 for r in rets) / len(rets))
    if downside > 0:
        out["sortino"] = round(mean / downside * ann, 3)
    return out


def _compute_metrics(trades: List[BacktestTrade], start_cap: float, end_cap: float,
                     equity_curve: Optional[List[Dict[str, Any]]] = None, *,
                     max_positions: int = 0,
                     skipped_insufficient_cash: int = 0,
                     skipped_min_quantity: int = 0,
                     stale_mark_closes: int = 0,
                     daily: Optional[List[Dict[str, float]]] = None,
                     counters: Optional[Dict[str, int]] = None,
                     slippage_sweep: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Summary metrics for a sized run.

    A WIN means the trade MADE MONEY AFTER COSTS: wins and losses are split on net
    `pnl_abs`, the same figure `profit_factor` divides, so the two metrics can no
    longer disagree.

    Averages come in two pairs, and only one of them is coherent:

      • `avg_win_abs` / `avg_loss_abs` (RUPEES) are the mean net `pnl_abs` of the
        same buckets `win_rate` and `profit_factor` use. These three are mutually
        consistent, so THIS is the pair to display.
      • `avg_win_pct` / `avg_loss_pct` are kept unchanged because other code reads
        them, but they are a GROSS PER-SHARE percentage averaged over buckets
        defined by NET RUPEES. Do not headline that pair.

    Added with exit-rules-v1 (PRD §12; all from this run's own trades and daily curve):
      expectancy_rs / expectancy_r            mean net ₹ / mean R per trade (R = net P&L ÷ quantity × initial stop distance)
      expectancy_rs_per_session / _r_         total net ₹ / total R over the sessions held
      payoff_ratio                            avg_win_abs ÷ |avg_loss_abs|
      sharpe / sortino                        daily mark-to-market returns, risk-free 0, ×√252
      days_invested_pct, avg/max_gross_exposure_pct   share of days with a position; gross exposure ÷ equity
      traded_value_rs, turnover_x, turnover_x_annualised   Σ entry + exit value; ÷ mean equity; × 252 ÷ days
      avg/max_capital_deployed_rs, avg_capital_deployed_pct   Σ quantity × entry fill of the open book
      signals_seen / signals_taken / signals_dropped_no_slot / signals_already_held   rejected-signal coverage
      exit_reasons                            trades by exit reason
      slippage_sweep                          see `slippage_sweep`
    `max_drawdown_pct` comes from the DAILY mark-to-market `equity_curve`.
    """
    counters = counters or {}
    sizing = {
        "sizing_basis":              "portfolio",
        "max_positions":             max_positions,
        "skipped_insufficient_cash": skipped_insufficient_cash,
        "skipped_min_quantity":      skipped_min_quantity,
        "skipped_entries":           skipped_insufficient_cash + skipped_min_quantity,
        "stale_mark_closes":         stale_mark_closes,
        "starting_capital":          start_cap,
        "ending_capital":            round(end_cap, 2),
    }
    max_dd = min([p["drawdown"] for p in (equity_curve or [])], default=0.0)
    extra: Dict[str, Any] = {}
    if counters:
        seen = counters.get("signals_seen", 0)
        extra.update({k: counters.get(k, 0) for k in ("signals_seen", "signals_taken", "signals_dropped_no_slot",
                                                       "signals_already_held", "entries_lapsed_no_open",
                                                       "bars_high_low_from_close", "bars_unusable", "atr_unseeded_entries")})
        extra["signals_taken_pct"] = round(counters.get("signals_taken", 0) / seen * 100.0, 2) if seen else None
    if equity_curve is not None:
        extra.update(_risk_adjusted(equity_curve, start_cap))
    if daily:
        days = len(daily)
        priced = [p for p in daily if p["equity"] > 0]
        mean_eq = statistics.fmean(p["equity"] for p in daily)
        traded = sum(t.quantity * ((t.entry_price or 0.0) + (t.exit_price or 0.0)) for t in trades)
        extra.update({
            "days": days,
            "days_invested_pct": round(sum(1 for p in daily if p["exposure"] > 0) / days * 100.0, 2),
            "avg_gross_exposure_pct": round(statistics.fmean(p["exposure"] / p["equity"] for p in priced) * 100.0, 2) if priced else None,
            "max_gross_exposure_pct": round(max((p["exposure"] / p["equity"] for p in priced), default=0.0) * 100.0, 2),
            "traded_value_rs": round(traded, 2),
            "turnover_x": round(traded / mean_eq, 3) if mean_eq > 0 else None,
            "turnover_x_annualised": round(traded / mean_eq * TRADING_DAYS_PER_YEAR / days, 3) if mean_eq > 0 else None,
            "avg_capital_deployed_rs": round(statistics.fmean(p["deployed"] for p in daily), 2),
            "max_capital_deployed_rs": round(max(p["deployed"] for p in daily), 2),
            "avg_capital_deployed_pct": round(statistics.fmean(p["deployed"] / p["equity"] for p in priced) * 100.0, 2) if priced else None,
        })
    if slippage_sweep is not None:
        extra["slippage_sweep"] = slippage_sweep
    if not trades:
        return {"trade_count": 0,
                "max_drawdown_pct": round(max_dd, 2),
                "total_return_pct": round((end_cap - start_cap) / start_cap * 100.0, 2),
                **sizing, **extra}
    wins = [t for t in trades if (t.pnl_abs or 0) > 0]
    losses = [t for t in trades if (t.pnl_abs or 0) <= 0]
    avg_win = sum(t.pnl_pct for t in wins) / len(wins) if wins else 0.0
    avg_loss = sum(t.pnl_pct for t in losses) / len(losses) if losses else 0.0
    total_profit = sum(t.pnl_abs or 0 for t in wins)
    total_loss = abs(sum(t.pnl_abs or 0 for t in losses))
    # The coherent pair: mean net rupees over the same buckets as win_rate /
    # profit_factor. avg_loss_abs keeps pnl_abs's sign, so it is ≤ 0.
    avg_win_abs = (total_profit / len(wins)) if wins else 0.0
    avg_loss_abs = (sum(t.pnl_abs or 0 for t in losses) / len(losses)) if losses else 0.0
    # None means "nothing to divide by" (no losing trade). A profit factor of
    # exactly 0.0 is a real, terrible number and must not be reported as None.
    profit_factor = (total_profit / total_loss) if total_loss > 0 else None
    net = sum(t.pnl_abs or 0 for t in trades)
    rs = [t.r_multiple for t in trades if t.r_multiple is not None]
    sessions = sum(int(t.holding_sessions or 0) for t in trades)
    sessions_r = sum(int(t.holding_sessions or 0) for t in trades if t.r_multiple is not None)
    reasons: Dict[str, int] = {}
    for t in trades:
        reasons[t.exit_reason or "UNKNOWN"] = reasons.get(t.exit_reason or "UNKNOWN", 0) + 1

    return {
        "trade_count":        len(trades),
        "win_rate":           round(len(wins) / len(trades) * 100.0, 2),
        "avg_win_pct":        round(avg_win, 2),
        "avg_loss_pct":       round(avg_loss, 2),
        "avg_win_abs":        round(avg_win_abs, 2),
        "avg_loss_abs":       round(avg_loss_abs, 2),
        "profit_factor":      round(profit_factor, 2) if profit_factor is not None else None,
        "max_drawdown_pct":   round(max_dd, 2),
        "total_return_pct":   round((end_cap - start_cap) / start_cap * 100.0, 2),
        "avg_holding_days":   round(sum((t.holding_days or 0) for t in trades) / len(trades), 1),
        "avg_holding_sessions": round(sessions / len(trades), 1),
        "total_quantity":     sum(int(t.quantity or 0) for t in trades),
        "expectancy_rs":      round(net / len(trades), 2),
        "expectancy_r":       round(statistics.fmean(rs), 3) if rs else None,
        "expectancy_rs_per_session": round(net / sessions, 2) if sessions else None,
        "expectancy_r_per_session": round(sum(rs) / sessions_r, 4) if rs and sessions_r else None,
        "payoff_ratio":       round(avg_win_abs / abs(avg_loss_abs), 2) if avg_loss_abs < 0 else None,
        "exit_reasons":       reasons,
        **sizing,
        **extra,
    }


def _trade_metadata(t: BacktestTrade) -> Dict[str, Any]:
    return {"exit_rules_version": er.VERSION, "initial_stop": t.initial_stop, "stop_history": t.stop_history,
            "holding_sessions": t.holding_sessions, "r_multiple": round(t.r_multiple, 4) if t.r_multiple is not None else None,
            "exit_fill": t.exit_fill, "base_entry_price": t.base_entry_price, "base_exit_price": t.base_exit_price,
            "entry_charges": t.entry_charges, "exit_charges": t.exit_charges}


# ── Persistence helper ──────────────────────────────────────────────
async def persist_run(pool, *, strategy_id, version_id, spec, result: BacktestResult,
                       from_date, to_date, triggered_by) -> str:
    """Write a strategy_runs row + per-trade strategy_trades rows. Returns run_id.

    `snapshot_as_of` is the data watermark (metrics.data_watermark.latest_session_available: the newest session the data
    platform held when the run ended), NULL when it could not be read. The code version is in metrics.code_version.
    Older rows without either stay readable: nothing reads them as required."""
    run_id = str(uuid.uuid4())
    prov = result.metrics.get("provenance")
    if isinstance(prov, dict):
        prov.setdefault("rule_version", {})["strategy_version_id"] = str(version_id) if version_id is not None else None
    wm = (result.metrics.get("data_watermark") or {}).get("latest_session_available")
    snapshot_as_of = date.fromisoformat(wm) if wm else None
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """INSERT INTO strategy_runs
                       (id, strategy_id, version_id, run_type, status,
                        backtest_from, backtest_to,
                        metrics, equity_curve, trade_count,
                        triggered_by, finished_at, duration_ms, snapshot_as_of)
                   VALUES ($1, $2, $3, 'BACKTEST', 'OK',
                           $4, $5, $6::jsonb, $7::jsonb, $8,
                           $9, NOW(), NULL, $10)""",
                run_id, strategy_id, version_id,
                from_date, to_date,
                json.dumps(result.metrics),
                json.dumps(result.equity_curve),
                len(result.trades),
                triggered_by,
                snapshot_as_of,
            )
            for t in result.trades:
                await conn.execute(
                    """INSERT INTO strategy_trades
                           (run_id, strategy_id, symbol,
                            entry_date, entry_price, score,
                            stoploss_price, target_price, qty,
                            exit_date, exit_price, exit_reason,
                            pnl_pct, pnl_abs, holding_days,
                            brokerage, slippage_pct, metadata)
                       VALUES ($1, $2, $3,
                               $4, $5, $6,
                               $7, $8, $9,
                               $10, $11, $12,
                               $13, $14, $15,
                               $16, $17, $18::jsonb)""",
                    run_id, strategy_id, t.symbol,
                    t.entry_date, t.entry_price, t.score,
                    t.stoploss_price, t.target_price, int(t.quantity or 0),
                    t.exit_date, t.exit_price, t.exit_reason,
                    t.pnl_pct, t.pnl_abs, t.holding_days,
                    t.brokerage, t.slippage_pct, json.dumps(_trade_metadata(t), default=str),
                )
    return run_id
