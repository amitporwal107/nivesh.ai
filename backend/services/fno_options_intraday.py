"""Options intraday for the live chart's options pane (Trade Desk › Chart Analysis › Live chart).

    GET /api/fno/{symbol}/options/intraday?interval=15m&sessions=2&strikes=5   (routes/fno.py)

The Kite reading is IntradayService.options_intraday (services/kite_live_feed/intraday.py); everything below is pure
(nothing here reads a database or Kite) and is what the tests check (tests/test_live_chart_fno_series.py).

Which contracts
  expiry     the nearest unexpired expiry of the underlying's options in Kite's NFO instrument list (on the expiry day,
             that day's contracts all day, also after 15:30)
  ATM        the listed strike nearest the reference price; an exact tie goes to the lower strike (routes/fno.py's rule)
  strikes    the ATM strike and `strikes` listed strikes each side (fewer when fewer are listed; `note` says so)
  contracts  CE and PE at each of those strikes, read with Kite historical_data oi=1

The series (sums over every requested contract, one row per candle time in the sessions sent)
  ce_oi, pe_oi             summed open interest of the calls / the puts
  ce_volume, pe_volume     summed volume
  ce_oi_change, pe_oi_change   this row's sum − the previous row's; the first row is compared with the baseline row (the
                           last candle time before the sessions sent), else null
  pcr                      pe_oi / ce_oi (null when ce_oi is 0 or null)
A time at which ANY requested contract has no candle has every sum null: never a partial sum. A candle Kite sent without
an OI makes that side's OI sum null. OI shows positioning, not who initiated it.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

MAX_STRIKES = 8
SOURCE = "Kite intraday (historical, oi)"
SUM_KEYS = ("ce_oi", "pe_oi", "ce_volume", "pe_volume")
NOTE = ("Kite candles with open interest for the nearest expiry, ATM ± the strikes listed. A time at which any of these "
        "contracts has no candle has no sums (a gap, never a partial sum). OI shows positioning, not who initiated it.")
REASON_NOTE = {
    "token_missing": "The platform is not logged in to Kite today, so option candles cannot be read.",
    "token_expired": "The platform's Kite login has expired, so option candles cannot be read.",
    "no_options": "Kite lists no unexpired options for this underlying.",
    "no_bars": "Kite returned no option candles for these sessions.",
    "upstream_unavailable": "Kite did not answer the option candle read; try again shortly.",
}


def empty(symbol: str, interval: str, sessions: int, availability: str, now: datetime, note: Optional[str] = None,
          **known: Any) -> Dict[str, Any]:
    """The answer when Kite cannot give the pane its data; `known` fills what was found before it stopped."""
    out = {"symbol": symbol, "mode": "intraday", "interval": interval, "sessions": sessions, "expiry": None, "atm": None,
           "strikes": [], "ref": None, "series": [], "contracts": [], "missing": [], "availability": availability,
           "source": SOURCE, "as_of": now.isoformat(), "note": note or REASON_NOTE.get(availability, NOTE), "read_only": True}
    out.update({k: v for k, v in known.items() if k in out})
    return out


def pick_strikes(listed: Sequence[float], price: float, n: int) -> Tuple[Optional[float], List[float]]:
    """(the ATM strike, the ATM strike and up to `n` listed strikes each side, ascending). (None, []) without strikes."""
    strikes = sorted({float(s) for s in listed if s is not None and float(s) > 0})
    if not strikes:
        return None, []
    i = min(range(len(strikes)), key=lambda k: (abs(strikes[k] - price), strikes[k]))
    return strikes[i], strikes[max(0, i - n): i + n + 1]


def contracts_for(options: Sequence[Dict[str, Any]], chosen: Sequence[float]) -> List[Dict[str, Any]]:
    """The listed CE and PE contracts at the chosen strikes, by strike then CE before PE."""
    want = set(chosen)
    rows = [o for o in options if float(o["strike"]) in want and o.get("type") in ("CE", "PE")]
    return sorted(rows, key=lambda o: (float(o["strike"]), o["type"]))


def _int(v: Any) -> Optional[int]:
    return int(round(float(v))) if v is not None else None


def _sums(have: Sequence[Optional[Sequence[Any]]], types: Sequence[str]) -> Dict[str, Optional[float]]:
    """The four sums at one time. All null when any contract has no candle at that time."""
    if not have or any(b is None for b in have):
        return {k: None for k in SUM_KEYS}
    out: Dict[str, Optional[float]] = {}
    for side in ("CE", "PE"):
        bars = [b for b, ty in zip(have, types) if ty == side]
        ois = [b[6] for b in bars]                                            # type: ignore[index]
        out[f"{side.lower()}_oi"] = sum(float(x) for x in ois) if bars and all(x is not None for x in ois) else None
        out[f"{side.lower()}_volume"] = sum(float(b[5] or 0) for b in bars) if bars else None  # type: ignore[index]
    return out


def _chg(now: Optional[float], prev: Optional[float]) -> Optional[int]:
    return _int(now - prev) if now is not None and prev is not None else None


def build_series(contracts: Sequence[Dict[str, Any]], sessions: int) -> Tuple[List[Dict[str, Any]], List[str]]:
    """(series rows, the days sent) from the contracts' bars ([t, o, h, l, c, v, oi], oldest first). See the docstring."""
    all_days = sorted({b[0][:10] for c in contracts for b in c.get("bars") or []})
    days = all_days[-sessions:]
    if not days:
        return [], []
    by_t = [{b[0]: b for b in c.get("bars") or []} for c in contracts]
    types = [c["type"] for c in contracts]
    times = sorted({t for m in by_t for t in m})
    shown = [t for t in times if t[:10] >= days[0]]
    before = [t for t in times if t[:10] < days[0]]
    prev = _sums([m.get(before[-1]) for m in by_t], types) if before else {k: None for k in SUM_KEYS}
    out: List[Dict[str, Any]] = []
    for t in shown:
        s = _sums([m.get(t) for m in by_t], types)
        ce_oi, pe_oi = s["ce_oi"], s["pe_oi"]
        out.append({"t": t, "ce_oi": _int(ce_oi), "pe_oi": _int(pe_oi),
                    "ce_oi_change": _chg(ce_oi, prev["ce_oi"]), "pe_oi_change": _chg(pe_oi, prev["pe_oi"]),
                    "ce_volume": _int(s["ce_volume"]), "pe_volume": _int(s["pe_volume"]),
                    "pcr": round(pe_oi / ce_oi, 4) if ce_oi and pe_oi is not None else None})
        prev = s
    return out, days


def answer(symbol: str, interval: str, sessions: int, expiry: str, atm: float, chosen: Sequence[float], n: int,
           ref: Dict[str, Any], contracts: Sequence[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    """The route's body. `contracts` [{tradingsymbol, strike, type, bars: [[t, o, h, l, c, v, oi]]}] as Kite sent them
    (sorted, invalid candles already dropped), over the sessions sent plus the baseline session."""
    series, days = build_series(contracts, sessions)
    keep = set(days)
    out_contracts = [{"tradingsymbol": c.get("tradingsymbol"), "strike": float(c["strike"]), "type": c["type"],
                      "bars": [[b[0], b[1], b[2], b[3], b[4], _int(b[5] or 0), _int(b[6])] for b in c.get("bars") or [] if b[0][:10] in keep]}
                     for c in contracts]
    missing = [c["tradingsymbol"] for c in out_contracts if not c["bars"]]
    notes = [NOTE]
    below = sum(1 for s in chosen if s < atm)
    above = sum(1 for s in chosen if s > atm)
    if below < n or above < n:
        notes.append(f"Kite lists {below} strike(s) below and {above} above the ATM strike {atm:g} for this expiry "
                     f"(asked for {n} each side).")
    if missing and len(missing) < len(out_contracts):
        notes.append(f"{len(missing)} of {len(out_contracts)} contracts have no candle in these sessions, so every row's sums "
                     "are null.")
    gaps = sum(1 for r in series if r["ce_oi"] is None and r["ce_volume"] is None)
    if series and 0 < gaps and not missing:
        notes.append(f"{gaps} of {len(series)} times have no sums: at least one contract did not trade then.")
    ok = any(c["bars"] for c in out_contracts)
    return {
        "symbol": symbol, "mode": "intraday", "interval": interval, "sessions": sessions, "expiry": expiry,
        "atm": float(atm), "strikes": [float(s) for s in chosen], "ref": ref,
        "series": series, "contracts": out_contracts, "missing": missing,
        "availability": "ok" if ok else "no_bars", "source": SOURCE, "as_of": now.isoformat(),
        "note": " ".join(notes) if ok else REASON_NOTE["no_bars"], "read_only": True,
    }
