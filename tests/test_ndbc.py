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


if __name__ == "__main__":
    unittest.main()
