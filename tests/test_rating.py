"""The 1-10 scale: its named steps and colour tiers, and how a raw score becomes a rating."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sources import evaluate as E
from sources import words

CFG = {
    "name": "Test",
    "height_ok_ft": [2.5, 9.0], "height_ideal_ft": [3.5, 6.5],
    "period_min_s": 8.0, "period_ideal_s": 13.0,
    "swell_dir_deg": [190, 315],
    "offshore_dir_deg": [40, 110],
    "wind_ideal_kn": 6.0, "wind_max_kn": 12.0,
    "tide_ok_ft": [0.5, 5.0], "tide_ideal_ft": [1.5, 4.0],
}


class Steps(unittest.TestCase):
    def test_eight_named_steps(self):
        names = [(9.0, "Epic"), (9.9, "Epic"), (8.0, "Excellent"), (8.9, "Excellent"), (7.0, "Good"),
                 (7.9, "Good"), (6.0, "Decent"), (6.9, "Decent"), (5.0, "Fair"), (5.9, "Fair"),
                 (4.0, "Mediocre"), (4.9, "Mediocre"), (3.0, "Poor"), (3.9, "Poor"),
                 (2.9, "Very poor"), (1.0, "Very poor")]
        for r, name in names:
            self.assertEqual(words.rating_label(r), name, r)

    def test_bad_is_no_longer_everything_under_five(self):
        self.assertNotEqual(words.rating_label(4.5), words.rating_label(2.0))
        self.assertNotEqual(words.rating_label(4.5), words.rating_label(5.5))

    def test_four_colour_tiers(self):
        for r, band in [(10, "green"), (7.0, "green"), (6.9, "yellow"), (5.0, "yellow"),
                        (4.9, "orange"), (3.0, "orange"), (2.9, "red"), (1.0, "red")]:
            self.assertEqual(words.rating_band(r), band, r)

    def test_a_go_is_a_green_rating(self):
        self.assertEqual(words.rating_band(words.rating(70.0)), "green")
        self.assertNotEqual(words.rating_band(words.rating(69.0)), "green")

    def test_rating_is_clamped_to_one_to_ten(self):
        self.assertEqual(words.rating(0.0), 1.0)
        self.assertEqual(words.rating(100.0), 10.0)


class Ranking(unittest.TestCase):
    ANCHORS = [20.0, 40.0, 50.0, 60.0, 70.0, 80.0, 85.0, 90.0, 94.0, 98.0]

    def test_no_anchors_leaves_the_score_alone(self):
        self.assertEqual(E.to_rating_score(63.0, None), 63.0)
        self.assertEqual(E.to_rating_score(63.0, []), 63.0)

    def test_hitting_an_anchor_gives_that_rating(self):
        for i, a in enumerate(self.ANCHORS):
            self.assertAlmostEqual(E.to_rating_score(a, self.ANCHORS), (i + 1) * 10.0)

    def test_between_anchors_is_interpolated(self):
        self.assertAlmostEqual(E.to_rating_score(55.0, self.ANCHORS), 35.0)

    def test_ends_are_pinned(self):
        self.assertEqual(E.to_rating_score(0.0, self.ANCHORS), 10.0)
        self.assertEqual(E.to_rating_score(100.0, self.ANCHORS), 100.0)

    def test_never_goes_down_as_raw_goes_up(self):
        prev = -1.0
        for raw in range(0, 101):
            cur = E.to_rating_score(float(raw), self.ANCHORS)
            self.assertGreaterEqual(cur, prev)
            prev = cur

    def test_the_same_raw_score_ranks_lower_at_a_break_with_a_better_best(self):
        easy = [10.0, 30.0, 40.0, 50.0, 60.0, 70.0, 75.0, 80.0, 85.0, 90.0]
        hard = [a + 8.0 for a in easy]
        self.assertGreater(E.to_rating_score(72.0, easy), E.to_rating_score(72.0, hard))

    def test_score_applies_the_breaks_anchors(self):
        args = (4.5, 14.0, 250, 3.0, 75, 2.5)
        plain, _ = E.score(*args, dict(CFG))
        hard, _ = E.score(*args, dict(CFG, rating_anchors=[a + 10 for a in self.ANCHORS]))
        easy, _ = E.score(*args, dict(CFG, rating_anchors=[a - 10 for a in self.ANCHORS]))
        self.assertGreater(easy, hard)
        self.assertEqual(plain, E.raw_score(*args, CFG)[0])


class Gradient(unittest.TestCase):
    """The raw score keeps rising toward a break's best, rather than topping out at "ideal"."""
    GOOD = dict(swell_dir=250, wind_kn=3.0, wind_dir=75, tide_ft=2.7)

    def raw(self, h, p, **kw):
        a = dict(self.GOOD, **kw)
        return E.raw_score(h, p, a["swell_dir"], a["wind_kn"], a["wind_dir"], a["tide_ft"], CFG)[0]

    def test_longer_period_beats_just_ideal(self):
        self.assertGreater(self.raw(5.0, 17.0), self.raw(5.0, 13.0))

    def test_middle_of_the_size_band_beats_its_edge(self):
        self.assertGreater(self.raw(5.0, 15.0), self.raw(3.5, 15.0))
        self.assertGreater(self.raw(5.0, 15.0), self.raw(6.5, 15.0))

    def test_period_credit_stops_at_the_cap(self):
        self.assertAlmostEqual(self.raw(5.0, 19.0), self.raw(5.0, 25.0))

    def test_never_above_one_hundred(self):
        self.assertLessEqual(self.raw(5.0, 20.0), 100.0)


if __name__ == "__main__":
    unittest.main()


class BreakPage(unittest.TestCase):
    """The 'how this break is rated' section on each break's page."""

    def test_benchmark_payload_and_section(self):
        import config
        from sitegen import render
        from sitegen.build import _benchmark
        cfg = config.spot_config([s for s in config.SPOTS if s["slug"] == "swamis"][0])
        b = _benchmark(cfg["benchmark"])
        self.assertEqual(b["typical"]["9"]["label"], "Epic")
        self.assertEqual(b["typical"]["7"]["label"], "Good")
        html = render._rated_section({"name": "Swami's", "benchmark": b})
        self.assertIn("How Swami&#x27;s is rated", html)
        self.assertIn("Epic", html)
        self.assertIn("Good", html)
        self.assertIn("kt wind", html)

    def test_no_benchmark_no_section(self):
        from sitegen import render
        self.assertEqual(render._rated_section({"name": "X", "benchmark": None}), "")
        self.assertEqual(render._rated_section({"name": "X"}), "")

    def test_every_break_has_a_benchmark(self):
        import config
        for s in config.SPOTS:
            self.assertIn("benchmark", config.spot_config(s), s["slug"])
