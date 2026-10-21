"""The break roster in config.py: every entry has to be coherent, because a typo in one of 28
breaks' coordinates, tide range or buoy would otherwise go unnoticed until someone relied on it."""
import math
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

# NDBC offshore buoys the roster may use (id -> lat, lon); see config.py for why not nearshore ones.
BUOYS = {
    "46224": (33.178, -117.472),   # Oceanside Offshore
    "46225": (32.933, -117.391),   # Torrey Pines Outer
    "46258": (32.749, -117.502),   # Mission Bay West
    "46232": (32.517, -117.425),   # Point Loma South
}
ORIGINAL_FIVE = ["swamis", "grandview", "beacons", "blacks", "oceanside"]


def km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 6371 * 2 * math.asin(math.sqrt(a))


def cfgs():
    return [config.spot_config(s) for s in config.SPOTS]


class Roster(unittest.TestCase):
    def test_covers_the_county_not_just_a_handful(self):
        self.assertGreaterEqual(len(config.SPOTS), 25)

    def test_slugs_and_names_are_unique_and_url_safe(self):
        slugs = [s["slug"] for s in config.SPOTS]
        names = [s["name"] for s in config.SPOTS]
        self.assertEqual(len(set(slugs)), len(slugs))
        self.assertEqual(len(set(names)), len(names))
        for slug in slugs:
            self.assertRegex(slug, r"^[a-z0-9]+(-[a-z0-9]+)*$")

    def test_public_topics_are_unique_and_header_safe(self):
        topics = [c["ntfy_topic"] for c in cfgs()]
        self.assertEqual(len(set(topics)), len(topics))
        for t in topics + [config.public_topic("daily")]:
            self.assertRegex(t, r"^[a-z0-9-]+$")

    def test_every_break_is_on_the_san_diego_county_coast(self):
        for s in config.SPOTS:
            self.assertTrue(32.50 <= s["lat"] <= 33.30, "%s lat" % s["name"])
            self.assertTrue(-117.45 <= s["lon"] <= -117.10, "%s lon" % s["name"])

    def test_no_coordinate_strays_far_from_the_line_the_coast_follows(self):
        # catches a sign or digit typo: no break should sit more than 12 km off the straight
        # line from the northernmost to the southernmost break
        pts = sorted(((s["lat"], s["lon"]) for s in config.SPOTS), reverse=True)
        north, south = pts[0], pts[-1]
        for lat, lon in pts:
            t = (north[0] - lat) / (north[0] - south[0])
            line_lon = north[1] + t * (south[1] - north[1])
            self.assertLess(abs(lon - line_lon) * 111 * math.cos(math.radians(lat)), 12, (lat, lon))

    def test_each_break_uses_approved_offshore_buoys_and_its_nearest_is_among_them(self):
        for s in config.SPOTS:
            for b in s["buoys"]:
                self.assertIn(b, BUOYS, "%s uses %s" % (s["name"], b))
            nearest = min(BUOYS, key=lambda b: km(s["lat"], s["lon"], *BUOYS[b]))
            self.assertIn(nearest, s["buoys"], "%s: nearest buoy %s isn't used" % (s["name"], nearest))
            first = s["buoys"][0]
            self.assertLess(km(s["lat"], s["lon"], *BUOYS[first]), 60, "%s first buoy too far" % s["name"])

    def test_ranges_are_ordered_and_nested(self):
        for c in cfgs():
            n = c["name"]
            self.assertLess(c["height_ok_ft"][0], c["height_ok_ft"][1], n)
            self.assertLess(c["height_ideal_ft"][0], c["height_ideal_ft"][1], n)
            self.assertLessEqual(c["height_ok_ft"][0], c["height_ideal_ft"][0], n)
            self.assertGreaterEqual(c["height_ok_ft"][1], c["height_ideal_ft"][1], n)
            self.assertLess(c["tide_ideal_ft"][0], c["tide_ideal_ft"][1], n)
            self.assertLessEqual(c["tide_ok_ft"][0], c["tide_ideal_ft"][0], n)
            self.assertGreaterEqual(c["tide_ok_ft"][1], c["tide_ideal_ft"][1], n)
            self.assertLessEqual(c["period_min_s"], c["period_ideal_s"], n)
            self.assertLess(c["wind_ideal_kn"], c["wind_max_kn"], n)

    def test_swell_windows_are_real_compass_arcs_that_face_the_ocean(self):
        for c in cfgs():
            lo, hi = c["swell_dir_deg"]
            self.assertTrue(0 <= lo < hi <= 360, c["name"])
            self.assertGreaterEqual(hi - lo, 40, "%s window too narrow to ever be useful" % c["name"])
            # every break faces west-ish; a window entirely east of south would be a typo
            self.assertTrue(lo >= 160 and hi <= 330, "%s window %s-%s" % (c["name"], lo, hi))

    def test_every_break_has_an_area_notes_and_clean_aliases(self):
        for s in config.SPOTS:
            self.assertTrue(s["area"].strip(), s["name"])
            self.assertTrue(s.get("notes", "").strip(), s["name"])
            for a in config.spot_config(s)["aliases"]:
                self.assertEqual(a, a.lower(), "%s alias %r" % (s["name"], a))
                self.assertEqual(a, a.strip())

    def test_no_alias_points_at_two_different_breaks_by_accident(self):
        seen = {}
        for s in config.SPOTS:
            for a in s.get("aliases", []):
                self.assertNotIn(a, seen, "alias %r on both %s and %s" % (a, seen.get(a), s["name"]))
                seen[a] = s["name"]

    def test_only_the_original_five_are_the_owners(self):
        mine = [c["slug"] for c in cfgs() if c["mine"]]
        self.assertEqual(sorted(mine), sorted(ORIGINAL_FIVE))

    def test_the_original_five_come_first_and_keep_their_settings(self):
        self.assertEqual([s["slug"] for s in config.SPOTS[:5]], ORIGINAL_FIVE)
        swamis = config.spot_config(config.SPOTS[0])
        self.assertEqual(swamis["buoys"], ["46224", "46225"])
        self.assertEqual(swamis["tide_ideal_ft"], [2.5, 5.0])

    def test_pipes_sits_between_swamis_and_cardiff_reef_where_the_spot_guides_put_it(self):
        by = {c["slug"]: c for c in cfgs()}
        pipes, north, south = by["pipes"], by["swamis"], by["cardiff"]
        self.assertLess(south["lat"], pipes["lat"])
        self.assertLess(pipes["lat"], north["lat"])
        self.assertLess(km(pipes["lat"], pipes["lon"], 33.0246, -117.2888), 0.5)     # the two guides agree to within a few hundred metres
        self.assertLess(km(pipes["lat"], pipes["lon"], south["lat"], south["lon"]), 3.0)
        self.assertEqual(pipes["area"], "Cardiff")

    def test_pipes_wants_what_the_guides_say_it_wants(self):
        c = {c["slug"]: c for c in cfgs()}["pipes"]
        lo, hi = c["swell_dir_deg"]
        self.assertLessEqual(lo, 195)                      # the guides give 182 to 303 degrees: south-west through west-north-west
        self.assertGreaterEqual(hi, 300)
        self.assertLess(c["tide_ideal_ft"][1], 4.0)        # low to mid tide, not the high water Cardiff Reef likes
        self.assertEqual(c["offshore_dir_deg"], [40, 110])  # north-east to east, east-north-east best
        self.assertEqual(c["height_ideal_ft"], [3.0, 6.0])
        self.assertFalse(c["mine"])
        self.assertEqual(c["buoys"], config.BUOY_CENTRAL)

    def test_pipes_is_found_by_the_names_people_use(self):
        c = {c["slug"]: c for c in cfgs()}["pipes"]
        for alias in ("pipes", "san elijo", "campgrounds"):
            self.assertIn(alias, c["aliases"])

    def test_home_shows_five(self):
        self.assertEqual(config.HOME_COUNT, 5)

    def test_every_break_has_the_fields_the_checker_needs(self):
        for c in cfgs():
            for key in ("name", "slug", "area", "lat", "lon", "buoys", "tide_station", "offshore_dir_deg"):
                self.assertIn(key, c, "%s.%s" % (c["name"], key))
            self.assertRegex(c["tide_station"], r"^\d{7}$")


if __name__ == "__main__":
    unittest.main()
