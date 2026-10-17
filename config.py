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

import json
import os

TIMEZONE = "America/Los_Angeles"

# Local wall-clock times the checker runs. Used only to answer "is a good window
# coming before the next check?" — it doesn't have to line up exactly with the
# GitHub Actions cron, a rough picture of the gaps is enough.
CHECK_TIMES = ["05:00", "06:00", "07:00", "10:30", "15:00", "16:00"]

# Days of forecast to pull. One more than the 7-day outlook shows, so there are still
# seven full days to show when today has already gone dark.
FORECAST_DAYS = 8
OUTLOOK_DAYS = 7

# --- public website + opt-in notifications ----------------------------------------
# Visitors subscribe to a public ntfy topic per spot. ntfy topics are not
# password-protected, so anyone who knows the name can read *and post* — the random
# suffix just keeps names from colliding with other people's topics.
SITE_URL = "https://colinwehmann-wq.github.io/swell-conditions-app"
# Where the profile service (worker/) lives. The address is public; reading every profile needs a key.
PROFILES_API = "https://swell-profiles.swellcheck.workers.dev"
PUBLIC_TOPIC_BASE = "swellcheck-nc"
PUBLIC_TOPIC_SUFFIX = "ed10f8"


def public_topic(slug):
    """Public ntfy topic for a spot slug (or "daily" for the morning digest)."""
    return "%s-%s-%s" % (PUBLIC_TOPIC_BASE, slug, PUBLIC_TOPIC_SUFFIX)

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
    "alert_score_min":  70,

    # NOAA CO-OPS tide station (9410230 = La Jolla; tide is ~identical up the
    # North County coast, offsets of only a couple of minutes).
    "tide_station":     "9410230",

    # NDBC buoys, best first. The evaluator uses the first one returning fresh data.
    "buoys":            ["46224"],   # Oceanside Offshore

    # "mine" = one of the owner's own breaks: only these send to the private phone topic and
    # appear in the private digest. Every break still gets its own public opt-in topic.
    "mine":             False,

    # Other names people search by ("15th street", "swamis"). Lower-case, no punctuation needed.
    "aliases":          [],
}

# How many breaks the home page shows, ranked best-first across the whole county.
HOME_COUNT = 5

# Offshore buoys, one per stretch of coast. Nearshore buoys (Leucadia, Del Mar, Scripps...) read
# lower and from a different angle because the swell has already bent on its way in, and the
# thresholds in DEFAULTS assume an offshore reading, so they are deliberately not used.
BUOY_NORTH = ["46224", "46225"]      # Oceanside Offshore, then Torrey Pines Outer
BUOY_CENTRAL = ["46225", "46224"]    # Torrey Pines Outer (Encinitas to La Jolla)
BUOY_SOUTH = ["46258", "46225"]      # Mission Bay West (Pacific Beach to Point Loma)
BUOY_BORDER = ["46232", "46258"]     # Point Loma South (Coronado to the border)

SPOTS = [
    {
        "name": "Swami's",
        "slug": "swamis",
        "mine": True,
        "aliases": ["swamis", "swami", "self realization"],
        "area": "Encinitas",
        "lat": 33.0361, "lon": -117.2925,
        "buoys": ["46224", "46225"],
        "swell_dir_deg": [190, 315],
        "tide_ideal_ft": [2.5, 5.0],     # reef holds shape better on the push
        "tide_ok_ft":    [1.0, 6.0],
        "notes": "Long reef point. W-NW has more wall; S/SW is softer. Offshore = E.",
    },
    {
        "name": "Grandview",
        "slug": "grandview",
        "mine": True,
        "aliases": ["grandview surf beach"],
        "area": "Leucadia",
        "lat": 33.0581, "lon": -117.3012,
        "buoys": ["46224", "46225"],
        "swell_dir_deg": [195, 315],
        "tide_ideal_ft": [1.5, 3.5],
        "notes": "Reefy peak. Likes a moderate tide; gets shifty when overhead.",
    },
    {
        "name": "Beacon's",
        "slug": "beacons",
        "mine": True,
        "aliases": ["beacons", "beacon"],
        "area": "Leucadia",
        "lat": 33.0518, "lon": -117.2991,
        "buoys": ["46224", "46225"],
        "swell_dir_deg": [195, 315],
        "tide_ideal_ft": [1.5, 4.0],
        "notes": "Sand bottom, fairly tide-tolerant. Wraps in NW well.",
    },
    {
        "name": "Blacks",
        "slug": "blacks",
        "mine": True,
        "aliases": ["black's", "blacks beach", "torrey pines glider port"],
        "area": "La Jolla",
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
        "slug": "oceanside",
        "mine": True,
        "aliases": ["oside", "harbor", "oceanside harbor"],
        "area": "Oceanside",
        "lat": 33.2049, "lon": -117.3936,
        "buoys": ["46224"],
        "swell_dir_deg": [200, 290],     # jetty favors more W in the swell
        "tide_ideal_ft": [0.5, 3.0],
        "tide_ok_ft":    [-0.5, 4.5],
        "notes": "South-jetty sandbar. Jetty shades some NW wind and swell. Lower tide.",
    },

    # ---- the rest of the county, north to south --------------------------------------------
    # Coordinates are the beach (OpenStreetMap) so the forecast is for the right stretch of
    # coast; the wave model's grid is 8-25 km, so a few hundred metres never changes the answer.
    # Anything not overridden below takes DEFAULTS. These are starting points, not gospel:
    # tune height / tide / swell window here as you learn each break.
    {
        "name": "Oceanside Pier", "slug": "oceanside-pier", "area": "Oceanside",
        "aliases": ["oside pier", "oceanside city beach"],
        "lat": 33.1942, "lon": -117.3846, "buoys": BUOY_NORTH,
        "swell_dir_deg": [200, 300],
        "tide_ideal_ft": [0.5, 3.0], "tide_ok_ft": [-0.5, 4.5],
        "notes": "Sandbars either side of the pier. Works best on lower tides and a clean W–SW swell.",
    },
    {
        "name": "Buccaneer Beach", "slug": "buccaneer", "area": "Oceanside",
        "aliases": ["buc", "south oceanside"],
        "lat": 33.1814, "lon": -117.3733, "buoys": BUOY_NORTH,
        "swell_dir_deg": [195, 300],
        "tide_ideal_ft": [0.5, 3.0], "tide_ok_ft": [-0.5, 4.5],
        "notes": "Beach break south of the harbor. Picks up south and southwest swell well.",
    },
    {
        "name": "Tamarack", "slug": "tamarack", "area": "Carlsbad",
        "aliases": ["tamarack beach", "carlsbad"],
        "lat": 33.1507, "lon": -117.3483, "buoys": BUOY_NORTH,
        "swell_dir_deg": [190, 310],
        "tide_ideal_ft": [1.0, 3.5],
        "notes": "Carlsbad beach break. Sandbars shift, so it's best on a mid tide with a moderate swell.",
    },
    {
        "name": "Ponto", "slug": "ponto", "area": "Carlsbad",
        "aliases": ["south ponto", "south carlsbad", "ponto jetty"],
        "lat": 33.0844, "lon": -117.3123, "buoys": BUOY_NORTH,
        "swell_dir_deg": [195, 310],
        "notes": "South Carlsbad beach break. Likes south-leaning swell and a mid tide.",
    },
    {
        "name": "Moonlight Beach", "slug": "moonlight", "area": "Encinitas",
        "aliases": ["moonlight", "d street"],
        "lat": 33.0483, "lon": -117.2951, "buoys": BUOY_CENTRAL,
        "height_ideal_ft": [2.5, 5.5],
        "notes": "Mellow beach break that handles small swell. Popular with longboards and beginners.",
    },
    {
        "name": "D Street", "slug": "d-street", "area": "Encinitas",
        "aliases": ["d st", "boneyard", "boneyards"],
        "lat": 33.0456, "lon": -117.2974, "buoys": BUOY_CENTRAL,
        "swell_dir_deg": [195, 310],
        "notes": "Sand and reef just south of Moonlight. Works on a mid tide; busy on good days.",
    },
    {
        "name": "Cardiff Reef", "slug": "cardiff", "area": "Cardiff",
        "aliases": ["cardiff", "cardiff by the sea", "seaside", "seaside reef"],
        "lat": 33.0105, "lon": -117.2796, "buoys": BUOY_CENTRAL,
        "swell_dir_deg": [200, 310],
        "tide_ideal_ft": [2.0, 4.5], "tide_ok_ft": [1.0, 5.5],
        "notes": "Reef that wants a clean swell and a mid-to-high tide. Crowded when it's on.",
    },
    {
        "name": "Fletcher Cove", "slug": "fletcher-cove", "area": "Solana Beach",
        "aliases": ["fletchers", "tabletops", "solana beach", "solana"],
        "lat": 32.9914, "lon": -117.2739, "buoys": BUOY_CENTRAL,
        "swell_dir_deg": [200, 310],
        "notes": "Reef and sand around Fletcher Cove and Tabletops. Best on a mid tide.",
    },
    {
        "name": "Del Mar", "slug": "del-mar", "area": "Del Mar",
        "aliases": ["15th street", "dog beach", "del mar dog beach"],
        "lat": 32.9735, "lon": -117.2699, "buoys": BUOY_CENTRAL,
        "swell_dir_deg": [200, 315],
        "tide_ideal_ft": [0.5, 3.5], "tide_ok_ft": [-0.5, 5.0],
        "notes": "Beach break up and down the Del Mar shore. Lower to mid tide.",
    },
    {
        "name": "Torrey Pines", "slug": "torrey-pines", "area": "Torrey Pines",
        "aliases": ["torrey pines state beach", "torrey pines state reserve", "flat rock"],
        "lat": 32.9314, "lon": -117.2621, "buoys": BUOY_CENTRAL,
        "swell_dir_deg": [220, 320],
        "height_ideal_ft": [3.0, 6.0], "tide_ideal_ft": [0.5, 3.5], "tide_ok_ft": [-0.5, 5.0],
        "notes": "Long open beach break that likes a west-to-northwest swell. Lower to mid tide.",
    },
    {
        "name": "Scripps Pier", "slug": "scripps-pier", "area": "La Jolla",
        "aliases": ["scripps", "la jolla scripps", "the canyon"],
        "lat": 32.8667, "lon": -117.2543, "buoys": BUOY_CENTRAL,
        "swell_dir_deg": [215, 320],
        "tide_ideal_ft": [0.5, 3.5], "tide_ok_ft": [-0.5, 5.0],
        "notes": "The canyon off the pier focuses swell, so it can be bigger than the beaches around it.",
    },
    {
        "name": "La Jolla Shores", "slug": "la-jolla-shores", "area": "La Jolla",
        "aliases": ["shores", "the shores"],
        "lat": 32.8614, "lon": -117.2553, "buoys": BUOY_CENTRAL,
        "swell_dir_deg": [170, 250],
        "height_ok_ft": [1.5, 7.0], "height_ideal_ft": [2.0, 4.0],
        "period_ideal_s": 12.0,
        "notes": "Sheltered from west swell, so it only works when the swell comes from the south. Small and gentle.",
    },
    {
        "name": "Windansea", "slug": "windansea", "area": "La Jolla",
        "aliases": ["windansea beach", "wind and sea", "wind n sea"],
        "lat": 32.8315, "lon": -117.2809, "buoys": BUOY_CENTRAL,
        "swell_dir_deg": [180, 260],
        "height_ok_ft": [2.5, 12.0], "height_ideal_ft": [3.0, 6.5],
        "tide_ideal_ft": [2.0, 5.0], "tide_ok_ft": [1.0, 6.0],
        "notes": "Reef that comes alive on south and southwest swell. Better at a mid-to-high tide.",
    },
    {
        "name": "Bird Rock", "slug": "bird-rock", "area": "La Jolla",
        "aliases": ["birdrock", "bird rock reef"],
        "lat": 32.8140, "lon": -117.2745, "buoys": BUOY_CENTRAL,
        "swell_dir_deg": [200, 300],
        "tide_ideal_ft": [1.5, 4.0],
        "notes": "Rocky reef north of Tourmaline. Wants a mid tide and a clean, well-spaced swell.",
    },
    {
        "name": "Tourmaline", "slug": "tourmaline", "area": "Pacific Beach",
        "aliases": ["tourmaline surfing park", "tourmaline surf park", "law street"],
        "lat": 32.8041, "lon": -117.2615, "buoys": BUOY_SOUTH,
        "swell_dir_deg": [200, 310],
        "height_ok_ft": [1.5, 7.0], "height_ideal_ft": [2.0, 4.5],
        "tide_ideal_ft": [1.5, 4.5], "tide_ok_ft": [0.5, 5.5],
        "notes": "Long, forgiving walls that suit longboards. Handles small swell and a mid tide.",
    },
    {
        "name": "Pacific Beach", "slug": "pacific-beach", "area": "Pacific Beach",
        "aliases": ["pb", "crystal pier", "garnet", "pb pier"],
        "lat": 32.7961, "lon": -117.2575, "buoys": BUOY_SOUTH,
        "swell_dir_deg": [200, 310],
        "height_ideal_ft": [2.5, 5.0], "tide_ideal_ft": [0.5, 3.5], "tide_ok_ft": [-0.5, 5.0],
        "notes": "Wide beach break around Crystal Pier. Lower to mid tide, and best with light offshore wind.",
    },
    {
        "name": "Mission Beach", "slug": "mission-beach", "area": "Mission Beach",
        "aliases": ["mb", "belmont park", "south mission"],
        "lat": 32.7826, "lon": -117.2525, "buoys": BUOY_SOUTH,
        "swell_dir_deg": [200, 310],
        "height_ideal_ft": [2.5, 5.0], "tide_ideal_ft": [0.5, 3.5], "tide_ok_ft": [-0.5, 5.0],
        "notes": "Long stretch of sand-bottom peaks. Lower to mid tide.",
    },
    {
        "name": "Ocean Beach", "slug": "ocean-beach", "area": "Ocean Beach",
        "aliases": ["ob", "ob pier", "ocean beach pier"],
        "lat": 32.7470, "lon": -117.2534, "buoys": BUOY_SOUTH,
        "swell_dir_deg": [200, 310],
        "tide_ideal_ft": [1.0, 4.5], "tide_ok_ft": [0.0, 5.5],
        "notes": "Peaks around the pier. Catches both west and south swell; gets crowded on weekends.",
    },
    {
        "name": "Sunset Cliffs", "slug": "sunset-cliffs", "area": "Point Loma",
        "aliases": ["the cliffs", "luscombes", "garbage", "pepper park", "point loma"],
        "lat": 32.7245, "lon": -117.2575, "buoys": BUOY_SOUTH,
        "swell_dir_deg": [200, 300],
        "height_ok_ft": [2.0, 14.0], "height_ideal_ft": [3.0, 7.0],
        "tide_ideal_ft": [1.5, 4.5], "tide_ok_ft": [0.5, 5.5],
        "notes": "A string of reefs below the cliffs that can handle real size. Needs experience and a mid tide.",
    },
    {
        "name": "Coronado", "slug": "coronado", "area": "Coronado",
        "aliases": ["coronado beach", "hotel del", "central beach"],
        "lat": 32.6832, "lon": -117.1880, "buoys": BUOY_BORDER,
        "swell_dir_deg": [190, 260],
        "height_ideal_ft": [2.5, 5.0], "tide_ideal_ft": [0.5, 3.5], "tide_ok_ft": [-0.5, 5.0],
        "notes": "Point Loma shelters it from northwest swell, so it works best when the swell is from the south or southwest.",
    },
    {
        "name": "Imperial Beach", "slug": "imperial-beach", "area": "Imperial Beach",
        "aliases": ["ib", "ib pier", "imperial beach pier"],
        "lat": 32.5797, "lon": -117.1350, "buoys": BUOY_BORDER,
        "swell_dir_deg": [180, 260],
        "tide_ideal_ft": [1.0, 3.5], "tide_ok_ft": [-0.5, 5.0],
        "notes": "The southernmost beach break around the pier. Does best on south swell; sheltered from the northwest.",
    },
    {
        "name": "Tijuana Sloughs", "slug": "tijuana-sloughs", "area": "Imperial Beach",
        "aliases": ["the sloughs", "sloughs", "border field", "border"],
        "lat": 32.5545, "lon": -117.1235, "buoys": BUOY_BORDER,
        "swell_dir_deg": [180, 250],
        "height_ok_ft": [2.5, 12.0], "height_ideal_ft": [3.0, 7.0],
        "tide_ideal_ft": [1.0, 3.5], "tide_ok_ft": [-0.5, 5.0],
        "notes": "Exposed sandbars at the border. Light on crowds and big on south swell.",
    },
]


_BENCHMARKS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "benchmarks.json")
_anchor_cache = {}


def _anchors():
    """{slug: anchors} from benchmarks.json (see tools/build_benchmarks.py). Missing file means
    every break falls back to the plain 0-100 score, so a fresh checkout still works."""
    if "anchors" not in _anchor_cache:
        try:
            with open(_BENCHMARKS) as f:
                data = json.load(f)
            _anchor_cache["anchors"] = {slug: b["anchors"] for slug, b in data["breaks"].items()}
            _anchor_cache["benchmarks"] = {slug: {"typical": b["typical"], "days_per_year": b["days_per_year"],
                                                  "history": b["history"]} for slug, b in data["breaks"].items()}
        except (OSError, ValueError, KeyError):
            _anchor_cache["anchors"] = {}
            _anchor_cache["benchmarks"] = {}
    return _anchor_cache["anchors"]


def spot_config(spot):
    """Merge a SPOTS entry over DEFAULTS and attach its public ntfy topic."""
    cfg = dict(DEFAULTS)
    cfg.update(spot)
    anchors = _anchors().get(cfg["slug"])
    if anchors:
        cfg["rating_anchors"] = anchors
        cfg["benchmark"] = _anchor_cache["benchmarks"][cfg["slug"]]
    cfg["ntfy_topic"] = public_topic(cfg["slug"])
    return cfg
