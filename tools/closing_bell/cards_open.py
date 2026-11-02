"""Opening Bell — the morning edition's cards: everything about the previous session (cards.build on the
previous trading day's bundle), plus the morning's own figures, each computed here from data:

  lv    Nifty ranges and levels: India VIX one-day range, the nearest expiry's largest put / call open interest,
        put-call ratio, max pain, and on expiry day the at-the-money straddle (NIDP DaaS option chain, bhavcopy)
  imp   option-implied moves for F&O companies reporting today (at-the-money straddle / spot, nearest expiry)
  mcx   MCX crude oil and gold, last close vs the one before (TrueData end-of-day bars)
  pre   the 9:00-9:08 pre-open (NSE public pre-open data): indicated Nifty from its constituents' equilibrium
        prices weighted as on the desk, F&O breadth, biggest gaps, after-the-bell filers and the AI list's names

Owner decisions (2 Nov 2026): "anticipated moves" are data-based ranges and levels, never calls; no global cues.
usage: python3 cards_open.py BUNDLE.json OUT_cards.json [PREOPEN.json]
Pure standard library.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date
from typing import Any, Dict, List, Optional

import cards as C
from cards import r2, short_name

OPEN_TIME = "09:15"
MIN_N50_COVER = 45          # constituents with a pre-open price needed before an indicated Nifty is stated
FLAT_PCT = 0.10             # |indicated change| below this is read as a flat start


def chain_levels(ch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Support / resistance by open interest, put-call ratio, max pain and the ATM straddle for one chain."""
    rows = []
    spot = None
    for s in ch.get("strikes") or []:
        ce, pe = s.get("CE") or {}, s.get("PE") or {}
        spot = spot or ce.get("underlying_price") or pe.get("underlying_price")
        rows.append({"k": float(s["strike"]), "ce_oi": float(ce.get("open_interest") or 0), "pe_oi": float(pe.get("open_interest") or 0),
                     "ce": ce.get("close_price"), "pe": pe.get("close_price"),
                     "ce_chg": float(ce.get("change_in_oi") or 0), "pe_chg": float(pe.get("change_in_oi") or 0)})
    if not rows or not spot:
        return None
    spot = float(spot)
    ce_tot, pe_tot = sum(r["ce_oi"] for r in rows), sum(r["pe_oi"] for r in rows)
    below = [r for r in rows if r["k"] <= spot and r["pe_oi"] > 0]
    above = [r for r in rows if r["k"] >= spot and r["ce_oi"] > 0]
    if not below or not above or ce_tot <= 0:
        return None
    sup = max(below, key=lambda r: r["pe_oi"])
    res = max(above, key=lambda r: r["ce_oi"])
    pain = {r["k"]: sum(x["ce_oi"] * max(0.0, r["k"] - x["k"]) + x["pe_oi"] * max(0.0, x["k"] - r["k"]) for x in rows) for r in rows}
    mp = min(pain, key=lambda k: (pain[k], abs(k - spot)))
    atm = min(rows, key=lambda r: abs(r["k"] - spot))
    strad = (atm["ce"] + atm["pe"]) if atm["ce"] and atm["pe"] and atm["ce_oi"] > 0 and atm["pe_oi"] > 0 else None
    near = sorted([r for r in rows if abs(r["k"] - spot) <= spot * 0.04], key=lambda r: -(r["ce_oi"] + r["pe_oi"]))[:12]
    return {"spot": r2(spot), "expiry": ch.get("expiry"), "as_of": str(ch.get("as_of"))[:10],
            "sup": sup["k"], "sup_oi": sup["pe_oi"], "res": res["k"], "res_oi": res["ce_oi"],
            "pcr": r2(pe_tot / ce_tot), "max_pain": mp,
            "atm": atm["k"], "straddle": r2(strad), "straddle_pct": r2(strad / spot * 100, 1) if strad else None,
            "bars": [{"k": r["k"], "ce_oi": r["ce_oi"], "pe_oi": r["pe_oi"]} for r in sorted(near, key=lambda r: r["k"])]}


def mcx_line(bars: Any, prev: str) -> Optional[Dict[str, Any]]:
    if not isinstance(bars, list) or len(bars) < 2:
        return None
    bars = sorted(bars, key=lambda x: str(x.get("timestamp")))
    last, before = bars[-1], bars[-2]
    if str(last.get("timestamp"))[:10] != prev or not last.get("close") or not before.get("close"):
        return None
    pct = (last["close"] / before["close"] - 1) * 100
    return {"date": prev, "close": r2(last["close"], 0), "prev": r2(before["close"], 0), "prev_date": str(before.get("timestamp"))[:10], "pct": r2(pct)}


def build(b: Dict[str, Any], pre: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    op = b.get("open") or {}
    d, p = date.fromisoformat(op["date"]), date.fromisoformat(op["prev"])
    base = C.build(b)                                     # the previous session, as the Closing Bell reads it
    gaps: List[str] = list(base["gaps"])
    out = dict(base)
    L = C.labels(d, d, None)
    L.update({"list_date": base["L"]["list_date"], "prev_date": p.isoformat(), "prev_short": f"{p.day} {p:%b}",
              "prev_mid": f"{p:%a} {p.day} {p:%b} {p.year}", "prev_dow": f"{p:%A}", "prev_long": f"{p:%A}, {p.day} {p:%B} {p.year}"})
    out.update({"schema": "opening-bell-cards-v1", "kind": "opening", "date": d.isoformat(), "prev": p.isoformat(), "L": L,
                "open_time": OPEN_TIME})

    by = {x["name"]: x for x in base["idx"]}
    n50, vix = by.get("Nifty 50"), by.get("India VIX")

    # ---- ranges and levels (India VIX + the nearest Nifty expiry)
    lv: Dict[str, Any] = {}
    if n50 and vix and vix.get("close"):
        pts = n50["close"] * vix["close"] / 100 / math.sqrt(365)
        lv.update({"close": n50["close"], "vix": vix["close"], "pts": round(pts), "lo": round(n50["close"] - pts), "hi": round(n50["close"] + pts)})
    else:
        gaps.append("ranges: Nifty 50 or India VIX close missing")
    ch = (op.get("chains") or {}).get("NIFTY") or {}
    cl = chain_levels(ch) if isinstance(ch, dict) and not ch.get("_http") else None
    if cl and cl["as_of"] == p.isoformat():
        cl["expiry_today"] = cl["expiry"] == d.isoformat()
        lv["oi"] = cl
    else:
        gaps.append(f"option chain: NIFTY chain missing or not as of {p} (as of {(ch or {}).get('as_of')})")
    out["lv"] = lv

    # ---- option-implied moves for F&O companies reporting today
    names = {r["symbol"]: short_name(r.get("name"), r["symbol"]) for r in op.get("results_today") or []}
    imp = []
    for r in op.get("results_today") or []:
        c = (op.get("chains") or {}).get(r["symbol"])
        if not isinstance(c, dict) or c.get("_http"):
            continue
        x = chain_levels(c)
        if x and x["as_of"] == p.isoformat() and x["straddle_pct"]:
            imp.append({"sym": r["symbol"], "name": names[r["symbol"]], "expiry": x["expiry"], "spot": x["spot"], "atm": x["atm"],
                        "straddle": x["straddle"], "pct": x["straddle_pct"]})
    if imp:
        e0 = imp[0]["expiry"]
        imp = [x for x in imp if x["expiry"] == e0][:3]
    out["imp"] = imp
    out["due_today"] = [names[r["symbol"]] for r in op.get("results_today") or []]
    out["due_today_syms"] = [r["symbol"] for r in op.get("results_today") or []]
    if "results_today_source" in op and not op["results_today_source"]:
        gaps.append(f"results calendar for {d} unavailable (desk HTTP {op.get('results_today_http')}); results lines dropped")

    # ---- MCX overnight (TrueData)
    mx = op.get("mcx") or {}
    out["mcx"] = {"crude": mcx_line(mx.get("CRUDEOIL-I"), p.isoformat()), "gold": mcx_line(mx.get("GOLD-I"), p.isoformat())}
    if not out["mcx"]["crude"] or not out["mcx"]["gold"]:
        gaps.append("MCX crude/gold close for the previous session unavailable")

    # ---- the 9:08 pre-open
    out["pre"] = preopen_cards(b, base, pre, d, p) if pre else None
    if pre and out["pre"].get("problem"):
        gaps.append("pre-open: " + out["pre"]["problem"])
    out["gaps"] = gaps
    return out


def preopen_cards(b: Dict[str, Any], base: Dict[str, Any], pre: Dict[str, Any], d: date, p: date) -> Dict[str, Any]:
    if pre.get("date") != d.isoformat() and not pre.get("allow_stale"):
        return {"problem": f"NSE pre-open data is from {pre.get('date')} ({pre.get('timestamp')}), not {d}"}
    fo = {r["sym"]: r for r in pre.get("fo") or []}
    allr = {r["sym"]: r for r in pre.get("all") or []}
    if len(fo) < 150:
        return {"problem": f"only {len(fo)} F&O rows in the pre-open"}
    hm = b.get("heatmaps") or {}
    names: Dict[str, str] = {}
    for code in ("NIFTY500", "NIFTY50"):
        for s in (hm.get(code) or {}).get("stocks") or []:
            names.setdefault(s["symbol"], short_name(s.get("name"), s["symbol"]))
    for x in base["ideas"] + base["after"]:
        names[x["sym"]] = x["name"]
    nm = lambda s: names.get(s, s)

    out: Dict[str, Any] = {"time": pre.get("timestamp"), "hhmm": str(pre.get("timestamp") or "")[12:17], "date": pre.get("date"), "stale": pre.get("date") != d.isoformat(),
                           "adv": pre.get("fo_adv"), "dec": pre.get("fo_dec"), "unch": pre.get("fo_unch"), "n": len(fo)}
    # indicated Nifty: previous close x weighted equilibrium-price ratio of its constituents (desk heatmap weights)
    n50 = next((x for x in base["idx"] if x["name"] == "Nifty 50"), None)
    w = [(s["symbol"], s.get("weight_pct") or 0) for s in (hm.get("NIFTY50") or {}).get("stocks") or []]
    found = [(sym, wt, fo[sym]) for sym, wt in w if sym in fo and fo[sym]["prev"]]
    if n50 and len(found) >= MIN_N50_COVER and sum(wt for _, wt, _ in found) > 0:
        ratio = sum(wt * (r["iep"] / r["prev"] if r["iep"] else 1.0) for _, wt, r in found) / sum(wt for _, wt, _ in found)
        ind = n50["close"] * ratio
        out["nifty"] = {"ind": round(ind), "pct": r2((ratio - 1) * 100), "pts": round(ind - n50["close"]), "cover": len(found), "of": len(w),
                        "prev": n50["close"], "flat": abs((ratio - 1) * 100) < FLAT_PCT}
    else:
        return {"problem": f"only {len(found)} of {len(w)} Nifty 50 stocks have a pre-open price (need {MIN_N50_COVER})"}
    priced = [r for r in fo.values() if r["iep"] and r["prev"]]
    priced.sort(key=lambda r: -r["pct"])
    row = lambda r: {"sym": r["sym"], "name": nm(r["sym"]), "pct": r2(r["pct"]), "iep": r2(r["iep"]), "prev": r2(r["prev"])}
    out["ups"] = [row(r) for r in priced[:5] if r["pct"] > 0]
    out["dns"] = [row(r) for r in priced[::-1][:5] if r["pct"] < 0]
    out["after"] = [row(fo[x["sym"]]) for x in base["after"] if x["sym"] in fo and fo[x["sym"]]["iep"]][:4]
    out["ideas"] = []
    for x in base["ideas"]:
        r = fo.get(x["sym"]) or allr.get(x["sym"])
        if r and r["iep"] and r["prev"]:
            out["ideas"].append(dict(row(r), rank=x["rank"]))
    return out


if __name__ == "__main__":
    b = json.load(open(sys.argv[1]))
    pre = json.load(open(sys.argv[3])) if len(sys.argv) > 3 else None
    c = build(b, pre)
    json.dump(c, open(sys.argv[2], "w"), indent=1, ensure_ascii=False)
    print(json.dumps({"date": c["date"], "prev": c["prev"], "gaps": c["gaps"], "ideas": len(c["ideas"]), "imp": len(c["imp"]),
                      "levels": {k: v for k, v in (c["lv"].get("oi") or {}).items() if k != "bars"}, "pre": bool(c["pre"])}, ensure_ascii=False))
