"""Broker position rows → NSE contracts. Pure functions plus one CSV read; no network.

Brokers name a position their own way:
  * ICICI Direct sends its own stock code (SONBLW for NSE SONACOMS, CNXBAN for BANKNIFTY) with the contract's type,
    expiry and strike in separate fields. The code is mapped through ICICI's own security master
    (backend/data/broker_symbols/icicidirect.csv, built by scripts/build_icici_symbol_map.py).
  * Zerodha (Kite, read through Fenix) sends the exchange trading symbol only: NIFTY25NOVFUT, NIFTY25NOV23000CE
    (a monthly contract: the expiry DAY is not in the symbol) or NIFTY25N0423000CE (a weekly one: YY, a month
    character 1-9/O/N/D, DD).
  * Every other broker: the symbol as given, with the row's own contract fields when it has them.

A row that cannot be named as one NSE contract is kept, flagged `mapped: False` with the reason, and left out of
every figure worked out from contracts. Nothing is guessed.

Canonical key of a contract: "<UNDERLYING>|<EXPIRY>|<STRIKE>|<CE|PE>" for an option, "<UNDERLYING>|<EXPIRY>|FUT" for
a future, "<SYMBOL>|EQ" for shares. A monthly Zerodha contract whose expiry day is not known yet carries
expiry_month ("2026-11") and gets its day from the underlying's listed futures expiry in that month
(`resolve_monthly`).
"""
from __future__ import annotations

import csv
import functools
import re
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

MAP_DIR = Path(__file__).resolve().parents[2] / "data" / "broker_symbols"
ICICI_SLUGS = ("icicidirect", "icici")
ZERODHA_SLUGS = ("zerodha", "kite")

_MONTHS = {m: i + 1 for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"))}
_WEEK_MONTH = {**{str(i): i for i in range(1, 10)}, "O": 10, "N": 11, "D": 12}

# Zerodha: futures and monthly options (no day), then weekly options (YY, month character, DD).
_Z_MONTHLY = re.compile(r"^(?P<u>[A-Z0-9&\-]+?)(?P<yy>\d{2})(?P<mon>JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
                        r"(?:(?P<fut>FUT)|(?P<strike>\d+(?:\.\d+)?)(?P<opt>CE|PE))$")
_Z_WEEKLY = re.compile(r"^(?P<u>[A-Z0-9&\-]+?)(?P<yy>\d{2})(?P<m>[1-9OND])(?P<dd>\d{2})(?P<strike>\d+(?:\.\d+)?)(?P<opt>CE|PE)$")


@dataclass(frozen=True)
class Contract:
    """One position row named as an NSE instrument."""
    underlying: str                         # NSE symbol of the share or the F&O underlying
    instrument: str                         # "EQ" | "FUT" | "CE" | "PE"
    expiry: Optional[str] = None            # ISO day; None for shares, and for a monthly contract not yet resolved
    expiry_month: Optional[str] = None      # "YYYY-MM" for a monthly contract whose day is to be resolved
    strike: Optional[float] = None
    mapped: bool = True
    problem: Optional[str] = None
    broker_code: Optional[str] = field(default=None, compare=False)

    @property
    def is_derivative(self) -> bool:
        return self.instrument in ("FUT", "CE", "PE")

    @property
    def key(self) -> Optional[str]:
        if not self.mapped:
            return None
        if self.instrument == "EQ":
            return f"{self.underlying}|EQ"
        if not self.expiry:
            return None
        if self.instrument == "FUT":
            return f"{self.underlying}|{self.expiry}|FUT"
        return f"{self.underlying}|{self.expiry}|{_strike_text(self.strike)}|{self.instrument}"


def _strike_text(strike: Optional[float]) -> str:
    if strike is None:
        return "?"
    return str(int(strike)) if float(strike).is_integer() else f"{strike:g}"


@functools.lru_cache(maxsize=4)
def _load_map(name: str) -> Dict[str, str]:
    path = MAP_DIR / name
    out: Dict[str, str] = {}
    if not path.exists():
        return out
    with path.open(newline="") as f:
        lines = (line for line in f if not line.startswith("#"))
        for row in csv.DictReader(lines):
            code, nse = (row.get("broker_code") or "").strip().upper(), (row.get("nse_symbol") or "").strip().upper()
            if code and nse:
                out[code] = nse
    return out


def icici_symbol(code: str) -> Optional[str]:
    """The NSE symbol of an ICICI Direct stock code, or None when ICICI's master does not list it."""
    return _load_map("icicidirect.csv").get((code or "").strip().upper())


def _iso(value: Any) -> Optional[str]:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and len(value) >= 10:
        try:
            return date.fromisoformat(value[:10]).isoformat()
        except ValueError:
            return None
    return None


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def parse_zerodha(symbol: str) -> Optional[Contract]:
    """A Kite F&O trading symbol as a contract, or None when it is not one (shares, or a format not recognised)."""
    s = (symbol or "").strip().upper()
    m = _Z_WEEKLY.match(s)
    if m:
        month = _WEEK_MONTH[m.group("m")]
        try:
            day = date(2000 + int(m.group("yy")), month, int(m.group("dd")))
        except ValueError:
            day = None
        if day is not None:
            return Contract(m.group("u"), m.group("opt"), expiry=day.isoformat(), strike=float(m.group("strike")),
                            broker_code=s)
    m = _Z_MONTHLY.match(s)
    if m:
        ym = f"{2000 + int(m.group('yy')):04d}-{_MONTHS[m.group('mon')]:02d}"
        if m.group("fut"):
            return Contract(m.group("u"), "FUT", expiry_month=ym, broker_code=s)
        return Contract(m.group("u"), m.group("opt"), expiry_month=ym, strike=float(m.group("strike")), broker_code=s)
    return None


def normalise(row: Dict[str, Any], broker: str) -> Contract:
    """The NSE contract a broker position row (a HubPosition dict) holds."""
    slug = (broker or "").strip().lower()
    code = str(row.get("symbol") or "").strip().upper()
    segment = str(row.get("segment") or "").lower()
    itype = str(row.get("instrument_type") or "").upper() or None
    expiry = _iso(row.get("expiry"))
    strike = _num(row.get("strike"))
    derivative = segment == "fno" or itype in ("FUT", "CE", "PE")
    if not code:
        return Contract("", "EQ", mapped=False, problem="the broker sent a row with no symbol")
    if slug in ICICI_SLUGS:
        nse = icici_symbol(code)
        if nse is None:
            return Contract(code, itype or "EQ", expiry=expiry, strike=strike, mapped=False, broker_code=code,
                            problem=f"ICICI Direct code {code} is not in ICICI's security master")
        if not derivative:
            return Contract(nse, "EQ", broker_code=code)
        return _derivative(nse, itype, expiry, strike, code)
    if slug in ZERODHA_SLUGS and derivative:
        parsed = parse_zerodha(code)
        if parsed is None:
            return Contract(code, itype or "FUT", mapped=False, broker_code=code,
                            problem=f"the Kite symbol {code} is not a recognised futures or options symbol")
        # The row's own expiry, when the broker sends one, beats a month read from the symbol.
        if expiry and parsed.expiry is None:
            parsed = replace(parsed, expiry=expiry, expiry_month=None)
        return parsed
    if not derivative:
        return Contract(code, "EQ", broker_code=code)
    return _derivative(code, itype, expiry, strike, code)


def _derivative(underlying: str, itype: Optional[str], expiry: Optional[str], strike: Optional[float], code: str) -> Contract:
    if itype not in ("FUT", "CE", "PE"):
        return Contract(underlying, "FUT", mapped=False, broker_code=code,
                        problem=f"{code}: the broker did not say whether this is a future, a call or a put")
    if not expiry:
        return Contract(underlying, itype, mapped=False, broker_code=code, problem=f"{code}: the broker sent no expiry date")
    if itype in ("CE", "PE") and (strike is None or strike <= 0):
        return Contract(underlying, itype, expiry=expiry, mapped=False, broker_code=code,
                        problem=f"{code}: the broker sent no strike for an option")
    return Contract(underlying, itype, expiry=expiry, strike=strike if itype != "FUT" else None, broker_code=code)


def resolve_monthly(c: Contract, futures_expiries: Iterable[str]) -> Contract:
    """A monthly contract's expiry day: the underlying's listed futures expiry in that month (NSE's monthly expiry).
    Unchanged when the contract already has its day; unmapped when no listed future expires in that month."""
    if c.expiry or not c.expiry_month or not c.mapped:
        return c
    days = sorted(e for e in futures_expiries if isinstance(e, str) and e.startswith(c.expiry_month))
    if not days:
        return replace(c, mapped=False, problem=f"{c.broker_code or c.underlying}: no {c.underlying} future is listed "
                                                 f"for {c.expiry_month}, so its expiry day is unknown")
    return replace(c, expiry=days[-1], expiry_month=None)


def label(c: Contract) -> str:
    """'NIFTY 25 Nov 2026 23000 CE', 'SONACOMS 25 Nov 2026 FUT', 'RELIANCE'."""
    if c.instrument == "EQ":
        return c.underlying
    when = c.expiry or c.expiry_month or "?"
    try:
        d = date.fromisoformat(when)
        when = f"{d.day} {d.strftime('%b %Y')}"
    except ValueError:
        pass
    if c.instrument == "FUT":
        return f"{c.underlying} {when} FUT"
    return f"{c.underlying} {when} {_strike_text(c.strike)} {c.instrument}"
