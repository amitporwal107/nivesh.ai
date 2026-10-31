"""TrueData real-time WebSocket messages → plain dicts (LP-1 … LP-6 in test_reports/truedata_live_dq_TESTCASES.md).

Formats from TrueData's Market Data API documentation v2.6 (JSON stream), checked against the sandbox login on 29 Oct 2026:
  login        {"success", "message", "segments", "maxsymbols", "subscription", "validity"}
  heartbeat    {"success": true, "message": "HeartBeat", "timestamp": "YYYY-MM-DDTHH:MM:SS.FFF"}   every 5–6 s
  market       {"success": true, "message": "marketstatus", "data": "NSE EQ Normal Market Start"}
  touchline    {"message": "touchline" | "symbols added", "symbollist": [[Symbol, SymbolID, LastUpdateTime, LTP,
                TickVolume, ATP, TotalVolume, Open, High, Low, PrevClose, OI, PrevOI, Turnover, Bid, BidQty, Ask, AskQty]]}
  trade        {"trade": [SymbolID, Time, LTP, LTQ, ATP, TTQ, Open, High, Low, PrevClose, OI, PrevOI, Turnover, Tag,
                Sequence, Bid, BidQty, Ask, AskQty]}
  bidask       {"bidask": [SymbolID, Time, Bid, BidQty, Ask, AskQty]}
All values arrive as strings. Times are exchange times in IST without an offset; the bidask example uses
"M/D/YYYY h:mm:ss AM". Nothing here touches the network or a credential.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

IST = timezone(timedelta(hours=5, minutes=30))

TOUCHLINE_FIELDS = ("symbol", "symbol_id", "ts", "ltp", "tick_volume", "atp", "volume", "open", "high", "low",
                    "prev_close", "oi", "prev_oi", "turnover", "bid", "bid_qty", "ask", "ask_qty")
TRADE_FIELDS = ("symbol_id", "ts", "ltp", "ltq", "atp", "volume", "open", "high", "low", "prev_close", "oi", "prev_oi",
                "turnover", "tag", "seq", "bid", "bid_qty", "ask", "ask_qty")
BIDASK_FIELDS = ("symbol_id", "ts", "bid", "bid_qty", "ask", "ask_qty")
_TEXT = {"symbol", "symbol_id", "ts", "tag"}
_TS_FORMATS = ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y %I:%M:%S %p", "%Y-%m-%d %H:%M:%S")


class Malformed(ValueError):
    """A message that does not have the documented shape."""


def num(v: Any) -> Optional[float]:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_ts(v: Any) -> Optional[datetime]:
    """TrueData's exchange time (IST, no offset) → aware IST datetime; None when absent or unreadable."""
    s = str(v or "").strip()
    if not s or s.startswith("0001-01-01"):
        return None
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    return None


def kind_of(msg: Dict[str, Any]) -> str:
    if not isinstance(msg, dict):
        return "unknown"
    for k in ("trade", "bidask", "greeks", "bar1min", "bidaskL2"):
        if k in msg:
            return k
    m = str(msg.get("message") or "").strip().lower()
    if m == "heartbeat":
        return "heartbeat"
    if m == "marketstatus":
        return "marketstatus"
    if "symbollist" in msg and m in ("symbols added", "touchline"):
        return "touchline"
    if "maxsymbols" in msg:
        return "login"
    if m == "symbols removed":
        return "removed"
    if msg.get("success") is False or str(msg.get("success")).lower() == "false":
        return "error"
    return "unknown"


@dataclass
class LoginInfo:
    ok: bool
    message: str
    segments: List[str] = field(default_factory=list)
    maxsymbols: int = 0
    subscription: Optional[str] = None
    validity: Optional[date] = None

    @property
    def duplicate(self) -> bool:
        return "already connected" in self.message.lower()

    def public(self) -> Dict[str, Any]:
        return {"ok": self.ok, "message": self.message, "segments": self.segments, "maxsymbols": self.maxsymbols,
                "subscription": self.subscription, "validity": self.validity.isoformat() if self.validity else None}


def parse_login(msg: Dict[str, Any]) -> LoginInfo:
    ok = msg.get("success") is True or str(msg.get("success")).lower() == "true"
    validity = None
    raw = str(msg.get("validity") or "")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%d/%m/%YT%H:%M:%S", "%Y-%m-%d"):
        try:
            d = datetime.strptime(raw[:19] if fmt != "%d/%m/%YT%H:%M:%S" else raw, fmt).date()
            validity = None if d.year <= 1 else d
            break
        except ValueError:
            continue
    try:
        maxsymbols = int(msg.get("maxsymbols") or 0)
    except (TypeError, ValueError):
        maxsymbols = 0
    return LoginInfo(ok=ok, message=str(msg.get("message") or "")[:200],
                     segments=[str(s).upper() for s in (msg.get("segments") or [])], maxsymbols=maxsymbols,
                     subscription=msg.get("subscription"), validity=validity)


def _row(fields, arr) -> Dict[str, Any]:
    if not isinstance(arr, list) or len(arr) < len(fields) - 4:      # the trade array may omit bid/ask (bid/ask off)
        raise Malformed(f"expected {len(fields)} fields, got {len(arr) if isinstance(arr, list) else type(arr).__name__}")
    out: Dict[str, Any] = {}
    for k, v in zip(fields, arr):
        out[k] = (str(v).strip() if v is not None else None) if k in _TEXT else num(v)
    out["ts"] = parse_ts(out.get("ts"))
    if "seq" in out and out["seq"] is not None:
        out["seq"] = int(out["seq"])
    return out


def parse_touchline(msg: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for arr in msg.get("symbollist") or []:
        r = _row(TOUCHLINE_FIELDS, arr)
        if not r.get("symbol") or not r.get("symbol_id"):
            raise Malformed("touchline row without symbol or id")
        rows.append(r)
    return rows


def parse_trade(msg: Dict[str, Any]) -> Dict[str, Any]:
    return _row(TRADE_FIELDS, msg.get("trade"))


def parse_bidask(msg: Dict[str, Any]) -> Dict[str, Any]:
    arr = msg.get("bidask")
    if not isinstance(arr, list) or len(arr) < len(BIDASK_FIELDS):
        raise Malformed("bidask array too short")
    return _row(BIDASK_FIELDS, arr)


def quote_from(row: Dict[str, Any], received_at: datetime) -> Dict[str, Any]:
    """A touchline or trade row as the shadow quote (absent values None, never 0 for a price)."""
    def price(k):
        v = row.get(k)
        return v if v and v > 0 else None
    return {"symbol": row.get("symbol"), "symbol_id": row.get("symbol_id"), "ltp": row.get("ltp"),
            "open": price("open"), "high": price("high"), "low": price("low"), "prev_close": price("prev_close"),
            "volume": row.get("volume"), "oi": row.get("oi"), "prev_oi": row.get("prev_oi"),
            "bid": row.get("bid"), "bid_qty": row.get("bid_qty"), "ask": row.get("ask"), "ask_qty": row.get("ask_qty"),
            "seq": row.get("seq"), "ts": row.get("ts"), "received_at": received_at}
