"""Strategy analytics of one paper account (docs/scanner_paper_trading/UI_DESIGN_V2.md §2.06, §4 item 5, §7
`GET /api/v1/analytics/account/{id}?days=90`). Reads only.

TRADES  the caller's CLOSED SPT positions (spt_positions, slice C) closed within the last `days` days (IST). Desk paper
        trades are NOT included: they did not come through the scanner pipeline, so they have no setup type and no
        regime at entry to group by (their own journal is on the P&L screen).
        net_rs   the position's realized_net_rs: exit proceeds − entry cost − every fill's charges (net of costs)
        r        the position's outcome r_multiple (net_rs ÷ initial risk = (average entry − initial stop) × entry
                 quantity); else net_rs ÷ initial_risk_rs; a trade with no initial risk has no R and is left out of the
                 R figures (counted in notes)
        setup    the opportunity's category (the proposal's opportunity summary, else the opportunity), lower case
        regime   the opportunity's validation market regime at entry (services/spt/opportunities/validate: the desk
                 regime, macro_engine.classify_desk_regime): bullish → uptrend, bearish → downtrend, sideways → sideways;
                 high_volatility and mixed by the regime's own Nifty trend (up / down / flat); none → unknown
FIGURES wins (net > 0), losses (net < 0), win_rate_pct, avg_win_r, avg_loss_r, expectancy_r (mean R), profit_factor
        (Σ net of wins ÷ |Σ net of losses|; null with a reason when there is no loss), max_drawdown_pct (peak to trough
        of starting capital + the cumulative net P&L of the window's trades, by close day).
RATIOS  Sharpe and Sortino from the DAILY series: every weekday from the first trade's entry day through today, the net
        P&L of the trades closed that day (0 on a day without a close) ÷ the equity at the start of that day; annualised
        × √252. Realised only: no daily mark of the open SPT positions is stored. Fewer than MIN_RATIO_DAYS points → null
        with `ratio_reason`. Sortino's downside deviation = √(mean(min(r, 0)²)); none below 0 → null with the reason.
CERTIFICATION per setup (§2.06): minimum 50 completed trades; positive net expectancy; profit factor ≥ 1.3; out of
        sample (`not_measured`: no walk-forward split exists yet); two or more market regimes. A passing figure on fewer
        than SMALL_SAMPLE trades is `warn`. certified only when every criterion passes.
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from services import data_freshness as fresh

from . import constants as C

logger = logging.getLogger(__name__)

VERSION = "spt-account-analytics-v1"
DEFAULT_DAYS, MAX_DAYS = 90, 365
MIN_TRADES = 50
PF_MIN = 1.3
SMALL_SAMPLE = 30
MIN_RATIO_DAYS = 20
TRADING_DAYS = 252
REGIMES = ("uptrend", "sideways", "downtrend")
BY_KEY = {"bullish": "uptrend", "bearish": "downtrend", "sideways": "sideways"}
BY_TREND = {"up": "uptrend", "down": "downtrend", "flat": "sideways"}
MAX_ROWS = 5000
BASIS = ("Closed scanner (SPT) paper positions of the window, net of every fill's charges; R = net P&L ÷ initial price "
         "risk; desk paper trades are not included (no setup type or regime at entry). Sharpe / Sortino on the realised "
         "daily P&L series.")


def _f(x: Any) -> Optional[float]:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(float(x)):
        return None
    return float(x)


def _r(x: Optional[float], dp: int = 2) -> Optional[float]:
    return None if x is None else round(x + 0.0, dp)


def ist_day(stamp: Any) -> Optional[date]:
    if not stamp:
        return None
    try:
        d = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=fresh.IST)
    return d.astimezone(fresh.IST).date()


def regime_of(market: Optional[Dict[str, Any]]) -> Tuple[str, Optional[str]]:
    """(uptrend | sideways | downtrend | unknown, the desk regime key) — module docstring."""
    m = market or {}
    key = m.get("key")
    if key in BY_KEY:
        return BY_KEY[key], key
    if key in ("high_volatility", "mixed"):
        return BY_TREND.get(str(m.get("trend") or ""), "unknown"), key
    return "unknown", key


def trade_rows(positions: List[Dict[str, Any]], proposals: Dict[str, Dict[str, Any]],
               opportunities: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for p in positions:
        net = _f(p.get("realized_net_rs"))
        if net is None:
            continue
        oc = p.get("outcome") or {}
        r = _f(oc.get("r_multiple"))
        if r is None:
            risk0 = _f(p.get("initial_risk_rs"))
            r = net / risk0 if risk0 else None
        prop = proposals.get(p.get("proposal_id") or "") or {}
        opp = opportunities.get(p.get("opportunity_id") or prop.get("opportunity_id") or "") or {}
        setup = (prop.get("opportunity") or {}).get("category") or opp.get("category") or "unknown"
        regime, desk_key = regime_of((opp.get("validation") or {}).get("market"))
        out.append({"position_id": p.get("_id"), "symbol": p.get("symbol"), "net_rs": net, "r": r,
                    "setup": str(setup).lower(), "regime": regime, "desk_regime": desk_key,
                    "opened_day": ist_day(p.get("opened_at")), "closed_day": ist_day(p.get("closed_at"))})
    return out


def stats(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(trades)
    wins = [t for t in trades if t["net_rs"] > 0]
    losses = [t for t in trades if t["net_rs"] < 0]
    rs = [t["r"] for t in trades if t["r"] is not None]
    win_r = [t["r"] for t in wins if t["r"] is not None]
    loss_r = [t["r"] for t in losses if t["r"] is not None]
    gross_win = sum(t["net_rs"] for t in wins)
    gross_loss = -sum(t["net_rs"] for t in losses)
    pf, pf_reason = None, None
    if not n:
        pf_reason = "no closed trade"
    elif gross_loss <= 0:
        pf_reason = "no losing trade yet, so the profit factor is undefined"
    else:
        pf = gross_win / gross_loss
    return {"trades": n, "wins": len(wins), "losses": len(losses),
            "win_rate_pct": _r(len(wins) / n * 100.0) if n else None,
            "avg_win_r": _r(sum(win_r) / len(win_r), 3) if win_r else None,
            "avg_loss_r": _r(sum(loss_r) / len(loss_r), 3) if loss_r else None,
            "expectancy_r": _r(sum(rs) / len(rs), 3) if rs else None,
            "profit_factor": _r(pf, 3), "profit_factor_reason": pf_reason,
            "net_rs": _r(sum(t["net_rs"] for t in trades)), "r_missing": n - len(rs)}


def weekdays(a: date, b: date) -> List[date]:
    out, d = [], a
    while d <= b:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def daily_series(trades: List[Dict[str, Any]], start_capital: float, today: date) -> List[Dict[str, Any]]:
    if not trades:
        return []
    first = min(t["opened_day"] or t["closed_day"] for t in trades if (t["opened_day"] or t["closed_day"]))
    by_day: Dict[date, float] = {}
    for t in trades:
        if t["closed_day"]:
            by_day[t["closed_day"]] = by_day.get(t["closed_day"], 0.0) + t["net_rs"]
    eq = start_capital
    out = []
    for d in weekdays(first, max(today, max(by_day) if by_day else today)):
        pnl = by_day.get(d, 0.0)
        out.append({"day": d.isoformat(), "pnl_rs": round(pnl, 2), "ret": pnl / eq if eq > 0 else 0.0})
        eq += pnl
    return out


def ratios(series: List[Dict[str, Any]]) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    n = len(series)
    if n < MIN_RATIO_DAYS:
        return None, None, (f"{n} daily points since the first closed trade; at least {MIN_RATIO_DAYS} are needed for "
                            "Sharpe and Sortino")
    rets = [p["ret"] for p in series]
    mean = sum(rets) / n
    sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / (n - 1))
    down = math.sqrt(sum(min(r, 0.0) ** 2 for r in rets) / n)
    sharpe = mean / sd * math.sqrt(TRADING_DAYS) if sd > 0 else None
    sortino = mean / down * math.sqrt(TRADING_DAYS) if down > 0 else None
    why = None
    if sharpe is None:
        why = "the daily P&L does not vary, so Sharpe is undefined"
    elif sortino is None:
        why = "no losing day in the series, so Sortino's downside deviation is zero"
    return _r(sharpe, 3), _r(sortino, 3), why


def max_drawdown(trades: List[Dict[str, Any]], start_capital: float) -> Optional[float]:
    if not trades:
        return None
    eq = peak = start_capital
    worst = 0.0
    for t in sorted(trades, key=lambda t: (t["closed_day"] or date.min, str(t["position_id"]))):
        eq += t["net_rs"]
        peak = max(peak, eq)
        if peak > 0:
            worst = max(worst, (peak - eq) / peak * 100.0)
    return round(worst, 4)


def _crit(key: str, label: str, status: str, value: Any) -> Dict[str, Any]:
    return {"key": key, "label": label, "status": status, "value": value}


def certification(setup: str, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    s = stats(trades)
    n = s["trades"]
    small = n < SMALL_SAMPLE
    crits = [_crit("min_trades", f"Minimum {MIN_TRADES} completed trades", "pass" if n >= MIN_TRADES else "fail",
                   f"{n} / {MIN_TRADES}")]
    e = s["expectancy_r"]
    crits.append(_crit("positive_expectancy", "Positive net expectancy",
                       "not_measured" if e is None else ("fail" if e <= 0 else ("warn" if small else "pass")),
                       "no R measured" if e is None else f"{e:+.2f}R"))
    pf = s["profit_factor"]
    crits.append(_crit("profit_factor", f"Profit factor ≥ {PF_MIN:g}",
                       "not_measured" if pf is None else ("fail" if pf < PF_MIN else ("warn" if small else "pass")),
                       s["profit_factor_reason"] if pf is None else f"{pf:.2f}"))
    crits.append(_crit("out_of_sample", "Out-of-sample validated", "not_measured", "no walk-forward split yet"))
    known = sorted({t["regime"] for t in trades if t["regime"] != "unknown"})
    crits.append(_crit("regimes", "Two or more market regimes",
                       "not_measured" if not known else ("pass" if len(known) >= 2 else "fail"),
                       f"{len(known)}: {', '.join(known)}" if known else "no regime recorded at entry"))
    return {"setup": setup, "trades": n, "criteria": crits, "certified": all(c["status"] == "pass" for c in crits)}


def build(trades: List[Dict[str, Any]], *, days: int, start_capital: float, today: date, skipped: int = 0
          ) -> Dict[str, Any]:
    s = stats(trades)
    series = daily_series(trades, start_capital, today)
    sharpe, sortino, why = ratios(series)
    setups = sorted({t["setup"] for t in trades})
    by_setup = []
    for st in setups:
        x = stats([t for t in trades if t["setup"] == st])
        by_setup.append({"setup": st, "trades": x["trades"], "expectancy_r": x["expectancy_r"],
                         "profit_factor": x["profit_factor"], "win_rate_pct": x["win_rate_pct"], "net_rs": x["net_rs"]})
    by_regime = []
    for rg in REGIMES + ("unknown",):
        group = [t for t in trades if t["regime"] == rg]
        if rg == "unknown" and not group:
            continue
        x = stats(group)
        keys: Dict[str, int] = {}
        for t in group:
            keys[str(t["desk_regime"])] = keys.get(str(t["desk_regime"]), 0) + 1
        by_regime.append({"regime": rg, "trades": x["trades"], "expectancy_r": x["expectancy_r"], "desk_regimes": keys})
    notes = []
    if not trades:
        notes.append(f"No scanner paper trade closed in the last {days} days.")
    if s["r_missing"]:
        notes.append(f"{s['r_missing']} trade(s) have no initial risk, so no R; they count in the trade and win figures only.")
    if skipped:
        notes.append(f"{skipped} closed position(s) had no realised P&L recorded and are left out.")
    return {"days": days, **{k: s[k] for k in ("trades", "wins", "losses", "win_rate_pct", "avg_win_r", "avg_loss_r",
                                               "expectancy_r", "profit_factor", "profit_factor_reason", "net_rs")},
            "max_drawdown_pct": max_drawdown(trades, start_capital), "sharpe": sharpe, "sortino": sortino,
            "ratio_reason": why, "daily_points": len(series), "by_setup": by_setup, "by_regime": by_regime,
            "certification": [certification(st, [t for t in trades if t["setup"] == st]) for st in setups],
            "basis": BASIS, "start_capital_rs": start_capital, "notes": notes, "version": VERSION,
            "thresholds": {"min_trades": MIN_TRADES, "profit_factor": PF_MIN, "small_sample": SMALL_SAMPLE,
                           "min_ratio_days": MIN_RATIO_DAYS}}


async def read(db, user_id: str, *, days: int, now: datetime) -> Dict[str, Any]:
    from services import paper_account
    today = fresh.ist_today(now)
    since = today - timedelta(days=days)
    docs = await db[C.POSITIONS].find({"user_id": user_id, "state": C.POS_CLOSED}).to_list(MAX_ROWS)
    docs = [d for d in docs if (ist_day(d.get("closed_at")) or date.min) > since]
    skipped = sum(1 for d in docs if _f(d.get("realized_net_rs")) is None)
    prop_ids = [d.get("proposal_id") for d in docs if d.get("proposal_id")]
    props = {p["_id"]: p for p in await db[C.PROPOSALS].find({"_id": {"$in": prop_ids}}).to_list(len(prop_ids) or 1)} \
        if prop_ids else {}
    opp_ids = sorted({d.get("opportunity_id") or (props.get(d.get("proposal_id") or "") or {}).get("opportunity_id")
                      for d in docs} - {None})
    opps = {o["_id"]: o for o in await db[C.OPPORTUNITIES].find({"_id": {"$in": opp_ids}}).to_list(len(opp_ids) or 1)} \
        if opp_ids else {}
    acct = await paper_account.read(db, user_id)
    start = float(acct.get("starting_capital_rs") or paper_account.DEFAULT_CAPITAL)
    return {"account_id": user_id, **build(trade_rows(docs, props, opps), days=days, start_capital=start, today=today,
                                           skipped=skipped)}
