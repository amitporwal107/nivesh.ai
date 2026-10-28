"""Closing Bell — write the night's anchor script from cards.json with fixed templates, in English, Hindi,
Tamil, Marathi and Gujarati (i18n.py holds the templates).

Every number in the narration (all five languages) and the on-screen captions goes through `Facts`, which reads
it from cards.json by path and records (text, path). checks.py re-reads each path and rejects the script if any
number in any language was not recorded this way. Nothing is invented: when a figure is missing the sentence that
needs it is left out. Each beat is a list of (template key, arguments); the same arguments render every language.

usage: python3 script_gen.py CARDS.json OUT_script.json
Output: {"segments": [{id, tag, title, beats: [{who, text, texts{lang}, parts, sup, card, focus}]}],
         "headlines": [...], "languages": [...], "trace": [{"s": "4,240", "path": "fii.fii_net", "fmt": "in0"}...]}
`text` is the English narration (kept for the graphics/recorder/transcript code paths that read it).
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

import i18n
from i18n import LANGS


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
        self.trace: List[Dict[str, Any]] = []

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
        """A text field taken verbatim from cards (idea reason, strategy label): its numbers are traced to it."""
        v = self.get(path)
        if v is None:
            raise KeyError(path)
        s = str(v)
        for tok in re.findall(r"\d[\d,]*(?:\.\d+)?", s):
            self.trace.append({"s": tok, "path": path, "fmt": "text", "abs": True})
        return s

    def date(self, path: str, style: str = "long") -> str:
        """English '2 September' / '2 Sep' (captions)."""
        import datetime as _d
        v = self.get(path)
        if v is None:
            raise KeyError(path)
        dd = _d.date.fromisoformat(str(v)[:10])
        self.trace.append({"s": str(dd.day), "path": path, "fmt": "day", "abs": True})
        return f"{dd.day} {dd:%B}" if style == "long" else f"{dd.day} {dd:%b}"

    def dt(self, path: str) -> Dict[str, str]:
        """A date argument rendered per language ('2 सितंबर', 'செப்டம்பர் 2'); the day number is traced."""
        v = self.get(path)
        if v is None:
            raise KeyError(path)
        self.trace.append({"s": str(int(str(v)[8:10])), "path": path, "fmt": "day", "abs": True})
        return {"k": "date", "iso": str(v)[:10]}

    def time(self, path: str) -> Dict[str, str]:
        """A clock time ('16:00') rendered per language ('4 PM', 'शाम 4 बजे'); hour and minute tokens are traced."""
        v = str(self.get(path) or "")
        if not re.fullmatch(r"\d\d:\d\d", v):
            raise KeyError(path)
        h, m = int(v[:2]), v[3:]
        for tok in {v[:2], m, str(h % 12 or 12)}:
            self.trace.append({"s": tok, "path": path, "fmt": "time", "abs": True})
        return {"k": "time", "hhmm": v}


def pick_i(day: str, salt: str, n: int) -> int:
    """Deterministic variety: the same date always gets the same wording."""
    return int(hashlib.sha256((day + salt).encode()).hexdigest(), 16) % n


def updown(v: float) -> str:
    return "up" if v > 0 else "down" if v < 0 else "flat"


def sgn_txt(F: Facts, path: str, fmt: str = "2", unit: str = "%") -> str:
    v = F.get(path)
    s = F.n(path, fmt)
    return ("+" if v > 0 else "−" if v < 0 else "") + s + unit


def L_(items: List[Any]) -> Dict[str, Any]:
    return {"k": "list", "items": items}


def M(key: str, **args) -> Dict[str, Any]:
    return {"k": "msg", "key": key, "args": args}


def IX(name: str) -> Dict[str, str]:
    return {"k": "index", "en": name}


Part = Tuple[str, Dict[str, Any]]


def build(cards: Dict[str, Any]) -> Dict[str, Any]:
    F = Facts(cards)
    L = cards["L"]
    day = cards["date"]
    idx = {x["name"]: i for i, x in enumerate(cards["idx"])}
    segs: List[Dict[str, Any]] = []

    def ip(name: str, key: str) -> str:
        return f"idx.{idx[name]}.{key}"

    def beat(parts: List[Part], sup: str, card: Optional[str], f: Optional[dict] = None) -> dict:
        texts = {lang: i18n.spoken(lang, "".join(i18n.render(lang, k, a) for k, a in parts)) for lang in LANGS}
        texts["en"] = texts["en"][:1].upper() + texts["en"][1:]
        return {"who": "A", "text": texts["en"], "texts": texts, "parts": [{"key": k, "args": a} for k, a in parts],
                "sup": sup, "card": card, "focus": f or {}}

    n50p = F.get(ip("Nifty 50", "pct")) if "Nifty 50" in idx else None
    sc = F.get(ip("Nifty Smallcap 250", "pct")) if "Nifty Smallcap 250" in idx else None
    mv = cards["movers"]
    n500 = mv.get("Nifty 500") or {}

    # ------------------------------------------------------------ s0 headlines
    heads: List[Dict[str, str]] = []
    hb: List[dict] = []
    if n50p is not None:
        flat = abs(n50p) < 0.15
        if flat and sc is not None and abs(sc) > 1:
            up = sc > 0
            big = f'Nifty flat, <span class="{"up" if up else "dn"}">smallcaps {"sprint" if up else "slide"}</span>'
            parts: List[Part] = [("h1_flat_sc.up" if up else "h1_flat_sc.down", {"p": F.n(ip("Nifty Smallcap 250", "pct"), "1")})]
        elif flat:
            big = 'Nifty <span class="up">steady</span>'
            parts = [("h1_flat", {"close": F.n(ip("Nifty 50", "close"), "in2")})]
        else:
            d = updown(n50p)
            big = f'Nifty <span class="{"up" if d == "up" else "dn"}">{"closes higher" if d == "up" else "closes lower"}</span>'
            parts = [("h1_move", {"d": d, "p": F.n(ip("Nifty 50", "pct")), "close": F.n(ip("Nifty 50", "close"), "in2")})]
        small = (f"Nifty 50 {F.n(ip('Nifty 50', 'close'), 'in2')} {sgn_txt(F, ip('Nifty 50', 'pct'))}"
                 + (f" · Smallcap 250 {sgn_txt(F, ip('Nifty Smallcap 250', 'pct'))}" if sc is not None else "")
                 + (f" · {F.n('movers.Nifty 500.adv', 'int')} of {F.n('movers.Nifty 500.n', 'int')} Nifty 500 stocks up" if n500 else ""))
        heads.append({"kicker": "Markets", "big": big, "small": small}); hb.append(beat(parts, small, "h1"))
    f = cards["fii"]
    if f.get("available"):
        buy = f["fii_net"] >= 0
        b = "buy" if buy else "sell"
        since = f.get("biggest_since")
        args = {"b": b, "amt": F.n("fii.fii_net", "in0")}
        if since:
            args["since"] = F.dt("fii.biggest_since")
        small = (f"FIIs {'+' if buy else '−'}₹{F.n('fii.fii_net', 'in0')} Cr · DIIs {'+' if f['dii_net'] >= 0 else '−'}₹{F.n('fii.dii_net', 'in0')} Cr"
                 + (f" · biggest FII {'buying' if buy else 'selling'} day since {F.date('fii.biggest_since')}" if since else "")
                 + ("" if f.get("same_day") else f" · figures for {F.date('fii.date')}"))
        heads.append({"kicker": "Flows", "big": f'Foreign investors <span class="{"up" if buy else "dn"}">{"buy" if buy else "sell"}</span>', "small": small})
        hb.append(beat([("h2_since" if since else "h2", args)], small, "h2"))
    ru = cards["res_up"]
    if len(ru) >= 2:
        k = min(4, len(ru))
        small = " · ".join(f"{ru[i]['name']} {sgn_txt(F, f'res_up.{i}.pct', '1')}" for i in range(k))
        heads.append({"kicker": "Results", "big": 'Results-day <span class="up">rallies</span>', "small": small})
        hb.append(beat([("h3", {"names": L_([ru[i]["name"] for i in range(k)])})], small, "h3"))
    secs = cards["sectors"]
    if secs:
        worst, best = secs[-1], secs[0]
        if worst["d1"] <= -1.0 and abs(worst["d1"]) >= abs(best["d1"]) * 0.6:
            s, i, up = worst, len(secs) - 1, False
        else:
            s, i, up = best, 0, True
        v = pick_i(day, "h4", 3)
        word = (["leads", "shines", "outperforms"] if up else ["cracks", "slides", "lags"])[v]
        small = f"Nifty {s['name']} {sgn_txt(F, f'sectors.{i}.d1')}" + (
            f", {F.n(f'sectors.{i}.adv', 'int')} of {F.n(f'sectors.{i}.n', 'int')} up" if s.get("adv") is not None and s.get("n") else "")
        heads.append({"kicker": "Sectors", "big": f'{s["name"]} <span class="{"up" if up else "dn"}">{word}</span>', "small": small})
        hb.append(beat([("h4.lead" if up else "h4.weak", {"sector": s["name"], "p": F.n(f"sectors.{i}.d1")})], small, "h4"))
    title = f"Closing Bell · {L['day_long']}"
    s0 = [beat([(f"welcome.{pick_i(day, 'welcome', 3)}", {})], title, "title"), beat([("heads_intro", {})], title, "title")] + hb
    segs.append({"id": "s0", "tag": "HEADLINES", "title": "Tonight's headlines", "beats": s0})

    # ------------------------------------------------------------ s1 market wrap
    s1 = []
    if n50p is not None:
        pts = F.get(ip("Nifty 50", "pts"))
        s1.append(beat([("score", {"close": F.n(ip("Nifty 50", "close"), "in2"), "d": updown(pts), "pts": F.n(ip("Nifty 50", "pts")),
                                   "pct": F.n(ip("Nifty 50", "pct"))})],
                       f"Nifty 50 {F.n(ip('Nifty 50', 'close'), 'in2')} · {sgn_txt(F, ip('Nifty 50', 'pts'), '2', ' pts')} ({sgn_txt(F, ip('Nifty 50', 'pct'))}) · "
                       f"range {F.n('day.low', 'in2')}–{F.n('day.high', 'in2')}", "idx", {"desk": "overview"}))
        items, sparts = [], []
        for name, said in (("Nifty Bank", "Bank Nifty"), ("Nifty Next 50", "the Next 50"), ("Nifty Midcap 150", "the Midcap 150"),
                           ("Nifty Smallcap 250", "the Smallcap 250")):
            if name in idx:
                v = F.get(ip(name, "pct"))
                if v:
                    items.append(M("broad_item", idx=IX(said), d=updown(v), p=F.n(ip(name, "pct"))))
                else:
                    items.append(M("broad_flat", idx=IX(said)))
                sparts.append(f"{said.replace('the ', '')} {sgn_txt(F, ip(name, 'pct'))}")
        if items:
            s1.append(beat([("broad", {"items": L_(items)})], " · ".join(sparts), "idx"))
        if n500 and "India VIX" in idx:
            adv, dec = n500["adv"], n500["dec"]
            ratio = adv / dec if dec else 99
            kind = "strong" if ratio >= 1.5 else "weak" if ratio <= 0.67 else "mixed"
            vix = F.get(ip("India VIX", "pct"))
            s1.append(beat([(f"breadth.{kind}", {"adv": F.n("movers.Nifty 500.adv", "int"), "dec": F.n("movers.Nifty 500.dec", "int")}),
                            ("sp", {}), ("vix", {"d": updown(vix), "p": F.n(ip("India VIX", "pct"), "1"), "close": F.n(ip("India VIX", "close"), "1")})],
                           f"Nifty 500: {F.n('movers.Nifty 500.adv', 'int')} up · {F.n('movers.Nifty 500.dec', 'int')} down · India VIX "
                           f"{F.n(ip('India VIX', 'close'), '2')} ({sgn_txt(F, ip('India VIX', 'pct'))})", "brd"))
    rg = cards.get("regime") or {}
    if rg.get("label"):
        s1.append(beat([("regime", {"label": rg["label"], "t": rg.get("trend") or "flat"})],
                       f"Desk regime: {rg['label']} · trend {rg.get('trend') or '—'} · as of {L['day_short']}", None, {"desk": "regime"}))
    segs.append({"id": "s1", "tag": "MARKET WRAP", "title": "How the market closed", "beats": s1})

    # ------------------------------------------------------------ s2 results
    s2 = []
    cn = cards.get("counts") or {}
    if cn.get("declared") is not None:
        if cn.get("upcoming"):
            parts = [("rw_up", {"declared": F.n("counts.declared", "int"), "upcoming": F.n("counts.upcoming", "int")})]
        else:
            parts = [("rw", {"declared": F.n("counts.declared", "int")})]
        s2.append(beat(parts, f"Results week · {F.n('counts.declared', 'int')} declared" + (f" · {F.n('counts.upcoming', 'int')} upcoming" if cn.get("upcoming") else ""),
                       None, {"desk": "results"}))
        if cn.get("above") is not None:
            s2.append(beat([("basis", {"above": F.n("counts.above", "int"), "in_line": F.n("counts.in_line", "int"), "below": F.n("counts.below", "int")})],
                           f"Vs the company's own past trend, not consensus · {F.n('counts.above', 'int')} above · {F.n('counts.in_line', 'int')} in line · "
                           f"{F.n('counts.below', 'int')} below", None))
    if ru:
        a = ru[0]
        parts = [("res_top", {"name": a["name"], "pct": F.n("res_up.0.pct", "1")})]
        if a.get("volx"):
            parts.append(("res_top_vol", {"volx": F.n("res_up.0.volx", "1" if a["volx"] < 10 else "0")}))
        if a.get("pat_yoy") is not None:
            parts.append(("res_top_pat", {"d": "up" if a["pat_yoy"] > 0 else "down", "pat": F.n("res_up.0.pat_yoy", "0")}))
        parts.append(("stop", {}))
        sup = f"{a['name']} {sgn_txt(F, 'res_up.0.pct')}" + (f" · volume {F.n('res_up.0.volx', '0')}× its 20-day average" if a.get("volx") else "") + (
            f" · PAT {sgn_txt(F, 'res_up.0.pat_yoy', '0')} YoY" if a.get("pat_yoy") is not None else "")
        s2.append(beat(parts, sup, "res", {"search": [a["name"]], "syms": [a["sym"]]}))
        if len(ru) > 1:
            rest = ru[1:4]
            s2.append(beat([("res_more", {"items": L_([M("pct_up", name=x["name"], pct=F.n(f"res_up.{i + 1}.pct", "1")) for i, x in enumerate(rest)])})],
                           " · ".join(f"{x['name']} {sgn_txt(F, f'res_up.{i + 1}.pct')}" for i, x in enumerate(rest)), "res",
                           {"search": [x["name"] for x in rest], "syms": [x["sym"] for x in rest]}))
    rd = cards["res_dn"]
    if rd:
        k = min(3, len(rd))
        items = []
        for i in range(k):
            if i == 0 and rd[0].get("volx") and rd[0]["volx"] >= 2.5:
                items.append(M("pct_dn_vol", name=rd[0]["name"], pct=F.n("res_dn.0.pct", "1"), volx=F.n("res_dn.0.volx", "1" if rd[0]["volx"] < 10 else "0")))
            else:
                items.append(M("pct_dn", name=rd[i]["name"], pct=F.n(f"res_dn.{i}.pct", "1")))
        s2.append(beat([("res_down", {"items": L_(items)})], " · ".join(f"{rd[i]['name']} {sgn_txt(F, f'res_dn.{i}.pct')}" for i in range(k)), "res",
                       {"search": [rd[0]["name"]], "syms": [rd[0]["sym"]]}))
    af = cards["after"]
    if af:
        ups = [(i, a) for i, a in enumerate(af) if a["pat_yoy"] >= 0][:3]
        dns = [(i, a) for i, a in enumerate(af) if a["pat_yoy"] < 0][:4]
        dow = {"k": "dow", "iso": L["next_date"]}
        if ups:
            i0, a0 = ups[0]
            parts = [("after_lead", {}), ("sp", {}), ("after_first", {"name": a0["name"], "p": F.n(f"after.{i0}.pat_yoy", "1"), "pat": F.n(f"after.{i0}.pat", "in0")})]
            if len(ups) > 1:
                parts.append(("after_more", {"items": L_([M("pat_item", name=a["name"], p=F.n(f"after.{i}.pat_yoy", "1")) for i, a in ups[1:]])}))
            parts.append(("stop", {}))
            s2.append(beat(parts, "After the close (net profit, YoY): " + " · ".join(f"{a['name']} {sgn_txt(F, f'after.{i}.pat_yoy', '1')}" for i, a in ups),
                           "after", {"syms": [a["sym"] for _, a in ups]}))
        if dns:
            parts = ([] if ups else [("after_lead", {}), ("sp", {})]) + [
                ("after_down", {"items": L_([M("pat_item", name=a["name"], p=F.n(f"after.{i}.pat_yoy", "1")) for i, a in dns]), "dow": dow})]
            s2.append(beat(parts, " · ".join(f"{a['name']} {sgn_txt(F, f'after.{i}.pat_yoy', '1')}" for i, a in dns) + " (net profit, YoY)",
                           "after", {"syms": [a["sym"] for _, a in dns]}))
    segs.append({"id": "s2", "tag": "RESULTS", "title": "Results and the market's verdict", "beats": s2})

    # ------------------------------------------------------------ s3 sector rotation
    s3 = []
    if secs:
        tops = [i for i in range(min(5, len(secs))) if secs[i]["d1"] > 0]
        bots = [i for i in range(len(secs) - 1, max(len(secs) - 5, -1), -1) if secs[i]["d1"] < 0]
        if tops:
            t0 = tops[0]
            parts = [("rot_top", {"sector": secs[t0]["name"], "p": F.n(f"sectors.{t0}.d1")})]
            if len(tops) > 1:
                parts.append(("rot_follow", {"names": L_([secs[i]["name"] for i in tops[1:]])}))
            s3.append(beat(parts, "Day: " + " · ".join(f"{secs[i]['name']} {sgn_txt(F, f'sectors.{i}.d1')}" for i in tops), "sec", {"desk": "sectors"}))
        if bots:
            b0 = bots[0]
            parts = [("rot_weak", {"sector": secs[b0]["name"], "p": F.n(f"sectors.{b0}.d1")})]
            if secs[b0].get("dec") is not None and secs[b0].get("n"):
                parts.append(("rot_weak_n", {"dec": F.n(f"sectors.{b0}.dec", "int"), "n": F.n(f"sectors.{b0}.n", "int")}))
            s3.append(beat(parts, " · ".join(f"{secs[i]['name']} {sgn_txt(F, f'sectors.{i}.d1')}" for i in bots), "sec"))
        m_sorted = sorted(range(len(secs)), key=lambda i: secs[i]["m1"] if secs[i].get("m1") is not None else 0)
        lo, hi = m_sorted[0], m_sorted[-1]
        rot = cards.get("rotation") or {}
        parts = [("rot_month", {"hi": secs[hi]["name"], "phi": F.n(f"sectors.{hi}.m1", "1"), "dh": updown(secs[hi]["m1"]),
                                "lo": secs[lo]["name"], "plo": F.n(f"sectors.{lo}.m1", "1"), "dl": updown(secs[lo]["m1"])})]
        sup = f"Month: Nifty {secs[hi]['name']} {sgn_txt(F, f'sectors.{hi}.m1')} · {secs[lo]['name']} {sgn_txt(F, f'sectors.{lo}.m1')}"
        if rot.get("leading"):
            lead = [short_sector(x) for x in rot["leading"][:3]]
            parts.append(("rot_leading", {"names": L_(lead)}))
            sup += " · Leading: " + " · ".join(lead)
        s3.append(beat(parts, sup, None, {"desk": "matrix"}))
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
        parts = ([("mv_intro", {})] if k == 0 else []) + [("mv_head", {"idx": IX(name), "adv": F.n(f"{mp}.adv", "int"), "dec": F.n(f"{mp}.dec", "int")})]
        if ups:
            parts.append(("mv_ups", {"items": L_([M("pct_item", name=x["name"], pct=F.n(f"{mp}.top.{i}.pct", "1")) for i, x in ups])}))
        if dns:
            parts.append(("mv_downs", {"items": L_([M("pct_item", name=x["name"], pct=F.n(f"{mp}.bottom.{i}.pct", "1")) for i, x in dns])}))
        sup = f"{name}: {F.n(f'{mp}.adv', 'int')} up · {F.n(f'{mp}.dec', 'int')} down · " + " · ".join(
            [f"{x['name']} {sgn_txt(F, f'{mp}.top.{i}.pct')}" for i, x in ups] + [f"{x['name']} {sgn_txt(F, f'{mp}.bottom.{i}.pct')}" for i, x in dns])
        s4.append(beat(parts, sup, card, {"index": m["code"], "syms": [x["sym"] for _, x in ups + dns]}))
    if n500:
        ss = [(i, s) for i, s in enumerate(n500["sectors"]) if s["n"] >= 4]
        full = sorted([(i, s) for i, s in ss if s["adv"] == s["n"]], key=lambda t: -t[1]["n"])[:2]
        worst = [t for t in sorted(ss, key=lambda t: t[1]["adv"] / t[1]["n"])[:1] if t[1]["adv"] / t[1]["n"] < 0.35]
        items, sb = [], []
        for i, s in full:
            items.append(M("sec_full", sector=short_sector(s["sector"])))
            sb.append(f"{short_sector(s['sector'])} {F.n(f'movers.Nifty 500.sectors.{i}.adv', 'int')}/{F.n(f'movers.Nifty 500.sectors.{i}.n', 'int')}")
        for i, s in worst:
            adv, n = F.n(f"movers.Nifty 500.sectors.{i}.adv", "int"), F.n(f"movers.Nifty 500.sectors.{i}.n", "int")
            items.append(M("sec_worst", sector=short_sector(s["sector"]), adv=adv, n=n))
            sb.append(f"{short_sector(s['sector'])} {adv}/{n}")
        if items:
            s4.append(beat([("sec_intro", {"items": L_(items)})], "Nifty 500 by sector: " + " · ".join(sb), "s500",
                           {"sectors": [s["sector"] for _, s in full + worst]}))
    segs.append({"id": "s4", "tag": "MOVERS & SHAKERS", "title": "Nifty 50 · 100 · 200 · 500", "beats": s4})

    # ------------------------------------------------------------ s5 FII / DII
    s5 = []
    if f.get("available"):
        buy, dbuy = f["fii_net"] >= 0, f["dii_net"] >= 0
        when = M("today") if f.get("same_day") else M("on_date", date=F.dt("fii.date"))
        parts = [("flows_fii", {"b": "buy" if buy else "sell", "fii": F.n("fii.fii_net", "in0"), "when": when})]
        if f.get("biggest_since"):
            parts.append(("flows_since", {"b": "buy" if buy else "sell", "since": F.dt("fii.biggest_since")}))
        parts.append(("flows_dii", {"db": "buy" if dbuy else "sell", "dii": F.n("fii.dii_net", "in0")}))
        s5.append(beat(parts, f"{F.date('fii.date', 'short')} (provisional): FII {'+' if buy else '−'}₹{F.n('fii.fii_net', 'in0')} Cr · "
                              f"DII {'+' if dbuy else '−'}₹{F.n('fii.dii_net', 'in0')} Cr", "fii", {"desk": "smartmoney"}))
        parts = [("mtd", {"month": {"k": "month", "m": int(day[5:7])}, "b1": "buy" if f["mtd_fii"] >= 0 else "sell", "f1": F.n("fii.mtd_fii", "in0"),
                          "b2": "buy" if f["mtd_dii"] >= 0 else "sell", "f2": F.n("fii.mtd_dii", "in0")})]
        sup = (f"{f['month']} so far: FII {'+' if f['mtd_fii'] >= 0 else '−'}₹{F.n('fii.mtd_fii', 'in0')} Cr · "
               f"DII {'+' if f['mtd_dii'] >= 0 else '−'}₹{F.n('fii.mtd_dii', 'in0')} Cr")
        if f.get("m3_fii") is not None:
            parts.append(("m3", {"b3": "buy" if f["m3_fii"] >= 0 else "sell", "f3": F.n("fii.m3_fii", "in0"),
                                 "b4": "buy" if f["m3_dii"] >= 0 else "sell", "f4": F.n("fii.m3_dii", "in0")}))
            sup += f" · Three months: FII {'+' if f['m3_fii'] >= 0 else '−'}₹{F.n('fii.m3_fii', 'in0')} Cr · DII {'+' if f['m3_dii'] >= 0 else '−'}₹{F.n('fii.m3_dii', 'in0')} Cr"
        s5.append(beat(parts, sup, "fii"))
        if f.get("desk_flow_to") and f["desk_flow_to"] < f["date"]:
            s5.append(beat([("flow_chart", {"date": F.dt("fii.desk_flow_to")})],
                           f"Desk flow chart runs to {F.date('fii.desk_flow_to', 'short')} · today joins with the next NSE load", None))
        else:
            s5.append(beat([("flow_signal", {})], "One day of flows is a signal, not a trend", None))
    segs.append({"id": "s5", "tag": "FII / DII", "title": "Follow the money", "beats": s5})

    # ------------------------------------------------------------ s6 top 10 ideas
    s6 = []
    ideas = cards["ideas"]
    if ideas:
        s6.append(beat([("ideas_intro", {})], "Ideas for review, not recommendations · no measurable ranking skill yet", "ideas", {"desk": "scanner"}))
        i0, i1 = ideas[0], ideas[1] if len(ideas) > 1 else None
        parts = [("ideas_lead", {"names": L_([i0["name"]] + ([i1["name"]] if i1 else []))})]
        if i0.get("why"):
            parts.append(("ideas_why", {"name": i0["name"], "why": why_spoken(F.t("ideas.0.why"))}))
        s6.append(beat(parts, f"{i0['name']}: {F.t('ideas.0.why')}" + (f" · {i1['name']}: {F.t('ideas.1.why')}" if i1 and i1.get("why") else ""), "ideas",
                       {"syms": [i0["sym"]] + ([i1["sym"]] if i1 else [])}))
        if len(ideas) > 2:
            rest = [x["name"] for x in ideas[2:]]
            s6.append(beat([("ideas_rest", {"names": L_(rest)})], " · ".join(rest), None, {"syms": [x["sym"] for x in ideas[2:]]}))
    fx = cards["fno"]
    if fx and rg.get("label"):
        x0 = fx[0]
        sym = {"NIFTY": "Nifty", "BANKNIFTY": "Bank Nifty"}.get(x0["sym"], x0["sym"])
        parts = [("fno", {"label": rg["label"], "t": rg.get("trend") or "flat", "sym": sym,
                          "strategy": F.t("fno.0.label").lower(), "expiry": F.dt("fno.0.expiry")})]
        if any(v.get("view") == "down" for v in fx) and ideas:
            parts.append(("fno_conflict", {}))
        s6.append(beat(parts, f"F&O board: regime {rg['label']} · trend {rg.get('trend') or '—'} · {x0['sym']} {F.t('fno.0.label')}, "
                              f"{F.date('fno.0.expiry', 'short')} expiry", "fno", {"desk": "fno"}))
    segs.append({"id": "s6", "tag": "TOP 10 IDEAS", "title": "The desk's ideas for review", "beats": s6})

    # ------------------------------------------------------------ s7 what to watch
    s7 = []
    mac = cards.get("macro") or []
    dow = {"k": "dow", "iso": L["next_date"]}
    if mac:
        items = [M("macro_item", event={"k": "macro", "code": m[4] if len(m) > 4 else "", "name": m[1], "country": m[3]}, time=F.time(f"macro.{i}.0"))
                 for i, m in enumerate(mac[:2])]
        s7.append(beat([("watch_macro", {"dow": dow, "items": L_(items)})],
                       " · ".join(f"{L['next_short'][:3]} {F.t(f'macro.{i}.0')} IST {('India' if m[3] == 'IN' else 'US')} {m[1]}" for i, m in enumerate(mac[:2])), "watch",
                       {"macro": [f"{L['next_date']}|{m[4]}" for m in mac[:2] if len(m) > 4 and m[4]]}))
    due = cards.get("due") or []
    react = [a["name"] for a in af][:4]
    lead = M("plus") if mac else M("dow_lead", dow=dow)
    key = "watch_both" if react and due else "watch_react" if react else "watch_due" if due else None
    if key:
        s7.append(beat([(key, {"lead": lead, "react": L_(react), "due": L_(due[:3])})],
                       f"Results due {L['next_short'][:3]}: " + " · ".join(due[:6]) if due else "First reaction: " + " · ".join(react), "watch",
                       {"search": due[:1], "syms": (cards.get("due_syms") or [])[:1]}))
    s7.append(beat([(f"signoff.{pick_i(day, 'signoff', 2)}", {})], "Source: NSE end-of-day data and exchange filings, read on the Nivesh Smart Trading Desk", "end"))
    s7.append(beat([("disclaimer", {})], "Market information and education, not investment advice", "end"))
    segs.append({"id": "s7", "tag": "WHAT TO WATCH", "title": L["next_title"], "beats": s7})

    segs = [s for s in segs if s["beats"]]
    return {"schema": "closing-bell-script-v2", "date": day, "languages": LANGS, "segments": segs, "headlines": heads, "trace": F.trace}


def short_sector(s: str) -> str:
    return {"Information Technology": "IT", "Telecommunication": "Telecom", "Fast Moving Consumer Goods": "FMCG",
            "Automobile and Auto Components": "Auto", "Oil Gas & Consumable Fuels": "Oil and gas",
            "Metals & Mining": "Metals", "Construction Materials": "Construction materials",
            "Financial Services": "Financials", "Consumer Durables": "Consumer durables"}.get(s, s)


def why_spoken(w: str) -> str:
    w = w.replace("₹", "").replace("×", " times").replace(" · ", ", ").replace("DMA", "day average")
    return w[0].lower() + w[1:] if w else w


if __name__ == "__main__":
    c = json.load(open(sys.argv[1]))
    s = build(c)
    json.dump(s, open(sys.argv[2], "w"), indent=1, ensure_ascii=False)
    print(json.dumps({"segments": [(x["id"], len(x["beats"])) for x in s["segments"]],
                      "words_en": sum(len(b["text"].split()) for x in s["segments"] for b in x["beats"]),
                      "languages": s["languages"], "trace": len(s["trace"])}))
