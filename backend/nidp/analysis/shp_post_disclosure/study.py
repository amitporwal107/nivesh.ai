#!/usr/bin/env python3
"""NIDP-SHP-FWD-001 - post-disclosure forward returns by institutional ownership change.

A RESEARCH ARTIFACT. Not a product feature. Nothing it computes may be promoted to any score.

The question it answers, and the only one it answers: in the trading sessions AFTER a quarterly
shareholding pattern becomes PUBLIC, do stocks whose institutional ownership rose outperform those
whose institutional ownership fell?

The same-quarter move is not the question. Jul-Sep shareholding is disclosed in late October, by
which time the quarter's price move is history. This study therefore never touches a return that
starts before the data was available.

Rules this module enforces rather than hopes for:

 1. THE ENTRY IS AFTER PUBLICATION. Entry is the adjusted open of the first trading session
    STRICTLY AFTER period_end + 25 calendar days. SEBI (LODR) Reg 31(1)(b) requires the filing
    within 21 days of quarter end, and in the one quarter where this warehouse holds real NSE
    broadcast timestamps the observed maximum lag is 22 days. 48.5% of those broadcasts land after
    the 15:30 close, which is why entry is the NEXT session's open and not the filing day's.
 2. THE CONTRACT IS FROZEN. preregistration.json is re-hashed and compared with PREREG_SHA256
    before any data is read. A mismatch aborts; it does not adapt.
 3. EVERY DROPPED ROW IS COUNTED. Screens report their firing counts. A screen that silently
    removes the inconvenient half of a cross-section is indistinguishable from a result.
 4. THE SAMPLE IS REPORTED BEFORE THE EFFECT. 10 formation quarters against a review floor of 12
    means a POSITIVE verdict is unreachable, and the contract says so in writing.
 5. INCONCLUSIVE IS AN ANSWER. Thin samples do not become findings by being averaged.

Read-only: the warehouse is queried through the operator's psql wrapper, which takes SQL on STDIN.
No credentials are read, printed or embedded here.

Usage:
    python3 study.py [--psql ~/.config/nivesh/nidp-psql.sh] [--panel-csv PATH] [--out DIR]

With --panel-csv the SQL step is skipped and a previously captured panel is re-analysed, so the
statistics are reproducible without warehouse access.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

STUDY_ID = "NIDP-SHP-FWD-001"
PREREG_SHA256 = "5452b0551ab57ff68ba365963eae4d0490ee250c0d4322c9f5218d0734ec7071"

# --- frozen contract terms, mirrored from preregistration.json ---------------------------------
HORIZONS = (5, 20, 60)
PRIMARY_HORIZON = 20
BAND_PP = 0.50                 # |delta| below this is "flat"
HURDLE_PP = 1.00               # spread must clear this at the primary horizon
REVIEW_FLOOR_BLOCKS = 12       # independent formation quarters required for a promotion-grade call
BOOTSTRAP_N = 5000
BOOTSTRAP_SEED = 20261023
COST_PCT_PER_LEG = 0.4937      # round trip, one leg; the spread carries two legs
MIN_TURNOVER_INR = 10_000_000  # S3
MIN_LIQ_SESSIONS = 10          # S3, short-history clause
MIN_ENTRY_PRICE = 20.0         # S4


# ---------------------------------------------------------------------------------------------
# contract guard
# ---------------------------------------------------------------------------------------------
def verify_preregistration() -> dict[str, Any]:
    path = HERE / "preregistration.json"
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != PREREG_SHA256:
        raise SystemExit(
            f"ABORT: preregistration.json hash {digest} does not match the registered "
            f"{PREREG_SHA256}. The contract changed. Re-register it deliberately or restore it; "
            f"do not run the study against an unregistered contract."
        )
    print(f"preregistration hash verified: {digest}")
    return json.loads(raw)


# ---------------------------------------------------------------------------------------------
# panel
# ---------------------------------------------------------------------------------------------
def fetch_panel(psql: str) -> list[dict[str, str]]:
    sql = (HERE / "panel.sql").read_bytes()
    proc = subprocess.run(
        [os.path.expanduser(psql)], input=sql, capture_output=True, check=False
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr.decode("utf-8", "replace"))
        raise SystemExit(f"ABORT: panel query failed with exit {proc.returncode}")
    text = proc.stdout.decode("utf-8")
    return list(csv.DictReader(text.splitlines()))


def _f(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def apply_screens(rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Return the eligible observations plus a ledger of why everything else went."""
    ledger: dict[str, int] = {}
    kept: list[dict[str, Any]] = []

    def drop(reason: str) -> None:
        ledger[reason] = ledger.get(reason, 0) + 1

    for r in rows:
        # S6 - source disagreement is not an ownership change.
        if r["contested"] == "t":
            drop("S6_contested_source")
            continue
        # S5 - an unapplied corporate action inside the window is not a return.
        if int(r["artefact_days"] or 0) > 0:
            drop("S5_corporate_action_artefact")
            continue

        entry = _f(r["open_entry"])
        if entry is None or entry <= 0:
            drop("S2_no_entry_price")
            continue
        if entry < MIN_ENTRY_PRICE:
            drop("S4_below_min_price")
            continue

        liq_sessions = int(r["liq_sessions"] or 0)
        if liq_sessions < MIN_LIQ_SESSIONS:
            drop("S3_insufficient_liquidity_history")
            continue
        med_turnover = _f(r["med_turnover_pre"])
        if med_turnover is None or med_turnover < MIN_TURNOVER_INR:
            drop("S3_below_liquidity_floor")
            continue

        rets: dict[int, float] = {}
        missing = False
        for h in HORIZONS:
            exit_px = _f(r[f"open_h{h}"])
            if exit_px is None or exit_px <= 0:
                missing = True
                break
            rets[h] = 100.0 * (exit_px / entry - 1.0)
        if missing:
            drop("S2_no_exit_price")
            continue

        cur_fii, prv_fii = _f(r["cur_fii"]), _f(r["prv_fii"])
        cur_dii, prv_dii = _f(r["cur_dii"]), _f(r["prv_dii"])
        if cur_fii is None or prv_fii is None:
            drop("no_fii_pair")
            continue

        delta_fii = cur_fii - prv_fii
        delta_inst = (
            (cur_fii + cur_dii) - (prv_fii + prv_dii)
            if cur_dii is not None and prv_dii is not None
            else None
        )

        kept.append(
            {
                "period_end": r["period_end"],
                "symbol": r["symbol"],
                "entry_date": r["entry_date"],
                "avail_date": r["avail_date"],
                "entry_price": entry,
                "delta_fii": delta_fii,
                "delta_inst": delta_inst,
                "ret": rets,
            }
        )
    return kept, ledger


# ---------------------------------------------------------------------------------------------
# grouping and statistics
# ---------------------------------------------------------------------------------------------
def band(delta: float) -> str:
    if delta >= BAND_PP:
        return "increased"
    if delta <= -BAND_PP:
        return "reduced"
    return "flat"


def per_quarter(obs: list[dict[str, Any]], key: str, horizon: int) -> list[dict[str, Any]]:
    """Equal-weighted group means and the increased-minus-reduced spread, one row per quarter."""
    quarters = sorted({o["period_end"] for o in obs})
    out = []
    for q in quarters:
        rows = [o for o in obs if o["period_end"] == q and o[key] is not None]
        if not rows:
            continue
        groups: dict[str, list[float]] = {"increased": [], "flat": [], "reduced": []}
        for o in rows:
            groups[band(o[key])].append(o["ret"][horizon])
        inc, flat, red = groups["increased"], groups["flat"], groups["reduced"]
        out.append(
            {
                "quarter": q,
                "entry_date": rows[0]["entry_date"],
                "n": len(rows),
                "n_inc": len(inc),
                "n_flat": len(flat),
                "n_red": len(red),
                "mean_inc": statistics.fmean(inc) if inc else None,
                "mean_flat": statistics.fmean(flat) if flat else None,
                "mean_red": statistics.fmean(red) if red else None,
                "mean_all": statistics.fmean([o["ret"][horizon] for o in rows]),
                "spread": (
                    statistics.fmean(inc) - statistics.fmean(red) if inc and red else None
                ),
            }
        )
    return out


def tercile_per_quarter(obs: list[dict[str, Any]], key: str, horizon: int) -> list[dict[str, Any]]:
    """Threshold-free robustness check: top tercile of delta minus bottom tercile, per quarter."""
    quarters = sorted({o["period_end"] for o in obs})
    out = []
    for q in quarters:
        rows = sorted(
            (o for o in obs if o["period_end"] == q and o[key] is not None),
            key=lambda o: o[key],
        )
        if len(rows) < 9:
            continue
        cut = len(rows) // 3
        bottom = [o["ret"][horizon] for o in rows[:cut]]
        top = [o["ret"][horizon] for o in rows[-cut:]]
        out.append(
            {
                "quarter": q,
                "n": len(rows),
                "n_per_tercile": cut,
                "mean_bottom": statistics.fmean(bottom),
                "mean_top": statistics.fmean(top),
                "spread": statistics.fmean(top) - statistics.fmean(bottom),
            }
        )
    return out


def block_bootstrap(values: list[float], n: int, seed: int) -> tuple[float, float, float]:
    """Mean plus a 95% percentile CI, resampling WHOLE QUARTERS - the dependence unit."""
    if not values:
        return float("nan"), float("nan"), float("nan")
    rng = random.Random(seed)
    k = len(values)
    means = []
    for _ in range(n):
        means.append(statistics.fmean([values[rng.randrange(k)] for _ in range(k)]))
    means.sort()
    lo = means[int(0.025 * n)]
    hi = means[min(int(0.975 * n), n - 1)]
    return statistics.fmean(values), lo, hi


def verdict(mean: float, lo: float, hi: float, blocks: int) -> tuple[str, str]:
    if lo > HURDLE_PP and blocks >= REVIEW_FLOOR_BLOCKS:
        return "POSITIVE", f"CI lower bound {lo:+.4f} pp clears the {HURDLE_PP:+.2f} pp hurdle"
    if hi < 0.0:
        return "NEGATIVE", f"CI upper bound {hi:+.4f} pp is below zero"
    reasons = []
    if blocks < REVIEW_FLOOR_BLOCKS:
        reasons.append(
            f"{blocks} formation quarters against a review floor of {REVIEW_FLOOR_BLOCKS}"
        )
    if lo <= HURDLE_PP:
        reasons.append(f"CI [{lo:+.4f}, {hi:+.4f}] pp does not clear {HURDLE_PP:+.2f} pp")
    if hi >= 0.0 >= lo:
        reasons.append("the interval straddles zero")
    return "INCONCLUSIVE", "; ".join(reasons)


# ---------------------------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--psql", default="~/.config/nivesh/nidp-psql.sh")
    ap.add_argument("--panel-csv", default=None, help="re-analyse a captured panel; skips SQL")
    ap.add_argument("--out", default=None, help="directory for panel.csv / results.json")
    args = ap.parse_args()

    verify_preregistration()

    if args.panel_csv:
        rows = list(csv.DictReader(Path(args.panel_csv).read_text().splitlines()))
        print(f"panel loaded from {args.panel_csv}: {len(rows)} rows")
    else:
        rows = fetch_panel(args.psql)
        print(f"panel fetched from the warehouse: {len(rows)} rows")

    obs, ledger = apply_screens(rows)

    print(f"\n{'=' * 78}\n{STUDY_ID}  -  post-disclosure forward returns\n{'=' * 78}")
    print(f"\nRaw (quarter, symbol) pairs with a prior quarter : {len(rows)}")
    print(f"Eligible after screens                           : {len(obs)}")
    print("\nExclusion ledger")
    for reason, count in sorted(ledger.items(), key=lambda kv: -kv[1]):
        print(f"  {reason:38s} {count:6d}")

    quarters = sorted({o["period_end"] for o in obs})
    print(f"\nFormation quarters : {len(quarters)}  ({quarters[0]} .. {quarters[-1]})")
    print(f"Review floor       : {REVIEW_FLOOR_BLOCKS} independent blocks")
    if len(quarters) < REVIEW_FLOOR_BLOCKS:
        print(
            f"  -> BELOW FLOOR. A POSITIVE verdict is unreachable by construction, as the "
            f"contract states.\n"
        )

    with_dii = sum(1 for o in obs if o["delta_inst"] is not None)
    print(f"Eligible with FII+DII pair (primary) : {with_dii}")
    print(f"Eligible with FII pair (robustness)  : {len(obs)}")

    results: dict[str, Any] = {
        "study_id": STUDY_ID,
        "preregistration_sha256": PREREG_SHA256,
        "raw_pairs": len(rows),
        "eligible": len(obs),
        "eligible_with_dii": with_dii,
        "exclusion_ledger": ledger,
        "formation_quarters": quarters,
        "review_floor": REVIEW_FLOOR_BLOCKS,
        "horizons": {},
    }

    for label, key, spec in (
        ("PRIMARY  delta(FII+DII)", "delta_inst", "bands"),
        ("ROBUST   delta(FII) only", "delta_fii", "bands"),
        ("ROBUST   delta(FII+DII) terciles", "delta_inst", "terciles"),
    ):
        print(f"\n\n{'-' * 78}\n{label}  -  grouping: {spec}\n{'-' * 78}")
        block = results["horizons"].setdefault(label, {})
        for h in HORIZONS:
            if spec == "bands":
                table = per_quarter(obs, key, h)
                print(f"\nHorizon {h} sessions")
                print(
                    f"  {'quarter':11s} {'entry':11s} {'n':>4s} "
                    f"{'n_inc':>5s} {'n_flat':>6s} {'n_red':>5s} "
                    f"{'inc%':>8s} {'flat%':>8s} {'red%':>8s} {'all%':>8s} {'spread_pp':>10s}"
                )
                for t in table:
                    def fmt(v: float | None) -> str:
                        return "      --" if v is None else f"{v:+8.2f}"
                    sp = "        --" if t["spread"] is None else f"{t['spread']:+10.3f}"
                    print(
                        f"  {t['quarter']:11s} {t['entry_date']:11s} {t['n']:4d} "
                        f"{t['n_inc']:5d} {t['n_flat']:6d} {t['n_red']:5d} "
                        f"{fmt(t['mean_inc'])} {fmt(t['mean_flat'])} {fmt(t['mean_red'])} "
                        f"{fmt(t['mean_all'])} {sp}"
                    )
            else:
                table = tercile_per_quarter(obs, key, h)
                print(f"\nHorizon {h} sessions (terciles)")
                print(
                    f"  {'quarter':11s} {'n':>4s} {'per_t':>5s} "
                    f"{'bottom%':>9s} {'top%':>9s} {'spread_pp':>10s}"
                )
                for t in table:
                    print(
                        f"  {t['quarter']:11s} {t['n']:4d} {t['n_per_tercile']:5d} "
                        f"{t['mean_bottom']:+9.2f} {t['mean_top']:+9.2f} {t['spread']:+10.3f}"
                    )

            spreads = [t["spread"] for t in table if t["spread"] is not None]
            mean, lo, hi = block_bootstrap(spreads, BOOTSTRAP_N, BOOTSTRAP_SEED + h)
            pos = sum(1 for s in spreads if s > 0)
            net = mean - 2 * COST_PCT_PER_LEG
            v, why = verdict(mean, lo, hi, len(spreads))
            print(
                f"\n  mean spread {mean:+.4f} pp | 95% CI [{lo:+.4f}, {hi:+.4f}] pp "
                f"| blocks {len(spreads)} | positive quarters {pos}/{len(spreads)} "
                f"| net of {2 * COST_PCT_PER_LEG:.4f} pp costs {net:+.4f} pp"
            )
            if h == PRIMARY_HORIZON:
                print(f"  verdict at the primary horizon: {v}  -  {why}")
            block[h] = {
                "per_quarter": table,
                "mean_spread_pp": mean,
                "ci95_lo_pp": lo,
                "ci95_hi_pp": hi,
                "blocks": len(spreads),
                "positive_quarters": pos,
                "net_of_costs_pp": net,
                "verdict": v,
                "verdict_reason": why,
            }

    primary = results["horizons"]["PRIMARY  delta(FII+DII)"][PRIMARY_HORIZON]
    print(f"\n\n{'=' * 78}")
    print(f"VERDICT ({PRIMARY_HORIZON}-session, primary estimand): {primary['verdict']}")
    print(f"  {primary['verdict_reason']}")
    print(f"{'=' * 78}")
    results["final_verdict"] = primary["verdict"]
    results["final_verdict_reason"] = primary["verdict_reason"]

    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "results.json").write_text(json.dumps(results, indent=2, default=str))
        print(f"\nwrote {out / 'results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
