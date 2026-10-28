"""Closing Bell — write the night's anchor script from cards.json with fixed templates.

Every number in the narration and the on-screen captions is inserted through `Facts.n()`, which
reads it from cards.json by path and records (text, path). checks.py later re-reads each path and
rejects the script if any number in the text was not recorded this way. Nothing is invented: when
a figure is missing the sentence that needs it is left out.

usage: python3 script_gen.py CARDS.json OUT_script.json
Output: {"segments": [{id, tag, title, beats: [{who, text, sup, card, focus}]}], "headlines": [...],
         "trace": [{"s": "4,240", "path": "fii.fii_net", "fmt": "int"}...], "focus": {...}}
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from typing import Any, Dict, List, Optional


def fmt_in(v: float, dec: int = 0) -> str:
    """Indian digit grouping: 101175 -> 1,01,175; 22749.75 -> 22,749.75."""
    neg = v < 0
    s = f"{abs(v):.{dec}f}"
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        whole = head + "," + tail
    return ("-" if neg else "") + whole + ("." + frac if frac else "")


class Facts:
    def __init__(self, cards: Dict[str, Any]):
        self.c = cards
        self.trace: List[Dict[str, str]] = []

    def get(self, path: str) -> Any:
        cur: Any = self.c
        for part in path.split("."):
            if isinstance(cur, list):
                cur = cur[int(part)]
            elif isinstance(cur, dict):
                cur = cur.get(part)
            else:
                return None
            if cur is None:
                return None
        return cur

    def n(self, path: str, fmt: str = "2", absval: bool = True) -> str:
        """Format the number at `path` (fmt: 'int' | '0' | '1' | '2' | 'in0' | 'in2') and record it."""
        v = self.get(path)
        if v is None:
            raise KeyError(path)
        x = abs(float(v)) if absval else float(v)
        s = {"int": lambda: str(int(round(x))), "0": lambda: f"{x:.0f}", "1": lambda: f"{x:.1f}", "2": lambda: f"{x:.2f}",
             "in0": lambda: fmt_in(x, 0), "in2": lambda: fmt_in(x, 2)}[fmt]()
        self.trace.append({"s": s, "path": path, "fmt": fmt, "abs": absval})
        return s

    def t(self, path: str) -> str:
        """A text field taken verbatim from cards (idea reason, strategy label, time): its numbers are traced to it."""
        v = self.get(path)
        if v is None:
            raise KeyError(path)
        s = str(v)
        for tok in re.findall(r"\d[\d,]*(?:\.\d+)?", s):
            self.trace.append({"s": tok, "path": path, "fmt": "text", "abs": True})
        return s

    def date(self, path: str, style: str = "long") -> str:
        """'2 September' (long) or '2 Sep' (short) from an ISO date in cards."""
        import datetime as _d
        v = self.get(path)
        if v is None:
            raise KeyError(path)
        dd = _d.date.fromisoformat(str(v)[:10])
        self.trace.append({"s": str(dd.day), "path": path, "fmt": "day", "abs": True})
        return f"{dd.day} {dd:%B}" if style == "long" else f"{dd.day} {dd:%b}"


def pick(day: str, *options: str) -> str:
    """Deterministic variety: the same date always gets the same wording."""
    h = int(hashlib.sha256((day + options[0]).encode()).hexdigest(), 16)
    return options[h % len(options)]


def spoken(text: str) -> str:
    """Narration fixes for the voice: symbols read aloud."""
    t = text.replace("&", " and ").replace("₹", "").replace("×", " times").replace("%", " percent")
    t = re.sub(r"(\d)/(\d)", r"\1 to \2", t)
    t = re.sub(r"\bavg\b", "average", t)
    t = re.sub(r"\bDMA\b", "day average", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def updown(v: float) -> str:
    return "up" if v > 0 else "down" if v < 0 else "flat"


def sgn_txt(F: Facts, path: str, fmt: str = "2", unit: str = "%") -> str:
    v = F.get(path)
    s = F.n(path, fmt)
    return ("+" if v > 0 else "−" if v < 0 else "") + s + unit


def build(cards: Dict[str, Any]) -> Dict[str, Any]:
    F = Facts(cards)
    L = cards["L"]
    day = cards["date"]
    idx = {x["name"]: i for i, x in enumerate(cards["idx"])}
    segs: List[Dict[str, Any]] = []
    focus: Dict[str, Any] = {}

    def ip(name: str, key: str) -> str:
        return f"idx.{idx[name]}.{key}"

    def beat(text: str, sup: str, card: Optional[str], f: Optional[dict] = None) -> dict:
        return {"who": "A", "text": spoken(text), "sup": sup, "card": card, "focus": f or {}}

    n50p = F.get(ip("Nifty 50", "pct")) if "Nifty 50" in idx else None
    sc = "Nifty Smallcap 250" in idx and F.get(ip("Nifty Smallcap 250", "pct"))
    mv = cards["movers"]
    n500 = mv.get("Nifty 500") or {}

    # ------------------------------------------------------------ s0 headlines
    heads: List[Dict[str, str]] = []
    hb: List[dict] = []
    if n50p is not None:
        flat = abs(n50p) < 0.15
        mood = ("flat" if flat else "higher" if n50p > 0 else "lower")
        if flat and sc and sc > 1:
            big, say = 'Nifty flat, <span class="up">smallcaps sprint</span>', f"The Nifty ends flat, but smallcaps jump {F.n(ip('Nifty Smallcap 250', 'pct'), '1')} percent."
        elif flat and sc and sc < -1:
            big, say = 'Nifty flat, <span class="dn">smallcaps slide</span>', f"The Nifty ends flat, but smallcaps fall {F.n(ip('Nifty Smallcap 250', 'pct'), '1')} percent."
        else:
            verb = {"flat": "ends flat", "higher": pick(day, "closes higher", "gains", "ends in the green"),
                    "lower": pick(day, "closes lower", "slips", "ends in the red")}[mood]
            big = f'Nifty <span class="{ "up" if n50p > 0 else "dn" }">{verb}</span>'
            say = f"The Nifty {verb}, {updown(n50p)} {F.n(ip('Nifty 50', 'pct'))} percent at {F.n(ip('Nifty 50', 'close'), 'in2')}."
        small = (f"Nifty 50 {F.n(ip('Nifty 50', 'close'), 'in2')} {sgn_txt(F, ip('Nifty 50', 'pct'))}"
                 + (f" · Smallcap 250 {sgn_txt(F, ip('Nifty Smallcap 250', 'pct'))}" if sc is not False else "")
                 + (f" · {F.n('movers.Nifty 500.adv', 'int')} of {F.n('movers.Nifty 500.n', 'int')} Nifty 500 stocks up" if n500 else ""))
        heads.append({"kicker": "Markets", "big": big, "small": small}); hb.append(beat(say, small, "h1"))
    f = cards["fii"]
    if f.get("available"):
        buy = f["fii_net"] >= 0
        big = f'Foreign investors <span class="{ "up" if buy else "dn" }">{"buy" if buy else "sell"}</span>'
        since = f.get("biggest_since")
        say = (f"Foreign investors were net {'buyers' if buy else 'sellers'} of {F.n('fii.fii_net', 'in0')} crore rupees"
               + (f", their biggest {'buying' if buy else 'selling'} day since {F.date('fii.biggest_since')}." if since else "."))
        small = (f"FIIs {'+' if buy else '−'}₹{F.n('fii.fii_net', 'in0')} Cr · DIIs {'+' if f['dii_net'] >= 0 else '−'}₹{F.n('fii.dii_net', 'in0')} Cr"
                 + (f" · biggest FII {'buying' if buy else 'selling'} day since {F.date('fii.biggest_since')}" if since else "")
                 + ("" if f.get("same_day") else f" · figures for {F.date('fii.date')}"))
        heads.append({"kicker": "Flows", "big": big, "small": small}); hb.append(beat(say, small, "h2"))
    ru = cards["res_up"]
    if len(ru) >= 2:
        k = min(4, len(ru))
        names = [ru[i]["name"] for i in range(k)]
        say = "Results-day rallies in " + ", ".join(names[:-1]) + " and " + names[-1] + "."
        small = " · ".join(f"{ru[i]['name']} {sgn_txt(F, f'res_up.{i}.pct', '1')}" for i in range(k))
        heads.append({"kicker": "Results", "big": 'Results-day <span class="up">rallies</span>', "small": small}); hb.append(beat(say, small, "h3"))
    secs = cards["sectors"]
    if secs:
        worst, best = secs[-1], secs[0]
        wi, bi = len(secs) - 1, 0
        if worst["d1"] <= -1.0 and abs(worst["d1"]) >= abs(best["d1"]) * 0.6:
            s, i, up = worst, wi, False
        else:
            s, i, up = best, bi, True
        big = f'{s["name"]} <span class="{ "up" if up else "dn" }">{pick(day, "leads", "shines", "outperforms") if up else pick(day, "cracks", "slides", "lags")}</span>'
        say = (f"And {s['name']} {('leads the sectors, up ' if up else 'is the weakest sector, down ')}{F.n(f'sectors.{i}.d1')} percent."
               + " All of it, straight from the Smart Trading Desk.")
        small = f"Nifty {s['name']} {sgn_txt(F, f'sectors.{i}.d1')}" + (
            f", {F.n(f'sectors.{i}.adv', 'int')} of {F.n(f'sectors.{i}.n', 'int')} up" if s.get("adv") is not None and s.get("n") else "")
        heads.append({"kicker": "Sectors", "big": big, "small": small}); hb.append(beat(say, small, "h4"))
    title = f"Closing Bell · {L['day_long']}"
    s0 = [beat(pick(day, "Good evening, and welcome to Closing Bell on the Nivesh Desk.",
                    "Good evening. This is Closing Bell, from the Nivesh Desk.",
                    "Good evening, and welcome to Closing Bell on the Nivesh Desk, your wrap of the day's markets."), title, "title"),
          beat("Here are tonight's headlines.", title, "title")] + hb
    segs.append({"id": "s0", "tag": "HEADLINES", "title": "Tonight's headlines", "beats": s0})

    # ------------------------------------------------------------ s1 market wrap
    s1 = []
    if n50p is not None:
        d = cards["day"]
        pts = F.get(ip("Nifty 50", "pts"))
        s1.append(beat(
            f"First, the scoreboard. The Nifty 50 settled at {F.n(ip('Nifty 50', 'close'), 'in2')}, "
            f"{updown(pts)} {F.n(ip('Nifty 50', 'pts'))} points, or {F.n(ip('Nifty 50', 'pct'))} percent.",
            f"Nifty 50 {F.n(ip('Nifty 50', 'close'), 'in2')} · {sgn_txt(F, ip('Nifty 50', 'pts'), '2', ' pts')} ({sgn_txt(F, ip('Nifty 50', 'pct'))}) · "
            f"range {F.n('day.low', 'in2')}–{F.n('day.high', 'in2')}", "idx", {"desk": "overview"}))
        parts, sparts = [], []
        for name, spoken_name in (("Nifty Bank", "Bank Nifty"), ("Nifty Next 50", "the Next 50"), ("Nifty Midcap 150", "the Midcap 150"),
                                  ("Nifty Smallcap 250", "the Smallcap 250")):
            if name in idx:
                v = F.get(ip(name, "pct"))
                parts.append(f"{spoken_name} {('rose' if v > 0 else 'fell' if v < 0 else 'was flat')} {F.n(ip(name, 'pct'))} percent" if v else f"{spoken_name} was flat")
                sparts.append(f"{spoken_name.replace('the ', '').replace('Bank Nifty', 'Bank Nifty')} {sgn_txt(F, ip(name, 'pct'))}")
        if parts:
            s1.append(beat(parts[0][0].upper() + parts[0][1:] + (", " + ", ".join(parts[1:-1]) + (", and " if len(parts) > 2 else " and ") + parts[-1] if len(parts) > 1 else "") + ".",
                           " · ".join(sparts), "idx"))
        if n500 and "India VIX" in idx:
            adv, dec = n500["adv"], n500["dec"]
            ratio = adv / dec if dec else None
            if ratio and ratio >= 1.5:
                mood = f"Breadth was strong: {F.n('movers.Nifty 500.adv', 'int')} Nifty 500 stocks rose, and {F.n('movers.Nifty 500.dec', 'int')} fell."
            elif ratio and ratio <= 0.67:
                mood = f"Breadth was weak: only {F.n('movers.Nifty 500.adv', 'int')} Nifty 500 stocks rose, while {F.n('movers.Nifty 500.dec', 'int')} fell."
            else:
                mood = f"Breadth was mixed: {F.n('movers.Nifty 500.adv', 'int')} Nifty 500 stocks rose and {F.n('movers.Nifty 500.dec', 'int')} fell."
            vix = F.get(ip("India VIX", "pct"))
            mood += f" India VIX {('rose' if vix > 0 else 'eased')} {F.n(ip('India VIX', 'pct'), '1')} percent, to {F.n(ip('India VIX', 'close'), '1')}."
            s1.append(beat(mood, f"Nifty 500: {F.n('movers.Nifty 500.adv', 'int')} up · {F.n('movers.Nifty 500.dec', 'int')} down · India VIX "
                                 f"{F.n(ip('India VIX', 'close'), '2')} ({sgn_txt(F, ip('India VIX', 'pct'))})", "brd"))
    rg = cards.get("regime") or {}
    if rg.get("label"):
        s1.append(beat(f"The desk's regime model reads {rg['label']}, with the trend {rg.get('trend') or 'unclear'}.",
                       f"Desk regime: {rg['label']} · trend {rg.get('trend') or '—'} · as of {L['day_short']}", None, {"desk": "regime"}))
    segs.append({"id": "s1", "tag": "MARKET WRAP", "title": "How the market closed", "beats": s1})

    # ------------------------------------------------------------ s2 results
    s2 = []
    cn = cards.get("counts") or {}
    wk = cards.get("week") or {}
    if cn.get("declared") is not None:
        s2.append(beat(f"To earnings. The desk's Results Week tracker shows {F.n('counts.declared', 'int')} companies have declared this week"
                       + (f", with {F.n('counts.upcoming', 'int')} still to come." if cn.get("upcoming") else "."),
                       f"Results week · {F.n('counts.declared', 'int')} declared" + (f" · {F.n('counts.upcoming', 'int')} upcoming" if cn.get("upcoming") else ""),
                       None, {"desk": "results"}))
        if cn.get("above") is not None:
            s2.append(beat(f"With no analyst consensus in the system, the desk scores each quarter against the company's own trend: "
                           f"{F.n('counts.above', 'int')} above, {F.n('counts.in_line', 'int')} in line, {F.n('counts.below', 'int')} below.",
                           f"Vs the company's own past trend, not consensus · {F.n('counts.above', 'int')} above · {F.n('counts.in_line', 'int')} in line · "
                           f"{F.n('counts.below', 'int')} below", None))
    if ru:
        a = ru[0]
        txt = f"{a['name']} {pick(day, 'jumped', 'surged', 'rallied')} {F.n('res_up.0.pct', '1')} percent"
        if a.get("volx"):
            txt += f" on {F.n('res_up.0.volx', '1' if a['volx'] < 10 else '0')} times its usual volume"
        if a.get("pat_yoy") is not None:
            txt += f", after profit {'grew' if a['pat_yoy'] > 0 else 'fell'} {F.n('res_up.0.pat_yoy', '0')} percent from a year ago"
        sup = f"{a['name']} {sgn_txt(F, 'res_up.0.pct')}" + (f" · volume {F.n('res_up.0.volx', '0')}× its 20-day average" if a.get("volx") else "") + (
            f" · PAT {sgn_txt(F, 'res_up.0.pat_yoy', '0')} YoY" if a.get("pat_yoy") is not None else "")
        s2.append(beat(txt + ".", sup, "res", {"search": [a["name"]], "syms": [a["sym"]]}))
        if len(ru) > 1:
            rest = ru[1:4]
            s2.append(beat(", ".join(f"{x['name']} gained {F.n(f'res_up.{i + 1}.pct', '1')} percent" for i, x in enumerate(rest[:-1]))
                           + ("" if len(rest) == 1 else ", and ") + f"{rest[-1]['name']} {F.n(f'res_up.{len(rest)}.pct', '1')} percent" + ".",
                           " · ".join(f"{x['name']} {sgn_txt(F, f'res_up.{i + 1}.pct')}" for i, x in enumerate(rest)), "res",
                           {"search": [x["name"] for x in rest], "syms": [x["sym"] for x in rest]}))
    rd = cards["res_dn"]
    if rd:
        k = min(3, len(rd))
        parts = [f"{rd[i]['name']} fell {F.n(f'res_dn.{i}.pct', '1')} percent" + (
            f" on {F.n(f'res_dn.{i}.volx', '1' if rd[i]['volx'] < 10 else '0')} times its usual volume" if i == 0 and rd[i].get("volx") and rd[i]["volx"] >= 2.5 else "") for i in range(k)]
        s2.append(beat("On the downside, " + (", ".join(parts[:-1]) + ", and " + parts[-1] if k > 1 else parts[0]) + ".",
                       " · ".join(f"{rd[i]['name']} {sgn_txt(F, f'res_dn.{i}.pct')}" for i in range(k)), "res",
                       {"search": [rd[0]["name"]], "syms": [rd[0]["sym"]]}))
    af = cards["after"]
    if af:
        ups = [(i, a) for i, a in enumerate(af) if a["pat_yoy"] >= 0][:3]
        dns = [(i, a) for i, a in enumerate(af) if a["pat_yoy"] < 0][:4]
        lead = "After the close, " + pick(day, "the heavyweights reported.", "more results came in.", "the late filers reported.")
        if ups:
            i0, a0 = ups[0]
            txt = lead + f" {a0['name']}'s profit rose {F.n(f'after.{i0}.pat_yoy', '1')} percent, to {F.n(f'after.{i0}.pat', 'in0')} crore rupees"
            txt += "".join(f", {a['name']}'s {F.n(f'after.{i}.pat_yoy', '1')} percent" for i, a in ups[1:]) + "."
            s2.append(beat(txt, "After the close (net profit, YoY): " + " · ".join(f"{a['name']} {sgn_txt(F, f'after.{i}.pat_yoy', '1')}" for i, a in ups),
                           "after", {"syms": [a["sym"] for _, a in ups]}))
            lead = "But"
        if dns:
            txt = (lead if lead == "But" else lead + " But") + " " + ", ".join(
                f"{a['name']}'s profit fell {F.n(f'after.{i}.pat_yoy', '1')} percent" for i, a in dns) + f". They react on {L['next_dow']}."
            s2.append(beat(txt, " · ".join(f"{a['name']} {sgn_txt(F, f'after.{i}.pat_yoy', '1')}" for i, a in dns) + " (net profit, YoY)",
                           "after", {"syms": [a["sym"] for _, a in dns]}))
    segs.append({"id": "s2", "tag": "RESULTS", "title": "Results and the market's verdict", "beats": s2})

    # ------------------------------------------------------------ s3 sector rotation
    s3 = []
    if secs:
        tops = [i for i in range(min(5, len(secs))) if secs[i]["d1"] > 0]
        bots = [i for i in range(len(secs) - 1, max(len(secs) - 5, -1), -1) if secs[i]["d1"] < 0]
        if tops:
            t0 = tops[0]
            txt = f"Sector rotation now. {secs[t0]['name']} led the indices, up {F.n(f'sectors.{t0}.d1')} percent"
            if len(tops) > 1:
                txt += ", followed by " + ", ".join(secs[i]["name"] for i in tops[1:-1]) + (" and " if len(tops) > 2 else "") + secs[tops[-1]]["name"]
            s3.append(beat(txt + ".", "Day: " + " · ".join(f"{secs[i]['name']} {sgn_txt(F, f'sectors.{i}.d1')}" for i in tops), "sec", {"desk": "sectors"}))
        if bots:
            b0 = bots[0]
            txt = f"{secs[b0]['name']} was the weakest, down {F.n(f'sectors.{b0}.d1')} percent"
            if secs[b0].get("dec") is not None and secs[b0].get("n"):
                txt += f", with {F.n(f'sectors.{b0}.dec', 'int')} of its {F.n(f'sectors.{b0}.n', 'int')} stocks in the red"
            s3.append(beat(txt + ".", " · ".join(f"{secs[i]['name']} {sgn_txt(F, f'sectors.{i}.d1')}" for i in bots), "sec"))
        m_sorted = sorted(range(len(secs)), key=lambda i: secs[i]["m1"] if secs[i].get("m1") is not None else 0)
        lo, hi = m_sorted[0], m_sorted[-1]
        rot = cards.get("rotation") or {}
        txt = (f"Over a month, {secs[hi]['name']} leads, {updown(secs[hi]['m1'])} {F.n(f'sectors.{hi}.m1', '1')} percent, while "
               f"{secs[lo]['name']} is {updown(secs[lo]['m1'])} {F.n(f'sectors.{lo}.m1', '1')} percent.")
        sup = f"Month: Nifty {secs[hi]['name']} {sgn_txt(F, f'sectors.{hi}.m1')} · {secs[lo]['name']} {sgn_txt(F, f'sectors.{lo}.m1')}"
        if rot.get("leading"):
            lead = [short_sector(x) for x in rot["leading"][:3]]
            txt += " The desk's rotation matrix tags " + (", ".join(lead[:-1]) + " and " + lead[-1] if len(lead) > 1 else lead[0]) + " as leading."
            sup += " · Leading: " + " · ".join(lead)
        s3.append(beat(txt, sup, None, {"desk": "matrix"}))
    segs.append({"id": "s3", "tag": "SECTOR ROTATION", "title": "Where the money rotated", "beats": s3})

    # ------------------------------------------------------------ s4 movers & shakers
    s4 = []
    seen: set = set()
    for k, (name, card) in enumerate((("Nifty 50", "n50"), ("Nifty 100", "n100"), ("Nifty 200", "n200"), ("Nifty 500", "n500"))):
        m = mv.get(name)
        if not m:
            continue
        mp = f"movers.{name}"
        ups = [(i, x) for i, x in enumerate(m["top"]) if x["pct"] > 0 and x["sym"] not in seen][:2]
        dns = [(i, x) for i, x in enumerate(m["bottom"]) if x["pct"] < 0 and x["sym"] not in seen][:1 if k else 2]
        for _, x in ups + dns:
            seen.add(x["sym"])
        head = ("Movers and shakers, index by index. " if k == 0 else "") + (
            f"The {name} split {F.n(f'{mp}.adv', 'int')} to {F.n(f'{mp}.dec', 'int')}." if m["adv"] == m["dec"] else
            f"In the {name}, {'advancers' if m['adv'] > m['dec'] else 'decliners'} won {F.n(f'{mp}.adv' if m['adv'] > m['dec'] else f'{mp}.dec', 'int')} to "
            f"{F.n(f'{mp}.dec' if m['adv'] > m['dec'] else f'{mp}.adv', 'int')}.")
        body = []
        if ups:
            body.append(" and ".join(f"{x['name']} {'jumped' if x['pct'] >= 5 else 'gained'} {F.n(f'{mp}.top.{i}.pct', '1')} percent" for i, x in ups))
        if dns:
            body.append(" and ".join(f"{x['name']} {'sank' if x['pct'] <= -5 else 'fell'} {F.n(f'{mp}.bottom.{i}.pct', '1')} percent" for i, x in dns))
        txt = head + " " + (body[0][0].upper() + body[0][1:] if body else "") + (", while " + body[1] if len(body) > 1 else "") + ("." if body else "")
        sup = f"{name}: {F.n(f'{mp}.adv', 'int')} up · {F.n(f'{mp}.dec', 'int')} down · " + " · ".join(
            [f"{x['name']} {sgn_txt(F, f'{mp}.top.{i}.pct')}" for i, x in ups] + [f"{x['name']} {sgn_txt(F, f'{mp}.bottom.{i}.pct')}" for i, x in dns])
        s4.append(beat(txt, sup, card, {"index": m["code"], "syms": [x["sym"] for _, x in ups + dns]}))
    if n500:
        ss = [(i, s) for i, s in enumerate(n500["sectors"]) if s["n"] >= 4]
        full = sorted([(i, s) for i, s in ss if s["adv"] == s["n"]], key=lambda t: -t[1]["n"])[:2]
        worst = sorted(ss, key=lambda t: t[1]["adv"] / t[1]["n"])[:1]
        bits, sb = [], []
        for i, s in full:
            bits.append(f"every {short_sector(s['sector']).lower()} stock in the 500 rose")
            sb.append(f"{short_sector(s['sector'])} {F.n(f'movers.Nifty 500.sectors.{i}.adv', 'int')}/{F.n(f'movers.Nifty 500.sectors.{i}.n', 'int')}")
        for i, s in worst:
            if s["adv"] / s["n"] < 0.35:
                g = "gainer" if s["adv"] == 1 else "gainers"
                bits.append(f"{short_sector(s['sector'])} managed just {F.n(f'movers.Nifty 500.sectors.{i}.adv', 'int')} {g} in "
                            f"{F.n(f'movers.Nifty 500.sectors.{i}.n', 'int')}")
                sb.append(f"{short_sector(s['sector'])} {F.n(f'movers.Nifty 500.sectors.{i}.adv', 'int')}/{F.n(f'movers.Nifty 500.sectors.{i}.n', 'int')}")
        if bits:
            s4.append(beat("By sector: " + "; ".join(bits) + ".", "Nifty 500 by sector: " + " · ".join(sb), "s500",
                           {"sectors": [s["sector"] for _, s in full + worst]}))
    segs.append({"id": "s4", "tag": "MOVERS & SHAKERS", "title": "Nifty 50 · 100 · 200 · 500", "beats": s4})

    # ------------------------------------------------------------ s5 FII / DII
    s5 = []
    if f.get("available"):
        buy, dbuy = f["fii_net"] >= 0, f["dii_net"] >= 0
        when = "today" if f.get("same_day") else f"on {F.date('fii.date')}"
        txt = (f"Follow the money. Provisional data show FIIs {'bought' if buy else 'sold'} a net {F.n('fii.fii_net', 'in0')} crore rupees in cash {when}"
               + (f", their biggest {'buying' if buy else 'selling'} day since {F.date('fii.biggest_since')}" if f.get("biggest_since") else "")
               + f". DIIs {'bought' if dbuy else 'sold'} {F.n('fii.dii_net', 'in0')} crore.")
        s5.append(beat(txt, f"{F.date('fii.date', 'short')} (provisional): FII {'+' if buy else '−'}₹{F.n('fii.fii_net', 'in0')} Cr · "
                            f"DII {'+' if dbuy else '−'}₹{F.n('fii.dii_net', 'in0')} Cr", "fii", {"desk": "smartmoney"}))
        txt = (f"For {f['month']} so far, FIIs are net {'buyers' if f['mtd_fii'] >= 0 else 'sellers'} of {F.n('fii.mtd_fii', 'in0')} crore, "
               f"and DIIs net {'buyers' if f['mtd_dii'] >= 0 else 'sellers'} of {F.n('fii.mtd_dii', 'in0')} crore.")
        sup = (f"{f['month']} so far: FII {'+' if f['mtd_fii'] >= 0 else '−'}₹{F.n('fii.mtd_fii', 'in0')} Cr · "
               f"DII {'+' if f['mtd_dii'] >= 0 else '−'}₹{F.n('fii.mtd_dii', 'in0')} Cr")
        if f.get("m3_fii") is not None:
            txt += (f" Over three months, FIIs have {'bought' if f['m3_fii'] >= 0 else 'sold'} {F.n('fii.m3_fii', 'in0')} crore, and DIIs "
                    f"{'bought' if f['m3_dii'] >= 0 else 'sold'} {F.n('fii.m3_dii', 'in0')} crore.")
            sup += f" · Three months: FII {'+' if f['m3_fii'] >= 0 else '−'}₹{F.n('fii.m3_fii', 'in0')} Cr · DII {'+' if f['m3_dii'] >= 0 else '−'}₹{F.n('fii.m3_dii', 'in0')} Cr"
        s5.append(beat(txt, sup, "fii"))
        if f.get("desk_flow_to") and f["desk_flow_to"] < f["date"]:
            s5.append(beat(f"The desk's flow chart runs to {F.date('fii.desk_flow_to')}; today's figures join with the next load. "
                           "One day of flows is a signal, not yet a trend.",
                           f"Desk flow chart runs to {F.date('fii.desk_flow_to', 'short')} · today joins with the next NSE load", None))
        else:
            s5.append(beat("One day of flows is a signal, not yet a trend.", "One day of flows is a signal, not a trend", None))
    segs.append({"id": "s5", "tag": "FII / DII", "title": "Follow the money", "beats": s5})

    # ------------------------------------------------------------ s6 top 10 ideas
    s6 = []
    ideas = cards["ideas"]
    if ideas:
        s6.append(beat("Now, the desk's Top 10 ideas. These are ideas for review, not recommendations, and the desk's own scorecard shows no measurable ranking skill yet.",
                       "Ideas for review, not recommendations · no measurable ranking skill yet", "ideas", {"desk": "scanner"}))
        i0, i1 = ideas[0], ideas[1] if len(ideas) > 1 else None
        txt = f"{i0['name']}" + (f" and {i1['name']} lead" if i1 else " leads") + " the cash list."
        if i0.get("why"):
            txt += f" {i0['name']}: {why_spoken(F.t('ideas.0.why'))}."
        s6.append(beat(txt, f"{i0['name']}: {F.t('ideas.0.why')}" + (f" · {i1['name']}: {F.t('ideas.1.why')}" if i1 and i1.get('why') else ""), "ideas",
                       {"syms": [i0["sym"]] + ([i1["sym"]] if i1 else [])}))
        if len(ideas) > 2:
            rest = [x["name"] for x in ideas[2:]]
            s6.append(beat(", ".join(rest[:-1]) + " and " + rest[-1] + " complete the list." if len(rest) > 1 else f"{rest[0]} completes the list.",
                           " · ".join(rest), None, {"syms": [x["sym"] for x in ideas[2:]]}))
    fx = cards["fno"]
    if fx and rg.get("label"):
        x0 = fx[0]
        txt = (f"The F and O board reads a {rg['label'].lower()} regime with a {rg.get('trend') or 'mixed'} trend, so it fits defined-risk structures, "
               f"like the {x0['sym'].title().replace('Banknifty', 'Bank Nifty')} {F.t('fno.0.label').lower()} for {F.date('fno.0.expiry')}.")
        if any(v.get("view") == "down" for v in fx) and ideas:
            txt += " The desk shows these for information only where they conflict with bullish cash setups."
        s6.append(beat(txt, f"F&O board: regime {rg['label']} · trend {rg.get('trend') or '—'} · {x0['sym']} {F.t('fno.0.label')}, "
                            f"{F.date('fno.0.expiry', 'short')} expiry", "fno", {"desk": "fno"}))
    segs.append({"id": "s6", "tag": "TOP 10 IDEAS", "title": "The desk's ideas for review", "beats": s6})

    # ------------------------------------------------------------ s7 what to watch
    s7 = []
    mac = cards.get("macro") or []
    if mac:
        txt = f"{L['next_dow']}: " + ", and ".join(
            (f"India's {m[1].replace('YoY', '').strip().lower()} data" if m[3] == "IN" else f"the US {m[1].replace('YoY', '').strip()}")
            + f" at {spoken_time(F.t(f'macro.{i}.0'))} India time" for i, m in enumerate(mac[:2])) + "."
        s7.append(beat(txt, " · ".join(f"{L['next_short'][:3]} {F.t(f'macro.{i}.0')} IST {('India' if m[3] == 'IN' else 'US')} {m[1]}" for i, m in enumerate(mac[:2])), "watch",
                       {"macro": [f"{L['next_date']}|{m[4]}" for m in mac[:2] if len(m) > 4 and m[4]]}))
    due = cards.get("due") or []
    react = [a["name"] for a in af][:4]
    bits = []
    if react:
        bits.append("reactions to " + ", ".join(react[:-1]) + (" and " if len(react) > 1 else "") + react[-1])
    if due:
        bits.append("results from " + ", ".join(due[:3][:-1]) + (" and " if len(due[:3]) > 1 else "") + due[:3][-1])
    if bits:
        s7.append(beat(("Plus " if mac else f"{L['next_dow']}: ") + ", and ".join(bits) + ".",
                       f"Results due {L['next_short'][:3]}: " + " · ".join(due[:6]) if due else "First reaction: " + " · ".join(react), "watch",
                       {"search": due[:1], "syms": (cards.get("due_syms") or [])[:1]}))
    s7.append(beat(pick(day, "That's Closing Bell from the Nivesh Desk.", "And that's Closing Bell for today, from the Nivesh Desk."),
                   "Source: NSE end-of-day data and exchange filings, read on the Nivesh Smart Trading Desk", "end"))
    s7.append(beat("Market information and education, not investment advice. Good night.", "Market information and education, not investment advice", "end"))
    segs.append({"id": "s7", "tag": "WHAT TO WATCH", "title": L["next_title"], "beats": s7})

    segs = [s for s in segs if s["beats"]]
    return {"schema": "closing-bell-script-v1", "date": day, "segments": segs, "headlines": heads, "trace": F.trace}


def month_of(iso: str) -> str:
    import datetime as _d
    return _d.date.fromisoformat(iso[:10]).strftime("%B")


def short_sector(s: str) -> str:
    return {"Information Technology": "IT", "Telecommunication": "Telecom", "Fast Moving Consumer Goods": "FMCG",
            "Automobile and Auto Components": "Auto", "Oil Gas & Consumable Fuels": "Oil and gas",
            "Metals & Mining": "Metals", "Construction Materials": "Construction materials",
            "Financial Services": "Financials", "Consumer Durables": "Consumer durables"}.get(s, s)


def why_spoken(w: str) -> str:
    w = w.replace("₹", "").replace("×", " times").replace(" · ", ", ").replace("DMA", "day average")
    return w[0].lower() + w[1:] if w else w


def spoken_time(t: str) -> str:
    try:
        h, m = int(t[:2]), int(t[3:5])
    except (ValueError, IndexError):
        return t
    ap = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {ap}" if m else f"{h12} {ap}"


if __name__ == "__main__":
    c = json.load(open(sys.argv[1]))
    s = build(c)
    json.dump(s, open(sys.argv[2], "w"), indent=1, ensure_ascii=False)
    print(json.dumps({"segments": [(x["id"], len(x["beats"])) for x in s["segments"]], "words": sum(len(b["text"].split()) for x in s["segments"] for b in x["beats"]),
                      "trace": len(s["trace"])}))
