"""The feedback buttons: the form logic (sitegen/assets/feedback.js, run under Node, skipped without it) and the
markup the site generator makes for them."""
import json
import os
import re
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config
from sitegen import render
from sitegen.build import sitemap

FEEDBACK_JS = os.path.join(ROOT, "sitegen", "assets", "feedback.js")
NODE = shutil.which("node")

RUNNER = """
const F = require(process.argv[1]);
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify({
  built: input.values.map(v => F.buildFeedback(v)),
  can: input.values.map(v => F.canSend(v)),
  keys: input.dates.map(d => F.sentKey('swamis', new Date(d[0], d[1], d[2]))),
  votes: F.VOTES, max: [F.MAX_NOTE, F.MAX_CONTACT],
}));
"""

BREAK = {"kind": "break", "slug": "beacons", "name": "Beacon's", "vote": "better", "shown_rating": "8.4", "shown_label": "Excellent",
         "note": "perfect at 5:45", "contact": ""}


def run(values=(), dates=()):
    out = subprocess.run([NODE, "-e", RUNNER, FEEDBACK_JS], input=json.dumps({"values": list(values), "dates": list(dates)}),
                         capture_output=True, text=True, timeout=60, check=True)
    return json.loads(out.stdout)


@unittest.skipUnless(NODE, "Node is not installed")
class FormLogic(unittest.TestCase):
    def build(self, **over):
        return run([dict(BREAK, **over)])["built"][0]

    def test_a_break_vote_carries_the_rating_that_was_showing(self):
        f = self.build()["feedback"]
        self.assertEqual(f, {"kind": "break", "slug": "beacons", "name": "Beacon's", "vote": "better", "shown_rating": 8.4,
                             "shown_label": "Excellent", "note": "perfect at 5:45"})

    def test_a_vote_alone_or_a_note_alone_is_enough(self):
        self.assertIn("feedback", self.build(note=""))
        self.assertIn("feedback", self.build(vote="", note="sets were far apart"))

    def test_neither_a_vote_nor_a_note_is_not(self):
        self.assertIn("Pick how it compared", self.build(vote="", note="")["errors"][0])

    def test_every_vote_is_accepted_and_nothing_else(self):
        for v in ("better", "right", "worse"):
            self.assertEqual(self.build(vote=v)["feedback"]["vote"], v)
        self.assertIn("errors", self.build(vote="amazing"))

    def test_the_form_must_know_which_break_it_is_for(self):
        self.assertIn("errors", self.build(slug=""))

    def test_a_missing_or_silly_rating_is_left_out_rather_than_sent(self):
        for bad in ("", None, "abc", "11", "-1"):
            self.assertNotIn("shown_rating", self.build(shown_rating=bad)["feedback"], repr(bad))
        self.assertEqual(self.build(shown_rating="7.349")["feedback"]["shown_rating"], 7.3)

    def test_general_feedback_needs_a_note(self):
        both = run([{"kind": "general", "note": "love the map", "contact": "me@example.com"}, {"kind": "general", "note": "  "}])["built"]
        self.assertEqual(both[0]["feedback"], {"kind": "general", "note": "love the map", "contact": "me@example.com"})
        self.assertIn("Write a note", both[1]["errors"][0])

    def test_angle_brackets_are_stripped_and_lengths_capped(self):
        f = self.build(note="<b>hi</b> " + "x" * 600, contact="y" * 200)["feedback"]
        self.assertNotIn("<", f["note"])
        self.assertEqual(len(f["note"]), 500)
        self.assertEqual(len(f["contact"]), 80)

    def test_a_huge_note_is_refused_outright(self):
        self.assertIn("too long", self.build(note="x" * 1200)["errors"][0])

    def test_can_send_matches_whether_the_form_would_build(self):
        r = run([BREAK, dict(BREAK, vote="", note=""), {"kind": "general", "note": ""}, {"kind": "general", "note": "hi"}])
        self.assertEqual(r["can"], [True, False, False, True])

    def test_one_flag_per_break_per_day(self):
        keys = run(dates=[[2026, 9, 20], [2026, 9, 21], [2026, 0, 5]])["keys"]
        self.assertEqual(keys, ["swell-fb-swamis-2026-10-20", "swell-fb-swamis-2026-10-21", "swell-fb-swamis-2026-01-05"])

    def test_the_limits_match_the_service(self):
        r = run()
        self.assertEqual(r["votes"], ["better", "right", "worse"])
        self.assertEqual(r["max"], [500, 80])

    def test_the_script_never_uses_innerhtml(self):
        with open(FEEDBACK_JS) as f:
            self.assertIsNone(re.search(r"innerHTML|outerHTML|document\.write", f.read()))


def payload():
    """A real payload from the site tests' own inputs, with the first break's rating pinned so the test can look for it."""
    from sitegen.build import make_payload
    from tests.test_sitegen import at, make_inputs
    now = at(0, 10)
    p = make_payload(make_inputs(now), now)
    p["spots"][0].update(rating=8.4, label="Excellent")
    return p


class Pages(unittest.TestCase):
    def setUp(self):
        self.p = payload()
        self.spot_html = render.spot_page(self.p["spots"][0], self.p)
        self.page_html = render.feedback_page(self.p)

    def test_a_break_page_has_the_how_was_it_section_with_the_rating_that_was_showing(self):
        html = self.spot_html
        self.assertIn('id="feedback"', html)
        self.assertIn("How was it?", html)
        self.assertIn('data-kind="break"', html)
        self.assertIn('data-slug="%s"' % self.p["spots"][0]["slug"], html)
        self.assertIn('data-rating="8.4"', html)
        self.assertIn('data-label="Excellent"', html)
        self.assertIn('data-api="%s"' % config.PROFILES_API, html)

    def test_all_three_votes_are_there_and_start_unpressed(self):
        for vote in ("better", "right", "worse"):
            self.assertIn('data-vote="%s" aria-pressed="false"' % vote, self.spot_html)

    def test_the_hero_links_down_to_it(self):
        self.assertIn('href="#feedback">Been out? Tell us how it was', self.spot_html)

    def test_the_script_the_form_needs_is_loaded(self):
        self.assertIn("assets/feedback.js", self.spot_html)
        self.assertIn("assets/feedback.js", self.page_html)

    def test_the_hooks_the_script_reads_exist(self):
        for hook in ("data-feedback", "data-fb-form", "data-fb-thanks", "data-fb-send", "data-fb-status", 'name="note"', 'name="contact"'):
            self.assertIn(hook, self.spot_html, hook)
            self.assertIn(hook, self.page_html, hook)

    def test_the_send_button_starts_disabled_and_the_thanks_hidden(self):
        for html in (self.spot_html, self.page_html):
            self.assertRegex(html, r"data-fb-send disabled")
            self.assertRegex(html, r"data-fb-thanks hidden")

    def test_the_general_page_has_no_votes_and_asks_for_a_note(self):
        self.assertNotIn("data-vote=", self.page_html)
        self.assertIn('data-kind="general"', self.page_html)
        self.assertIn("What is missing, confusing or wrong?", self.page_html)
        self.assertIn("<h1>Send feedback</h1>", self.page_html)

    def test_the_form_says_where_it_goes_and_that_the_address_is_not_kept(self):
        for html in (self.spot_html, self.page_html):
            self.assertIn("goes to the person who built the site", html)
            self.assertIn("address is not stored", html)

    def test_every_page_footer_links_to_the_feedback_page(self):
        footer = render._footer(self.p)
        self.assertIn('href="%s/feedback/"' % config.SITE_URL.rstrip("/"), footer)

    def test_the_sitemap_lists_the_page(self):
        self.assertIn("%s/feedback/" % config.SITE_URL.rstrip("/"), sitemap(self.p))

    def test_a_visitor_text_cannot_become_markup_in_the_page(self):
        spot = dict(self.p["spots"][0], name='X"><script>alert(1)</script>')
        html = render.spot_page(spot, self.p)
        self.assertNotIn("<script>alert(1)</script>", html)


if __name__ == "__main__":
    unittest.main()
