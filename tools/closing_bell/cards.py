"""Closing Bell — turn the night's data bundle into cards.json: every figure the graphics and the
script use, each computed here from the bundle (nothing typed by hand except labels).

usage: python3 cards.py BUNDLE.json OUT_cards.json
Pure standard library, so it runs on the host and in tests.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

INDEX_ORDER = ["Nifty 50", "Nifty Bank", "Nifty Next 50", "Nifty 100", "Nifty 200", "Nifty 500",
               "Nifty Midcap 150", "Nifty Smallcap 250", "Nifty Microcap 250", "India VIX"]
HEATMAP_KEYS = {"Nifty 50": "NIFTY50", "Nifty 100": "NIFTY100", "Nifty 200": "NIFTY200", "Nifty 500": "NIFTY500"}
ALIASES = {
    "Cholamandalam Investment and Finance Company": "Cholamandalam Finance",
    "Mahindra & Mahindra Financial Services": "M&M Financial",
    "One 97 Communications": "Paytm (One 97)",
    "Adani Ports and Special Economic Zone": "Adani Ports",
    "Mazagoan Dock Shipbuilders": "Mazagon Dock",
    "Mazagon Dock Shipbuilders": "Mazagon Dock",
    "Onesource Specialty Pharma": "OneSource",
    "Maruti Suzuki India": "Maruti Suzuki",
    "Info Edge (India)": "Info Edge",
    "Tata Consumer Products": "Tata Consumer",
    "Hindustan Unilever": "Hindustan Unilever",
    "Larsen & Toubro": "L&T",
    "Divi's Laboratories": "Divi's",
    "Bharti Airtel": "Bharti Airtel",
    "The Great Eastern Shipping Company": "GE Shipping",
    "The Great Eastern Shipping": "GE Shipping",
    "Sona BLW Precision Forgings": "Sona BLW",
    "Hindustan Aeronautics": "HAL",
    "Bharat Electronics": "BEL",
    "Adani Enterprises": "Adani Enterprises",
}


def short_name(name: Optional[str], sym: str) -> str:
    n = (name or sym).strip()
    if n.isupper() and len(n) > 4:
        n = " ".join(w if len(w) <= 3 else w.title() for w in n.split())
    n = re.sub(r"\s+(Ltd\.?|Limited)$", "", n, flags=re.I).strip()
    n = re.sub(r"\s+(Ltd\.?|Limited)$", "", n, flags=re.I).strip()
    n = ALIASES.get(n, n)
    for suffix in (" of India", " India", " Industries", " Company", " Corporation", " Laboratories", " Mobility",
                   " Systems", " Precision Forgings"):
        if len(n) > 15 and n.endswith(suffix):
            n = n[: -len(suffix)].strip()
    if len(n) > 24:  # long legal names: keep the first two words, never an ellipsis (it is read aloud)
        n = " ".join(n.split()[:2])
    return n


def labels(d: date, nxt: date, list_date: Optional[str]) -> Dict[str, str]:
    ld = date.fromisoformat(list_date) if list_date else None
    return {
        "date": d.isoformat(),
        "day_short": f"{d.day} {d:%b}",                       # 27 Oct
        "day_mid": f"{d:%a} {d.day} {d:%b} {d.year}",         # Tue 27 Oct 2026
        "day_long": f"{d:%A}, {d.day} {d:%B} {d.year}",       # Tuesday, 27 October 2026
        "top_date": f"{d:%a} {d.day} {d:%b} {d.year}".upper(),  # TUE 27 OCT 2026
        "title_date": f"{d:%A} · {d.day} {d:%B} {d.year}".upper(),
        "dow": f"{d:%A}",
        "month": f"{d:%B}",
        "next_date": nxt.isoformat(),
        "next_long": f"{nxt:%A} · {nxt.day} {nxt:%B} {nxt.year}",
        "next_title": f"{nxt:%A}, {nxt.day} {nxt:%B}",
        "next_short": f"{nxt:%a} {nxt.day} {nxt:%b}",
        "next_dow": f"{nxt:%A}",
        "list_date": f"{ld.day} {ld:%b}" if ld else "",
    }


def next_trading_day(d: date, holidays: List[str]) -> date:
    hol = set(holidays)
    n = d + timedelta(days=1)
    while n.weekday() >= 5 or n.isoformat() in hol:
        n += timedelta(days=1)
    return n


def r2(v: Optional[float], n: int = 2) -> Optional[float]:
    return None if v is None else round(float(v), n)


def build(b: Dict[str, Any]) -> Dict[str, Any]:
    d = date.fromisoformat(b["meta"]["date"])
    gaps: List[str] = []

    # ---- calendar
    holidays: List[str] = []
    events: List[dict] = []
    for m in (b.get("macro_calendar") or {}).values():
        if isinstance(m, dict) and not m.get("_http"):
            holidays += [h["date"] for h in m.get("holidays") or []]
            events += m.get("events") or []
    nxt = next_trading_day(d, holidays)

    # ---- indices (NIDP index_eod)
    by = {r["index_name"]: r for r in b.get("indices") or []}
    idx = [{"name": n, "close": r2(by[n]["close_price"]), "pts": r2(by[n]["pts_change"]), "pct": r2(by[n]["pct_change"])}
           for n in INDEX_ORDER if n in by]
    missing = [n for n in INDEX_ORDER if n not in by]
    if missing:
        gaps.append("index closes missing: " + ", ".join(missing))
    n50 = by.get("Nifty 50") or {}
    day = {k: r2(n50.get(f"{k}_price")) for k in ("open", "high", "low", "close")}

    # ---- movers per index (desk sector heatmap, end of day)
    movers: Dict[str, Any] = {}
    list_date = None
    for key, code in HEATMAP_KEYS.items():
        h = (b.get("heatmaps") or {}).get(code) or {}
        if h.get("_http") or not h.get("stocks"):
            gaps.append(f"heatmap {code} unavailable"); continue
        if str(h.get("as_of"))[:10] != d.isoformat():
            gaps.append(f"heatmap {code} is as of {h.get('as_of')}, not {d}")
        list_date = list_date or h.get("list_date")
        rows = [{"sym": s["symbol"], "name": short_name(s.get("name"), s["symbol"]), "pct": r2(s["returns"]["d"]),
                 "sector": s.get("sector"), "volx": r2(s.get("rel_volume"), 1)}
                for s in h["stocks"] if (s.get("returns") or {}).get("d") is not None]
        rows.sort(key=lambda r: r["pct"], reverse=True)
        secs: Dict[str, List[dict]] = {}
        for r in rows:
            secs.setdefault(r["sector"] or "Other", []).append(r)
        br = h.get("breadth") or {}
        movers[key] = {
            "index": key, "code": code, "n": len(rows),
            "adv": br.get("advances", sum(r["pct"] > 0 for r in rows)),
            "dec": br.get("declines", sum(r["pct"] < 0 for r in rows)),
            "top": rows[:5], "bottom": rows[::-1][:5],
            "sectors": [{"sector": k, "n": len(v), "adv": sum(x["pct"] > 0 for x in v),
                         "avg": r2(sum(x["pct"] for x in v) / len(v)),
                         "up": {"sym": v[0]["sym"], "name": v[0]["name"], "pct": v[0]["pct"]},
                         "dn": {"sym": v[-1]["sym"], "name": v[-1]["name"], "pct": v[-1]["pct"]}} for k, v in secs.items()],
        }

    # ---- rotation state (same rule as the desk matrix: vs the index's weighted change, 1W and 1M)
    rot = {"leading": [], "lagging": [], "index": None}
    h50 = (b.get("heatmaps") or {}).get("NIFTY50") or {}
    wc = h50.get("weighted_change") or {}
    if h50.get("sectors") and wc:
        rot["index"] = "Nifty 50"
        for s in h50["sectors"]:
            rr = s.get("returns") or {}
            if rr.get("w") is None or rr.get("m") is None:
                continue
            if rr["m"] > wc["m"] and rr["w"] > wc["w"]:
                rot["leading"].append(s["name"])
            elif rr["m"] < wc["m"] and rr["w"] < wc["w"]:
                rot["lagging"].append(s["name"])

    # ---- sector indices (desk Sector returns)
    sr = b.get("sector_returns") or {}
    brd = ((sr.get("in_sector_breadth") or {}).get("indices")) or {}
    sectors = []
    for s in sr.get("sectors") or []:
        if str(s.get("date"))[:10] != d.isoformat() or s.get("ret_1d_pct") is None:
            continue
        bb = brd.get(s["index"]) or {}
        sectors.append({"name": s["index"].replace("Nifty ", "").replace(" Index", ""), "index": s["index"],
                        "d1": r2(s["ret_1d_pct"]), "w1": r2(s.get("ret_1w_pct")), "m1": r2(s.get("ret_1m_pct")),
                        "adv": bb.get("advances"), "dec": bb.get("declines"), "n": bb.get("members")})
    sectors.sort(key=lambda x: -x["d1"])
    if not sectors:
        gaps.append("sector index returns for the day unavailable")

    # ---- results (desk Results week)
    rw = b.get("results_week") or {}
    rows = rw.get("results") or [] if not rw.get("_http") else []
    tl = b.get("trendlyne_profit") or {}

    def yoy(r: dict) -> Optional[float]:
        return (((r.get("components") or {}).get("trend") or {}).get("yoy_pct") or {}).get("pat")

    reacted = []
    for r in rows:
        re_ = r.get("reaction") or {}
        if re_.get("first_session") == d.isoformat() and re_.get("stock_return_pct") is not None:
            reacted.append({"sym": r["symbol"], "name": short_name(r.get("name"), r["symbol"]),
                            "pct": r2(re_["stock_return_pct"]), "volx": r2(re_.get("volume_x"), 1), "pat_yoy": r2(yoy(r), 1),
                            "fno": bool(r.get("fno")), "event_date": r.get("event_date")})
    # Broadcast the names viewers know: Nifty 500 members first, everything else only if too few.
    n500 = {s["sym"] for s in (movers.get("Nifty 500") or {}).get("top", [])} | {
        s["symbol"] for s in (((b.get("heatmaps") or {}).get("NIFTY500") or {}).get("stocks") or [])}
    pool = [x for x in reacted if x["sym"] in n500]
    up = sorted([x for x in pool if x["pct"] > 0], key=lambda x: -x["pct"])
    dn = sorted([x for x in pool if x["pct"] < 0], key=lambda x: x["pct"])
    if len(up) < 3:
        up += sorted([x for x in reacted if x["pct"] > 0 and x not in up], key=lambda x: -x["pct"])
    if len(dn) < 2:
        dn += sorted([x for x in reacted if x["pct"] < 0 and x not in dn], key=lambda x: x["pct"])
    res_up, res_dn = up[:5], dn[:4]

    after = []
    for r in rows:
        re_ = r.get("reaction") or {}
        if not (r.get("event_date") == d.isoformat() and r.get("fno") and r.get("status") == "declared"
                and (re_.get("filed_after_close") or re_.get("stock_return_pct") is None)):
            continue
        t = tl.get(r["symbol"]) if isinstance(tl.get(r["symbol"]), dict) else None
        pat = (((r.get("components") or {}).get("surprise") or {}).get("metrics") or {}).get("pat") or {}
        if t and t.get("yoy") is not None:
            after.append({"sym": r["symbol"], "name": short_name(r.get("name"), r["symbol"]), "filed": r.get("filed_at"),
                          "pat": r2(t["npq"]), "pat_prev": r2(t["npqmy1"]), "pat_yoy": r2(t["yoy"], 1), "source": "trendlyne"})
        elif yoy(r) is not None and pat.get("filed") is not None:
            after.append({"sym": r["symbol"], "name": short_name(r.get("name"), r["symbol"]), "filed": r.get("filed_at"),
                          "pat": r2(pat["filed"]), "pat_prev": None, "pat_yoy": r2(yoy(r), 1), "source": "desk"})
    after.sort(key=lambda x: -(x["pat"] or 0))
    after = after[:7]
    if tl.get("_error"):
        gaps.append("Trendlyne unavailable (" + str(tl["_error"])[:80] + "); after-the-bell profits use the desk's own figures")

    # ---- FII / DII (Sensibull daily cash; the desk's 3-month series for the long view)
    fd = b.get("fii_dii_daily") or {}
    days = sorted(k for k in fd if (fd[k] or {}).get("cash"))
    fii: Dict[str, Any] = {"available": False}
    if days:
        last = d.isoformat() if d.isoformat() in fd else max(k for k in days if k <= d.isoformat())
        c = fd[last]["cash"]
        net = lambda k, side: (fd[k]["cash"].get(side) or {}).get("buy_sell_difference")
        month_days = [k for k in days if k[:7] == d.isoformat()[:7] and k <= last]
        fii = {
            "available": True, "date": last, "same_day": last == d.isoformat(),
            "fii_net": r2(c["fii"]["buy_sell_difference"]), "fii_buy": r2(c["fii"]["buy"]), "fii_sell": r2(c["fii"]["sell"]),
            "dii_net": r2(c["dii"]["buy_sell_difference"]), "dii_buy": r2(c["dii"]["buy"]), "dii_sell": r2(c["dii"]["sell"]),
            "mtd_fii": r2(sum(net(k, "fii") for k in month_days), 1), "mtd_dii": r2(sum(net(k, "dii") for k in month_days), 1),
            "mtd_sessions": len(month_days), "month": f"{d:%B}",
            "last10": [{"d": k, "fii": round(net(k, "fii")), "dii": round(net(k, "dii"))} for k in [x for x in days if x <= last][-10:]],
        }
        # biggest since: the most recent earlier session at least as large on the same side
        today = fii["fii_net"]
        prior = [k for k in days if k < last]
        same_side = [k for k in prior if (net(k, "fii") >= today if today >= 0 else net(k, "fii") <= today)]
        since = max(same_side) if same_side else None
        gap = len([k for k in prior if since is None or k > since])
        fii["biggest_since"] = since if since and gap >= 10 else None
        fii["biggest_in_window"] = since is None and len(prior) >= 40
        fl = b.get("smart_money_flows") or {}
        fr = fl.get("rows") or []
        if fr:
            add = fr[-1]["date"] < last
            fii["m3_fii"] = round(fr[-1]["fii_cum_cr"] + (fii["fii_net"] if add else 0))
            fii["m3_dii"] = round(fr[-1]["dii_cum_cr"] + (fii["dii_net"] if add else 0))
            fii["m3_from"] = fr[0]["date"]
            fii["desk_flow_to"] = fr[-1]["date"]
        if not fii["same_day"]:
            gaps.append(f"FII/DII for {d} not published yet; using {last}")
    else:
        gaps.append("FII/DII daily figures unavailable")

    # ---- Top 10 ideas + F&O board (desk AI scanner list for D)
    aw = b.get("ai_watchlist") or {}
    ideas, fno, regime = [], [], {}
    if aw.get("list_date") == d.isoformat():
        for e in sorted(aw.get("cash") or [], key=lambda e: e.get("rank") or 99)[:10]:
            sc = e.get("scanner") or {}
            ideas.append({"rank": e.get("rank"), "sym": e["symbol"], "name": short_name(e.get("name"), e["symbol"]),
                          "close": r2(sc.get("close")), "why": (sc.get("reason") or "").split(";")[0].strip()})
        fx = aw.get("fno") or []
        rank = {"NIFTY": 0, "BANKNIFTY": 1}
        order = sorted(fx, key=lambda x: rank.get(x.get("underlying"), 2))
        for x in order[:5]:
            fno.append({"sym": x["underlying"], "label": x.get("name"), "structure": x.get("structure"), "expiry": x.get("expiry"),
                        "rr": r2(x.get("reward_risk")), "max_loss": r2(x.get("max_loss"), 0), "max_profit": r2(x.get("max_profit"), 0),
                        "view": x.get("view")})
        regime = (aw.get("notes") or {}).get("regime") or {}
    else:
        gaps.append(f"Top 10 list for {d} not stored")

    md = b.get("market_dashboard") or {}
    desk_regime = {"verdict": md.get("deploy_verdict"), "reason": md.get("verdict_reason"), "as_of": md.get("as_of_date")}

    # ---- what to watch next session
    nx = nxt.isoformat()
    macro = sorted([(e.get("time") or "", e.get("name") or e.get("short") or e.get("code"), {"H": "HIGH", "M": "MEDIUM"}.get(e.get("impact"), "LOW"),
                     e.get("country"), e.get("code"))
                    for e in events if (e.get("date_ist") or e.get("date")) == nx and e.get("impact") in ("H", "M")])[:4]
    due_rows = [r for r in rows if r.get("event_date") == nx]
    weight = {s["symbol"]: s.get("weight_pct") or 0 for s in (((b.get("heatmaps") or {}).get("NIFTY500") or {}).get("stocks") or [])}
    due_fno = sorted({r["symbol"]: r for r in due_rows if r.get("fno")}.values(), key=lambda r: -weight.get(r["symbol"], 0))
    due = [short_name(r.get("name"), r["symbol"]) for r in due_fno]
    due_syms = [r["symbol"] for r in due_fno]

    counts = rw.get("counts") or {}
    snap = b.get("market_snapshot") or {}
    return {
        "schema": "closing-bell-cards-v1", "date": d.isoformat(), "L": labels(d, nxt, list_date),
        "idx": idx, "day": day, "movers": movers, "sectors": sectors, "rotation": rot,
        "res_up": res_up, "res_dn": res_dn, "after": after, "after_source": "trendlyne" if any(a["source"] == "trendlyne" for a in after) else "desk",
        "counts": counts, "week": rw.get("week"), "fii": fii, "ideas": ideas, "fno": fno, "regime": regime, "desk_regime": desk_regime,
        "macro": [list(m) for m in macro], "due": due, "due_syms": due_syms, "due_count": len(due_rows),
        "market_breadth_all": {"adv": snap.get("advances_count"), "dec": snap.get("declines_count")},
        "gaps": gaps,
    }


if __name__ == "__main__":
    b = json.load(open(sys.argv[1]))
    c = build(b)
    json.dump(c, open(sys.argv[2], "w"), indent=1, ensure_ascii=False)
    print(json.dumps({"date": c["date"], "gaps": c["gaps"], "ideas": len(c["ideas"]), "after": len(c["after"]),
                      "res_up": [x["sym"] for x in c["res_up"]], "res_dn": [x["sym"] for x in c["res_dn"]]}, ensure_ascii=False))
