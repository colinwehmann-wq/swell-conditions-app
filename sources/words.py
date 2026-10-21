"""Plain-language helpers shared by the notifications and the website.

Pure functions only: numbers in, human wording out. No I/O.
"""
from . import evaluate

_COMPASS_16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
               "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]

# The 1-10 scale, best first: (lowest rating in the step, name). Colour only ever groups the
# eight steps into four tiers (green 7+, yellow 5-6.9, orange 3-4.9, red below 3); it is never
# the only signal, because every step has a name and a number.
RATING_STEPS = [
    (9.0, "Epic"), (8.0, "Excellent"), (7.0, "Good"), (6.0, "Decent"),
    (5.0, "Fair"), (4.0, "Mediocre"), (3.0, "Poor"), (0.0, "Very poor"),
]


def compass(deg):
    if deg is None:
        return "?"
    return _COMPASS_16[int((deg % 360) / 22.5 + 0.5) % 16]


def rating(score):
    """0-100 internal score -> 1.0-10.0 surf rating."""
    return max(1.0, min(10.0, round(score / 10.0, 1)))


def rating_label(r):
    """Name of the step a 1.0-10.0 rating falls in: Epic, Excellent, Good, Decent, Fair, Mediocre,
    Poor or Very poor."""
    for floor, name in RATING_STEPS:
        if r >= floor:
            return name


def rating_band(r):
    """Colour tier: green 7+ (worth the trip), yellow 5-6.9 (marginal), orange 3-4.9 (weak),
    red below 3 (not worth paddling out)."""
    if r >= 7.0:
        return "green"
    if r >= 5.0:
        return "yellow"
    if r >= 3.0:
        return "orange"
    return "red"


# What to wear, by water temperature in °F. San Diego's water runs about 58 to 74, so most of these get used in a year.
WETSUIT_STEPS = [
    (72.0, "Boardshorts", "Warm: trunks, maybe a rash guard"),
    (68.0, "Spring suit", "Mild: a short-sleeve spring suit or a 2 mm"),
    (64.0, "3/2 wetsuit", "Cool: a 3/2 full wetsuit"),
    (60.0, "4/3 wetsuit", "Cold: a 4/3 full wetsuit, boots in the morning"),
    (55.0, "4/3 plus boots", "Cold: a 4/3 with boots, and a hood if you run cold"),
    (-99.0, "5/4 hooded", "Very cold: a 5/4 with hood, boots and gloves"),
]


def wetsuit(temp_f):
    """{"label", "hint"} for a water temperature in °F, or None if it is unknown."""
    if temp_f is None:
        return None
    for floor, label, hint in WETSUIT_STEPS:
        if temp_f >= floor:
            return {"label": label, "hint": hint}


def size_words(ft):
    if ft is None:
        return "size unknown"
    if ft < 1.5:
        return "tiny (ankle-high)"
    if ft < 2.5:
        return "small (knee-high)"
    if ft < 3.5:
        return "waist-high"
    if ft < 4.5:
        return "chest-high"
    if ft < 5.5:
        return "shoulder- to head-high"
    if ft < 7:
        return "head-high and bigger"
    if ft < 9:
        return "overhead"
    return "well overhead — big"


def power_words(period_s):
    if period_s is None:
        return ""
    if period_s < 8:
        return "weak, wind-choppy swell"
    if period_s < 10:
        return "average swell"
    if period_s < 13:
        return "solid, lined-up swell"
    return "powerful long-period swell"


def wind_words(wk, wd, cfg):
    if wk is None:
        return "wind unknown"
    rel = evaluate.wind_relation(wd, cfg)
    if wk < 4:
        return "no wind — glassy and clean"
    if rel == "offshore":
        return "offshore wind — grooming the waves clean"
    if wk < 8:
        return "light wind — mostly clean" if rel == "cross" else "light wind — slightly bumpy"
    if wk < 13:
        return "breezy — bumpy and choppy"
    return "windy — choppy and messy"


def tide_words(tf, state=None):
    if tf is None:
        return "tide unknown"
    level = "Low" if tf < 2.0 else "Medium" if tf < 4.0 else "High"
    move = {"rising": "coming in", "falling": "going out"}.get(state)
    return "%s tide, %s" % (level, move) if move else "%s tide" % level
