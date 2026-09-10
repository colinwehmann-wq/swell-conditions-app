"""Unit tests for the scoring / window logic — the stuff that decides GO vs no."""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sources import evaluate as E

UTC = datetime.timezone.utc

CFG = {
    "name": "Test",
    "height_ok_ft": [2.5, 9.0], "height_ideal_ft": [3.5, 6.5],
    "period_min_s": 8.0, "period_ideal_s": 13.0,
    "swell_dir_deg": [190, 315],
    "offshore_dir_deg": [40, 110],
    "wind_ideal_kn": 6.0, "wind_max_kn": 12.0,
    "tide_ok_ft": [0.5, 5.0], "tide_ideal_ft": [1.5, 4.0],
    "alert_score_min": 66,
}


class Ramp(unittest.TestCase):
    def test_linear(self):
        self.assertAlmostEqual(E._ramp(5, 0, 10), 0.5)
        self.assertAlmostEqual(E._ramp(2.5, 0, 10), 0.25)

    def test_clamped(self):
        self.assertEqual(E._ramp(-3, 0, 10), 0.0)
        self.assertEqual(E._ramp(99, 0, 10), 1.0)

    def test_degenerate_ab_equal(self):
        self.assertEqual(E._ramp(9, 10, 10), 0.0)
        self.assertEqual(E._ramp(10, 10, 10), 1.0)
        self.assertEqual(E._ramp(11, 10, 10), 1.0)

    def test_descending(self):
        self.assertAlmostEqual(E._ramp(3, 10, 0), 0.7)


class Band(unittest.TestCase):
    OK, IDEAL = [2.0, 10.0], [4.0, 7.0]

    def test_inside_ideal_is_one(self):
        self.assertEqual(E._band(5.0, self.OK, self.IDEAL), 1.0)
        self.assertEqual(E._band(4.0, self.OK, self.IDEAL), 1.0)
        self.assertEqual(E._band(7.0, self.OK, self.IDEAL), 1.0)

    def test_ramp_up_below_ideal(self):
        self.assertAlmostEqual(E._band(3.0, self.OK, self.IDEAL), 0.5)

    def test_ramp_down_above_ideal(self):
        self.assertAlmostEqual(E._band(8.5, self.OK, self.IDEAL), 0.5)

    def test_outside_ok_is_zero(self):
        self.assertEqual(E._band(1.9, self.OK, self.IDEAL), 0.0)
        self.assertEqual(E._band(10.1, self.OK, self.IDEAL), 0.0)
        self.assertEqual(E._band(2.0, self.OK, self.IDEAL), 0.0)


class Angles(unittest.TestCase):
    def test_ang_dist_wraps(self):
        self.assertEqual(E._ang_dist(10, 350), 20)
        self.assertEqual(E._ang_dist(350, 10), 20)
        self.assertEqual(E._ang_dist(0, 180), 180)
        self.assertEqual(E._ang_dist(90, 90), 0)

    def test_in_arc_simple(self):
        self.assertTrue(E._in_arc(200, 190, 315))
        self.assertFalse(E._in_arc(320, 190, 315))

    def test_in_arc_wraparound(self):
        self.assertTrue(E._in_arc(10, 340, 20))
        self.assertTrue(E._in_arc(350, 340, 20))
        self.assertFalse(E._in_arc(200, 340, 20))

    def test_in_arc_none(self):
        self.assertFalse(E._in_arc(None, 0, 90))

    def test_arc_center(self):
        self.assertAlmostEqual(E._arc_center(190, 315), 252.5)
        self.assertAlmostEqual(E._arc_center(350, 10), 0.0)


class DirScore(unittest.TestCase):
    def test_inside_window(self):
        self.assertEqual(E._dir_score(250, 190, 315), 1.0)

    def test_falloff_outside(self):
        # 5 deg past the 315 edge -> clamp(1 - 5/45) * 0.6
        self.assertAlmostEqual(E._dir_score(320, 190, 315), (1 - 5 / 45) * 0.6, places=4)

    def test_far_outside_is_zero(self):
        self.assertEqual(E._dir_score(90, 190, 315), 0.0)

    def test_unknown_is_neutral(self):
        self.assertEqual(E._dir_score(None, 190, 315), 0.5)


class WindScore(unittest.TestCase):
    def test_missing_speed(self):
        self.assertEqual(E._wind_score(None, 75, CFG), 0.6)

    def test_offshore_light_is_perfect(self):
        self.assertEqual(E._wind_score(5, 75, CFG), 1.0)

    def test_offshore_gale_penalised(self):
        self.assertAlmostEqual(E._wind_score(30, 75, CFG), 0.75, places=3)

    def test_onshore_light_capped_low(self):
        self.assertAlmostEqual(E._wind_score(6, 270, CFG), 0.6, places=3)

    def test_onshore_strong_is_zero(self):
        self.assertEqual(E._wind_score(15, 270, CFG), 0.0)


class WindRelation(unittest.TestCase):
    def test_offshore(self):
        self.assertEqual(E.wind_relation(75, CFG), "offshore")

    def test_onshore(self):
        self.assertEqual(E.wind_relation(270, CFG), "onshore")

    def test_cross(self):
        self.assertEqual(E.wind_relation(135, CFG), "cross")

    def test_none(self):
        self.assertIsNone(E.wind_relation(None, CFG))


class Gates(unittest.TestCase):
    def test_all_clear(self):
        self.assertTrue(E._gates_ok(4.0, 10.0, 3.0, 75, CFG))

    def test_too_small(self):
        self.assertFalse(E._gates_ok(2.0, 10.0, 3.0, 75, CFG))

    def test_too_big(self):
        self.assertFalse(E._gates_ok(9.5, 10.0, 3.0, 75, CFG))

    def test_period_too_short(self):
        self.assertFalse(E._gates_ok(4.0, 7.5, 3.0, 75, CFG))

    def test_blown_out(self):
        self.assertFalse(E._gates_ok(4.0, 10.0, 18.0, 270, CFG))

    def test_missing_data(self):
        self.assertFalse(E._gates_ok(None, 10.0, 3.0, 75, CFG))
        self.assertFalse(E._gates_ok(4.0, None, 3.0, 75, CFG))


class ScoreComposition(unittest.TestCase):
    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(E.WEIGHTS.values()), 1.0)

    def test_perfect_conditions_near_100(self):
        total, sub = E.score(5.0, 14.0, 250, 3.0, 75, 2.5, CFG)
        self.assertGreater(total, 95)
        self.assertEqual(sub["height"], 1.0)
        self.assertEqual(sub["wind"], 1.0)

    def test_missing_everything_is_low(self):
        total, _ = E.score(None, None, None, None, None, None, CFG)
        # only swell_dir (0.5) + wind (0.6) + tide (0.5) contribute
        self.assertLess(total, 45)


def _rows(scores, gates=None, start_hour=6):
    base = datetime.datetime(2026, 9, 9, start_hour, tzinfo=UTC)
    gates = gates if gates is not None else [True] * len(scores)
    return [
        {"time": base + datetime.timedelta(hours=i), "score": s, "gates_ok": g}
        for i, (s, g) in enumerate(zip(scores, gates))
    ]


class BestWindow(unittest.TestCase):
    def test_finds_contiguous_run(self):
        w = E._best_window(_rows([50, 70, 80, 75, 40, 90]), threshold=66)
        self.assertEqual(w["peak_score"], 90)         # the lone 90 beats the 70-80-75 block
        self.assertEqual(w["peak"].hour, 11)

    def test_picks_highest_peak_block(self):
        w = E._best_window(_rows([70, 80, 75, 40, 50]), threshold=66)
        self.assertEqual(w["start"].hour, 6)
        self.assertEqual(w["end"].hour, 9)            # last qualifying hour (8) + 1
        self.assertEqual(w["peak"].hour, 7)

    def test_gate_failure_excludes_hour(self):
        w = E._best_window(_rows([90, 90], gates=[False, True]), threshold=66)
        self.assertEqual(len(w["rows"]), 1)
        self.assertEqual(w["peak"].hour, 7)

    def test_nothing_qualifies(self):
        self.assertIsNone(E._best_window(_rows([10, 20, 30]), threshold=66))

    def test_empty(self):
        self.assertIsNone(E._best_window([], threshold=66))


if __name__ == "__main__":
    unittest.main()
