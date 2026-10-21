"""The map page: the vendored Leaflet files, the data and markup the page carries, how other pages link to
it, and the small pure functions in sitegen/assets/map.js (run under Node, skipped without it)."""
import base64
import hashlib
import inspect
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

ASSETS = os.path.join(ROOT, "sitegen", "assets")
LEAFLET = os.path.join(ASSETS, "vendor", "leaflet")
MAP_JS = os.path.join(ASSETS, "map.js")
NODE = shutil.which("node")

# The values Leaflet publishes for 1.9.4.
LEAFLET_SHA256 = {
    "leaflet.js": "20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=",
    "leaflet.css": "p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=",
}


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def payload():
    # tests/test_sitegen.py builds fuller inputs; the map only needs each spot's place, rating and position.
    spots = []
    for i, s in enumerate(config.SPOTS):
        spots.append({
            "slug": s["slug"], "name": s["name"], "area": s["area"], "lat": s["lat"], "lon": s["lon"],
            "rating": 5.5 + (i % 4), "band": ("green", "yellow", "orange", "red")[i % 4], "label": "Fair",
            "now": {"height_ft": 3.0, "period_s": 14.0, "swell_dir": "SW", "wind_kn": 4.0, "wind_dir": "ENE",
                    "tide_ft": 2.5, "tide_state": "rising", "words": {"size": "waist-high", "power": "long-period swell",
                                                                      "wind": "glassy", "tide": "Medium tide, coming in"}},
            "window": None,
        })
    return {"spots": spots, "breaks": [dict(slug=s["slug"], name=s["name"], area=s["area"], aliases=[]) for s in spots],
            "site_url": config.SITE_URL, "repo_url": "https://example.test/repo", "profiles_api": config.PROFILES_API,
            "sources": {"waves": "w", "tides": "t", "forecast": "f"}}


class Vendored(unittest.TestCase):
    def test_leaflet_files_are_the_unmodified_originals(self):
        for name, want in LEAFLET_SHA256.items():
            with open(os.path.join(LEAFLET, name), "rb") as f:
                got = base64.b64encode(hashlib.sha256(f.read()).digest()).decode()
            self.assertEqual(got, want, name + " has been changed; see sitegen/assets/vendor/leaflet/SOURCE.txt")

    def test_its_licence_travels_with_it(self):
        self.assertIn("BSD 2-Clause", read(os.path.join(LEAFLET, "LICENSE")))
        self.assertTrue(os.path.exists(os.path.join(LEAFLET, "SOURCE.txt")))


class Page(unittest.TestCase):
    def setUp(self):
        self.p = payload()
        self.html = render.map_page(self.p)
        raw = re.search(r'<script type="application/json" id="map-data">(.*?)</script>', self.html, re.S).group(1)
        self.points = json.loads(raw)

    def test_every_break_is_a_point_with_a_position_inside_san_diego_county(self):
        self.assertEqual([p["slug"] for p in self.points], [s["slug"] for s in config.SPOTS])
        for p in self.points:
            self.assertTrue(32.4 < p["lat"] < 33.4 and -117.5 < p["lon"] < -117.0, p["slug"])

    def test_points_carry_what_the_card_shows(self):
        for p in self.points:
            for key in ("name", "place", "rating", "band", "label", "cond", "when", "href"):
                self.assertTrue(p[key] not in (None, ""), "%s: %s" % (p["slug"], key))
            self.assertEqual(p["href"], "../spots/%s/" % p["slug"])
            self.assertIn(p["band"], ("green", "yellow", "orange", "red"))

    def test_leaflet_loads_before_the_page_script_and_its_stylesheet_before_ours(self):
        self.assertLess(self.html.index("vendor/leaflet/leaflet.js"), self.html.index("assets/map.js"))
        self.assertLess(self.html.index("vendor/leaflet/leaflet.css"), self.html.index("assets/style.css"))

    def test_the_card_and_controls_the_script_fills_exist(self):
        for hook in ("data-map-root", 'id="map"', "data-card", "data-card-close", "data-card-photo", "data-card-name", "data-card-place",
                     "data-card-chip", "data-card-cond", "data-card-when", "data-card-link", 'data-mode="satellite"', 'data-mode="map"'):
            self.assertIn(hook, self.html, hook)

    def test_there_is_a_list_that_works_without_the_map(self):
        for s in config.SPOTS:
            self.assertIn('href="../spots/%s/"' % s["slug"], self.html)
        self.assertIn("<noscript>", self.html)

    def test_the_legend_names_all_four_tiers_with_an_icon_each(self):
        for ico in ("✓", "!", "▼", "✕"):
            self.assertIn('<span class="pin-ico">%s</span>' % ico, self.html)

    def test_a_dot_has_a_small_click_area_so_neighbours_do_not_cover_each_other(self):
        css = read(os.path.join(ASSETS, "style.css"))
        rule = re.search(r"\.map-far \.pin-wrap \{([^}]*)\}", css).group(1)
        self.assertRegex(rule, r"width:\s*22px\s*!important")
        self.assertRegex(rule, r"height:\s*22px\s*!important")
        self.assertRegex(rule, r"margin-left:\s*-11px\s*!important")     # still centred on the break

    def test_the_card_starts_closed(self):
        self.assertRegex(self.html, r'<aside class="map-card" data-card hidden')

    def test_no_third_party_key_is_needed_or_shipped(self):
        # CARTO's basemaps began to demand an API key; the map uses the USGS's free, keyless tiles.
        text = self.html + read(MAP_JS)
        self.assertNotIn("cartocdn", text)
        self.assertNotRegex(text, r"(?i)api[_-]?key\s*[=:]")
        self.assertIn("basemap.nationalmap.gov", read(MAP_JS))


class Links(unittest.TestCase):
    def test_the_menu_has_a_map_link_from_every_depth(self):
        for prefix in ("", "../", "../../"):
            self.assertIn('href="%smap/"' % (prefix or "./"), render._header(prefix))

    def test_map_is_a_button_beside_my_alerts_not_only_inside_the_menu_phones_hide(self):
        for prefix in ("", "../", "../../"):
            header = render._header(prefix)
            href = "%smap/" % (prefix or "./")
            nav = header[header.index("<nav"):header.index("</nav>")]
            self.assertNotIn(href, nav)
            self.assertIn('<a class="top-tab" href="%s">Map</a>' % href, header)
            self.assertLess(header.index('class="top-tab"'), header.index('class="top-cta"'))

    def test_the_phone_menu_still_offers_the_colour_theme(self):
        # The header's own theme button is hidden on the narrowest phones to make room.
        header = render._header("")
        self.assertEqual(header.count("data-theme-toggle"), 2)

    def test_the_home_page_and_break_pages_link_to_it(self):
        self.assertIn('href="map/"', inspect.getsource(render.index_page))
        self.assertIn('href="../../map/#%s"', inspect.getsource(render.spot_page))

    def test_the_footer_credits_the_map_data_and_leaflet(self):
        footer = render._footer(payload())
        self.assertIn("USGS The National Map", footer)
        self.assertIn("Leaflet", footer)

    def test_the_site_build_writes_the_page(self):
        import tempfile
        import sitegen
        from tests.test_sitegen import at, make_inputs
        now = at(0, 10)
        with tempfile.TemporaryDirectory() as out:
            sitegen.build(make_inputs(now), now, out)
            self.assertTrue(os.path.exists(os.path.join(out, "map", "index.html")))
            for name in ("leaflet.js", "leaflet.css", "LICENSE"):
                self.assertTrue(os.path.exists(os.path.join(out, "assets", "vendor", "leaflet", name)), name)
            self.assertTrue(os.path.exists(os.path.join(out, "assets", "map.js")))


RUNNER = """
const M = require(process.argv[1]);
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify({
  hashes: input.hashes.map(h => M.slugFromHash(h, input.slugs)),
  far: input.zooms.map(z => M.isFar(z)),
  label: M.pinLabel({ name: "Swami's", label: 'Good', rating: 7.04 }),
  tips: input.tips.map(p => M.tipParts(p)),
  modes: input.modes.map(m => M.validMode(m)),
  tiles: M.TILES, farZoom: M.FAR_ZOOM, sat: M.SATELLITE_MIN_ZOOM, native: M.NATIVE_ZOOM,
  glyphs: M.GLYPH,
  clusters: input.clusters.map(c => M.cluster(c.items, c.w, c.h, c.keep)),
  boxes: [M.pinBox(true), M.pinBox(false)],
}));
"""


@unittest.skipUnless(NODE, "Node is not installed")
class Script(unittest.TestCase):
    def run_js(self, **kw):
        base = {"hashes": [], "slugs": ["swamis", "d-street"], "zooms": [], "modes": [], "tips": [], "clusters": []}
        base.update(kw)
        out = subprocess.run([NODE, "-e", RUNNER, MAP_JS], input=json.dumps(base), capture_output=True, text=True, timeout=60, check=True)
        return json.loads(out.stdout)

    def test_an_address_names_a_break_only_if_we_know_it(self):
        got = self.run_js(hashes=["#swamis", "swamis", "#d-street", "#nowhere", "", None, "#%73wamis", "#swamis/../x"])["hashes"]
        self.assertEqual(got, ["swamis", "swamis", "d-street", None, None, None, "swamis", None])

    def test_pins_shrink_to_dots_when_zoomed_out(self):
        r = self.run_js(zooms=[9, 10, 10.5, 11, 11.5, 12, 13, 16])
        self.assertEqual(r["far"], [True, True, True, True, True, False, False, False])

    def test_the_hover_label_says_which_break_and_how_it_rates(self):
        tips = self.run_js(tips=[{"name": "Swami's", "band": "yellow", "rating": 5.55, "label": "Fair"},
                                 {"name": "Blacks", "band": "red", "rating": 1.9, "label": "Very poor"}])["tips"]
        self.assertEqual((tips[0]["name"], tips[0]["glyph"], tips[0]["label"]), ("Swami's", "!", "Fair"))
        self.assertIn(tips[0]["rating"], ("5.5", "5.6"))       # one decimal, whichever way .55 rounds
        self.assertEqual(tips[1], {"name": "Blacks", "glyph": "✕", "rating": "1.9", "label": "Very poor"})

    def test_pins_have_a_label_on_hover_and_focus_and_no_slow_native_tooltip(self):
        js = read(MAP_JS)
        self.assertIn("bindTooltip", js)
        self.assertIn("flyToBounds", js)                   # a badge zooms in on its breaks
        self.assertIn("openTooltip", js)
        self.assertIn("closeTooltip", js)
        self.assertIn("aria-label", js)                    # the pin's accessible name, now that title is gone
        self.assertNotRegex(js, r"title:\s*pinLabel")

    def cluster(self, items, w=40, h=40, keep=()):
        return self.run_js(clusters=[{"items": [dict(slug=s, x=x, y=y, rating=r) for s, x, y, r in items], "w": w, "h": h, "keep": list(keep)}])["clusters"][0]

    def test_pins_that_collide_become_one_group_led_by_the_best_rated(self):
        got = self.cluster([("a", 0, 0, 5.0), ("b", 10, 5, 8.0), ("c", 400, 400, 6.0)])
        self.assertEqual(got, [["b", "a"], ["c"]])

    def test_pins_far_apart_stay_separate(self):
        self.assertEqual(self.cluster([("a", 0, 0, 5.0), ("b", 100, 0, 6.0), ("c", 0, 100, 7.0)]), [["c"], ["b"], ["a"]])

    def test_the_gap_has_to_be_small_in_both_directions(self):
        self.assertEqual(self.cluster([("a", 0, 0, 5.0), ("b", 30, 100, 6.0)]), [["b"], ["a"]])      # close across, far down
        self.assertEqual(self.cluster([("a", 0, 0, 5.0), ("b", 39, 39, 6.0)]), [["b", "a"]])
        self.assertEqual(self.cluster([("a", 0, 0, 5.0), ("b", 40, 0, 6.0)]), [["b"], ["a"]])         # exactly the limit is not a collision

    def test_a_pin_belongs_to_one_group_only(self):
        got = self.cluster([("a", 0, 0, 9.0), ("b", 30, 0, 8.0), ("c", 60, 0, 7.0)])
        self.assertEqual(sorted(s for g in got for s in g), ["a", "b", "c"])
        self.assertEqual(got, [["a", "b"], ["c"]])                          # c is close to b but b already joined a

    def test_the_open_card_break_is_never_swallowed(self):
        got = self.cluster([("a", 0, 0, 9.0), ("b", 10, 0, 5.0)], keep=["b"])
        self.assertEqual(got, [["a"], ["b"]])

    def test_a_kept_break_does_not_absorb_its_neighbours(self):
        self.assertEqual(self.cluster([("b", 0, 0, 9.0), ("a", 10, 0, 5.0)], keep=["b"]), [["b"], ["a"]])

    def test_nothing_in_nothing_out(self):
        self.assertEqual(self.cluster([]), [])

    def test_dots_and_pills_use_different_collision_boxes(self):
        far, near = self.run_js()["boxes"]
        self.assertEqual(far, {"w": 38, "h": 38})        # a badge
        self.assertGreater(near["w"], near["h"])          # a pill is wider than it is tall

    def test_the_pin_label_reads_well_aloud(self):
        self.assertEqual(self.run_js()["label"], "Swami's, Good, 7.0 out of 10")

    def test_the_map_style_choice_is_checked(self):
        self.assertEqual(self.run_js(modes=["satellite", "map", "dark", None, ""])["modes"], ["satellite", "map", "satellite", "satellite", "satellite"])

    def test_tiles_are_keyless_usgs_and_the_zoom_limits_agree(self):
        r = self.run_js()
        for url in r["tiles"].values():
            self.assertTrue(url.startswith("https://basemap.nationalmap.gov/arcgis/rest/services/"))
            self.assertIn("{z}/{y}/{x}", url)
        self.assertEqual(r["native"], 16)
        self.assertEqual(r["sat"], 11)           # its imagery has no ocean below this
        self.assertEqual(r["farZoom"], 12)       # pins become numbers once neighbours are far enough apart not to cover each other

    def test_every_band_has_a_glyph(self):
        self.assertEqual(set(self.run_js()["glyphs"]), {"green", "yellow", "orange", "red"})

    def test_the_script_never_uses_innerhtml(self):
        self.assertIsNone(re.search(r"innerHTML|outerHTML|document\.write", read(MAP_JS)))


if __name__ == "__main__":
    unittest.main()
