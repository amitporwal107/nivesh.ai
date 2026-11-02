"""Opening Bell — unit tests (no network). Builds a morning edition on the 27 Oct fixture bundle (as the previous
session) with a hand-built option chain, MCX bars and a pre-open derived from the fixture's Nifty 50 list.
run: python3 -m unittest discover -s tools/closing_bell/tests -v
"""
import copy
import gzip
import json
import math
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import cards_open  # noqa: E402
import checks  # noqa: E402
import i18n  # noqa: E402
import script_open  # noqa: E402
from i18n import LANGS  # noqa: E402

PREV, DAY = "2026-10-27", "2026-10-28"


def chain(spot, strikes, ce_oi, pe_oi, ce_px, pe_px, as_of=PREV, expiry="2026-11-03"):
    return {"symbol": "X", "as_of": as_of, "expiry": expiry, "strike_count": len(strikes),
            "strikes": [{"strike": k, "CE": {"open_interest": c, "close_price": cp, "underlying_price": spot, "change_in_oi": 0},
                         "PE": {"open_interest": p, "close_price": pp, "underlying_price": spot, "change_in_oi": 0}}
                        for k, c, p, cp, pp in zip(strikes, ce_oi, pe_oi, ce_px, pe_px)]}


def fixture():
    b = json.load(gzip.open(os.path.join(HERE, "fixtures", "bundle_20261027.json.gz")))
    spot = next(x for x in b["indices"] if x["index_name"] == "Nifty 50")["close_price"]
    base = round(spot / 100) * 100
    ks = [base + 100 * i for i in range(-6, 7)]
    ce = [1e6 * (1 + (k > spot) * (3 if k == base + 300 else 1)) for k in ks]
    pe = [1e6 * (1 + (k < spot) * (4 if k == base - 200 else 1)) for k in ks]
    cpx = [max(1.0, spot - k) + 40 for k in ks]
    ppx = [max(1.0, k - spot) + 35 for k in ks]
    stock = chain(3000.0, [2900, 3000, 3100], [5e5, 6e5, 7e5], [7e5, 6e5, 5e5], [150, 90, 50], [40, 85, 140], expiry="2026-11-24")
    b["open"] = {"date": DAY, "prev": PREV,
                 "results_today": [{"symbol": "ACME", "name": "Acme Industries Ltd", "status": "upcoming"}],
                 "chains": {"NIFTY": chain(spot, ks, ce, pe, cpx, ppx), "ACME": stock},
                 "mcx": {"CRUDEOIL-I": [{"timestamp": "2026-10-26", "close": 9500}, {"timestamp": PREV, "close": 9405}],
                         "GOLD-I": [{"timestamp": "2026-10-26", "close": 140000}, {"timestamp": PREV, "close": 141400}]}}
    b["meta"]["open_date"] = DAY
    return b, spot


def preopen(b, up=0.5, date=DAY):
    """Every F&O-like row: the fixture's Nifty 500 stocks, Nifty 50 names priced `up` percent higher."""
    n50 = {s["symbol"] for s in b["heatmaps"]["NIFTY50"]["stocks"]}
    rows = []
    for i, s in enumerate(b["heatmaps"]["NIFTY500"]["stocks"][:220]):
        prev = 100.0 + i
        pct = up if s["symbol"] in n50 else ((i % 7) - 3) * 0.8
        rows.append({"sym": s["symbol"], "iep": round(prev * (1 + pct / 100), 4), "prev": prev, "pct": pct, "qty": 1000})
    for s in b["heatmaps"]["NIFTY50"]["stocks"]:
        if s["symbol"] not in {r["sym"] for r in rows}:
            rows.append({"sym": s["symbol"], "iep": 100 * (1 + up / 100), "prev": 100.0, "pct": up, "qty": 10})
    return {"timestamp": "28-Oct-2026 09:08:12", "date": date, "fo": rows, "all": rows, "fo_adv": 150, "fo_dec": 50, "fo_unch": 18,
            "allow_stale": False}


class Levels(unittest.TestCase):
    def test_hand_built_chain(self):                              # OB-1
        c = cards_open.chain_levels(chain(112.0, [100, 110, 120], [10, 20, 30], [30, 20, 10], [14, 6, 1], [1, 3, 9]))
        self.assertEqual((c["sup"], c["res"], c["max_pain"], c["atm"]), (100, 120, 110, 110))
        self.assertEqual(c["pcr"], 1.0)
        self.assertEqual(c["straddle"], 9.0)                       # CE 6 + PE 3 at the 110 ATM strike

    def test_vix_range(self):                                     # OB-2
        b, spot = fixture()
        c = cards_open.build(b)
        vix = next(x for x in c["idx"] if x["name"] == "India VIX")["close"]
        pts = spot * vix / 100 / math.sqrt(365)
        self.assertEqual(c["lv"]["pts"], round(pts))
        self.assertEqual((c["lv"]["lo"], c["lv"]["hi"]), (round(spot - pts), round(spot + pts)))

    def test_expiry_day_only(self):                               # OB-3
        b, _ = fixture()
        self.assertFalse(cards_open.build(b)["lv"]["oi"]["expiry_today"])
        b["open"]["chains"]["NIFTY"]["expiry"] = DAY
        c = cards_open.build(b)
        self.assertTrue(c["lv"]["oi"]["expiry_today"])
        s = script_open.build(c)
        self.assertIn("o_straddle", [p["key"] for x in s["segments"] for bt in x["beats"] for p in bt["parts"]])

    def test_implied_move(self):                                  # OB-4
        b, _ = fixture()
        c = cards_open.build(b)
        self.assertEqual(c["imp"], [{"sym": "ACME", "name": "Acme Industries", "expiry": "2026-11-24", "spot": 3000.0, "atm": 3000.0,
                                     "straddle": 175.0, "pct": 5.8}])

    def test_stale_chain_blocks(self):
        b, _ = fixture()
        b["open"]["chains"]["NIFTY"]["as_of"] = "2026-10-20"
        c = cards_open.build(b)
        self.assertTrue(any("option chain" in f for f in checks.check_data(c)))


class PreOpen(unittest.TestCase):
    def test_indicated_nifty(self):                               # OB-5
        b, spot = fixture()
        c = cards_open.build(b, preopen(b, up=0.5))
        n = c["pre"]["nifty"]
        self.assertEqual((n["cover"], n["of"]), (50, 50))
        self.assertAlmostEqual(n["pct"], 0.5, places=2)
        self.assertEqual(n["ind"], round(spot * 1.005))
        self.assertFalse(n["flat"])

    def test_too_few_constituents(self):                          # OB-5
        b, _ = fixture()
        p = preopen(b)
        n50 = [s["symbol"] for s in b["heatmaps"]["NIFTY50"]["stocks"]]
        p["fo"] = [r for r in p["fo"] if r["sym"] not in n50[:10]]
        c = cards_open.build(b, p)
        self.assertTrue(any(g.startswith("pre-open: only 40 of 50") for g in c["gaps"]))
        self.assertTrue(checks.check_data(c, require_preopen=True))

    def test_stale_preopen_refused(self):                         # OB-6
        b, _ = fixture()
        c = cards_open.build(b, preopen(b, date=PREV))
        self.assertTrue(any("not " + DAY in g for g in c["gaps"]))
        self.assertTrue(any(f.startswith("pre-open:") for f in checks.check_data(c, require_preopen=True)))

    def test_lists(self):                                         # OB-7
        b, _ = fixture()
        c = cards_open.build(b, preopen(b))
        pre = c["pre"]
        self.assertEqual((pre["adv"], pre["dec"]), (150, 50))
        self.assertTrue(pre["ups"] and all(x["pct"] > 0 for x in pre["ups"]))
        self.assertTrue(pre["dns"] and all(x["pct"] < 0 for x in pre["dns"]))
        self.assertEqual(pre["ups"], sorted(pre["ups"], key=lambda x: -x["pct"]))


class Script(unittest.TestCase):
    def build(self, pre=True):
        b, _ = fixture()
        c = cards_open.build(b, preopen(b) if pre else None)
        return c, script_open.build(c)

    def test_checks_pass_phase_b(self):                           # OB-8, OB-10
        c, s = self.build()
        r = checks.check_script(c, s)
        self.assertEqual(r["fails"], [])
        self.assertEqual(checks.check_data(c, require_preopen=True), [])
        self.assertGreater(r["numbers_checked"], 150)

    def test_checks_pass_phase_a(self):
        c, s = self.build(pre=False)
        self.assertEqual(checks.check_script(c, s)["fails"], [])
        self.assertEqual(checks.check_data(c), [])
        self.assertTrue(checks.check_data(c, require_preopen=True))

    def test_morning_wording(self):                               # OB-9
        _, s = self.build()
        en = " ".join(b["text"] for x in s["segments"] for b in x["beats"])
        self.assertNotRegex(en, r"(?i)\btonight\b|good evening|good night")
        self.assertIn("Good morning", en)
        self.assertIn("today's Top 10 ideas", en)

    def test_every_language_rendered(self):
        _, s = self.build()
        for x in s["segments"]:
            for b in x["beats"]:
                for lang in LANGS:
                    t = b["texts"][lang]
                    self.assertTrue(t and "{" not in t, (x["id"], lang, t))
                    if lang != "en":
                        self.assertNotRegex(t, r"\b(?:percent|points|either way|crore)\b", (x["id"], lang, t))   # English template words

    def test_same_segments_both_phases(self):                     # OB-11
        _, a = self.build(pre=False)
        _, b = self.build(pre=True)
        self.assertEqual([x["id"] for x in a["segments"]], [x["id"] for x in b["segments"]])
        self.assertEqual([x["id"] for x in a["segments"]], ["s0", "o1", "o2", "o3", "o4", "o5"])
        self.assertEqual(a["segments"][2].get("min_len"), script_open.O2_PLACEHOLDER_LEN)
        self.assertIsNone(b["segments"][2].get("min_len"))
        for sid in ("o1", "o3", "o4", "o5"):                      # untouched by the 9:08 rebuild
            ta = [bt["texts"] for x in a["segments"] if x["id"] == sid for bt in x["beats"]]
            tb = [bt["texts"] for x in b["segments"] if x["id"] == sid for bt in x["beats"]]
            self.assertEqual(ta, tb, sid)

    def test_no_untraced_numbers_when_numbers_change(self):
        b, _ = fixture()
        c = cards_open.build(b, preopen(b))
        s = script_open.build(c)
        c2 = copy.deepcopy(c)
        c2["lv"]["pts"] += 7
        r = checks.check_script(c2, s)
        self.assertTrue(any("lv.pts" in f for f in r["fails"]))


if __name__ == "__main__":
    unittest.main()
