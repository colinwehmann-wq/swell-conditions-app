#!/usr/bin/env python3
"""Send each person an alert about an hour before their ideal conditions peak at one of their breaks.

  python3 tools/profile_alerts.py                       # the hourly job: fetch profiles, alert, remember
  python3 tools/profile_alerts.py --dry-run             # same, but print instead of sending or remembering
  python3 tools/profile_alerts.py --from-file p.json    # use {"profiles": [...]} from a file, no Worker needed
  python3 tools/profile_alerts.py --now 2026-10-20T06:10 --dry-run

Profiles come from the profile service (worker/), read with the admin key in PROFILES_ADMIN_KEY and
the address in PROFILES_API (default: config.PROFILES_API). Without a key it does nothing and says so.
Each alert goes only to that person's own private ntfy topic. What counts as "ideal", and when to
tell them, is in sources/profiles.py. Alerts already sent are remembered in .profile-state.json so the
same window never pings twice.
"""
import argparse
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import check  # noqa: E402  (its Context fetches and caches the forecast, tide and buoy data)
import config  # noqa: E402
from sources import evaluate, http, notify, profiles  # noqa: E402
from sources.timeutil import TZ, now as now_local  # noqa: E402

STATE_PATH = os.path.join(ROOT, ".profile-state.json")
MAX_PER_RUN = 3          # one person never gets more than this many alerts from a single run


def fetch_profiles(api, key):
    """Every stored profile, from the Worker, a page at a time."""
    out, cursor = [], None
    while True:
        url = api.rstrip("/") + "/api/admin/profiles" + ("?cursor=" + cursor if cursor else "")
        page = http.get_json(url, headers={"Authorization": "Bearer " + key})
        out.extend(page.get("profiles", []))
        cursor = page.get("cursor")
        if not cursor:
            return out


def load_state(path):
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(path, state):
    try:
        with open(path, "w") as f:
            json.dump(state, f, indent=1, sort_keys=True)
    except OSError as e:
        print("  ! could not write state: %s" % e, file=sys.stderr)


def hourly_rows(ctx, cfg, now):
    """Today's daylight hours at one break, scored, with the live buoy and tide folded in."""
    buoy = ctx.buoy(cfg["buoys"])
    tide = ctx.tide(cfg["tide_station"])
    marine = ctx.marine(cfg["lat"], cfg["lon"])
    wind = ctx.wind(cfg["lat"], cfg["lon"])
    sun = ctx.sun(cfg["lat"], cfg["lon"], now.date())
    if not sun or sun[0] is None:
        return []
    calib = evaluate.calibration(now, marine, wind, tide, buoy)
    return evaluate._daylight_rows(cfg, sun, now, marine, wind, tide, buoy, allow_buoy=True,
                                   calib=calib, start=sun[0])


def plan(people, cfgs, rows_for, state, now):
    """The alerts to send now as [(topic, slug, window, cfg)], best-rated first for each person and
    never more than MAX_PER_RUN each. `rows_for(cfg)` supplies the hourly rows."""
    out = []
    for person in people:
        topic = person.get("topic")
        if not topic:
            continue
        alerts = profiles.alerts_of(person)
        if profiles.in_quiet_hours(now.hour, alerts["quiet_from"], alerts["quiet_to"]):
            continue
        due = []
        for slug in person.get("breaks", []):
            cfg = cfgs.get(slug)
            if not cfg:
                continue
            window = profiles.upcoming(person, slug, cfg, rows_for(cfg), now)
            if window and profiles.should_send((state.get(topic) or {}).get(slug), window, now):
                due.append((topic, slug, window, cfg))
        due.sort(key=lambda d: -d[2]["peak"]["score"])
        out.extend(due[:MAX_PER_RUN])
    return out


def run(args):
    now = (datetime.datetime.strptime(args.now, "%Y-%m-%dT%H:%M").replace(tzinfo=TZ) if args.now else now_local())

    if args.from_file:
        with open(args.from_file) as f:
            people = json.load(f)["profiles"]
    else:
        key = os.environ.get("PROFILES_ADMIN_KEY", "").strip()
        if not key:
            print("PROFILES_ADMIN_KEY is not set; nothing to do.")
            return 0
        api = args.api or os.environ.get("PROFILES_API", "").strip() or config.PROFILES_API
        try:
            people = fetch_profiles(api, key)
        except Exception as e:  # noqa: BLE001
            print("could not read profiles: %s" % e, file=sys.stderr)
            return 1

    state = load_state(args.state)
    profiles.prune(state, {p.get("topic") for p in people}, now)
    cfgs = {c["slug"]: c for c in (config.spot_config(s) for s in config.SPOTS)}
    wanted = sorted({s for p in people for s in p.get("breaks", []) if s in cfgs})
    print("%d profiles, %d breaks in use, %s" % (len(people), len(wanted), now.strftime("%a %b %d %I:%M %p")))

    if wanted:
        ctx = check.Context(now)
        ctx.prefetch([cfgs[s] for s in wanted])
        cache = {}

        def rows_for(cfg):
            if cfg["slug"] not in cache:
                cache[cfg["slug"]] = hourly_rows(ctx, cfg, now)
            return cache[cfg["slug"]]

        todo = plan(people, cfgs, rows_for, state, now)
    else:
        todo = []

    sent = 0
    for topic, slug, window, cfg in todo:
        title, body = profiles.message(cfg["name"], window, cfg, now, site_url=config.SITE_URL)
        click = "%s/spots/%s/" % (config.SITE_URL.rstrip("/"), slug)
        if args.dry_run:
            print("\n>>> WOULD SEND (profile ...%s): %s\n%s\n" % (topic[-4:], title, body))
            continue
        if notify.send_to_topic(topic, title, body, click=click):
            profiles.record(state, topic, slug, window, now)
            sent += 1
    count = len(todo) if args.dry_run else sent
    print("%d alert%s %s" % (count, "" if count == 1 else "s", "would be sent" if args.dry_run else "sent"))

    if not args.dry_run:
        save_state(args.state, state)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", help="the profile service's address (default: PROFILES_API or config.PROFILES_API)")
    ap.add_argument("--from-file", metavar="FILE", help='read {"profiles": [...]} from a file instead of the service')
    ap.add_argument("--state", default=STATE_PATH, help="where sent alerts are remembered")
    ap.add_argument("--now", help="pretend it is this local time, e.g. 2026-10-20T06:10")
    ap.add_argument("--dry-run", action="store_true", help="print what would be sent; send and remember nothing")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
