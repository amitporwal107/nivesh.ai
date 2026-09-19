"""D3 baseline reconciliation (PRD §6): configuration A through the trade simulator vs the H#32 labels (labels.py
outputs stored in the dataset), trade by trade.

Compared per trade:
- the outcome (STOP / TARGET / EXPIRED);
- the exit date;
- the raw exit level (before slippage) within ₹0.01;
- the net return within 1e-6.

A difference is explained only by a recomputation that removes one known difference and then agrees:
- NET_PAISA_ROUNDING: the simulator's unrounded path (fills not rounded to the paisa, same quantity) agrees within 1e-6;
- NET_QTY_BOUNDARY: the unrounded path agrees, and its quantity differs from the rounded fill's;
- LOCKED_LOWER_FULL_DAY: the simulator could not sell because every blocked bar was locked all day (high == low);
  labels.py sold at that bar's open, a price at which nothing could be sold (a labels.py defect);
- LOCKED_LOWER_HEURISTIC: at least one blocked bar traded away from its open, so the lock test was a false positive
  and a sale at the open was possible (a simulator defect; fixed in D7, so this class can no longer arise);
- LOCKED_UPPER_LABELS_HEURISTIC: labels.py skipped the entry as locked at the upper circuit, but the s1 bar traded
  away from its open (high > low), so the stock was buyable. The simulator takes the trade. This is the OLD lock
  test surviving in labels.py, which is frozen with the H#32 dataset and is deliberately not changed (D7,
  2026-09-20).

Anything else is UNEXPLAINED. RC-1 treats UNEXPLAINED and simulator defects as a SIMULATION_FAILURE."""
from __future__ import annotations

import numpy as np
import pandas as pd

OUTCOME = {"STOP_HIT": "STOP", "GAP_THROUGH_STOP": "STOP", "TARGET_HIT": "TARGET", "TIME_EXIT": "EXPIRED",
           "LIQUIDITY_EXIT": "EXPIRED"}
LEVEL_TOL, NET_TOL = 0.01, 1e-6
DEFECT_SIDE = {"NET_PAISA_ROUNDING": "convention", "NET_QTY_BOUNDARY": "convention",
               "LOCKED_LOWER_FULL_DAY": "labels.py", "LOCKED_LOWER_HEURISTIC": "simulator",
               "LOCKED_UPPER_LABELS_HEURISTIC": "labels.py", "UNEXPLAINED": "unknown"}
SIMULATION_FAILURE_CLASSES = ("UNEXPLAINED", "LOCKED_LOWER_HEURISTIC")


def _locked_class(flags: str) -> str:
    f = flags or ""
    if "LOCKED_LOWER_PARTIAL" in f:
        return "LOCKED_LOWER_HEURISTIC"
    return "LOCKED_LOWER_FULL_DAY" if "LOCKED_LOWER_FULLDAY" in f else "UNEXPLAINED"


def compare(trade: dict, lab: pd.Series, s1_bar=None) -> dict:
    """One trade vs its label row. Returns the field checks and the classification of any difference.

    `s1_bar` is the trade's first session bar; it is what distinguishes a genuine disagreement from labels.py's own
    circuit-lock heuristic, so a caller that cannot supply it gets UNEXPLAINED rather than a guess."""
    out = {"symbol": trade["symbol"], "decision_date": str(trade["decision_date"])}
    lab_entry = lab.get("entry_status", "OK")
    if trade.get("status") != "CLOSED" or lab_entry != "OK":
        detail = f"simulator {trade.get('status')} ({trade.get('entry_rejection_reason') or trade.get('exit_reason')}), labels {lab_entry}"
        cls = "UNEXPLAINED"
        if (trade.get("status") == "CLOSED" and lab_entry == "LOCKED_UPPER_OPEN"
                and s1_bar is not None and s1_bar.high > s1_bar.low):
            cls = "LOCKED_UPPER_LABELS_HEURISTIC"
            detail += " (the s1 bar traded away from its open, so the stock was buyable)"
        out.update(ok=False, ok_outcome=False, ok_date=False, ok_level=False, ok_net=False, classes=cls,
                   detail=detail, level_diff=float("nan"), net_diff=float("nan"), net_exact_diff=float("nan"),
                   flags=trade.get("flags", ""))
        return out
    sim_outcome = OUTCOME[trade["exit_reason"]]
    lab_date = pd.Timestamp(lab.tbs_5_2_exit_date).date()
    level_diff = abs(float(trade["exit_level"]) - float(lab.tbs_5_2_exit_px))
    net_diff = abs(trade["net_ret"] - float(lab.net_ret_5_2))
    net_exact_diff = abs(trade["net_ret_exact"] - float(lab.net_ret_5_2))
    out.update(sim_outcome=sim_outcome, lab_outcome=lab.tbs_5_2, sim_exit_date=str(trade["exit_date"]),
               lab_exit_date=str(lab_date), sim_level=float(trade["exit_level"]), lab_level=float(lab.tbs_5_2_exit_px),
               level_diff=level_diff, sim_net=trade["net_ret"], lab_net=float(lab.net_ret_5_2), net_diff=net_diff,
               net_exact_diff=net_exact_diff, qty=trade["fill_quantity"], qty_exact=trade["qty_exact"],
               exit_detail=trade["exit_detail"], flags=trade["flags"])
    ok_outcome = sim_outcome == lab.tbs_5_2
    ok_date = trade["exit_date"] == lab_date
    ok_level = level_diff <= LEVEL_TOL + 1e-9          # float representation: 98.01 - 98.00 = 0.01000000000000512
    ok_net = net_diff <= NET_TOL
    out.update(ok_outcome=ok_outcome, ok_date=ok_date, ok_level=ok_level, ok_net=ok_net)
    classes = []
    if not (ok_outcome and ok_date and ok_level):
        classes.append(_locked_class(trade["flags"]))
    elif not ok_net:
        if net_exact_diff <= NET_TOL:
            classes.append("NET_QTY_BOUNDARY" if trade["qty_exact"] != trade["fill_quantity"] else "NET_PAISA_ROUNDING")
        else:
            classes.append("UNEXPLAINED")
    out["ok"] = not classes
    out["classes"] = ";".join(classes)
    out["detail"] = ""
    return out


def summarise(rows: pd.DataFrame) -> dict:
    n = len(rows)
    cls = rows.classes.replace("", np.nan).dropna().str.split(";").explode().value_counts().to_dict()
    return {"trades": int(n), "agree_all_fields": int(rows.ok.sum()),
            "outcome_agree": int(rows.ok_outcome.fillna(False).sum()), "exit_date_agree": int(rows.ok_date.fillna(False).sum()),
            "level_agree": int(rows.ok_level.fillna(False).sum()), "net_agree_1e-6": int(rows.ok_net.fillna(False).sum()),
            "net_exact_path_agree_1e-6": int((rows.net_exact_diff <= NET_TOL).sum()),
            "max_level_diff": float(rows.level_diff.max()), "max_net_diff": float(rows.net_diff.max()),
            "max_net_exact_diff": float(rows.net_exact_diff.max()),
            "mismatch_classes": {k: int(v) for k, v in cls.items()},
            "defect_side": {k: DEFECT_SIDE.get(k, "unknown") for k in cls},
            "simulator_defects": int(rows.classes.str.contains("LOCKED_LOWER_HEURISTIC").sum()),
            "stop_blocked_then_recovered": int(rows["flags"].fillna("").str.contains("STOP_BLOCKED_THEN_RECOVERED").sum()),
            "unexplained": int(rows.classes.str.contains("UNEXPLAINED").sum())}
