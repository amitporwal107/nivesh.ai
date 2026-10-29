"""Data-quality checks on TrueData's live stream: connection (group 1) and every tick (group 2).
LC-* and LT-* in test_reports/truedata_live_dq_TESTCASES.md. Pure functions and a small per-symbol state; no I/O.

A check never repairs a value. A tick that fails a "not usable" check (non-positive price) is not used; every other
finding is counted per minute with a few samples, so the comparison with Kite and the nightly NSE cross-check can say
whether TrueData is fit to serve.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

REQUIRED_SEGMENTS = ("EQ", "FO", "IND")
EXPIRY_WARN_DAYS = 7
HEARTBEAT_DELAYED_S = 15
HEARTBEAT_LOST_S = 60
STALE_S = {"INDEX": 5, "EQ": 30, "FUT": 30, "OPT": 60}
JUMP = {"INDEX": 0.10, "EQ": 0.20, "FUT": 0.20}          # options move too much for a fixed jump rule
TS_FUTURE_S = 5
EPS = 1e-6
INT32_MAX = 2_147_483_647

# Codes, their severity, and whether the tick may still be used.
SEVERITY = {
    "LOGIN_FAILED": "CRITICAL", "DUPLICATE_LOGIN": "CRITICAL", "SEGMENT_MISSING": "ERROR", "SYMBOL_LIMIT": "WARN",
    "LOGIN_EXPIRING": "WARN", "SYMBOL_NOT_SUBSCRIBED": "ERROR", "HEARTBEAT_LATE": "WARN", "HEARTBEAT_LOST": "ERROR",
    "PRICE_NONPOSITIVE": "ERROR", "OFF_TICK": "ERROR", "CIRCUIT_BREACH": "ERROR", "CROSSED_BOOK": "WARN",
    "OHLC_INCONSISTENT": "ERROR", "HIGH_DECREASED": "ERROR", "LOW_INCREASED": "ERROR", "VOLUME_DECREASED": "ERROR",
    "OI_NEGATIVE": "ERROR", "OI_SUSPECT_ZERO": "WARN", "TS_FUTURE": "ERROR", "TS_BACKWARDS": "WARN",
    "SEQ_GAP": "INFO", "JUMP_UNCONFIRMED": "WARN", "STALE_SYMBOL": "WARN", "UNMAPPED_ID": "WARN", "MALFORMED": "ERROR",
    "PREV_CLOSE_MISMATCH": "ERROR", "KITE_DISAGREE": "WARN", "OI_MISMATCH": "WARN",
}
UNUSABLE = {"PRICE_NONPOSITIVE", "TS_FUTURE"}


def kind_of_symbol(symbol: str, indices: Iterable[str] = ()) -> str:
    s = symbol.upper()
    if s in {i.upper() for i in indices}:
        return "INDEX"
    if s.endswith("FUT") or s.endswith(("-I", "-II", "-III")):
        return "FUT"
    if s.endswith(("CE", "PE")) and any(c.isdigit() for c in s):
        return "OPT"
    return "EQ"


# ── Group 1: connection ─────────────────────────────────────────────────────────────────────────────────────────

def login_findings(info, wanted: int, today: date) -> List[Tuple[str, str]]:
    """LC-1 … LC-4 from the login reply (protocol.LoginInfo)."""
    if not info.ok:
        return [("DUPLICATE_LOGIN" if info.duplicate else "LOGIN_FAILED", info.message)]
    out: List[Tuple[str, str]] = []
    missing = [s for s in REQUIRED_SEGMENTS if s not in info.segments]
    if missing:
        out.append(("SEGMENT_MISSING", f"segments {missing} not in the login reply {info.segments}"))
    if wanted > info.maxsymbols:
        out.append(("SYMBOL_LIMIT", f"{wanted} symbols wanted, the login allows {info.maxsymbols}"))
    if info.validity and (info.validity - today).days <= EXPIRY_WARN_DAYS:
        out.append(("LOGIN_EXPIRING", f"the TrueData login is valid until {info.validity.isoformat()}"))
    return out


def subscription_findings(requested: Iterable[str], subscribed: Iterable[str]) -> List[Tuple[str, str]]:
    """LC-5: a requested symbol TrueData did not subscribe (unknown name, or not entitled)."""
    got = {s.upper() for s in subscribed}
    return [("SYMBOL_NOT_SUBSCRIBED", s) for s in requested if s.upper() not in got]


def heartbeat_state(last_heartbeat: Optional[datetime], now: datetime) -> Tuple[str, Optional[float]]:
    """LC-6: (ok | delayed | lost, age in seconds)."""
    if last_heartbeat is None:
        return "lost", None
    age = (now - last_heartbeat).total_seconds()
    if age > HEARTBEAT_LOST_S:
        return "lost", age
    if age > HEARTBEAT_DELAYED_S:
        return "delayed", age
    return "ok", age


# ── Group 2: every tick ─────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class SymbolMeta:
    kind: str = "EQ"
    tick_size: Optional[float] = None
    circuit_low: Optional[float] = None
    circuit_high: Optional[float] = None


@dataclass
class _State:
    day: Optional[date] = None
    ltp: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    volume: Optional[float] = None
    ts: Optional[datetime] = None
    seq: Optional[int] = None
    updated_at: Optional[datetime] = None


def _off_grid(price: float, tick: float) -> bool:
    steps = price / tick
    return abs(steps - round(steps)) * tick > max(EPS, tick * 1e-4)


@dataclass
class TickChecker:
    meta: Dict[str, SymbolMeta] = field(default_factory=dict)
    state: Dict[str, _State] = field(default_factory=dict)

    def check(self, symbol: str, q: Dict[str, Any], now: datetime) -> List[str]:
        """LT-1 … LT-11 for one tick (protocol.quote_from shape). Returns the finding codes; updates the state."""
        m = self.meta.get(symbol) or SymbolMeta()
        st = self.state.setdefault(symbol, _State())
        ts: Optional[datetime] = q.get("ts")
        day = (ts or now).date()
        if st.day != day:                                               # a new session: day high/low/volume restart
            self.state[symbol] = st = _State(day=day)
        codes: List[str] = []
        ltp = q.get("ltp")
        if ltp is None or ltp <= 0:
            return ["PRICE_NONPOSITIVE"]
        if ts is not None and ts > now + timedelta(seconds=TS_FUTURE_S):
            return ["TS_FUTURE"]
        if m.kind != "INDEX" and m.tick_size and _off_grid(ltp, m.tick_size):
            codes.append("OFF_TICK")
        if m.circuit_low and m.circuit_high and not (m.circuit_low - EPS <= ltp <= m.circuit_high + EPS):
            codes.append("CIRCUIT_BREACH")
        bid, ask = q.get("bid") or 0, q.get("ask") or 0
        if bid > 0 and ask > 0 and bid > ask + EPS:
            codes.append("CROSSED_BOOK")
        o, h, low = q.get("open"), q.get("high"), q.get("low")
        if o and h and low and (h < max(o, ltp) - EPS or low > min(o, ltp) + EPS):
            codes.append("OHLC_INCONSISTENT")
        if h and st.high and h < st.high - EPS:
            codes.append("HIGH_DECREASED")
        if low and st.low and low > st.low + EPS:
            codes.append("LOW_INCREASED")
        vol = q.get("volume")
        if vol is not None and st.volume is not None and vol < st.volume:
            codes.append("VOLUME_DECREASED")
        oi = q.get("oi")
        if oi is not None and oi < 0:
            codes.append("OI_NEGATIVE")
        elif m.kind in ("FUT", "OPT") and not oi and (q.get("prev_oi") or 0) > 0:
            codes.append("OI_SUSPECT_ZERO")
        if ts is not None and st.ts is not None and ts < st.ts:
            codes.append("TS_BACKWARDS")
        seq = q.get("seq")
        if seq is not None and st.seq is not None and seq > st.seq + 1:
            codes.append("SEQ_GAP")
        limit = JUMP.get(m.kind)
        if limit and st.ltp and not (m.circuit_low and m.circuit_high) and abs(ltp / st.ltp - 1) > limit:
            codes.append("JUMP_UNCONFIRMED")
        st.ltp = ltp
        st.high = max(st.high or 0, h or 0) or None
        st.low = min(x for x in (st.low, low) if x) if (st.low or low) else None
        st.volume = vol if vol is not None else st.volume
        st.ts = max(ts, st.ts) if (ts and st.ts) else (ts or st.ts)
        st.seq = seq if seq is not None else st.seq
        st.updated_at = now
        return codes

    def stale_symbols(self, now: datetime, subscribed: Iterable[str]) -> List[str]:
        """LT-12: subscribed symbols without an update for longer than their kind allows (call in market hours only)."""
        out = []
        for s in subscribed:
            st = self.state.get(s)
            limit = STALE_S.get((self.meta.get(s) or SymbolMeta()).kind, 30)
            last = st.updated_at if st else None
            if last is None or (now - last).total_seconds() > limit:
                out.append(s)
        return out
