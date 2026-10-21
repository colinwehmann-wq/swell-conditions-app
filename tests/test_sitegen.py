"""Tests for the website generator: payload shape, headline logic, HTML safety, file output."""
import datetime
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
from sources import boards
from sources import evaluate as E

TZ = datetime.timezone(datetime.timedelta(hours=-7))
DAY0 = datetime.date(2026, 10, 13)
IDENTITY = {"h_scale": 1.0, "p_shift": 0.0}


def at(day_offset, hour, minute=0):
    d = DAY0 + datetime.timedelta(days=day_offset)
    return datetime.datetime(d.year, d.month, d.day, hour, minute, tzinfo=TZ)


def sun_for(days):
    return {DAY0 + datetime.timedelta(days=i): (at(i, 6, 30), at(i, 18, 0)) for i in range(days)}


def forecast(days, height_m, period=14.0, wind_kn=3.0, wind_dir=75):
    marine, wind = {}, {}
    for i in range(days):
        for h in range(24):
            t = at(i, h)
            marine[t] = {"swell_wave_height": height_m, "swell_wave_period": period,
                         "swell_wave_direction": 250}
            wind[t] = {"wind_speed_10m": wind_kn, "wind_direction_10m": wind_dir}
    return marine, wind


def make_inputs(now, height_m=1.2, spots=(0, 1), first_name=None):
    marine, wind = forecast(10, height_m)
    sun = sun_for(10)
    inputs = []
    for idx in spots:
        cfg = config.spot_config(config.SPOTS[idx])
        if first_name and idx == spots[0]:
            cfg = dict(cfg, name=first_name)
        res = E.evaluate_spot(cfg, now, None, None, marine, wind, sun[DAY0], sun[DAY0 + datetime.timedelta(days=1)])
        calib = E.calibration(now, marine, wind, None, None)
        today_sun = sun[DAY0]
        day = DAY0 if now <= E.last_row_start(today_sun[1]) else DAY0 + datetime.timedelta(days=1)
        inputs.append({
            "result": res,
            "outlook": E.outlook(cfg, now, None, None, marine, wind, sun, calib, days=7),
            "sun": today_sun,
            "timeline_day": day,
            "timeline": E.timeline(cfg, day, sun[day], now, None, None, marine, wind, calib),
        })
    return inputs


class Payload(unittest.TestCase):
    def test_is_json_serialisable(self):
        payload = sitegen.make_payload(make_inputs(at(0, 10)), at(0, 10))
        json.dumps(payload)

    def test_spot_shape(self):
        payload = sitegen.make_payload(make_inputs(at(0, 10)), at(0, 10))
        spot = payload["spots"][0]
        for key in ("slug", "name", "area", "verdict", "rating", "band", "label", "now", "board",
                    "window", "timeline", "outlook", "ideal", "ntfy"):
            self.assertIn(key, spot)
        self.assertEqual(len(spot["outlook"]), 7)
        self.assertIn(spot["board"]["label"], boards.LABELS.values())

    def test_public_topics_come_from_config(self):
        payload = sitegen.make_payload(make_inputs(at(0, 10)), at(0, 10))
        ntfy = payload["spots"][0]["ntfy"]
        self.assertTrue(ntfy["topic"].startswith(config.PUBLIC_TOPIC_BASE))
        self.assertTrue(ntfy["app_url"].startswith("ntfy://"))
        self.assertTrue(ntfy["web_url"].startswith("https://"))
        self.assertEqual(payload["digest"]["topic"], config.public_topic("daily"))

    def test_ranking_is_best_first(self):
        payload = sitegen.make_payload(make_inputs(at(0, 10)), at(0, 10))
        by_slug = {s["slug"]: s for s in payload["spots"]}
        ratings = [by_slug[s]["rating"] for s in payload["ranking"]]
        self.assertEqual(ratings, sorted(ratings, reverse=True))


class Headline(unittest.TestCase):
    def test_daylight_and_good_names_the_pick(self):
        h = sitegen.make_payload(make_inputs(at(0, 10)), at(0, 10))["headline"]
        self.assertTrue(h["title"].endswith("is the pick."))
        self.assertTrue(h["slug"])

    def test_after_dark_looks_ahead_instead_of_claiming_right_now(self):
        h = sitegen.make_payload(make_inputs(at(0, 20)), at(0, 20))["headline"]
        self.assertEqual(h["kicker"], "Looking ahead")
        self.assertTrue(h["title"].startswith("Tomorrow is the one"))

    def test_flat_week(self):
        h = sitegen.make_payload(make_inputs(at(0, 10), height_m=0.2), at(0, 10))["headline"]
        self.assertEqual(h["title"], "A flat spell.")
        self.assertIsNone(h["slug"])


class Render(unittest.TestCase):
    def pages(self, **kw):
        now = kw.pop("now", at(0, 10))
        payload = sitegen.make_payload(make_inputs(now, **kw), now)
        return payload, render.index_page(payload), render.spot_page(payload["spots"][0], payload)

    def test_untrusted_text_is_escaped(self):
        evil = "<script>alert(1)</script>"
        _payload, index, spot = self.pages(first_name=evil)
        for page in (index, spot):
            self.assertNotIn(evil, page)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)

    def test_index_has_all_sections_and_opt_in(self):
        payload, index, _ = self.pages()
        for anchor in ('id="now"', 'id="week"', 'id="alerts"', 'id="how"', 'id="boards"'):
            self.assertIn(anchor, index)
        # the home page offers the digest; each break's own channel is on that break's page
        self.assertIn("Open digest in ntfy", index)
        self.assertIn(payload["digest"]["topic"], index)
        spot_page = render.spot_page(payload["spots"][0], payload)
        self.assertIn("Open in ntfy app", spot_page)
        self.assertIn(payload["spots"][0]["ntfy"]["topic"], spot_page)

    def test_every_rating_chip_has_icon_number_and_label(self):
        _payload, index, spot = self.pages()
        for page in (index, spot):
            chips = page.count('class="chip chip-')
            self.assertGreater(chips, 0)
            self.assertEqual(page.count('class="chip-ico"'), chips)
            self.assertEqual(page.count('class="chip-lbl"'), chips)

    def test_chart_has_a_table_alternative_and_hover_data(self):
        _payload, _index, spot = self.pages()
        self.assertIn("View as a table", spot)
        self.assertIn('data-tip="', spot)
        self.assertRegex(spot, r"Today, hour by hour")

    def test_after_dark_charts_tomorrow(self):
        _payload, _index, spot = self.pages(now=at(0, 20))
        self.assertIn("Tomorrow, hour by hour", spot)

    def test_asset_paths_are_relative_for_nested_pages(self):
        _payload, index, spot = self.pages()
        self.assertIn('href="assets/style.css"', index)
        self.assertIn('href="../../assets/style.css"', spot)

    def test_not_found_uses_absolute_asset_paths(self):
        payload, _i, _s = self.pages()
        page = render.not_found_page(payload)
        base = re.sub(r"^https?://[^/]+", "", config.SITE_URL).rstrip("/") + "/"
        self.assertIn('href="%sassets/style.css"' % base, page)


class Photos(unittest.TestCase):
    IMG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "sitegen", "assets", "img")

    def test_every_photo_belongs_to_a_real_break_and_carries_a_full_credit(self):
        slugs = {cfg["slug"] for cfg in config.SPOTS}
        for slug, p in media.PHOTOS.items():
            self.assertIn(slug, slugs, "photo for a break that doesn't exist")
            for key in ("file", "w", "h", "pos", "alt", "author", "licence", "source"):
                self.assertTrue(p[key], "%s.%s" % (slug, key))
            self.assertTrue(p["source"].startswith("https://commons.wikimedia.org/"))
            self.assertTrue(p["licence"][1].startswith("https://creativecommons.org/"))
            self.assertIn(p["licence"][0], media.credit_text(p))

    def test_the_original_five_still_have_photos(self):
        for slug in ("swamis", "grandview", "beacons", "blacks", "oceanside"):
            self.assertIsNotNone(media.photo(slug), slug)

    @staticmethod
    def jpeg_size(path):
        """(width, height) from a JPEG's start-of-frame marker; no imaging library needed."""
        with open(path, "rb") as f:
            data = f.read()
        i = 2
        while i < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                h, w = int.from_bytes(data[i + 5:i + 7], "big"), int.from_bytes(data[i + 7:i + 9], "big")
                return w, h
            i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
        raise ValueError("no frame header in %s" % path)

    def test_photo_files_exist_and_stay_web_sized(self):
        for slug, p in media.PHOTOS.items():
            path = os.path.join(self.IMG_DIR, p["file"])
            self.assertTrue(os.path.exists(path), path)
            self.assertLess(os.path.getsize(path), 600 * 1024, "%s is too heavy for a web page" % p["file"])

    def test_the_recorded_size_of_every_photo_is_its_real_size(self):
        # the page sets width and height from media.py to stop the layout jumping as images load
        for slug, p in media.PHOTOS.items():
            real = self.jpeg_size(os.path.join(self.IMG_DIR, p["file"]))
            self.assertEqual(real, (p["w"], p["h"]), slug)

    def test_every_photo_has_a_small_tile_copy_of_the_right_shape(self):
        for slug, p in media.PHOTOS.items():
            name, w, h = media.tile(p)
            path = os.path.join(self.IMG_DIR, name)
            self.assertTrue(os.path.exists(path), path)
            self.assertLess(os.path.getsize(path), 90 * 1024, "%s tile is not small" % name)
            real_w, real_h = self.jpeg_size(path)
            self.assertEqual(real_w, w, name)
            self.assertLessEqual(abs(real_h - h), 1, name)      # image tools round the height either way
            self.assertLessEqual(w, p["w"])

    def test_tile_never_upscales_and_keeps_the_aspect_ratio(self):
        small = {"file": "x.jpg", "w": 300, "h": 200}
        self.assertEqual(media.tile(small), ("x-sm.jpg", 300, 200))
        big = {"file": "y.jpg", "w": 1600, "h": 800}
        self.assertEqual(media.tile(big), ("y-sm.jpg", 480, 240))

    def test_every_photo_has_a_unique_file_and_a_unique_source(self):
        files = [p["file"] for p in media.PHOTOS.values()]
        sources = [p["source"] for p in media.PHOTOS.values()]
        self.assertEqual(len(set(files)), len(files))
        self.assertEqual(len(set(sources)), len(sources))

    def test_a_break_without_a_photo_falls_back_cleanly(self):
        self.assertIn("row-photo-plain", render._thumb("no-such-break-has-this-slug", ""))
        bg, credit = render._hero_bg("no-such-break-has-this-slug", "")
        self.assertIn("hero-bg-plain", bg)
        self.assertEqual(credit, "")

    def test_no_raw_downloads_are_left_in_the_assets(self):
        self.assertEqual([f for f in os.listdir(self.IMG_DIR) if f.startswith("raw-")], [])

    def test_home_hero_and_thumbnails(self):
        now = at(0, 10)
        payload = sitegen.make_payload(make_inputs(now, spots=(0, 1, 2, 3, 4)), now)
        index = render.index_page(payload)
        hero = media.PHOTOS[media.HERO_SLUG]["file"]
        self.assertIn('class="hero has-photo curtain"', index)
        self.assertIn('src="assets/img/%s"' % hero, index)
        self.assertEqual(index.count('class="row-photo"'), 5)
        # thumbnails sit beside a text heading, so they're decorative; they must not add noise for screen readers
        self.assertEqual(index.count('class="row-photo" href="spots/'), 5)
        self.assertNotIn('alt="Surfers', index.split('class="rows"')[1])

    def test_spot_hero_uses_that_spots_photo_with_alt_text(self):
        now = at(0, 10)
        payload = sitegen.make_payload(make_inputs(now), now)
        spot = payload["spots"][0]
        p = media.PHOTOS[spot["slug"]]
        page = render.spot_page(spot, payload)
        self.assertIn('src="../../assets/img/%s"' % p["file"], page)
        self.assertIn('alt="%s"' % render.esc(p["alt"]), page)

    def test_credits_are_shown_on_the_hero_and_in_the_footer(self):
        now = at(0, 10)
        payload = sitegen.make_payload(make_inputs(now, spots=(0, 1, 2, 3, 4)), now)
        index = render.index_page(payload)
        self.assertIn('class="photo-credit"', index)
        # the footer credits the photos of the breaks on the page, plus the hero's
        shown = {s["slug"] for s in payload["spots"]} | {media.HERO_SLUG}
        for slug in shown:
            p = media.PHOTOS[slug]
            self.assertIn(p["author"], index, slug)
            self.assertIn(p["licence"][1], index, slug)
            self.assertIn(render.esc(p["source"]), index, slug)

    def test_share_preview_image_is_absolute(self):
        now = at(0, 10)
        payload = sitegen.make_payload(make_inputs(now), now)
        index = render.index_page(payload)
        self.assertIn('property="og:image" content="%s/assets/img/%s"'
                      % (config.SITE_URL.rstrip("/"), media.PHOTOS[media.HERO_SLUG]["file"]), index)
        self.assertNotIn("og:image", render.not_found_page(payload))

    def test_build_copies_the_photos(self):
        now = at(0, 10)
        with tempfile.TemporaryDirectory() as out:
            sitegen.build(make_inputs(now), now, out)
            for p in media.PHOTOS.values():
                self.assertTrue(os.path.exists(os.path.join(out, "assets", "img", p["file"])), p["file"])
                self.assertTrue(os.path.exists(os.path.join(out, "assets", "img", media.tile(p)[0])), p["file"])


class SmoothScroll(unittest.TestCase):
    """The page slides up over the hero photo, and nothing is hidden without the script."""

    def pages(self):
        from sitegen.build import make_payload
        now = at(0, 10)
        payload = make_payload(make_inputs(now), now)
        return render.index_page(payload), render.spot_page(payload["spots"][0], payload)

    def test_home_and_break_pages_put_everything_under_the_hero_in_one_sheet(self):
        for html in self.pages():
            self.assertEqual(html.count('<div class="sheet">'), 1)
            self.assertLess(html.index("curtain"), html.index('<div class="sheet">'))
            self.assertLess(html.index('<div class="sheet">'), html.index("<footer"))

    def test_nothing_is_hidden_by_default(self):
        # The fade-in class is added by the script, so a page without it is fully visible.
        for html in self.pages():
            self.assertNotIn("rv", re.findall(r'class="([^"]*)"', html))

    def test_css_and_script_cover_motion_and_reduced_motion(self):
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sitegen", "assets")
        with open(os.path.join(base, "style.css")) as f:
            css = f.read()
        with open(os.path.join(base, "site.js")) as f:
            js = f.read()
        self.assertIn(".curtain { position: sticky", css)
        self.assertIn(".sheet {", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css[css.index(".curtain { position: sticky"):])
        self.assertIn("prefers-reduced-motion: reduce", js)
        self.assertIn("setProperty('--p'", js)
        self.assertIn("passive: true", js)

    def test_the_header_stays_in_view(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sitegen", "assets", "style.css")) as f:
            self.assertIn(".top { position: sticky; top: 0;", f.read())


class Build(unittest.TestCase):
    def test_writes_every_file(self):
        now = at(0, 10)
        with tempfile.TemporaryDirectory() as out:
            sitegen.build(make_inputs(now), now, out)
            for rel in ("index.html", "404.html", ".nojekyll", "assets/style.css", "assets/site.js",
                        "data/latest.json"):
                self.assertTrue(os.path.exists(os.path.join(out, rel)), rel)
            with open(os.path.join(out, "data", "latest.json"), encoding="utf-8") as f:
                data = json.load(f)
            for spot in data["spots"]:
                self.assertTrue(os.path.exists(os.path.join(out, "spots", spot["slug"], "index.html")))

    def test_rebuilding_into_an_existing_dir_works(self):
        now = at(0, 10)
        with tempfile.TemporaryDirectory() as out:
            sitegen.build(make_inputs(now), now, out)
            sitegen.build(make_inputs(now), now, out)


if __name__ == "__main__":
    unittest.main()
