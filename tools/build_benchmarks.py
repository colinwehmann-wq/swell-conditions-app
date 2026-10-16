#!/usr/bin/env python3
"""Measure every break against its own history and write benchmarks.json.

  python3 tools/build_benchmarks.py                    # all breaks, 2012 to now
  python3 tools/build_benchmarks.py --only swamis      # one break, to see what it produces
  python3 tools/build_benchmarks.py --cache ~/climate  # keep the downloads somewhere else

What it reads (all free, none needs a key), cached in --cache so a re-run takes seconds:
  - NOAA NDBC standard records for the break's offshore buoy: wave height, period, direction
  - NOAA CO-OPS wind observations at La Jolla (Scripps Pier) and tide predictions
  - Open-Meteo's archive for sunrise and sunset

Re-run it whenever a break's settings in config.py change or the scoring maths changes: a test
(tests/test_benchmarks.py) fails until benchmarks.json matches the code. The first run downloads
about 15 MB and takes five or six minutes, mostly waiting on the wind records.
"""
import argparse
import bisect
import collections
import datetime
import gzip
import json
import math
import os
import sys
import time
import urllib.request
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config  # noqa: E402
from sources import climate, evaluate  # noqa: E402

UA = {"User-Agent": "swell-conditions-app/1.0 (benchmark builder)"}
LOCAL = ZoneInfo("America/Los_Angeles")
UTC = datetime.timezone.utc
WIND_STATION = TIDE_STATION = "9410230"      # La Jolla (Scripps Pier)
COOPS = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
# Earliest year each buoy's standard record has the direction column filled in.
FIRST_YEAR = {"46224": 2012, "46225": 2012, "46232": 2012, "46258": 2016}


def fetch(url, path, tries=4):
    if os.path.exists(path):
        return
    last = None
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
                data = r.read()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
            return
        except OSError as e:
            last = e
            time.sleep(2 + 2 * attempt)
    raise RuntimeError("could not download %s: %s" % (url, last))


# ------------------------------------------------------------------------------------ waves

def load_waves(cache, buoy, first, last):
    """{local hour: (Hs m, dominant period s, mean direction deg)} from NDBC's yearly files."""
    out = {}
    for year in range(max(first, FIRST_YEAR[buoy]), last + 1):
        path = "%s/stdmet/%sh%d.txt.gz" % (cache, buoy, year)
        fetch("https://www.ndbc.noaa.gov/data/historical/stdmet/%sh%d.txt.gz" % (buoy, year), path)
        with gzip.open(path, "rt") as f:
            lines = f.read().splitlines()
        for line in lines[2:]:
            p = line.split()
            try:
                t = datetime.datetime(int(p[0]), int(p[1]), int(p[2]), int(p[3]), int(p[4]), tzinfo=UTC)
                hs, dpd, mwd = float(p[8]), float(p[9]), float(p[11])
            except (ValueError, IndexError):
                continue
            if hs >= 90 or dpd >= 90 or mwd >= 990:          # NDBC's "missing" markers
                continue
            local = t.astimezone(LOCAL).replace(minute=0, second=0, microsecond=0, tzinfo=None)
            out[local] = (hs, dpd, mwd)
    return out


# ------------------------------------------------------------------------------------- wind

def load_wind(cache, first, last):
    """{local hour: (mean speed kn, vector-mean direction deg)} from the 6-minute observations."""
    out = {}
    for year in range(first, last + 1):
        path = "%s/wind/%d.json" % (cache, year)
        if not os.path.exists(path):
            acc = collections.defaultdict(list)
            day = datetime.date(year, 1, 1)
            while day.year == year:
                end = min(day + datetime.timedelta(days=30), datetime.date(year, 12, 31))
                tmp = "%s/wind/_chunk.json" % cache
                if os.path.exists(tmp):
                    os.remove(tmp)
                fetch("%s?product=wind&station=%s&begin_date=%s&end_date=%s&time_zone=lst_ldt&units=english&format=json"
                      % (COOPS, WIND_STATION, day.strftime("%Y%m%d"), end.strftime("%Y%m%d")), tmp)
                with open(tmp) as f:
                    for r in json.load(f).get("data", []):
                        try:
                            pair = (float(r["s"]), float(r["d"]))
                        except (ValueError, KeyError):
                            continue
                        acc[r["t"][:13]].append(pair)
                os.remove(tmp)
                day = end + datetime.timedelta(days=1)
            hourly = {}
            for key, obs in acc.items():
                x = sum(s * math.sin(math.radians(d)) for s, d in obs) / len(obs)
                y = sum(s * math.cos(math.radians(d)) for s, d in obs) / len(obs)
                hourly[key] = [sum(s for s, _ in obs) / len(obs), (math.degrees(math.atan2(x, y)) + 360) % 360]
            with open(path, "w") as f:
                json.dump(hourly, f)
        with open(path) as f:
            for key, (kn, deg) in json.load(f).items():
                out[datetime.datetime.strptime(key, "%Y-%m-%d %H")] = (kn, deg)
    return out


# ------------------------------------------------------------------------------------ tides

class FastTide:
    """Cosine interpolation between hi/lo predictions, with a bisect so 100k lookups are quick."""

    def __init__(self, extremes):
        self.ext = extremes
        self.times = [e[0] for e in extremes]

    def __call__(self, when):
        i = bisect.bisect_right(self.times, when) - 1
        if i < 0 or i + 1 >= len(self.ext):
            return None
        (t1, h1), (t2, h2) = self.ext[i], self.ext[i + 1]
        frac = (when - t1).total_seconds() / (t2 - t1).total_seconds()
        return (h1 + h2) / 2.0 + (h1 - h2) / 2.0 * math.cos(math.pi * frac)


def load_tides(cache, first, last):
    ext = []
    for year in range(first, last + 1):
        path = "%s/tide/%d.json" % (cache, year)
        fetch("%s?product=predictions&begin_date=%d0101&end_date=%d1231&datum=MLLW&interval=hilo&units=english"
              "&time_zone=lst_ldt&format=json&station=%s" % (COOPS, year, year, TIDE_STATION), path)
        with open(path) as f:
            for p in json.load(f).get("predictions", []):
                ext.append((datetime.datetime.strptime(p["t"], "%Y-%m-%d %H:%M"), float(p["v"])))
    ext.sort()
    return FastTide(ext)


# --------------------------------------------------------------------------------------- sun

def load_sun(cache, first, last):
    path = "%s/sun.json" % cache
    end = min(datetime.date.today() - datetime.timedelta(days=2), datetime.date(last, 12, 31))
    fetch("https://archive-api.open-meteo.com/v1/archive?latitude=32.9&longitude=-117.3&start_date=%d-01-01&end_date=%s"
          "&daily=sunrise,sunset&timezone=America%%2FLos_Angeles" % (first, end), path)
    with open(path) as f:
        daily = json.load(f)["daily"]
    sun = {}
    for d, rise, set_ in zip(daily["time"], daily["sunrise"], daily["sunset"]):
        if rise and set_:
            sun[datetime.date.fromisoformat(d)] = (datetime.datetime.fromisoformat(rise), datetime.datetime.fromisoformat(set_))
    return sun


# -------------------------------------------------------------------------------------- main

def merged_waves(per_buoy, buoys):
    """Per hour, the first listed buoy that has a reading: the same rule the live app uses."""
    hours = set()
    for b in buoys:
        hours.update(per_buoy.get(b, {}))
    return {h: next(per_buoy[b][h] for b in buoys if h in per_buoy.get(b, {})) for h in hours}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", default=os.path.join(ROOT, ".climate-cache"))
    ap.add_argument("--first", type=int, default=2012)
    # NDBC publishes a year's file once it is over, so the default stops at last year.
    ap.add_argument("--last", type=int, default=datetime.date.today().year - 1)
    ap.add_argument("--out", default=os.path.join(ROOT, "benchmarks.json"))
    ap.add_argument("--only", metavar="SLUG", help="just this break; prints instead of writing")
    args = ap.parse_args()

    spots = [config.spot_config(s) for s in config.SPOTS]
    if args.only:
        spots = [s for s in spots if s["slug"] == args.only]
        if not spots:
            sys.exit("no break %r" % args.only)
    needed = sorted({b for s in spots for b in s["buoys"]})
    print("downloading history (cached in %s) ..." % args.cache, file=sys.stderr)
    per_buoy = {b: load_waves(args.cache, b, args.first, args.last) for b in needed}
    wind = load_wind(args.cache, args.first, args.last)
    tide = load_tides(args.cache, args.first, args.last)
    sun = load_sun(args.cache, args.first, args.last)
    print("waves %s | wind %d h | sun %d days" % ({b: len(w) for b, w in per_buoy.items()}, len(wind), len(sun)),
          file=sys.stderr)

    breaks = {}
    for cfg in spots:
        waves = merged_waves(per_buoy, cfg["buoys"])
        hours = climate.daylight_hours(waves, wind, tide, sun)
        breaks[cfg["slug"]] = climate.build(hours, cfg)
        b = breaks[cfg["slug"]]
        print("%-17s %5d days  P90 raw %.1f  P99.5 raw %.1f | days/yr at 7+: %s, 9+: %s" % (
            cfg["name"], b["history"]["days"], b["anchors"][6], b["anchors"][9],
            b["days_per_year"]["7"], b["days_per_year"]["9"]), file=sys.stderr)

    result = {
        "about": "Per-break rating anchors measured from NOAA history by tools/build_benchmarks.py. "
                 "Do not edit by hand; re-run the tool.",
        "scoring_version": evaluate.SCORING_VERSION,
        "percentiles": evaluate.RATING_PERCENTILES,
        "generated": datetime.date.today().isoformat(),
        "breaks": breaks,
    }
    if args.only:
        print(json.dumps(result["breaks"], indent=1))
        return 0
    with open(args.out, "w") as f:
        json.dump(result, f, indent=1)
        f.write("\n")
    print("wrote %s" % args.out, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
