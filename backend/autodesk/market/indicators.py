"""Plain indicators over daily bars (oldest first). Decimal in, Decimal out; None when there are not enough bars —
never a padded or zero-filled value."""
from __future__ import annotations

from decimal import Decimal
from typing import Optional, Sequence

from .view import Bar

Q = Decimal("0.0001")


def sma(values: Sequence[Decimal], n: int) -> Optional[Decimal]:
    if n <= 0 or len(values) < n:
        return None
    return (sum(values[-n:], Decimal("0")) / n).quantize(Q)


def closes(bars: Sequence[Bar]) -> list[Decimal]:
    return [b.close for b in bars]


def true_ranges(bars: Sequence[Bar]) -> list[Decimal]:
    out = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i].high, bars[i].low, bars[i - 1].close
        out.append(max(h - l, abs(h - pc), abs(l - pc)))
    return out


def atr(bars: Sequence[Bar], n: int = 14) -> Optional[Decimal]:
    """Wilder's average true range."""
    tr = true_ranges(bars)
    if len(tr) < n:
        return None
    a = sum(tr[:n], Decimal("0")) / n
    for x in tr[n:]:
        a = (a * (n - 1) + x) / n
    return a.quantize(Q)


def rsi(values: Sequence[Decimal], n: int = 14) -> Optional[Decimal]:
    """Wilder's RSI."""
    if len(values) < n + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(d, Decimal("0")))
        losses.append(max(-d, Decimal("0")))
    ag = sum(gains[:n], Decimal("0")) / n
    al = sum(losses[:n], Decimal("0")) / n
    for g, l in zip(gains[n:], losses[n:]):
        ag = (ag * (n - 1) + g) / n
        al = (al * (n - 1) + l) / n
    if al == 0:
        return Decimal("100")
    rs = ag / al
    return (Decimal("100") - Decimal("100") / (1 + rs)).quantize(Q)


def pct_return(values: Sequence[Decimal], n: int) -> Optional[Decimal]:
    """Return over the last n sessions, in percent."""
    if len(values) < n + 1 or values[-n - 1] == 0:
        return None
    return ((values[-1] / values[-n - 1] - 1) * 100).quantize(Q)


def prior_high(bars: Sequence[Bar], n: int) -> Optional[Decimal]:
    """Highest high of the n sessions BEFORE the last one."""
    if len(bars) < n + 1:
        return None
    return max(b.high for b in bars[-n - 1:-1])


def prior_low(bars: Sequence[Bar], n: int) -> Optional[Decimal]:
    if len(bars) < n + 1:
        return None
    return min(b.low for b in bars[-n - 1:-1])


def volume_ratio(bars: Sequence[Bar], n: int = 20) -> Optional[Decimal]:
    """Last session's volume over the average of the n sessions before it."""
    if len(bars) < n + 1:
        return None
    avg = Decimal(sum(b.volume for b in bars[-n - 1:-1])) / n
    return (Decimal(bars[-1].volume) / avg).quantize(Q) if avg > 0 else None


def avg_traded_value(bars: Sequence[Bar], n: int = 20) -> Optional[Decimal]:
    if len(bars) < n:
        return None
    vals = [b.turnover_rs if b.turnover_rs is not None else b.close * b.volume for b in bars[-n:]]
    return (sum(vals, Decimal("0")) / n).quantize(Decimal("1"))
