"""Unit tests for next_check_after — the 'is a window coming before the next run?' clock."""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sources.timeutil import TZ, next_check_after

TIMES = ["05:00", "10:30", "15:00"]


def at(y, mo, d, h, mi=0):
    return datetime.datetime(y, mo, d, h, mi, tzinfo=TZ)


class NextCheckAfter(unittest.TestCase):
    def test_between_checks_returns_next_today(self):
        nc = next_check_after(at(2026, 9, 9, 7, 0), TIMES)
        self.assertEqual((nc.hour, nc.minute), (10, 30))
        self.assertEqual(nc.date(), datetime.date(2026, 9, 9))

    def test_before_first_check(self):
        nc = next_check_after(at(2026, 9, 9, 4, 0), TIMES)
        self.assertEqual((nc.hour, nc.minute), (5, 0))

    def test_after_last_check_rolls_to_tomorrow(self):
        nc = next_check_after(at(2026, 9, 9, 16, 0), TIMES)
        self.assertEqual((nc.hour, nc.minute), (5, 0))
        self.assertEqual(nc.date(), datetime.date(2026, 9, 10))

    def test_exactly_on_a_check_time_returns_the_next_one(self):
        nc = next_check_after(at(2026, 9, 9, 10, 30), TIMES)
        self.assertEqual((nc.hour, nc.minute), (15, 0))

    def test_empty_times_falls_back_six_hours(self):
        base = at(2026, 9, 9, 8, 0)
        self.assertEqual(next_check_after(base, []), base + datetime.timedelta(hours=6))

    def test_ignores_unparseable_entries(self):
        nc = next_check_after(at(2026, 9, 9, 8, 0), ["garbage", "10:00", None])
        self.assertEqual((nc.hour, nc.minute), (10, 0))

    def test_result_is_timezone_aware(self):
        self.assertIsNotNone(next_check_after(at(2026, 9, 9, 7, 0), TIMES).tzinfo)


if __name__ == "__main__":
    unittest.main()
