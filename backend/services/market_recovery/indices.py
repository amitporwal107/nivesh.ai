"""Market Recovery › Nifty and Bank Nifty by expiry (docs/market_recovery/DESIGN.md §9; owner, 4 Nov 2026).

Per index: the close and its technicals (index closes, the scan builder's indicator conventions), classic floor pivots, the
futures build-up per contract, levels above and below the close, and — the owner's point — the option positioning of EVERY live
expiry separately (weekly and monthly): PCR, max pain, the ATM straddle's implied range, walls, OI additions and cuts, and
rule-based setups per expiry (Bull Call Spread, Bear Put Spread, Iron Condor, a hedge put spread) priced from that expiry's
end-of-day chain. Plus India VIX, Bank Nifty's relative strength, NSE FII/DII cash and, for Nifty, what the expiries say together.

Reads only, all through sources the app already uses (routes/fno for chains and futures — current session, unexpired series —,
DaaS index closes, the DaaS market pulse for FII/DII). Payoffs: services/strategy_plan/payoff.py; leg liquidity:
candidates.leg_view. Nothing is stored and nothing is sent to a broker. Leg words Buy / Sell (the owner's choice for this page).
"""
from __future__ import annotations

import asyncio
import logging
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
from fastapi import HTTPException, Request

from services.scan_builder import indicators as ind
from services.scan_builder.data import DataUnavailable
from services.strategy_plan import payoff as po
from services.strategy_plan.candidates import iv_fences

from .engine import fnum
from .strategies import MIN_RR, CREDIT_MIN_WIDTH_FRACTION, option_leg

logger = logging.getLogger(__name__)

INDICES = (("NIFTY", "Nifty 50"), ("BANKNIFTY", "Nifty Bank"))
DISPLAY = {"NIFTY": "Nifty 50", "BANKNIFTY": "Bank Nifty"}
VIX = "India VIX"
MAX_DAYS = 70
ACTIVE_SHARE = 0.15           # volume share of the busiest expiry
THIN_VOLUME_SHARE = 0.02
THIN_OI_SHARE = 0.05
HISTORY_DAYS = 1100           # calendar days of index closes (EMA200 + 52 weeks + margin)
CACHE_S = 900.0
LEVELS_EACH = 5

LABEL = {"bull_call_spread": "Bull Call Spread", "bear_put_spread": "Bear Put Spread", "iron_condor": "Iron Condor",
         "hedge_put_spread": "Hedge put spread"}
BUILDUP = {"long_buildup": "long build-up", "short_covering": "short covering", "short_buildup": "short build-up",
           "long_unwinding": "long unwinding"}
NOTES = [
    "End of day: index closes, the NSE F&O bhavcopy option chains and futures of the date shown. Each expiry is read on its own; "
    "a series that expired on that date is never used.",
    "Open interest is in units (shares of the index lot), shown in lakh (L).",
    "Setups are rule-based from each expiry's chain: one lot, figures at expiry, before costs; conditional ideas, not advice. "
    "Exchange margin for written options is not estimated here.",
]


def _r(x: Optional[float], dp: int = 2) -> Optional[float]:
    return None if x is None else round(float(x) + 0.0, dp)


# ── technicals (pure) ─────────────────────────────────────────────────────────────────────────────────────────────────

def technicals(closes: Sequence[float], highs: Sequence[float], lows: Sequence[float]) -> Dict[str, Any]:
    c = np.asarray(closes, dtype=float).reshape(-1, 1)
    h = np.asarray(highs, dtype=float).reshape(-1, 1)
    l = np.asarray(lows, dtype=float).reshape(-1, 1)
    n = c.shape[0]
    last = lambda a, back=0: fnum(a[-1 - back, 0]) if a.shape[0] > back else None        # noqa: E731
    e20, e50, e200 = ind.ema(c, 20), ind.ema(c, 50), ind.ema(c, 200)
    rsi = ind.rsi(c, 14)
    line, sig, hist = ind.macd(c, 26, 12, 9)
    atr = ind.atr(h, l, c, 14)
    close = last(c)
    pct = lambda ref: None if ref in (None, 0) or close is None else 100.0 * (close / ref - 1.0)     # noqa: E731
    hi20 = float(np.nanmax(h[-20:])) if n >= 20 else None
    lo20 = float(np.nanmin(l[-20:])) if n >= 20 else None
    hi52 = float(np.nanmax(h[-252:])) if n else None
    lo52 = float(np.nanmin(l[-252:])) if n else None
    out = {
        "ema20": last(e20), "ema50": last(e50), "ema200": last(e200),
        "vs_ema20_pct": pct(last(e20)), "vs_ema50_pct": pct(last(e50)), "vs_ema200_pct": pct(last(e200)),
        "rsi14": last(rsi), "rsi14_5ago": last(rsi, 5),
        "macd": last(line), "macd_signal": last(sig), "macd_hist": last(hist), "macd_hist_prev": last(hist, 1),
        "atr14": last(atr), "atr_pct": None if last(atr) is None or not close else 100.0 * last(atr) / close,
        "high20": hi20, "low20": lo20, "high52": hi52, "low52": lo52,
        "from_high52_pct": pct(hi52), "from_low52_pct": pct(lo52), "sessions": n,
    }
    return {k: (_r(v) if isinstance(v, float) else v) for k, v in out.items()}


def pivots(h: float, l: float, c: float) -> Dict[str, float]:
    p = (h + l + c) / 3.0
    return {"p": _r(p), "r1": _r(2 * p - l), "r2": _r(p + (h - l)), "r3": _r(h + 2 * (p - l)),
            "s1": _r(2 * p - h), "s2": _r(p - (h - l)), "s3": _r(l - 2 * (h - p))}


def up_streak(closes: Sequence[float]) -> int:
    """Consecutive up closes ending at the last one (negative = consecutive down closes)."""
    n, sign = 0, 0
    for i in range(len(closes) - 1, 0, -1):
        d = closes[i] - closes[i - 1]
        s = 1 if d > 0 else -1 if d < 0 else 0
        if s == 0 or (sign and s != sign):
            break
        sign = s
        n += 1
    return n * sign


def buildup(price_chg: Optional[float], oi_chg: Optional[float]) -> Optional[str]:
    if price_chg is None or oi_chg is None or price_chg == 0 or oi_chg == 0:
        return None
    if price_chg > 0:
        return "long_buildup" if oi_chg > 0 else "short_covering"
    return "short_buildup" if oi_chg > 0 else "long_unwinding"


# ── expiries (pure) ───────────────────────────────────────────────────────────────────────────────────────────────────

def expiry_kinds(expiries: Sequence[str], monthly_only: bool = False) -> Dict[str, str]:
    """weekly / monthly: a monthly is the last listed expiry of its calendar month."""
    last: Dict[str, str] = {}
    for e in sorted(expiries):
        last[e[:7]] = e
    return {e: "monthly" if (monthly_only or last[e[:7]] == e) else "weekly" for e in expiries}


def liquidity(volume: float, oi: float, max_volume: float, max_oi: float) -> str:
    vs = volume / max_volume if max_volume else 0.0
    os_ = oi / max_oi if max_oi else 0.0
    if vs >= ACTIVE_SHARE:
        return "active"
    if vs < THIN_VOLUME_SHARE and os_ < THIN_OI_SHARE:
        return "too_thin"
    return "thin"


def _price(side: Optional[Dict[str, Any]]) -> Tuple[Optional[float], Optional[str]]:
    s = side or {}
    c, st = fnum(s.get("close")), fnum(s.get("settle"))
    if c and c > 0:
        return c, "close"
    if st and st > 0:
        return st, "settlement"
    return None, None


def _top(rows: Sequence[Dict[str, Any]], side: str, field: str, n: int, reverse: bool = True,
         keep: Callable[[float], bool] = lambda v: True) -> List[Dict[str, Any]]:
    vals = [(float(r["strike"]), fnum((r.get(side) or {}).get(field))) for r in rows if r.get(side)]
    vals = [(k, v) for k, v in vals if v is not None and keep(v)]
    vals.sort(key=lambda kv: (-kv[1], kv[0]) if reverse else (kv[1], kv[0]))
    key = "oi" if field == "oi" else "change"
    return [{"strike": _r(k, 2), key: int(v)} for k, v in vals[:n]]


def _lakh(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x / 1e5:,.1f}L"


def _wall(v: Any) -> Optional[float]:
    """routes/fno summarise_chain gives a wall as {"strike", "oi"} (top_oi_strike); accept a bare number too."""
    return fnum(v.get("strike")) if isinstance(v, dict) else fnum(v)


def expiry_view(chain: Dict[str, Any], expiry: str, days: int, kind: str, liq: str, volume: float) -> Dict[str, Any]:
    s = chain.get("summary") or {}
    rows = chain.get("strikes") or []
    spot = fnum(s.get("spot"))
    atm = fnum(s.get("atm_strike"))
    row = next((r for r in rows if fnum(r.get("strike")) == atm), None)
    ce, _ = _price((row or {}).get("call"))
    pe, _ = _price((row or {}).get("put"))
    straddle = None if ce is None or pe is None else ce + pe
    out = {
        "expiry": expiry, "days": days, "kind": kind, "liquidity": liq, "volume": int(volume),
        "pcr": _r(fnum(s.get("pcr"))), "call_oi": s.get("total_call_oi"), "put_oi": s.get("total_put_oi"),
        "max_pain": fnum(s.get("max_pain")), "atm": atm, "atm_call": _r(ce), "atm_put": _r(pe), "straddle": _r(straddle),
        "move_pct": None if straddle is None or not spot else _r(100.0 * straddle / spot),
        "range_lo": None if straddle is None or spot is None else round(spot - straddle),
        "range_hi": None if straddle is None or spot is None else round(spot + straddle),
        "call_wall": _wall(s.get("call_wall")), "put_wall": _wall(s.get("put_wall")),
        "call_oi_top": _top(rows, "call", "oi", 3), "put_oi_top": _top(rows, "put", "oi", 3),
        "call_adds": _top(rows, "call", "change_in_oi", 3, keep=lambda v: v > 0),
        "put_adds": _top(rows, "put", "change_in_oi", 3, keep=lambda v: v > 0),
        "call_cuts": _top(rows, "call", "change_in_oi", 2, reverse=False, keep=lambda v: v < 0),
        "put_cuts": _top(rows, "put", "change_in_oi", 2, reverse=False, keep=lambda v: v < 0),
    }
    out["read"] = expiry_read(out)
    return out


def _ks(items: Sequence[Dict[str, Any]], key: str) -> str:
    return ", ".join(f"{i['strike']:,.0f} ({'+' if key == 'change' and i[key] > 0 else ''}{_lakh(i[key])})" for i in items) or "none"


def expiry_read(e: Dict[str, Any]) -> str:
    when = f"{e['kind'].capitalize()} {date.fromisoformat(e['expiry']).strftime('%-d %b')}"
    if e["liquidity"] == "too_thin":
        return f"{when}: too little open interest and volume to read."
    parts = []
    if e["range_lo"] is not None:
        parts.append(f"the ATM straddle prices {e['range_lo']:,}–{e['range_hi']:,} (±{e['move_pct']:.2f}%) by expiry")
    if e["call_wall"]:
        parts.append(f"heaviest calls at {e['call_wall']:,.0f}" + (f", new calls at {_ks(e['call_adds'], 'change')}" if e["call_adds"] else ""))
    if e["put_wall"]:
        parts.append(f"heaviest puts at {e['put_wall']:,.0f}" + (f", new puts at {_ks(e['put_adds'], 'change')}" if e["put_adds"] else ""))
    if e["pcr"] is not None:
        parts.append(f"PCR {e['pcr']:.2f}, max pain {e['max_pain']:,.0f}" if e["max_pain"] else f"PCR {e['pcr']:.2f}")
    txt = f"{when}: " + "; ".join(parts) + "."
    if e["liquidity"] == "thin":
        txt += " Thin series: use limit orders."
    return txt


# ── setups (pure) ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _priced(rows: Sequence[Dict[str, Any]], side: str) -> List[float]:
    return sorted(float(r["strike"]) for r in rows if _price(r.get(side))[0] is not None)


def _liquid(rows: Sequence[Dict[str, Any]], side: str) -> List[float]:
    """Strikes whose contract traded that day with open interest (a traded close, OI > 0, volume > 0): the only strikes a
    wing or a hedge leg is picked from (3 Nov: a 1%-out wing landed on an untraded 25,250 call priced at settlement)."""
    out = []
    for r in rows:
        x = r.get(side) or {}
        if (fnum(x.get("close")) or 0) > 0 and (fnum(x.get("oi")) or 0) > 0 and (fnum(x.get("volume")) or 0) > 0:
            out.append(float(r["strike"]))
    return sorted(out)


def _nearest(ks: Sequence[float], x: float) -> Optional[float]:
    return min(ks, key=lambda k: (abs(k - x), k)) if ks else None


def _heaviest(rows, side: str, lo: float, hi: float) -> Optional[float]:
    best = None
    for r in rows:
        k = float(r["strike"])
        if lo < k <= hi or (lo <= k < hi and side == "put"):
            oi = fnum((r.get(side) or {}).get("oi")) or 0.0
            if _price(r.get(side))[0] is not None and (best is None or oi > best[1]):
                best = (k, oi)
    return best[0] if best else None


def setup_strikes(key: str, e: Dict[str, Any], rows: Sequence[Dict[str, Any]], close: float) -> Optional[Dict[str, float]]:
    atm, lo, hi = e.get("atm"), e.get("range_lo"), e.get("range_hi")
    calls, puts = _priced(rows, "call"), _priced(rows, "put")
    lcalls, lputs = _liquid(rows, "call"), _liquid(rows, "put")
    if atm is None or lo is None or hi is None:
        return None
    if key == "bull_call_spread":
        k2 = _heaviest(rows, "call", atm, hi) or _nearest([k for k in lcalls if k > atm], hi)
        return {"long_call": atm, "short_call": k2} if k2 and atm in calls else None
    if key == "bear_put_spread":
        k2 = _heaviest(rows, "put", lo, atm) or _nearest([k for k in lputs if k < atm], lo)
        return {"long_put": atm, "short_put": k2} if k2 and atm in puts else None
    if key == "iron_condor":
        cw, pw = e.get("call_wall"), e.get("put_wall")
        if not cw or not pw or cw <= atm or pw >= atm or cw not in calls or pw not in puts:
            return None
        wing = 0.01 * close
        cl = _nearest([k for k in lcalls if k > cw], cw + wing)
        pl = _nearest([k for k in lputs if k < pw], pw - wing)
        return {"short_call": cw, "long_call": cl, "short_put": pw, "long_put": pl} if cl and pl else None
    if key == "hedge_put_spread":
        k1 = _nearest([k for k in lputs if k < close], close * 0.99)
        k2 = _nearest([k for k in lputs if k1 is not None and k < k1], lo)
        return {"long_put": k1, "short_put": k2} if k1 and k2 else None
    raise ValueError(key)


def _legs(key: str, k: Dict[str, float], lot: int, rows, fences) -> List[Dict[str, Any]]:
    rows_by = {float(r["strike"]): r for r in rows}
    L = lambda i, act, side, strike: option_leg(i, act, side, strike, 1, lot, rows_by, list(rows), fences)  # noqa: E731
    if key == "bull_call_spread":
        return [L(0, "Buy", "call", k["long_call"]), L(1, "Sell", "call", k["short_call"])]
    if key == "bear_put_spread":
        return [L(0, "Buy", "put", k["long_put"]), L(1, "Sell", "put", k["short_put"])]
    if key == "iron_condor":
        return [L(0, "Sell", "put", k["short_put"]), L(1, "Buy", "put", k["long_put"]),
                L(2, "Sell", "call", k["short_call"]), L(3, "Buy", "call", k["long_call"])]
    return [L(0, "Buy", "put", k["long_put"]), L(1, "Sell", "put", k["short_put"])]


def _when(key: str, k: Dict[str, float], e: Dict[str, Any]) -> str:
    if key == "bull_call_spread":
        return f"If it rises toward {k['short_call']:,.0f}"
    if key == "bear_put_spread":
        return f"If it breaks below {(e.get('put_wall') or k['short_put']):,.0f}"
    if key == "iron_condor":
        return f"If it stays {k['short_put']:,.0f}–{k['short_call']:,.0f}"
    return "To protect long stocks against a fall"


def build_setups(e: Dict[str, Any], chain: Dict[str, Any], close: float) -> List[Dict[str, Any]]:
    if e["liquidity"] == "too_thin":
        return []
    rows = chain.get("strikes") or []
    lot = int(chain.get("lot_size") or 0)
    if lot <= 0:
        return []
    fences = iv_fences(list(rows))
    day = (chain.get("summary") or {}).get("as_of") or ""
    out = []
    for key in ("bull_call_spread", "bear_put_spread", "iron_condor", "hedge_put_spread"):
        k = setup_strikes(key, e, rows, close)
        if not k:
            continue
        legs = _legs(key, k, lot, rows, fences)
        if any(l["entry_price"] is None for l in legs):
            continue
        lo, hi = close * 0.85, close * 1.15
        grid = [lo + (hi - lo) * i / 60 for i in range(61)]
        ext = po.extremes(legs, lo, hi, grid)
        net = po.net_premium(legs)
        mx_gain, mx_loss = ext["max_profit"], ext["max_loss"]
        rr = None if key == "hedge_put_spread" or mx_gain is None or not mx_loss or mx_loss >= 0 else mx_gain / -mx_loss
        checks = []
        bad = [l["_view"] for l in legs if l["_view"]["blockers"]]
        checks.append({"id": "liquid", "label": "Every leg traded that day", "pass": not bad,
                       "detail": "; ".join(f"{v['instrument']} {v['strike']:,.0f}: {', '.join(b.replace('_', ' ') for b in v['blockers'])}"
                                           for v in bad) or "Each leg has a premium, open interest and trades."})
        if key in ("bull_call_spread", "bear_put_spread"):
            checks.append({"id": "reward_risk", "label": f"Reward : risk at least {MIN_RR:g}", "pass": None if rr is None else rr >= MIN_RR,
                           "detail": "Not measurable." if rr is None else f"{rr:.2f} : 1"})
        if key == "iron_condor":
            width = max(k["long_call"] - k["short_call"], k["short_put"] - k["long_put"]) * lot
            ok = width > 0 and net >= CREDIT_MIN_WIDTH_FRACTION * width
            checks.append({"id": "credit", "label": "Credit at least a third of the wider wing", "pass": ok,
                           "detail": f"credit ₹{net:,.0f} vs wing ₹{width:,.0f}"})
        if e["liquidity"] == "thin":
            checks.append({"id": "thin", "label": "Thin series", "pass": None, "detail": "Use limit orders; the spread between bid and ask can be wide."})
        fails = [c for c in checks if c["pass"] is False]
        out.append({
            "expiry": e["expiry"], "kind": e["kind"], "key": key, "label": LABEL[key], "when": _when(key, k, e), "lot_size": lot,
            "legs": [{kk: v for kk, v in l["_view"].items() if kk != "blockers"} for l in legs],
            "net_premium": _r(net), "max_gain": _r(mx_gain), "max_loss": _r(mx_loss), "reward_risk": _r(rr),
            "breakevens": [_r(x) for x in po.breakevens(legs, lo, hi, grid)["all"]],
            "status": "fails" if fails else "passes",
            "why": "; ".join(f"{c['label']}: {c['detail']}" for c in fails) or None, "checks": checks, "as_of": day,
        })
    return out


# ── levels and reads (pure) ───────────────────────────────────────────────────────────────────────────────────────────

def levels(close: float, tech: Dict[str, Any], piv: Dict[str, float], expiries: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    cands: List[Tuple[float, str]] = []
    for k, lab in (("ema20", "20-day average (EMA)"), ("ema50", "50-day average (EMA)"), ("ema200", "200-day average (EMA)"),
                   ("high20", "20-session high"), ("low20", "20-session low")):
        if tech.get(k):
            cands.append((tech[k], lab))
    for k, lab in (("r1", "pivot R1"), ("r2", "pivot R2"), ("p", "pivot"), ("s1", "pivot S1"), ("s2", "pivot S2")):
        if piv.get(k):
            cands.append((piv[k], lab))
    near = next((e for e in expiries if e["liquidity"] == "active"), None)
    monthly = next((e for e in expiries if e["kind"] == "monthly" and e["liquidity"] != "too_thin"), None)
    for e in [x for x in (near, monthly) if x]:
        tag = f"{e['kind']} {date.fromisoformat(e['expiry']).strftime('%-d %b')}"
        if e.get("call_wall"):
            cands.append((e["call_wall"], f"call wall, {tag}"))
        if e.get("put_wall"):
            cands.append((e["put_wall"], f"put wall, {tag}"))
        if e.get("max_pain"):
            cands.append((e["max_pain"], f"max pain, {tag}"))
    merged: List[Dict[str, Any]] = []
    for lvl, lab in sorted(cands):
        if merged and abs(lvl - merged[-1]["level"]) <= close * 0.0005:
            if lab not in merged[-1]["label"]:
                merged[-1]["label"] += f" · {lab}"
            continue
        merged.append({"level": _r(lvl), "label": lab})
    above = [m for m in merged if m["level"] > close][:LEVELS_EACH]
    below = [m for m in reversed(merged) if m["level"] < close][:LEVELS_EACH]
    return {"above": above, "below": below}


def index_read(name: str, close: float, chg_pct: Optional[float], streak: int, tech: Dict[str, Any],
               fut: Sequence[Dict[str, Any]]) -> List[str]:
    out = []
    if chg_pct is not None:
        s = f"{name} closed {chg_pct:+.2f}% at {close:,.2f}"
        if abs(streak) >= 2:
            s += f", {'up' if streak > 0 else 'down'} {abs(streak)} sessions in a row"
        out.append(s + ".")
    for k, lab in (("ema200", "200-day"), ("ema50", "50-day")):
        v, p = tech.get(k), tech.get(f"vs_{k}_pct")
        if v and p is not None:
            out.append(f"{'Above' if p > 0 else 'Below'} its {lab} average ({v:,.2f}, {p:+.2f}%).")
    if tech.get("rsi14") is not None:
        mom = f"RSI {tech['rsi14']:.0f}" + (f" ({tech['rsi14_5ago']:.0f} five sessions ago)" if tech.get("rsi14_5ago") is not None else "")
        if tech.get("macd_hist") is not None and tech.get("macd_hist_prev") is not None:
            mom += f"; MACD histogram {'rising' if tech['macd_hist'] > tech['macd_hist_prev'] else 'falling'} ({tech['macd_hist']:+.1f})"
        out.append(mom + ".")
    if fut:
        f = fut[0]
        if f.get("buildup"):
            s = (f"Near-month futures ({date.fromisoformat(f['expiry']).strftime('%-d %b')}): {BUILDUP[f['buildup']]}, price "
                 f"{f['change_pct']:+.2f}% with open interest {f['oi_change_pct']:+.1f}%")
            if f["buildup"] == "short_covering":
                s += " — shorts closing rather than new positions opening"
            out.append(s + ".")
    return out


def together(expiries: Sequence[Dict[str, Any]], close: float) -> List[str]:
    live = [e for e in expiries if e["liquidity"] != "too_thin"]
    if not live:
        return []
    out = []
    adds: Dict[float, Tuple[float, int]] = {}
    for e in live:
        for a in e.get("put_adds") or []:
            v, n = adds.get(a["strike"], (0.0, 0))
            adds[a["strike"]] = (v + a["change"], n + 1)
    if adds:
        k, (v, n) = max(adds.items(), key=lambda kv: (kv[1][1], kv[1][0]))
        out.append(f"Common floor: {k:,.0f} — put writers added there in {n} of {len(live)} series ({_lakh(v)} in all).")
    near = next((e for e in live if e["liquidity"] == "active"), live[0])
    if near.get("call_wall"):
        out.append(f"Near ceiling: {near['call_wall']:,.0f}, the heaviest call strike of the {near['kind']} "
                   f"{date.fromisoformat(near['expiry']).strftime('%-d %b')}.")
    far = [e for e in live if e["kind"] == "monthly"]
    if far and far[-1].get("max_pain"):
        f = far[-1]
        rel = "above" if f["max_pain"] > close else "below" if f["max_pain"] < close else "at"
        out.append(f"The {date.fromisoformat(f['expiry']).strftime('%-d %b')} monthly's max pain is {f['max_pain']:,.0f}, {rel} the close.")
    return out


# ── I/O ───────────────────────────────────────────────────────────────────────────────────────────────────────────────

Getter = Callable[..., Awaitable[Any]]


def _day(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


class IndicesService:
    def __init__(self, *, daas_get: Optional[Getter] = None, fno_module: Any = None, pulse: Optional[Getter] = None,
                 clock: Callable[[], float] = time.monotonic, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self._get, self._fno, self._pulse = daas_get, fno_module, pulse
        self._clock, self._now = clock, now
        self._cache: Optional[Tuple[str, float, Dict[str, Any]]] = None
        self._lock = asyncio.Lock()

    def _deps(self):
        if self._get is None or self._pulse is None:
            from services.copilot_tools import daas_client
            self._get = self._get or daas_client._get
            self._pulse = self._pulse or daas_client.get_market_pulse_fii_dii
        if self._fno is None:
            from routes import fno
            self._fno = fno
        return self._get, self._fno, self._pulse

    async def _series(self, name: str) -> List[Dict[str, Any]]:
        get, _, _ = self._deps()
        start = (self._now().date() - timedelta(days=HISTORY_DAYS)).isoformat()
        try:
            body = await get(f"/indices/{urllib.parse.quote(name)}/eod", {"start": start, "limit": 1000}, timeout=30.0)
        except Exception as e:  # noqa: BLE001
            raise DataUnavailable(f"{name} closes could not be read ({type(e).__name__}).") from e
        rows = [r for r in (body or {}).get("data") or [] if _day(r.get("as_of_date")) and fnum(r.get("close_price"))]
        rows.sort(key=lambda r: str(r["as_of_date"]))
        return rows

    async def get(self, request: Request) -> Dict[str, Any]:
        _, fno, _ = self._deps()
        n50 = await self._series("Nifty 50")
        if len(n50) < 60:
            raise DataUnavailable("Too few Nifty 50 closes to analyse.")
        as_of = str(n50[-1]["as_of_date"])[:10]
        async with self._lock:
            if self._cache and self._cache[0] == as_of and self._clock() - self._cache[1] < CACHE_S:
                return self._cache[2]
            out = await self._build(request, n50, as_of)
            self._cache = (as_of, self._clock(), out)
            return out

    async def _build(self, request: Request, n50: List[Dict[str, Any]], as_of: str) -> Dict[str, Any]:
        _, fno, pulse = self._deps()
        bank, vix = await asyncio.gather(self._series("Nifty Bank"), self._series(VIX))
        warnings: List[str] = []
        series = {"NIFTY": n50, "BANKNIFTY": bank}
        indices = []
        for sym, _name in INDICES:
            rows = series[sym]
            if len(rows) < 60:
                warnings.append(f"{DISPLAY[sym]}: too few closes to analyse.")
                continue
            indices.append(await self._one(request, fno, sym, rows, warnings))
        closes = {s: [fnum(r["close_price"]) for r in series[s]] for s in series}
        rel = {}
        for n, key in ((1, "1d"), (5, "5d"), (20, "20d")):
            a, b = closes["NIFTY"], closes["BANKNIFTY"]
            if len(a) > n and len(b) > n:
                rel[f"bank_minus_nifty_{key}"] = _r(100 * (b[-1] / b[-1 - n] - 1) - 100 * (a[-1] / a[-1 - n] - 1))
        vix_out = None
        vc = [fnum(r["close_price"]) for r in vix]
        if len(vc) > 5:
            vix_out = {"close": _r(vc[-1]), "change_pct": _r(100 * (vc[-1] / vc[-2] - 1)), "close_5ago": _r(vc[-6]),
                       "change_5d_pct": _r(100 * (vc[-1] / vc[-6] - 1)), "up_streak": up_streak(vc), "as_of": str(vix[-1]["as_of_date"])[:10]}
        flows = None
        try:
            body = await pulse(days=30)
            days = sorted(((str(d.get("date"))[:10], fnum(d.get("fii_net")), fnum(d.get("dii_net"))) for d in (body or {}).get("daily") or []
                           if d.get("date")), reverse=True)
            days = [d for d in days if d[1] is not None][:10]
            if days:
                last5 = days[:5]
                flows = {"as_of": days[0][0], "days": [{"date": d, "fii": _r(f), "dii": _r(i)} for d, f, i in days],
                         "fii_5d": _r(sum(f for _, f, _ in last5)), "fii_buy_days_5": sum(1 for _, f, _ in last5 if f > 0)}
        except Exception as e:  # noqa: BLE001
            warnings.append(f"FII / DII flows could not be read ({type(e).__name__}).")
        nifty = next((i for i in indices if i["symbol"] == "NIFTY"), None)
        return {"as_of": as_of, "indices": indices, "vix": vix_out, "relative": rel, "flows": flows,
                "together": [] if not nifty else together(nifty["expiries"], nifty["close"]),
                "notes": NOTES, "warnings": warnings,
                "sources": [{"what": "Index closes and highs / lows", "source": "NSE index closes, NIDP warehouse", "as_of": as_of},
                            {"what": "Option chains and futures", "source": "NSE F&O bhavcopy via /api/fno", "as_of": (indices[0]["expiries"][0]["as_of"] if indices and indices[0]["expiries"] else None)},
                            {"what": "FII / DII cash", "source": "NSE provisional figures, NIDP warehouse", "as_of": (flows or {}).get("as_of")}]}

    async def _one(self, request: Request, fno: Any, sym: str, rows: List[Dict[str, Any]], warnings: List[str]) -> Dict[str, Any]:
        c = [fnum(r["close_price"]) for r in rows]
        h = [fnum(r.get("high_price")) or c[i] for i, r in enumerate(rows)]
        l = [fnum(r.get("low_price")) or c[i] for i, r in enumerate(rows)]
        tech = technicals(c, h, l)
        piv = pivots(h[-1], l[-1], c[-1])
        out = {"symbol": sym, "name": DISPLAY[sym], "as_of": str(rows[-1]["as_of_date"])[:10], "close": _r(c[-1]),
               "change": _r(c[-1] - c[-2]), "change_pct": _r(100 * (c[-1] / c[-2] - 1)),
               "open": _r(fnum(rows[-1].get("open_price"))), "high": _r(h[-1]), "low": _r(l[-1]), "up_streak": up_streak(c),
               "ret_5d": _r(100 * (c[-1] / c[-6] - 1)), "ret_20d": _r(100 * (c[-1] / c[-21] - 1)),
               "technicals": tech, "pivots": piv}
        # futures
        fut = []
        try:
            fb = await fno.futures(request, symbol=sym)
            for f in fb.get("futures") or []:
                close, prev = fnum(f.get("close")) or fnum(f.get("settle")), fnum(f.get("prev_close"))
                oi, doi = fnum(f.get("oi")), fnum(f.get("change_in_oi"))
                chg = None if not close or not prev else 100 * (close / prev - 1)
                oi_pct = None if oi is None or doi is None or oi - doi <= 0 else 100 * doi / (oi - doi)
                fut.append({"expiry": f.get("expiry"), "close": _r(close), "change_pct": _r(chg), "oi": oi, "oi_change": doi,
                            "oi_change_pct": _r(oi_pct, 1), "basis": _r(fnum(f.get("basis"))), "buildup": buildup(chg, doi)})
        except HTTPException as e:
            warnings.append(f"{DISPLAY[sym]} futures could not be read (HTTP {e.status_code}).")
        out["futures"] = fut[:2]
        # expiries
        exps: List[Dict[str, Any]] = []
        setups: List[Dict[str, Any]] = []
        try:
            ex = await fno.expiries(request, symbol=sym)
            ex_as_of = _day(ex.get("as_of"))
            listed = [str(r.get("expiry"))[:10] for r in ex.get("expiries") or [] if r.get("expiry")]
            listed = [e for e in listed if ex_as_of and 0 < (date.fromisoformat(e) - ex_as_of).days <= MAX_DAYS]
            kinds = expiry_kinds(listed)
            chains = await asyncio.gather(*[fno.chain(request, symbol=sym, expiry=date.fromisoformat(e), around=fno.DEFAULT_AROUND)
                                            for e in listed], return_exceptions=True)
            good = [(e, ch) for e, ch in zip(listed, chains) if isinstance(ch, dict)]
            for e, ch in zip(listed, chains):
                if not isinstance(ch, dict):
                    warnings.append(f"{DISPLAY[sym]} {e}: the chain could not be read.")
            vol = {e: sum((fnum((r.get(s) or {}).get("volume")) or 0) for r in ch.get("strikes") or [] for s in ("call", "put")) for e, ch in good}
            ois = {e: (fnum((ch.get("summary") or {}).get("total_call_oi")) or 0) + (fnum((ch.get("summary") or {}).get("total_put_oi")) or 0)
                   for e, ch in good}
            mv, mo = max(vol.values() or [0]), max(ois.values() or [0])
            for e, ch in good:
                days = (date.fromisoformat(e) - ex_as_of).days
                ev = expiry_view(ch, e, days, kinds[e], liquidity(vol[e], ois[e], mv, mo), vol[e])
                ev["as_of"] = (ch.get("summary") or {}).get("as_of")
                exps.append(ev)
                setups.extend(build_setups(ev, ch, c[-1]))
        except HTTPException as e:
            warnings.append(f"{DISPLAY[sym]} option expiries could not be read (HTTP {e.status_code}).")
        out["expiries"] = exps
        out["setups"] = setups
        out["levels"] = levels(c[-1], tech, piv, exps)
        out["read"] = index_read(DISPLAY[sym], c[-1], out["change_pct"], out["up_streak"], tech, out["futures"])
        return out


_service: Optional[IndicesService] = None


def get_service() -> IndicesService:
    global _service
    if _service is None:
        _service = IndicesService()
    return _service
