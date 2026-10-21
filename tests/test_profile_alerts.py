"""The hourly profile-alert job: reading profiles from the service, deciding who to tell, remembering."""
import datetime
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import profile_alerts as J  # noqa: E402
from sources import notify, profiles as P  # noqa: E402

TZ = datetime.timezone(datetime.timedelta(hours=-7))
CFG = {"slug": "swamis", "name": "Swami's", "offshore_dir_deg": [40, 110]}
CFG2 = {"slug": "windansea", "name": "Windansea", "offshore_dir_deg": [40, 110]}
CFGS = {"swamis": CFG, "windansea": CFG2}


def at(hour, minute=0, day=0):
    d = datetime.date(2026, 10, 20) + datetime.timedelta(days=day)
    return datetime.datetime(d.year, d.month, d.day, hour, minute, tzinfo=TZ)


def good_rows(score=70.0):
    return [{"time": at(h), "cond": (4.0, 14.0, 250, 3.0, 75, 2.5), "score": score + (5 if h == 8 else 0), "tide_state": "rising"}
            for h in range(6, 12)]


def person(topic="swell-aaaa", **over):
    base = {"topic": topic, "breaks": ["swamis"], "prefs": {"height_ft": [3, 6], "period_min_s": 10},
            "overrides": {}, "alerts": {}}
    base.update(over)
    return base


class Fetch(unittest.TestCase):
    def test_pages_are_followed_and_the_key_is_sent(self):
        pages = [{"profiles": [{"topic": "a"}, {"topic": "b"}], "cursor": "c1"}, {"profiles": [{"topic": "c"}], "cursor": None}]
        calls = []

        def fake(url, headers=None, **kw):
            calls.append((url, headers))
            return pages[len(calls) - 1]

        with mock.patch.object(J.http, "get_json", fake):
            got = J.fetch_profiles("https://api.example.test/", "KEY")
        self.assertEqual([p["topic"] for p in got], ["a", "b", "c"])
        self.assertEqual(calls[0][0], "https://api.example.test/api/admin/profiles")
        self.assertEqual(calls[1][0], "https://api.example.test/api/admin/profiles?cursor=c1")
        self.assertTrue(all(h == {"Authorization": "Bearer KEY"} for _, h in calls))

    def test_no_profiles(self):
        with mock.patch.object(J.http, "get_json", lambda *a, **k: {"profiles": [], "cursor": None}):
            self.assertEqual(J.fetch_profiles("https://x", "k"), [])


class Plan(unittest.TestCase):
    def rows_for(self, cfg):
        return good_rows()

    def test_alerts_an_hour_before_the_peak(self):
        todo = J.plan([person()], CFGS, self.rows_for, {}, at(7, 5))
        self.assertEqual([(t, [s for s, _, _ in items]) for t, items in todo], [("swell-aaaa", ["swamis"])])
        self.assertEqual(todo[0][1][0][1]["peak"]["time"], at(8))

    def test_not_before_the_lead_time(self):
        self.assertEqual(J.plan([person()], CFGS, self.rows_for, {}, at(6, 5)), [])

    def test_not_twice(self):
        state = {}
        first = J.plan([person()], CFGS, self.rows_for, state, at(7, 5))
        P.record(state, "swell-aaaa", "swamis", first[0][1][0][1], at(7, 5))
        self.assertEqual(J.plan([person()], CFGS, self.rows_for, state, at(8, 5)), [])

    def test_quiet_hours_hold_it_back(self):
        quiet = person(alerts={"quiet_from": 6, "quiet_to": 9})
        self.assertEqual(J.plan([quiet], CFGS, self.rows_for, {}, at(7, 5)), [])
        self.assertEqual(len(J.plan([quiet], CFGS, self.rows_for, {}, at(9, 5))), 1)       # sent once it ends

    def test_unknown_breaks_and_missing_topics_are_ignored(self):
        self.assertEqual(J.plan([person(breaks=["nowhere"])], CFGS, self.rows_for, {}, at(7, 5)), [])
        self.assertEqual(J.plan([person(topic=None)], CFGS, self.rows_for, {}, at(7, 5)), [])

    def test_each_person_is_judged_on_their_own_conditions(self):
        picky = person(topic="swell-bbbb", prefs={"height_ft": [8, 12], "period_min_s": 10})
        todo = J.plan([person(), picky], CFGS, self.rows_for, {}, at(7, 5))
        self.assertEqual([t for t, _ in todo], ["swell-aaaa"])

    def test_every_matching_break_goes_in_one_entry_per_person_best_rated_first(self):
        many = {"b%d" % i: {"slug": "b%d" % i, "name": "B%d" % i, "offshore_dir_deg": [40, 110]} for i in range(5)}
        rows = {slug: good_rows(score=50.0 + i * 5) for i, slug in enumerate(many)}
        todo = J.plan([person(breaks=list(many))], many, lambda cfg: rows[cfg["slug"]], {}, at(7, 5))
        self.assertEqual(len(todo), 1)                                    # one message, not five
        self.assertEqual([s for s, _, _ in todo[0][1]], ["b4", "b3", "b2", "b1", "b0"])

    def test_breaks_that_do_not_match_this_person_are_left_out(self):
        rows = {"swamis": good_rows(), "windansea": [dict(r, cond=(9.0, 14.0, 250, 3.0, 75, 2.5)) for r in good_rows()]}
        todo = J.plan([person(breaks=["swamis", "windansea"])], CFGS, lambda cfg: rows[cfg["slug"]], {}, at(7, 5))
        self.assertEqual([s for s, _, _ in todo[0][1]], ["swamis"])

    def test_a_break_already_alerted_is_not_repeated_but_a_new_one_still_goes(self):
        state = {}
        first = J.plan([person(breaks=["swamis"])], CFGS, self.rows_for, state, at(7, 5))
        P.record(state, "swell-aaaa", "swamis", first[0][1][0][1], at(7, 5))
        both = J.plan([person(breaks=["swamis", "windansea"])], CFGS, self.rows_for, state, at(7, 35))
        self.assertEqual([s for s, _, _ in both[0][1]], ["windansea"])

    def test_two_people_get_their_own_messages(self):
        todo = J.plan([person(), person(topic="swell-bbbb", breaks=["windansea"])], CFGS, self.rows_for, {}, at(7, 5))
        self.assertEqual([t for t, _ in todo], ["swell-aaaa", "swell-bbbb"])


class State(unittest.TestCase):
    def test_round_trip_and_damage(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.json")
            self.assertEqual(J.load_state(path), {})
            J.save_state(path, {"t": {"swamis": {"date": "2026-10-20", "peak": "x"}}})
            self.assertEqual(J.load_state(path)["t"]["swamis"]["date"], "2026-10-20")
            with open(path, "w") as f:
                f.write("{broken")
            self.assertEqual(J.load_state(path), {})
            with open(path, "w") as f:
                f.write("[1, 2]")
            self.assertEqual(J.load_state(path), {})


class Run(unittest.TestCase):
    def test_without_a_key_it_does_nothing_and_succeeds(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PROFILES_ADMIN_KEY", None)
            args = J.argparse.Namespace(api=None, from_file=None, state="/nonexistent/state", now=None, dry_run=False)
            self.assertEqual(J.run(args), 0)

    def test_a_service_failure_fails_the_run_visibly(self):
        args = J.argparse.Namespace(api="https://api.example.test", from_file=None, state="/nonexistent/state", now=None, dry_run=False)
        with mock.patch.dict(os.environ, {"PROFILES_ADMIN_KEY": "k"}), \
                mock.patch.object(J, "fetch_profiles", side_effect=RuntimeError("down")):
            self.assertEqual(J.run(args), 1)

    def test_no_profiles_means_no_network_and_a_clean_state(self):
        with tempfile.TemporaryDirectory() as d:
            state = os.path.join(d, "s.json")
            J.save_state(state, {"gone": {"swamis": {"date": "2026-10-20", "peak": "x"}}})
            pf = os.path.join(d, "p.json")
            with open(pf, "w") as f:
                json.dump({"profiles": []}, f)
            args = J.argparse.Namespace(api=None, from_file=pf, state=state, now="2026-10-20T07:05", dry_run=False)
            with mock.patch.object(J.check, "Context", side_effect=AssertionError("must not fetch")):
                self.assertEqual(J.run(args), 0)
            self.assertEqual(J.load_state(state), {})              # the deleted profile was forgotten


class SendToTopic(unittest.TestCase):
    def test_goes_only_to_the_persons_topic(self):
        posted = []
        with mock.patch.object(notify.http, "post", lambda url, body="", headers=None, **k: posted.append((url, headers))), \
                mock.patch.dict(os.environ, {"NTFY_TOPIC": "owners-private", "SURF_PUBLISH_PUBLIC": "1"}):
            self.assertTrue(notify.send_to_topic("swell-abc", "Title", "Body", click="https://x/y"))
        self.assertEqual(len(posted), 1)
        self.assertTrue(posted[0][0].endswith("/swell-abc"))
        self.assertEqual(posted[0][1]["Click"], "https://x/y")

    def test_a_failed_post_is_reported_not_raised(self):
        with mock.patch.object(notify.http, "post", side_effect=OSError("boom")):
            self.assertFalse(notify.send_to_topic("swell-abc", "T", "B"))


if __name__ == "__main__":
    unittest.main()
