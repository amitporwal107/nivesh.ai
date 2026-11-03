"""The early-signals study end to end (research, read-only): which signals flagged, ahead of time, the stocks that rose
>= 5 % above the day's open — the dashboard's widgets, candidate price/volume indicators and context indicators — with the
thresholds chosen on the first sessions (train) and checked on the last ones (test).

Inputs (written by replay.py, features.py, context.py into ROOT): flags.csv, universe.csv, features.csv, context.csv, bars5/.
Outputs into ROOT: study.md (the report for the owner) and study.json.

    python -m research.early_signals.study --root /tmp/early_signals [--test-sessions 10] [--min-support 30]
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from . import outcomes as O
from . import report as R

TEST_SESSIONS = 10
SHORTLIST = 14
MIN_LIFT = 1.5
HOLD_LIFT = 1.3
MIN_TEST_SUPPORT = 15

LABELS = {
    "rvol2": "Volume so far ≥ 2× its usual by this time", "rvol3": "Volume so far ≥ 3× its usual by this time",
    "rvol5": "Volume so far ≥ 5× its usual by this time",
    "vwap_up1": "Above the day's VWAP and ≥ 1 % over the open", "vwap_up2": "Above the day's VWAP and ≥ 2 % over the open",
    "gap1_hold": "Opened ≥ 1 % up and holding above the open", "gap2_hold": "Opened ≥ 2 % up and holding above the open",
    "orb": "Above the first 15 minutes' high", "first_hour_up2": "≥ 2 % over the open at 10:15",
    "first_hour_up3": "≥ 3 % over the open at 10:15", "brk_prev_day": "Above the previous day's high",
    "brk_20d": "Above the 20-session high", "brk_52w": "Above the 52-week high", "brk_all": "Above the highest high since Apr 2024",
    "low52_recovery": "Within 15 % of the 52-week low and ≥ 1 % over the open",
    "mom_up": "Uptrend (close > EMA20 > EMA50, 20-session return > 5 %) and ≥ 1 % over the open",
    "fut_lb_prev": "Previous day futures long build-up (price up, OI up ≥ 5 %) and ≥ 1 % over the open",
    "results_pos1": "Net profit YoY ≥ 20 % announced since the previous close, and ≥ 1 % over the open",
    "results_pos3": "Net profit YoY ≥ 20 % announced in the last 3 sessions, and ≥ 1 % over the open",
    "ann_pos": "Positive announcement (orders, M&A, capex, share repurchase, rating) since the previous close, and ≥ 1 % over the open",
    "low52_quality": "Quality stock 10–30 % off its 52-week low with a rising 50-day average, and ≥ 1 % over the open",
    "accum": "Accumulation / delivery building at the previous close, and ≥ 1 % over the open",
    "mf_net_add": "More mutual-fund schemes adding than reducing (latest month), and ≥ 1 % over the open",
    "deal_prev": "Bulk / block deal on the previous session (acquiring side), and ≥ 1 % over the open",
}


def label_of(sig: str, titles: Dict[str, str]) -> str:
    if sig.startswith("k>="):
        n = sig[3:]
        return "Any dashboard widget" if n == "1" else f"{n} or more dashboard widgets at the same step"
    kind, _, name = sig.partition(":")
    if kind == "w":
        return f"Widget · {titles.get(name, name)}"
    if kind == "p":
        a, _, b = name.partition("+")
        return f"{label_of(a, titles)}  +  {label_of(b, titles)}"
    if name in LABELS:
        return LABELS[name]
    import re
    m = re.fullmatch(r"rvol(\d)_up(\d)", name)
    if m:
        return f"Volume so far ≥ {m[1]}× its usual and ≥ {m[2]} % over the open"
    m = re.fullmatch(r"fut_oi(\d+)_up(\d)", name)
    if m:
        return f"Futures OI ≥ {m[1]} % over the previous close and the price ≥ {m[2]} % over the open"
    m = re.fullmatch(r"mkt_(\w+)_up([\d.]+)", name)
    if m:
        return f"{ {'nifty50': 'Nifty 50', 'mid100': 'Midcap 100', 'small100': 'Smallcap 100'}.get(m[1], m[1]) } ≥ {m[2]} % over its open, stock ≥ 1 % over its open"
    m = re.fullmatch(r"sector_up([\d.]+)_rs", name)
    if m:
        return f"Sector index ≥ {m[1]} % over its open, the stock ahead of it and ≥ 1 % over its open"
    m = re.fullmatch(r"(call|put)_breadth(\d+)", name)
    if m:
        return f"Previous day {m[1]} OI up on ≥ {m[2]} % of strikes (nearest expiry), and ≥ 1 % over the open"
    return name


def singles(flags: pd.DataFrame, prefix: str) -> pd.DataFrame:
    """The first step of each signal per stock-day, in first_signals' shape."""
    if flags.empty:
        return pd.DataFrame(columns=["signal", "kind", "day", "symbol", "step", "price"])
    f = flags.copy()
    f["_t"] = f["step"].map(lambda s: tuple(int(x) for x in s.split(":")))
    w = f.sort_values("_t").drop_duplicates(["day", "symbol", "widget"], keep="first")
    return pd.DataFrame({"signal": prefix + w["widget"].astype(str), "kind": "single", "day": w["day"], "symbol": w["symbol"],
                         "step": w["step"], "price": w["close_at_step"]})


def score(firsts: pd.DataFrame, days: Dict, sd: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    if firsts.empty:
        return {}
    outs = O.outcomes(firsts, days)
    steps = sorted(set(R.STEP_GRID) | set(firsts["step"].unique().tolist()))
    return R.summarize(outs, sd, O.base_rates(sd, steps))


def _p(v: Optional[float], dp: int = 1) -> str:
    return "–" if v is None or v != v else f"{v * 100:.{dp}f}%"


def _x(v: Optional[float]) -> str:
    return "–" if v is None or v != v else f"{v:.2f}×"


def _m(v: Optional[float], unit: str = "") -> str:
    """Minutes, or a figure outcomes.py already gives in percent (2.4 = 2.4 %)."""
    return "–" if v is None or v != v else f"{v:.0f}{unit}" if unit == " min" else f"{v:.1f}%"


def run(root: str, test_sessions: int = TEST_SESSIONS, min_support: int = 30) -> Tuple[str, Dict[str, Any]]:
    titles = R.widget_titles()
    fw = O.read_flags(os.path.join(root, "flags.csv"))
    fi = pd.concat([O.read_flags(os.path.join(root, n)) for n in ("features.csv", "context.csv")
                    if os.path.exists(os.path.join(root, n))], ignore_index=True)
    universe = O.read_universe(os.path.join(root, "universe.csv"))
    days = O.load_days(os.path.join(root, "bars5"), set(universe["symbol"]))
    sd_all = O.stock_days(days, universe)
    # every signal only on the stock-days the replay kept (its scale check), so all signals share one universe
    keep = set(zip(sd_all["day"], sd_all["symbol"]))
    fw = fw[[k in keep for k in zip(fw["day"], fw["symbol"])]]
    if not fi.empty:
        fi = fi[[k in keep for k in zip(fi["day"], fi["symbol"])]]
    all_days = sorted(sd_all["day"].unique().tolist())
    test_days = all_days[-test_sessions:]
    train_days = [d for d in all_days if d not in set(test_days)]
    out: Dict[str, Any] = {"train_days": train_days, "test_days": test_days, "splits": {}}
    for name, dd in (("train", train_days), ("test", test_days)):
        sd = sd_all[sd_all["day"].isin(dd)]
        w = fw[fw["day"].isin(dd)]
        i = fi[fi["day"].isin(dd)] if not fi.empty else fi
        st = score(pd.concat([singles(w, "w:"), singles(i, "i:")], ignore_index=True), days, sd)
        conf = O.first_signals(w, pairs=False)
        conf = conf[conf["kind"] == "confluence"] if "kind" in conf else conf
        st.update(score(conf, days, sd))
        movers = int(pd.to_numeric(sd["t5"], errors="coerce").notna().sum())
        out["splits"][name] = {"stats": st, "stock_days": int(len(sd)), "movers": movers}
    tr = out["splits"]["train"]["stats"]
    # shortlist on TRAIN only, then pairs among the shortlist on both splits
    cand = [s for s, v in tr.items() if (s.startswith("w:") or s.startswith("i:")) and v["eligible"] >= min_support
            and (v["lift"] or 0) >= MIN_LIFT]
    cand.sort(key=lambda s: (-(tr[s]["lift"] or 0), -tr[s]["eligible"]))
    short = cand[:SHORTLIST]
    out["shortlist"] = short
    keep_w = {s[2:] for s in short if s.startswith("w:")}
    keep_i = {s[2:] for s in short if s.startswith("i:")}
    both = pd.concat([fw[fw["widget"].isin(keep_w)].assign(widget=lambda x: "w:" + x["widget"]),
                      fi[fi["widget"].isin(keep_i)].assign(widget=lambda x: "i:" + x["widget"]) if not fi.empty else fi],
                     ignore_index=True)
    for name, dd in (("train", train_days), ("test", test_days)):
        sd = sd_all[sd_all["day"].isin(dd)]
        fp = O.first_signals(both[both["day"].isin(dd)], max_k=0, pairs=True) if not both.empty else both
        fp = fp[fp["kind"] == "pair"] if not fp.empty and "kind" in fp else fp
        out["splits"][name]["stats"].update(score(fp, days, sd))
    md = render(out, titles, min_support)
    return md, out


def _row(sig: str, tr: Dict, te: Dict, titles: Dict[str, str]) -> str:
    a, b = tr.get(sig) or {}, te.get(sig) or {}
    holds = (b.get("eligible") or 0) >= MIN_TEST_SUPPORT and (b.get("lift") or 0) >= HOLD_LIFT
    verdict = "holds" if holds else ("too few in test" if (b.get("eligible") or 0) < MIN_TEST_SUPPORT else "fades")
    return (f"| {label_of(sig, titles)} | {a.get('eligible', 0)} | {_p(a.get('precision'))} | {_x(a.get('lift'))} | "
            f"{b.get('eligible', 0)} | {_p(b.get('precision'))} | {_x(b.get('lift'))} | {verdict} | "
            f"{_m(a.get('median_lead_min'), ' min')} | {_m(a.get('median_move_done_pct'))} | {_m(a.get('median_upside_pct'))} | "
            f"{_m(a.get('median_drawdown_pct'))} |")


HEAD = ("| Signal | Train flags | Train hit rate | Train lift | Test flags | Test hit rate | Test lift | Out of sample | "
        "Lead (median) | Move done at flag | Upside after | Drawdown after |\n|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|")


def render(out: Dict[str, Any], titles: Dict[str, str], min_support: int) -> str:
    tr, te = out["splits"]["train"]["stats"], out["splits"]["test"]["stats"]
    s_tr, s_te = out["splits"]["train"], out["splits"]["test"]
    L: List[str] = ["# Early signals of a ≥ 5 % rise from the open — study", ""]
    L.append(f"Sessions: train {out['train_days'][0]} … {out['train_days'][-1]} ({len(out['train_days'])}), test "
             f"{out['test_days'][0]} … {out['test_days'][-1]} ({len(out['test_days'])}). Stock-days: train {s_tr['stock_days']:,} "
             f"({s_tr['movers']:,} rose ≥ 5 % above the open), test {s_te['stock_days']:,} ({s_te['movers']:,}).")
    L += ["", "A flag counts when it fires BEFORE the stock first reaches +5 % over its open (\"hit rate\" = share of those "
          "flags followed by +5 %; \"lift\" = hit rate ÷ the rate for every stock still below +5 % at the same step). "
          f"Thresholds and the shortlist are chosen on the train sessions only; the test sessions check them. A signal "
          f"\"holds\" when its test lift is ≥ {HOLD_LIFT}× on ≥ {MIN_TEST_SUPPORT} test flags. Medians are over the flags; "
          "upside and drawdown are from the flag price to the day's later high / the low before it. In-sample, ~30 sessions, "
          "no costs or slippage: an indication of what to look at, not a tested strategy.", ""]
    L += ["## The shortlist (best lift on the train sessions)", "", HEAD]
    L += [_row(s, tr, te, titles) for s in out["shortlist"]]
    pairs = [s for s in tr if s.startswith("p:") and (tr[s].get("eligible") or 0) >= min_support]
    pairs.sort(key=lambda s: -(tr[s].get("lift") or 0))
    L += ["", "## Pairs of shortlisted signals firing at the same step", "", HEAD]
    # pairs with identical flags (one signal implies the other's threshold) are one row
    seen_pairs, uniq = set(), []
    for s_ in pairs:
        key = tuple((tr[s_].get(k), (te.get(s_) or {}).get(k)) for k in ("eligible", "hits"))
        if key not in seen_pairs:
            seen_pairs.add(key)
            uniq.append(s_)
    L += [_row(s, tr, te, titles) for s in uniq[:12]] or ["| (none with enough flags) |"]
    L += ["", "## Dashboard widgets, and several widgets at once", "", HEAD]
    ws = [s for s in tr if s.startswith("w:") or s.startswith("k>=")]
    ws.sort(key=lambda s: -(tr[s].get("lift") or 0))
    L += [_row(s, tr, te, titles) for s in ws]
    L += ["", "## Every candidate indicator", "", HEAD]
    ins = [s for s in tr if s.startswith("i:")]
    ins.sort(key=lambda s: -(tr[s].get("lift") or 0))
    L += [_row(s, tr, te, titles) for s in ins]
    text = "\n".join(L) + "\n"
    bad = R.BARRED.findall(text)
    if bad:
        raise ValueError(f"barred words in the study report: {sorted(set(bad))}")
    return text


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", required=True)
    ap.add_argument("--test-sessions", type=int, default=TEST_SESSIONS)
    ap.add_argument("--min-support", type=int, default=30)
    a = ap.parse_args(argv)
    md, out = run(a.root, a.test_sessions, a.min_support)
    open(os.path.join(a.root, "study.md"), "w").write(md)
    json.dump(R.clean_json(out), open(os.path.join(a.root, "study.json"), "w"), indent=1)
    print(f"study: {os.path.join(a.root, 'study.md')}, shortlist {len(out['shortlist'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
