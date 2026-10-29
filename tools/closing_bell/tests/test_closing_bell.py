"""Unit tests for the Closing Bell build tools (standard library only).

Run: python3 -m unittest discover -s tools/closing_bell/tests -v
Fixture: the real 27 Oct 2026 bundle collected on staging, trimmed to the fields the tools read.
Test-case IDs match test_reports/closing_bell_daily_20261028.md.
"""
import copy
import gzip
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import cards as cards_mod  # noqa: E402
import checks  # noqa: E402
import i18n  # noqa: E402
import pipeline  # noqa: E402
import publish  # noqa: E402
import script_gen  # noqa: E402

BUNDLE = json.loads(gzip.open(os.path.join(HERE, "fixtures", "bundle_20261027.json.gz")).read())


def build_all(bundle=None):
    c = cards_mod.build(copy.deepcopy(bundle or BUNDLE))
    return c, script_gen.build(c)


class Cards(unittest.TestCase):
    """TC-4: the cards reproduce the figures cross-checked by hand for 27 Oct."""

    @classmethod
    def setUpClass(cls):
        cls.c, cls.s = build_all()

    def test_breadth(self):
        m = self.c["movers"]
        self.assertEqual((m["Nifty 50"]["adv"], m["Nifty 50"]["dec"]), (25, 25))
        self.assertEqual((m["Nifty 500"]["adv"], m["Nifty 500"]["dec"]), (356, 138))
        self.assertEqual(m["Nifty 500"]["top"][0]["sym"], "OLAELEC")

    def test_indices(self):
        n50 = next(x for x in self.c["idx"] if x["name"] == "Nifty 50")
        self.assertEqual((n50["close"], n50["pts"], n50["pct"]), (22749.75, -3.45, -0.02))
        self.assertEqual(len(self.c["idx"]), 10)

    def test_fii_dii(self):
        f = self.c["fii"]
        self.assertTrue(f["same_day"])
        self.assertEqual((f["fii_net"], f["dii_net"]), (4240.39, -1250.03))
        self.assertEqual((f["mtd_fii"], f["mtd_dii"]), (-48688.5, 60469.9))
        self.assertEqual(f["biggest_since"], "2026-09-02")

    def test_rotation_and_labels(self):
        self.assertEqual(self.c["rotation"]["leading"], ["Information Technology", "Telecommunication", "Consumer Services"])
        self.assertEqual(self.c["L"]["day_long"], "Tuesday, 27 October 2026")
        self.assertEqual(self.c["L"]["next_date"], "2026-10-28")

    def test_results_are_index_names(self):
        n500 = {s["symbol"] for s in BUNDLE["heatmaps"]["NIFTY500"]["stocks"]}
        self.assertTrue(all(x["sym"] in n500 for x in self.c["res_up"]))
        self.assertEqual(self.c["res_up"][0]["sym"], "ONESOURCE")

    def test_names_are_speakable(self):
        names = [x["name"] for x in self.c["res_up"] + self.c["res_dn"]] + [i["name"] for i in self.c["ideas"]]
        self.assertFalse([n for n in names if "…" in n or len(n) > 24], names)


class ScriptGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c, cls.s = build_all()

    def test_tc5_every_number_traced(self):
        r = checks.check_script(self.c, self.s)
        self.assertTrue(r["ok"], r["fails"])
        self.assertGreater(r["numbers_checked"], 150)
        self.assertEqual(checks.check_data(self.c), [])

    def test_tc6_altered_number_is_caught(self):
        s = copy.deepcopy(self.s)
        fii = next(seg for seg in s["segments"] if seg["id"] == "s5")
        b = fii["beats"][0]
        b["text"] = b["texts"]["en"] = b["texts"]["en"].replace("4,240", "4,420")
        r = checks.check_script(self.c, s)
        self.assertFalse(r["ok"])
        self.assertTrue(any("4,420" in f for f in r["fails"]), r["fails"])

    def test_tc6_stale_trace_is_caught(self):
        c = copy.deepcopy(self.c)
        c["fii"]["fii_net"] = 5000.0          # source moved after the script was written
        r = checks.check_script(c, self.s)
        self.assertFalse(r["ok"])
        self.assertTrue(any("trace mismatch fii.fii_net" in f for f in r["fails"]), r["fails"])

    def test_tc7_missing_data_blocks(self):
        b = copy.deepcopy(BUNDLE)
        b["heatmaps"]["NIFTY500"] = {"_http": 502}
        b["ai_watchlist"] = {"_http": 404}
        c = cards_mod.build(b)
        fails = checks.check_data(c)
        self.assertTrue(any("heatmap NIFTY500" in f for f in fails), fails)
        self.assertTrue(any("Top 10" in f for f in fails), fails)

    def test_tc8_wording(self):
        s = copy.deepcopy(self.s)
        b = s["segments"][-1]["beats"][0]
        b["text"] = b["texts"]["en"] = b["texts"]["en"] + " Tonight's top picks are below."
        self.assertTrue(any("advice-like" in f for f in checks.check_script(self.c, s)["fails"]))
        s2 = copy.deepcopy(self.s)
        for seg in s2["segments"]:
            for b in seg["beats"]:
                b["text"] = b["texts"]["en"] = b["texts"]["en"].replace("not investment advice", "general commentary")
        self.assertTrue(any("closing disclaimer" in f for f in checks.check_script(self.c, s2)["fails"]))

    def test_headlines_and_segments(self):
        self.assertEqual([x["id"] for x in self.s["segments"]], ["s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7"])
        self.assertEqual(len(self.s["headlines"]), 4)
        for seg in self.s["segments"]:
            for b in seg["beats"]:
                self.assertNotIn("&", b["text"])        # read aloud as "and"
                self.assertNotIn("₹", b["text"])

    def test_deterministic(self):
        _, again = build_all()
        self.assertEqual(json.dumps(self.s, sort_keys=True), json.dumps(again, sort_keys=True))


class Languages(unittest.TestCase):
    """Owner, 2026-10-28: the commentary in Hindi, Tamil, Marathi and Gujarati, from fixed translated templates."""

    @classmethod
    def setUpClass(cls):
        cls.c, cls.s = build_all()

    def test_every_beat_in_every_language(self):
        self.assertEqual(self.s["languages"], ["en", "hi", "ta", "mr", "gu"])
        for seg in self.s["segments"]:
            for b in seg["beats"]:
                for lang in i18n.LANGS:
                    txt = b["texts"][lang]
                    self.assertTrue(txt.strip(), (seg["id"], lang))
                    self.assertNotIn("{", txt)
                    if lang != "en":
                        self.assertNotIn("percent", txt)          # every language says it in its own words

    def test_numbers_and_disclaimers_checked_in_all_languages(self):
        r = checks.check_script(self.c, self.s)
        self.assertTrue(r["ok"], r["fails"])
        self.assertGreater(r["numbers_checked"], 400)              # five narrations + captions

    def test_altered_hindi_number_is_caught(self):
        s = copy.deepcopy(self.s)
        b = next(seg for seg in s["segments"] if seg["id"] == "s5")["beats"][0]
        b["texts"]["hi"] = b["texts"]["hi"].replace("4,240", "4,420")
        r = checks.check_script(self.c, s)
        self.assertTrue(any("text[hi]" in f and "4,420" in f for f in r["fails"]), r["fails"])

    def test_missing_tamil_disclaimer_is_caught(self):
        s = copy.deepcopy(self.s)
        for seg in s["segments"]:
            for b in seg["beats"]:
                b["texts"]["ta"] = b["texts"]["ta"].replace("முதலீட்டு ஆலோசனை அல்ல", "")
        self.assertTrue(any("[ta]" in f for f in checks.check_script(self.c, s)["fails"]))

    def test_localised_dates_times_and_names(self):
        s0 = {seg["id"]: seg for seg in self.s["segments"]}
        fii = s0["s0"]["beats"][3]["texts"]
        self.assertIn("2 सितंबर", fii["hi"])
        self.assertIn("செப்டம்பர் 2", fii["ta"])
        self.assertIn("2 सप्टेंबर", fii["mr"])
        self.assertIn("2 સપ્ટેમ્બર", fii["gu"])
        watch = s0["s7"]["beats"][0]["texts"]
        self.assertIn("शाम 4 बजे", watch["hi"])
        self.assertIn("இரவு 11:30 மணிக்கு", watch["ta"])
        self.assertIn("बुधवार", watch["mr"])
        self.assertIn("निफ्टी 50", s0["s1"]["beats"][0]["texts"]["hi"])

    def test_opposite_day_renders_and_passes(self):
        """A falling market with FIIs selling exercises the other template branches in every language."""
        c = copy.deepcopy(self.c)
        n50 = next(i for i, x in enumerate(c["idx"]) if x["name"] == "Nifty 50")
        c["idx"][n50].update(pct=-1.21, pts=-278.4)
        c["fii"].update(fii_net=-3150.5, dii_net=2890.0, biggest_since=None, same_day=False, date="2026-10-26")
        c["movers"]["Nifty 500"].update(adv=110, dec=380)
        s = script_gen.build(c)
        r = checks.check_script(c, s)
        self.assertTrue(r["ok"], r["fails"])
        hi = {seg["id"]: seg for seg in s["segments"]}
        self.assertIn("बिकवाली", hi["s5"]["beats"][0]["texts"]["hi"])
        self.assertIn("26 अक्टूबर को", hi["s5"]["beats"][0]["texts"]["hi"])
        self.assertIn("weak", hi["s1"]["beats"][2]["parts"][0]["key"])


class Formatting(unittest.TestCase):
    def test_indian_grouping(self):
        self.assertEqual(script_gen.fmt_in(101175), "1,01,175")
        self.assertEqual(script_gen.fmt_in(22749.75, 2), "22,749.75")
        self.assertEqual(script_gen.fmt_in(4240.39), "4,240")

    def test_next_trading_day_skips_weekend_and_holiday(self):
        from datetime import date
        self.assertEqual(cards_mod.next_trading_day(date(2026, 10, 30), []), date(2026, 11, 2))
        self.assertEqual(cards_mod.next_trading_day(date(2026, 10, 30), ["2026-11-02"]), date(2026, 11, 3))


class Scheduling(unittest.TestCase):
    """TC-9: before-noon runs belong to the previous evening; the cut-off is 00:50 IST next morning."""

    def test_edition_date(self):
        ist = pipeline.IST
        self.assertEqual(pipeline.edition_date(datetime(2026, 10, 28, 23, 10, tzinfo=ist)), "2026-10-28")
        self.assertEqual(pipeline.edition_date(datetime(2026, 10, 29, 0, 40, tzinfo=ist)), "2026-10-28")

    def test_cutoff(self):
        ist = pipeline.IST
        self.assertFalse(pipeline.past_cutoff("2026-10-28", datetime(2026, 10, 29, 0, 40, tzinfo=ist)))
        self.assertTrue(pipeline.past_cutoff("2026-10-28", datetime(2026, 10, 29, 0, 50, tzinfo=ist)))


class Publish(unittest.TestCase):
    """TC-10: files land per date, the index is newest-first, re-publish replaces, retention trims list + disk."""

    def make_work(self, root, date):
        c, s = build_all()
        c["date"] = date
        c["L"] = dict(c["L"], day_long=f"Day {date}")
        w = os.path.join(root, "work-" + date)
        os.makedirs(os.path.join(w, "out"), exist_ok=True)
        json.dump(c, open(os.path.join(w, "cards.json"), "w"))
        json.dump(s, open(os.path.join(w, "script.json"), "w"))
        json.dump({"duration": 351.1}, open(os.path.join(w, "out", "media.json"), "w"))
        for f in ("web.mp4", "poster.jpg", "captions.vtt", "transcript.json"):
            open(os.path.join(w, "out", f), "w").write(f"{date}:{f}")
        for lang in ("hi", "ta", "mr", "gu"):
            for f in (f"web_{lang}.mp4", f"captions_{lang}.vtt", f"transcript_{lang}.json"):
                open(os.path.join(w, "out", f), "w").write(f"{date}:{f}")
        return w

    def test_publish_and_retention(self):
        with tempfile.TemporaryDirectory() as root:
            dest = os.path.join(root, "dest")
            os.makedirs(dest)
            for d in ("2026-10-26", "2026-10-27", "2026-10-28"):
                publish.main(self.make_work(root, d), dest, retain=2)
            idx = json.load(open(os.path.join(dest, "index.json")))
            self.assertEqual(idx["latest"], "2026-10-28")
            self.assertEqual([e["date"] for e in idx["editions"]], ["2026-10-28", "2026-10-27"])
            self.assertFalse(os.path.exists(os.path.join(dest, "2026-10-26")))
            ed = idx["editions"][0]
            self.assertEqual(ed["files"]["video"], "2026-10-28/closing-bell-2026-10-28.mp4")
            with open(os.path.join(dest, ed["files"]["video"])) as fh:
                self.assertEqual(fh.read(), "2026-10-28:web.mp4")
            self.assertEqual(ed["duration_label"], "5:51")
            self.assertFalse(any("<" in h["big"] for h in ed["headlines"]))
            self.assertEqual([x["code"] for x in ed["languages"]], ["en", "hi", "ta", "mr", "gu"])
            hi = next(x for x in ed["languages"] if x["code"] == "hi")
            self.assertEqual(hi["video"], "2026-10-28/closing-bell-2026-10-28-hi.mp4")
            with open(os.path.join(dest, hi["transcript"])) as fh:
                self.assertEqual(fh.read(), "2026-10-28:transcript_hi.json")
            # re-publishing a date replaces it, never duplicates it
            publish.main(self.make_work(root, "2026-10-28"), dest, retain=2)
            idx = json.load(open(os.path.join(dest, "index.json")))
            self.assertEqual([e["date"] for e in idx["editions"]], ["2026-10-28", "2026-10-27"])

    def test_older_editions_keep_english_only(self):
        with tempfile.TemporaryDirectory() as root:
            dest = os.path.join(root, "dest")
            os.makedirs(dest)
            for d in ("2026-10-26", "2026-10-27", "2026-10-28"):
                publish.main(self.make_work(root, d), dest, retain=45, lang_retain=2)
            idx = json.load(open(os.path.join(dest, "index.json")))
            langs = {e["date"]: [x["code"] for x in e["languages"]] for e in idx["editions"]}
            self.assertEqual(langs["2026-10-28"], ["en", "hi", "ta", "mr", "gu"])
            self.assertEqual(langs["2026-10-26"], ["en"])
            self.assertFalse(os.path.exists(os.path.join(dest, "2026-10-26", "closing-bell-2026-10-26-hi.mp4")))
            self.assertTrue(os.path.exists(os.path.join(dest, "2026-10-26", "closing-bell-2026-10-26.mp4")))


if __name__ == "__main__":
    unittest.main()
