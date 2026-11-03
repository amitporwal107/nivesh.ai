"""Which dashboard widgets flagged today's movers early (3 Nov 2026), from replay_today.py's flags.csv / days.csv.

Owner's rule: a MOVER is a stock whose intraday range (high − low) reached 5 % of its open. Its MARK is the first minute the
running range reached 5 %. A widget's flag is EARLY when the step it came from used only minutes before the mark
(step end ≤ mark minute); LEAD = mark − step end, in minutes. DIRECTION: up when the day's low came before its high.
ROOM LEFT = the move still ahead after the first early flag, in the move's direction: up = (highest high after the flag −
price at the flag) ÷ price at the flag; down = (price at the flag − lowest low after) ÷ price at the flag.
HIT RATE = of the stocks a widget listed while their range was still under 5 %, the share that became movers; LIFT = that ÷
the share of movers among all stocks of the widget's universe that traded today. One session only: indicative, not tested.
LIQUID = 20-session average volume ≥ 50,000 and previous close ≥ ₹20 (the filter of session fffb64a1's 30-session study).

Runs inside the backend container (reads the 1-minute candles for the room-left figures). Writes OUT/report.md, OUT/*.csv.
"""
import csv
import json
import os
import statistics as st
import sys
from collections import defaultdict

import numpy as np

OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/replay_20261103/out"
MINUTES = "/tmp/replay_20261103/minutes.jsonl"
OPEN_MIN = 9 * 60 + 15
N_MIN = 375


def hhmm(m):
    t = OPEN_MIN + int(m)
    return f"{t // 60:02d}:{t % 60:02d}"


def med(xs):
    return st.median(xs) if xs else None


def pct(x, dp=1):
    return "–" if x is None else f"{x:.{dp}f}%"


days = {}
for r in csv.DictReader(open(os.path.join(OUT, "days.csv"))):
    if r["skipped"] == "1":
        continue
    r["range_pct"] = float(r["range_pct"])
    r["mark"] = int(r["range5_min"]) if r["range5_min"] != "" else None
    r["up"] = int(r["high_min"]) > int(r["low_min"]) or (r["high_min"] == r["low_min"] and float(r["close"]) >= float(r["open"]))
    r["liquid"] = float(r["avg_vol20"] or 0) >= 50000 and float(r["prev_close"] or 0) >= 20
    days[r["symbol"]] = r
movers = {s for s, r in days.items() if r["mark"] is not None}

# 1-minute highs / lows for the room-left figures (movers only)
hl = {}
for ln in open(MINUTES):
    x = json.loads(ln)
    s = x.get("s")
    if s in movers and s not in hl and x.get("b"):
        h = np.full(N_MIN, np.nan)
        lo = np.full(N_MIN, np.nan)
        for b in x["b"]:
            m = int(b[0][11:13]) * 60 + int(b[0][14:16]) - OPEN_MIN
            if 0 <= m < N_MIN:
                h[m], lo[m] = b[2], b[3]
        hl[s] = (h, lo)


def room(s, t_end, price):
    h, lo = hl[s]
    if days[s]["up"]:
        after = np.nanmax(h[t_end:]) if t_end < N_MIN and np.isfinite(h[t_end:]).any() else np.nan
        return (after - price) / price * 100 if np.isfinite(after) else None
    after = np.nanmin(lo[t_end:]) if t_end < N_MIN and np.isfinite(lo[t_end:]).any() else np.nan
    return (price - after) / price * 100 if np.isfinite(after) else None


# first listing per (widget, stock), and every step's listings
first = {}                                    # (dash, widget) -> {symbol: (step_min, price)}
title = {}
at_step = defaultdict(lambda: defaultdict(set))   # symbol -> step -> {(dash, widget)}
for r in csv.DictReader(open(os.path.join(OUT, "flags.csv"))):
    s = r["symbol"]
    if s not in days:
        continue
    k = (r["dashboard"], r["widget"])
    title[k] = r["title"]
    t = int(r["step_min"])
    f = first.setdefault(k, {})
    if s not in f or t < f[s][0]:
        f[s] = (t, float(r["price"]))
    at_step[s][t].add(k)

UNIVERSE = {}                                  # widget -> fno | nifty50 | cash, from where it listed stocks
for k, f in first.items():
    syms = list(f)
    if syms and all(days[s]["fno"] == "1" for s in syms):
        UNIVERSE[k] = "fno"
    else:
        UNIVERSE[k] = "cash"
for k in first:
    if k[1] == "n50_gainers":
        UNIVERSE[k] = "nifty50"


def universe_of(kind, liquid_only):
    out = set()
    for s, r in days.items():
        if liquid_only and not r["liquid"]:
            continue
        if kind == "fno" and r["fno"] != "1":
            continue
        if kind == "nifty50" and r["nifty50"] != "1":
            continue
        out.add(s)
    return out


def widget_rows(liquid_only):
    rows = []
    for k, f in first.items():
        uni = universe_of(UNIVERSE[k], liquid_only)
        base = len(movers & uni) / len(uni) if uni else 0
        cand = [s for s, (t, _) in f.items() if s in uni and (s not in movers or t <= days[s]["mark"])]
        hits = [s for s in cand if s in movers]
        early = [(s, f[s][0], f[s][1]) for s in hits]
        leads = [days[s]["mark"] - t for s, t, _ in early]
        rooms = [x for x in (room(s, t, p) for s, t, p in early) if x is not None]
        ups = sum(1 for s, *_ in early if days[s]["up"])
        hr = len(hits) / len(cand) if cand else None
        rows.append({"dashboard": k[0], "widget": k[1], "title": title[k], "universe": UNIVERSE[k],
                     "listed": len([s for s in f if s in uni]), "listed_under_5": len(cand), "early_movers": len(hits),
                     "up_movers": ups, "hit_rate": hr, "base_rate": base,
                     "lift": (hr / base) if (hr is not None and base) else None,
                     "lead_med": med(leads), "room_med": med(rooms)})
    rows.sort(key=lambda r: (-(r["lift"] or 0), -r["early_movers"]))
    return rows


BROAD = {("daytrade", "dt_multiyear")}       # lists every large or liquid stock by definition: not a signal in a combination


def combo_rows(liquid_only, ks=(2, 3, 4), skip=frozenset()):
    out = []
    uni = universe_of("cash", liquid_only)
    base = len(movers & uni) / len(uni)
    for need in ks:
        cand, hits, leads, rooms = [], [], [], []
        for s in uni:
            steps = sorted(t for t, ws in at_step[s].items() if len(ws - skip) >= need)
            ok = [t for t in steps if s not in movers or t <= days[s]["mark"]]
            if not ok:
                continue
            cand.append(s)
            if s in movers:
                hits.append(s)
                t = ok[0]
                leads.append(days[s]["mark"] - t)
                price = None
                for r in csv_price.get((s, t), []):
                    price = r
                    break
                if price:
                    x = room(s, t, price)
                    if x is not None:
                        rooms.append(x)
        hr = len(hits) / len(cand) if cand else None
        label = f"{need} or more widgets (either dashboard) at the same step" + (
            " — Multiyear breakout not counted" if skip else "")
        out.append({"label": label, "listed_under_5": len(cand),
                    "early_movers": len(hits), "hit_rate": hr, "base_rate": base, "lift": hr / base if hr else None,
                    "lead_med": med(leads), "room_med": med(rooms)})
    return out


csv_price = defaultdict(list)
for r in csv.DictReader(open(os.path.join(OUT, "flags.csv"))):
    csv_price[(r["symbol"], int(r["step_min"]))].append(float(r["price"]))

lines = []
P = lines.append
n_all, n_liq = len(days), sum(1 for r in days.values() if r["liquid"])
mv_liq = [s for s in movers if days[s]["liquid"]]
P("# Replay of 3 Nov 2026 — which scan-dashboard widgets flagged today's movers early")
P("")
P(f"**Movers (owner's rule: intraday range ≥ 5 % of the open):** {len(movers)} of {n_all} stocks that traded "
  f"({sum(1 for s in movers if days[s]['up'])} up, {sum(1 for s in movers if not days[s]['up'])} down); "
  f"liquid: {len(mv_liq)} of {n_liq} ({sum(1 for s in mv_liq if days[s]['up'])} up).")
marks = [days[s]["mark"] for s in mv_liq]
P(f"Liquid movers reached the 5 % range at a median {hhmm(med(marks)) if marks else '–'} IST; "
  f"{sum(1 for m in marks if m < 15)} of them inside the first 15 minutes (often a gap at the open).")
P("")
for liquid_only, head in ((True, "Liquid stocks (20-day average volume ≥ 50,000, price ≥ ₹20)"), (False, "All stocks")):
    P(f"## {head}")
    P("")
    P("| Dashboard | Widget | Universe | Listed | Listed under 5 % | Early movers (up) | Hit rate | Base rate | Lift | "
      "Lead (median) | Room left after flag (median) |")
    P("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in widget_rows(liquid_only):
        hit = pct(r["hit_rate"] * 100 if r["hit_rate"] is not None else None)
        lift = "–" if r["lift"] is None else format(r["lift"], ".2f") + "×"
        lead = "–" if r["lead_med"] is None else format(r["lead_med"], ".0f") + " min"
        P(f"| {r['dashboard']} | {r['title']} | {r['universe']} | {r['listed']} | {r['listed_under_5']} | "
          f"{r['early_movers']} ({r['up_movers']}) | {hit} | {pct(r['base_rate'] * 100)} | {lift} | {lead} | "
          f"{pct(r['room_med'])} |")
    P("")
    P("| Several widgets at once | Listed under 5 % | Early movers | Hit rate | Base rate | Lift | Lead (median) | Room left (median) |")
    P("|---|---:|---:|---:|---:|---:|---:|---:|")
    for r in combo_rows(liquid_only) + combo_rows(liquid_only, skip=BROAD):
        P(f"| {r['label']} | {r['listed_under_5']} | {r['early_movers']} | "
          f"{pct(r['hit_rate'] * 100 if r['hit_rate'] is not None else None)} | {pct(r['base_rate'] * 100)} | "
          f"{'–' if r['lift'] is None else format(r['lift'], '.2f') + '×'} | "
          f"{'–' if r['lead_med'] is None else format(r['lead_med'], '.0f') + ' min'} | {pct(r['room_med'])} |")
    P("")

# per-mover table (liquid), largest range first
P("## Liquid movers: which widgets had them before the 5 % mark")
P("")
P("| Stock | Range | Direction | 5 % mark | First early widget(s) | Lead | Price at flag | Room left | All early widgets |")
P("|---|---:|---|---:|---|---:|---:|---:|---|")
per_mover = []
for s in sorted(mv_liq, key=lambda s: -days[s]["range_pct"]):
    d = days[s]
    early = sorted(((t, p, k) for k, f in first.items() if s in f for t, p in [f[s]] if t <= d["mark"]))
    if early:
        t0 = early[0][0]
        firsts = sorted({title[k] for t, p, k in early if t == t0})
        allw = sorted({f"{title[k]} ({hhmm(t)})" for t, p, k in early})
        rm = room(s, t0, early[0][1])
        per_mover.append([s, d["range_pct"], "up" if d["up"] else "down", hhmm(d["mark"]), "; ".join(firsts),
                          d["mark"] - t0, early[0][1], rm, "; ".join(allw)])
        P(f"| {s} | {d['range_pct']:.1f}% | {'up' if d['up'] else 'down'} | {hhmm(d['mark'])} | {'; '.join(firsts)} | "
          f"{d['mark'] - t0} min | {early[0][1]:,.2f} | {pct(rm)} | {'; '.join(allw)[:300]} |")
    else:
        per_mover.append([s, d["range_pct"], "up" if d["up"] else "down", hhmm(d["mark"]), "", None, None, None, ""])
        P(f"| {s} | {d['range_pct']:.1f}% | {'up' if d['up'] else 'down'} | {hhmm(d['mark'])} | none | – | – | – | |")
P("")
open(os.path.join(OUT, "report.md"), "w").write("\n".join(lines) + "\n")
with open(os.path.join(OUT, "movers_liquid.csv"), "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["symbol", "range_pct", "direction", "mark_ist", "first_early_widgets", "lead_min", "price_at_flag",
                "room_left_pct", "all_early_widgets"])
    w.writerows(per_mover)
print("\n".join(lines[:60]))
