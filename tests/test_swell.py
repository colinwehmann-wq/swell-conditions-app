"""Tests for scoring both swell trains: how the trains combine, what reaches a break, display."""
import datetime
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import sitegen
from sitegen import render
from sources import evaluate as E
from sources import skill, verify

TZ = datetime.timezone(datetime.timedelta(hours=-7))
NOW = datetime.datetime(2026, 10, 13, 10, 0, tzinfo=TZ)
CFG = config.spot_config(config.SPOTS[0])        # Swami's: swell window 190-315 degrees
M_TO_FT = E.M_TO_FT


def row(**kw):
    base = {"swell_wave_height": 1.2, "swell_wave_period": 14.0, "swell_wave_direction": 250.0}
    base.update(kw)
    return base


def train(h, p, d):
    return {"h": h, "p": p, "d": d}


class Receptivity(unittest.TestCase):
    def test_inside_the_window_is_full(self):
        self.assertEqual(E._receptivity(250, CFG), 1.0)
        self.assertEqual(E._receptivity(190, CFG), 1.0)

    def test_fades_to_nothing_over_45_degrees(self):
        self.assertAlmostEqual(E._receptivity(190 - 22.5, CFG), 0.5)
        self.assertEqual(E._receptivity(190 - 45, CFG), 0.0)
        self.assertEqual(E._receptivity(100, CFG), 0.0)

    def test_the_window_edge_on_the_other_side_works_too(self):
        self.assertAlmostEqual(E._receptivity(315 + 9, CFG), 0.8)

    def test_no_cfg_means_everything_counts(self):
        self.assertEqual(E._receptivity(100, None), 1.0)

    def test_unknown_direction_gets_half(self):
        self.assertEqual(E._receptivity(None, CFG), 0.5)


class ModelTrains(unittest.TestCase):
    def test_primary_only(self):
        self.assertEqual(E.model_trains(row()), [train(1.2, 14.0, 250.0)])

    def test_real_secondary_is_added_after_the_primary(self):
        t = E.model_trains(row(secondary_swell_wave_height=0.6, secondary_swell_wave_period=9.0,
                               secondary_swell_wave_direction=290.0))
        self.assertEqual(t[1], train(0.6, 9.0, 290.0))

    def test_chop_is_not_a_train(self):
        t = E.model_trains(row(secondary_swell_wave_height=0.6, secondary_swell_wave_period=6.0))
        self.assertEqual(len(t), 1)

    def test_empty_or_zero_secondary_is_ignored(self):
        self.assertEqual(len(E.model_trains(row(secondary_swell_wave_height=0.0, secondary_swell_wave_period=10.0))), 1)
        self.assertEqual(len(E.model_trains(row(secondary_swell_wave_height=None, secondary_swell_wave_period=None))), 1)

    def test_no_primary_swell_means_no_trains(self):
        self.assertEqual(E.model_trains({"wave_height": 1.0}), [])
        self.assertEqual(E.model_trains({"swell_wave_height": 1.0}), [])


class CombineSwell(unittest.TestCase):
    def test_a_single_train_comes_back_unchanged(self):
        self.assertEqual(E.combine_swell([train(1.2, 14.0, 250.0)], CFG), (1.2, 14.0, 250.0))
        self.assertEqual(E.combine_swell([train(1.2, 14.0, 250.0)]), (1.2, 14.0, 250.0))

    def test_height_adds_half_the_secondary_energy(self):
        h, _p, _d = E.combine_swell([train(2.0, 14.0, 250.0), train(1.0, 9.0, 260.0)], CFG)
        self.assertAlmostEqual(h, math.sqrt(4.0 + 0.5 * 1.0))

    def test_a_train_that_misses_the_break_adds_nothing(self):
        h, _p, _d = E.combine_swell([train(2.0, 14.0, 250.0), train(1.5, 12.0, 100.0)], CFG)
        self.assertAlmostEqual(h, 2.0)

    def test_a_partly_off_angle_train_adds_part(self):
        h, _p, _d = E.combine_swell([train(2.0, 14.0, 250.0), train(1.0, 12.0, 190 - 22.5)], CFG)
        self.assertAlmostEqual(h, math.sqrt(4.0 + 0.5 * 0.5))

    def test_a_buoy_comparison_counts_all_of_it(self):
        h, _p, _d = E.combine_swell([train(2.0, 14.0, 250.0), train(1.0, 12.0, 100.0)])
        self.assertAlmostEqual(h, math.sqrt(4.0 + 0.5))

    def test_period_is_the_power_weighted_mean(self):
        # energy 4 and 0.5; power (energy x period) 56 and 4 -> (56*14 + 4*8) / 60
        _h, p, _d = E.combine_swell([train(2.0, 14.0, 250.0), train(1.0, 8.0, 260.0)], CFG)
        self.assertAlmostEqual(p, (56 * 14 + 4 * 8) / 60.0)

    def test_a_tiny_secondary_barely_moves_the_period(self):
        _h, p, _d = E.combine_swell([train(2.0, 14.0, 250.0), train(0.2, 8.0, 260.0)], CFG)
        self.assertGreater(p, 13.9)

    def test_a_secondary_with_a_longer_period_lifts_it(self):
        _h, p, _d = E.combine_swell([train(1.5, 9.0, 250.0), train(1.2, 16.0, 200.0)], CFG)
        self.assertGreater(p, 9.0)

    def test_direction_is_the_longest_period_significant_train(self):
        # shares: 4 and 1.44 of 5.44 -> 26% clears the 25% bar, so the 16 s train sets the direction
        _h, _p, d = E.combine_swell([train(2.0, 10.0, 300.0), train(1.2, 16.0, 200.0)], CFG)
        self.assertEqual(d, 200.0)

    def test_an_insignificant_train_does_not_set_the_direction(self):
        _h, _p, d = E.combine_swell([train(2.0, 10.0, 300.0), train(0.9, 16.0, 200.0)], CFG)
        self.assertEqual(d, 300.0)

    def test_direction_ignores_trains_with_no_direction(self):
        _h, _p, d = E.combine_swell([train(2.0, 10.0, 300.0), train(1.5, 16.0, None)], CFG)
        self.assertEqual(d, 300.0)

    def test_unknown_primary_direction_stays_unknown(self):
        _h, _p, d = E.combine_swell([train(2.0, 10.0, None)], CFG)
        self.assertIsNone(d)


class Conditions(unittest.TestCase):
    def cond(self, marine_row, cfg=CFG, calib=None, buoy=None, use_buoy=False):
        return E._conditions(NOW, marine_row, {}, None, buoy, use_buoy=use_buoy, calib=calib, cfg=cfg)

    def test_without_a_secondary_nothing_changes(self):
        h, p, d, *_ = self.cond(row())
        self.assertAlmostEqual(h, 1.2 * M_TO_FT)
        self.assertEqual((p, d), (14.0, 250.0))

    def test_a_secondary_makes_the_break_bigger(self):
        base = self.cond(row())[0]
        mixed = self.cond(row(secondary_swell_wave_height=0.8, secondary_swell_wave_period=10.0,
                              secondary_swell_wave_direction=270.0))[0]
        self.assertGreater(mixed, base)

    def test_calibration_height_is_scaled_after_combining(self):
        mixed = row(secondary_swell_wave_height=0.8, secondary_swell_wave_period=10.0,
                    secondary_swell_wave_direction=270.0)
        plain = self.cond(mixed)[0]
        scaled = self.cond(mixed, calib={"h_scale": 1.5, "p_shift": 0.0})[0]
        self.assertAlmostEqual(scaled, plain * 1.5)

    def test_period_shift_applies_on_top(self):
        _h, p, *_ = self.cond(row(), calib={"h_scale": 1.0, "p_shift": 2.0})
        self.assertEqual(p, 16.0)

    def test_a_model_without_swell_partitions_falls_back_to_total_wave_height(self):
        h, p, d, *_ = self.cond({"wave_height": 1.5, "wave_period": 11.0, "wave_direction": 240.0})
        self.assertAlmostEqual(h, 1.5 * M_TO_FT)
        self.assertEqual((p, d), (11.0, 240.0))

    def test_the_live_buoy_is_taken_as_it_reads_and_ignores_the_models_secondary(self):
        buoy = {"stale": False, "swh_m": 1.0, "wvht_m": 1.1, "swp_s": 15.0, "apd_s": 8.0,
                "swd_deg": 200.0, "mwd_deg": 210.0}
        mixed = row(secondary_swell_wave_height=2.0, secondary_swell_wave_period=12.0,
                    secondary_swell_wave_direction=250.0)
        h, p, d, *_ = self.cond(mixed, buoy=buoy, use_buoy=True)
        self.assertAlmostEqual(h, 1.0 * M_TO_FT)
        self.assertEqual((p, d), (15.0, 200.0))


class Calibration(unittest.TestCase):
    BUOY = {"stale": False, "swh_m": 1.0, "wvht_m": 1.1, "swp_s": 15.0, "apd_s": 8.0,
            "swd_deg": 200.0, "mwd_deg": 210.0}

    def test_calibrates_against_everything_the_model_sees_not_just_what_hits_one_break(self):
        # The secondary comes from a direction Swami's can't see (100 degrees). The buoy would still
        # read it, so calibration must count it in full while scoring at the break does not.
        hour = E.floor_hour(NOW)
        marine = {hour: row(swell_wave_height=0.8, secondary_swell_wave_height=0.6,
                            secondary_swell_wave_period=10.0, secondary_swell_wave_direction=100.0)}
        calib = E.calibration(NOW, marine, {}, None, self.BUOY)
        expected = 1.0 / math.sqrt(0.8 ** 2 + 0.5 * 0.6 ** 2)
        self.assertAlmostEqual(calib["h_scale"], expected, places=3)
        at_break = E._conditions(hour, marine[hour], {}, None, self.BUOY, use_buoy=False, cfg=CFG)[0]
        self.assertAlmostEqual(at_break, 0.8 * M_TO_FT)


class EvaluateSpot(unittest.TestCase):
    SUN = (datetime.datetime(2026, 10, 13, 6, 30, tzinfo=TZ), datetime.datetime(2026, 10, 13, 18, 0, tzinfo=TZ))

    def spot(self, marine_row):
        marine = {E.floor_hour(NOW): marine_row}
        sun_tomorrow = tuple(t + datetime.timedelta(days=1) for t in self.SUN)
        return E.evaluate_spot(CFG, NOW, None, None, marine, {}, self.SUN, sun_tomorrow)

    def test_reports_no_secondary_when_there_isnt_one(self):
        self.assertIsNone(self.spot(row())["secondary_swell"])

    def test_reports_a_real_secondary_for_display(self):
        res = self.spot(row(secondary_swell_wave_height=0.6, secondary_swell_wave_period=10.0,
                            secondary_swell_wave_direction=270.0))
        s = res["secondary_swell"]
        self.assertAlmostEqual(s["height_ft"], 0.6 * M_TO_FT)
        self.assertEqual((s["period_s"], s["dir_deg"], s["in_window"]), (10.0, 270.0, True))

    def test_a_secondary_under_a_foot_is_not_worth_mentioning(self):
        self.assertIsNone(E.secondary_train(CFG, row(secondary_swell_wave_height=0.25,
                                                     secondary_swell_wave_period=10.0)))

    def test_a_secondary_far_smaller_than_the_primary_is_not_worth_mentioning(self):
        r = row(swell_wave_height=3.0, secondary_swell_wave_height=0.35,
                secondary_swell_wave_period=10.0)
        self.assertIsNone(E.secondary_train(CFG, r))

    def test_off_angle_secondary_is_flagged(self):
        s = E.secondary_train(CFG, row(secondary_swell_wave_height=0.8, secondary_swell_wave_period=10.0,
                                       secondary_swell_wave_direction=120.0))
        self.assertFalse(s["in_window"])

    def test_a_good_second_swell_can_only_help_the_score(self):
        alone = self.spot(row())["now_score"]
        mixed = self.spot(row(secondary_swell_wave_height=0.9, secondary_swell_wave_period=12.0,
                              secondary_swell_wave_direction=260.0))["now_score"]
        self.assertGreaterEqual(mixed, alone - 1e-9)


class Site(unittest.TestCase):
    def payload(self, marine_row):
        from tests.test_sitegen import DAY0, at, forecast, sun_for
        marine, wind = forecast(10, 1.2)
        for t in marine:
            marine[t].update({k: v for k, v in marine_row.items()})
        now = at(0, 10)
        sun = sun_for(10)
        cfg = config.spot_config(config.SPOTS[0])
        res = E.evaluate_spot(cfg, now, None, None, marine, wind, sun[DAY0], sun[DAY0 + datetime.timedelta(days=1)])
        calib = E.calibration(now, marine, wind, None, None)
        item = {"result": res, "outlook": E.outlook(cfg, now, None, None, marine, wind, sun, calib, days=7),
                "sun": sun[DAY0], "timeline_day": DAY0,
                "timeline": E.timeline(cfg, DAY0, sun[DAY0], now, None, None, marine, wind, calib)}
        return sitegen.make_payload([item], now)

    def test_payload_has_no_secondary_by_default(self):
        self.assertIsNone(self.payload({})["spots"][0]["secondary_swell"])

    def test_payload_and_page_describe_the_second_swell(self):
        p = self.payload({"secondary_swell_wave_height": 0.7, "secondary_swell_wave_period": 10.0,
                          "secondary_swell_wave_direction": 270.0})
        s = p["spots"][0]["secondary_swell"]
        self.assertEqual((s["dir"], s["period_s"], s["in_window"]), ("W", 10, True))
        page = render.spot_page(p["spots"][0], p)
        self.assertIn("plus W 2.3 ft at 10 s", page)
        self.assertNotIn("off-angle", page)

    def test_page_says_when_the_second_swell_misses_the_break(self):
        p = self.payload({"secondary_swell_wave_height": 0.7, "secondary_swell_wave_period": 10.0,
                          "secondary_swell_wave_direction": 120.0})
        self.assertIn("off-angle", render.spot_page(p["spots"][0], p))

    def test_page_is_unchanged_without_a_second_swell(self):
        p = self.payload({})
        self.assertNotIn("plus ", render.spot_page(p["spots"][0], p).split('class="stats"')[1].split("</dl>")[0])


class ScoredInTheAccuracyReport(unittest.TestCase):
    ISSUED = datetime.datetime(2026, 10, 14, 6, 0, tzinfo=TZ)

    def log(self):
        t = self.ISSUED + datetime.timedelta(hours=3)
        fc = {"k": "fc", "issued": self.ISSUED.isoformat(), "buoy": "46224", "model": "default",
              "rows": [{"t": t.isoformat(), "lead": 3, "sh": 2.0, "sp": 14.0, "sd": 300.0,
                        "s2h": 1.2, "s2p": 16.0, "s2d": 200.0}]}
        o = {"k": "ob", "buoy": "46224", "t": t.astimezone(datetime.timezone.utc).isoformat(),
             "sh": 2.2, "sp": 15.0, "sd": 205.0}
        return [fc, o]

    def pair(self, label):
        return [p for p in skill.pairs(self.log()) if p["model"] == "default" and p["var"] == label][0]

    def test_combined_rows_are_derived_from_the_same_code_the_app_uses(self):
        self.assertAlmostEqual(self.pair("Swell height, both trains (m)")["fc"], math.sqrt(4.0 + 0.5 * 1.44))
        self.assertEqual(self.pair("Swell direction, both trains (deg)")["fc"], 200.0)
        self.assertGreater(self.pair("Swell period, both trains (s)")["fc"], 14.0)

    def test_primary_only_rows_are_still_there_for_comparison(self):
        self.assertEqual(self.pair("Swell height (m)")["fc"], 2.0)
        self.assertEqual(self.pair("Swell direction (deg)")["fc"], 300.0)

    def test_a_model_with_no_secondary_data_scores_the_same_both_ways(self):
        recs = self.log()
        for k in ("s2h", "s2p", "s2d"):
            del recs[0]["rows"][0][k]
        pairs = skill.pairs(recs)
        both = [p for p in pairs if p["var"] == "Swell height, both trains (m)"][0]
        prim = [p for p in pairs if p["var"] == "Swell height (m)" and p["model"] == "default"][0]
        self.assertEqual(both["fc"], prim["fc"])

    def test_the_secondary_direction_is_logged(self):
        self.assertIn("secondary_swell_wave_direction", verify.FC_VARS)
        rec = verify.forecast_record(NOW, "46224", "default", {
            NOW: {"secondary_swell_wave_direction": 197.6, "secondary_swell_wave_height": 0.5}})
        self.assertEqual(rec["rows"][0]["s2d"], 198.0)


if __name__ == "__main__":
    unittest.main()
