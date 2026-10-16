"""Growing the roster must not change who gets what: the owner's phone only hears about the
owner's own breaks, and fetching a couple of dozen breaks must not mean a couple of dozen
sequential network calls."""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import check
import config
from sources import notify
from tests.test_sitegen import at, make_inputs

NOW = at(0, 10)
MINE_IDX, OTHER_IDX = 0, 5          # Swami's (the owner's) and Oceanside Pier (not)


def results_for(*idx):
    return [i["result"] for i in make_inputs(NOW, spots=tuple(idx))]


class NotifyScope(unittest.TestCase):
    def setUp(self):
        self.posts = []
        self._post = notify.http.post
        notify.http.post = lambda url, body="", headers=None, timeout=15: self.posts.append(url)
        self._env = {k: os.environ.get(k) for k in ("NTFY_TOPIC", "SURF_PUBLISH_PUBLIC", "SURF_WEBHOOK_URL", "NTFY_SERVER")}
        os.environ["NTFY_TOPIC"] = "owner-private"
        os.environ["SURF_PUBLISH_PUBLIC"] = "1"
        os.environ["SURF_WEBHOOK_URL"] = "https://hooks.example/owner"
        os.environ["NTFY_SERVER"] = "https://ntfy.test"

    def tearDown(self):
        notify.http.post = self._post
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_by_default_a_message_goes_to_the_private_topic_the_public_ones_and_the_webhook(self):
        notify.send("t", "b", public_topics=("pub-a",))
        self.assertEqual(sorted(self.posts), sorted([
            "https://ntfy.test/owner-private", "https://ntfy.test/pub-a", "https://hooks.example/owner"]))

    def test_public_only_never_touches_the_owners_phone_or_webhook(self):
        notify.send("t", "b", public_topics=("pub-a",), private=False)
        self.assertEqual(self.posts, ["https://ntfy.test/pub-a"])

    def test_public_only_still_respects_the_public_publishing_switch(self):
        os.environ["SURF_PUBLISH_PUBLIC"] = ""
        notify.send("t", "b", public_topics=("pub-a",), private=False)
        self.assertEqual(self.posts, [])


class Alerts(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self._send = check.notify.send
        check.notify.send = lambda title, body, **kw: self.sent.append((title, kw))

    def tearDown(self):
        check.notify.send = self._send

    def test_the_owners_break_reaches_their_phone_and_its_own_public_topic(self):
        mine = results_for(MINE_IDX)
        check.send_alerts(mine, NOW)
        (_t, kw), = self.sent
        self.assertTrue(kw["private"])
        self.assertEqual(kw["public_topics"], (mine[0]["cfg"]["ntfy_topic"],))

    def test_any_other_break_reaches_only_its_public_topic(self):
        other = results_for(OTHER_IDX)
        check.send_alerts(other, NOW)
        (_t, kw), = self.sent
        self.assertFalse(kw["private"])
        self.assertEqual(kw["public_topics"], (other[0]["cfg"]["ntfy_topic"],))
        self.assertIn("/spots/%s/" % other[0]["cfg"]["slug"], kw["click"])

    def test_a_mixed_batch_is_split_correctly(self):
        both = results_for(MINE_IDX, OTHER_IDX, 6, 7)
        check.send_alerts(both, NOW)
        flags = [kw["private"] for _t, kw in self.sent]
        self.assertEqual(flags, [True, False, False, False])


class Digests(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self._send = check.notify.send
        check.notify.send = lambda title, body, **kw: self.sent.append((title, body, kw))

    def tearDown(self):
        check.notify.send = self._send

    def county(self):
        return results_for(*range(len(config.SPOTS)))

    def test_the_private_digest_covers_only_the_owners_breaks(self):
        check.send_digests(self.county(), NOW, {"last_alert": NOW.isoformat()})
        _title, body, kw = self.sent[0]
        self.assertNotIn("private", kw)                    # default: the private topic
        self.assertNotIn("public_topics", kw)
        text = body.lower()
        for cfg in config.SPOTS:
            if cfg.get("mine"):
                self.assertIn(cfg["name"].lower(), text)
            else:
                self.assertNotIn(cfg["name"].lower(), text, "private digest mentions %s" % cfg["name"])

    def test_the_public_digest_is_the_countys_best_five_to_the_public_topic_only(self):
        res = self.county()
        check.send_digests(res, NOW, {})
        _t, body, kw = self.sent[1]
        self.assertFalse(kw["private"])
        self.assertEqual(kw["public_topics"], (config.public_topic("daily"),))
        text = body.lower()
        best = {r["name"] for r in check._best_first(res)[:config.HOME_COUNT]}
        for name in best:
            self.assertIn(name.lower(), text)
        mentioned = {r["name"] for r in res if r["name"].lower() in text}
        self.assertEqual(mentioned, best)

    def test_the_public_digest_leaves_out_the_owners_heartbeat_line(self):
        meta = {"last_alert": NOW.isoformat(), "last_run": NOW.isoformat()}
        check.send_digests(self.county(), NOW, meta)
        private_body, public_body = self.sent[0][1], self.sent[1][1]
        self.assertNotEqual(private_body, public_body)
        self.assertNotIn("last GO alert", public_body)

    def test_narrowing_a_run_to_one_spot_skips_the_public_digest(self):
        check.send_digests(results_for(MINE_IDX), NOW, {}, whole_county=False)
        self.assertEqual(len(self.sent), 1)
        self.assertNotIn("private", self.sent[0][2])

    def test_with_none_of_the_owners_breaks_in_the_run_there_is_no_private_digest(self):
        check.send_digests(results_for(OTHER_IDX, 6), NOW, {})
        self.assertEqual(len(self.sent), 1)
        self.assertFalse(self.sent[0][2]["private"])


class Prefetch(unittest.TestCase):
    def setUp(self):
        self.lock = threading.Lock()
        self.calls = {"marine": 0, "wind": 0, "tide": 0, "buoy": 0}
        self.inflight = 0
        self.peak = 0
        self._orig = (check.forecast.marine, check.forecast.wind_and_sun, check.tides.fetch, check.ndbc.fetch_spec)

        def work(kind):
            with self.lock:
                self.calls[kind] += 1
                self.inflight += 1
                self.peak = max(self.peak, self.inflight)
            time.sleep(0.03)
            with self.lock:
                self.inflight -= 1

        def marine(lat, lon, days=3):
            work("marine")
            return {}

        def wind_and_sun(lat, lon, days=3):
            work("wind")
            return {}, {}

        def tide(station, start, days=1):
            work("tide")
            return None

        def buoy(bid, max_age_hours=3.0):
            work("buoy")
            return None

        check.forecast.marine, check.forecast.wind_and_sun, check.tides.fetch, check.ndbc.fetch_spec = (
            marine, wind_and_sun, tide, buoy)
        self.spots = [config.spot_config(s) for s in config.SPOTS]

    def tearDown(self):
        check.forecast.marine, check.forecast.wind_and_sun, check.tides.fetch, check.ndbc.fetch_spec = self._orig

    def test_each_source_is_fetched_once_however_many_breaks_share_it(self):
        ctx = check.Context(NOW)
        ctx.prefetch(self.spots)
        grids = {(round(c["lat"], 2), round(c["lon"], 2)) for c in self.spots}
        buoys = {b for c in self.spots for b in c["buoys"]}
        self.assertEqual(self.calls, {"marine": len(grids), "wind": len(grids), "tide": 1, "buoy": len(buoys)})

    def test_it_really_runs_them_at_the_same_time(self):
        check.Context(NOW).prefetch(self.spots)
        self.assertGreater(self.peak, 1)

    def test_the_loop_afterwards_only_reads_the_caches(self):
        ctx = check.Context(NOW)
        ctx.prefetch(self.spots)
        before = dict(self.calls)
        for c in self.spots:
            ctx.buoy(c["buoys"])
            ctx.tide(c["tide_station"])
            ctx.marine(c["lat"], c["lon"])
            ctx.wind(c["lat"], c["lon"])
        self.assertEqual(self.calls, before)

    def test_a_failing_source_cannot_break_the_run(self):
        def boom(lat, lon, days=3):
            raise RuntimeError("HTTP 500")
        check.forecast.marine = boom
        ctx = check.Context(NOW)
        ctx.prefetch(self.spots)                      # must not raise
        self.assertEqual(ctx.marine(self.spots[0]["lat"], self.spots[0]["lon"]), {})


if __name__ == "__main__":
    unittest.main()
