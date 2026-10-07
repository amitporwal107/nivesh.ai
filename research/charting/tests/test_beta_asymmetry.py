"""Directional beta — `research/charting/baselines/beta_asymmetry.py`.

The module's whole claim is that ONE regression cannot tell an upside-capturing stock from a
downside-capturing one. `test_conventional_beta_cannot_separate...` is that claim, stated as a
test: if it ever fails, the feature has no reason to exist.

Recovered 2026-09-30 alongside the module, which existed only on the study box. The module's own
comment cites `test_a_window_across_the_sealed_gap_is_unavailable` by name — that test had been
lost, so it is reinstated here.
"""
from datetime import date, timedelta

import pytest

from research.charting.baselines import beta_asymmetry as B


def _dates(n: int, start=date(2025, 1, 1), step=1) -> list[str]:
    return [(start + timedelta(days=i * step)).isoformat() for i in range(n)]


def _series(n=70, up_beta=1.0, down_beta=1.0, amp=0.01, start=date(2025, 1, 1), step=1):
    """Index alternates up/down; the stock responds with a different beta on each leg.

    The magnitude VARIES within each leg on purpose. With a constant +-1% index move, every x in a
    leg is identical, the regression has no variance to fit, and the slope is legitimately
    undefined — which looks like a module bug and is really a degenerate fixture.
    """
    ds = _dates(n, start, step)
    idx, stk = {}, []
    for i, d in enumerate(ds):
        mag = amp * (1.0 + 0.35 * (i % 5))
        m = mag if i % 2 == 0 else -mag
        idx[d] = m
        stk.append((d, m * (up_beta if m > 0 else down_beta)))
    return ds, stk, idx


# ── the claim the feature exists for ───────────────────────────────────────────────

def test_conventional_beta_cannot_separate_two_opposite_stocks_but_the_split_can():
    """Nifty+1%->+1.8%/Nifty-1%->-0.3% vs +0.5%/-1.7%: opposite animals, near-identical beta."""
    _, up_stock, idx = _series(70, up_beta=1.8, down_beta=0.3)
    _, dn_stock, _ = _series(70, up_beta=0.5, down_beta=1.7)

    a = B.rolling_betas(up_stock, idx)[sorted(idx)[-1]]
    b = B.rolling_betas(dn_stock, idx)[sorted(idx)[-1]]

    # one regression: nearly the same number for both
    assert a["beta_60"] == pytest.approx(b["beta_60"], abs=0.35), \
        "if conventional beta already separates them, this feature is unnecessary"
    # split: opposite signs, unmistakably
    assert a["beta_asym_60"] > 1.0
    assert b["beta_asym_60"] < -1.0
    assert a["beta_up_60"] == pytest.approx(1.8, abs=0.05)
    assert a["beta_down_60"] == pytest.approx(0.3, abs=0.05)


# ── point-in-time ──────────────────────────────────────────────────────────────────

def test_the_window_never_includes_the_signal_bar():
    """A window ending at i would use the very bar whose outcome is being predicted."""
    ds, stk, idx = _series(70, up_beta=1.0, down_beta=1.0)
    clean = B.rolling_betas(stk, idx)[ds[-1]]["beta_60"]

    spiked = list(stk)
    spiked[-1] = (ds[-1], stk[-1][1] * 50)          # violent move ON the signal bar
    after = B.rolling_betas(spiked, idx)[ds[-1]]["beta_60"]
    assert after == pytest.approx(clean), "the signal bar leaked into its own estimate"


# ── the sealed gap, and the subtler staleness case ─────────────────────────────────

def test_a_window_across_the_sealed_gap_is_unavailable():
    """The index jumps 2022-12-30 -> 2024-08-01. A window straddling it mixes two market epochs."""
    pre = _series(40, start=date(2022, 11, 1))
    post = _series(40, start=date(2024, 8, 1))
    idx = {**pre[2], **post[2]}
    stk = pre[1] + post[1]
    out = B.rolling_betas(stk, idx)
    straddler = sorted(idx)[65]                      # its 60-row window spans the gap
    assert out[straddler]["beta_60"] is None
    assert out[straddler]["beta_asym_60"] is None


def test_a_clean_window_applied_across_the_gap_is_also_refused():
    """The worse case the span check alone misses: at the first post-gap row the window is 60
    CLEAN pre-gap sessions, so span passes — and the beta is then applied 19 months later."""
    pre = _series(61, start=date(2022, 10, 1))
    post = _series(5, start=date(2024, 8, 1))
    idx = {**pre[2], **post[2]}
    out = B.rolling_betas(pre[1] + post[1], idx)
    first_post = sorted(idx)[61]
    assert out[first_post]["beta_60"] is None, "a beta 19 months stale is another market's beta"


def test_an_ordinary_holiday_gap_is_still_allowed():
    """The staleness guard must not reject a long weekend, or it rejects everything."""
    ds, stk, idx = _series(70, step=1)
    assert B.rolling_betas(stk, idx)[ds[-1]]["beta_60"] is not None


# ── leg sizes and pairing ──────────────────────────────────────────────────────────

def test_a_leg_with_too_few_observations_gives_none_not_a_two_point_line():
    ds = _dates(70)
    idx, stk = {}, []
    for i, d in enumerate(ds):
        mag = 0.01 * (1.0 + 0.3 * (i % 7))
        m = mag if i % 20 else -mag                # only ~3 down days in any 60-row window
        idx[d] = m
        stk.append((d, m * 1.2))
    rec = B.rolling_betas(stk, idx)[ds[-1]]
    assert rec["beta_down_60"] is None, f"under MIN_LEG_OBS={B.MIN_LEG_OBS} is not a regression"
    assert rec["beta_asym_60"] is None, "asymmetry needs both legs"
    assert rec["beta_60"] is not None, "the pooled beta is still estimable"


def test_a_date_the_stock_did_not_trade_is_dropped_not_zero_filled():
    ds, stk, idx = _series(70)
    thinned = [(d, r) for d, r in stk if d != ds[10]]
    out = B.rolling_betas(thinned, idx)
    assert ds[10] not in out, "a non-trading day must contribute nothing, not a fabricated zero"


def test_rows_before_the_first_full_window_are_unavailable():
    ds, stk, idx = _series(70)
    assert B.rolling_betas(stk, idx)[ds[5]]["beta_60"] is None


# ── surface ────────────────────────────────────────────────────────────────────────

def test_feature_names_cover_every_window_and_measure():
    names = B.feature_names()
    assert len(names) == len(B.WINDOWS) * 5
    for w in B.WINDOWS:
        for k in ("beta_up", "beta_down", "beta_asym", "beta", "corr"):
            assert f"{k}_{w}" in names


def test_every_record_carries_every_key_even_when_unavailable():
    """A missing key and a None value read very differently downstream."""
    ds, stk, idx = _series(70)
    for rec in B.rolling_betas(stk, idx).values():
        for n in B.feature_names():
            assert n in rec
