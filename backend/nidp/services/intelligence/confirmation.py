"""Market Confirmation Engine.

Checks whether the market is confirming a corporate event through:

  1. Volume spike      — today's volume vs 20-day average
  2. Delivery spike    — delivery % today vs 20-day average delivery %
  3. OI buildup        — futures open interest change vs previous day
  4. Sector strength   — relevant index return for the day
  5. Relative volume   — how unusual today's activity is (> 3x = very strong)

All checks pull from existing NIDP warehouse tables:
  - nidp.eod_prices      (volume, delivery)
  - nidp.fno_bhavcopy    (futures OI)
  - nidp.index_close     (sector index daily close)

Returns a ConfirmationResult dict with scores for each layer and an
overall confirmation_score (0–100) + boolean `confirmed` flag.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Thresholds for each confirmation signal
_VOL_SPIKE_STRONG    = 3.0   # ≥ 3x 20D avg → strong
_VOL_SPIKE_MODERATE  = 2.0   # ≥ 2x → moderate
_DEL_SPIKE_STRONG    = 2.0   # ≥ 2x avg delivery % → strong
_DEL_SPIKE_MODERATE  = 1.5   # ≥ 1.5x → moderate
_OI_CHANGE_STRONG    = 10.0  # ≥ +10% OI → strong build
_OI_CHANGE_MODERATE  = 5.0   # ≥ +5% → moderate
_SECTOR_STRONG_PCT   = 1.0   # ≥ +1% sector move
_SECTOR_MODERATE_PCT = 0.5   # ≥ +0.5%


async def get_confirmation(
    conn,
    symbol: str,
    trade_date: date,
) -> dict:
    """Run all confirmation checks for a symbol on a given trade date.

    Returns a dict with individual signal details and aggregate scores.
    Empty/unavailable data produces partial results gracefully.
    """
    result: dict = {
        "trade_date":           str(trade_date),
        "symbol":               symbol,
        "volume_spike_ratio":   None,
        "delivery_pct_today":   None,
        "delivery_spike_ratio": None,
        "oi_change_pct":        None,
        "sector_return_pct":    None,
        "relative_volume":      None,
        "signals_hit":          [],
        "confirmation_score":   0.0,
        "confirmed":            False,
    }

    score = 0.0

    # ── 1. Volume + Delivery (from eod_prices) ───────────────────────
    try:
        price_row = await conn.fetchrow(
            """
            SELECT traded_qty,
                   delivery_qty,
                   avg_vol_20d,
                   avg_del_pct_20d
              FROM (
                  SELECT traded_qty,
                         delivery_qty,
                         NULLIF(traded_qty, 0) AS tq,
                         AVG(traded_qty) OVER (
                             ORDER BY trade_date
                             ROWS BETWEEN 21 PRECEDING AND 1 PRECEDING
                         ) AS avg_vol_20d,
                         AVG(
                             CASE WHEN traded_qty > 0
                                  THEN delivery_qty::float / traded_qty
                             END
                         ) OVER (
                             ORDER BY trade_date
                             ROWS BETWEEN 21 PRECEDING AND 1 PRECEDING
                         ) AS avg_del_pct_20d,
                         trade_date
                    FROM nidp.eod_prices
                   WHERE symbol = $1
                     AND trade_date <= $2
                   ORDER BY trade_date DESC
                   LIMIT 1
              ) x
            """,
            symbol, trade_date,
        )

        if price_row and price_row["traded_qty"]:
            tq = float(price_row["traded_qty"])
            avg = float(price_row["avg_vol_20d"] or tq)
            vol_ratio = tq / avg if avg > 0 else 1.0
            result["volume_spike_ratio"] = round(vol_ratio, 2)
            result["relative_volume"]    = round(vol_ratio, 2)

            if vol_ratio >= _VOL_SPIKE_STRONG:
                score += 25
                result["signals_hit"].append(f"Volume spike {vol_ratio:.1f}x 20D avg")
            elif vol_ratio >= _VOL_SPIKE_MODERATE:
                score += 15
                result["signals_hit"].append(f"Volume elevated {vol_ratio:.1f}x 20D avg")

            dq = float(price_row["delivery_qty"] or 0)
            del_pct = dq / tq if tq > 0 else 0.0
            avg_del = float(price_row["avg_del_pct_20d"] or del_pct or 0.30)
            del_ratio = del_pct / avg_del if avg_del > 0 else 1.0
            result["delivery_pct_today"]   = round(del_pct * 100, 1)
            result["delivery_spike_ratio"] = round(del_ratio, 2)

            if del_ratio >= _DEL_SPIKE_STRONG:
                score += 20
                result["signals_hit"].append(f"Delivery spike {del_ratio:.1f}x avg ({del_pct*100:.0f}%)")
            elif del_ratio >= _DEL_SPIKE_MODERATE:
                score += 12
                result["signals_hit"].append(f"Delivery elevated {del_ratio:.1f}x avg")

    except Exception as e:
        logger.debug("confirmation: volume/delivery check failed for %s: %s", symbol, e)

    # ── 2. Futures OI (from fno_bhavcopy) ───────────────────────────
    try:
        oi_row = await conn.fetchrow(
            """
            SELECT oi_today, oi_prev,
                   CASE WHEN oi_prev > 0 THEN (oi_today - oi_prev)::float / oi_prev * 100 END
                       AS oi_change_pct
              FROM (
                  SELECT
                      SUM(CASE WHEN trade_date = $2 THEN open_interest ELSE 0 END) AS oi_today,
                      SUM(CASE WHEN trade_date = $3 THEN open_interest ELSE 0 END) AS oi_prev
                    FROM nidp.fno_bhavcopy
                   WHERE symbol = $1
                     AND instrument ILIKE 'FUT%'
                     AND trade_date IN ($2, $3)
              ) x
            """,
            symbol, trade_date, trade_date - timedelta(days=1),
        )

        if oi_row and oi_row["oi_change_pct"] is not None:
            oi_chg = float(oi_row["oi_change_pct"])
            result["oi_change_pct"] = round(oi_chg, 1)

            if oi_chg >= _OI_CHANGE_STRONG:
                score += 20
                result["signals_hit"].append(f"Futures OI buildup +{oi_chg:.0f}%")
            elif oi_chg >= _OI_CHANGE_MODERATE:
                score += 12
                result["signals_hit"].append(f"Futures OI up +{oi_chg:.0f}%")
            elif oi_chg <= -_OI_CHANGE_MODERATE:
                # OI unwinding — bearish confirmation for shorts
                result["signals_hit"].append(f"Futures OI unwinding {oi_chg:.0f}%")

    except Exception as e:
        logger.debug("confirmation: OI check failed for %s: %s", symbol, e)

    # ── 3. Sector strength (from index_close) ───────────────────────
    try:
        sector_row = await conn.fetchrow(
            """
            WITH latest AS (
                SELECT index_name, close_value,
                       LAG(close_value) OVER (PARTITION BY index_name ORDER BY trade_date) AS prev_close,
                       trade_date
                  FROM nidp.index_close
                 WHERE index_name IN (
                     SELECT COALESCE(sector_index, 'NIFTY 50')
                       FROM nidp.symbol_master
                      WHERE symbol = $1
                 )
                   AND trade_date >= $2 - INTERVAL '5 days'
                   AND trade_date <= $2
            )
            SELECT index_name,
                   CASE WHEN prev_close > 0
                        THEN (close_value - prev_close) / prev_close * 100
                   END AS return_pct
              FROM latest
             WHERE trade_date = $2
             ORDER BY return_pct DESC NULLS LAST
             LIMIT 1
            """,
            symbol, trade_date,
        )

        if sector_row and sector_row["return_pct"] is not None:
            sec_ret = float(sector_row["return_pct"])
            result["sector_return_pct"] = round(sec_ret, 2)

            if sec_ret >= _SECTOR_STRONG_PCT:
                score += 15
                result["signals_hit"].append(f"Sector strong +{sec_ret:.1f}%")
            elif sec_ret >= _SECTOR_MODERATE_PCT:
                score += 8
                result["signals_hit"].append(f"Sector positive +{sec_ret:.1f}%")
            elif sec_ret <= -_SECTOR_STRONG_PCT:
                result["signals_hit"].append(f"Sector weak {sec_ret:.1f}%")

    except Exception as e:
        logger.debug("confirmation: sector check failed for %s: %s", symbol, e)

    # ── VWAP hold approximation ──────────────────────────────────────
    # If delivery % > 30% AND volume spike — institutional accumulation likely
    del_pct = result.get("delivery_pct_today") or 0
    vol_ratio = result.get("volume_spike_ratio") or 1
    if del_pct >= 30 and vol_ratio >= 2.0:
        score += 10
        result["signals_hit"].append(f"Institutional accumulation (delivery {del_pct:.0f}%)")

    result["confirmation_score"] = round(min(score, 100.0), 1)
    result["confirmed"] = score >= 40  # at least 2 moderate signals

    return result
