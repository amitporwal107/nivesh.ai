"""Daily simulation loop (PRD §4.1, §8.2): signal → eligibility gate → sizing → order → fill → accounting → risk.

Order of events inside a session d (daily bars, so nothing inside a bar is ordered beyond what the bar proves):
  1. start_day: equity at the previous closes; drawdown pauses may auto-resume.
  2. entries for pending MOO / BUY_STOP orders at d's open or trigger (a fill at or below its stop is cancelled —
     BR-002 at fill time); a stop touched on the entry bar exits at the stop (stop-first, conservative).
  3. stop exits for positions entered before d (gap-through at the open).
  4. time exits at the close of the position's `max_sessions`-th session (s1 = entry session).
  5. MOC signals dated d are sized and filled at d's close (their signal must use data up to 15:15 only — the
     runner's responsibility).
  6. closes update breakeven / trailing stops (effective from the next session), equity is marked, end_day runs.
  7. signals dated d (MOO / BUY_STOP) are gated, sized against end-of-day state and become orders for d+1.
Signals columns: signal_id, date, symbol, arm, order_type (MOO|BUY_STOP|MOC), trigger, valid_sessions, stop,
reference_price, atr, rank [, model_version, feature_snapshot_id, available_at].
Bars columns: symbol, date, open, high, low, close, volume, value20 [, prev_close].
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Optional

import pandas as pd

from . import config as RC
from . import costs as CC
from . import execution as EX
from . import sizing as SZ
from .drawdown import DrawdownMonitor
from .ledger import Ledger
from .portfolio import Portfolio, Position


@dataclass
class Result:
    trades: pd.DataFrame
    equity: pd.DataFrame
    events: list
    decisions: list
    ledger_digest: str
    ledger: Ledger


def _dec(x, places: int = 4) -> Optional[Decimal]:
    if x is None:
        return None
    try:
        if pd.isna(x):
            return None
    except (TypeError, ValueError):
        pass
    return Decimal(str(round(float(x), places)))


def _load_bars(bars: pd.DataFrame) -> tuple[dict, list, dict, dict]:
    b = bars.copy()
    b["date"] = pd.to_datetime(b["date"]).dt.date
    b = b.sort_values(["symbol", "date"])
    if "prev_close" not in b.columns:
        b["prev_close"] = b.groupby("symbol")["close"].shift(1)
    out, v20, by_date = {}, {}, {}
    for r in b.itertuples(index=False):
        bar = EX.Bar(_dec(r.open), _dec(r.high), _dec(r.low), _dec(r.close), int(r.volume), _dec(r.prev_close))
        out[(r.symbol, r.date)] = bar
        v20[(r.symbol, r.date)] = _dec(getattr(r, "value20", None), 2)
        by_date.setdefault(r.date, []).append((r.symbol, bar))
    return out, sorted(by_date), v20, by_date


def run(signals: pd.DataFrame, bars: pd.DataFrame, cfg: RC.RiskConfig, cost_model: CC.CostModel, sectors: dict,
        exits: dict, *, eligibility: Optional[Callable] = None, allow_retroactive_costs: bool = False,
        exchange: str = "NSE", profile: str = "delivery", slippage_mult: Decimal = Decimal(1),
        ledger_path: Optional[str] = None) -> Result:
    errs = RC.validate(cfg)
    if errs:
        raise ValueError(f"invalid risk config {cfg.config_id}: {errs}")
    bar_of, calendar, value20, bars_on = _load_bars(bars)
    idx = {d: i for i, d in enumerate(calendar)}
    sig = signals.copy()
    sig["date"] = pd.to_datetime(sig["date"]).dt.date
    sig = sig.sort_values(["date", "rank", "signal_id"], ascending=[True, False, True])
    by_day = {d: g for d, g in sig.groupby("date", sort=True)}

    cfg_ver = f"{cfg.config_id}@v{cfg.version}#{RC.config_hash(cfg)[:12]}"
    cost_ver = f"{cost_model.cost_model_id}@v{cost_model.version}"
    est_pct = Decimal(str(exits["cost_estimate_pct_for_sizing"]))
    max_sessions = int(exits["max_sessions"])
    be_r, tr_r, tr_mult = (Decimal(str(exits[k])) for k in ("breakeven_at_r", "trail_at_r", "trail_atr_mult"))

    led = Ledger(ledger_path)
    pf = Portfolio(cash=cfg.capital_inr)
    mon = DrawdownMonitor(cfg)
    last_px: dict = {}
    pending: list[dict] = []           # orders waiting for their session
    trades, equity_rows, decisions = [], [], []
    oid = 0

    def slip(sym, d):
        return CC.slippage_pct(cost_model, value20.get((sym, d))) * slippage_mult

    def costs(side, value, d):
        return CC.fill_costs(cost_model, profile, exchange, side, value, dp_applies=(side == "SELL"), on_date=d,
                             allow_retroactive=allow_retroactive_costs)

    def capital_base(prices):
        return cfg.capital_inr if cfg.capital_basis == "FIXED" else pf.equity(prices)

    def close_position(p: Position, d: dt.date, price: Decimal, reason: str, realised: bool = True):
        c = costs("SELL", Decimal(p.qty) * price, d) if realised else {"total": Decimal(0), "retroactive": False}
        if realised:
            pf.cash += Decimal(p.qty) * price - c["total"]
            pf.remove(p.symbol)
        gross = Decimal(p.qty) * (price - p.entry_price)
        net = gross - p.entry_costs - c["total"]
        r_den = Decimal(p.qty) * p.r_per_share
        t = {"symbol": p.symbol, "sector": p.sector, "arm": p.arm, "signal_id": p.signal_id, "entry_date": p.entry_date,
             "entry_price": p.entry_price, "qty": p.qty, "initial_stop": p.initial_stop, "exit_date": d,
             "exit_price": price, "exit_reason": reason, "gross_pnl": gross, "costs": p.entry_costs + c["total"],
             "net_pnl": net, "r_multiple": float(net / r_den) if r_den > 0 else None,
             "sessions_held": idx[d] - p.entry_index + 1, "stop_kind": p.stop_kind,
             "binding_constraint": p.binding_constraint,
             "risk_config_id": cfg.config_id, "risk_config_version": cfg_ver, "cost_model_id": cost_model.cost_model_id,
             "retroactive_costs": bool(p.retroactive_costs or c["retroactive"]), "realised": realised}
        trades.append(t)
        led.append("trade", t)

    def decide(s, d: dt.date, stamp: str):
        """Gate + size one signal; returns (SizingResult or None, decision dict)."""
        nonlocal oid
        reasons, res = [], None
        ok, why = (eligibility(s) if eligibility else (True, None))
        ref = _dec(s["trigger"] if s["order_type"] == "BUY_STOP" else s["reference_price"])
        stop = _dec(s["stop"])
        if not ok:
            reasons = ["PIT_VIOLATION", str(why)]
        elif not mon.entries_allowed(d):
            reasons = [f"RISK_STATE_{mon.state}"]
        else:
            prices = {**last_px}
            sector = sectors.get(s["symbol"])
            held = s["symbol"] in pf.positions or any(o["symbol"] == s["symbol"] for o in pending)
            if sector is None:
                reasons = ["MISSING_INPUT", "no sector"]
            else:
                res = SZ.size(cfg, SZ.SizingInput(
                    capital=capital_base(prices), entry=ref, stop=stop,
                    cost_per_share=(ref * est_pct / 100) if ref is not None else None,
                    cash=pf.cash, reserved=pf.reserved_value(),
                    deployed_value=pf.market_value(prices) + pf.reserved_value(),
                    stock_exposure=Decimal(0), sector_exposure=pf.sector_value(sector, prices) + pf.reserved_sector(sector),
                    open_risk=pf.open_risk() + pf.reserved_risk(), avg_traded_value=value20.get((s["symbol"], d)),
                    holds_symbol=held, open_positions=len(pf.positions) + len(pending),
                    risk_multiplier=mon.risk_multiplier()))
                reasons = list(res.reasons)
        status = res.status if (res is not None and res.quantity > 0) else "REJECTED"
        snap = hashlib.sha256(json.dumps({"cash": str(pf.cash), "pos": sorted((p.symbol, p.qty, str(p.stop)) for p in pf.positions.values()),
                                          "pending": sorted(o["order_id"] for o in pending)}).encode()).hexdigest()[:16]
        dec = {"signal_id": s["signal_id"], "symbol": s["symbol"], "arm": s.get("arm"),
               "model_version": s.get("model_version", "rules"), "feature_snapshot_id": s.get("feature_snapshot_id"),
               "risk_config_version": cfg_ver, "cost_model_version": cost_ver, "portfolio_snapshot_id": snap,
               "input_prices": {"reference": ref, "stop": stop}, "stop_loss": stop,
               "proposed_quantity": res.candidates.get("risk") if res else None,
               "approved_quantity": res.quantity if (res and status != "REJECTED") else 0,
               "risk_checks": {"candidates": res.candidates if res else {}, "binding": res.binding if res else None,
                               "risk_state": mon.state},
               "rejection_reasons": reasons, "decision_status": status, "decision_timestamp": stamp}
        decisions.append(dec)
        led.append("decision", dec)
        return (res if status != "REJECTED" else None), dec

    def enter(o: dict, d: dt.date, fill: EX.Fill):
        pf.reservations.pop(o["order_id"], None)
        if fill.price <= o["stop"]:
            led.append("order", {"order_id": o["order_id"], "status": "CANCELLED", "reason": "FILL_AT_OR_BELOW_STOP", "date": d})
            return None
        c = costs("BUY", Decimal(fill.qty) * fill.price, d)
        qty = fill.qty
        if Decimal(qty) * fill.price + c["total"] > pf.cash:
            led.append("order", {"order_id": o["order_id"], "status": "CANCELLED", "reason": "INSUFFICIENT_CASH_AT_FILL", "date": d})
            return None
        pf.cash -= Decimal(qty) * fill.price + c["total"]
        p = Position(o["symbol"], o["sector"], qty, fill.price, o["stop"], d, entry_index=idx[d], entry_costs=c["total"],
                     signal_id=o["signal_id"], arm=o["arm"], atr=o["atr"], binding_constraint=o["binding"],
                     retroactive_costs=c["retroactive"])
        pf.add(p)
        led.append("fill", {"order_id": o["order_id"], "symbol": o["symbol"], "side": "BUY", "date": d, "price": fill.price,
                            "qty": qty, "status": fill.status, "costs": {k: c[k] for k in CC.COMPONENTS + ("total",)}})
        return p

    for d in calendar:
        i = idx[d]
        prices_prev = {k: v for k, v in last_px.items()}
        for e in mon.start_day(d, pf.equity(prices_prev)):
            led.append("event", e)
        # 2. entries at the open / trigger
        still = []
        for o in pending:
            if o["first_index"] > i:
                still.append(o)
                continue
            b = bar_of.get((o["symbol"], d))
            if b is None:
                if i < o["last_index"]:
                    still.append(o)
                else:
                    pf.reservations.pop(o["order_id"], None)
                    led.append("order", {"order_id": o["order_id"], "status": "EXPIRED", "reason": "NO_BAR", "date": d})
                continue
            f = EX.fill_entry(o["kind"], b, qty=o["qty"], slippage_pct=slip(o["symbol"], d),
                              participation_pct=cfg.max_volume_participation_pct, trigger=o["trigger"])
            if f.status == "NO_FILL":
                if o["kind"] == "BUY_STOP" and f.reason == "NOT_TRIGGERED" and i < o["last_index"]:
                    still.append(o)
                else:
                    pf.reservations.pop(o["order_id"], None)
                    led.append("order", {"order_id": o["order_id"], "status": "EXPIRED" if i >= o["last_index"] else "NO_FILL",
                                         "reason": f.reason, "date": d})
                continue
            p = enter(o, d, f)
            if p is not None and b.low <= p.stop:                        # stop touched on the entry bar: stop-first
                close_position(p, d, EX.px(p.stop * (1 - slip(p.symbol, d) / 100)), "STOP_SAME_DAY")
        pending = still
        # 3. stop exits for positions entered before d
        for sym in sorted(pf.positions):
            p = pf.positions[sym]
            if p.entry_index >= i:
                continue
            b = bar_of.get((sym, d))
            if b is None:
                continue
            f = EX.check_stop(b, p.stop, slip(sym, d))
            if f is None:
                continue
            if f.status == "NO_FILL":
                led.append("event", {"date": d.isoformat(), "event_type": "EXIT_BLOCKED", "symbol": sym, "reason": f.reason})
                continue
            close_position(p, d, f.price, f.reason)
        # 4. time exits at the close of the max_sessions-th session
        for sym in sorted(pf.positions):
            p = pf.positions[sym]
            b = bar_of.get((sym, d))
            if b is not None and i - p.entry_index + 1 >= max_sessions:
                f = EX.close_exit(b, slip(sym, d), "TIME")
                if f.status == "FILLED":
                    close_position(p, d, f.price, "TIME")
                else:
                    led.append("event", {"date": d.isoformat(), "event_type": "EXIT_BLOCKED", "symbol": sym, "reason": f.reason})
        # 5. MOC signals of d, filled at d's close
        today = by_day.get(d)
        if today is not None:
            for s in today[today.order_type == "MOC"].to_dict("records"):
                res, _ = decide(s, d, f"{d.isoformat()}T15:15:00+05:30")
                if res is None:
                    continue
                b = bar_of.get((s["symbol"], d))
                o = {"order_id": f"o{oid}", "signal_id": s["signal_id"], "symbol": s["symbol"], "arm": s.get("arm"),
                     "sector": sectors[s["symbol"]], "kind": "MOC", "qty": res.quantity, "trigger": None,
                     "stop": _dec(s["stop"]), "atr": _dec(s.get("atr")), "binding": res.binding}
                oid += 1
                if b is None:
                    led.append("order", {"order_id": o["order_id"], "status": "NO_FILL", "reason": "NO_BAR", "date": d})
                    continue
                f = EX.fill_entry("MOC", b, qty=o["qty"], slippage_pct=slip(o["symbol"], d),
                                  participation_pct=cfg.max_volume_participation_pct)
                if f.status == "NO_FILL":
                    led.append("order", {"order_id": o["order_id"], "status": "NO_FILL", "reason": f.reason, "date": d})
                    continue
                enter(o, d, f)
        # 6. closes: prices, breakeven / trailing (effective next session), equity, drawdown monitor
        for sym, b in bars_on[d]:
            last_px[sym] = b.close
        for p in pf.positions.values():
            b = bar_of.get((p.symbol, d))
            if b is None:
                continue
            p.highest_close = max(p.highest_close, b.close)
            r = p.r_per_share
            if r > 0 and b.close >= p.entry_price + be_r * r and p.entry_price > p.stop:
                p.stop, p.stop_kind = p.entry_price, "BREAKEVEN"
            if r > 0 and p.atr is not None and b.close >= p.entry_price + tr_r * r:
                trail = p.highest_close - tr_mult * p.atr
                if trail > p.stop:
                    p.stop, p.stop_kind = trail, "TRAILING"
        eq = pf.equity(last_px)
        for e in mon.end_day(d, eq):
            led.append("event", e)
        # 7. end-of-day signals -> orders for the next session(s)
        if today is not None:
            for s in today[today.order_type != "MOC"].to_dict("records"):
                res, _ = decide(s, d, f"{d.isoformat()}T15:30:00+05:30")
                if res is None:
                    continue
                o = {"order_id": f"o{oid}", "signal_id": s["signal_id"], "symbol": s["symbol"], "arm": s.get("arm"),
                     "sector": sectors[s["symbol"]], "kind": s["order_type"], "qty": res.quantity,
                     "trigger": _dec(s["trigger"]) if s["order_type"] == "BUY_STOP" else None, "stop": _dec(s["stop"]),
                     "atr": _dec(s.get("atr")), "binding": res.binding, "first_index": i + 1,
                     "last_index": i + int(s.get("valid_sessions") or 1)}
                oid += 1
                ref = o["trigger"] if o["kind"] == "BUY_STOP" else _dec(s["reference_price"])
                value = Decimal(o["qty"]) * ref * (1 + est_pct / 100)
                pf.reservations[o["order_id"]] = (o["symbol"], o["sector"], value, Decimal(o["qty"]) * (ref - o["stop"]))
                pending.append(o)
                led.append("order", {"order_id": o["order_id"], "signal_id": o["signal_id"], "symbol": o["symbol"],
                                     "kind": o["kind"], "qty": o["qty"], "status": "PLACED", "date": d})
        equity_rows.append({"date": d, "cash": pf.cash, "market_value": pf.market_value(last_px), "equity": eq,
                            "open_risk": pf.open_risk(), "positions": len(pf.positions), "state": mon.state,
                            "drawdown_pct": mon.drawdown_pct()})
    # positions still open at the end of the data: marked at the last close, flagged unrealised
    for sym in sorted(list(pf.positions)):
        p = pf.positions[sym]
        close_position(p, calendar[-1], last_px[sym], "OPEN_AT_END", realised=False)
    return Result(pd.DataFrame(trades), pd.DataFrame(equity_rows), list(mon.events), decisions, led.digest(), led)
