#!/usr/bin/env python3
"""Render result.json files from run_study.py as markdown tables (no statistics are computed here).

    python3 report.py <result_T2.json> <result_T1.json> > tables.md
"""
from __future__ import annotations

import json
import sys
from typing import Any, Dict, List

SEASON = {"2025-09-30": "Oct–Nov 2025", "2025-12-31": "Jan–Feb 2026", "2026-03-31": "Apr–May 2026", "2026-06-30": "Jul–Aug 2026"}


def f(v: Any, kind: str) -> str:
    if v is None:
        return "—"
    return f"{v * 100:+.2f} pp" if kind == "diff" else f"{v:+.3f}"


def p(v: Any) -> str:
    return "—" if v is None else (f"{v:.4f}" if v >= 0.0001 else "<0.0001")


def test_rows(tests: List[Dict[str, Any]], holm_key: str = "holm_p") -> List[str]:
    out = ["| Test | Estimate (equal-weight over seasons) | 95 % CI (date bootstrap) | p one-sided | Holm p | Pooled (Welch diff / IC) | Cross-season t (p) | Same sign | Result |",
           "|---|---|---|---|---|---|---|---|---|"]
    for t in tests:
        k = t["kind"]
        if t.get("status") == "INSUFFICIENT":
            out.append(f"| {t['name']} | — | — | — | — | — | — | — | INSUFFICIENT |")
            continue
        ci = f"[{f(t['ci95'][0], k)}, {f(t['ci95'][1], k)}]"
        if k == "diff":
            w = t["welch"]
            pooled = f"{f(w['pooled_diff'], k)} (t {w['t']:.2f}, p {p(w['p_one_sided'])})"
        else:
            pooled = f"{f(t['pooled_ic'], k)} (n {t['pooled_n']})"
        cs = t.get("cross_season_t")
        cst = f"{cs['t']:.2f} ({p(cs['p_one_sided'])})" if cs else "—"
        hp = t.get(holm_key)
        res = t.get("verdict") or ("harmful (provisional)" if t.get("harmful_provisional") else "")
        out.append(f"| {t['name']}{' (tests < 0)' if t['direction'] < 0 else ''} | {f(t['estimate'], k)} | {ci} | {p(t['p_one_sided'])} | "
                   f"{p(hp)} | {pooled} | {cst} | {'yes' if t['same_sign_all'] else 'no'} | {res} |")
    return out


def season_rows(tests: List[Dict[str, Any]]) -> List[str]:
    out = ["| Test | Season | n | Group means (a / b) | Estimate | Eligible |", "|---|---|---|---|---|---|"]
    for t in tests:
        for s in t["per_season"]:
            if t["kind"] == "diff":
                n = f"{s['n_a']} / {s['n_b']}"
                gm = f"{f(s['mean_a'], 'diff')} / {f(s['mean_b'], 'diff')}" if s["mean_a"] is not None and s["mean_b"] is not None else "—"
            else:
                n, gm = str(s["n"]), "—"
            out.append(f"| {t['name']} | {SEASON[s['season']]} | {n} | {gm} | {f(s['estimate'], t['kind'])} | {'yes' if s['eligible'] else 'no'} |")
    return out


def main(r2: str, r1: str) -> None:
    A, Z = json.load(open(r2)), json.load(open(r1))
    print("### Counts (T2, liquid universe)\n")
    print("| Season | Events | Liquid | R5 | D5 | Verdict above / in line / below (registered) | Live-code verdict above / in line / below | H5 strong / weak / unflagged | H5-L strong / weak / unflagged | F&O (S−1) |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for s, c in A["counts"].items():
        v, lv, h = c["verdict"], c["l_verdict"], c["h5"]
        print(f"| {SEASON[s]} | {c['events']} | {c['liquid']} | {c['R5x']} | {c['D5x']} | {v.get('above', 0)} / {v.get('in_line', 0)} / {v.get('below', 0)} | "
              f"{lv.get('above', 0)} / {lv.get('in_line', 0)} / {lv.get('below', 0)} | {h.get('strong', 0)} / {h.get('weak', 0)} / {h.get('unflagged', 0)} | "
              f"{c['h5_l'].get('strong', 0)} / {c['h5_l'].get('weak', 0)} / {c['h5_l'].get('unflagged', 0)} | {c['fno_m1']} |")
    for fam, title in (("F1", "F1 — registered formulas (H1–H4)"), ("F7", "F7 — live code, S7 (H1–H4)"), ("F5", "F5 — results-strength boost (H5, registered A1.1)"),
                       ("F5L", "F5L — the new live rule at 790d8132 (H5-L, A3)")):
        print(f"\n### {title} (T2, governs)\n")
        print("\n".join(test_rows(A["families"][fam])))
        print("\nPer season:\n")
        print("\n".join(season_rows(A["families"][fam])))
    for grp, tests in A["secondary"].items():
        print(f"\n### Secondary {grp} (T2; raw p, no decision)\n")
        print("\n".join(test_rows(tests, "holm_p_two_sided" if grp == "S6" else "holm_p")))
        print("\n".join([""] + season_rows(tests)))
    for grp, tests in A["exploratory"].items():
        print(f"\n### Exploratory {grp} (T2; raw p, no decision)\n")
        print("\n".join(test_rows(tests)))
        print("\n".join([""] + season_rows(tests)))
    print("\n### T1 (§5 timing as registered) beside T2\n")
    print("| Test | T1 estimate | T1 p | T1 result | T2 estimate | T2 p | T2 result |")
    print("|---|---|---|---|---|---|---|")
    for fam in ("F1", "F7", "F5", "F5L"):
        for t1, t2 in zip(Z["families"][fam], A["families"][fam]):
            k = t1["kind"]
            print(f"| {t1['name']} | {f(t1.get('estimate'), k)} | {p(t1.get('p_one_sided'))} | {t1.get('verdict')} | "
                  f"{f(t2.get('estimate'), k)} | {p(t2.get('p_one_sided'))} | {t2.get('verdict')} |")
    print("\n### Registered decisions (T2)\n")
    print("```json\n" + json.dumps(A["decisions"], indent=1) + "\n```")
    print("\nT1 decisions, for comparison:\n")
    print("```json\n" + json.dumps(Z["decisions"], indent=1) + "\n```")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
