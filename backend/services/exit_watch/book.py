"""Exit watch: broker position rows → watched positions (docs/paper_pnl_dashboard/EXIT_WATCH.md "Scope"). Pure; no network.

Rows are broker NET position rows (HubPosition dicts) carrying the positions workspace's private keys: _account_id,
_broker, _broker_display, _read_at. They come from paper_pnl.live.BrokerBook.rows (the GET) or from a stored
position_snapshots document, with those keys added by the runner. Each row is named as an NSE contract by
services/positions/symbols.normalise. ICICI Direct's codes differ from NSE's: TATSTE = TATASTEEL, DLFLIM = DLF.

One watched position per account and underlying:

    delta-one legs    the shares (EQ) and futures (FUT). All on one side: long (quantity > 0) or short (< 0).
    kind              "shares" (EQ only) · "future" (a future among them) · "hedged" (see below)
    hedge             a long put for a long position, a long call for a short one. For futures, of the same expiry as a
                      future held; a Zerodha monthly symbol names its month only, so the month is matched. For
                      shares, any expiry. Hedged when the options' quantity is at least the delta-one quantity. Less
                      than that: not hedged, with the note "partly hedged (x of y)".
    not watched       options only · delta-one legs on both sides · a row with no NSE symbol (for example an ICICI SGB
                      code), each with its reason

Key = "<account_id>|<UNDERLYING>|<side>".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


@dataclass
class WatchLeg:
    instrument: str
    type: str                       # EQ | FUT | CE | PE
    quantity: float                 # signed
    avg: Optional[float]
    expiry: Optional[str]           # ISO day, or "YYYY-MM" for a Zerodha monthly contract
    strike: Optional[float]
    price: Optional[float]          # the broker's last price on its read (used for a future's basis)

    def public(self) -> Dict[str, Any]:
        return {"instrument": self.instrument, "type": self.type, "quantity": self.quantity, "avg": self.avg,
                "expiry": self.expiry, "strike": self.strike}


@dataclass
class Watched:
    key: str
    account_id: str
    account: str
    broker: str
    underlying: str
    kind: str                       # shares | future | hedged
    side: str                       # long | short
    legs: List[WatchLeg] = field(default_factory=list)
    hedge: Optional[Dict[str, Any]] = None      # {type, strike, quantity, avg, expiry} when hedged
    note: Optional[str] = None
    read_at: Optional[str] = None

    @property
    def delta_one(self) -> List[WatchLeg]:
        return [l for l in self.legs if l.type in ("EQ", "FUT")]

    @property
    def label(self) -> str:
        if self.kind == "hedged" and self.hedge:
            k = self.hedge["strike"]
            what = "future" if any(l.type == "FUT" for l in self.delta_one) else "shares"
            return f"{self.underlying} {what} + {k:g} {self.hedge['type']}"
        return f"{self.underlying} {'future' if self.kind == 'future' else 'shares'}"

    @property
    def method(self) -> str:
        if self.kind != "hedged":
            return "atr_trail"
        return "put_floor" if self.side == "long" else "call_cap"


def _leg(c: Any, r: Dict[str, Any]) -> WatchLeg:
    from services.positions import symbols
    try:
        name = symbols.label(c)
    except Exception:  # noqa: BLE001 — a label is cosmetic; the broker's code names the leg instead
        name = str(r.get("symbol") or c.underlying)
    return WatchLeg(instrument=name, type=c.instrument, quantity=_num(r.get("quantity")) or 0.0, avg=_num(r.get("avg_price")),
                    expiry=c.expiry or c.expiry_month, strike=c.strike, price=_num(r.get("last_price")))


def group(rows: List[Dict[str, Any]]) -> Tuple[List[Watched], List[Dict[str, Any]]]:
    """(watched positions, not watched [{label, why, account_id, account}]) from open broker rows."""
    from services.positions import symbols
    by: Dict[Tuple[str, str], List[Tuple[Any, Dict[str, Any]]]] = {}
    meta: Dict[str, Tuple[str, str, Optional[str]]] = {}
    skipped: List[Dict[str, Any]] = []
    for r in rows:
        qty = _num(r.get("quantity"))
        if not qty:
            continue
        acct = str(r.get("_account_id") or "")
        display = r.get("_broker_display") or r.get("_broker") or "Broker"
        meta[acct] = (display, str(r.get("_broker") or ""), r.get("_read_at"))
        try:
            c = symbols.normalise(r, str(r.get("_broker") or ""))
        except Exception as e:  # noqa: BLE001 — listed as not watched with the reason, never guessed
            logger.warning("exit_watch: broker row not named (%s)", type(e).__name__)
            skipped.append({"label": f"{r.get('symbol') or '?'} ({display})", "why": "the row could not be read as an instrument",
                            "account_id": acct, "account": display})
            continue
        if not c.mapped:
            skipped.append({"label": f"{r.get('symbol') or c.underlying} ({display})",
                            "why": c.problem or "no NSE symbol for this broker code", "account_id": acct, "account": display})
            continue
        by.setdefault((acct, c.underlying), []).append((c, r))
    out: List[Watched] = []
    for (acct, und), items in sorted(by.items()):
        display, broker, read_at = meta.get(acct, ("Broker", "", None))
        legs = [_leg(c, r) for c, r in items]
        d1 = [l for l in legs if l.type in ("EQ", "FUT")]
        if not d1:
            skipped.append({"label": f"{und} options ({display})",
                            "why": "options only: there are no shares or futures to set a stop loss on", "account_id": acct,
                            "account": display})
            continue
        if any(l.quantity > 0 for l in d1) and any(l.quantity < 0 for l in d1):
            skipped.append({"label": f"{und} ({display})", "why": "shares or futures on both sides (long and short)",
                            "account_id": acct, "account": display})
            continue
        side = "long" if d1[0].quantity > 0 else "short"
        kind = "future" if any(l.type == "FUT" for l in d1) else "shares"
        need = sum(abs(l.quantity) for l in d1)
        opt_type = "PE" if side == "long" else "CE"
        fut_exp = {_month(l.expiry) for l in d1 if l.type == "FUT"}
        cover = [l for l in legs if l.type == opt_type and l.quantity > 0 and l.strike
                 and (kind == "shares" or _month(l.expiry) in fut_exp)]
        have = sum(l.quantity for l in cover)
        w = Watched(key=f"{acct}|{und}|{side}", account_id=acct, account=display, broker=broker, underlying=und, kind=kind,
                    side=side, legs=legs, read_at=read_at)
        if cover and have >= need:
            # The binding strike: walking from the best-protecting strike (highest put / lowest call), the strike at which
            # the options held reach the delta-one quantity. Below it (above it for calls) the loss stops growing.
            ordered = sorted(cover, key=lambda l: -l.strike if side == "long" else l.strike)
            got, k = 0.0, ordered[0].strike
            for l in ordered:
                got += l.quantity
                k = l.strike
                if got >= need:
                    break
            w.kind = "hedged"
            w.hedge = {"type": opt_type, "strike": k, "quantity": have, "avg": _weighted([(l.avg, l.quantity) for l in cover]),
                       "expiry": next(l.expiry for l in ordered if l.strike == k),
                       "legs": [{"strike": l.strike, "quantity": l.quantity, "avg": l.avg} for l in cover]}
        elif cover:
            w.note = f"partly hedged ({have:g} of {need:g})"
        out.append(w)
    return out, skipped


def _month(expiry: Optional[str]) -> Optional[str]:
    return str(expiry)[:7] if expiry else None


def _weighted(pairs: List[Tuple[Optional[float], float]]) -> Optional[float]:
    if any(a is None for a, _ in pairs):
        return None
    qty = sum(q for _, q in pairs)
    return round(sum(a * q for a, q in pairs) / qty, 4) if qty else None
