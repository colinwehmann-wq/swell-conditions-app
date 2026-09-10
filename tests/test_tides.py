"""Unit tests for tide interpolation between hi/lo extremes."""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sources.tides import TideSeries

UTC = datetime.timezone.utc
T0 = datetime.datetime(2026, 9, 9, 0, 0, tzinfo=UTC)


def _h(hours):
    return T0 + datetime.timedelta(hours=hours)


class Height(unittest.TestCase):
    def setUp(self):
        # low 1.0 at 00:00 -> high 5.0 at 06:00
        self.ts = TideSeries([(_h(0), 1.0, "L"), (_h(6), 5.0, "H")])

    def test_endpoints_exact(self):
        self.assertAlmostEqual(self.ts.height(_h(0)), 1.0)
        self.assertAlmostEqual(self.ts.height(_h(6)), 5.0)

    def test_midpoint_is_mean(self):
        self.assertAlmostEqual(self.ts.height(_h(3)), 3.0)

    def test_quarter_points_follow_cosine(self):
        # frac 0.25 -> 3 + (-2)*cos(pi/4)
        import math
        self.assertAlmostEqual(self.ts.height(_h(1.5)), 3 + (-2) * math.cos(math.pi / 4))

    def test_out_of_range_is_none(self):
        self.assertIsNone(self.ts.height(_h(-1)))
        self.assertIsNone(self.ts.height(_h(7)))

    def test_empty_series(self):
        self.assertIsNone(TideSeries([]).height(_h(0)))


class State(unittest.TestCase):
    def test_rising_toward_high(self):
        ts = TideSeries([(_h(0), 1.0, "L"), (_h(6), 5.0, "H")])
        self.assertEqual(ts.state(_h(3)), "rising")

    def test_falling_toward_low(self):
        ts = TideSeries([(_h(0), 5.0, "H"), (_h(6), 1.0, "L")])
        self.assertEqual(ts.state(_h(3)), "falling")

    def test_outside_range(self):
        ts = TideSeries([(_h(0), 1.0, "L"), (_h(6), 5.0, "H")])
        self.assertEqual(ts.state(_h(9)), "flat")


class NextExtreme(unittest.TestCase):
    def setUp(self):
        self.ts = TideSeries([(_h(0), 1.0, "L"), (_h(6), 5.0, "H"), (_h(12), 0.5, "L")])

    def test_returns_first_at_or_after(self):
        self.assertEqual(self.ts.next_extreme(_h(-1))[2], "L")
        self.assertEqual(self.ts.next_extreme(_h(3))[2], "H")
        self.assertEqual(self.ts.next_extreme(_h(6))[2], "H")

    def test_none_past_end(self):
        self.assertIsNone(self.ts.next_extreme(_h(13)))


if __name__ == "__main__":
    unittest.main()
