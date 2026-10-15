"""Tests for forecast scoring: pairing forecasts with outcomes, error maths, persistence, the report."""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sources import skill

UTC = datetime.timezone.utc
PDT = datetime.timezone(datetime.timedelta(hours=-7))
ISSUED = datetime.datetime(2026, 10, 14, 6, 0, tzinfo=PDT)          # 13:00 UTC


def ob(minutes_after_issue, buoy="46224", **vals):
    t = ISSUED.astimezone(UTC) + datetime.timedelta(minutes=minutes_after_issue)
    rec = {"k": "ob", "buoy": buoy, "t": t.isoformat()}
    rec.update(vals)
    return rec


def fc(rows, model="default", buoy="46224", issued=ISSUED):
    out = []
    for lead, vals in rows:
        t = issued + datetime.timedelta(hours=lead)
        row = {"t": t.isoformat(), "lead": lead}
        row.update(vals)
        out.append(row)
    return {"k": "fc", "issued": issued.isoformat(), "buoy": buoy, "model": model, "rows": out}


def only(pair_list, model, var):
    return [p for p in pair_list if p["model"] == model and p["var"] == var]


class AngleDiff(unittest.TestCase):
    def test_wraps_the_short_way_round(self):
        self.assertEqual(skill.angle_diff(355, 5), -10)
        self.assertEqual(skill.angle_diff(5, 355), 10)
        self.assertEqual(skill.angle_diff(200, 190), 10)

    def test_half_turn_is_positive_180(self):
        self.assertEqual(skill.angle_diff(0, 180), 180)
        self.assertEqual(skill.angle_diff(180, 0), 180)


class Bucket(unittest.TestCase):
    def test_edges(self):
        self.assertEqual(skill.bucket(0), "0-6h")
        self.assertEqual(skill.bucket(5), "0-6h")
        self.assertEqual(skill.bucket(6), "6-12h")
        self.assertEqual(skill.bucket(47), "24-48h")
        self.assertEqual(skill.bucket(72), "48-72h")
        self.assertIsNone(skill.bucket(73))


class Pairs(unittest.TestCase):
    def test_error_is_forecast_minus_observed(self):
        recs = [ob(180, sh=1.0, hs=1.4), fc([(3, {"sh": 1.25, "hs": 1.3})])]
        got = skill.pairs(recs)
        self.assertAlmostEqual(only(got, "default", "Swell height (m)")[0]["err"], 0.25)
        self.assertAlmostEqual(only(got, "default", "Total wave height (m)")[0]["err"], -0.1)

    def test_tolerance_window(self):
        near = skill.pairs([ob(180 + 40, sh=1.0), fc([(3, {"sh": 1.0})])])
        far = skill.pairs([ob(180 + 50, sh=1.0), fc([(3, {"sh": 1.0})])])
        self.assertEqual(len(only(near, "default", "Swell height (m)")), 1)
        self.assertEqual(only(far, "default", "Swell height (m)"), [])

    def test_the_closest_reading_wins(self):
        recs = [ob(180 - 20, sh=9.0), ob(180 + 5, sh=1.0), fc([(3, {"sh": 1.0})])]
        self.assertEqual(only(skill.pairs(recs), "default", "Swell height (m)")[0]["ob"], 1.0)

    def test_direction_error_wraps(self):
        recs = [ob(180, sd=5.0), fc([(3, {"sd": 355.0})])]
        self.assertEqual(only(skill.pairs(recs), "default", "Swell direction (deg)")[0]["err"], -10)

    def test_no_pair_without_a_matching_observation(self):
        self.assertEqual(skill.pairs([fc([(3, {"sh": 1.0})])]), [])
        self.assertEqual(skill.pairs([ob(180, sh=1.0, buoy="46225"), fc([(3, {"sh": 1.0})])]), [])

    def test_a_forecast_for_the_future_has_nothing_to_score_against_yet(self):
        recs = [ob(0, sh=1.0), fc([(0, {"sh": 1.0}), (48, {"sh": 2.0})])]
        leads = [p["lead"] for p in only(skill.pairs(recs), "default", "Swell height (m)")]
        self.assertEqual(leads, [0])

    def test_variables_the_model_lacks_are_skipped(self):
        recs = [ob(180, sh=1.0, hs=1.2), fc([(3, {"hs": 1.5})], model="ecmwf_wam")]
        got = skill.pairs(recs)
        self.assertEqual(only(got, "ecmwf_wam", "Swell height (m)"), [])
        self.assertEqual(len(only(got, "ecmwf_wam", "Total wave height (m)")), 1)

    def test_models_are_kept_separate(self):
        recs = [ob(180, sh=1.0), fc([(3, {"sh": 1.1})], "a"), fc([(3, {"sh": 1.5})], "b")]
        got = skill.pairs(recs)
        self.assertAlmostEqual(only(got, "a", "Swell height (m)")[0]["err"], 0.1)
        self.assertAlmostEqual(only(got, "b", "Swell height (m)")[0]["err"], 0.5)


class Persistence(unittest.TestCase):
    def test_predicts_the_reading_from_before_issue_time(self):
        recs = [ob(-4, sh=0.8), ob(180, sh=1.0), fc([(3, {"sh": 1.0})])]
        p = only(skill.pairs(recs), "persistence", "Swell height (m)")
        self.assertEqual(len(p), 1)
        self.assertAlmostEqual(p[0]["err"], -0.2)
        self.assertEqual(p[0]["lead"], 3)

    def test_is_not_scored_at_lead_zero(self):
        recs = [ob(-4, sh=0.8), ob(0, sh=0.8), fc([(0, {"sh": 0.8})])]
        self.assertEqual([p for p in skill.pairs(recs) if p["model"] == "persistence"], [])

    def test_needs_a_reading_from_before_issue_time(self):
        recs = [ob(180, sh=1.0), fc([(3, {"sh": 1.0})])]
        self.assertEqual([p for p in skill.pairs(recs) if p["model"] == "persistence"], [])

    def test_a_reading_from_after_issue_time_is_never_used(self):
        # the only nearby reading is 20 minutes *after* issue; using it would peek at the outcome
        recs = [ob(20, sh=5.0), ob(180, sh=1.0), fc([(3, {"sh": 1.0})])]
        self.assertEqual([p for p in skill.pairs(recs) if p["model"] == "persistence"], [])

    def test_counted_once_per_issue_time_not_once_per_model(self):
        recs = [ob(-4, sh=0.8), ob(180, sh=1.0), fc([(3, {"sh": 1.0})], "a"), fc([(3, {"sh": 1.0})], "b")]
        p = only(skill.pairs(recs), "persistence", "Swell height (m)")
        self.assertEqual(len(p), 1)


class Summarize(unittest.TestCase):
    def pair(self, err, fc_val, ob_val, lead=3, var="Swell height (m)", model="m"):
        return {"model": model, "buoy": "b", "lead": lead, "var": var, "fc": fc_val, "ob": ob_val, "err": err}

    def test_bias_mae_rmse_and_ratio(self):
        s = skill.summarize([self.pair(0.1, 1.1, 1.0), self.pair(-0.3, 0.7, 1.0)])
        st = s["Swell height (m)"]["m"]["0-6h"]
        self.assertEqual(st["n"], 2)
        self.assertAlmostEqual(st["bias"], -0.1)
        self.assertAlmostEqual(st["mae"], 0.2)
        self.assertAlmostEqual(st["rmse"], (0.05) ** 0.5)
        self.assertAlmostEqual(st["ratio"], 0.9)

    def test_groups_by_lead_bucket(self):
        s = skill.summarize([self.pair(0.1, 1, 1, lead=3), self.pair(0.2, 1, 1, lead=30)])
        self.assertEqual(sorted(s["Swell height (m)"]["m"]), ["0-6h", "24-48h"])

    def test_direction_has_no_ratio(self):
        s = skill.summarize([self.pair(10, 200, 190, var="Swell direction (deg)")])
        self.assertIsNone(s["Swell direction (deg)"]["m"]["0-6h"]["ratio"])


class Report(unittest.TestCase):
    def build_log(self, n=6, still=False):
        """n issue times 6 h apart. The swell is 1.0 m except right at each 3 h valid time, when
        it is 2.0 m (so "no change" is badly wrong). Model "good" says 2.1, "bad" says 2.5.
        With still=True the swell never changes, so persistence is perfect."""
        recs = []
        for i in range(n):
            issued = ISSUED + datetime.timedelta(hours=6 * i)
            recs.append(fc([(3, {"sh": 1.1 if still else 2.1})], "good", issued=issued))
            recs.append(fc([(3, {"sh": 1.5 if still else 2.5})], "bad", issued=issued))
        for minutes in range(-60, 6 * n * 60 + 300, 30):
            recs.append(ob(minutes, sh=2.0 if (minutes % 360 == 180 and not still) else 1.0))
        return recs

    def test_empty_log(self):
        self.assertIn("No forecasts logged yet", skill.format_report([]))

    def test_forecasts_without_outcomes_say_so(self):
        out = skill.format_report([fc([(3, {"sh": 1.0})])])
        self.assertIn("Nothing to score yet", out)

    def test_table_lists_every_model_and_persistence_and_stars_the_best(self):
        out = skill.format_report(self.build_log())
        self.assertIn("## Swell height (m)", out)
        self.assertIn("| good |", out)
        self.assertIn("| bad |", out)
        self.assertIn("| persistence |", out)
        good_row = [ln for ln in out.splitlines() if ln.startswith("| good |")][0]
        bad_row = [ln for ln in out.splitlines() if ln.startswith("| bad |")][0]
        self.assertIn("*", good_row.split("|")[2])
        self.assertNotIn("*", bad_row.split("|")[2])

    def test_thin_samples_are_flagged(self):
        out = skill.format_report(self.build_log(n=2))
        self.assertIn("n=2", out)

    def test_persistence_takes_the_star_when_no_model_beats_it(self):
        out = skill.format_report(self.build_log(still=True))
        rows = {ln.split("|")[1].strip(): ln.split("|")[2] for ln in out.splitlines()
                if ln.startswith("| ") and ln.split("|")[1].strip() in ("good", "bad", "persistence")}
        self.assertIn("*", rows["persistence"])
        self.assertNotIn("*", rows["good"])

    def test_ratio_line_is_reported_once_there_is_enough_data(self):
        out = skill.format_report(self.build_log())
        self.assertIn("ratio at 0-6h", out)
        self.assertIn("good 1.05", out)


if __name__ == "__main__":
    unittest.main()
