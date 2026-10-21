"""The history maths behind each break's rating scale (sources/climate.py)."""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sources import climate, evaluate

CFG = {
    "name": "Test",
    "height_ok_ft": [2.5, 9.0], "height_ideal_ft": [3.5, 6.5],
    "period_min_s": 8.0, "period_ideal_s": 13.0,
    "swell_dir_deg": [190, 315],
    "offshore_dir_deg": [40, 110],
    "wind_ideal_kn": 6.0, "wind_max_kn": 12.0,
    "tide_ok_ft": [0.5, 5.0], "tide_ideal_ft": [1.5, 4.0],
    "buoys": ["46224"],
}


def synthetic_hours(days, start=datetime.date(2020, 1, 1)):
    """One hour a day, with size, period and wind cycling so the days differ."""
    for i in range(days):
        yield (start + datetime.timedelta(days=i), 8, 2.0 + (i % 7), 9.0 + (i % 9), 250.0,
               2.0 + (i % 11), 75.0, 2.5)


class Fractions(unittest.TestCase):
    def test_swell_share_by_period(self):
        self.assertEqual(climate.swell_fraction(7.0), 0.45)
        self.assertEqual(climate.swell_fraction(10.0), 0.62)
        self.assertEqual(climate.swell_fraction(15.0), 0.70)


class Quantiles(unittest.TestCase):
    def test_interpolates(self):
        self.assertEqual(climate.quantile([0, 10, 20, 30, 40], 50), 20)
        self.assertAlmostEqual(climate.quantile([0, 10], 25), 2.5)

    def test_ends(self):
        self.assertEqual(climate.quantile([3, 5, 9], 0), 3)
        self.assertEqual(climate.quantile([3, 5, 9], 100), 9)

    def test_empty_is_an_error(self):
        with self.assertRaises(ValueError):
            climate.quantile([], 50)

    def test_anchors_are_strictly_ascending_even_when_scores_tie(self):
        a = climate.anchors([70.0] * 500)
        self.assertEqual(len(a), len(evaluate.RATING_PERCENTILES))
        self.assertTrue(all(y > x for x, y in zip(a, a[1:])))


class Daylight(unittest.TestCase):
    def test_covers_sunrise_hour_to_the_hour_the_light_runs_out(self):
        day = datetime.date(2024, 3, 1)
        rise, set_ = datetime.datetime(2024, 3, 1, 6, 20), datetime.datetime(2024, 3, 1, 18, 5)
        hours = {datetime.datetime(2024, 3, 1, h): (1.0, 12.0, 250.0) for h in range(24)}
        wind = {k: (3.0, 75.0) for k in hours}
        got = [h[1] for h in climate.daylight_hours(hours, wind, lambda t: 2.0, {day: (rise, set_)})]
        self.assertEqual(got[0], 6)
        self.assertEqual(got[-1], 18)           # sunset 6:05 PM: the 6 PM hour is the one the light runs out in

    def test_the_hour_after_that_is_not_included(self):
        day = datetime.date(2024, 3, 1)
        rise, set_ = datetime.datetime(2024, 3, 1, 6, 20), datetime.datetime(2024, 3, 1, 18, 50)   # sunset 6:50 PM
        hours = {datetime.datetime(2024, 3, 1, h): (1.0, 12.0, 250.0) for h in range(24)}
        wind = {k: (3.0, 75.0) for k in hours}
        got = [h[1] for h in climate.daylight_hours(hours, wind, lambda t: 2.0, {day: (rise, set_)})]
        self.assertEqual(got[-1], 19)           # 7:00 PM starts 10 minutes after sunset: still the last light
        set_late = datetime.datetime(2024, 3, 1, 18, 40)
        got = [h[1] for h in climate.daylight_hours(hours, wind, lambda t: 2.0, {day: (rise, set_late)})]
        self.assertEqual(got[-1], 18)           # 6:55 PM is the last start allowed: 7:00 PM would be dark

    def test_skips_hours_missing_any_series(self):
        day = datetime.date(2024, 3, 1)
        rise, set_ = datetime.datetime(2024, 3, 1, 6, 20), datetime.datetime(2024, 3, 1, 18, 5)
        waves = {datetime.datetime(2024, 3, 1, 9): (1.0, 12.0, 250.0)}
        wind = {datetime.datetime(2024, 3, 1, 9): (3.0, 75.0), datetime.datetime(2024, 3, 1, 10): (3.0, 75.0)}
        got = list(climate.daylight_hours(waves, wind, lambda t: 2.0, {day: (rise, set_)}))
        self.assertEqual([h[1] for h in got], [9])

    def test_converts_total_height_to_swell_feet(self):
        day = datetime.date(2024, 3, 1)
        rise, set_ = datetime.datetime(2024, 3, 1, 9, 0), datetime.datetime(2024, 3, 1, 10, 0)
        t = datetime.datetime(2024, 3, 1, 9)
        got = next(climate.daylight_hours({t: (2.0, 15.0, 260.0)}, {t: (4.0, 80.0)}, lambda x: 1.0, {day: (rise, set_)}))
        self.assertAlmostEqual(got[2], 2.0 * 0.70 * 3.28084, places=3)


class Build(unittest.TestCase):
    def test_a_break_needs_a_year_of_history(self):
        with self.assertRaises(ValueError):
            climate.build(list(synthetic_hours(200)), CFG)

    def test_produces_anchors_and_a_benchmark(self):
        b = climate.build(list(synthetic_hours(800)), CFG)
        self.assertEqual(len(b["anchors"]), 10)
        self.assertEqual(b["history"]["days"], 800)
        self.assertIn("9", b["typical"])
        self.assertGreater(b["typical"]["9"]["period_s"], b["typical"]["7"]["period_s"] - 0.01)
        self.assertEqual(b["signature"], climate.signature(CFG))

    def test_rare_ratings_are_rarer(self):
        b = climate.build(list(synthetic_hours(800)), CFG)
        per = b["days_per_year"]
        self.assertGreaterEqual(per["5"], per["7"])
        self.assertGreaterEqual(per["7"], per["9"])


class Signature(unittest.TestCase):
    def test_changes_when_the_breaks_settings_change(self):
        self.assertNotEqual(climate.signature(CFG), climate.signature(dict(CFG, height_ideal_ft=[4.0, 8.0])))
        self.assertNotEqual(climate.signature(CFG), climate.signature(dict(CFG, buoys=["46225"])))

    def test_ignores_settings_that_do_not_move_the_score(self):
        self.assertEqual(climate.signature(CFG), climate.signature(dict(CFG, notes="x", alert_score_min=80)))


if __name__ == "__main__":
    unittest.main()
