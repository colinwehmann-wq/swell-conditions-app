"""The page's JavaScript (sitegen/assets/peaks.js) must pick exactly what the Python build picks.

The text built into the page and the text the browser swaps in at runtime come from two
implementations of the same rule. This runs both over the same scenarios and demands identical
answers. It needs Node; without it the test is skipped (CI has it).
"""
import datetime
import json
import os
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sitegen.build import peak_title, pick_next_peak
from tests.test_peaks import PDT, peak

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PEAKS_JS = os.path.join(ROOT, "sitegen", "assets", "peaks.js")
NODE = shutil.which("node")

RUNNER = """
const P = require(process.argv[1]);
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(input.nows.map(n => P.headline(input.peaks, n.ms, n.today))));
"""


def run_js(peaks, nows):
    out = subprocess.run([NODE, "-e", RUNNER, PEAKS_JS], input=json.dumps({"peaks": peaks, "nows": nows}),
                         capture_output=True, text=True, timeout=60, check=True)
    return json.loads(out.stdout)


def python_headline(peaks, now):
    best = pick_next_peak(peaks, now)
    if not best:
        return {"title": "A flat spell.", "fig": None, "anchor_ms": None}
    lead = (datetime.date.fromisoformat(best["date"]) - now.date()).days
    return {"title": peak_title(best, lead), "sub": best["sub"], "fig_slug": best["slug"],
            "anchor_ms": datetime.datetime.fromisoformat(best["time"]).timestamp() * 1000}


SCENARIOS = {
    "a normal week": [
        peak("blacks", 15, 6, 92.0), peak("swamis", 15, 9, 88.0), peak("grandview", 15, 7, 70.0),
        peak("blacks", 16, 7, 70.0), peak("swamis", 16, 8, 80.0), peak("beacons", 16, 8, 80.0),
        peak("swamis", 17, 8, 55.0), peak("blacks", 18, 9, 66.0), peak("oceanside", 19, 6, 40.0),
    ],
    "only rideable days": [peak("a", 15, 8, 55.0), peak("b", 15, 7, 61.0), peak("c", 16, 6, 61.0)],
    "ties everywhere": [peak("b", 15, 9, 80.0), peak("a", 15, 7, 80.0), peak("c", 16, 6, 80.0)],
    "exactly on the threshold": [peak("a", 15, 8, 66.0), peak("b", 16, 8, 65.9), peak("c", 17, 8, 50.0)],
    "flat": [peak("a", 15, 8, 30.0), peak("b", 16, 8, 49.9)],
    "nothing at all": [],
}


@unittest.skipUnless(NODE, "Node is not installed")
class Parity(unittest.TestCase):
    def check(self, name, peaks):
        # every 20 minutes from before the first peak to after the last one
        nows = []
        t = datetime.datetime(2026, 10, 14, 22, 0, tzinfo=PDT)
        while t < datetime.datetime(2026, 10, 20, 12, 0, tzinfo=PDT):
            nows.append(t)
            t += datetime.timedelta(minutes=20)
        got = run_js(peaks, [{"ms": n.timestamp() * 1000, "today": n.date().isoformat()} for n in nows])
        for now, js in zip(nows, got):
            py = python_headline(peaks, now)
            where = "%s @ %s" % (name, now.isoformat())
            self.assertEqual(js["title"], py["title"], where)
            if py["anchor_ms"] is None:
                self.assertIsNone(js["fig"], where)
                self.assertIsNone(js["anchor"], where)
            else:
                self.assertEqual(js["fig"]["slug"], py["fig_slug"], where)
                self.assertEqual(js["sub"], py["sub"], where)
                self.assertEqual(js["anchor"], py["anchor_ms"], where)

    def test_python_and_javascript_agree_in_every_scenario_at_every_moment(self):
        for name, peaks in SCENARIOS.items():
            with self.subTest(name):
                self.check(name, peaks)

    def test_the_headline_changes_exactly_when_a_peak_passes(self):
        peaks = SCENARIOS["a normal week"]
        before = datetime.datetime(2026, 10, 15, 5, 59, tzinfo=PDT)
        after = datetime.datetime(2026, 10, 15, 6, 1, tzinfo=PDT)
        a, b = run_js(peaks, [{"ms": t.timestamp() * 1000, "today": "2026-10-15"} for t in (before, after)])
        self.assertEqual(a["title"], "Today, Blacks peaks around 6:00 AM.")
        self.assertEqual(b["title"], "Today, Swamis peaks around 9:00 AM.")
        self.assertEqual(b["fig"]["slug"], "swamis")

    def test_the_visitors_calendar_day_decides_today_versus_tomorrow(self):
        peaks = [peak("blacks", 16, 6, 90.0, name="Blacks")]
        now = datetime.datetime(2026, 10, 15, 21, 0, tzinfo=PDT)
        night, morning = run_js(peaks, [{"ms": now.timestamp() * 1000, "today": "2026-10-15"},
                                        {"ms": now.timestamp() * 1000, "today": "2026-10-16"}])
        self.assertTrue(night["title"].startswith("Tomorrow is the one"))
        self.assertTrue(morning["title"].startswith("Today, Blacks"))


if __name__ == "__main__":
    unittest.main()
