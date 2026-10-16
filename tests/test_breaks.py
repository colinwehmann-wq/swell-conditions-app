"""The expanded roster on the site: the home page shows the county's best five, the directory lists
every break, and breaks without a photo still look right."""
import json
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import sitegen
from sitegen import media, render
from sitegen.build import PEAKS_PER_DAY
from tests.test_sitegen import at, make_inputs

ALL = tuple(range(len(config.SPOTS)))
NOW = at(0, 10)


def payload_for_all():
    return sitegen.make_payload(make_inputs(NOW, spots=ALL), NOW)


class Top(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = payload_for_all()
        cls.index = render.index_page(cls.payload)

    def test_the_payload_covers_every_break(self):
        self.assertEqual(len(self.payload["spots"]), len(config.SPOTS))
        self.assertEqual(len(self.payload["breaks"]), len(config.SPOTS))

    def test_top_is_the_best_five_of_the_whole_county(self):
        p = self.payload
        self.assertEqual(len(p["top"]), config.HOME_COUNT)
        self.assertEqual(p["top"], p["ranking"][:config.HOME_COUNT])
        by = {s["slug"]: s for s in p["spots"]}
        worst_top = min(by[s]["rating"] for s in p["top"])
        best_rest = max(s["rating"] for s in p["spots"] if s["slug"] not in p["top"])
        self.assertGreaterEqual(worst_top, best_rest)

    def test_the_home_page_lists_only_those_five_in_rows_and_in_the_week(self):
        rows = re.findall(r'<article class="row">.*?</article>', self.index, re.S)
        self.assertEqual(len(rows), config.HOME_COUNT)
        week = self.index.split('id="week"')[1].split('id="boards"')[0]
        self.assertEqual(week.count('<th scope="row">'), config.HOME_COUNT)
        outside = [s for s in self.payload["spots"] if s["slug"] not in self.payload["top"]]
        for s in outside[:5]:
            self.assertNotIn('href="spots/%s/"' % s["slug"], "".join(rows) + week)

    def test_the_home_page_says_how_many_it_is_choosing_from(self):
        n = len(config.SPOTS)
        self.assertIn("out of the %d we track" % n, self.index)
        self.assertIn("See all %d breaks" % n, self.index)

    def test_the_search_box_is_hidden_until_script_runs_and_the_directory_link_always_works(self):
        self.assertIn('<form class="finder" role="search" data-finder hidden>', self.index)
        self.assertIn('<a href="breaks/">Browse all %d breaks' % len(config.SPOTS), self.index)

    def test_the_search_data_is_embedded_and_round_trips(self):
        raw = re.search(r'id="breaks-data">(.*?)</script>', self.index, re.S).group(1)
        self.assertEqual(json.loads(raw), self.payload["breaks"])

    def test_both_scripts_load_before_site_js(self):
        for s in ("assets/peaks.js", "assets/search.js"):
            self.assertLess(self.index.index(s), self.index.index("assets/site.js"))

    def test_the_headline_considers_the_whole_county_not_only_the_top_five(self):
        h = self.payload["headline"]
        self.assertIn(h["slug"], {s["slug"] for s in self.payload["spots"]})

    def test_the_alerts_section_no_longer_lists_every_break(self):
        alerts = self.index.split('id="alerts"')[1].split('id="how"')[0]
        self.assertEqual(alerts.count("Open in ntfy app"), 0)
        self.assertIn("Open digest in ntfy", alerts)
        self.assertIn('<a href="breaks/">find yours</a>', alerts)


class Privacy(unittest.TestCase):
    def test_nothing_marks_which_breaks_are_the_owners(self):
        p = payload_for_all()
        for s in p["spots"]:
            self.assertNotIn("mine", s)
        self.assertNotIn('"mine"', json.dumps(p))

    def test_peaks_are_capped_per_day_so_the_page_stays_small(self):
        p = payload_for_all()
        per_day = {}
        for peak in p["peaks"]:
            per_day[peak["date"]] = per_day.get(peak["date"], 0) + 1
        self.assertTrue(per_day)
        self.assertLessEqual(max(per_day.values()), PEAKS_PER_DAY)


class Directory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = payload_for_all()
        cls.page = render.breaks_page(cls.payload)

    def test_lists_every_break_with_a_link_to_its_page(self):
        for s in self.payload["spots"]:
            self.assertIn('href="../spots/%s/"' % s["slug"], self.page)
        self.assertEqual(self.page.count('data-break '), len(config.SPOTS))

    def test_runs_north_to_south(self):
        order = [b["slug"] for b in self.payload["breaks"]]
        lats = {s["slug"]: s["lat"] for s in self.payload["spots"]}
        self.assertEqual([lats[s] for s in order], sorted((lats[s] for s in order), reverse=True))
        positions = [self.page.index('href="../spots/%s/"' % s) for s in order]
        self.assertEqual(positions, sorted(positions))

    def test_each_area_appears_once_as_a_single_group(self):
        heads = re.findall(r'<h2 class="dir-h">(.*?)</h2>', self.page)
        self.assertEqual(len(heads), len(set(heads)))
        self.assertEqual(set(heads), {s["area"] for s in self.payload["spots"]})

    def test_rows_carry_what_the_filter_matches_on(self):
        self.assertRegex(self.page, r'data-name="Swami&#x27;s" data-area="Encinitas" data-aliases="[^"]*swamis')

    def test_every_break_shows_a_rating_chip_with_icon_number_and_label(self):
        items = re.findall(r'<li class="dir-item".*?</li>', self.page, re.S)
        self.assertEqual(len(items), len(config.SPOTS))
        for li in items:
            for part in ('class="chip-ico"', 'class="chip-num"', 'class="chip-lbl"'):
                self.assertIn(part, li)

    def test_has_the_search_box_the_empty_message_and_the_tuning_note(self):
        self.assertIn("data-finder hidden", self.page)
        self.assertIn("data-empty hidden", self.page)
        self.assertIn("starting points", self.page)

    def test_loads_the_search_script_but_not_the_headline_one(self):
        self.assertIn("assets/search.js", self.page)
        self.assertNotIn("peaks.js", self.page)
        self.assertIn('href="../assets/style.css"', self.page)

    def test_the_header_links_to_it_from_every_page(self):
        self.assertIn('href="./breaks/"', render.index_page(self.payload))
        self.assertIn('href="../../breaks/"', render.spot_page(self.payload["spots"][0], self.payload))

    def test_a_break_name_cannot_inject_markup(self):
        evil = '"><script>alert(1)</script>'
        p = sitegen.make_payload(make_inputs(NOW, spots=ALL, first_name=evil), NOW)
        for page in (render.breaks_page(p), render.index_page(p)):
            self.assertNotIn(evil, page)


class Photos(unittest.TestCase):
    """Bird Rock and Buccaneer had no free-licensed photo to be found; anything without one must
    still look finished. A slug that can never have a photo keeps these tests true if that changes."""
    NONE = "a-break-that-has-no-photo"

    def test_the_row_gets_a_quiet_tile_instead_of_a_gap(self):
        tile = render._thumb(self.NONE, "")
        self.assertIn("row-photo row-photo-plain", tile)
        self.assertNotIn("<img", tile)
        self.assertIn('href="spots/%s/"' % self.NONE, tile)

    def test_a_photo_break_gets_its_small_tile_not_the_full_photo(self):
        tile = render._thumb("windansea", "")
        self.assertIn('src="assets/img/windansea-sm.jpg"', tile)
        self.assertNotIn('windansea.jpg"', tile)
        self.assertIn('loading="lazy"', tile)

    def test_every_new_break_with_a_photo_uses_it_on_its_page_with_alt_text_and_a_credit(self):
        p = payload_for_all()
        for spot in p["spots"]:
            photo = media.photo(spot["slug"])
            if not photo:
                continue
            page = render.spot_page(spot, p)
            hero = page.split("</section>")[0]
            self.assertIn('src="../../assets/img/%s"' % photo["file"], hero, spot["slug"])
            self.assertIn('alt="%s"' % render.esc(photo["alt"]), hero, spot["slug"])
            self.assertIn(photo["author"], hero, spot["slug"])
            self.assertIn(render.esc(photo["source"]), hero, spot["slug"])

    def test_the_spot_page_hero_falls_back_to_a_gradient_and_keeps_the_dark_styling(self):
        p = payload_for_all()
        spot = dict(next(s for s in p["spots"] if s["slug"] == "swamis"), slug=self.NONE)
        page = render.spot_page(spot, p)
        self.assertIn("hero-bg hero-bg-plain", page)
        self.assertIn('class="spot-hero has-photo"', page)
        self.assertNotIn('class="photo-credit"', page.split("</section>")[0])

    def test_the_footer_credits_every_photo_on_the_page(self):
        p = payload_for_all()
        footer = render.index_page(p).split('class="foot-credits"')[1]
        for spot in p["spots"]:
            photo = media.photo(spot["slug"])
            if photo:
                self.assertIn(render.esc(photo["source"]), footer, spot["slug"])
                self.assertIn(photo["licence"][0], footer, spot["slug"])


class Build(unittest.TestCase):
    def test_writes_the_directory_and_a_page_for_every_break(self):
        with tempfile.TemporaryDirectory() as out:
            sitegen.build(make_inputs(NOW, spots=ALL), NOW, out)
            self.assertTrue(os.path.exists(os.path.join(out, "breaks", "index.html")))
            self.assertTrue(os.path.exists(os.path.join(out, "assets", "search.js")))
            for cfg in config.SPOTS:
                self.assertTrue(os.path.exists(os.path.join(out, "spots", cfg["slug"], "index.html")), cfg["slug"])
            with open(os.path.join(out, "data", "latest.json"), encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(len(data["spots"]), len(config.SPOTS))
            self.assertEqual(len(data["top"]), config.HOME_COUNT)


if __name__ == "__main__":
    unittest.main()
