"""Track 1, days 4-5: append-only signal ledger (TRACK1_SCOPE_v1/v2 lifecycle).

One JSON line per event in /app/research/reports/<session>/ledger.jsonl. Each event carries the SHA-256 of the previous
event, so any edit to history breaks the chain (`verify`). Transitions are validated against the lifecycle:

  WATCHLIST -> TRIGGER_APPROACHING -> ENTRY_CONFIRMED -> CLOSED
  WATCHLIST / TRIGGER_APPROACHING -> EXPIRED | INVALIDATED
Manual fills are separate events (MANUAL_ENTRY / MANUAL_EXIT) and never alter the theoretical record.
"""
from __future__ import annotations
import datetime as dt, hashlib, json, os

STATES = {"WATCHLIST", "TRIGGER_APPROACHING", "ENTRY_CONFIRMED", "CLOSED", "EXPIRED", "INVALIDATED"}
ALLOWED = {None: {"WATCHLIST"},
           "WATCHLIST": {"TRIGGER_APPROACHING", "ENTRY_CONFIRMED", "EXPIRED", "INVALIDATED"},   # H-A confirms at the open
           "TRIGGER_APPROACHING": {"ENTRY_CONFIRMED", "EXPIRED", "INVALIDATED"},
           "ENTRY_CONFIRMED": {"CLOSED"}, "CLOSED": set(), "EXPIRED": set(), "INVALIDATED": set()}
MANUAL = {"MANUAL_ENTRY", "MANUAL_EXIT"}
GENESIS = "0" * 64
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

class LedgerError(Exception):
    pass

def _hash(ev: dict) -> str:
    body = {k: v for k, v in ev.items() if k != "event_hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()

class Ledger:
    def __init__(self, path: str):
        self.path = path
        self.events = [json.loads(l) for l in open(path)] if os.path.exists(path) else []
        self.state: dict[tuple[str, str], str] = {}
        for e in self.events:
            if e["kind"] == "STATE":
                self.state[(e["symbol"], e["arm"])] = e["to_state"]

    def _append(self, ev: dict) -> dict:
        ev["prev_hash"] = self.events[-1]["event_hash"] if self.events else GENESIS
        ev["seq"] = len(self.events)
        ev["event_hash"] = _hash(ev)
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "a") as f:
            f.write(json.dumps(ev, sort_keys=True, default=str) + "\n")
        self.events.append(ev)
        return ev

    def transition(self, symbol: str, arm: str, to_state: str, reason: str, data: dict | None = None, at: str | None = None) -> dict:
        if to_state not in STATES:
            raise LedgerError(f"unknown state {to_state}")
        cur = self.state.get((symbol, arm))
        if to_state not in ALLOWED[cur]:
            raise LedgerError(f"illegal transition {symbol}/{arm}: {cur} -> {to_state}")
        ev = self._append({"kind": "STATE", "symbol": symbol, "arm": arm, "from_state": cur, "to_state": to_state,
                           "reason": reason, "data": data or {}, "at": at or dt.datetime.now(IST).isoformat(timespec="seconds")})
        self.state[(symbol, arm)] = to_state
        return ev

    def manual(self, kind: str, symbol: str, arm: str, price: float, qty: int, at: str) -> dict:
        if kind not in MANUAL:
            raise LedgerError(f"unknown manual event {kind}")
        if kind == "MANUAL_ENTRY" and self.state.get((symbol, arm)) not in {"ENTRY_CONFIRMED", "CLOSED"}:
            raise LedgerError(f"manual entry for {symbol}/{arm} without a confirmed signal (state {self.state.get((symbol, arm))})")
        return self._append({"kind": kind, "symbol": symbol, "arm": arm, "price": float(price), "qty": int(qty), "at": at})

def verify(path: str) -> tuple[bool, str]:
    """Recompute the hash chain. Any edited, removed or reordered line fails."""
    prev = GENESIS
    for i, line in enumerate(open(path)):
        e = json.loads(line)
        if e.get("seq") != i or e.get("prev_hash") != prev or _hash(e) != e.get("event_hash"):
            return False, f"chain broken at line {i}"
        prev = e["event_hash"]
    return True, "ok"
