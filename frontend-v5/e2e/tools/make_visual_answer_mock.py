# Usage: python3 e2e/tools/make_visual_answer_mock.py e2e/fixtures/visual-answer.mock.json
"""Writes frontend-v5/e2e/fixtures/visual-answer.mock.json: one visual-answer-v1 payload per Release-1 intent.
MOCK — not real data. Numbers are synthetic (a seeded random walk), shaped exactly per the contract."""
import json, math, random, sys, datetime as dt

random.seed(30)
OUT = sys.argv[1]
PLAN = "tp_2de66265bb4979a3"   # e2e/fixtures/contract-decision-card.json cash plan (ICICIBANK), so DecisionCardById resolves

def sessions(n, last="2026-10-29"):
    d = dt.date.fromisoformat(last); out = []
    while len(out) < n:
        if d.weekday() < 5: out.append(d.isoformat())
        d -= dt.timedelta(days=1)
    return out[::-1]

def walk(n, start, vol, drift=0.0, volume=1e7):
    bars, c = [], start
    for day in sessions(n):
        o = round(c * (1 + random.gauss(0, vol / 3)), 2)
        c = round(o * (1 + random.gauss(drift, vol)), 2)
        h = round(max(o, c) * (1 + abs(random.gauss(0, vol / 2))), 2)
        l = round(min(o, c) * (1 - abs(random.gauss(0, vol / 2))), 2)
        bars.append({"d": day, "o": o, "h": h, "l": l, "c": c, "v": int(volume * (0.6 + random.random()))})
    return bars

def ema(bars, n):
    k, out, e = 2 / (n + 1), [], None
    for i, b in enumerate(bars):
        e = b["c"] if e is None else b["c"] * k + e * (1 - k)
        out.append(round(e, 2) if i >= n - 1 else None)
    return out

def dq(sources, stale=False, missing=()):
    return {"sources": [{"name": n, "as_of": a, "status": s, "note": note} for n, a, s, note in sources], "stale": stale, "missing": list(missing)}

CAVEAT = "MOCK — not real data. Built from end-of-day data of 29 Oct 2026. Ideas to review, not recommendations; nothing is sent to a broker."
GEN = "2026-10-30T04:50:00+05:30"

nifty = walk(60, 22100, 0.007, 0.0006, 2.5e8)
last = nifty[-1]["c"]
sectors = [("Bank", 1.42), ("IT", -0.86), ("Auto", 0.64), ("Pharma", -0.12), ("FMCG", 0.03), ("Metal", 2.31),
           ("Realty", -1.95), ("Energy", 0.88), ("Media", -0.47), ("PSU Bank", 1.12)]
heat = {"type": "heatmap", "id": "sectors", "title": "Sectors on the day", "note": None, "unit": "%",
        "cells": [{"label": n, "value": v} for n, v in sectors]}

market_view = {
    "schema": "visual-answer-v1", "intent": "market_view", "title": "Market view · Nifty and Bank Nifty",
    "as_of": "2026-10-29", "generated_at": GEN, "mode": "eod",
    "headline": {"text": f"MOCK: Nifty closed at {last:,.2f}; 62% of stocks advanced; India VIX 15.12.", "tone": "up"},
    "decision": None,
    "blocks": [
        {"type": "kpis", "id": "kpis", "title": "The day", "note": None, "items": [
            {"label": "Nifty 50", "value": f"{last:,.2f}", "sub": "+1.05%", "tone": "up"},
            {"label": "Bank Nifty", "value": "49,212.40", "sub": "+1.31%", "tone": "up"},
            {"label": "India VIX", "value": "15.12", "sub": "−3.40%", "tone": "neutral"},
            {"label": "Advance / decline", "value": "1,312 / 804", "sub": "62% advanced", "tone": "up"},
            {"label": "FII cash", "value": "−₹943.60 Cr", "sub": "29 Oct", "tone": "down"},
            {"label": "DII cash", "value": "+₹1,210.05 Cr", "sub": "29 Oct", "tone": "up"}]},
        {"type": "candles", "id": "nifty", "title": "Nifty 50 · 60 sessions", "note": "Shaded: the expected move to the 4 Nov expiry, from the ATM straddle.",
         "symbol": "NIFTY", "bars": nifty, "overlays": {"ema20": ema(nifty, 20), "ema50": ema(nifty, 50)},
         "levels": [{"kind": "wall_call", "price": 23200.0, "label": "Call OI wall 23,200"},
                    {"kind": "wall_put", "price": 22500.0, "label": "Put OI wall 22,500"}],
         "band": {"low": round(last - 335.4, 2), "high": round(last + 335.4, 2), "label": "Expected move to 4 Nov"}},
        heat,
        {"type": "notice", "id": "gift", "title": None, "note": None, "tone": "warn",
         "text": "MOCK: F&O open interest is from 28 Oct; the 29 Oct F&O bhavcopy had not arrived when this was built."}],
    "evidence": [{"label": "FII cash", "value": "−₹943.60 Cr", "source": "NSE FII/DII", "as_of": "2026-10-29"},
                 {"label": "Breadth", "value": "62% advanced", "source": "NSE bhavcopy", "as_of": "2026-10-29"}],
    "data_quality": dq([("NSE bhavcopy", "2026-10-29", "fresh", None), ("NSE F&O bhavcopy", "2026-10-28", "stale", "29 Oct file not in yet"),
                        ("NSE FII/DII", "2026-10-29", "fresh", None)], stale=True, missing=["GIFT Nifty: no source"]),
    "follow_ups": [{"label": "Where is smart money moving?", "query": "Where is smart money moving?"},
                   {"label": "What is the expected move in Nifty?", "query": "What is the expected move in Nifty?"}],
    "caveat": CAVEAT}

fii = [-943.6, 412.3, -1288.15, -220.4, 865.0, -1530.75, -310.2, 98.6, -742.1, -455.9][::-1]   # oldest first; 29 Oct = −943.60 (the KPI)
dii = [1210.05, 640.8, 1502.3, 388.0, -120.45, 1810.6, 955.1, 230.0, 1102.7, 860.4][::-1]
days10 = sessions(10)
lab = lambda d: dt.date.fromisoformat(d).strftime("%-d %b")
smart_money = {
    "schema": "visual-answer-v1", "intent": "smart_money", "title": "Where smart money is moving",
    "as_of": "2026-10-29", "generated_at": GEN, "mode": "eod",
    "headline": {"text": "MOCK: FIIs sold in 7 of the last 10 sessions while DIIs bought in 9; long buildup led in banks.", "tone": "neutral"},
    "decision": None,
    "blocks": [
        {"type": "bars", "id": "fii", "title": "FII cash, last 10 sessions", "note": None, "unit": "₹ Cr", "orientation": "v",
         "items": [{"label": lab(d), "value": v} for d, v in zip(days10, fii)]},
        {"type": "bars", "id": "dii", "title": "DII cash, last 10 sessions", "note": None, "unit": "₹ Cr", "orientation": "v",
         "items": [{"label": lab(d), "value": v} for d, v in zip(days10, dii)]},
        {"type": "heatmap", "id": "rotation", "title": "Sector rotation, 5 sessions", "note": None, "unit": "%",
         "cells": [{"label": n, "value": round(v * 2.3, 2)} for n, v in sectors]},
        {"type": "quadrant", "id": "buildup", "title": "F&O buildup · price vs open interest", "note": None,
         "x": {"label": "Price change", "unit": "%"}, "y": {"label": "OI change", "unit": "%"},
         "quadrants": {"tr": "Long buildup", "tl": "Short buildup", "br": "Short covering", "bl": "Long unwinding"},
         "points": [{"label": "HDFCBANK", "x": 1.82, "y": 6.4, "quadrant": "Long buildup"},
                    {"label": "ICICIBANK", "x": 2.15, "y": 4.1, "quadrant": "Long buildup"},
                    {"label": "TCS", "x": -1.2, "y": 5.3, "quadrant": "Short buildup"},
                    {"label": "INFY", "x": -0.74, "y": -3.9, "quadrant": "Long unwinding"},
                    {"label": "TATASTEEL", "x": 3.05, "y": -2.6, "quadrant": "Short covering"},
                    {"label": "DLF", "x": -2.4, "y": 8.2, "quadrant": "Short buildup"}]},
        {"type": "ranked", "id": "strongest", "title": "Strongest long buildup and short covering", "note": None,
         "columns": [{"key": "symbol", "label": "Stock", "align": "left", "format": "text"},
                     {"key": "price_pct", "label": "Price", "align": "right", "format": "pct"},
                     {"key": "oi_pct", "label": "OI", "align": "right", "format": "pct"},
                     {"key": "buildup", "label": "Buildup", "align": "left", "format": "text"}],
         "rows": [{"symbol": "HDFCBANK", "cells": {"symbol": "HDFCBANK", "price_pct": 1.82, "oi_pct": 6.4, "buildup": "Long buildup"}, "tone": "up", "ask": "Is HDFCBANK a buy now?"},
                  {"symbol": "TATASTEEL", "cells": {"symbol": "TATASTEEL", "price_pct": 3.05, "oi_pct": -2.6, "buildup": "Short covering"}, "tone": "up", "ask": "Is TATASTEEL a buy now?"}]}],
    "evidence": [{"label": "FII cash, 10 sessions", "value": f"−₹{abs(sum(fii)):,.2f} Cr", "source": "NSE FII/DII", "as_of": "2026-10-29"}],
    "data_quality": dq([("NSE FII/DII", "2026-10-29", "fresh", None), ("NSE sector indices", "2026-10-29", "fresh", None), ("NSE F&O bhavcopy", "2026-10-29", "fresh", None)]),
    "follow_ups": [{"label": "Today's top 5 opportunities", "query": "Today's top 5 opportunities"}],
    "caveat": CAVEAT}

tops = [("ICICIBANK", "Breakout", 1200.0, 1160.0, 1280.0, 82, PLAN), ("TATASTEEL", "Pullback to EMA 20", 152.4, 146.9, 164.0, 77, None),
        ("LT", "Breakout", 3712.5, 3598.0, 3950.0, 74, None), ("SUNPHARMA", "Range breakout", 1688.0, 1641.0, 1790.0, 71, None),
        ("HAL", "Flag", 4420.0, 4268.0, 4760.0, 69, None)]
top_opportunities = {
    "schema": "visual-answer-v1", "intent": "top_opportunities", "title": "Today's top 5 ideas",
    "as_of": "2026-10-29", "generated_at": GEN, "mode": "eod",
    "headline": {"text": "MOCK: 5 of the scanner's Top 10 have a plan with levels; 2 wait for a volume confirmation.", "tone": "neutral"},
    "decision": None,
    "blocks": [
        {"type": "ranked", "id": "top5", "title": "Top 5 by score", "note": "Reward:risk to the first target, before charges.",
         "columns": [{"key": "rank", "label": "#", "align": "right", "format": "int"},
                     {"key": "symbol", "label": "Stock", "align": "left", "format": "text"},
                     {"key": "setup", "label": "Setup", "align": "left", "format": "text"},
                     {"key": "entry", "label": "Entry", "align": "right", "format": "price"},
                     {"key": "stop", "label": "Stop", "align": "right", "format": "price"},
                     {"key": "target", "label": "Target", "align": "right", "format": "price"},
                     {"key": "rr", "label": "R:R", "align": "right", "format": "x"},
                     {"key": "score", "label": "Score", "align": "right", "format": "int"}],
         "rows": [{"symbol": s, "cells": {"rank": i + 1, "symbol": s, "setup": st, "entry": e, "stop": sl, "target": t,
                                          "rr": round((t - e) / (e - sl), 2), "score": sc},
                   "tone": None, "plan_id": pid, "ask": f"Entry, target and stop-loss for {s}?"}
                  for i, (s, st, e, sl, t, sc, pid) in enumerate(tops)]},
        {"type": "trade_plan", "id": "first", "title": "The first idea's plan", "note": None, "plan_id": PLAN}],
    "evidence": [{"label": "Scanner day", "value": "Top 10 of 29 Oct", "source": "AI scanner watchlist", "as_of": "2026-10-29"}],
    "data_quality": dq([("AI scanner watchlist", "2026-10-29", "fresh", None), ("NSE bhavcopy", "2026-10-29", "fresh", None)]),
    "follow_ups": [{"label": "Which breakouts are confirmed?", "query": "Which breakouts are confirmed?"}],
    "caveat": CAVEAT}

lt = walk(60, 3500, 0.012, 0.0012, 2e6)
lt[-1]["c"] = round(max(lt[-1]["c"], 3712.5 * 1.004), 2); lt[-1]["h"] = max(lt[-1]["h"], lt[-1]["c"])
breakouts = {
    "schema": "visual-answer-v1", "intent": "breakouts", "title": "Confirmed breakouts",
    "as_of": "2026-10-29", "generated_at": GEN, "mode": "eod",
    "headline": {"text": "MOCK: 3 breakouts closed above their level on at least 1.5× their usual volume.", "tone": "up"},
    "decision": None,
    "blocks": [
        {"type": "ranked", "id": "list", "title": "Breakouts confirmed on 29 Oct", "note": None,
         "columns": [{"key": "symbol", "label": "Stock", "format": "text"}, {"key": "level", "label": "Breakout level", "format": "price"},
                     {"key": "close", "label": "Close", "format": "price"}, {"key": "vol_x", "label": "Volume", "format": "x"},
                     {"key": "stop", "label": "Stop", "format": "price"}],
         "rows": [{"symbol": "LT", "cells": {"symbol": "LT", "level": 3712.5, "close": lt[-1]["c"], "vol_x": 2.4, "stop": 3598.0}, "ask": "Is LT a buy now?"},
                  {"symbol": "SUNPHARMA", "cells": {"symbol": "SUNPHARMA", "level": 1688.0, "close": 1702.35, "vol_x": 1.8, "stop": 1641.0}, "ask": "Is SUNPHARMA a buy now?"},
                  {"symbol": "HAL", "cells": {"symbol": "HAL", "level": 4420.0, "close": 4436.1, "vol_x": 1.55, "stop": 4268.0}, "ask": "Is HAL a buy now?"}]},
        {"type": "candles", "id": "lt", "title": "LT · the breakout", "note": None, "symbol": "LT", "bars": lt,
         "overlays": {"ema20": ema(lt, 20), "ema50": ema(lt, 50)},
         "levels": [{"kind": "resistance", "price": 3712.5, "label": "Breakout level"}, {"kind": "stop", "price": 3598.0, "label": "Stop"}], "band": None},
        {"type": "bars", "id": "volx", "title": "Volume against the 20-day average", "note": None, "unit": "×", "orientation": "h",
         "items": [{"label": "LT", "value": 2.4}, {"label": "SUNPHARMA", "value": 1.8}, {"label": "HAL", "value": 1.55}], "baseline": 1.0}],
    "evidence": [{"label": "Rule", "value": "Close above the level, volume ≥ 1.5×", "source": "Positional watchlist", "as_of": "2026-10-29"}],
    "data_quality": dq([("Positional watchlist", "2026-10-29", "fresh", None), ("NSE bhavcopy", "2026-10-29", "fresh", None)]),
    "follow_ups": [{"label": "Entry, target and stop-loss for LT", "query": "Entry, target and stop-loss for LT?"}],
    "caveat": CAVEAT}

uv = [("ADANIPORTS", 4.8, 2.1, 38.2), ("PAYTM", 3.9, -3.4, 22.5), ("IRCTC", 3.2, 1.2, 41.0), ("BHEL", 2.9, 4.6, 29.4),
      ("ZOMATO", 2.7, -1.1, 18.7), ("VEDL", 2.5, 2.8, 33.3), ("PFC", 2.4, 0.6, 45.1), ("IDEA", 2.2, -0.9, 12.4),
      ("NMDC", 2.1, 1.7, 36.8), ("GAIL", 2.0, -0.3, 40.2)]
unusual_volume = {
    "schema": "visual-answer-v1", "intent": "unusual_volume", "title": "Unusual volume today",
    "as_of": "2026-10-29", "generated_at": GEN, "mode": "eod",
    "headline": {"text": "MOCK: 10 stocks traded at least twice their 20-day average volume.", "tone": "neutral"},
    "decision": None,
    "blocks": [
        {"type": "bars", "id": "rvol", "title": "Relative volume, top 10", "note": None, "unit": "×", "orientation": "h",
         "items": [{"label": s, "value": x, "sub": None} for s, x, _, _ in uv], "baseline": 1.0},
        {"type": "ranked", "id": "table", "title": "Price and delivery", "note": None,
         "columns": [{"key": "symbol", "label": "Stock", "format": "text"}, {"key": "price_pct", "label": "Price", "format": "pct"},
                     {"key": "vol_x", "label": "Volume", "format": "x"}, {"key": "delivery", "label": "Delivery", "format": "pct"}],
         "rows": [{"symbol": s, "cells": {"symbol": s, "price_pct": p, "vol_x": x, "delivery": d}} for s, x, p, d in uv]}],
    "evidence": [{"label": "Volume measure", "value": "volume ÷ 20-day average", "source": "Stock features", "as_of": "2026-10-29"}],
    "data_quality": dq([("Stock features", "2026-10-29", "fresh", None), ("NSE bhavcopy", "2026-10-29", "fresh", None)]),
    "follow_ups": [{"label": "Which breakouts are confirmed?", "query": "Which breakouts are confirmed?"}],
    "caveat": CAVEAT}

icici = walk(60, 1120, 0.01, 0.0011, 1.5e7)
stock_decision = {
    "schema": "visual-answer-v1", "intent": "stock_decision", "title": "ICICIBANK · entry, stop and targets",
    "as_of": "2026-10-29", "generated_at": GEN, "mode": "eod",
    "headline": {"text": "MOCK: ICICIBANK closed above its breakout level on 2.1× its usual volume.", "tone": "up"},
    "decision": {"status": "setup_ready", "label": "Setup ready", "reason": "MOCK: close above the breakout level 1,195 on 2.1× average volume.",
                 "conditions": [{"text": "Close above ₹1,195", "met": True}, {"text": "Volume ≥ 1.5× its 20-day average", "met": True},
                                {"text": "Nifty above its 50-day EMA", "met": False}],
                 "invalidation": "A close below ₹1,160", "plan_id": PLAN},
    "blocks": [
        {"type": "candles", "id": "chart", "title": "ICICIBANK · the plan on the chart", "note": None, "symbol": "ICICIBANK", "bars": icici,
         "overlays": {"ema20": ema(icici, 20), "ema50": ema(icici, 50)},
         "levels": [{"kind": "entry", "price": 1200.0, "label": "Entry"}, {"kind": "stop", "price": 1160.0, "label": "Stop"},
                    {"kind": "target", "price": 1220.0, "label": "T1"}, {"kind": "target", "price": 1280.0, "label": "T2"}], "band": None},
        {"type": "kpis", "id": "risk", "title": "Risk and reward", "note": None, "items": [
            {"label": "Reward : risk (T2)", "value": "2.0×", "tone": "up"}, {"label": "Size", "value": "125 shares", "sub": "your risk profile"},
            {"label": "Max loss", "value": "₹5,000.00", "sub": "to the stop, before charges", "tone": "down"}]},
        {"type": "list", "id": "warn", "title": "Watch out", "note": None, "items": [
            {"text": "MOCK: results on 4 Nov fall inside the holding period.", "tone": "warn", "sub": "Gaps can jump the stop."},
            {"text": "MOCK: bank stocks led the day; a sector reversal would weaken the idea.", "tone": "neutral"}]},
        {"type": "trade_plan", "id": "plan", "title": "The desk's plan", "note": None, "plan_id": PLAN}],
    "evidence": [{"label": "Breakout level", "value": "₹1,195.00", "source": "Desk plan", "as_of": "2026-10-29"},
                 {"label": "Volume", "value": "2.1×", "source": "Stock features", "as_of": "2026-10-29"}],
    "data_quality": dq([("NSE bhavcopy", "2026-10-29", "fresh", None), ("Desk trade plan", "2026-10-29", "fresh", None)]),
    "follow_ups": [{"label": "Plan a bearish trade instead", "query": "Plan a bearish trade for ICICIBANK instead"}],
    "caveat": CAVEAT}

expected_move = {
    "schema": "visual-answer-v1", "intent": "expected_move", "title": "Expected move in Nifty to 4 Nov",
    "as_of": "2026-10-29", "generated_at": GEN, "mode": "eod",
    "headline": {"text": f"MOCK: the options price a move of about ±335 points (±1.46%) to the 4 Nov expiry.", "tone": "neutral"},
    "decision": None,
    "blocks": [
        {"type": "kpis", "id": "chain", "title": "Option chain, 4 Nov expiry", "note": None, "items": [
            {"label": "ATM IV", "value": "13.8%"}, {"label": "Expected move", "value": "±335.40", "sub": "±1.46%"},
            {"label": "PCR (OI)", "value": "1.12"}, {"label": "Max pain", "value": "22,900"}, {"label": "Expiry", "value": "4 Nov 2026"}]},
        {"type": "candles", "id": "nifty", "title": "Nifty 50 with the expected-move band", "note": None, "symbol": "NIFTY", "bars": nifty,
         "overlays": {"ema20": ema(nifty, 20)},
         "levels": [{"kind": "wall_call", "price": 23200.0, "label": "Call wall"}, {"kind": "wall_put", "price": 22500.0, "label": "Put wall"},
                    {"kind": "max_pain", "price": 22900.0, "label": "Max pain"}],
         "band": {"low": round(last - 335.4, 2), "high": round(last + 335.4, 2), "label": "Expected move to 4 Nov"}}],
    "evidence": [{"label": "ATM straddle", "value": "₹335.40", "source": "F&O chain summary", "as_of": "2026-10-29"}],
    "data_quality": dq([("F&O chain summary", "2026-10-29", "fresh", None)]),
    "follow_ups": [{"label": "What is the market view today?", "query": "What is the market view today?"}],
    "caveat": CAVEAT}

doc = {"about": "MOCK — not real data. Synthetic visual-answer-v1 payloads, one per Release-1 intent, written by the frontend "
                "until the backend's real capture (contract-visual-answer.json) exists. Generator: e2e/tools/make_visual_answer_mock.py (a seeded random walk).",
       "payloads": {p["intent"]: p for p in [market_view, smart_money, top_opportunities, breakouts, unusual_volume, stock_decision, expected_move]}}
json.dump(doc, open(OUT, "w"), ensure_ascii=False, indent=1)
print("wrote", OUT, list(doc["payloads"]))
