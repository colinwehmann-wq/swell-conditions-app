"""
Surf-check configuration.

Edit SPOTS to add/remove breaks or tune what "ideal" means for each one.
  - Heights are in FEET, periods in SECONDS.
  - Directions are COMPASS DEGREES the swell/wind comes FROM
    (0 = N, 90 = E, 180 = S, 270 = W).
  - A direction window [lo, hi] is an arc and may wrap past 360
    (e.g. [340, 20] spans NNW through N to NNE).

Any key in DEFAULTS can be overridden per spot.
"""

TIMEZONE = "America/Los_Angeles"

# Local wall-clock times the checker runs. Used only to answer "is a good window
# coming before the next check?" — it doesn't have to line up exactly with the
# GitHub Actions cron, a rough picture of the gaps is enough.
CHECK_TIMES = ["05:00", "06:00", "07:00", "10:30", "15:00", "16:00"]

DEFAULTS = {
    # Significant wave height (ft). Outside `ok` = no-go; inside `ideal` = full marks.
    "height_ok_ft":     [2.5, 9.0],
    "height_ideal_ft":  [3.5, 6.5],

    # Primary swell period (s).
    "period_min_s":     8.0,
    "period_ideal_s":   13.0,

    # Swell direction arc the break actually receives.
    "swell_dir_deg":    [190, 315],

    # Wind. Coming FROM `offshore_dir_deg` grooms the face regardless of speed.
    # Otherwise light is best; at/above `wind_max_kn` it's blown out.
    "offshore_dir_deg": [40, 110],   # E / NE
    "wind_ideal_kn":    6.0,
    "wind_max_kn":      12.0,

    # Tide (ft, MLLW). `ok` = surfable, `ideal` = prime.
    "tide_ok_ft":       [0.5, 5.0],
    "tide_ideal_ft":    [1.5, 4.0],

    # Score 0-100 at/above which the spot is a GO and worth a push.
    "alert_score_min":  66,

    # NOAA CO-OPS tide station (9410230 = La Jolla; tide is ~identical up the
    # North County coast, offsets of only a couple of minutes).
    "tide_station":     "9410230",

    # NDBC buoys, best first. The evaluator uses the first one returning fresh data.
    "buoys":            ["46224"],   # Oceanside Offshore
}

SPOTS = [
    {
        "name": "Swami's",
        "lat": 33.0361, "lon": -117.2925,
        "buoys": ["46224", "46225"],
        "swell_dir_deg": [190, 315],
        "tide_ideal_ft": [2.5, 5.0],     # reef holds shape better on the push
        "tide_ok_ft":    [1.0, 6.0],
        "notes": "Long reef point. W-NW has more wall; S/SW is softer. Offshore = E.",
    },
    {
        "name": "Grandview",
        "lat": 33.0581, "lon": -117.3012,
        "buoys": ["46224", "46225"],
        "swell_dir_deg": [195, 315],
        "tide_ideal_ft": [1.5, 3.5],
        "notes": "Reefy peak. Likes a moderate tide; gets shifty when overhead.",
    },
    {
        "name": "Beacon's",
        "lat": 33.0518, "lon": -117.2991,
        "buoys": ["46224", "46225"],
        "swell_dir_deg": [195, 315],
        "tide_ideal_ft": [1.5, 4.0],
        "notes": "Sand bottom, fairly tide-tolerant. Wraps in NW well.",
    },
    {
        "name": "Blacks",
        "lat": 32.8887, "lon": -117.2523,
        "buoys": ["46225", "46224"],
        "swell_dir_deg": [180, 320],     # canyon focuses nearly everything
        "tide_ideal_ft": [1.0, 3.0],
        "tide_ok_ft":    [-0.5, 4.5],
        "period_ideal_s": 14.0,
        "notes": "Submarine canyon. Bigger and better on long-period W/NW. Lower tide.",
    },
    {
        "name": "Oceanside Harbor",
        "lat": 33.2049, "lon": -117.3936,
        "buoys": ["46224"],
        "swell_dir_deg": [200, 290],     # jetty favors more W in the swell
        "tide_ideal_ft": [0.5, 3.0],
        "tide_ok_ft":    [-0.5, 4.5],
        "notes": "South-jetty sandbar. Jetty shades some NW wind and swell. Lower tide.",
    },
]


def spot_config(spot):
    """Merge a SPOTS entry over DEFAULTS."""
    cfg = dict(DEFAULTS)
    cfg.update(spot)
    return cfg
