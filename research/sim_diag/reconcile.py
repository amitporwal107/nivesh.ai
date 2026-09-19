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
- LOCKED_LOWER: the simulator could not sell a bar locked at the lower circuit (the labels exit at its open).

Anything else is UNEXPLAINED, which RC-1 treats as a SIMULATION_FAILURE."""
from __future__ import annotations

import numpy as np
import pandas as pd

OUTCOME = {"STOP_HIT": "STOP", "GAP_THROUGH_STOP": "STOP", "TARGET_HIT": "TARGET", "TIME_EXIT": "EXPIRED",
           "LIQUIDITY_EXIT": "EXPIRED"}
LEVEL_TOL, NET_TOL = 0.01, 1e-6


def compare(trade: dict, lab: pd.Series) -> dict:
    """One trade vs its label row. Returns the field checks and the classification of any difference."""
    out = {"symbol": trade["symbol"], "decision_date": str(trade["decision_date"])}
    if trade.get("status") != "CLOSED":
        out.update(ok=False, classes="UNEXPLAINED", detail=f"simulator status {trade.get('status')}")
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
        classes.append("LOCKED_LOWER" if "LOCKED_LOWER" in (trade["flags"] or "") else "UNEXPLAINED")
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
            "unexplained": int(rows.classes.str.contains("UNEXPLAINED").sum())}
