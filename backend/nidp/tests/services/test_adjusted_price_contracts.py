"""Price readers must declare raw-vs-adjusted, and the across-session ones must be adjusted.

nidp.prices_eod is RAW. Its own prev_close is raw too: on KOTAKBANK's 5:1 split ex 2026-01-14 it
reads 2132.60 against an open of 426.00, so even a one-session return off that feed is -80.26%.
Every figure measured across sessions therefore has to come from nidp.prices_eod_adjusted.

The bars below are the real staging rows for 2025-12-31..2026-01-21 (read 2026-10-22), in both
spaces, so these cases actually traverse a corporate action instead of asserting on flat prices.
"""
import asyncio
import inspect
from datetime import date

import pytest

from nidp.services.d1_prep import service as d1_prep
from nidp.services.daas_api.routers import movers
from nidp.services.event_analyzer import analyzer
from nidp.services.intelligence import breakout, confirmation
from nidp.services.intelligence import service as intel
from nidp.services.intelligence_layer import service as intel_layer

# as_of_date, prev_close, open, high, low, close — nidp.prices_eod, series EQ
_RAW = [
    ("2025-12-31", 2152.70, 2158.00, 2205.40, 2155.70, 2201.10),
    ("2026-01-01", 2201.10, 2210.00, 2220.90, 2189.00, 2217.80),
    ("2026-01-02", 2217.80, 2217.80, 2227.90, 2180.50, 2195.10),
    ("2026-01-05", 2195.10, 2196.90, 2206.70, 2182.00, 2190.90),
    ("2026-01-06", 2190.90, 2202.10, 2228.00, 2135.00, 2146.40),
    ("2026-01-07", 2146.40, 2146.40, 2150.50, 2109.20, 2144.00),
    ("2026-01-08", 2144.00, 2140.10, 2143.00, 2118.60, 2133.00),
    ("2026-01-09", 2133.00, 2133.00, 2133.00, 2116.00, 2126.80),
    ("2026-01-12", 2126.80, 2126.80, 2139.40, 2106.00, 2133.30),
    ("2026-01-13", 2133.30, 2126.90, 2144.40, 2120.00, 2132.60),
    ("2026-01-14", 2132.60,  426.00,  427.60,  418.80,  421.00),   # 5:1 split ex-date
    ("2026-01-16",  421.00,  424.00,  427.60,  417.10,  418.20),
    ("2026-01-19",  418.20,  419.00,  430.40,  415.00,  426.90),
    ("2026-01-20",  426.90,  428.00,  431.00,  422.50,  423.80),
    ("2026-01-21",  423.80,  422.10,  425.50,  416.40,  421.60),
]

# the same sessions from nidp.prices_eod_adjusted, prev_adj = lag(adj_close)
_ADJ = [
    ("2025-12-31", 430.54, 431.60, 441.08, 431.14, 440.22),
    ("2026-01-01", 440.22, 442.00, 444.18, 437.80, 443.56),
    ("2026-01-02", 443.56, 443.56, 445.58, 436.10, 439.02),
    ("2026-01-05", 439.02, 439.38, 441.34, 436.40, 438.18),
    ("2026-01-06", 438.18, 440.42, 445.60, 427.00, 429.28),
    ("2026-01-07", 429.28, 429.28, 430.10, 421.84, 428.80),
    ("2026-01-08", 428.80, 428.02, 428.60, 423.72, 426.60),
    ("2026-01-09", 426.60, 426.60, 426.60, 423.20, 425.36),
    ("2026-01-12", 425.36, 425.36, 427.88, 421.20, 426.66),
    ("2026-01-13", 426.66, 425.38, 428.88, 424.00, 426.52),
    ("2026-01-14", 426.52, 426.00, 427.60, 418.80, 421.00),
    ("2026-01-16", 421.00, 424.00, 427.60, 417.10, 418.20),
    ("2026-01-19", 418.20, 419.00, 430.40, 415.00, 426.90),
    ("2026-01-20", 426.90, 428.00, 431.00, 422.50, 423.80),
    ("2026-01-21", 423.80, 422.10, 425.50, 416.40, 421.60),
]

_EX = 10        # index of 2026-01-14, the ex-date
_LAST = 14      # index of 2026-01-21


def _bars(rows):
    return [{"t": t, "prev_c": p, "o": o, "h": h, "l": l, "c": c, "v": 0, "turnover": 0.0}
            for t, p, o, h, l, c in rows]


# ── movers.py: everything downstream of _bars_for is across-session arithmetic ────────────────

def test_atr_off_raw_bars_overstates_volatility_nearly_fourfold():
    """ATR ranks names into the volatility deciles the flag-lift card controls on, so a split
    inside the window moves a name into a decile it does not belong in."""
    raw, adj = movers._atr_pct(_bars(_RAW), _LAST), movers._atr_pct(_bars(_ADJ), _LAST)
    assert raw == pytest.approx(0.07589535, abs=1e-8)
    assert adj == pytest.approx(0.01996765, abs=1e-8)
    assert raw / adj > 3.5


def test_leak_fires_falsely_on_raw_bars_after_a_split():
    """_leak asks whether price drifted the move's way BEFORE the news. On the raw feed the
    split itself is the drift, so the week after any split reads as PRE-PRICED."""
    assert movers._leak(_bars(_RAW), _LAST) is True
    assert movers._leak(_bars(_ADJ), _LAST) is False


def test_event_metrics_gap_and_re_are_the_split_not_a_move():
    raw = movers._event_metrics(_bars(_RAW), _EX - 1)
    adj = movers._event_metrics(_bars(_ADJ), _EX - 1)
    assert raw["gap"] == pytest.approx(-0.80024383, abs=1e-8)
    assert adj["gap"] == pytest.approx(-0.00121917, abs=1e-8)
    assert raw["re"] == pytest.approx(-0.80265317, abs=1e-8)
    assert adj["re"] == pytest.approx(-0.01326583, abs=1e-8)


def test_raw_bars_raise_phantom_gap_flags_the_adjusted_bars_do_not():
    assert movers._flags_fired(_bars(_RAW), _EX - 1) == {"gap2", "gap3", "leak"}
    assert movers._flags_fired(_bars(_ADJ), _EX - 1) == {"leak"}


def test_bars_for_reads_the_adjusted_series_and_keeps_turnover_raw():
    src = inspect.getsource(movers._bars_for)
    assert "nidp.prices_eod_adjusted" in src
    assert "adj_open" in src and "adj_close" in src
    assert "lag(adj_close)" in src                 # the feed's prev_close is raw on an ex-date
    assert "p.turnover" in src and "p.series = 'EQ'" in src   # turnover + the EQ pin stay raw


# ── confirmation.py: the 20-session figures are adjusted, delivery and the quote are raw ──────

class _Conn:
    """Minimal asyncpg stand-in: records SQL and serves the one row the price layer asks for."""

    def __init__(self, row, oi=None):
        self.row, self.oi, self.calls = row, oi, []

    async def fetchrow(self, sql, *args):
        self.calls.append(sql)
        if "prices_eod_adjusted" in sql:
            return self.row
        if self.oi is not None and "fno_bhavcopy" in sql and "open_interest" in sql:
            return self.oi
        return None

    async def fetchval(self, sql, *args):
        self.calls.append(sql)
        return None

    async def fetch(self, sql, *args):
        self.calls.append(sql)
        return []


# the real staging row for KOTAKBANK 2026-01-20, 5:1 split ex 2026-01-14 inside the window
_K20 = {
    "as_of_date": date(2026, 1, 20),
    "adj_open": 428.00, "adj_high": 431.00, "adj_low": 422.50, "adj_close": 423.80,
    "adj_volume": 18805991, "avg_vol_20d": 12310010.571428571429,
    "close_high_20d": 443.56, "intraday_high_20d": 445.60, "avg_range_20d": 7.06,
    "prev_adj": 426.90, "deliv_qty": 14016152, "deliv_pct": 74.53,
    "avg_del_pct_20d": 69.1185714285714286, "raw_close": 423.80,
}


def test_confirmation_scores_the_adjusted_window_not_the_raw_one():
    conn = _Conn(_K20)
    out = asyncio.run(confirmation.get_confirmation(conn, "KOTAKBANK", date(2026, 1, 20)))
    # raw would read vs_20d_high -80.89%, a 4.27x volume spike and range expansion 0.30x
    assert out["vs_20d_high_pct"] == pytest.approx(-4.45, abs=0.01)
    assert out["volume_spike_ratio"] == pytest.approx(1.53, abs=0.01)
    assert out["range_expansion"] == pytest.approx(1.20, abs=0.01)
    # the 4.27x spike scored +25 and printed a signal line; 1.53x is below the 2.0x bar
    assert not any("Volume" in s for s in out["signals_hit"])
    # delivery is a ratio of two raw quantities and needs no adjustment
    assert out["delivery_pct_today"] == pytest.approx(74.5, abs=0.1)
    # the published quote stays the price that actually traded
    assert out["close_price"] == pytest.approx(423.80, abs=0.01)


def test_confirmation_asks_for_delivery_from_the_raw_feed():
    conn = _Conn(_K20)
    asyncio.run(confirmation.get_confirmation(conn, "KOTAKBANK", date(2026, 1, 20)))
    q = conn.calls[0]
    assert "nidp.prices_eod_adjusted" in q and "adj_volume" in q
    assert "FROM nidp.prices_eod" in q and "deliv_pct" in q and "series  = 'EQ'" in q


# the real staging row for AGIIL 2025-10-10, its 5:1 split ex-date: the stock ROSE 15.61% that
# session on the adjusted series while the raw feed reads -76.88% (1245.10 -> 287.90)
_AGIIL = {
    "as_of_date": date(2025, 10, 10),
    "adj_open": 259.00, "adj_high": 298.80, "adj_low": 255.00, "adj_close": 287.90,
    "adj_volume": 5614790, "avg_vol_20d": 1117528.333333333333,
    "close_high_20d": 278.80, "intraday_high_20d": 281.60,
    "avg_range_20d": 16.2233333333333333, "prev_adj": 249.02,
    "deliv_qty": 641366, "deliv_pct": 11.42,
    "avg_del_pct_20d": 35.3514285714285714, "raw_close": 287.90,
}


def test_oi_direction_is_decided_on_the_adjusted_bar():
    """The OI classifier needs the sign of today's move. Off the raw feed an ex-date is always a
    fall, so a name that rose through its split is labelled SHORT_BUILDUP. AGIIL 2025-10-10 is
    that case: raw -76.88%, adjusted +15.61%."""
    conn = _Conn(_AGIIL, oi={"oi_today": 1_100_000, "oi_prev": 1_000_000, "oi_chg_direct": None})
    out = asyncio.run(confirmation.get_confirmation(conn, "AGIIL", date(2025, 10, 10)))
    assert out["oi_change_pct"] == pytest.approx(10.0, abs=0.05)
    assert out["oi_signal"] == "LONG_BUILDUP"
    assert any("price up" in s for s in out["signals_hit"])
    # and the second prices_eod round trip that used to decide this is gone
    assert not any("SELECT prev_close FROM nidp.prices_eod" in q for q in conn.calls)


# ── the three 52-week-range readers: adjusted extremes, restated onto the raw quote's scale ───

class _CtxConn:
    def __init__(self, row):
        self.row, self.calls = row, []

    async def fetchrow(self, sql, *args):
        self.calls.append(sql)
        return self.row


_ANGELONE = {"close_price": 293.20, "high_52w": 354.80, "low_52w": 213.07,
             "sector": "FINANCIAL", "adj_factor": 1.0}


@pytest.mark.parametrize("mod, args", [
    (intel, ("ANGELONE", date(2026, 10, 21))),
    (analyzer, ("ANGELONE",)),
    (d1_prep, ("ANGELONE",)),
])
def test_52w_range_is_adjusted_and_current_price_is_raw(mod, args):
    conn = _CtxConn(dict(_ANGELONE))
    ctx = asyncio.run(mod._get_price_context(conn, *args))
    # raw closes would put the 52-week high at 2847.40 — a 10:1 split ex 2026-02-26, not a high
    assert ctx["high_52w"] == pytest.approx(354.80, abs=0.01)
    assert ctx["low_52w"] == pytest.approx(213.07, abs=0.01)
    assert ctx["current_price"] == pytest.approx(293.20, abs=0.01)
    q = conn.calls[0]
    assert "nidp.prices_eod_adjusted" in q and "MAX(adj_close)" in q
    assert "p.close_price" in q                     # the quote itself still off the raw feed


@pytest.mark.parametrize("mod, args", [
    (intel, ("X", date(2026, 10, 21))),
    (analyzer, ("X",)),
    (d1_prep, ("X",)),
])
def test_extremes_are_restated_onto_the_quoted_share_scale(mod, args):
    """A pending ex-date leaves a non-unit factor on the newest session (2 of 2,694 symbols on
    staging 2026-10-21). There the quote is still on the old scale, so the extremes must be too —
    an adjusted high beside a raw price would be a new inconsistency, not a fix."""
    conn = _CtxConn(dict(_ANGELONE, adj_factor=0.1))
    ctx = asyncio.run(mod._get_price_context(conn, *args))
    assert ctx["high_52w"] == pytest.approx(3548.00, abs=0.01)
    assert ctx["low_52w"] == pytest.approx(2130.70, abs=0.01)
    assert ctx["current_price"] == pytest.approx(293.20, abs=0.01)


def test_near_52w_high_bonus_is_reachable_only_on_the_adjusted_extreme():
    """breakout.py awards near_52w_high within 5%. KOTAKBANK on 2026-10-21 sits 2.3% below its
    adjusted 52-week high and 80.3% below the raw one, so the raw path can never fire it."""
    raw = breakout.detect_breakout(
        event_type="order_win", sentiment="bullish", confidence=80, impact_score=50,
        confirmation={}, current_price=437.80, high_52w=2225.60, low_52w=353.40)
    adj = breakout.detect_breakout(
        event_type="order_win", sentiment="bullish", confidence=80, impact_score=50,
        confirmation={}, current_price=437.80, high_52w=447.95, low_52w=353.40)
    assert not any("52W" in s for s in raw["layers_hit"])
    assert any("52W" in s for s in adj["layers_hit"])
    assert adj["breakout_score"] > raw["breakout_score"]


# ── intelligence_layer: graph.correlations must not be fed a return that never happened ───────

def test_correlations_read_adjusted_closes_and_drop_the_raw_source_filter():
    src = inspect.getsource(intel_layer.run)
    # these three strings occur only inside the graph.correlations statement
    assert "FROM nidp.prices_eod_adjusted p" in src
    assert "lag(p.adj_close)" in src
    # the adjusted table's only source is NIDP_PRICE_ADJUSTER, so the old predicate matched nothing
    assert "p.source = 'NSE_BHAVCOPY'" not in src
    # the trading calendar is not a price and stays on the raw table
    assert "SELECT max(as_of_date) AS dt FROM nidp.prices_eod" in src
