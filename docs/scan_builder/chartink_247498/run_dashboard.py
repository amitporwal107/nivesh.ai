"""Chartink dashboard 247498 ("Atlas fresh") widgets computed on OUR data (read-only).

Runs inside the staging backend container with the committed scan_builder package copied to /tmp/ckraw/scan_builder.
Prices: NIDP warehouse NSE EOD bars (split/bonus adjusted) + today's Kite candle by the scan builder's rule.
Fundamentals: NIDP feature store (DaaS /stocks/screener). Quarterly/annual results: nidp.nse_financials_quarterly (fin.txt).
Writes /tmp/ckraw/out.json.
"""
import asyncio
import json
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np

import services
services.__path__.append("/tmp/ckraw")
from services.scan_builder import data as D, engine as E, spec as S, service as SV  # noqa: E402
from services.kite_live_feed import day_quote as dq  # noqa: E402

FIN_FIELDS = ["q_pat", "q1_pat", "q4_pat", "q_pbdt", "ttm_pat", "y_pat", "y_eps", "py_eps"]
for f in FIN_FIELDS:
    S.FUNDAMENTALS[f] = {"label": f, "unit": ""}


def read_fin(path):
    out = {}
    lines = Path(path).read_text().splitlines()
    head = [h.strip() for h in lines[0].split("|")]
    for ln in lines[2:]:
        parts = [p.strip() for p in ln.split("|")]
        if len(parts) != len(head):
            continue
        r = dict(zip(head, parts))
        def num(k):
            v = r.get(k) or ""
            try:
                return float(v)
            except ValueError:
                return math.nan
        def day(k):
            try:
                return date.fromisoformat(r.get(k) or "")
            except ValueError:
                return None
        q_end, q1_end, q4_end = day("q_end"), day("q1_end"), day("q4_end")
        rec = {k: num(k) for k in ("q_pat", "q1_pat", "q4_pat", "q_pbdt", "ttm_pat", "y_pat", "y_eps", "py_eps")}
        # only consecutive quarters count: 1 quarter ago must be ~3 months back, 4 quarters ago ~12 months back
        if not (q_end and q1_end and 80 <= (q_end - q1_end).days <= 100):
            rec["q1_pat"] = math.nan
        if not (q_end and q4_end and 355 <= (q_end - q4_end).days <= 375):
            rec["q4_pat"] = math.nan
            rec["ttm_pat"] = math.nan if not (q_end and q4_end) else rec["ttm_pat"]
        rec["q_end"] = q_end.isoformat() if q_end else None
        out[r["symbol"]] = rec
    return out


m, n, F, x = S.measure, S.number, S.fundamental, S.expr
CHG = x(m("close"), "-", m("close", 1), "/", m("close", 1), "*", n(100))


def f(fid, left, op, right):
    return S.flt(fid, left, op, right)


def spec(name, universe, children, extra_groups=()):
    root = S.group("root", list(children) + list(extra_groups), universe=universe)
    s = {"version": 1, "name": name, "description": "", "filters": root, "columns": [
        {"id": "c_chg", "alias": "% Change", "enabled": True, "format": "pct", "expr": CHG},
        {"id": "c_price", "alias": "Price", "enabled": True, "format": "price", "expr": x(m("close"))},
        {"id": "c_vol", "alias": "Volume", "enabled": True, "format": "volume", "expr": x(m("volume"))}],
        "sort": {"column": "c_chg", "dir": "desc"}, "limit": 500}
    return S.validate(s)


W = []  # (chartink id, name, universe note, spec or None, not-applied conditions)

W.append(("2798275", "Low PE and High ROCE", spec("lowpe", "cash", [
    f("a", x(F("pe_ttm")), "lt", x(n(15))),
    f("b", x(F("roce_pct")), "gt", x(n(15))),
    f("c", x(F("ttm_pat")), "gt", x(n(20))),
    f("d", x(F("y_pat")), "gt", x(n(1000))),
    f("e", x(F("market_cap_cr")), "gt", x(n(10000))),
    f("g", x(F("q_pat")), "gt", x(n(100)))]), []))

W.append(("2774840", "Eps growth", spec("eps", "fno", [
    f("a", x(F("y_eps")), "gt", x(F("py_eps"))),
    f("b", x(F("q_pat")), "gt", x(F("y_pat"))),
    f("c", x(F("y_eps"), "/", F("py_eps")), "gt", x(n(1.5)))]), []))

W.append(("2850641", "Long Build Up (fresh)", None,
          ["[0] 1 hour ADX DI+(14) > DI-(14)", "[0] 1 hour ADX(14) > DI-(14)", "[0] 1 hour ADX(14) < DI+(14)"]))

W.append(("2556934", "Nifty 50 Top Gainers", spec("n50", "nifty50", [
    f("a", x(m("open")), "gt", x(m("close", 1))),
    f("c", x(m("volume")), "gt", x(n(200000))),
    f("e", x(m("rsi", period=14)), "gt", x(n(55)))]),
    ["latest close > [=1] 15 minute high (first 15-min candle)", "latest close > [0] 15 minute EMA(close, 21)"]))

W.append(("2750391", "Copy - supertrend rsi scan", spec("st", "cash", [
    f("c", x(m("rsi", period=14)), "gt", x(n(50))),
    f("d", x(m("volume")), "gt", x(n(500000))),
    f("e", x(F("market_cap_cr")), "gt", x(n(5000))),
    f("g", x(F("y_eps"), "/", F("py_eps")), "gt", x(n(1.25))),
    f("h", x(F("roce_pct")), "gt", x(n(15))),
    f("i", x(F("market_cap_cr")), "gt", x(n(2000))),
    f("j", x(F("q_pbdt")), "gt", x(n(100)))]),
    ["[0] 15 minute Supertrend(7,3) < latest close", "[-1] 15 minute Supertrend(7,3) >= 1 day ago close"]))

W.append(("2737396", "Good quarter result stocks", spec("gq", "cash", [
    f("a", x(F("q_pat")), "gt", x(F("q1_pat"))),
    f("b", x(F("q_pat")), "gt", x(F("q4_pat"))),
    f("c", x(m("close")), "gt", x(n(50))),
    f("d", x(m("volume")), "gt", x(n(100000))),
    f("e", x(F("market_cap_cr")), "gt", x(n(400))),
    f("g", x(m("close")), "gt", x(m("ema", source="close", period=50))),
    f("h", x(m("rsi", period=14)), "gt", x(n(50))),
    f("i", x(m("close")), "gte", x(n(1.3), "*", m("min", tf="1w", source="low", period=52))),
    f("j", x(F("roce_pct")), "gt", x(n(15))),
    f("k", x(F("y_eps")), "gt", x(n(20))),
    f("l", x(F("debt_to_equity")), "lt", x(n(1)))]), []))

W.append(("2653943", "10x volume first 5 min", None,
          ["[=1] 5 minute volume > [-1] 5 minute SMA(volume, 1000) × 10",
           "latest buyer-initiated trades / seller-initiated trades > 1"]))

W.append(("3072994", "Marketcap Advances % / Declines", "GROUPED_AD", []))
W.append(("3072995", "Positive vs Negative volumes (in lacs)", "GROUPED_VOL", []))
W.append(("3073022", "Index stats", "INDEX", []))

W.append(("2894893", "Triple bottom", spec("tb", "fno", [
    f("a", x(m("close")), "gt", x(m("ema", 50, source="close", period=40))),
    f("b", x(m("rsi", period=14)), "gt", x(n(50))),
    f("c", x(m("macd_line", slow=26, fast=12, signal=9)), "gt", x(m("macd_signal", slow=26, fast=12, signal=9))),
    f("d", x(m("adx", period=14)), "gt", x(n(20))),
    f("e", x(m("volume")), "gt", x(n(1.5))),
    S.group("g57960", [
        f("g1", x(m("volume")), "gt", x(m("sma", source="volume", period=50))),
        f("g2", x(F("q_pbdt")), "gt", x(n(100)))])]), []))

W.append(("2750384", "RSI ABOVE 50 - DAILY, WEEKLY AND MONTHLY", spec("rsi", "cash", [
    f("a", x(m("rsi", period=14)), "gt", x(n(70))),
    f("b", x(m("rsi", tf="1w", period=14)), "gt", x(n(50))),
    f("c", x(F("market_cap_cr")), "gt", x(n(10000)))]), []))

W.append(("2804704", "Cup & Handle Pattern", spec("cup", "cash", [
    f("a", x(m("high", 7, tf="1M")), "lt", x(m("high", 6, tf="1M"))),
    f("b", x(m("high", 7, tf="1M")), "lt", x(m("high", 5, tf="1M"))),
    f("c", x(m("high", 5, tf="1M")), "lt", x(m("high", 4, tf="1M"))),
    f("d", x(m("high", 5, tf="1M")), "lt", x(m("high", 3, tf="1M"))),
    f("e", x(m("high", 3, tf="1M")), "gt", x(m("high", 2, tf="1M"))),
    f("g", x(m("high")), "gt", x(m("high", 6, tf="1M"))),
    f("h", x(m("volume")), "gt", x(n(100000)))]), []))

W.append(("3044849", "Open interest", spec("oi", "fno", [
    f("a", x(m("volume")), "gt", x(m("ema", source="close", period=10), "*", n(5))),
    S.group("or1", [
        f("b", x(m("close")), "gt", x(m("close", 1), "*", n(1.05))),
        f("c", x(m("close")), "lt", x(m("close", 1), "*", n(0.95)))], join="any")]), []))

W.append(("3072992", "TODAYS TOP BUY", spec("ttb", "cash", [
    f("a", x(m("volume")), "gt", x(m("sma", source="volume", period=20), "*", n(2))),
    f("b", x(F("market_cap_cr")), "gt", x(n(40))),
    f("c", x(m("close")), "gt", x(n(10))),
    f("d", x(m("close")), "lt", x(n(1000))),
    f("e", x(m("volume")), "gt", x(n(50000))),
    f("g", x(m("close")), "gt", x(m("sma", source="close", period=44))),
    f("h", x(m("macd_line", slow=26, fast=12, signal=9)), "gt", x(m("macd_signal", slow=26, fast=12, signal=9))),
    f("i", x(m("di_plus", period=14)), "gt", x(m("di_minus", period=14))),
    f("j", x(m("cci", period=20)), "gt", x(n(100))),
    f("k", x(m("cci", 1, period=20)), "lte", x(n(100))),
    f("l", x(m("supertrend", period=7, multiplier=3)), "lt", x(m("close"))),
    f("o", x(m("psar", start=0.02, increment=0.02, max=0.2)), "lt", x(m("close"))),
    f("p", x(m("adx", period=14)), "gt", x(n(25)))]),
    ["column BUY% ([0] 15 minute candle) — shown as n/a; Chartink sorts by it, we sort by DBUY"]))

W.append(("2807387", "long  tight consolidation stocks", spec("tight", "cash", [
    f("a", x(m("close")), "gte", x(m("high", 1))),
    f("b", x(m("close")), "gt", x(m("high"), "*", n(0.75))),
    f("c", x(m("max", tf="1w", source="close", period=4)), "lt", x(m("close"), "*", n(1.03))),
    f("d", x(m("min", tf="1w", source="close", period=4)), "gt", x(m("close"), "*", n(0.95))),
    f("e", x(m("max", tf="1w", source="open", period=4)), "lt", x(m("close"), "*", n(1.03))),
    f("g", x(m("min", tf="1w", source="open", period=4)), "gt", x(m("close"), "*", n(0.95))),
    f("h", x(F("market_cap_cr")), "gt", x(n(10000)))]), []))

W.append(("2854924", "OPEN INTEREST BUY7", spec("oib7", "fno", [
    f("a", x(m("volume")), "gt", x(m("ema", source="close", period=8), "*", n(5))),
    S.group("or1", [
        f("b", x(m("close")), "gt", x(m("close", 1), "*", n(1.012))),
        S.group("and2", [
            f("c", x(m("close")), "lt", x(m("close", 1), "*", n(0.98))),
            f("d", x(m("stoch_k", period=14)), "gt", x(n(30))),
            f("e", x(m("stoch_k", 1, period=14)), "lte", x(n(30))),
            f("g", x(m("volume")), "gt", x(n(400000))),
            f("h", x(m("adx", period=14)), "gt", x(n(42)))])], join="any")]), []))


def r2(v):
    return None if v is None or not np.isfinite(v) else round(float(v), 2)


async def main():
    fin = read_fin("/tmp/ckraw/fin.txt")
    data = D.ScanData(cache_dir=Path("/tmp/ckraw/cache"))
    base = await data.panel()
    ref = await data.reference()
    syms_all = list(base.symbols)
    overlay = await data.today(base, syms_all)
    panel = SV.assemble(base, list(range(len(syms_all))), overlay)
    last = panel.close[-1]
    eligible = np.isfinite(last)
    pos = {s: i for i, s in enumerate(panel.symbols)}
    N = len(panel.symbols)

    def mask(key):
        mk = np.zeros(N, dtype=bool)
        for s in SV.universe_symbols(key, base, ref):
            mk[pos[s]] = True
        return mk
    universes = {k: mask(k) for k in ("cash", "fno", "nifty50")}
    funds = {}
    for fld in ("pe_ttm", "roce_pct", "market_cap_cr", "debt_to_equity"):
        vals = ref.fundamentals.get(fld) or {}
        funds[fld] = np.array([vals.get(s, np.nan) for s in panel.symbols], dtype=float)
    for fld in FIN_FIELDS:
        funds[fld] = np.array([fin.get(s, {}).get(fld, np.nan) for s in panel.symbols], dtype=float)

    c0, c1 = panel.close[-1], panel.close[-2]
    v0, h0, l0 = panel.volume[-1], panel.high[-1], panel.low[-1]
    out = {"basis": {"mode": overlay.mode, "day": overlay.day.isoformat(), "eod_date": base.eod_date.isoformat(),
                     "quote_as_of": overlay.quote_as_of, "panel_source": data.panel_source,
                     "fundamentals_as_of": ref.fundamentals_as_of, "universe_cash": int(eligible.sum()),
                     "fno": int((universes["fno"] & eligible).sum()), "nifty50": int((universes["nifty50"] & eligible).sum()),
                     "fin_symbols": len(fin), "warnings": overlay.warnings},
           "widgets": []}

    # market-cap groups: SEBI/AMFI rank bands on the latest market cap
    mc = funds["market_cap_cr"]
    ranked = sorted((s for s in ref.fundamentals.get("market_cap_cr", {}) if np.isfinite(ref.fundamentals["market_cap_cr"][s])
                     and ref.fundamentals["market_cap_cr"][s] > 0), key=lambda s: -ref.fundamentals["market_cap_cr"][s])
    rank = {s: i + 1 for i, s in enumerate(ranked)}
    grp = np.array([(0 if rank.get(s, 10**9) <= 100 else 1 if rank.get(s, 10**9) <= 250 else 2) if s in rank else -1
                    for s in panel.symbols])
    labels = ["Largecap", "Midcap", "Smallcap"]
    up = eligible & (c0 > c1)
    dn = eligible & (c0 < c1)

    for wid, name, sp, missing in W:
        w = {"id": wid, "name": name, "not_applied": missing}
        if sp is None:
            w["status"] = "not_computed"
        elif sp == "GROUPED_AD":
            rows = []
            for g, lab in enumerate(labels):
                ing = eligible & (grp == g)
                k = int(ing.sum())
                rows.append({"Marketcap": lab, "Advances": r2(100.0 * (up & ing).sum() / k) if k else None,
                             "Declines": r2(100.0 * (dn & ing).sum() / k) if k else None, "_stocks": k})
            rows.sort(key=lambda r: -(r["Advances"] or -1))
            w.update(status="ok", columns=["Marketcap", "Advances", "Declines"], rows=rows)
        elif sp == "GROUPED_VOL":
            rows = []
            for g, lab in enumerate(labels):
                ing = eligible & (grp == g)
                pv = float(np.nansum(v0[up & ing])) / 1e5
                nv = float(np.nansum(v0[dn & ing])) / 1e5
                rows.append({"Marketcap": lab, "+-VOL": r2(pv - nv), "Positive volume": r2(pv), "Negative volume": r2(nv),
                             "_stocks": int(ing.sum())})
            rows.sort(key=lambda r: -(r["Positive volume"] or -1))
            w.update(status="ok", columns=["Marketcap", "+-VOL", "Positive volume", "Negative volume"], rows=rows)
        elif sp == "INDEX":
            names = ["NIFTY 50", "NIFTY BANK", "NIFTY FIN SERVICE", "NIFTY MID SELECT", "INDIA VIX"]
            q = await dq.day_quotes(names)
            short = {"NIFTY 50": "NIFTY", "NIFTY BANK": "BANKNIFTY", "NIFTY FIN SERVICE": "FINNIFTY",
                     "NIFTY MID SELECT": "MIDCPNIFTY", "INDIA VIX": "INDIA VIX"}
            rows = []
            for nm in names:
                qq = (q.get("quotes") or {}).get(nm)
                if not qq:
                    continue
                ltp, prev = qq.get("ltp"), qq.get("close")
                rows.append({"Symbol": short[nm], "Ltp": r2(ltp),
                             "% chg": r2((ltp - prev) / prev * 100) if ltp and prev else None})
            rows.sort(key=lambda r: -(r["Ltp"] or 0))
            w.update(status="ok", columns=["Symbol", "Ltp", "% chg"], rows=rows,
                     basis=f"{q.get('source')} {q.get('day')} as of {q.get('as_of')} why={q.get('why')}")
        else:
            res = E.evaluate(sp, panel, eligible=eligible, universes=universes, fundamentals=funds)
            rows = []
            for i, vals in zip(res["order"], res["values"]):
                s = panel.symbols[i]
                row = {"Symbol": s, "% Change": r2(vals[0]), "Price": r2(vals[1]), "Volume": int(vals[2]) if vals[2] is not None else None}
                rows.append(row)
            cols = ["Symbol", "% Change", "Price", "Volume"]
            if wid == "3072992":   # TODAYS TOP BUY columns
                from services.scan_builder import indicators as I  # noqa: F401
                extra = {"cci": E.evaluate(S.validate({**sp, "columns": [
                    {"id": "x1", "alias": "CCI", "enabled": True, "format": "number", "expr": x(m("cci", period=20))},
                    {"id": "x2", "alias": "ADX", "enabled": True, "format": "number", "expr": x(m("adx", period=14))},
                    {"id": "x3", "alias": "RSI", "enabled": True, "format": "number", "expr": x(m("rsi", period=14))},
                    {"id": "x4", "alias": "SMAV", "enabled": True, "format": "number", "expr": x(m("sma", source="volume", period=20))},
                    {"id": "x0", "alias": "%", "enabled": True, "format": "pct", "expr": CHG}],
                    "sort": {"column": "x0", "dir": "desc"}}), panel, eligible=eligible, universes=universes, fundamentals=funds)}["cci"]
                by = {panel.symbols[i]: vals for i, vals in zip(extra["order"], extra["values"])}
                rows = []
                for s, (cci, adx, rsi, smav, chg) in by.items():
                    i = pos[s]
                    rng = h0[i] - l0[i]
                    rows.append({"Symbol": s, "%": r2(chg), "Price": r2(c0[i]), "BUY%": "n/a",
                                 "DBUY": r2((c0[i] - l0[i]) / rng * 100) if rng > 0 else None,
                                 "V%": r2((v0[i] - smav) / smav * 100) if smav else None,
                                 "CCI": r2(cci), "ADX": r2(adx), "RSI": r2(rsi), "Volume": int(v0[i]),
                                 "EQUITY": r2(mc[i] / c0[i]) if np.isfinite(mc[i]) and c0[i] else None})
                rows.sort(key=lambda r: -(r["DBUY"] if r["DBUY"] is not None else -1))
                cols = ["Symbol", "%", "Price", "BUY%", "DBUY", "V%", "CCI", "ADX", "RSI", "Volume", "EQUITY"]
            w.update(status="partial" if missing else "ok", columns=cols, rows=rows,
                     counts=res["counts"])
        out["widgets"].append(w)
    Path("/tmp/ckraw/out.json").write_text(json.dumps(out, indent=1, default=str))
    print("ok", json.dumps(out["basis"], default=str))
    for w in out["widgets"]:
        print(w["id"], w["name"], w["status"], len(w.get("rows", [])))


asyncio.run(main())
