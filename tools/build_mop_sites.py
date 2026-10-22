#!/usr/bin/env python3
"""Match each break to its nearest CDIP MOP point and write mop_sites.json.

  python3 tools/build_mop_sites.py                # all breaks
  python3 tools/build_mop_sites.py --only swamis  # one break, to see what it finds

MOP points run south to north along the coast, one every ~100 m, named D0001 (the border) to D1210
(San Onofre). Asking for every point's position would be 1,200 requests, so this samples every
STEP-th point to find the stretch of coast, then checks each point in that stretch. A break's match
is the closest point by distance; `km` records how far away it is so a poor match is visible.
"""
import argparse
import json
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import config  # noqa: E402
from sources import cdip  # noqa: E402

FIRST, LAST = 1, 1210
STEP = 10
WORKERS = 4                    # a university server: a few at a time is plenty


def site_name(n):
    return "D%04d" % n


def km(lat1, lon1, lat2, lon2):
    """Distance in km (equirectangular: fine over a few kilometres)."""
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2.0))
    y = math.radians(lat2 - lat1)
    return 6371.0 * math.hypot(x, y)


def nearest(points, lat, lon):
    """(number, km) of the point in {number: (lat, lon)} closest to (lat, lon)."""
    return min(((n, km(lat, lon, p[0], p[1])) for n, p in points.items()), key=lambda t: t[1])


def locate(numbers, fetch_location=cdip.fetch_location):
    """{number: (lat, lon)} for the given point numbers, fetched a few at a time. A point that fails is left out."""
    def one(n):
        try:
            lat, lon, _ = fetch_location(site_name(n))
            return n, (lat, lon)
        except Exception as e:  # noqa: BLE001
            print("  ! %s: %s" % (site_name(n), e), file=sys.stderr)
            return n, None
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        return {n: p for n, p in pool.map(one, numbers) if p}


def build(spots, fetch_location=cdip.fetch_location, step=STEP, first=FIRST, last=LAST):
    """{slug: {"site", "lat", "lon", "km"}} for the given break configs."""
    coarse = locate(range(first, last + 1, step), fetch_location)
    if not coarse:
        raise RuntimeError("could not read any MOP point positions")
    picks = {}
    for cfg in spots:
        n, _ = nearest(coarse, cfg["lat"], cfg["lon"])
        near = [i for i in range(max(first, n - step), min(last, n + step) + 1)]
        picks[cfg["slug"]] = near
    fine = locate(sorted({i for near in picks.values() for i in near}), fetch_location)
    out = {}
    for cfg in spots:
        pts = {i: fine[i] for i in picks[cfg["slug"]] if i in fine}
        if not pts:
            continue
        n, d = nearest(pts, cfg["lat"], cfg["lon"])
        out[cfg["slug"]] = {"site": site_name(n), "lat": round(pts[n][0], 5), "lon": round(pts[n][1], 5), "km": round(d, 2)}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", help="a single break's slug")
    ap.add_argument("--out", default=cdip.SITES_PATH)
    args = ap.parse_args(argv)
    spots = [c for c in config.SPOTS if not args.only or c["slug"] == args.only]
    if not spots:
        print("no break with slug %r" % args.only, file=sys.stderr)
        return 2
    sites = build(spots)
    for slug, s in sites.items():
        print("%-18s %s  %.2f km away" % (slug, s["site"], s["km"]))
    if args.only:
        return 0
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"sites": sites}, f, indent=1, sort_keys=True)
        f.write("\n")
    print("wrote %s (%d breaks)" % (args.out, len(sites)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
