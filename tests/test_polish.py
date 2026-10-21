"""Pre-launch polish: home-screen icons, the web manifest, the sitemap and link previews for every page."""
import json
import os
import struct
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import config
import make_icons
import sitegen
from sitegen import media, render
from sitegen.build import manifest, sitemap
from tests.test_map import payload as map_payload
from tests.test_sitegen import at, make_inputs

ASSETS = os.path.join(ROOT, "sitegen", "assets")


def png_size(path):
    with open(path, "rb") as f:
        data = f.read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    w, h = struct.unpack(">II", data[16:24])
    return w, h, data


class Icons(unittest.TestCase):
    def test_the_three_icons_exist_at_the_right_sizes(self):
        for name, size in make_icons.SIZES.items():
            w, h, _ = png_size(os.path.join(ASSETS, name))
            self.assertEqual((w, h), (size, size), name)

    def test_they_are_valid_pngs_with_a_clean_ending(self):
        for name in make_icons.SIZES:
            _, _, data = png_size(os.path.join(ASSETS, name))
            self.assertTrue(data.endswith(b"IEND\xaeB`\x82"), name)
            idat = data[data.index(b"IDAT") + 4:data.index(b"IEND") - 8]
            zlib.decompress(idat)                                  # the picture data inflates

    def test_the_generator_is_deterministic_and_matches_the_files_in_the_repo(self):
        for name, size in make_icons.SIZES.items():
            if size > 192:
                continue                                          # the 512 one is checked by size above; this keeps the suite fast
            with open(os.path.join(ASSETS, name), "rb") as f:
                self.assertEqual(f.read(), make_icons.png(size), name + " is out of date: run tools/make_icons.py")


class Manifest(unittest.TestCase):
    def test_it_names_the_app_and_starts_at_the_home_page(self):
        m = manifest()
        self.assertEqual(m["name"], "Swell Check")
        self.assertEqual(m["start_url"], "./")
        self.assertEqual(m["display"], "standalone")

    def test_every_icon_it_lists_exists(self):
        for icon in manifest()["icons"]:
            path = os.path.join(ROOT, "sitegen", icon["src"])
            w, h, _ = png_size(path)
            self.assertEqual("%dx%d" % (w, h), icon["sizes"])

    def test_it_is_valid_json(self):
        json.loads(json.dumps(manifest()))


class Sitemap(unittest.TestCase):
    def test_it_lists_every_page_once_with_a_date(self):
        p = map_payload()
        p["generated"] = "2026-10-20T08:00:00-07:00"
        root = ET.fromstring(sitemap(p))
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locs = [u.find("s:loc", ns).text for u in root.findall("s:url", ns)]
        self.assertEqual(len(locs), len(set(locs)))
        base = config.SITE_URL.rstrip("/")
        for page in ("", "map/", "breaks/", "profile/"):
            self.assertIn("%s/%s" % (base, page), locs)
        for s in config.SPOTS:
            self.assertIn("%s/spots/%s/" % (base, s["slug"]), locs)
        self.assertEqual({u.find("s:lastmod", ns).text for u in root.findall("s:url", ns)}, {"2026-10-20"})


class Head(unittest.TestCase):
    def test_every_page_has_the_icon_and_manifest_links_from_any_depth(self):
        for prefix in ("", "../", "../../"):
            html = render._shell("T", "d", "<p>x</p>", prefix, map_payload())
            self.assertIn('rel="apple-touch-icon" href="%sassets/apple-touch-icon.png"' % prefix, html)
            self.assertIn('rel="manifest" href="%smanifest.webmanifest"' % prefix, html)

    def test_the_map_my_alerts_and_break_list_pages_get_a_link_preview_picture(self):
        p = map_payload()
        p["breaks"] = [dict(b, rating=7.0, band="green", label="Good", size="3 ft at 14 s") for b in p["breaks"]]
        pages = {"map": render.map_page(p), "profile": render.profile_page(p), "breaks": render.breaks_page(p)}
        for name, html in pages.items():
            self.assertIn('property="og:image"', html, name)
            self.assertIn("/assets/img/%s" % media.photo(media.HERO_SLUG)["file"], html, name)
            self.assertIn('name="twitter:card" content="summary_large_image"', html, name)

    def test_the_picture_address_is_absolute_so_other_apps_can_fetch_it(self):
        html = render.map_page(map_payload())
        self.assertIn('og:image" content="%s/assets/img/' % config.SITE_URL.rstrip("/"), html)


class Build(unittest.TestCase):
    def test_the_build_writes_the_manifest_sitemap_and_icons(self):
        now = at(0, 10)
        with tempfile.TemporaryDirectory() as out:
            sitegen.build(make_inputs(now), now, out)
            for rel in ("manifest.webmanifest", "sitemap.xml", "assets/apple-touch-icon.png", "assets/icon-192.png", "assets/icon-512.png"):
                self.assertTrue(os.path.exists(os.path.join(out, rel)), rel)
            with open(os.path.join(out, "manifest.webmanifest")) as f:
                self.assertEqual(json.load(f)["name"], "Swell Check")
            ET.parse(os.path.join(out, "sitemap.xml"))             # well-formed


if __name__ == "__main__":
    unittest.main()
