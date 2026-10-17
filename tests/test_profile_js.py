"""The profile page: its form logic (sitegen/assets/profile.js, run under Node, skipped without it) and
the page the site generator makes for it."""
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

PROFILE_JS = os.path.join(ROOT, "sitegen", "assets", "profile.js")
NODE = shutil.which("node")

RUNNER = """
const P = require(process.argv[1]);
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = {
  built: input.values.map(v => P.buildProfile(v)),
  valuesFromProfile: input.profiles.map(p => P.valuesFromProfile(p)),
  links: P.subscribeLinks('swell-abc'),
  ids: input.ids.map(i => P.validId(i)),
  nearest: input.degs.map(d => P.nearestDirection(d)),
  defaults: P.DEFAULTS,
  directions: P.DIRECTIONS.length,
};
process.stdout.write(JSON.stringify(out));
"""

GOOD = {"breaks": ["swamis"], "height_min": "3", "height_max": "6", "period_min": "10", "wind": "offshore", "wind_max": "12",
        "dir_from": "", "dir_to": "", "tide_min": "", "tide_max": "", "lead_min": "60", "min_hours": "1",
        "quiet_on": False, "quiet_from": "22", "quiet_to": "4"}


def run(values=(), profiles=(), ids=(), degs=()):
    out = subprocess.run([NODE, "-e", RUNNER, PROFILE_JS],
                         input=json.dumps({"values": list(values), "profiles": list(profiles), "ids": list(ids), "degs": list(degs)}),
                         capture_output=True, text=True, timeout=60, check=True)
    return json.loads(out.stdout)


@unittest.skipUnless(NODE, "Node is not installed")
class FormLogic(unittest.TestCase):
    def build(self, **over):
        return run([dict(GOOD, **over)])["built"][0]

    def test_a_good_form_becomes_a_profile(self):
        p = self.build()["profile"]
        self.assertEqual(p["breaks"], ["swamis"])
        self.assertEqual(p["prefs"], {"height_ft": [3, 6], "period_min_s": 10, "wind": "offshore", "wind_max_kn": 12,
                                      "swell_dir_deg": None, "tide_ft": None})
        self.assertEqual(p["alerts"], {"lead_min": 60, "min_hours": 1, "quiet_from": None, "quiet_to": None})

    def test_no_break_picked(self):
        self.assertIn("Pick at least one break.", self.build(breaks=[])["errors"])

    def test_height_problems(self):
        self.assertTrue(any("bigger than the biggest" in e for e in self.build(height_min="9", height_max="3")["errors"]))
        self.assertTrue(any("smallest and biggest" in e for e in self.build(height_min="")["errors"]))
        self.assertTrue(any("0 and 30" in e for e in self.build(height_max="40")["errors"]))

    def test_period_and_wind_limits(self):
        self.assertTrue(any("period" in e for e in self.build(period_min="40")["errors"]))
        self.assertTrue(any("wind speed" in e for e in self.build(wind="light", wind_max="99")["errors"]))

    def test_wind_speed_is_ignored_when_wind_does_not_matter(self):
        p = self.build(wind="any", wind_max="")["profile"]
        self.assertEqual(p["prefs"]["wind"], "any")
        self.assertEqual(p["prefs"]["wind_max_kn"], 12)

    def test_direction_needs_both_ends_or_neither(self):
        self.assertTrue(any("both ends" in e for e in self.build(dir_from="202.5", dir_to="")["errors"]))
        self.assertEqual(self.build(dir_from="202.5", dir_to="292.5")["profile"]["prefs"]["swell_dir_deg"], [202.5, 292.5])

    def test_a_swell_window_may_wrap_past_north(self):
        self.assertEqual(self.build(dir_from="337.5", dir_to="22.5")["profile"]["prefs"]["swell_dir_deg"], [337.5, 22.5])

    def test_tide_needs_both_ends_or_neither_and_in_order(self):
        self.assertTrue(any("lowest and a highest" in e for e in self.build(tide_min="1")["errors"]))
        self.assertTrue(any("higher than" in e for e in self.build(tide_min="4", tide_max="1")["errors"]))
        self.assertEqual(self.build(tide_min="1", tide_max="4")["profile"]["prefs"]["tide_ft"], [1, 4])
        self.assertEqual(self.build(tide_min="-0.5", tide_max="2")["profile"]["prefs"]["tide_ft"], [-0.5, 2])

    def test_quiet_hours(self):
        a = self.build(quiet_on=True, quiet_from="22", quiet_to="4")["profile"]["alerts"]
        self.assertEqual((a["quiet_from"], a["quiet_to"]), (22, 4))
        self.assertTrue(any("Quiet hours" in e for e in self.build(quiet_on=True, quiet_from="5", quiet_to="5")["errors"]))
        # unticked: the hours in the boxes are not sent
        self.assertIsNone(self.build(quiet_on=False, quiet_from="22", quiet_to="4")["profile"]["alerts"]["quiet_from"])

    def test_lead_and_minimum_hours(self):
        a = self.build(lead_min="90", min_hours="2")["profile"]["alerts"]
        self.assertEqual((a["lead_min"], a["min_hours"]), (90, 2))

    def test_the_form_and_a_stored_profile_round_trip(self):
        built = self.build(breaks=["swamis", "windansea"], dir_from="202.5", dir_to="292.5", tide_min="1", tide_max="4",
                           quiet_on=True, lead_min="120", min_hours="3")["profile"]
        values = run(profiles=[built])["valuesFromProfile"][0]
        self.assertEqual(values["breaks"], ["swamis", "windansea"])
        self.assertEqual((values["dir_from"], values["dir_to"]), ("202.5", "292.5"))
        self.assertEqual((values["tide_min"], values["tide_max"]), ("1", "4"))
        self.assertEqual((values["lead_min"], values["min_hours"], values["quiet_on"]), ("120", "3", True))
        self.assertEqual(run([values])["built"][0]["profile"], built)

    def test_no_profile_gives_the_defaults(self):
        got = run(profiles=[None])["valuesFromProfile"][0]
        self.assertEqual(got, run()["defaults"])
        self.assertEqual(got["breaks"], [])
        self.assertEqual(got["wind"], "light")

    def test_nearest_compass_point_and_wraparound(self):
        self.assertEqual(run(degs=[200, 359, 1, 250])["nearest"], ["202.5", "0", "0", "247.5"])

    def test_subscribe_links(self):
        links = run()["links"]
        self.assertEqual(links["app"], "ntfy://ntfy.sh/swell-abc")
        self.assertEqual(links["web"], "https://ntfy.sh/swell-abc")

    def test_ids_are_checked_before_they_reach_the_server(self):
        got = run(ids=["22Tz2frOYx2WfOC1nmLZkQ", "short", "../../etc/passwd", None, "A" * 23])["ids"]
        self.assertEqual(got, [True, False, False, False, False])

    def test_sixteen_compass_points(self):
        self.assertEqual(run()["directions"], 16)


def page():
    breaks = [{"slug": s["slug"], "name": s["name"], "area": s["area"], "aliases": []} for s in config.SPOTS]
    return render.profile_page({"breaks": breaks, "spots": [], "site_url": config.SITE_URL, "repo_url": "https://example.test/repo",
                                "profiles_api": config.PROFILES_API, "sources": {"waves": "w", "tides": "t", "forecast": "f"}})


class ProfilePage(unittest.TestCase):
    def test_every_break_can_be_picked(self):
        html = page()
        for s in config.SPOTS:
            self.assertIn('name="break" value="%s"' % s["slug"], html)

    def test_it_knows_where_the_service_is(self):
        self.assertIn('data-api="%s"' % config.PROFILES_API, page())

    def test_the_form_fields_the_script_reads_exist(self):
        html = page()
        for name in ("height_min", "height_max", "period_min", "wind", "wind_max", "dir_from", "dir_to", "tide_min", "tide_max",
                     "lead_min", "min_hours", "quiet_on", "quiet_from", "quiet_to"):
            self.assertIn('name="%s"' % name, html, name)
        for hook in ("data-pf-save", "data-pf-delete", "data-pf-status", "data-pf-errors", "data-pf-saved", "data-pf-link",
                     "data-pf-topic", "data-pf-app", "data-pf-web", "data-pf-copy-link", "data-pf-copy-topic", "data-pf-test"):
            self.assertIn(hook, html, hook)

    def test_it_loads_its_script_and_is_in_the_nav(self):
        html = page()
        self.assertIn('assets/profile.js', html)
        self.assertIn('href="../profile/"', html)             # the header link, from a page one level down

    def test_direction_options_cover_the_compass(self):
        html = page()
        self.assertIn('<option value="">any direction</option>', html)
        for deg in ("0", "202.5", "292.5", "337.5"):
            self.assertIn('<option value="%s">' % deg, html)

    def test_quiet_hours_default_to_night(self):
        html = page()
        self.assertRegex(html, r'name="quiet_from">.*<option value="22" selected>10 PM</option>')
        self.assertRegex(html, r'name="quiet_to">.*<option value="4" selected>4 AM</option>')

    def test_the_script_never_uses_innerhtml(self):
        with open(PROFILE_JS) as f:
            self.assertIsNone(re.search(r"innerHTML|outerHTML|document\.write", f.read()))


if __name__ == "__main__":
    unittest.main()
