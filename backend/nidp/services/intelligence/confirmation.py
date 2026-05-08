"""Market Confirmation Engine.

Checks whether the market is confirming a corporate event through five
independent signal layers, all pulled from existing NIDP warehouse tables:

  1. Volume spike      — prices_eod.volume vs 20-day average
  2. Delivery spike    — prices_eod.deliv_pct vs 20-day average
  3. Futures OI        — fno_bhavcopy FUTSTK open_interest change
  4. Put-Call Ratio    — fno_bhavcopy CE/PE open_interest balance
  5. Sector strength   — index_eod.pct_change for the sector index
  + Price breakout     — close vs 20D high, gap-up, range expansion

Table references (correct schema):
  nidp.prices_eod    — EOD OHLCV + delivery; key columns: volume, deliv_qty,
                       deliv_pct, close_price, high_price, low_price,
                       open_price, prev_close; date col: as_of_date
  nidp.fno_bhavcopy  — F&O bhavcopy; key cols: ticker_symbol, instrument_type,
                       option_type, open_interest, change_in_oi; date: as_of_date
  nidp.index_eod     — Index daily closes; pct_change already computed by NSE
  nidp.sector_master — symbol → sector mapping (no direct sector_index col)
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ── Sector → NSE index name mapping ─────────────────────────────────
_SECTOR_INDEX: dict[str, str] = {
    "BANKING":    "Nifty Bank",
    "IT":         "Nifty IT",
    "PHARMA":     "Nifty Pharma",
    "HEALTHCARE": "Nifty Healthcare Index",
    "FMCG":       "Nifty FMCG",
    "METAL":      "Nifty Metal",
    "ENERGY":     "Nifty Energy",
    "AUTO":       "Nifty Auto",
    "REALTY":     "Nifty Realty",
    "INFRA":      "Nifty Infra",
    "MEDIA":      "Nifty Media",
    "PSU_BANK":   "Nifty PSU Bank",
    "FINANCIAL":  "Nifty Financial Services",
    "NBFC":       "Nifty Financial Services",
    "DEFENCE":    "Nifty India Defence",
    "CONSUMER":   "Nifty India Consumption",
    "MIDCAP":     "Nifty Midcap 100",
}
_DEFAULT_INDEX = "Nifty 50"

# ── Confirmation thresholds ──────────────────────────────────────────
_VOL_SPIKE_STRONG    = 3.0
_VOL_SPIKE_MODERATE  = 2.0
_DEL_SPIKE_STRONG    = 2.0    # delivery% today / 20D avg delivery%
_DEL_SPIKE_MODERATE  = 1.5
_OI_CHANGE_STRONG    = 10.0   # % change in futures OI
_OI_CHANGE_MODERATE  = 5.0
_PCR_VERY_BULLISH    = 0.7    # many more calls than puts
_PCR_BULLISH         = 0.85
_PCR_VERY_BEARISH    = 1.4
_PCR_BEARISH         = 1.2
_SECTOR_STRONG       = 1.0    # % sector index move
_SECTOR_MODERATE     = 0.5


async def get_confirmation(conn, symbol: str, trade_date: date) -> dict:
    """Run all confirmation checks for a symbol on a given trade date.

    All unavailable data produces partial results gracefully —
    missing layers simply contribute 0 to the confirmation_score.
    """
    result: dict = {
        "trade_date":           str(trade_date),
        "symbol":               symbol,
        # Volume / Delivery
        "volume_spike_ratio":   None,
        "delivery_pct_today":   None,
        "delivery_spike_ratio": None,
        # Price action
        "close_price":          None,
        "vs_20d_high_pct":      None,   # (close / 20D_high_close - 1) * 100
        "gap_up_pct":           None,   # (open / prev_close - 1) * 100
        "range_expansion":      None,   # today_range / avg_20d_range
        "price_breakout":       False,
        # Derivatives
        "oi_change_pct":        None,
        "oi_signal":            None,   # LONG_BUILDUP | SHORT_COVERING | etc.
        "put_call_ratio":       None,
        "pcr_signal":           None,
        # Sector
        "sector_return_pct":    None,
        "sector_index":         None,
        # Aggregate
        "signals_hit":          [],
        "confirmation_score":   0.0,
        "confirmed":            False,
    }

    score = 0.0

    # ── 1. Volume + Delivery + Price breakout (prices_eod) ───────────
    try:
        price_row = await conn.fetchrow(
            """
            SELECT
                volume,
                deliv_qty,
                deliv_pct,
                close_price,
                open_price,
                high_price,
                low_price,
                prev_close,
                AVG(volume)
                    OVER (ORDER BY as_of_date
                          ROWS BETWEEN 21 PRECEDING AND 1 PRECEDING) AS avg_vol_20d,
                AVG(deliv_pct)
                    OVER (ORDER BY as_of_date
                          ROWS BETWEEN 21 PRECEDING AND 1 PRECEDING) AS avg_del_pct_20d,
                MAX(close_price)
                    OVER (ORDER BY as_of_date
                          ROWS BETWEEN 21 PRECEDING AND 1 PRECEDING) AS close_high_20d,
                MAX(high_price)
                    OVER (ORDER BY as_of_date
                          ROWS BETWEEN 21 PRECEDING AND 1 PRECEDING) AS intraday_high_20d,
                AVG(high_price - low_price)
                    OVER (ORDER BY as_of_date
                          ROWS BETWEEN 21 PRECEDING AND 1 PRECEDING) AS avg_range_20d,
                as_of_date
            FROM nidp.prices_eod
            WHERE symbol = $1
              AND series  = 'EQ'
              AND as_of_date >= $2 - INTERVAL '35 days'
              AND as_of_date <= $2
            ORDER BY as_of_date DESC
            LIMIT 1
            """,
            symbol, trade_date,
        )

        if price_row and price_row["volume"]:
            vol    = float(price_row["volume"])
            avg_v  = float(price_row["avg_vol_20d"] or vol)
            vol_ratio = vol / avg_v if avg_v > 0 else 1.0
            result["volume_spike_ratio"] = round(vol_ratio, 2)

            if vol_ratio >= _VOL_SPIKE_STRONG:
                score += 25
                result["signals_hit"].append(f"Volume spike {vol_ratio:.1f}x 20D avg")
            elif vol_ratio >= _VOL_SPIKE_MODERATE:
                score += 15
                result["signals_hit"].append(f"Volume elevated {vol_ratio:.1f}x 20D avg")

            # Delivery
            del_pct     = float(price_row["deliv_pct"] or 0)
            avg_del_pct = float(price_row["avg_del_pct_20d"] or del_pct or 30.0)
            del_ratio   = del_pct / avg_del_pct if avg_del_pct > 0 else 1.0
            result["delivery_pct_today"]   = round(del_pct, 1)
            result["delivery_spike_ratio"] = round(del_ratio, 2)

            if del_ratio >= _DEL_SPIKE_STRONG:
                score += 20
                result["signals_hit"].append(
                    f"Delivery spike {del_ratio:.1f}x avg ({del_pct:.0f}% of volume)")
            elif del_ratio >= _DEL_SPIKE_MODERATE:
                score += 12
                result["signals_hit"].append(f"Delivery elevated {del_ratio:.1f}x avg")

            # VWAP hold proxy: high delivery + high volume = institutional accumulation
            if del_pct >= 30 and vol_ratio >= 2.0:
                score += 8
                result["signals_hit"].append(
                    f"Institutional accumulation (delivery {del_pct:.0f}%, vol {vol_ratio:.1f}x)")

            # Price breakout checks
            close       = float(price_row["close_price"] or 0)
            open_p      = float(price_row["open_price"] or close)
            prev_close  = float(price_row["prev_close"] or close)
            today_range = float((price_row["high_price"] or close) - (price_row["low_price"] or close))
            avg_range   = float(price_row["avg_range_20d"] or today_range or 1)
            close_h20   = float(price_row["close_high_20d"] or 0)
            result["close_price"] = round(close, 2)

            if close > 0 and close_h20 > 0:
                vs_high = (close / close_h20 - 1) * 100
                result["vs_20d_high_pct"] = round(vs_high, 2)
                if vs_high >= 0:
                    result["price_breakout"] = True
                    score += 15
                    result["signals_hit"].append(f"20D high close breakout (vs high {vs_high:+.1f}%)")
                elif vs_high >= -2:
                    score += 8
                    result["signals_hit"].append(f"Approaching 20D high close ({vs_high:+.1f}%)")

            # Gap-up detection
            if prev_close > 0 and open_p > 0:
                gap_pct = (open_p / prev_close - 1) * 100
                result["gap_up_pct"] = round(gap_pct, 2)
                if gap_pct >= 2.0:
                    score += 12
                    result["signals_hit"].append(f"Gap-up open +{gap_pct:.1f}%")
                elif gap_pct <= -2.0:
                    result["signals_hit"].append(f"Gap-down open {gap_pct:.1f}%")

            # Range expansion
            if avg_range > 0:
                range_ratio = today_range / avg_range
                result["range_expansion"] = round(range_ratio, 2)
                if range_ratio >= 1.5:
                    score += 8
                    result["signals_hit"].append(f"Range expansion {range_ratio:.1f}x normal")

    except Exception as e:
        logger.debug("confirmation: price check failed for %s: %s", symbol, e)

    # ── 2. Futures OI (fno_bhavcopy FUTSTK) ─────────────────────────
    try:
        prev_date = trade_date - timedelta(days=1)
        oi_row = await conn.fetchrow(
            """
            SELECT
                SUM(CASE WHEN as_of_date = $2 THEN open_interest  ELSE 0 END) AS oi_today,
                SUM(CASE WHEN as_of_date = $3 THEN open_interest  ELSE 0 END) AS oi_prev,
                SUM(CASE WHEN as_of_date = $2 THEN change_in_oi   ELSE 0 END) AS oi_chg_direct
              FROM nidp.fno_bhavcopy
             WHERE ticker_symbol   = $1
               AND instrument_type = 'FUTSTK'
               AND as_of_date IN ($2, $3)
            """,
            symbol, trade_date, prev_date,
        )

        if oi_row and oi_row["oi_today"]:
            oi_today = float(oi_row["oi_today"])
            oi_prev  = float(oi_row["oi_prev"] or 0)
            if oi_prev > 0:
                oi_chg_pct = (oi_today - oi_prev) / oi_prev * 100
            else:
                oi_chg_pct = float(oi_row["oi_chg_direct"] or 0)

            result["oi_change_pct"] = round(oi_chg_pct, 1)

            # Classify OI signal using price direction
            close = result.get("close_price") or 0
            prev  = float((await conn.fetchval(
                "SELECT prev_close FROM nidp.prices_eod WHERE symbol=$1 AND as_of_date=$2 AND series='EQ'",
                symbol, trade_date,
            ) or 0))
            price_up = close > prev if close and prev else None

            if oi_chg_pct >= _OI_CHANGE_STRONG:
                score += 18
                if price_up is True:
                    result["oi_signal"] = "LONG_BUILDUP"
                    result["signals_hit"].append(f"Long buildup: OI +{oi_chg_pct:.0f}% with price up")
                else:
                    result["oi_signal"] = "SHORT_BUILDUP"
                    result["signals_hit"].append(f"Short buildup: OI +{oi_chg_pct:.0f}% with price down")
            elif oi_chg_pct >= _OI_CHANGE_MODERATE:
                score += 10
                result["oi_signal"] = "OI_BUILDUP"
                result["signals_hit"].append(f"Futures OI buildup +{oi_chg_pct:.0f}%")
            elif oi_chg_pct <= -_OI_CHANGE_MODERATE:
                if price_up is True:
                    result["oi_signal"] = "SHORT_COVERING"
                    score += 8
                    result["signals_hit"].append(f"Short covering: OI {oi_chg_pct:.0f}% with price up")
                else:
                    result["oi_signal"] = "LONG_UNWINDING"
                    result["signals_hit"].append(f"Long unwinding: OI {oi_chg_pct:.0f}% with price down")

    except Exception as e:
        logger.debug("confirmation: futures OI check failed for %s: %s", symbol, e)

    # ── 3. Put-Call Ratio (fno_bhavcopy options chain) ───────────────
    try:
        pcr_row = await conn.fetchrow(
            """
            SELECT
                SUM(CASE WHEN option_type = 'PE' THEN open_interest ELSE 0 END) AS pe_oi,
                SUM(CASE WHEN option_type = 'CE' THEN open_interest ELSE 0 END) AS ce_oi,
                SUM(CASE WHEN option_type = 'PE' THEN change_in_oi  ELSE 0 END) AS pe_chg,
                SUM(CASE WHEN option_type = 'CE' THEN change_in_oi  ELSE 0 END) AS ce_chg
              FROM nidp.fno_bhavcopy
             WHERE ticker_symbol = $1
               AND as_of_date    = $2
               AND option_type  IN ('CE', 'PE')
            """,
            symbol, trade_date,
        )

        if pcr_row and pcr_row["ce_oi"] and float(pcr_row["ce_oi"]) > 0:
            pe_oi = float(pcr_row["pe_oi"] or 0)
            ce_oi = float(pcr_row["ce_oi"])
            pcr   = pe_oi / ce_oi
            result["put_call_ratio"] = round(pcr, 3)

            if pcr <= _PCR_VERY_BULLISH:
                result["pcr_signal"] = "VERY_BULLISH"
                score += 12
                result["signals_hit"].append(f"PCR {pcr:.2f} — strong call buildup (very bullish)")
            elif pcr <= _PCR_BULLISH:
                result["pcr_signal"] = "BULLISH"
                score += 6
                result["signals_hit"].append(f"PCR {pcr:.2f} — options bullish")
            elif pcr >= _PCR_VERY_BEARISH:
                result["pcr_signal"] = "VERY_BEARISH"
                result["signals_hit"].append(f"PCR {pcr:.2f} — heavy put buying (bearish)")
            elif pcr >= _PCR_BEARISH:
                result["pcr_signal"] = "BEARISH"
                result["signals_hit"].append(f"PCR {pcr:.2f} — put-heavy options")
            else:
                result["pcr_signal"] = "NEUTRAL"

            # Contrarian: extreme PCR > 1.5 can signal peak fear (buy the dip)
            if pcr >= 1.5:
                result["signals_hit"].append(f"PCR {pcr:.2f} — extreme fear, watch for reversal")

    except Exception as e:
        logger.debug("confirmation: PCR check failed for %s: %s", symbol, e)

    # ── 4. Sector strength (index_eod) ───────────────────────────────
    try:
        sector_row = await conn.fetchrow(
            "SELECT sector FROM nidp.sector_master WHERE symbol = $1 LIMIT 1", symbol
        )
        sector = (sector_row["sector"] if sector_row else None) or ""
        idx_name = _SECTOR_INDEX.get(sector.upper(), _DEFAULT_INDEX)
        result["sector_index"] = idx_name

        idx_row = await conn.fetchrow(
            """
            SELECT pct_change
              FROM nidp.index_eod
             WHERE index_name = $1
               AND as_of_date = $2
             LIMIT 1
            """,
            idx_name, trade_date,
        )

        if idx_row and idx_row["pct_change"] is not None:
            sec_ret = float(idx_row["pct_change"])
            result["sector_return_pct"] = round(sec_ret, 2)

            if sec_ret >= _SECTOR_STRONG:
                score += 12
                result["signals_hit"].append(f"Sector ({idx_name}) strong +{sec_ret:.1f}%")
            elif sec_ret >= _SECTOR_MODERATE:
                score += 6
                result["signals_hit"].append(f"Sector ({idx_name}) positive +{sec_ret:.1f}%")
            elif sec_ret <= -_SECTOR_STRONG:
                result["signals_hit"].append(f"Sector ({idx_name}) weak {sec_ret:.1f}%")

    except Exception as e:
        logger.debug("confirmation: sector check failed for %s: %s", symbol, e)

    result["confirmation_score"] = round(min(score, 100.0), 1)
    # Confirmed = at least 2 independent positive signals hit
    positive_signals = [s for s in result["signals_hit"]
                        if "weak" not in s.lower() and "bearish" not in s.lower()
                        and "unwinding" not in s.lower() and "short buildup" not in s.lower()]
    result["confirmed"] = len(positive_signals) >= 2

    return result
