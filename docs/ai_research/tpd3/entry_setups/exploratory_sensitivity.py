"""EXPLORATORY — not part of the pre-registered decision (run after the verdicts were seen). Re-runs the registered backtest in
memory (no writes) and asks where the edge goes missing:
  S1 upper bound: target before stop whenever both sit inside one bar (the registered rule assumes the stop first)
  S2 gross: no costs
  S3 raw 5-session return (entry → T+5 close, no stop/target, no R/R filter) for every filled setup vs every eligible stock-day
  S4 P(+5%) / P(+10%) within 5 sessions without the R/R filter, setups vs the same baseline
  S5 S3 within the v4 model's top probability quintile (Jan–Aug 2025)
"""
import json, os, runpy
from pathlib import Path
import numpy as np, pandas as pd

os.environ["ENTRY_SETUPS_NO_WRITE"] = "1"
ns = runpy.run_path(str(Path(__file__).parent / "backtest_entry_setups.py"))
E, build, TRADES, SETUPS, boot, COST = ns["E"], ns["build"], ns["TRADES"], ns["SETUPS"], ns["boot"], ns["COST"]
O, H, L, C = ns["O"], ns["H"], ns["L"], ns["C"]
out = {"note": "EXPLORATORY, post-verdict; not decisive"}


def bracket_target_first(entry, stop, target, o, h, l, c):
    n = len(entry); done = np.zeros(n, bool); exitp = c[:, 4].copy()
    for i in range(5):
        if i > 0:
            gp = ~done & (o[:, i] <= stop); exitp[gp] = o[gp, i]; done |= gp
        tg = ~done & (h[:, i] >= target); exitp[tg] = target[tg]; done |= tg
        st = ~done & (l[:, i] <= stop); exitp[st] = stop[st]; done |= st
    return exitp


def mean_ci(v, dates):
    d = pd.DataFrame({"as_of_date": dates, "net": v})
    return {"n": int(len(v)), "mean": float(np.mean(v)) if len(v) else None, "ci95": boot(d) if len(v) > 1 else [None, None]}


pool = E[E["filters_ok"] & E["regime_ok"] & ~E["no_chase"]]
for tr, (tp, mult) in TRADES.items():
    for s in SETUPS + ["base"]:
        cand = pool if s == "base" else pool[pool[f"setup_{s}"]]
        b = build(cand, s, tr)
        filled = b[b["filled"]]
        ok = filled[filled["plan_ok"]]
        e = ok["entry"].to_numpy(); t = e * (1 + tp)
        s1 = bracket_target_first(e, ok["stop"].to_numpy(), t, O(ok), H(ok), L(ok), C(ok)) / e - 1 - COST
        ef = filled["entry"].to_numpy(); hf = H(filled); cf = C(filled)
        r5 = cf[:, 4] / ef - 1
        key = f"{s}_{tr}"
        out[key] = {
            "S1_target_first_net": mean_ci(s1, ok["as_of_date"]),
            "S2_gross_registered_bracket": float(np.mean(ns["outcomes"](ok, tr)["net"] + COST)) if len(ok) else None,
            "S3_raw_5d_return_net_of_cost_all_filled": mean_ci(r5 - COST, filled["as_of_date"]),
            "S4_no_rr_filter": {"n": int(len(filled)), "p_up5_5d": float((hf.max(1) >= ef * 1.05).mean()), "p_up10_5d": float((hf.max(1) >= ef * 1.10).mean()),
                                "p_up5_1d": float((hf[:, 0] >= ef * 1.05).mean()), "p_up10_1d": float((hf[:, 0] >= ef * 1.10).mean()),
                                "mfe5_median": float(np.median(hf.max(1) / ef - 1)), "mae5_median": float(np.median(L(filled).min(1) / ef - 1))},
        }
        if tr == "5%":
            pred = ns["pred"]
            m = filled.merge(pred[pred["trade"] == tr][["symbol", "as_of_date", "p_rank"]], on=["symbol", "as_of_date"], how="inner")
            top = m[m["p_rank"] >= 0.8]
            if len(top):
                out[key]["S5_raw_5d_top_model_quintile_jan_aug_2025"] = mean_ci(C(top)[:, 4] / top["entry"].to_numpy() - 1 - COST, top["as_of_date"])
(Path(__file__).parent / "exploratory_sensitivity.json").write_text(json.dumps(out, indent=2, default=str))
for k, v in out.items():
    if k == "note": continue
    s1, s3, s4 = v["S1_target_first_net"], v["S3_raw_5d_return_net_of_cost_all_filled"], v["S4_no_rr_filter"]
    f = lambda x: "  n/a " if x is None else f"{x:+.4f}"
    print(f"{k:9s} S1 n={s1['n']:5d} {f(s1['mean'])} ci={[round(c,4) if c is not None else None for c in s1['ci95']]} | S2 gross {f(v['S2_gross_registered_bracket'])} | "
          f"S3 n={s3['n']:6d} {f(s3['mean'])} ci={[round(c,4) if c is not None else None for c in s3['ci95']]} | S4 P5_5d={s4['p_up5_5d']:.3f} P10_5d={s4['p_up10_5d']:.3f} P5_1d={s4['p_up5_1d']:.3f} MFE={s4['mfe5_median']:+.3f} MAE={s4['mae5_median']:+.3f}"
          + (f" | S5 n={v['S5_raw_5d_top_model_quintile_jan_aug_2025']['n']} {f(v['S5_raw_5d_top_model_quintile_jan_aug_2025']['mean'])}" if "S5_raw_5d_top_model_quintile_jan_aug_2025" in v else ""))
