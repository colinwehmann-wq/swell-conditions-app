"""Forwarding feedback from the site to the owner's phone: what the notification says, never twice, never in the logs."""
import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import feedback_forward as F  # noqa: E402
from sources import notify  # noqa: E402

BREAK = {"t": "2026-10-20T14:00:00.000Z", "kind": "break", "slug": "beacons", "name": "Beacon's", "vote": "better",
         "shown_rating": 8.4, "shown_label": "Excellent", "note": "perfect at 5:45", "contact": "friend@example.com"}
GENERAL = {"t": "2026-10-20T14:05:00.000Z", "kind": "general", "note": "love the map"}


def item(i, **over):
    d = {"t": "2026-10-20T14:%02d:00.000Z" % i, "kind": "general", "note": "note %d" % i}
    d.update(over)
    return d


class Describe(unittest.TestCase):
    def test_a_break_vote_says_which_break_how_it_compared_and_what_the_site_showed(self):
        line = F.describe(BREAK)
        self.assertIn("Beacon's: better than rated", line)
        self.assertIn("it showed 8.4 Excellent", line)
        self.assertIn('"perfect at 5:45"', line)
        self.assertIn("[reply: friend@example.com]", line)

    def test_general_feedback(self):
        self.assertEqual(F.describe(GENERAL), '- General - "love the map"')

    def test_a_vote_with_no_note(self):
        line = F.describe({"kind": "break", "slug": "swamis", "vote": "right", "shown_rating": 6.0})
        self.assertEqual(line, "- swamis: about right (it showed 6.0)")

    def test_a_note_with_no_vote(self):
        self.assertIn("a note", F.describe({"kind": "break", "slug": "swamis", "name": "Swami's", "note": "sets far apart"}))

    def test_long_notes_are_trimmed_and_newlines_flattened(self):
        line = F.describe({"kind": "general", "note": "word " * 100})
        self.assertLessEqual(len(line), F.NOTE_CHARS + 20)
        self.assertTrue(line.rstrip('"').endswith("…"))
        self.assertNotIn("\n", F.describe({"kind": "general", "note": "a\nb"}))


class Format(unittest.TestCase):
    def test_title_counts_and_body_lists(self):
        title, body = F.format_items([BREAK, GENERAL])
        self.assertEqual(title, "Swell feedback: 2 new")
        self.assertEqual(len(body.splitlines()), 2)

    def test_a_long_batch_is_summarised(self):
        title, body = F.format_items([item(i) for i in range(F.MAX_LISTED + 3)])
        self.assertEqual(title, "Swell feedback: %d new" % (F.MAX_LISTED + 3))
        self.assertTrue(body.endswith("+3 more"))
        self.assertEqual(len(body.splitlines()), F.MAX_LISTED + 1)

    def test_the_title_is_plain_ascii_for_a_header(self):
        F.format_items([BREAK])[0].encode("ascii")


class Collect(unittest.TestCase):
    def test_pages_are_followed_until_a_short_one(self):
        pages = [{"items": [item(i) for i in range(F.PAGE)], "last": "L1"}, {"items": [item(99)], "last": "L2"}]
        seen = []

        def fetch(api, key, after):
            seen.append(after)
            return pages[len(seen) - 1]

        items, last = F.collect("https://x", "k", "", fetch)
        self.assertEqual(len(items), F.PAGE + 1)
        self.assertEqual(last, "L2")
        self.assertEqual(seen, ["", "L1"])

    def test_nothing_new_leaves_the_marker_alone(self):
        items, last = F.collect("https://x", "k", "2026-10-20T14:00:00.000Z", lambda *a: {"items": [], "last": "2026-10-20T14:00:00.000Z"})
        self.assertEqual((items, last), ([], "2026-10-20T14:00:00.000Z"))

    def test_it_never_loops_forever(self):
        calls = []
        full = {"items": [item(i) for i in range(F.PAGE)], "last": "L"}
        F.collect("https://x", "k", "", lambda *a: calls.append(1) or full)
        self.assertEqual(len(calls), F.MAX_PAGES)


class Run(unittest.TestCase):
    def args(self, state, dry=False):
        return F.argparse.Namespace(api="https://api.example.test", state=state, dry_run=dry)

    def env(self, **extra):
        env = {"PROFILES_ADMIN_KEY": "k", "NTFY_TOPIC": "owner-private"}
        env.update(extra)
        return mock.patch.dict(os.environ, env)

    def test_it_sends_one_notification_and_remembers_the_newest(self):
        sent = []
        with tempfile.TemporaryDirectory() as d, self.env():
            state = os.path.join(d, "s.json")
            rc = F.run(self.args(state), fetch=lambda *a: {"items": [BREAK, GENERAL], "last": GENERAL["t"]},
                       send=lambda title, body, click=None: sent.append((title, body)) or True)
            self.assertEqual(rc, 0)
            self.assertEqual(len(sent), 1)
            self.assertEqual(F.load_state(state), {"after": GENERAL["t"]})

    def test_a_second_run_asks_only_for_what_is_newer(self):
        asked = []
        with tempfile.TemporaryDirectory() as d, self.env():
            state = os.path.join(d, "s.json")
            F.save_state(state, {"after": GENERAL["t"]})
            F.run(self.args(state), fetch=lambda api, key, after: asked.append(after) or {"items": [], "last": after}, send=lambda *a, **k: True)
            self.assertEqual(asked, [GENERAL["t"]])

    def test_nothing_new_sends_nothing(self):
        sent = []
        with tempfile.TemporaryDirectory() as d, self.env():
            F.run(self.args(os.path.join(d, "s.json")), fetch=lambda *a: {"items": [], "last": None}, send=lambda *a, **k: sent.append(1) or True)
        self.assertEqual(sent, [])

    def test_a_failed_send_is_not_remembered_so_it_is_tried_again(self):
        with tempfile.TemporaryDirectory() as d, self.env():
            state = os.path.join(d, "s.json")
            F.run(self.args(state), fetch=lambda *a: {"items": [BREAK], "last": BREAK["t"]}, send=lambda *a, **k: False)
            self.assertEqual(F.load_state(state), {})

    def test_without_a_phone_topic_it_waits_instead_of_losing_feedback(self):
        sent = []
        with tempfile.TemporaryDirectory() as d, self.env(NTFY_TOPIC=""):
            state = os.path.join(d, "s.json")
            F.run(self.args(state), fetch=lambda *a: {"items": [BREAK], "last": BREAK["t"]}, send=lambda *a, **k: sent.append(1) or True)
            self.assertEqual((sent, F.load_state(state)), ([], {}))

    def test_without_the_key_it_does_nothing(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PROFILES_ADMIN_KEY", None)
            self.assertEqual(F.run(self.args("/nonexistent/s.json")), 0)

    def test_a_service_failure_fails_the_run_visibly(self):
        def boom(*a):
            raise RuntimeError("down")
        with self.env(), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(F.run(self.args("/nonexistent/s.json"), fetch=boom), 1)

    def test_dry_run_counts_but_sends_and_remembers_nothing(self):
        sent = []
        with tempfile.TemporaryDirectory() as d, self.env():
            state = os.path.join(d, "s.json")
            F.run(self.args(state, dry=True), fetch=lambda *a: {"items": [BREAK], "last": BREAK["t"]}, send=lambda *a, **k: sent.append(1) or True)
            self.assertEqual((sent, F.load_state(state)), ([], {}))

    def test_the_log_never_shows_what_anyone_wrote_or_their_email(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as d, self.env(), contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            F.run(self.args(os.path.join(d, "s.json")), fetch=lambda *a: {"items": [BREAK, GENERAL], "last": GENERAL["t"]},
                  send=lambda *a, **k: True)
        log = out.getvalue()
        for secret in ("perfect at 5:45", "friend@example.com", "love the map"):
            self.assertNotIn(secret, log)
        self.assertIn("2 new feedback items", log)


class QuietSend(unittest.TestCase):
    def test_it_goes_only_to_the_owners_private_topic(self):
        posted = []
        with mock.patch.object(notify.http, "post", lambda url, body="", headers=None, **k: posted.append((url, body, headers))), \
                mock.patch.dict(os.environ, {"NTFY_TOPIC": "owner-private", "SURF_PUBLISH_PUBLIC": "1"}):
            self.assertTrue(notify.send_private_quiet("T", "B", click="https://x"))
        self.assertEqual(len(posted), 1)
        self.assertTrue(posted[0][0].endswith("/owner-private"))
        self.assertEqual(posted[0][2]["Click"], "https://x")

    def test_it_never_prints_the_body(self):
        out = io.StringIO()
        with mock.patch.object(notify.http, "post", lambda *a, **k: None), mock.patch.dict(os.environ, {"NTFY_TOPIC": "t"}), contextlib.redirect_stdout(out):
            notify.send_private_quiet("Title here", "a private body")
        self.assertIn("Title here", out.getvalue())
        self.assertNotIn("a private body", out.getvalue())

    def test_no_topic_means_no_send(self):
        with mock.patch.dict(os.environ, {"NTFY_TOPIC": ""}):
            self.assertFalse(notify.send_private_quiet("T", "B"))

    def test_a_failure_is_reported_not_raised(self):
        with mock.patch.object(notify.http, "post", side_effect=OSError("boom")), mock.patch.dict(os.environ, {"NTFY_TOPIC": "t"}), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(notify.send_private_quiet("T", "B"))

    def test_personal_alerts_log_the_title_but_not_the_conditions(self):
        out = io.StringIO()
        with mock.patch.object(notify.http, "post", lambda *a, **k: None), contextlib.redirect_stdout(out):
            notify.send_to_topic("swell-abcd1234", "Swami's: your conditions peak at 8 AM", "4.2 ft at 15 s secret body")
        self.assertIn("your conditions peak at 8 AM", out.getvalue())
        self.assertNotIn("secret body", out.getvalue())


if __name__ == "__main__":
    unittest.main()
