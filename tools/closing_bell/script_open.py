"""Opening Bell — the morning anchor script from cards_open.py's cards, in the same five languages and with the
same rules as the evening (fixed templates, every number traced through Facts, nothing invented).

Segments (the list is the same in both build phases, so the 9:08 rebuild only re-renders s0 and o2):
  s0 headlines · o1 previous session · o2 pre-open · o3 ranges & levels · o4 the AI lists · o5 today
Phase A (about 07:30, no pre-open yet) gives o2 a one-line placeholder and a long minimum length so the desk
footage recorded then covers the final segment; phase B (09:08) writes the real o2 and the pre-open headline.
"""
from __future__ import annotations

from typing import Any, Dict, List

import i18n_open  # noqa: F401 — registers the morning templates
from i18n import LANGS
from script_gen import Facts, IX, L_, M, ai_lists_beats, make_beat as beat, pick_i, sgn_txt, updown

ORDER = ["s0", "o1", "o2", "o3", "o4", "o5"]
O2_PLACEHOLDER_LEN = 80.0       # seconds of desk footage recorded in phase A for the pre-open segment


def build(cards: Dict[str, Any]) -> Dict[str, Any]:
    F = Facts(cards)
    L, day, prev = cards["L"], cards["date"], cards["prev"]
    idx = {x["name"]: i for i, x in enumerate(cards["idx"])}
    ip = lambda name, key: f"idx.{idx[name]}.{key}"
    dow_prev = {"k": "dow", "iso": prev}
    pre = cards.get("pre") or None
    lv, ideas = cards.get("lv") or {}, cards["ideas"]
    oi = lv.get("oi") or {}
    segs: List[Dict[str, Any]] = []

    # ------------------------------------------------------------ s0 headlines
    heads: List[Dict[str, str]] = []
    hb: List[dict] = []

    def head(kicker: str, big: str, small: str, parts) -> None:
        heads.append({"kicker": kicker, "big": big, "small": small})
        hb.append(beat(parts, small, f"h{len(heads)}"))

    if pre and pre.get("nifty"):
        n = pre["nifty"]
        k = "flat" if n["flat"] else updown(n["pct"])
        big = {"up": 'Pre-open points <span class="up">higher</span>', "down": 'Pre-open points <span class="dn">lower</span>',
               "flat": 'Pre-open: a <span class="up">flat</span> start'}[k]
        small = (f"Nifty indicated near {F.n('pre.nifty.ind', 'in0')} ({sgn_txt(F, 'pre.nifty.pct')}) · F&O {F.n('pre.adv', 'int')} up · "
                 f"{F.n('pre.dec', 'int')} down · NSE pre-open {F.t('pre.hhmm')} IST")
        head("Pre-open", big, small, [(f"oh_pre.{k}", {"lvl": F.n("pre.nifty.ind", "in0")})])
    else:
        head("Pre-open", 'Pre-open <span class="up">at the bell</span>', "NSE pre-open call auction · prices added as soon as they land",
             [("oh_pre.wait", {})])
    if lv.get("pts") and oi:
        small = (f"India VIX {F.n('lv.vix')} · about ±{F.n('lv.pts', 'int')} pts · OI support {F.n('lv.oi.sup', 'in0')} · "
                 f"resistance {F.n('lv.oi.res', 'in0')}")
        head("Range to watch", f'Range <span class="up">{F.n("lv.lo", "in0")}–{F.n("lv.hi", "in0")}</span>', small,
             [("oh_range", {"pts": F.n("lv.pts", "int"), "lo": F.n("lv.lo", "in0"), "hi": F.n("lv.hi", "in0")})])
    if len(ideas) >= 2:
        k = min(3, len(ideas))
        small = "AI Top 10 · " + " · ".join(f"#{F.n(f'ideas.{i}.rank', 'int')} {ideas[i]['name']}" for i in range(k))
        head("AI Top 10", f'AI list: <span class="up">{ideas[0]["name"]}</span> leads', small,
             [("oh_ai", {"names": L_([ideas[i]["name"] for i in range(min(2, len(ideas)))])})])
    due = cards.get("due_today") or []
    if oi.get("expiry_today") or due:
        parts, bits = [], []
        if oi.get("expiry_today"):
            parts.append(("oh_expiry", {}))
            bits.append(f"Nifty expiry today" + (f" · {F.n('lv.oi.atm', 'in0')} straddle {F.n('lv.oi.straddle')} pts" if oi.get("straddle") else ""))
        if due:
            if parts:
                parts.append(("sp", {}))
            parts.append(("oh_results", {"names": L_(due[:3])}))
            bits.append("Results: " + " · ".join(due[:5]))
        big = 'Nifty <span class="up">expiry day</span>' if oi.get("expiry_today") else 'Results <span class="up">today</span>'
        head("Today", big, " · ".join(bits), parts)
    title = f"Opening Bell · {L['day_long']}"
    s0 = [beat([(f"o_welcome.{pick_i(day, 'o_welcome', 3)}", {})], title, "title"), beat([("o_heads", {})], title, "title")] + hb
    segs.append({"id": "s0", "tag": "HEADLINES", "title": "This morning's headlines", "beats": s0})

    # ------------------------------------------------------------ o1 previous session + overnight
    o1 = []
    if "Nifty 50" in idx:
        pts = F.get(ip("Nifty 50", "pts"))
        o1.append(beat([("o_recap", {"dow": dow_prev, "close": F.n(ip("Nifty 50", "close"), "in2"), "d": updown(pts),
                                     "pts": F.n(ip("Nifty 50", "pts")), "pct": F.n(ip("Nifty 50", "pct"))})],
                       f"{F.date('prev', 'short')} close: Nifty 50 {F.n(ip('Nifty 50', 'close'), 'in2')} · {sgn_txt(F, ip('Nifty 50', 'pts'), '2', ' pts')} "
                       f"({sgn_txt(F, ip('Nifty 50', 'pct'))})", "ovn", {"desk": "overview"}))
        items, sparts = [], []
        for name, said in (("Nifty Bank", "Bank Nifty"), ("Nifty Midcap 150", "the Midcap 150"), ("Nifty Smallcap 250", "the Smallcap 250")):
            if name in idx:
                v = F.get(ip(name, "pct"))
                items.append(M("broad_item", idx=IX(said), d=updown(v), p=F.n(ip(name, "pct"))) if v else M("broad_flat", idx=IX(said)))
                sparts.append(f"{said.replace('the ', '')} {sgn_txt(F, ip(name, 'pct'))}")
        if items:
            o1.append(beat([("broad", {"items": L_(items)})], " · ".join(sparts), "ovn"))
    f = cards["fii"]
    if f.get("available"):
        buy, dbuy = f["fii_net"] >= 0, f["dii_net"] >= 0
        o1.append(beat([("flows_fii", {"b": "buy" if buy else "sell", "fii": F.n("fii.fii_net", "in0"), "when": M("on_date", date=F.dt("fii.date"))}),
                        ("flows_dii", {"db": "buy" if dbuy else "sell", "dii": F.n("fii.dii_net", "in0")})],
                       f"{F.date('fii.date', 'short')} (provisional): FII {'+' if buy else '−'}₹{F.n('fii.fii_net', 'in0')} Cr · "
                       f"DII {'+' if dbuy else '−'}₹{F.n('fii.dii_net', 'in0')} Cr", "ovn"))
    mx = cards.get("mcx") or {}
    if mx.get("crude") and mx.get("gold"):
        cr, go = mx["crude"], mx["gold"]
        o1.append(beat([("o_mcx", {"crude": F.n("mcx.crude.close", "in0"), "d1": updown(cr["pct"]), "p1": F.n("mcx.crude.pct", "1"),
                                   "gold": F.n("mcx.gold.close", "in0"), "d2": updown(go["pct"]), "p2": F.n("mcx.gold.pct", "1")})],
                       f"MCX {F.date('mcx.crude.date', 'short')}: crude ₹{F.n('mcx.crude.close', 'in0')}/bbl ({sgn_txt(F, 'mcx.crude.pct', '1')}) · "
                       f"gold ₹{F.n('mcx.gold.close', 'in0')}/10 g ({sgn_txt(F, 'mcx.gold.pct', '1')})", "ovn"))
    segs.append({"id": "o1", "tag": "PREVIOUS SESSION", "title": "Where we left off, and overnight", "beats": o1})

    # ------------------------------------------------------------ o2 the pre-open (phase B), placeholder in phase A
    o2: List[dict] = []
    seg_o2: Dict[str, Any] = {"id": "o2", "tag": "PRE-OPEN", "title": "What the 9:08 pre-open says"}
    if pre and pre.get("nifty"):
        n = pre["nifty"]
        k = "flat" if n["flat"] else updown(n["pct"])
        args = {"lvl": F.n("pre.nifty.ind", "in0"), "dow": dow_prev}
        if k != "flat":
            args.update({"pct": F.n("pre.nifty.pct"), "d": k})
        o2.append(beat([(f"o_pre.{'flat' if k == 'flat' else 'move'}", args)],
                       f"Indicated Nifty {F.n('pre.nifty.ind', 'in0')} ({sgn_txt(F, 'pre.nifty.pct')}) · {F.n('pre.nifty.cover', 'int')} of "
                       f"{F.n('pre.nifty.of', 'int')} constituents priced · NSE pre-open {F.t('pre.hhmm')} IST", "pre", {"desk": "overview"}))
        o2.append(beat([("o_pre_breadth", {"adv": F.n("pre.adv", "int"), "dec": F.n("pre.dec", "int")})],
                       f"F&O pre-open: {F.n('pre.adv', 'int')} up · {F.n('pre.dec', 'int')} down · {F.n('pre.unch', 'int')} unchanged", "pre"))
        ups = list(enumerate(pre.get("ups") or []))[:3]
        if ups:
            o2.append(beat([("o_gap_up", {"items": L_([M("gap_up_item", name=x["name"], pct=F.n(f"pre.ups.{i}.pct", "1")) for i, x in ups])})],
                           "Gap-ups: " + " · ".join(f"{x['name']} {sgn_txt(F, f'pre.ups.{i}.pct', '1')}" for i, x in ups), "pre"))
        dns = list(enumerate(pre.get("dns") or []))[:3]
        if dns:
            o2.append(beat([("o_gap_dn", {"items": L_([M("gap_dn_item", name=x["name"], pct=F.n(f"pre.dns.{i}.pct", "1")) for i, x in dns])})],
                           "Gap-downs: " + " · ".join(f"{x['name']} {sgn_txt(F, f'pre.dns.{i}.pct', '1')}" for i, x in dns), "pre"))
        ga = [(i, x) for i, x in enumerate(pre.get("after") or []) if round(x["pct"], 1) != 0][:3]
        if ga:
            items = [M("gap_up_item" if x["pct"] > 0 else "gap_dn_item", name=x["name"], pct=F.n(f"pre.after.{i}.pct", "1")) for i, x in ga]
            o2.append(beat([("o_pre_after", {"dow": dow_prev, "items": L_(items)})],
                           "After the bell: " + " · ".join(f"{x['name']} {sgn_txt(F, f'pre.after.{i}.pct', '1')}" for i, x in ga), "pre",
                           {"syms": [x["sym"] for _, x in ga]}))
        gi = [(i, x) for i, x in enumerate(pre.get("ideas") or []) if round(x["pct"], 1) != 0][:4]
        if gi:
            items = [M("gap_up_item" if x["pct"] > 0 else "gap_dn_item", name=x["name"], pct=F.n(f"pre.ideas.{i}.pct", "1")) for i, x in gi]
            o2.append(beat([("o_pre_ideas", {"items": L_(items)})],
                           "AI list in the pre-open: " + " · ".join(f"#{F.n(f'pre.ideas.{i}.rank', 'int')} {x['name']} {sgn_txt(F, f'pre.ideas.{i}.pct', '1')}"
                                                                    for i, x in gi), "pre", {"syms": [x["sym"] for _, x in gi]}))
        o2.append(beat([("o_pre_note", {"time": F.time("open_time")})], f"Indicative until the {F.t('open_time')} IST open", "pre"))
    else:
        o2.append(beat([("o_pre.wait", {})], "NSE pre-open call auction · prices added as soon as they land", "pre", {"desk": "overview"}))
        seg_o2["min_len"] = O2_PLACEHOLDER_LEN
    seg_o2["beats"] = o2
    segs.append(seg_o2)

    # ------------------------------------------------------------ o3 ranges & levels (options market, not forecasts)
    o3 = []
    if lv.get("pts"):
        o3.append(beat([("o_vix", {"vix": F.n("lv.vix"), "pts": F.n("lv.pts", "int"), "lo": F.n("lv.lo", "in0"), "hi": F.n("lv.hi", "in0"), "dow": dow_prev})],
                       f"India VIX {F.n('lv.vix')} → about ±{F.n('lv.pts', 'int')} Nifty points · {F.n('lv.lo', 'in0')} to {F.n('lv.hi', 'in0')}",
                       "lvl", {"desk": "fno"}))
    if oi:
        o3.append(beat([("o_oi", {"sup": F.n("lv.oi.sup", "in0"), "res": F.n("lv.oi.res", "in0")})],
                       f"Nifty {F.date('lv.oi.expiry', 'short')} expiry · largest put OI {F.n('lv.oi.sup', 'in0')} · largest call OI {F.n('lv.oi.res', 'in0')}",
                       "lvl", {"strikes": [oi["sup"], oi["res"]]}))
        o3.append(beat([("o_pcr", {"pcr": F.n("lv.oi.pcr"), "mp": F.n("lv.oi.max_pain", "in0")})],
                       f"Put-call ratio {F.n('lv.oi.pcr')} · max pain {F.n('lv.oi.max_pain', 'in0')}", "lvl", {"strikes": [oi["max_pain"]]}))
        if oi.get("expiry_today") and oi.get("straddle"):
            o3.append(beat([("o_straddle", {"atm": F.n("lv.oi.atm", "in0"), "strad": F.n("lv.oi.straddle"), "pct": F.n("lv.oi.straddle_pct", "1")})],
                           f"{F.n('lv.oi.atm', 'in0')} straddle {F.n('lv.oi.straddle')} pts ≈ ±{F.n('lv.oi.straddle_pct', '1')}% · expiring today",
                           "lvl", {"strikes": [oi["atm"]]}))
    imp = cards.get("imp") or []
    if imp:
        o3.append(beat([("o_implied", {"expiry": F.dt("imp.0.expiry"), "items": L_([M("imp_item", name=x["name"], pct=F.n(f"imp.{i}.pct", "1"))
                                                                                    for i, x in enumerate(imp)])})],
                       f"Implied to {F.date('imp.0.expiry', 'short')} (ATM straddle): " + " · ".join(f"{x['name']} ±{F.n(f'imp.{i}.pct', '1')}%"
                                                                                                    for i, x in enumerate(imp)), "lvl"))
    if o3:
        o3.append(beat([("o_levels_note", {})], "Ranges priced by the options market, not forecasts", "lvl"))
    segs.append({"id": "o3", "tag": "RANGES & LEVELS", "title": "What the options market is pricing", "beats": o3})

    # ------------------------------------------------------------ o4 the desk's AI lists for today
    segs.append({"id": "o4", "tag": "TOP 10 AI IDEAS", "title": "Today's AI lists, idea by idea", "beats": ai_lists_beats(F, cards, "o_ai_intro")})

    # ------------------------------------------------------------ o5 today
    o5 = []
    mac = cards.get("macro") or []
    if mac:
        items = [M("macro_item", event={"k": "macro", "code": m[4] if len(m) > 4 else "", "name": m[1], "country": m[3]}, time=F.time(f"macro.{i}.0"))
                 for i, m in enumerate(mac[:2])]
        o5.append(beat([("o_macro", {"items": L_(items)})],
                       " · ".join(f"{F.t(f'macro.{i}.0')} IST {('India' if m[3] == 'IN' else 'US')} {m[1]}" for i, m in enumerate(mac[:2])), "today",
                       {"macro": [f"{day}|{m[4]}" for m in mac[:2] if len(m) > 4 and m[4]]}))
    if due:
        o5.append(beat([("o_due", {"due": L_(due[:4])})], "Results due today (F&O): " + " · ".join(due[:6]), "today",
                       {"search": due[:1], "syms": (cards.get("due_today_syms") or [])[:1]}))
    o5.append(beat([(f"o_signoff.{pick_i(day, 'o_signoff', 2)}", {"time": F.time("open_time")})],
                   "Sources: NSE pre-open and end-of-day data, NIDP option chain, MCX via TrueData · read on the Nivesh Smart Trading Desk", "end"))
    o5.append(beat([("o_disclaimer", {})], "Market information and education, not investment advice", "end"))
    segs.append({"id": "o5", "tag": "TODAY", "title": L["next_title"], "beats": o5})

    segs = [s for s in segs if s["beats"]]
    return {"schema": "opening-bell-script-v1", "kind": "opening", "date": day, "phase": "B" if pre else "A", "languages": LANGS,
            "segments": segs, "headlines": heads, "trace": F.trace}
