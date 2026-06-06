"""Pure-Python corp-action factor math. No DB, no I/O.

The whole correctness story for the price adjuster lives here. Every
edge case has a test in test_nidp_price_adjuster_factors.py — if you
touch this file, run those tests first.

Conventions:
    • Factor < 1 means PRIOR closes get scaled DOWN (forward-adjust).
      e.g. a 5:1 split means each old share becomes 5 new; old prices
      should be divided by 5 (factor = 0.2 in our model since
      face_value_post / face_value_pre = 1/5 when 10 → 2).
    • Cumulative factor for date t = product of every event factor
      where ex_date > t. The ex-date itself is post-adjustment per
      NSE convention (NSE bhavcopy reports the post-split close on
      the ex-date), so we use STRICTLY GREATER than.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CorpActionEvent:
    """Normalised corp-action event with its computable factor.

    `pret_factor`: applies to price-return adjustment (used for
        adj_close — what backtests should use).
    `tret_factor`: applies to total-return (adj_close × dividend
        adjustment). Equals pret_factor for SPLIT/BONUS;
        differs only for DIVIDEND/DISTRIBUTION where pret_factor = 1.0
        and tret_factor accounts for the cash payout.
    """
    symbol:      str
    ex_date:     date
    action_type: str              # 'SPLIT' | 'BONUS' | 'DIVIDEND' | 'DISTRIBUTION'
    pret_factor: float
    tret_factor: float


# ── Per-event factor computation ────────────────────────────────────
def split_factor(face_value_pre: Optional[float],
                 face_value_post: Optional[float]) -> Optional[float]:
    """Stock split: 1 share of face_value_pre becomes
    (face_value_pre / face_value_post) shares of face_value_post.
    Each share's price scales by face_value_post / face_value_pre.

    Example: 10 → 2 split. Pre = ₹10 face value; Post = ₹2.
    factor = 2/10 = 0.2 → prior ₹500 close becomes ₹100 adj_close.
    """
    if face_value_pre is None or face_value_post is None:
        return None
    if face_value_pre <= 0 or face_value_post <= 0:
        return None
    if face_value_pre == face_value_post:
        return None  # not actually a split
    return face_value_post / face_value_pre


_BONUS_RATIO_RE = re.compile(r"(?P<n>\d+(?:\.\d+)?)\s*[:/]\s*(?P<m>\d+(?:\.\d+)?)")


def bonus_factor(ratio: Optional[str]) -> Optional[float]:
    """Bonus issue: ratio is "n:m" meaning n new shares for every m
    held. After bonus, total shares = m + n per m original; factor
    = m / (m + n).

    Example: 1:1 → 1 new for 1 held → factor = 1/2 = 0.5
    Example: 1:5 → 1 new for 5 held → factor = 5/6 ≈ 0.833
    Example: 2:1 → 2 new for 1 held → factor = 1/3 ≈ 0.333
    """
    if not ratio:
        return None
    m = _BONUS_RATIO_RE.search(ratio)
    if not m:
        return None
    try:
        n = float(m.group("n"))
        held = float(m.group("m"))
    except ValueError:
        return None
    if n <= 0 or held <= 0:
        return None
    factor = held / (held + n)
    if not (0 < factor < 1):
        return None
    return factor


def dividend_factor(amount: Optional[float],
                    prev_close: Optional[float]) -> Optional[float]:
    """Dividend factor for total-return adjustment.

    On ex-date, theoretical ex-price = prev_close − dividend_amount.
    Total-return factor = (prev_close − amount) / prev_close, applied
    to all PRIOR prices to reflect that dividends were paid out.

    Returns None if either input is missing or non-positive.
    """
    if amount is None or prev_close is None:
        return None
    if amount <= 0 or prev_close <= 0:
        return None
    if amount >= prev_close:
        # Dividend exceeds prev close — almost always a data error
        # (special distribution mis-classified as cash dividend).
        return None
    return (prev_close - amount) / prev_close


# ── Normalisation pass ──────────────────────────────────────────────
def build_events(
    raw_actions: Iterable[dict],
    prev_close_lookup,
) -> List[CorpActionEvent]:
    """Transform raw nidp.corporate_actions rows into computable
    events. Drops rows where the factor cannot be derived.

    `prev_close_lookup(symbol, ex_date) -> Optional[float]` returns
    the close on the trading day strictly before `ex_date` for that
    symbol. Used only for dividend adjustments. Pass a no-op (always
    returning None) to skip dividends entirely.
    """
    out: List[CorpActionEvent] = []
    for r in raw_actions:
        symbol = r.get("symbol")
        ex_date = r.get("ex_date")
        action = (r.get("action_type") or "").upper()
        if not symbol or not ex_date or not action:
            continue

        if action == "SPLIT":
            fv_pre  = float(r["face_value_pre"])  if r.get("face_value_pre")  is not None else None
            fv_post = float(r["face_value_post"]) if r.get("face_value_post") is not None else None
            f = split_factor(fv_pre, fv_post)
            if f is None:
                continue
            out.append(CorpActionEvent(symbol, ex_date, action, f, f))

        elif action == "BONUS":
            f = bonus_factor(r.get("ratio"))
            if f is None:
                continue
            out.append(CorpActionEvent(symbol, ex_date, action, f, f))

        elif action in ("DIVIDEND", "DISTRIBUTION"):
            # DISTRIBUTION: InvIT/REIT income distributions — same cash-payout
            # mechanics as a regular dividend. pret_factor = 1.0 (the price
            # drop on ex-date reflects the distribution but we don't scale
            # historical prices); tret_factor accounts for the cash received.
            prev = prev_close_lookup(symbol, ex_date)
            if prev is not None:
                prev = float(prev)
            div_amt = float(r["dividend_amount"]) if r.get("dividend_amount") is not None else None
            f = dividend_factor(div_amt, prev)
            if f is None:
                continue
            # PRET unaffected by cash payouts
            out.append(CorpActionEvent(symbol, ex_date, action, 1.0, f))

        elif action == "RIGHTS":
            # Rights issues require the subscription price to compute the
            # theoretical ex-rights price (TERP). We don't store subscription
            # price in nidp.corporate_actions, so we cannot derive an accurate
            # factor. Treating rights like bonus (dilution-only) would
            # systematically overstate the adjustment. Skip and warn so the
            # gap is visible in logs rather than silently wrong.
            logger.warning(
                "price_adjuster: skipping RIGHTS event for %s ex_date=%s "
                "(ratio=%s) — subscription price not stored; "
                "TERP-based adjustment cannot be computed",
                symbol, ex_date, r.get("ratio"),
            )

        elif action == "BUYBACK":
            # Buybacks are executed at market price (or a small premium via
            # tender offer). They reduce share count but do not cause a
            # defined per-share price drop on ex-date — no factor to apply.
            pass

        # INTEREST_PAYMENT, MERGER, DEMERGER, and other types: no adjustment.
    return out


# ── Cumulative factor walk ──────────────────────────────────────────
def cumulative_factors_for_dates(
    events: List[CorpActionEvent],
    target_dates: List[date],
) -> List[Tuple[float, float, Optional[date], Optional[str]]]:
    """For each target_date, compute (cum_pret, cum_tret, last_ex,
    last_type) where the cumulative factor multiplies all event
    factors with ex_date STRICTLY GREATER than target_date.

    O(D log E + E) — events sorted ascending by ex_date, then we
    walk both lists in tandem.

    Returns list aligned 1:1 with target_dates input order.
    """
    if not events:
        return [(1.0, 1.0, None, None) for _ in target_dates]

    # Events sorted ascending by ex_date
    events_sorted = sorted(events, key=lambda e: e.ex_date)

    # Precompute suffix products: from event index i onward, the
    # product of all factors at indices >= i. That's the cumulative
    # factor for any target_date < events_sorted[i].ex_date.
    n = len(events_sorted)
    pret_suffix = [1.0] * (n + 1)   # pret_suffix[i] = prod of pret_factor[j>=i]
    tret_suffix = [1.0] * (n + 1)
    for i in range(n - 1, -1, -1):
        pret_suffix[i] = pret_suffix[i + 1] * events_sorted[i].pret_factor
        tret_suffix[i] = tret_suffix[i + 1] * events_sorted[i].tret_factor

    # For each target_date, find the first event index whose
    # ex_date > target_date. Bisect.
    import bisect
    ex_dates = [e.ex_date for e in events_sorted]

    out: List[Tuple[float, float, Optional[date], Optional[str]]] = []
    for d in target_dates:
        # bisect_right gives the insertion point after all events
        # with ex_date <= d. So events at idx >= that point have
        # ex_date > d.
        idx = bisect.bisect_right(ex_dates, d)
        if idx >= n:
            out.append((1.0, 1.0, None, None))
        else:
            evt = events_sorted[idx]
            out.append((pret_suffix[idx], tret_suffix[idx], evt.ex_date, evt.action_type))
    return out
