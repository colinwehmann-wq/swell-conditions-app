"""benchmarks.json must match the code and the roster: stale anchors fail here, loudly."""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config
from sources import climate, evaluate

REGEN = "Regenerate with: python3 tools/build_benchmarks.py"

with open(os.path.join(ROOT, "benchmarks.json")) as _f:
    DATA = json.load(_f)


class Benchmarks(unittest.TestCase):
    def test_scoring_version_matches(self):
        self.assertEqual(DATA["scoring_version"], evaluate.SCORING_VERSION, REGEN)
        self.assertEqual(DATA["percentiles"], evaluate.RATING_PERCENTILES, REGEN)

    def test_every_break_has_an_entry_and_no_extras(self):
        self.assertEqual(sorted(DATA["breaks"]), sorted(s["slug"] for s in config.SPOTS), REGEN)

    def test_every_entry_is_current(self):
        for spot in config.SPOTS:
            cfg = config.spot_config(spot)
            self.assertEqual(DATA["breaks"][cfg["slug"]]["signature"], climate.signature(cfg),
                             "%s is out of date. %s" % (cfg["name"], REGEN))

    def test_anchors_are_usable(self):
        for slug, b in DATA["breaks"].items():
            a = b["anchors"]
            self.assertEqual(len(a), len(evaluate.RATING_PERCENTILES), slug)
            self.assertTrue(all(y > x for x, y in zip(a, a[1:])), slug)
            self.assertTrue(0 <= a[0] and a[-1] <= 100, slug)

    def test_history_is_long_enough_to_trust(self):
        for slug, b in DATA["breaks"].items():
            self.assertGreater(b["history"]["days"], 3000, slug)

    def test_config_merges_the_anchors(self):
        for spot in config.SPOTS:
            cfg = config.spot_config(spot)
            self.assertEqual(cfg["rating_anchors"], DATA["breaks"][cfg["slug"]]["anchors"], cfg["name"])

    def test_a_ten_is_a_rare_day_everywhere(self):
        for slug, b in DATA["breaks"].items():
            self.assertLess(b["days_per_year"]["9"], 15, slug)
            self.assertGreater(b["days_per_year"]["5"], 40, slug)


if __name__ == "__main__":
    unittest.main()
