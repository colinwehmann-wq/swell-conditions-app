"""Tests for the multi-day outlook, full-day timeline and buoy calibration."""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sources import evaluate as E

TZ = datetime.timezone(datetime.timedelta(hours=-7))

CFG = {
    "name": "Test",
    "height_ok_ft": [2.5, 9.0], "height_ideal_ft": [3.5, 6.5],
    "period_min_s": 8.0, "period_ideal_s": 13.0,
    "swell_dir_deg": [190, 315],
    "offshore_dir_deg": [40, 110],
    "wind_ideal_kn": 6.0, "wind_max_kn": 12.0,
    "tide_ok_ft": [0.5, 5.0], "tide_ideal_ft": [1.5, 4.0],
    "alert_score_min": 70,
}

DAY0 = datetime.date(2026, 10, 13)


def at(day_offset, hour, minute=0):
    d = DAY0 + datetime.timedelta(days=day_offset)
    return datetime.datetime(d.year, d.month, d.day, hour, minute, tzinfo=TZ)


def sun_for(days):
    return {DAY0 + datetime.timedelta(days=i): (at(i, 6, 30), at(i, 18, 0)) for i in range(days)}


def forecast(days, height_m=1.2, period=14.0, wind_kn=3.0, wind_dir=75):
    marine, wind = {}, {}
    for i in range(days):
        for h in range(24):
            t = at(i, h)
            marine[t] = {"swell_wave_height": height_m, "swell_wave_period": period,
                         "swell_wave_direction": 250}
            wind[t] = {"wind_speed_10m": wind_kn, "wind_direction_10m": wind_dir}
    return marine, wind


IDENTITY = {"h_scale": 1.0, "p_shift": 0.0}


class Outlook(unittest.TestCase):
    def run_outlook(self, now, marine, wind, days=7, sun_days=10):
        return E.outlook(CFG, now, None, None, marine, wind, sun_for(sun_days), IDENTITY, days=days)

    def test_after_sunset_skips_today(self):
        marine, wind = forecast(10)
        out = self.run_outlook(at(0, 20), marine, wind)
        self.assertEqual(out[0]["lead_days"], 1)
        self.assertEqual(len(out), 7)

    def test_before_sunset_includes_today(self):
        marine, wind = forecast(10)
        out = self.run_outlook(at(0, 9), marine, wind)
        self.assertEqual(out[0]["lead_days"], 0)

    def test_good_day_scores_high_and_has_a_window(self):
        marine, wind = forecast(10)
        day = self.run_outlook(at(0, 20), marine, wind)[0]
        # a good day, not a peak one: 14 s and a size off the middle of the band can't earn full marks
        self.assertGreater(day["rating_score"], 80)
        self.assertLess(day["rating_score"], 95)
        self.assertIsNotNone(day["window"])

    def test_failed_gate_caps_the_day(self):
        marine, wind = forecast(10, height_m=0.3)            # ~1 ft: below the ok band
        day = self.run_outlook(at(0, 20), marine, wind)[0]
        self.assertLessEqual(day["rating_score"], E.RATING_GATE_CAP)
        self.assertIsNone(day["window"])

    def test_height_range_is_reported_in_feet(self):
        marine, wind = forecast(10, height_m=1.0)
        lo, hi = self.run_outlook(at(0, 20), marine, wind)[0]["height_range_ft"]
        self.assertAlmostEqual(lo, 3.28, places=1)
        self.assertAlmostEqual(hi, 3.28, places=1)

    def test_days_without_forecast_data_are_skipped(self):
        marine, wind = forecast(3)                            # only 3 days of model data
        out = self.run_outlook(at(0, 20), marine, wind, sun_days=10)
        self.assertEqual([d["lead_days"] for d in out], [1, 2])

    def test_respects_requested_day_count(self):
        marine, wind = forecast(10)
        self.assertEqual(len(self.run_outlook(at(0, 20), marine, wind, days=3)), 3)


class Timeline(unittest.TestCase):
    def test_covers_the_whole_day_even_in_the_evening(self):
        marine, wind = forecast(2)
        rows = E.timeline(CFG, DAY0, sun_for(1)[DAY0], at(0, 20), None, None, marine, wind, IDENTITY)
        self.assertEqual(rows[0]["time"].hour, 6)              # starts at sunrise, not at "now"
        self.assertEqual(rows[-1]["time"].hour, 18)            # sunset is 6:00 PM: the 6 PM hour is the last, so dusk sessions count
        self.assertEqual(len(rows), 13)


class Calibration(unittest.TestCase):
    def buoy(self, swell_m, period, stale=False):
        return {"stale": stale, "swh_m": swell_m, "wvht_m": swell_m, "swp_s": period,
                "apd_s": period, "swd_deg": 250.0, "mwd_deg": 250.0}

    def test_scales_model_onto_buoy(self):
        marine, wind = forecast(2, height_m=1.0, period=10.0)
        c = E.calibration(at(0, 9), marine, wind, None, self.buoy(1.5, 13.0))
        self.assertAlmostEqual(c["h_scale"], 1.5)
        self.assertAlmostEqual(c["p_shift"], 3.0)

    def test_clamped(self):
        marine, wind = forecast(2, height_m=0.5, period=10.0)
        c = E.calibration(at(0, 9), marine, wind, None, self.buoy(2.0, 20.0))
        self.assertEqual(c["h_scale"], 2.0)
        self.assertEqual(c["p_shift"], 3.0)

    def test_identity_without_a_fresh_buoy(self):
        marine, wind = forecast(2)
        self.assertEqual(E.calibration(at(0, 9), marine, wind, None, None), IDENTITY)
        self.assertEqual(E.calibration(at(0, 9), marine, wind, None, self.buoy(2.0, 12.0, stale=True)), IDENTITY)


if __name__ == "__main__":
    unittest.main()
