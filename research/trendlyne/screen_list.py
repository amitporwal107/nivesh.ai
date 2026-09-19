"""Rule-based research screen of a stock list from cached Trendlyne data (bulk parameters + overview, news, events and
bulk/block deals). Every input comes through TLCache, so a re-run costs no calls while the cache is fresh.

This is a transparent points screen (quality, growth, ownership, valuation, trend) plus red flags. It is NOT a validated
trading model and makes no return claim.

usage: python screen_list.py UNIVERSE_CSV(code,name,rank) OUT_DIR [--as-of YYYY-MM-DD]
"""
import argparse
import datetime as dt
import html
import json
import os
import re

import pandas as pd

import tl_cache as T
from tl_client import TLClient

P50 = ["roea", "rocea", "debtcea", "rev4qq", "npqgrowth", "prompct", "fiihold", "instihold", "pettm", "currentprice",
       "cvolday", "cvol30dayavg", "mcapq", "rev1a", "npagrowth", "npttmgrowth", "npq", "totalsrq", "mfhold", "prompct1q",
       "fiipct1q", "instipct1q", "mfpct1q", "prompledge", "pegttm", "peavg5y", "buysellpettmp", "psttm", "ltdea", "roica",
       "daychangep", "monthchangep", "yearchangep", "ltpyearhighdiff", "yearhigh", "delivery30dayavg", "delivery5dayavg",
       "rsi", "adx", "atr", "tldurabilitymetric", "tlvaluationmetric", "absscore", "prevclose", "freefloatmcapq", "rev1qq",
       "ni1qq", "roeaave3", "netdebta", "changep3yr"]
P2 = ["sma20", "sma50", "sma200", "macd", "macdsignal", "todaychangesgoldencross", "todaychangesdeathcross", "mfi",
      "beta1y", "weekchangep", "cvolhighest3m", "insideronlysellqtr", "insideronlysellmonthplustoday",
      "insidersellweekplustoday", "opmpctq", "opmpctttm", "opmpctqmy1", "op4qq", "epsttmgrowth", "epsyoygrowth", "ica",
      "pitroskif", "altmanzscore", "pbva", "pcfoa", "priceupcurpevspeavg5yp", "rev3a", "ni3a", "sloanratioamy1",
      "prompct4q", "fiipct4q", "mfpct4q", "prompledge1q", "delivery6mavg", "halfyrhigh", "changep2yr",
      "insideronlybuymonthplustoday", "insideronlybuyqtr", "insiderbuymonthplustoday", "dividendyield1yr",
      "dividendpayout", "ltpyearlowdiff", "insideronlybuyweekplustoday"]


def section(text: str, name: str) -> str:
    m = re.search(rf"^{name}:\n((?:[ \t]+.*\n?)*)", text, re.M)
    return m.group(1) if m else ""


def pipe_rows(block: str) -> list[dict]:
    rows, hdr = [], None
    for l in block.splitlines():
        if "|" not in l:
            continue
        cells = [x.strip() for x in l.strip().split("|")]
        if hdr is None:
            hdr = cells
        elif len(cells) == len(hdr):
            rows.append(dict(zip(hdr, cells)))
    return rows


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_views(c: "T.TLCache", code: str, today: dt.date) -> dict:
    out = {}
    ov = c.overview(code, "overview")
    a = section(ov, "asmData")
    m = re.search(r"text:\s*(.*)", a)
    out["asm"] = m.group(1).strip() if m and m.group(1).strip() else ""
    m = re.search(r"checklistP:\s*([\d.]+)", ov)
    out["checklist_pct"] = round(float(m.group(1)), 1) if m else None
    b = section(ov, "brokerSummaryData")
    for k in ("broker_covered", "broker_avg_target", "broker_average_upside"):
        m = re.search(rf"{k}:\s*(\S+)", b)
        out[k] = f(m.group(1)) if m else None
    news = pipe_rows(section(c.overview(code, "news"), "newsList"))
    recent = [n for n in news if n.get("pubDate", "")[:10] >= str(today - dt.timedelta(days=10))]
    out["news_recent"] = [(n["pubDate"][:10], n.get("title", ""), n.get("source", ""), n.get("url", "")) for n in recent[:3]]
    ev = c.overview(code, "events")
    isdate = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    bm = [r for r in pipe_rows(section(ev, "boardMeeting")) if isdate.match(r.get("board_meet_date", ""))]
    upcoming = sorted((r["board_meet_date"], r.get("purpose", "")) for r in bm if r["board_meet_date"] >= str(today))
    out["next_board_meeting"] = upcoming[0] if upcoming else None
    dv = [r for r in pipe_rows(section(ev, "dividend")) if isdate.match(r.get("exdate", ""))]
    out["last_dividend"] = (dv[0]["exdate"], dv[0].get("amount")) if dv else None
    deals = section(c.ownership(code, "bulblockdeal"), "tableData")
    rows = [json.loads(x) for x in re.findall(r"\[[^\[\]]*\]", deals)]
    cut = str(today - dt.timedelta(days=30))
    rec = [r for r in rows if len(r) >= 7 and str(r[3]) >= cut]
    out["deals_30d_buy"] = sum(1 for r in rec if "Purchase" in str(r[2]) or "Buy" in str(r[2]))
    out["deals_30d_sell"] = sum(1 for r in rec if "Sell" in str(r[2]))
    out["deals_30d"] = [f"{r[3]} {r[2]} {r[0][:40]} {r[6]}%" for r in rec[:4]]
    return out


def score(r: dict) -> tuple[int, dict, list]:
    g = lambda k: f(r.get(k))
    pts = {"quality": 0, "growth": 0, "ownership": 0, "valuation": 0, "trend": 0}
    roe, roce, de, pio, icr = g("roea"), g("rocea"), g("debtcea"), g("pitroskif"), g("ica")
    pts["quality"] = sum([bool(roe and roe >= 15), bool(roce and roce >= 15), bool(de is not None and de <= 0.5),
                          bool(pio and pio >= 6), bool((icr and icr >= 3) or (de is not None and de < 0.05))])
    rev, npg, opm, opm4, ni3 = g("rev4qq"), g("npqgrowth"), g("opmpctq"), g("opmpctqmy1"), g("ni3a")
    pts["growth"] = sum([bool(rev and rev >= 15), bool(npg and npg >= 20), bool(opm is not None and opm4 is not None and opm > opm4),
                         bool(ni3 and ni3 >= 15)])
    pl, dfii, dmf, dinst, pr1 = g("prompledge"), g("fiipct1q"), g("mfpct1q"), g("instipct1q"), g("prompct1q")
    ib, isq = g("insideronlybuyqtr") or 0, g("insideronlysellqtr") or 0
    pts["ownership"] = sum([bool(pl is not None and pl <= 1), bool(any(x and x > 0 for x in (dfii, dmf, dinst))),
                            bool(ib >= isq and (pr1 is None or pr1 >= 0))])
    peg, pe, pe5, vs = g("pegttm"), g("pettm"), g("peavg5y"), g("tlvaluationmetric")
    pts["valuation"] = sum([bool(peg and 0 < peg <= 1.5), bool(pe and pe5 and 0 < pe <= pe5), bool(vs and vs >= 40)])
    ltp, s50, s200, hi, dlv = g("currentprice"), g("sma50"), g("sma200"), g("ltpyearhighdiff"), g("delivery30dayavg")
    pts["trend"] = sum([bool(ltp and s50 and s200 and ltp > s50 > s200), bool(hi is not None and 0 <= hi <= 10), bool(dlv and dlv >= 40)])
    flags = []
    if r.get("asm"):
        flags.append("ASM: " + r["asm"])
    if (pl and pl > 10) or (g("prompledge1q") or 0) > 0:
        flags.append(f"pledge {pl}% (QoQ {g('prompledge1q')})")
    if pr1 is not None and pr1 <= -1:
        flags.append(f"promoter holding {pr1:+.2f}pp QoQ")
    if (g("npq") is not None and g("npq") < 0) or (npg is not None and npg < 0):
        flags.append(f"profit falling/loss (qtr PAT {g('npq')}, YoY {npg}%)")
    if de and de > 1.5:
        flags.append(f"debt/equity {de}")
    if g("altmanzscore") is not None and g("altmanzscore") < 1.8:
        flags.append(f"Altman Z {g('altmanzscore')}")
    if g("rsi") and g("rsi") > 80:
        flags.append(f"RSI {g('rsi')} (overbought)")
    if isq > ib:
        flags.append(f"insiders sold {int(isq):,} > bought {int(ib):,} shares (qtr; includes inter-se transfers)")
    val = (g("cvol30dayavg") or 0) * (ltp or 0) / 1e7
    if not ltp or g("cvol30dayavg") is None:
        flags.append("no price/volume data in Trendlyne")
    elif val < 2:
        flags.append(f"illiquid (~Rs {val:.1f} cr/day)")
    nb = r.get("next_board_meeting")
    if nb and nb[0] <= str(r["_today"] + dt.timedelta(days=10)):
        flags.append(f"board meeting {nb[0]} ({nb[1]})")
    return sum(pts.values()), pts, flags


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("universe")
    ap.add_argument("out_dir")
    ap.add_argument("--as-of", default=str(dt.datetime.now(T.IST).date()))
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.as_of)
    U = pd.read_csv(a.universe)
    c = T.TLCache(TLClient(), T.RedisStore())
    bulk = c.get_params(U.code.tolist(), P50 + P2)
    rows = []
    for _, u in U.iterrows():
        r = {"rank": u["rank"], "name": u["name"], "code": u["code"], "_today": today, **bulk.get(u["code"].upper(), {})}
        r.update(parse_views(c, u["code"], today))
        total, pts, flags = score(r)
        r.update(score=total, **{f"pts_{k}": v for k, v in pts.items()}, flags="; ".join(flags), n_flags=len(flags))
        r["daily_value_cr"] = round((f(r.get("cvol30dayavg")) or 0) * (f(r.get("currentprice")) or 0) / 1e7, 2)
        rows.append(r)
    D = pd.DataFrame(rows).drop(columns=["_today"]).sort_values(["score", "n_flags"], ascending=[False, True])
    os.makedirs(a.out_dir, exist_ok=True)
    D.to_csv(os.path.join(a.out_dir, "screen.csv"), index=False)
    cols = ["rank", "name", "code", "score", "pts_quality", "pts_growth", "pts_ownership", "pts_valuation", "pts_trend",
            "roea", "rocea", "debtcea", "rev4qq", "npqgrowth", "prompct", "fiihold", "instihold", "pettm", "pegttm",
            "rsi", "ltpyearhighdiff", "daily_value_cr", "flags"]
    tbl = D[cols].to_html(index=False, escape=True, na_rep="")
    news = "".join(f"<h3>{html.escape(str(r['name']))} ({r['code']})</h3><ul>" +
                   "".join(f"<li>{d} — <a href='{html.escape(u)}'>{html.escape(t)}</a> ({html.escape(s)})</li>" for d, t, s, u in r["news_recent"]) +
                   "</ul>" for _, r in D.iterrows() if r["news_recent"])
    open(os.path.join(a.out_dir, "screen.html"), "w").write(
        f"<html><head><meta charset='utf-8'><title>Trendlyne screen {today}</title><style>body{{font-family:sans-serif;margin:16px}}"
        f"table{{border-collapse:collapse;font-size:12px}}td,th{{border:1px solid #ccc;padding:3px 5px}}</style></head><body>"
        f"<h1>Research screen, {len(D)} stocks, {today}</h1><p>Rule-based points screen from cached Trendlyne data (internal use only; "
        f"prices are Trendlyne's latest snapshot). Not a validated trading model.</p>{tbl}<h2>Recent news (10 days)</h2>{news}</body></html>")
    print(json.dumps(c.stats, default=list), "| calls today", c.calls_today())


if __name__ == "__main__":
    main()
