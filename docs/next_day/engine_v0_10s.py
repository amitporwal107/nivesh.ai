"""Next-Day Conviction Engine — rubric v0 with the owner's 7 Nov rule: every window ≤ 10 sessions, data ≤ one month.

Reads the CSV exports in this folder (e1..e7, staging NIDP warehouse, 8 Oct – 6 Nov 2026). Scores each of the last
11 sessions; the first 10 have a known next session (look-back), the last (6 Nov) is the prediction for 9 Nov.
Read-only analysis. Run: python3 -I engine.py <folder>
"""
import csv, json, math, sys, hashlib
from collections import defaultdict
from statistics import median, mean
from datetime import date

F = sys.argv[1]
SESS = "2026-10-08 2026-10-09 2026-10-12 2026-10-13 2026-10-14 2026-10-15 2026-10-16 2026-10-19 2026-10-21 2026-10-22 2026-10-23 2026-10-26 2026-10-27 2026-10-28 2026-10-29 2026-10-30 2026-11-02 2026-11-03 2026-11-04 2026-11-05 2026-11-06".split()
NEXT_AFTER_LAST = "2026-11-08"          # owner 7 Nov: Sunday 8 Nov Diwali special (Muhurat) session
FULL_AFTER_LAST = "2026-11-09"          # first full session after it (10 Nov is a holiday)
W = 10                                   # owner rule: 10-session windows
FUT_COST = 0.204                         # desk-cost-v2 futures round trip, % of Rs 1 lakh
DEL_COST = 0.370                         # desk-cost-v2 equity delivery round trip
IDX = {d: i for i, d in enumerate(SESS)}
def nxt(d): i = IDX[d]; return SESS[i + 1] if i + 1 < len(SESS) else NEXT_AFTER_LAST
def fnum(x): return None if x in ("", None) else float(x)

# ── load cash (raw + factor), adjust as of each symbol's last session in the window ──
raw = defaultdict(dict)
for r in csv.DictReader(open(f"{F}/e1.csv")):
    raw[r["symbol"]][r["as_of_date"]] = r
cash = {}
for s, rows in raw.items():
    last = max(rows); fl = float(rows[last]["cumulative_adj_factor"])
    out = {}
    for d, r in rows.items():
        k = float(r["cumulative_adj_factor"]) / fl
        out[d] = dict(o=float(r["open_price"]) * k, h=float(r["high_price"]) * k, l=float(r["low_price"]) * k,
                      c=float(r["close_price"]) * k, v=float(r["volume"]) / k, tv=float(r["turnover"]),
                      n=fnum(r["trades"]), dq=(fnum(r["deliv_qty"]) / k) if fnum(r["deliv_qty"]) is not None else None,
                      dp=fnum(r["deliv_pct"]), raw_o=float(r["open_price"]), raw_c=float(r["close_price"]))
    cash[s] = out
nifty = {r["as_of_date"]: float(r["close_price"]) for r in csv.DictReader(open(f"{F}/e2.csv"))}

# ── futures, consolidated per underlying ──
fut = defaultdict(lambda: defaultdict(list))
for r in csv.DictReader(open(f"{F}/e3.csv")):
    fut[r["ticker_symbol"]][r["as_of_date"]].append(r)
def fut_day(s, d):
    cs = fut.get(s, {}).get(d)
    if not cs: return None
    cs = sorted(cs, key=lambda r: r["expiry_date"])
    oi = sum(int(r["open_interest"] or 0) for r in cs); ch = sum(int(r["change_in_oi"] or 0) for r in cs)
    near = cs[0]
    pc = (float(near["close_price"]) / float(near["prev_close_price"]) - 1) * 100 if fnum(near["prev_close_price"]) else None
    # basis from the nearest contract with >= 3 calendar days to expiry
    bc = next((r for r in cs if (date.fromisoformat(r["expiry_date"]) - date.fromisoformat(d)).days >= 3), None)
    return dict(oi=oi, ch=ch, chp=(ch / (oi - ch) * 100) if oi - ch > 0 else None, pc=pc,
                vol=sum(int(r["traded_volume"] or 0) for r in cs), basis_c=bc)

# ── option series choice + PCR per (d, s, expiry) ──
pcr = {}
exps = defaultdict(set)
for r in csv.DictReader(open(f"{F}/e5.csv")):
    p, c = fnum(r["put_oi"]), fnum(r["call_oi"])
    pcr[(r["as_of_date"], r["ticker_symbol"], r["expiry_date"])] = (p / c) if p and c else None
    exps[(r["as_of_date"], r["ticker_symbol"])].add(r["expiry_date"])
series = {}
for (d, s), es in exps.items():
    ok = sorted(e for e in es if e > nxt(d))       # never a series expiring on d or the next session
    if ok: series[(d, s)] = ok[0]
opt = defaultdict(list)
with open(f"{F}/e4.csv") as fh:
    for r in csv.DictReader(fh):
        key = (r["as_of_date"], r["ticker_symbol"])
        if series.get(key) == r["expiry_date"]:
            opt[key].append((float(r["strike_price"]), r["option_type"], fnum(r["close_price"]), fnum(r["prev_close_price"]),
                             int(r["open_interest"] or 0), int(r["change_in_oi"] or 0), int(r["traded_volume"] or 0),
                             fnum(r["underlying_price"])))

# ── events (results / board meetings) and price bands ──
ev = defaultdict(list)
etypes = defaultdict(int)
for r in csv.DictReader(open(f"{F}/e6.csv")):
    etypes[r["event_type"]] += 1
    ev[r["symbol"]].append(r)
EVENT_TYPES = {"quarterly_results", "board_meeting", "results", "financial_results"}
def event_between(s, lo, hi, d):
    """results / board meetings dated after `lo` up to and including `hi` (weekend filings count), known by d 22:45"""
    cutoff = f"{d} 22:45"
    return [r for r in ev.get(s, []) if lo < r["event_date"] <= hi and r["event_type"].lower() in EVENT_TYPES
            and r["first_seen_at"][:16] <= cutoff]
band = {(r["as_of_date"], r["symbol"]): fnum(r["price_band_pct"]) for r in csv.DictReader(open(f"{F}/e7.csv"))}

# ── features ──
def feats(s, i):
    d = SESS[i]; x = cash[s]
    win = SESS[i - W:i + 1]
    if any(day not in x for day in win): return None
    b = [x[day] for day in win]                    # b[-1] = d, b[0] = d-10
    prev = b[:-1]
    cd, cp = b[-1], b[-2]
    for j in range(1, len(b)):
        if abs(b[j]["c"] / b[j - 1]["c"] - 1) > 0.25: return {"excluded": "one-day move > 25 % in window"}
    f = {}
    f["r"] = cd["c"] / cp["c"] - 1
    f["tvr"] = cd["tv"] / mean(p["tv"] for p in prev)
    f["clv"] = (cd["c"] - cd["l"]) / (cd["h"] - cd["l"]) if cd["h"] > cd["l"] else None
    ats_prev = [p["tv"] / p["n"] for p in prev if p["n"]]
    f["ats"] = (cd["tv"] / cd["n"]) / median(ats_prev) if cd["n"] and ats_prev else None
    dqs = [p["dq"] for p in prev if p["dq"] is not None]; dps = [p["dp"] for p in prev if p["dp"] is not None]
    f["de"] = cd["dq"] / median(dqs) if cd["dq"] is not None and dqs and median(dqs) > 0 else None
    f["dpc"] = cd["dp"] - median(dps) if cd["dp"] is not None and dps else None
    f["dp3"] = cd["c"] / b[-4]["c"] - 1
    base = [p["dq"] for p in b[:-3] if p["dq"] is not None]
    last3 = [p["dq"] for p in b[-3:] if p["dq"] is not None]
    f["dd3"] = mean(last3) / median(base) - 1 if base and len(last3) == 3 and median(base) > 0 else None
    med = median(dqs) if dqs else None
    f["k3_bull"] = sum(1 for j in (-3, -2, -1) if med and b[j]["dq"] and b[j]["dq"] > med and b[j]["c"] > b[j - 1]["c"])
    f["k3_bear"] = sum(1 for j in (-3, -2, -1) if med and b[j]["dq"] and b[j]["dq"] > med and b[j]["c"] < b[j - 1]["c"])
    n0, n5, n10 = nifty[d], nifty[SESS[i - 5]], nifty[SESS[i - 10]]
    f["rs5"] = (cd["c"] / b[-6]["c"] - 1) - (n0 / n5 - 1)
    f["rs10"] = (cd["c"] / b[0]["c"] - 1) - (n0 / n10 - 1)
    f["sma10"] = mean(p["c"] for p in b[1:]); f["sma5"] = mean(p["c"] for p in b[-5:]); f["sma5_prev"] = mean(p["c"] for p in b[-10:-5])
    f["hi10"] = max(p["h"] for p in prev); f["hi5"] = max(p["h"] for p in prev[-5:])
    f["lo10"] = min(p["l"] for p in prev); f["lo5"] = min(p["l"] for p in prev[-5:])
    f["roc5"] = cd["c"] / b[-6]["c"] - 1
    up = sum(b[j]["v"] for j in range(1, len(b)) if b[j]["c"] > b[j - 1]["c"]); tot = sum(b[j]["v"] for j in range(1, len(b)))
    f["u10"] = up / tot if tot else None
    trs = [max(b[j]["h"] - b[j]["l"], abs(b[j]["h"] - b[j - 1]["c"]), abs(b[j]["l"] - b[j - 1]["c"])) for j in range(1, len(b))]
    f["atr10"] = mean(trs); f["c"] = cd["c"]; f["raw_c"] = cd["raw_c"]
    f["med_tv"] = median(p["tv"] for p in prev)
    return f

def fno_feats(s, i):
    d = SESS[i]
    days = [fut_day(s, SESS[j]) for j in range(i - W, i + 1)]
    if days[-1] is None or days[-1]["chp"] is None or days[-1]["pc"] is None: return None
    t = days[-1]; g = {}
    g["fut_pc"] = t["pc"]; g["oi_chp"] = t["chp"]; g["oi"] = t["oi"]
    if abs(t["pc"]) >= 0.3 and abs(t["chp"]) >= 1.0:
        g["label"] = {(True, True): "long_buildup", (False, True): "short_buildup", (True, False): "short_covering",
                      (False, False): "long_unwinding"}[(t["pc"] > 0, t["chp"] > 0)]
    else:
        g["label"] = "neutral"
    ois = [x["oi"] for x in days[-10:] if x]
    g["oi_pct"] = sum(1 for o in ois if o <= t["oi"]) / len(ois) if len(ois) >= 8 else None
    ch = [x["chp"] if x else None for x in days[-3:]]
    g["accel"] = (None not in ch and ((ch[2] > ch[1] > ch[0] > 0) or (ch[2] < ch[1] < ch[0] < 0)))
    vols = [x["vol"] for x in days[:-1] if x]
    g["fvr"] = t["vol"] / mean(vols) if vols and mean(vols) > 0 else None
    def basis(x, day):
        if not x or not x["basis_c"] or day not in cash[s]: return None
        bc = x["basis_c"]; S0 = cash[s][day]["raw_c"]
        dd = (date.fromisoformat(bc["expiry_date"]) - date.fromisoformat(day)).days
        return (float(bc["close_price"]) - S0) / S0 * 365 / dd * 100
    bs = [basis(days[k], SESS[i - W + k]) for k in range(len(days))]
    prevb = [v for v in bs[-6:-1] if v is not None]
    g["dbasis"] = bs[-1] - mean(prevb) if bs[-1] is not None and prevb else None
    # options: nearest series that does not expire on d or the next session
    e = series.get((d, s)); rows = opt.get((d, s), [])
    g["series"] = e; g["put_write"] = g["call_unwind"] = g["call_write"] = g["put_unwind"] = False
    if e and rows:
        und = next((r[7] for r in rows if r[7]), None)
        strikes = sorted({r[0] for r in rows})
        if und and strikes:
            k = min(range(len(strikes)), key=lambda q: abs(strikes[q] - und))
            below = set(strikes[max(0, k - 2):k + 1]); above = set(strikes[k:k + 3])
            live = [r for r in rows if r[6] > 0 and r[2] is not None and r[3] is not None]
            def agg(typ, ks):
                rs = [r for r in live if r[1] == typ and r[0] in ks]
                dOI = sum(r[5] for r in rs); w = sum(r[4] for r in rs)
                prem = sum((r[2] - r[3]) * r[4] for r in rs) / w if w else 0.0
                return dOI, prem, len(rs)
            pdoi, pprem, pn = agg("PE", below); cdoi, cprem, cn = agg("CE", above)
            g["put_write"] = pn > 0 and pdoi > 0 and pprem < 0
            g["call_unwind"] = cn > 0 and cdoi < 0
            g["call_write"] = cn > 0 and cdoi > 0 and cprem < 0
            g["put_unwind"] = pn > 0 and pdoi < 0
            g["atm"] = strikes[k]
        p0 = pcr.get((d, s, e)); p5 = pcr.get((SESS[i - 5], s, e))
        hist = [pcr.get((SESS[j], s, e)) for j in range(i - 9, i + 1)]; hist = [h for h in hist if h is not None]
        g["pcr"] = p0; g["dpcr5"] = (p0 - p5) if p0 is not None and p5 is not None else None
        g["pcr_pct"] = sum(1 for h in hist if h <= p0) / len(hist) if p0 is not None and len(hist) >= 5 else None
    return g

# ── rubric v0 (10-session variant) ──
def band_pts(v, bands):
    if v is None: return 0
    for lo, hi, p in bands:
        if lo <= v < hi: return p
    return 0
def score(f, g, side):
    up = side == "bull"; sgn = 1 if up else -1; dir_ok = (f["r"] > 0) if up else (f["r"] < 0)
    P = {}
    P["C1"] = band_pts(f["tvr"], [(1.3, 1.5, 4), (1.5, 2, 8), (2, 5, 12), (5, 1e9, 8)]) if dir_ok else 0
    a = f["r"] * 100 * sgn
    P["C2"] = band_pts(a, [(0.0000001, 1, 2), (1, 3, 4), (3, 5, 6), (5, 1e9, 3)])
    clv = f["clv"] if f["clv"] is None or up else 1 - f["clv"]
    P["C3"] = band_pts(clv, [(0.75, 9, 6), (0.5, 0.75, 3)])
    P["C4"] = band_pts(f["ats"], [(1.5, 1e9, 6), (1.2, 1.5, 3)]) if dir_ok else 0
    P["D1"] = band_pts(f["de"], [(2, 1e9, 7), (1.5, 2, 5), (1.2, 1.5, 2)]) if dir_ok else 0
    P["D2"] = band_pts(f["dpc"], [(10, 1e9, 5), (5, 10, 3), (0.0000001, 5, 1)]) if dir_ok else 0
    P["D3"] = 4 if f["dd3"] is not None and f["dd3"] > 0 and f["dp3"] * sgn > 0 else 0
    k3 = f["k3_bull"] if up else f["k3_bear"]; P["D4"] = {3: 4, 2: 2}.get(k3, 0)
    r5, r10 = f["rs5"] * sgn > 0, f["rs10"] * sgn > 0
    P["P1"] = 8 if r5 and r10 else 5 if r10 else 3 if r5 else 0
    P["P2"] = (3 if (f["c"] - f["sma10"]) * sgn > 0 else 0) + (3 if (f["sma5"] - f["sma10"]) * sgn > 0 else 0) + \
              (2 if (f["sma5"] - f["sma5_prev"]) * sgn > 0 else 0)
    if up: P["P3"] = 5 if f["c"] > f["hi10"] else 3 if f["c"] > f["hi5"] else 0
    else:  P["P3"] = 5 if f["c"] < f["lo10"] else 3 if f["c"] < f["lo5"] else 0
    P["P4"] = (2 if f["roc5"] * sgn > 0 else 0) + (2 if f["u10"] is not None and ((f["u10"] >= 0.6) if up else (f["u10"] <= 0.4)) else 0)
    if g is not None:
        lab = g["label"]
        P["F1"] = {"long_buildup": 8, "short_covering": 6}.get(lab, 0) if up else {"short_buildup": 8, "long_unwinding": 6}.get(lab, 0)
        f2 = 0
        if P["F1"]:
            build = lab in ("long_buildup", "short_buildup")
            if g["oi_pct"] is not None and ((g["oi_pct"] >= 0.8) if build else (g["oi_pct"] <= 0.2)): f2 += 2
            if g["accel"]: f2 += 3
        P["F2"] = f2
        fdir = (g["fut_pc"] > 0) if up else (g["fut_pc"] < 0)
        P["F3"] = (2 if fdir and g["fvr"] is not None and g["fvr"] >= 1.5 else 0) + (1 if g["dbasis"] is not None and g["dbasis"] * sgn > 0 else 0)
        P["F4"] = ((3 if g["put_write"] else 0) + (2 if g["call_unwind"] else 0)) if up else ((3 if g["call_write"] else 0) + (2 if g["put_unwind"] else 0))
        p = 0
        if g.get("dpcr5") is not None and ((g["dpcr5"] > 0 and f["r"] > 0) if up else (g["dpcr5"] < 0 and f["r"] < 0)): p += 2
        if g.get("pcr_pct") is not None and ((g["pcr_pct"] >= 0.6) if up else (g["pcr_pct"] <= 0.4)): p += 2
        P["F5"] = p
    return P

PILLARS = {"cash": (["C1", "C2", "C3", "C4"], 30), "delivery": (["D1", "D2", "D3", "D4"], 20),
           "price_volume": (["P1", "P2", "P3", "P4"], 25), "fno": (["F1", "F2", "F3", "F4", "F5"], 25)}
def classify(bull, bear, has_fno):
    states = {}
    for name, (keys, mx) in PILLARS.items():
        if name == "fno" and not has_fno: continue
        pb, pr = sum(bull[k] for k in keys), sum(bear[k] for k in keys)
        states[name] = "bull" if pb >= 0.5 * mx and pr < 0.25 * mx else "bear" if pr >= 0.5 * mx and pb < 0.25 * mx else "neutral"
    sv = list(states.values()); need = 3
    if "bull" in sv and "bear" in sv: cls = "conflict"
    elif sv.count("bull") >= need: cls = "aligned_bull"
    elif sv.count("bear") >= need: cls = "aligned_bear"
    else: cls = "unaligned"
    return states, cls

def trade_quality(f, s, d):
    atrp = f["atr10"] / f["c"] * 100
    q = 30 if 1 <= atrp <= 4 else 15 if 4 < atrp <= 6 else 0
    room_hi = f["hi10"]
    room = (room_hi - f["c"]) / f["atr10"] if room_hi > f["c"] else None
    q += 30 if room is None or room >= 2 else 15 if room >= 1 else 0
    q += 20 if f["med_tv"] >= 5e8 else 10 if f["med_tv"] >= 1e8 else 0
    n1 = nxt(d); n2 = SESS[IDX[n1] + 1] if n1 in IDX and IDX[n1] + 1 < len(SESS) else (FULL_AFTER_LAST if d == SESS[-1] else n1)
    evs = event_between(s, n1, n2, d)
    q += 0 if evs else 20
    return q, atrp, room

# ── run every scoring day ──
results = {}
for i in range(W, len(SESS)):
    d = SESS[i]; n1 = nxt(d)
    fno_names = {s for s in fut if SESS[i] in fut[s]}
    rows = []
    liq = []
    for s in cash:
        f = feats(s, i)
        if f is None: continue
        if "excluded" in f: rows.append(dict(sym=s, excluded=f["excluded"])); continue
        liq.append((f["med_tv"], s, f))
    liq.sort(reverse=True)
    cash_univ = {s for tv, s, f in liq[:500] if tv >= 1e8} - fno_names
    for tv, s, f in liq:
        uni = "FNO" if s in fno_names else "CASH" if s in cash_univ else None
        if not uni: continue
        bd = band.get((d, s))
        if bd in (2.0, 5.0): rows.append(dict(sym=s, uni=uni, excluded=f"price band {bd:g} %")); continue
        if event_between(s, d, n1, d): rows.append(dict(sym=s, uni=uni, excluded=f"results/board meeting by {n1}")); continue
        g = fno_feats(s, i) if uni == "FNO" else None
        if uni == "FNO" and g is None: rows.append(dict(sym=s, uni=uni, excluded="no futures data")); continue
        bull, bear = score(f, g, "bull"), score(f, g, "bear")
        k = 1 if uni == "FNO" else 100 / 75
        sb, sr = round(sum(bull.values()) * k, 1), round(sum(bear.values()) * k, 1)
        states, cls = classify(bull, bear, uni == "FNO")
        q, atrp, room = trade_quality(f, s, d)
        rows.append(dict(sym=s, uni=uni, bull=sb, bear=sr, cls=cls, states=states, bullP=bull, bearP=bear, tq=q,
                         atr_pct=round(atrp, 2), room_atr=None if room is None else round(room, 2), f=f, g=g))
    results[d] = rows

def lists(rows, uni, side):
    key = "bull" if side == "bull" else "bear"; cls = "aligned_" + side
    c = [r for r in rows if r.get("uni") == uni and "excluded" not in r and r["cls"] == cls and r[key] >= 75]
    c.sort(key=lambda r: (-r[key], -r["tq"], -r["f"]["med_tv"]))
    return c[:5]

def oc(s, day):
    x = cash.get(s, {}).get(day)
    return (x["raw_c"] / x["raw_o"] - 1) * 100 if x else None

json.dump({"etypes": etypes}, open(f"{F}/etypes.json", "w"))
out = {"sessions": SESS, "next_after_last": NEXT_AFTER_LAST, "days": {}}
for d, rows in results.items():
    n1 = nxt(d); day = {"next": n1}
    for uni in ("FNO", "CASH"):
        elig = [r for r in rows if r.get("uni") == uni and "excluded" not in r]
        uoc = [oc(r["sym"], n1) for r in elig]; uoc = [v for v in uoc if v is not None]
        umean = mean(uoc) if uoc else None
        for side in ("bull", "bear"):
            L = lists(rows, uni, side)
            items = []
            for r in L:
                o = oc(r["sym"], n1)
                items.append(dict(sym=r["sym"], score=r[side], tq=r["tq"], label=(r["g"] or {}).get("label"), oc=o))
            day[f"{uni}_{side}"] = items
        day[f"{uni}_univ_oc"] = umean; day[f"{uni}_n"] = len(elig)
        day[f"{uni}_excluded"] = sum(1 for r in rows if r.get("uni") == uni and "excluded" in r)
        al = [r for r in elig if r["cls"].startswith("aligned")]
        day[f"{uni}_aligned"] = {"bull": sum(1 for r in al if r["cls"] == "aligned_bull"), "bear": sum(1 for r in al if r["cls"] == "aligned_bear"),
                                 "conflict": sum(1 for r in elig if r["cls"] == "conflict")}
        # momentum-only baseline (M1): top 5 by RS10
        mom = sorted(elig, key=lambda r: -r["f"]["rs10"])[:5]
        mo = [oc(r["sym"], n1) for r in mom]; mo = [v for v in mo if v is not None]
        day[f"{uni}_mom_oc"] = mean(mo) if mo else None
        # score band check: all bull-aligned names, by band
        day[f"{uni}_closest"] = sorted(([r["sym"], r["bull"], r["cls"]] for r in elig), key=lambda x: -x[1])[:5]
    out["days"][d] = day
json.dump(out, open(f"{F}/run.json", "w"), indent=1, default=str)
# full detail for the prediction day
pred = [r for r in results[SESS[-1]] if "excluded" not in r]
json.dump(pred, open(f"{F}/pred_detail.json", "w"), default=str)
print("ok", len(results), "days;", "event types:", dict(etypes))
