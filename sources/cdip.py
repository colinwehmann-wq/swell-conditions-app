"""CDIP's MOP (Monitoring and Prediction) nearshore wave model, read over OPeNDAP with the standard library.

MOP runs a wave model along the whole Southern California coast and publishes, for a point every
~100 m in 10 m of water, the wave height, peak period and peak direction: a 3-hourly forecast about
10 days ahead and a nowcast of what the model says happened. Sites are named like "D0580" (the D
series is San Diego County, numbered south to north from the border). Free, no key; CDIP asks to be
credited. https://cdip.ucsd.edu/ and https://thredds.cdip.ucsd.edu/
"""
import datetime
import json
import os
import re

from . import http
from .timeutil import UTC

_BASE = "https://thredds.cdip.ucsd.edu/thredds/dodsC/cdip/model/MOP_alongshore"
FILL = -999.0                  # the files mark a missing value as about -999.99
GOOD_FLAG = 1                  # waveFlagPrimary: 1 = good data

KINDS = ("forecast", "nowcast")


def url(site, kind="forecast"):
    return "%s/%s_%s.nc" % (_BASE, site, kind)


def _arrays(text):
    """{name: [values as strings]} from an OPeNDAP .ascii response (a scalar comes back as a one-item list)."""
    out = {}
    lines = text.splitlines()
    try:
        i = next(n for n, ln in enumerate(lines) if ln.startswith("---")) + 1
    except StopIteration:
        return out
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
        elif re.match(r"^\w+\[", line):                    # an array: a header line, then one line of values
            name = line.split("[", 1)[0]
            out[name] = [v.strip() for v in lines[i + 1].split(",")] if i + 1 < len(lines) else []
            i += 2
        else:                                              # a scalar: "name, value"
            name, _, value = line.partition(",")
            out[name.strip()] = [value.strip()]
            i += 1
    return out


def _num(s):
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    return None if v <= FILL else v


def parse(text):
    """Rows [{"time": aware UTC datetime, "hs": m, "tp": s, "dp": degrees-from}] from a MOP .ascii response,
    keeping only readings the model flags as good."""
    a = _arrays(text)
    flags = a.get("waveFlagPrimary")
    rows = []
    for i, t in enumerate(a.get("waveTime") or []):
        try:
            when = datetime.datetime.fromtimestamp(int(float(t)), UTC)
        except ValueError:
            continue
        if flags and i < len(flags) and _num(flags[i]) not in (None, GOOD_FLAG):
            continue
        row = {"time": when}
        for key, name in (("hs", "waveHs"), ("tp", "waveTp"), ("dp", "waveDp")):
            vals = a.get(name) or []
            row[key] = _num(vals[i]) if i < len(vals) else None
        if row["hs"] is not None:
            rows.append(row)
    return rows


def fetch(site, kind="forecast", window=None):
    """MOP rows for one site, oldest first. `window` is an (index_from, index_to) pair to ask for part of
    a long file (a nowcast file holds years); omit it for the whole file."""
    if kind not in KINDS:
        raise ValueError("kind must be one of %s" % (KINDS,))
    sel = "" if window is None else "[%d:1:%d]" % window
    variables = ",".join("%s%s" % (v, sel) for v in ("waveTime", "waveHs", "waveTp", "waveDp", "waveFlagPrimary"))
    return parse(http.get("%s.ascii?%s" % (url(site, kind), variables), timeout=40))


def fetch_location(site):
    """(lat, lon, depth_m) of a site, from its forecast file."""
    text = http.get("%s.ascii?metaLatitude,metaLongitude,metaWaterDepth" % url(site), timeout=30, tries=2)
    a = _arrays(text)
    return float(a["metaLatitude"][0]), float(a["metaLongitude"][0]), float(a["metaWaterDepth"][0])


def count(site, kind="nowcast"):
    """How many time steps a site's file holds."""
    m = re.search(r"waveTime = (\d+)", http.get(url(site, kind) + ".dds", timeout=30, tries=2))
    return int(m.group(1)) if m else 0


def fetch_recent(site, n, kind="nowcast"):
    """The newest `n` rows of a (long) file."""
    total = count(site, kind)
    return fetch(site, kind, window=(max(0, total - n), total - 1)) if total else []


SITES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mop_sites.json")


def load_sites(path=SITES_PATH):
    """{break slug: {"site": "D0580", "lat", "lon", "km"}}: each break's nearest MOP point, written by
    tools/build_mop_sites.py. Empty when the file is missing, so everything that uses it just does nothing."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("sites", {})
    except (OSError, ValueError):
        return {}
