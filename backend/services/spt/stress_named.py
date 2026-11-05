"""The named stress scenarios of Paper Trading v2 › Portfolio risk (docs/scanner_paper_trading/UI_DESIGN_V2.md §2.04,
§4 item 4, §7), added to the existing GET /api/v1/risk/stress-test/{id} next to its three scenarios (services/spt/risk.
stress: gap_through_stop, sector_shock, market_shock), which are unchanged. Deterministic; every row states its
assumption. `loss_rs` is the loss in rupees (0 when the scenario gains), `pnl_rs` the signed figure.

THE BOOK these scenarios read (wider than the existing three, which read the open SPT entries only):
    cash   the open SPT entries and positions (risk.open_spt_book: quantity, entry, stop, sector) and the desk's open,
           entered paper share trades (quantity, entry price, stop, the sector the risk book holds for them)
    F&O    the desk's open paper F&O structures (services/spt/fno_structures), repriced on their own chain
SCENARIOS
    index_down        "Nifty -2%"            every share position falls 2 % (beta 1 ASSUMED: no beta source is wired),
                                             marked at the entry price, stops not triggered; each F&O structure takes its
                                             own "underlying −2 %" repricing
    sector_gap        "<Sector> gap -3%"     the sector holding the most share exposure opens 3 % lower; marked to market,
                                             stops not triggered; F&O not included (no sector is held for an underlying)
    correlated_stops  "Correlated stops hit" every share position in a pair with 60-day |ρ| ≥ 0.70
                                             (services/spt/correlation) exits at its stop together: quantity × (entry −
                                             stop) + round-trip costs; with no such pair nothing is counted, said so
    gap_beyond_stops  "Gap beyond stops +25%" every share position's stop is gapped through: it exits 25 % of its stop
                                             distance beyond the stop, + round-trip costs
    iv_up             "IV +10 pts (F&O)"      every F&O structure's options reprice at their implied volatility + 10
                                             points, the underlying unchanged
A row whose inputs are missing has loss_rs null and says why (`reason`); it is never estimated.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from services import desk_trading as desk

VERSION = "spt-stress-named-v1"
INDEX_MOVE_PCT = 2.0
SECTOR_GAP_PCT = 3.0
GAP_BEYOND_PCT = 25.0
IV_UP_PTS = 10.0


def _f(x: Any) -> Optional[float]:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x)


def _row(name: str, label: str, pnl: Optional[float], assumption: str, **extra: Any) -> Dict[str, Any]:
    # + 0.0 turns a −0.0 (a zero loss) into 0.0, so the JSON never shows "-0.0"
    return {"name": name, "label": label, "pnl_rs": None if pnl is None else round(float(pnl), 2) + 0.0,
            "loss_rs": None if pnl is None else round(max(-float(pnl), 0.0), 2) + 0.0, "assumption": assumption, **extra}


def priced(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in rows if _f(r.get("quantity")) and _f(r.get("entry")) and _f(r.get("stop")) is not None]


def stop_loss(r: Dict[str, Any], beyond_pct: float = 0.0, model: Optional[Dict[str, Any]] = None) -> float:
    q, e, s = int(r["quantity"]), float(r["entry"]), float(r["stop"])
    dist = max(e - s, 0.0)
    exit_px = s - dist * beyond_pct / 100.0
    return q * dist * (1.0 + beyond_pct / 100.0) + desk.round_trip_cost(q, e, max(exit_px, 0.01), model or desk.COST_MODEL)


def named(cash: List[Dict[str, Any]], structures: Optional[List[Dict[str, Any]]], *,
          correlated: Optional[List[str]], fno_reason: Optional[str] = None, corr_reason: Optional[str] = None
          ) -> Dict[str, Any]:
    """{scenarios: [...], unpriced: [...]} (module docstring). `structures` = fno_structures rows (None = unreadable,
    `fno_reason` says why); `correlated` = the symbols in a |ρ| ≥ 0.70 pair (None = unknown, `corr_reason`). Pure."""
    rows = priced(cash)
    unpriced = [r.get("symbol") for r in cash if r not in rows]
    value = sum(int(r["quantity"]) * float(r["entry"]) for r in rows)
    fno = structures or []

    def fno_sum(key: str) -> Optional[float]:
        vals = []
        for s in fno:
            if key == "iv_up_10":
                vals.append((s.get("stress") or {}).get("iv_up_10_rs"))
            else:
                vals.append(next((x.get("pnl_rs") for x in s.get("scenarios") or [] if x.get("name") == key), None))
        return None if any(v is None for v in vals) else sum(vals)

    out: List[Dict[str, Any]] = []
    # index down
    cash_pnl = -value * INDEX_MOVE_PCT / 100.0
    f_idx: Optional[float] = None
    idx_reason: Optional[str] = None
    if structures is None:
        pnl: Optional[float] = None
        idx_reason = f"the F&O structures could not be read ({fno_reason or 'unknown'}); the share part alone is " \
                     f"shares_pnl_rs"
    elif not fno:
        pnl = cash_pnl
    else:
        f_idx = fno_sum("und_down_2")
        pnl = None if f_idx is None else cash_pnl + f_idx
        if f_idx is None:
            idx_reason = "an F&O structure could not be repriced (an option leg has no implied volatility)"
    out.append(_row("index_down", f"Nifty -{INDEX_MOVE_PCT:g}%", pnl,
                    f"Every share position falls {INDEX_MOVE_PCT:g}% with the index (beta 1 assumed: no beta source is "
                    "wired), marked at its entry price, stops not triggered; each F&O structure is repriced with its "
                    f"underlying {INDEX_MOVE_PCT:g}% lower at its own implied volatility.",
                    shares_pnl_rs=round(cash_pnl, 2) + 0.0, fno_pnl_rs=None if f_idx is None else round(f_idx, 2),
                    reason=idx_reason))
    # sector gap
    by_sector: Dict[str, float] = {}
    for r in rows:
        key = r.get("sector") or "unclassified"
        by_sector[key] = by_sector.get(key, 0.0) + int(r["quantity"]) * float(r["entry"])
    if by_sector:
        sector, sv = sorted(by_sector.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        out.append(_row("sector_gap", f"{sector} gap -{SECTOR_GAP_PCT:g}%", -sv * SECTOR_GAP_PCT / 100.0,
                        f"The sector with the most share exposure ({sector}, ₹{sv:,.2f}) opens {SECTOR_GAP_PCT:g}% lower; "
                        "marked to market, stops not triggered; F&O structures are not included.", sector=sector))
    else:
        out.append(_row("sector_gap", f"Sector gap -{SECTOR_GAP_PCT:g}%", 0.0,
                        "No open share position, so no sector exposure to gap.", sector=None))
    # correlated stops
    if correlated is None:
        out.append(_row("correlated_stops", "Correlated stops hit", None,
                        "Share positions whose 60-day returns correlate at |ρ| ≥ 0.70 all exit at their stops together.",
                        reason=corr_reason or "the correlation could not be worked out", symbols=[]))
    else:
        hit = [r for r in rows if str(r.get("symbol") or "").upper() in set(correlated)]
        out.append(_row("correlated_stops", "Correlated stops hit", -sum(stop_loss(r) for r in hit),
                        "Share positions whose 60-day returns correlate at |ρ| ≥ 0.70 with another open position all "
                        "exit at their stops together (quantity × (entry − stop) + round-trip costs)."
                        + ("" if hit else " No two open positions correlate that strongly, so nothing is counted."),
                        symbols=sorted({str(r.get("symbol")) for r in hit})))
    # gap beyond stops
    out.append(_row("gap_beyond_stops", f"Gap beyond stops +{GAP_BEYOND_PCT:g}%",
                    -sum(stop_loss(r, GAP_BEYOND_PCT) for r in rows),
                    f"Every share position's stop is gapped through and it exits {GAP_BEYOND_PCT:g}% of its stop distance "
                    "beyond the stop (a stop is not a guaranteed fill), plus round-trip costs."))
    # IV up
    if structures is None:
        out.append(_row("iv_up", f"IV +{IV_UP_PTS:g} pts (F&O)", None,
                        f"Every F&O structure's options reprice at implied volatility + {IV_UP_PTS:g} points.",
                        reason=fno_reason or "the F&O structures could not be read"))
    else:
        f_iv = fno_sum("iv_up_10")
        out.append(_row("iv_up", f"IV +{IV_UP_PTS:g} pts (F&O)", f_iv if fno else 0.0,
                        f"Every F&O structure's options reprice at implied volatility + {IV_UP_PTS:g} points, the "
                        "underlying unchanged." + ("" if fno else " No open F&O structure."),
                        reason="an option leg has no implied volatility" if fno and f_iv is None else None))
    return {"scenarios": out, "unpriced": unpriced, "version": VERSION,
            "book": {"share_rows": len(rows), "fno_structures": None if structures is None else len(fno),
                     "share_value_rs": round(value, 2)}}


async def desk_share_rows(db, user_id: str, book: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The desk's open, entered paper share trades as stress rows (sector from the risk book)."""
    from services import desk_strategy_trades as strat
    sectors = {p.get("trade_id"): p.get("sector") for p in (book or {}).get("positions") or []}
    sectors.update({e.get("trade_id"): e.get("sector") for e in (book or {}).get("reservations") or []})
    out = []
    for t in await db[desk.TRADES].find({"user_id": user_id, "status": "open"}).to_list(500):
        if t.get("kind") == strat.KIND:
            continue
        entered = (t.get("entry_status") or ("assumed" if (t.get("entry_rule") or "at_once") == "at_once" else None)) \
            in ("assumed", "reached")
        if not entered:
            continue
        out.append({"order_id": t.get("_id"), "symbol": t.get("symbol"), "sector": sectors.get(t.get("_id")),
                    "quantity": t.get("quantity"), "entry": _f(t.get("sim_entry_price")) or _f(t.get("entry_price")),
                    "stop": _f(t.get("stop_price")), "source": "desk paper share trade"})
    return out


async def _no_margin(db, underlying, legs, key):
    return None, "not read for the stress test"


async def gather(request: Any, db, user_id: str, state: Dict[str, Any], spt_rows: List[Dict[str, Any]], *, now
                 ) -> Dict[str, Any]:
    """Read the wider book (module docstring) and work the named scenarios out. Never raises for a source it cannot
    read: the scenario that needs it is null with the reason."""
    import logging
    from . import correlation, fno_structures
    log = logging.getLogger(__name__)
    cash = [dict(r, source=r.get("source") or "spt") for r in spt_rows]
    try:
        cash += await desk_share_rows(db, user_id, state.get("book") or {})
    except Exception as e:  # noqa: BLE001
        log.warning("stress named: desk share trades unreadable (%s)", type(e).__name__)
    extras = (state.get("config") or {}).get("extras") or {}
    structures: Optional[List[Dict[str, Any]]] = None
    fno_reason = None
    try:
        got = await fno_structures.read(request, db, user_id, now=now, equity=state.get("equity_rs"),
                                        limits={"fno_max_loss_pct": extras.get("fno_max_loss_pct"),
                                                "margin_util_pct": extras.get("margin_util_pct")},
                                        margin_fn=_no_margin)
        structures = got["structures"]
    except Exception as e:  # noqa: BLE001
        log.warning("stress named: F&O structures unreadable (%s)", type(e).__name__)
        fno_reason = f"the F&O structures could not be read ({type(e).__name__})"
    correlated: Optional[List[str]] = None
    corr_reason = None
    try:
        c = await correlation.read(db, user_id, now=now)
        correlated = sorted({p["a"] for p in c["concentrated_pairs"]} | {p["b"] for p in c["concentrated_pairs"]})
    except Exception as e:  # noqa: BLE001
        log.warning("stress named: correlation unreadable (%s)", type(e).__name__)
        corr_reason = f"the correlation could not be worked out ({type(e).__name__})"
    return named(cash, structures, correlated=correlated, fno_reason=fno_reason, corr_reason=corr_reason)
