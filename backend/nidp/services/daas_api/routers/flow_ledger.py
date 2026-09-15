"""FLOW LEDGER auto-fill — GET /v1/flows/ledger/{company,sector}/{name}.

The FLOW LEDGER scores FII/DII distribution from evidence streams that were typed in
by hand. This fills the fields NIDP can source and states, per stream, why the rest
are blank.

**It returns inputs, not a verdict.** The tracker's scoring — quarter weights, the
consistency bonus, the composite renormalised over filled weights — stays the single
implementation. A score computed here would be a second one to drift against, and the
tracker's maths is the part a user can already read.

**An unavailable stream returns a sentence, never a zero.** The tracker excludes
unfilled streams and renormalises, so a fabricated neutral would not just be wrong —
it would dilute the streams that are real.

Sourceable today (measured on nidp_staging 2026-08-19, after the NSE egress fix):
company S1/S2 (holdings QoQ), S4 (delivery), S6 (F&O); sector S3 (breadth), S4
(relative strength). Not sourceable: company S3 and S5, sector S1 and S2 — each
returns its reason.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api import flow_ledger as fl
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import envelope, jsonify

router = APIRouter(
    prefix="/flows",
    tags=["flow-ledger"],
    dependencies=[Depends(require_api_key)],
)

_DELIVERY_WINDOW_DAYS = 40   # ~28 sessions, enough for a 20-session baseline
_FNO_LOOKBACK_ROWS = 6       # ~5 sessions of near-month futures
_RS_WINDOW_DAYS = 92         # the tracker's stream is explicitly 3-month
_FPI_FORTNIGHTS = 8          # ~4 months; the tracker's streak caps at ~6
_DEAL_WINDOW_DAYS = 45       # ~30 trading sessions, the stream's own window


@router.get("/ledger/company/{symbol}",
            summary="Auto-fill the FLOW LEDGER's company streams from NIDP")
async def company_ledger(symbol: str) -> Dict[str, Any]:
    sym = symbol.strip().upper()
    if not sym or not sym.replace("&", "").replace("-", "").isalnum():
        raise HTTPException(status_code=400, detail=f"invalid symbol {symbol!r}")

    pool = await get_pool()
    async with pool.acquire() as conn:
        held = await conn.fetch(fl.HOLDINGS_SQL, sym)
        deliv = await conn.fetchrow(fl.DELIVERY_SQL, sym, _DELIVERY_WINDOW_DAYS)
        fno = await conn.fetch(fl.FNO_SQL, sym, _FNO_LOOKBACK_ROWS)
        deals = await conn.fetch(fl.DEALS_SQL, sym, _DEAL_WINDOW_DAYS)

    streams: List[Dict[str, Any]] = []
    inputs: Dict[str, Any] = {}

    # ── S1 / S2: quarterly holdings, newest first ───────────────────────────
    fii = fl.qoq_bps([r["fii_pct"] and float(r["fii_pct"]) for r in held])
    dii = fl.qoq_bps([r["dii_pct"] and float(r["dii_pct"]) for r in held])
    inputs["fiiQ"] = fl.as_field(fii)
    inputs["diiQ"] = fl.as_field(dii)
    quarters = [str(r["period_end"]) for r in held]

    if fii:
        streams.append(fl.stream(
            "S1", 30, "FII stake, quarterly", filled=True,
            evidence=f"{len(fii)} QoQ change(s) from {len(held)} filings "
                     f"({', '.join(quarters[:len(fii) + 1])})",
            source="nidp.shareholding_pattern"))
    else:
        streams.append(fl.stream(
            "S1", 30, "FII stake, quarterly", filled=False,
            reason=("Only one shareholding filing is on record for this symbol, and "
                    "one filing is a holding level, not a quarter-on-quarter move")))

    if any(v is not None for v in dii):
        streams.append(fl.stream(
            "S2", 15, "DII stake, quarterly", filled=True,
            evidence=f"{len([v for v in dii if v is not None])} QoQ change(s). "
                     "DII only — mf_pct is NULL in every row, so the mutual-fund "
                     "half of this stream has no data behind it",
            source="nidp.shareholding_pattern"))
    else:
        streams.append(fl.stream(
            "S2", 15, "DII stake, quarterly", filled=False,
            reason="No DII holding recorded across the available filings"))

    # ── S3: net FPI direction on the exchange deal lists ───────────────────
    fpi_rows = [r for r in deals if fl.is_fpi_house(r["client_name"])]
    buy_cr = sum(float(r["value_cr"] or 0) for r in fpi_rows if r["deal_type"] == "BUY")
    sell_cr = sum(float(r["value_cr"] or 0) for r in fpi_rows if r["deal_type"] == "SELL")
    code, net_cr, gross_cr = fl.deal_direction(buy_cr, sell_cr)

    if fpi_rows:
        inputs["deal"] = code
        # A staggered exit by one entity is the classic distribution footprint, which
        # is why the tracker has a separate flag for it — and it is detectable here:
        # the same house selling on more than one day.
        inputs["repeatSeller"] = any(
            r["deal_type"] == "SELL" and (r["days"] or 0) > 1 for r in fpi_rows)
        names = sorted({(r["client_name"] or "").strip().title()
                        for r in fpi_rows})[:3]
        streams.append(fl.stream(
            "S3", 20, "Bulk / block deals, 30 sessions", filled=True,
            evidence=f"FPI net {net_cr:+,.1f} cr on {gross_cr:,.1f} cr gross across "
                     f"{len(fpi_rows)} counterparty-side(s) — {', '.join(names)}"
                     f"{'…' if len(fpi_rows) > 3 else ''}",
            source="nidp.bulk_deals + nidp.block_deals"))
    elif deals:
        others = sorted({(r["client_name"] or "").strip().title() for r in deals})[:3]
        inputs["deal"] = ""
        streams.append(fl.stream(
            "S3", 20, "Bulk / block deals, 30 sessions", filled=False,
            reason=fl.BULK_DEAL_UNRECOGNISED + ", ".join(others)
                   + ("…" if len(deals) > 3 else "")))
    else:
        # Zero qualifying deals IS complete information — anything large enough to
        # matter must be disclosed — so this one is a real "no meaningful FII deals".
        inputs["deal"] = "n"
        streams.append(fl.stream(
            "S3", 20, "Bulk / block deals, 30 sessions", filled=True,
            evidence="No bulk or block deal disclosed for this symbol in the window",
            source="nidp.bulk_deals + nidp.block_deals"))

    streams.append(fl.stream("S5", 10, "MF monthly portfolios",
                             filled=False, reason=fl.MF_MONTHLY_LIMIT))

    # ── S4: delivery on down days ──────────────────────────────────────────
    base = deliv and deliv["baseline"]
    down = deliv and deliv["down_day"]
    if base is not None and down is not None and (deliv["down_days"] or 0) >= 3:
        inputs["delivBase"] = str(float(base))
        inputs["delivDown"] = str(float(down))
        streams.append(fl.stream(
            "S4", 15, "Delivery % on down days", filled=True,
            evidence=f"{float(down)}% on {deliv['down_days']} down days vs "
                     f"{float(base)}% across {deliv['sessions']} sessions",
            source="nidp.prices_eod"))
    else:
        inputs["delivBase"] = inputs["delivDown"] = ""
        n_down = (deliv["down_days"] if deliv else 0) or 0
        streams.append(fl.stream(
            "S4", 15, "Delivery % on down days", filled=False,
            reason=(f"Only {n_down} down day(s) with delivery data in the last "
                    f"{_DELIVERY_WINDOW_DAYS} days — too few to average against a "
                    "baseline")))

    # ── S6: near-month futures price + OI ──────────────────────────────────
    if len(fno) >= 2:
        newest, oldest = fno[0], fno[-1]
        quad = fl.fo_quadrant(
            float(newest["close_price"]) - float(oldest["close_price"]),
            int(newest["open_interest"]) - int(oldest["open_interest"]))
        inputs["fo"] = quad or ""
        streams.append(fl.stream(
            "S6", 10, "Stock F&O positioning", filled=True,
            evidence=f"near-month future over {len(fno)} sessions: close "
                     f"{float(oldest['close_price'])} to {float(newest['close_price'])}, "
                     f"OI {int(oldest['open_interest']):,} to "
                     f"{int(newest['open_interest']):,}",
            source="nidp.fno_bhavcopy"))
    else:
        inputs["fo"] = ""
        streams.append(fl.stream(
            "S6", 10, "Stock F&O positioning", filled=False,
            reason="Not in the F&O segment — only 215 symbols have stock futures"))

    # Fields NIDP cannot fill are returned empty so the caller can prefill the whole
    # form in one pass without having to know which keys were omitted.
    inputs.setdefault("deal", "")
    inputs.setdefault("repeatSeller", False)
    inputs["mf"] = ""

    return envelope([{
        "mode": "company",
        "name": sym,
        "inputs": inputs,
        "streams": streams,
        "filled_weight": sum(s["weight"] for s in streams if s["filled"]),
        "total_weight": sum(s["weight"] for s in streams),
    }], limit=1, offset=0, total=1, extra={"generated_from": "nidp"})


@router.get("/ledger/sector/{sector}",
            summary="Auto-fill the FLOW LEDGER's sector streams from NIDP")
async def sector_ledger(
    sector: str,
    as_of: Optional[str] = Query(None, description="feature date, default latest"),
) -> Dict[str, Any]:
    name = sector.strip()
    index_name = fl.SECTOR_INDEX.get(name)
    # Called directly — which is how this is verified against the real DB without
    # standing up HTTP — the unresolved FastAPI Query default arrives instead of
    # None and reaches asyncpg as a date parameter:
    #   AttributeError: 'Query' object has no attribute 'toordinal'
    # Anything that is not a non-empty string is not an as-of date.
    if not isinstance(as_of, str) or not as_of.strip():
        as_of = None

    pool = await get_pool()
    async with pool.acquire() as conn:
        feat_date = as_of or await conn.fetchval(
            f"SELECT MAX(as_of_date) FROM {fl.FEATURES}")
        breadth = await conn.fetchrow(fl.BREADTH_SQL, name, feat_date)
        fpi = await conn.fetch(fl.FPI_SECTOR_SQL, name, _FPI_FORTNIGHTS)
        idx_rows = []
        if index_name:
            idx_rows = await conn.fetch(
                fl.INDEX_RETURN_SQL, [index_name, fl.BENCHMARK_INDEX], _RS_WINDOW_DAYS)

    streams: List[Dict[str, Any]] = []
    inputs: Dict[str, Any] = {"ftDir": "", "ftN": "", "auc": "", "idx": "",
                              "breadth": "", "rs": ""}

    # ── S1: consecutive fortnights of FPI flow in one direction ────────────
    streak = fl.fortnight_streak([r["net_inv_inr_cr"] and float(r["net_inv_inr_cr"])
                                  for r in fpi])
    if streak:
        direction, count = streak
        inputs["ftDir"], inputs["ftN"] = direction, str(count)
        latest = fpi[0]
        streams.append(fl.stream(
            "S1", 35, "NSDL fortnightly FPI flows", filled=True,
            evidence=f"{count} consecutive fortnight(s) of "
                     f"{'inflow' if direction == 'in' else 'outflow'} to "
                     f"{latest['report_date']} "
                     f"(latest net {float(latest['net_inv_inr_cr']):+,.0f} cr, "
                     f"{len(fpi)} fortnights on record)",
            source="nidp.fpi_sector_auc"))
    else:
        streams.append(fl.stream(
            "S1", 35, "NSDL fortnightly FPI flows", filled=False,
            reason=fl.NSDL_NO_SECTOR if not fpi else fl.NSDL_TOO_SHORT))

    # ── S2: AUC change vs the sector index move over the same window ───────
    # The index move is mark-to-market; what is left after subtracting it is the
    # part FPIs actually bought or sold. Both legs must span the SAME dates or the
    # residual is just a window mismatch, so the index window is pinned to the
    # fortnight range rather than reusing the 3-month one from S4.
    auc_pct = idx_pct = None
    if len(fpi) >= 2 and index_name:
        auc_pct = fl.pct_return(fpi[0]["auc_inr_cr"], fpi[-1]["auc_inr_cr"])
        async with pool.acquire() as conn:
            idx_pct = await conn.fetchval(
                fl.INDEX_RETURN_BETWEEN_SQL, index_name,
                fpi[-1]["report_date"], fpi[0]["report_date"])
    if auc_pct is not None and idx_pct is not None:
        inputs["auc"], inputs["idx"] = str(auc_pct), str(round(float(idx_pct), 2))
        streams.append(fl.stream(
            "S2", 25, "AUC change vs index change", filled=True,
            evidence=f"FPI custody in {name} {auc_pct:+}% vs {index_name} "
                     f"{float(idx_pct):+.2f}% between {fpi[-1]['report_date']} and "
                     f"{fpi[0]['report_date']}",
            source="nidp.fpi_sector_auc + nidp.index_eod"))
    else:
        streams.append(fl.stream(
            "S2", 25, "AUC change vs index change", filled=False,
            reason=(fl.NSDL_NO_SECTOR if not fpi else
                    f"No Nifty sector index represents {name!r}, so the AUC move "
                    "cannot be separated from the market move"
                    if not index_name else fl.NSDL_TOO_SHORT)))

    # ── S3: constituent breadth ────────────────────────────────────────────
    ranked = (breadth and breadth["ranked"]) or 0
    measured = (breadth and breadth["measured"]) or 0
    if measured >= 5:
        inputs["breadth"] = str(int(breadth["fell"]))
        streams.append(fl.stream(
            "S3", 25, "Constituent breadth", filled=True,
            evidence=f"{breadth['fell']} of the top {ranked} by market cap saw FII "
                     f"stake fall QoQ ({measured} had two comparable filings)",
            source="nidp.shareholding_pattern + nidp.sector_master"))
    else:
        streams.append(fl.stream(
            "S3", 25, "Constituent breadth", filled=False,
            reason=(f"Only {measured} of this sector's top constituents have two "
                    "comparable filings — too few to read breadth from"
                    if ranked else f"No constituents found for sector {name!r}")))

    # ── S4: relative strength vs the benchmark ─────────────────────────────
    rets = {r["index_name"]: fl.pct_return(r["last_px"], r["first_px"])
            for r in idx_rows}
    sec_ret, bench_ret = rets.get(index_name or ""), rets.get(fl.BENCHMARK_INDEX)
    if sec_ret is not None and bench_ret is not None:
        inputs["rs"] = str(round(sec_ret - bench_ret, 2))
        streams.append(fl.stream(
            "S4", 15, "Relative strength vs Nifty, 3M", filled=True,
            evidence=f"{index_name} {sec_ret:+}% vs {fl.BENCHMARK_INDEX} "
                     f"{bench_ret:+}% over ~3 months",
            source="nidp.index_eod"))
    else:
        streams.append(fl.stream(
            "S4", 15, "Relative strength vs Nifty, 3M", filled=False,
            reason=(f"No Nifty sector index represents {name!r}"
                    if not index_name else
                    f"{index_name} has no closes in the last {_RS_WINDOW_DAYS} days")))

    return envelope([{
        "mode": "sector",
        "name": name,
        "index_used": index_name,
        "as_of": jsonify(feat_date),
        "inputs": inputs,
        "streams": streams,
        "filled_weight": sum(s["weight"] for s in streams if s["filled"]),
        "total_weight": sum(s["weight"] for s in streams),
    }], limit=1, offset=0, total=1, extra={"generated_from": "nidp"})


@router.get("/ledger/sectors", summary="Sectors the ledger can auto-fill")
async def sectors() -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT sector, COUNT(*) AS symbols FROM nidp.sector_master "
            "WHERE sector IS NOT NULL GROUP BY 1 ORDER BY 2 DESC")
    data = [{"sector": r["sector"], "symbols": r["symbols"],
             "index_used": fl.SECTOR_INDEX.get(r["sector"]),
             "relative_strength_available": r["sector"] in fl.SECTOR_INDEX}
            for r in rows]
    return envelope(data, limit=len(data), offset=0, total=len(data))
