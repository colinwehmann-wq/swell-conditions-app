"""Personal alerts: which hours match a profile, when to tell the person, and what to say."""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sources import profiles as P

TZ = datetime.timezone(datetime.timedelta(hours=-7))
CFG = {"name": "Swami's", "offshore_dir_deg": [40, 110]}
DAY = datetime.date(2026, 10, 20)


def at(hour, minute=0, day=0):
    d = DAY + datetime.timedelta(days=day)
    return datetime.datetime(d.year, d.month, d.day, hour, minute, tzinfo=TZ)


def row(hour, h=4.0, p=14.0, sd=250, wk=3.0, wd=75, tide=2.5, score=70.0):
    return {"time": at(hour), "cond": (h, p, sd, wk, wd, tide), "score": score, "tide_state": "rising"}


def profile(**over):
    base = {"breaks": ["swamis"], "prefs": {"height_ft": [3, 6], "period_min_s": 10, "wind": "light", "wind_max_kn": 12}}
    base.update(over)
    return base


PREFS = P.prefs_for(profile(), "swamis")


class Preferences(unittest.TestCase):
    def test_defaults_then_profile_then_break(self):
        p = profile(prefs={"height_ft": [2, 4]}, overrides={"swamis": {"period_min_s": 14}})
        got = P.prefs_for(p, "swamis")
        self.assertEqual(got["height_ft"], [2, 4])
        self.assertEqual(got["period_min_s"], 14)
        self.assertEqual(got["wind"], "light")                       # default
        self.assertEqual(P.prefs_for(p, "windansea")["period_min_s"], 8.0)   # no override there

    def test_alert_defaults(self):
        self.assertEqual(P.alerts_of({})["lead_min"], 60)
        self.assertEqual(P.alerts_of({"alerts": {"lead_min": 90}})["lead_min"], 90)
        self.assertEqual(P.alerts_of({"alerts": {"lead_min": 90}})["min_hours"], 1)


class CheckHour(unittest.TestCase):
    def failed(self, cond, **prefs):
        return P.check_hour(cond, dict(PREFS, **prefs), CFG)

    def test_everything_met(self):
        self.assertEqual(self.failed((4.0, 14.0, 250, 3.0, 75, 2.5)), [])

    def test_size_is_inclusive_at_both_ends(self):
        self.assertEqual(self.failed((3.0, 14.0, 250, 3.0, 75, 2.5)), [])
        self.assertEqual(self.failed((6.0, 14.0, 250, 3.0, 75, 2.5)), [])
        self.assertEqual(self.failed((2.9, 14.0, 250, 3.0, 75, 2.5)), ["size"])
        self.assertEqual(self.failed((6.1, 14.0, 250, 3.0, 75, 2.5)), ["size"])

    def test_period(self):
        self.assertEqual(self.failed((4.0, 9.0, 250, 3.0, 75, 2.5)), ["period"])
        self.assertEqual(self.failed((4.0, 10.0, 250, 3.0, 75, 2.5)), [])

    def test_unknown_size_or_period_fails(self):
        self.assertIn("size", self.failed((None, 14.0, 250, 3.0, 75, 2.5)))
        self.assertIn("period", self.failed((4.0, None, 250, 3.0, 75, 2.5)))

    def test_light_wind_mode_is_about_speed_not_direction(self):
        self.assertEqual(self.failed((4.0, 14.0, 250, 12.0, 270, 2.5)), [])          # onshore but light
        self.assertEqual(self.failed((4.0, 14.0, 250, 13.0, 75, 2.5)), ["wind"])     # even offshore, too strong

    def test_offshore_mode(self):
        self.assertEqual(self.failed((4.0, 14.0, 250, 10.0, 75, 2.5), wind="offshore"), [])
        self.assertEqual(self.failed((4.0, 14.0, 250, 10.0, 270, 2.5), wind="offshore"), ["wind"])
        self.assertEqual(self.failed((4.0, 14.0, 250, 2.0, 270, 2.5), wind="offshore"), [])   # glassy counts
        self.assertEqual(self.failed((4.0, 14.0, 250, 26.0, 75, 2.5), wind="offshore"), ["wind"])

    def test_any_wind_mode(self):
        self.assertEqual(self.failed((4.0, 14.0, 250, 30.0, 270, 2.5), wind="any"), [])

    def test_swell_direction_window_and_wraparound(self):
        self.assertEqual(self.failed((4.0, 14.0, 250, 3.0, 75, 2.5), swell_dir_deg=[200, 300]), [])
        self.assertEqual(self.failed((4.0, 14.0, 190, 3.0, 75, 2.5), swell_dir_deg=[200, 300]), ["direction"])
        self.assertEqual(self.failed((4.0, 14.0, 10, 3.0, 75, 2.5), swell_dir_deg=[340, 20]), [])
        self.assertEqual(self.failed((4.0, 14.0, 90, 3.0, 75, 2.5), swell_dir_deg=[340, 20]), ["direction"])

    def test_tide_range(self):
        self.assertEqual(self.failed((4.0, 14.0, 250, 3.0, 75, 5.0), tide_ft=[1, 4]), ["tide"])
        self.assertEqual(self.failed((4.0, 14.0, 250, 3.0, 75, 2.0), tide_ft=[1, 4]), [])

    def test_a_missing_tide_or_wind_never_blocks(self):
        self.assertEqual(self.failed((4.0, 14.0, 250, None, None, None), tide_ft=[1, 4]), [])
        self.assertEqual(self.failed((4.0, 14.0, None, 3.0, 75, 2.5), swell_dir_deg=[200, 300]), [])

    def test_several_failures_are_all_reported(self):
        self.assertEqual(self.failed((9.0, 5.0, 250, 20.0, 270, 2.5)), ["size", "period", "wind"])


class Windows(unittest.TestCase):
    def test_a_run_of_matching_hours(self):
        rows = [row(6, h=1.0), row(7), row(8, score=80), row(9), row(10, h=9.0)]
        w = P.windows(rows, PREFS, CFG)
        self.assertEqual(len(w), 1)
        self.assertEqual((w[0]["start"], w[0]["end"], w[0]["hours"]), (at(7), at(10), 3))
        self.assertEqual(w[0]["peak"]["time"], at(8))

    def test_peak_is_the_best_rated_hour_earliest_on_a_tie(self):
        rows = [row(7, score=75), row(8, score=75), row(9, score=60)]
        self.assertEqual(P.windows(rows, PREFS, CFG)[0]["peak"]["time"], at(7))

    def test_two_windows_split_by_a_bad_hour(self):
        rows = [row(7), row(8, wk=20.0), row(9), row(10)]
        w = P.windows(rows, PREFS, CFG)
        self.assertEqual([(x["start"], x["hours"]) for x in w], [(at(7), 1), (at(9), 2)])

    def test_minimum_hours(self):
        rows = [row(7), row(8, h=1.0), row(9), row(10)]
        self.assertEqual(len(P.windows(rows, PREFS, CFG, min_hours=2)), 1)
        self.assertEqual(P.windows(rows, PREFS, CFG, min_hours=3), [])

    def test_a_gap_in_the_rows_splits_a_run(self):
        w = P.windows([row(7), row(9)], PREFS, CFG)
        self.assertEqual(len(w), 2)

    def test_nothing_matches(self):
        self.assertEqual(P.windows([row(7, h=1.0), row(8, h=1.0)], PREFS, CFG), [])
        self.assertEqual(P.windows([], PREFS, CFG), [])


class Timing(unittest.TestCase):
    def window(self):
        return P.windows([row(7), row(8, score=80), row(9), row(10)], PREFS, CFG)[0]       # 7-11, peak 8

    def test_due_from_an_hour_before_the_peak(self):
        w = self.window()
        self.assertFalse(P.is_due(w, at(6, 59), 60))
        self.assertTrue(P.is_due(w, at(7, 0), 60))
        self.assertTrue(P.is_due(w, at(7, 40), 60))

    def test_still_due_after_the_peak_while_the_window_has_time(self):
        w = self.window()
        self.assertTrue(P.is_due(w, at(9, 30), 60))
        self.assertTrue(P.is_due(w, at(10, 29), 60))

    def test_not_due_when_the_window_is_nearly_over(self):
        w = self.window()
        self.assertFalse(P.is_due(w, at(10, 31), 60))
        self.assertFalse(P.is_due(w, at(11, 0), 60))

    def test_longer_lead_alerts_earlier(self):
        self.assertTrue(P.is_due(self.window(), at(6, 30), 90))

    def test_upcoming_picks_the_due_window(self):
        rows = [row(7), row(8, score=80), row(9), row(10), row(11, h=1.0), row(14), row(15, score=90)]
        self.assertEqual(P.upcoming(profile(), "swamis", CFG, rows, at(7, 10))["peak"]["time"], at(8))
        self.assertIsNone(P.upcoming(profile(), "swamis", CFG, rows, at(5, 0)))
        self.assertEqual(P.upcoming(profile(), "swamis", CFG, rows, at(14, 5))["peak"]["time"], at(15))

    def test_upcoming_respects_minimum_hours(self):
        rows = [row(7), row(8, h=1.0)]
        self.assertIsNotNone(P.upcoming(profile(), "swamis", CFG, rows, at(6, 30)))
        self.assertIsNone(P.upcoming(profile(alerts={"min_hours": 2}), "swamis", CFG, rows, at(6, 30)))

    def test_upcoming_uses_the_break_override(self):
        rows = [row(7, h=7.0), row(8, h=7.0)]
        self.assertIsNone(P.upcoming(profile(), "swamis", CFG, rows, at(6, 30)))
        big = profile(overrides={"swamis": {"height_ft": [6, 10]}})
        self.assertIsNotNone(P.upcoming(big, "swamis", CFG, rows, at(6, 30)))


class QuietHours(unittest.TestCase):
    def test_same_day_range(self):
        self.assertTrue(P.in_quiet_hours(13, 12, 14))
        self.assertFalse(P.in_quiet_hours(14, 12, 14))

    def test_range_wrapping_midnight(self):
        self.assertTrue(P.in_quiet_hours(23, 22, 4))
        self.assertTrue(P.in_quiet_hours(2, 22, 4))
        self.assertFalse(P.in_quiet_hours(4, 22, 4))
        self.assertFalse(P.in_quiet_hours(12, 22, 4))

    def test_unset(self):
        self.assertFalse(P.in_quiet_hours(3, None, None))
        self.assertFalse(P.in_quiet_hours(3, 5, 5))


class State(unittest.TestCase):
    def window(self, hour=8):
        return P.windows([row(hour - 1), row(hour, score=80), row(hour + 1)], PREFS, CFG)[0]

    def test_first_time_sends(self):
        self.assertTrue(P.should_send(None, self.window(), at(7, 5)))

    def test_not_twice_for_the_same_window(self):
        state = {}
        P.record(state, "t1", "swamis", self.window(), at(7, 5))
        self.assertFalse(P.should_send(state["t1"]["swamis"], self.window(), at(8, 5)))

    def test_a_new_day_sends_again(self):
        state = {}
        P.record(state, "t1", "swamis", self.window(), at(7, 5))
        self.assertTrue(P.should_send(state["t1"]["swamis"], self.window(), at(7, 5, day=1)))

    def test_a_peak_that_moves_a_lot_sends_again_a_small_move_does_not(self):
        state = {}
        P.record(state, "t1", "swamis", self.window(8), at(7, 5))
        entry = state["t1"]["swamis"]
        self.assertFalse(P.should_send(entry, self.window(10), at(9, 0)))
        self.assertTrue(P.should_send(entry, self.window(12), at(11, 0)))

    def test_a_damaged_entry_sends(self):
        self.assertTrue(P.should_send({"date": DAY.isoformat(), "peak": "nonsense"}, self.window(), at(7)))

    def test_prune_forgets_deleted_profiles_and_old_days(self):
        state = {
            "gone": {"swamis": {"date": DAY.isoformat(), "peak": "x"}},
            "t1": {"swamis": {"date": DAY.isoformat(), "peak": "x"},
                   "windansea": {"date": (DAY - datetime.timedelta(days=9)).isoformat(), "peak": "x"}},
            "t2": {"swamis": {"date": (DAY - datetime.timedelta(days=9)).isoformat(), "peak": "x"}},
        }
        P.prune(state, {"t1", "t2"}, at(8))
        self.assertEqual(list(state), ["t1"])
        self.assertEqual(list(state["t1"]), ["swamis"])


class Digest(unittest.TestCase):
    """One message for everything due for a person."""
    CFG2 = {"name": "Windansea", "offshore_dir_deg": [40, 110]}

    def item(self, cfg, score, hour=8, **cond):
        rows = [row(hour - 1, score=score - 5), row(hour, score=score, **cond), row(hour + 1, score=score - 5)]
        return cfg, P.windows(rows, PREFS, cfg)[0]

    def test_a_single_break_gets_the_full_message(self):
        item = self.item(CFG, 84.0)
        self.assertEqual(P.digest([item], at(7, 5)), P.message("Swami's", item[1], CFG, at(7, 5)))

    def test_several_breaks_become_one_message_best_first(self):
        a, b = self.item(CFG, 74.0), self.item(self.CFG2, 91.0, hour=9)
        title, body = P.digest([a, b], at(7, 30), site_url="https://example.test/site/")
        self.assertEqual(title, "2 of your breaks are lining up")
        self.assertLess(body.index("1. Windansea"), body.index("2. Swami's"))
        self.assertIn("Epic 9.1/10", body)
        self.assertIn("Good 7.4/10", body)
        self.assertIn("4.0 ft at 14 s", body)
        self.assertIn("https://example.test/site/profile/", body)

    def test_each_line_has_the_peak_time_and_the_window(self):
        _, body = P.digest([self.item(CFG, 80.0), self.item(self.CFG2, 70.0)], at(7, 5))
        self.assertIn("best around 8:00 AM", body)
        self.assertIn("lined up 7 AM to 10 AM", body)

    def test_a_long_list_is_trimmed(self):
        items = [self.item(dict(CFG, name="B%d" % i), 60.0 + i) for i in range(P.MAX_LISTED + 3)]
        title, body = P.digest(items, at(7, 5))
        self.assertEqual(title, "%d of your breaks are lining up" % len(items))
        self.assertIn("+3 more", body)
        self.assertEqual(body.count("ft at"), P.MAX_LISTED)

    def test_title_is_plain_ascii_for_a_header(self):
        title, _ = P.digest([self.item(CFG, 80.0), self.item(self.CFG2, 70.0)], at(7, 5))
        title.encode("ascii")


class WhenPhrase(unittest.TestCase):
    def window(self):
        return P.windows([row(6), row(7), row(8, score=80), row(9), row(10)], PREFS, CFG)[0]       # 6-11, peak 8

    def test_before_the_peak(self):
        self.assertEqual(P.when_phrase(self.window(), at(7, 5)), "best around 8:00 AM (in about 55 minutes), lined up 6 AM to 11 AM")

    def test_around_the_peak(self):
        for now in (at(7, 52), at(8, 0), at(8, 9)):
            self.assertEqual(P.when_phrase(self.window(), now), "peaking now, lined up 6 AM to 11 AM")

    def test_after_the_peak_it_says_so_instead_of_pretending_it_is_now(self):
        self.assertEqual(P.when_phrase(self.window(), at(10, 5)), "on now until 11 AM (best was around 8:00 AM)")

    def test_hours_away(self):
        self.assertIn("in about 3 hours", P.when_phrase(self.window(), at(5, 0)))


class Message(unittest.TestCase):
    def test_title_and_body(self):
        w = P.windows([row(7), row(8, score=84), row(9), row(10)], PREFS, CFG)[0]
        title, body = P.message("Swami's", w, CFG, at(7, 5), site_url="https://example.test/site/")
        self.assertEqual(title, "Swami's: your conditions peak at 8 AM")
        self.assertIn("best around 8:00 AM (in about 55 minutes), lined up 7 AM to 11 AM", body)
        self.assertIn("4.0 ft at 14 s", body)
        self.assertIn("8.4/10", body)
        self.assertIn("https://example.test/site/profile/", body)

    def test_peak_right_now(self):
        w = P.windows([row(8, score=84)], PREFS, CFG)[0]
        _, body = P.message("Swami's", w, CFG, at(8, 4))
        self.assertIn("peaking now", body)

    def test_no_link_without_a_site_url(self):
        w = P.windows([row(8)], PREFS, CFG)[0]
        self.assertNotIn("Edit your", P.message("X", w, CFG, at(7, 30))[1])

    def test_message_is_plain_ascii_safe_for_a_header_title(self):
        w = P.windows([row(8)], PREFS, CFG)[0]
        title, _ = P.message("Swami's", w, CFG, at(7, 30))
        title.encode("ascii")


if __name__ == "__main__":
    unittest.main()
