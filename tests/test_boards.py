"""The board recommender is rule-based, so every rule gets a case."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sources import boards as B


class Recommend(unittest.TestCase):
    def key(self, *a, **k):
        return B.recommend(*a, **k)["key"]

    def test_missing_data_returns_none(self):
        self.assertIsNone(B.recommend(None, 10))
        self.assertIsNone(B.recommend(4, None))

    def test_small_is_longboard(self):
        self.assertEqual(self.key(1.8, 12), B.LONGBOARD)
        self.assertEqual(self.key(2.4, 16, 2, None), B.LONGBOARD)

    def test_short_period_small_is_longboard_bigger_is_fish(self):
        self.assertEqual(self.key(3.0, 7), B.LONGBOARD)
        self.assertEqual(self.key(4.0, 7), B.FISH)

    def test_waist_high_soft_and_clean_is_midlength(self):
        self.assertEqual(self.key(3.0, 10, 3, None), B.MIDLENGTH)
        self.assertEqual(self.key(2.5, 10, 3, None), B.MIDLENGTH)  # boundary: 2.5 is not "small"
        self.assertEqual(self.key(3.0, 10, 15, "offshore"), B.MIDLENGTH)

    def test_waist_high_and_bumpy_is_fish(self):
        self.assertEqual(self.key(3.0, 10, 12, "onshore"), B.FISH)

    def test_small_but_long_period_and_clean_is_shortboard(self):
        self.assertEqual(self.key(3.0, 14, 3, None), B.SHORTBOARD)

    def test_small_long_period_but_windy_is_fish(self):
        self.assertEqual(self.key(3.0, 14, 12, "onshore"), B.FISH)

    def test_big_is_performance(self):
        self.assertEqual(self.key(7.0, 11), B.PERFORMANCE)

    def test_clean_long_period_mid_size_is_performance(self):
        self.assertEqual(self.key(4.2, 13, 3, None), B.PERFORMANCE)

    def test_offshore_wind_counts_as_clean(self):
        self.assertEqual(self.key(4.5, 13, 15, "offshore"), B.PERFORMANCE)

    def test_onshore_chop_downgrades_performance_to_fish(self):
        self.assertEqual(self.key(4.2, 13, 12, "onshore"), B.FISH)

    def test_middling_period_mid_size_is_midlength_when_clean_fish_when_bumpy_then_shortboard(self):
        self.assertEqual(self.key(4.2, 9, 3, None), B.MIDLENGTH)
        self.assertEqual(self.key(4.2, 9, 12, "onshore"), B.FISH)
        self.assertEqual(self.key(5.0, 9, 3, None), B.SHORTBOARD)

    def test_solid_workable_is_shortboard(self):
        self.assertEqual(self.key(4.2, 11, 3, None), B.SHORTBOARD)

    def test_result_shape(self):
        r = B.recommend(4.2, 13, 3, None)
        self.assertEqual(set(r), {"key", "label", "why"})
        self.assertEqual(r["label"], B.LABELS[r["key"]])
        self.assertTrue(r["why"])

    def test_every_board_is_reachable(self):
        seen = {B.recommend(h, p, w, rel)["key"]
                for h in (1.5, 3.0, 4.2, 5.0, 7.0)
                for p in (6, 9, 11, 14)
                for w, rel in ((3, None), (12, "onshore"), (15, "offshore"))}
        self.assertEqual(seen, {B.LONGBOARD, B.MIDLENGTH, B.FISH, B.SHORTBOARD, B.PERFORMANCE})


if __name__ == "__main__":
    unittest.main()
