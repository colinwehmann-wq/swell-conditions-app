"""Unit tests for NDBC feed parsing (the bit most likely to break on a format change)."""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sources import ndbc

# A trimmed real .spec response: 2 header lines, newest row first, some MM values.
SPEC_SAMPLE = """\
#YY  MM DD hh mm WVHT  SwH  SwP  WWH  WWP SwD WWD  STEEPNESS  APD MWD
#yr  mo dy hr mn    m    m  sec    m  sec  -  degT     -      sec degT
2026 09 09 13 40  0.6  0.5 17.4  0.3  4.5 SSW   S  AVERAGE  6.1 202
2026 09 09 13 10  MM   MM   MM   MM   MM  MM  MM    N/A      MM  MM
"""


class NumParse(unittest.TestCase):
    def test_missing_marker(self):
        self.assertIsNone(ndbc._num("MM"))
        self.assertIsNone(ndbc._num(None))

    def test_number(self):
        self.assertEqual(ndbc._num("1.8"), 1.8)
        self.assertEqual(ndbc._num("201"), 201.0)

    def test_garbage(self):
        self.assertIsNone(ndbc._num("N/A"))
        self.assertIsNone(ndbc._num("AVERAGE"))


class DirParse(unittest.TestCase):
    def test_compass_text(self):
        self.assertEqual(ndbc._dir("SSW"), 202.5)
        self.assertEqual(ndbc._dir("N"), 0.0)
        self.assertEqual(ndbc._dir("W"), 270.0)

    def test_degrees_passthrough(self):
        self.assertEqual(ndbc._dir("315"), 315.0)

    def test_missing(self):
        self.assertIsNone(ndbc._dir("MM"))


class DataRows(unittest.TestCase):
    def test_strips_headers_and_blanks(self):
        rows = ndbc._data_rows(SPEC_SAMPLE)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][5], "0.6")

    def test_row_time_is_utc(self):
        rows = ndbc._data_rows(SPEC_SAMPLE)
        t = ndbc._row_time(rows[0])
        self.assertEqual(t, datetime.datetime(2026, 9, 9, 13, 40, tzinfo=ndbc.UTC))


class FetchSpec(unittest.TestCase):
    def setUp(self):
        self._orig = ndbc.http.get

    def tearDown(self):
        ndbc.http.get = self._orig

    def test_parses_newest_valid_row(self):
        ndbc.http.get = lambda *a, **k: SPEC_SAMPLE
        d = ndbc.fetch_spec("46224")
        self.assertEqual(d["buoy"], "46224")
        self.assertEqual(d["wvht_m"], 0.6)
        self.assertEqual(d["swp_s"], 17.4)
        self.assertEqual(d["swd_deg"], 202.5)
        self.assertIn("stale", d)

    def test_skips_all_MM_row(self):
        one_bad_row = "\n".join(SPEC_SAMPLE.splitlines()[:2] + [SPEC_SAMPLE.splitlines()[3]]) + "\n"
        ndbc.http.get = lambda *a, **k: one_bad_row
        self.assertIsNone(ndbc.fetch_spec("46224"))

    def test_network_error_returns_none(self):
        def boom(*a, **k):
            raise RuntimeError("down")
        ndbc.http.get = boom
        self.assertIsNone(ndbc.fetch_spec("46224"))

    def test_staleness_flag(self):
        old = datetime.datetime.now(ndbc.UTC) - datetime.timedelta(hours=9)
        line = "%s  0.6  0.5 17.4  0.3  4.5 SSW   S  AVERAGE  6.1 202" % old.strftime("%Y %m %d %H %M")
        text = "\n".join(SPEC_SAMPLE.splitlines()[:2] + [line]) + "\n"
        ndbc.http.get = lambda *a, **k: text
        self.assertTrue(ndbc.fetch_spec("46224", max_age_hours=3.0)["stale"])


class SmoothedSpec(unittest.TestCase):
    """The 'current' reading averages the newest few, so one big set or one lull doesn't swing the rating."""

    def setUp(self):
        self._orig = ndbc.http.get

    def tearDown(self):
        ndbc.http.get = self._orig

    def feed(self, readings):
        """readings: [(minutes_ago, WVHT, SwH, SwP, SwD)], newest first, as a .spec file."""
        now = datetime.datetime.now(ndbc.UTC)
        lines = ["#YY  MM DD hh mm WVHT  SwH  SwP  WWH  WWP SwD WWD  STEEPNESS  APD MWD", "#yr  mo dy hr mn    m    m  sec    m  sec  -  degT     -      sec degT"]
        for ago, wvht, swh, swp, swd in readings:
            t = (now - datetime.timedelta(minutes=ago)).replace(second=0, microsecond=0)
            lines.append("%s  %s  %s %s  0.3  4.5 %s   S  AVERAGE  6.1 202" % (t.strftime("%Y %m %d %H %M"), wvht, swh, swp, swd))
        ndbc.http.get = lambda *a, **k: "\n".join(lines) + "\n"
        return ndbc.fetch_spec("46224")

    def test_height_is_the_average_of_the_newest_three(self):
        d = self.feed([(20, 1.6, 1.5, 15.4, 202), (50, 1.3, 1.2, 15.4, 202), (80, 1.4, 1.3, 16.7, 202), (110, 9.9, 9.9, 9.9, 90)])
        self.assertAlmostEqual(d["swh_m"], (1.5 + 1.2 + 1.3) / 3.0)
        self.assertAlmostEqual(d["wvht_m"], (1.6 + 1.3 + 1.4) / 3.0)
        self.assertEqual(d["smoothed_from"], 3)

    def test_a_lone_big_set_is_pulled_back_toward_the_swell(self):
        d = self.feed([(20, 1.6, 1.5, 15.4, 202), (50, 1.1, 1.0, 15.4, 202), (80, 1.1, 1.0, 15.4, 202)])
        self.assertLess(d["swh_m"], d["raw"]["swh_m"])
        self.assertEqual(d["raw"]["swh_m"], 1.5)                         # the unsmoothed newest reading is still there

    def test_period_is_the_median_so_one_odd_reading_does_not_move_it(self):
        d = self.feed([(20, 1.2, 1.1, 20.0, 202), (50, 1.2, 1.1, 14.3, 202), (80, 1.2, 1.1, 14.3, 202)])
        self.assertEqual(d["swp_s"], 14.3)

    def test_direction_is_averaged_around_the_circle(self):
        d = self.feed([(20, 1.2, 1.1, 15.4, 350), (50, 1.2, 1.1, 15.4, 10), (80, 1.2, 1.1, 15.4, 350)])
        self.assertTrue(d["swd_deg"] > 355 or d["swd_deg"] < 5, d["swd_deg"])      # near north, not near 237

    def test_readings_too_far_back_are_not_averaged_in(self):
        d = self.feed([(20, 1.6, 1.5, 15.4, 202), (200, 0.5, 0.4, 9.0, 202)])
        self.assertEqual(d["smoothed_from"], 1)
        self.assertEqual(d["swh_m"], 1.5)

    def test_a_single_reading_passes_through_unchanged(self):
        d = self.feed([(20, 1.6, 1.5, 15.4, 202)])
        self.assertEqual((d["swh_m"], d["swp_s"], d["swd_deg"]), (1.5, 15.4, 202.0))

    def test_a_reading_missing_one_field_still_averages_the_rest(self):
        d = self.feed([(20, 1.6, "MM", 15.4, 202), (50, 1.3, 1.2, 15.4, 202), (80, 1.4, 1.4, 15.4, 202)])
        self.assertAlmostEqual(d["swh_m"], (1.2 + 1.4) / 2.0)

    def test_age_and_staleness_follow_the_newest_reading_not_the_average(self):
        d = self.feed([(20, 1.6, 1.5, 15.4, 202), (50, 1.3, 1.2, 15.4, 202), (80, 1.4, 1.3, 15.4, 202)])
        self.assertLess(d["age_hours"], 0.5)
        self.assertFalse(d["stale"])

    def test_everything_the_rest_of_the_app_reads_is_still_there(self):
        d = self.feed([(20, 1.6, 1.5, 15.4, 202), (50, 1.3, 1.2, 15.4, 202)])
        for key in ("buoy", "time", "age_hours", "stale", "wvht_m", "swh_m", "swp_s", "wwh_m", "wwp_s", "swd_deg", "apd_s", "mwd_deg"):
            self.assertIn(key, d, key)


class FetchSpecHistory(unittest.TestCase):
    def setUp(self):
        self._orig = ndbc.http.get

    def tearDown(self):
        ndbc.http.get = self._orig

    @staticmethod
    def row(hours_ago, wvht="1.1", swh="1.0", swp="14.3", swd="SSW", apd="8.1"):
        t = datetime.datetime.now(ndbc.UTC) - datetime.timedelta(hours=hours_ago)
        return "%s  %s  %s %s  0.6  6.2 %s WNW  SWELL  %s 204" % (
            t.strftime("%Y %m %d %H %M"), wvht, swh, swp, swd, apd)

    def feed(self, *rows):
        header = "\n".join(SPEC_SAMPLE.splitlines()[:2])
        ndbc.http.get = lambda *a, **k: header + "\n" + "\n".join(rows) + "\n"

    def test_returns_every_row_inside_the_window_newest_first(self):
        self.feed(self.row(1), self.row(5), self.row(20))
        got = ndbc.fetch_spec_history("46224", hours=24)
        self.assertEqual(len(got), 3)
        self.assertGreater(got[0]["time"], got[1]["time"])

    def test_rows_older_than_the_window_are_dropped(self):
        self.feed(self.row(1), self.row(40))
        self.assertEqual(len(ndbc.fetch_spec_history("46224", hours=30)), 1)

    def test_a_large_window_backfills_the_whole_feed(self):
        self.feed(self.row(1), self.row(24 * 40))
        self.assertEqual(len(ndbc.fetch_spec_history("46224", hours=24 * 46)), 2)

    def test_parses_the_fields_the_log_needs(self):
        self.feed(self.row(1))
        r = ndbc.fetch_spec_history("46224")[0]
        self.assertEqual((r["wvht_m"], r["swh_m"], r["swp_s"], r["swd_deg"], r["apd_s"]),
                         (1.1, 1.0, 14.3, 202.5, 8.1))

    def test_rows_with_no_wave_height_are_skipped(self):
        self.feed(self.row(1, wvht="MM"), self.row(2))
        self.assertEqual(len(ndbc.fetch_spec_history("46224")), 1)

    def test_network_error_returns_an_empty_list(self):
        def boom(*a, **k):
            raise RuntimeError("down")
        ndbc.http.get = boom
        self.assertEqual(ndbc.fetch_spec_history("46224"), [])


if __name__ == "__main__":
    unittest.main()
