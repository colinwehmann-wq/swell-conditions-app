"""Plain-language helpers shared by the notifications and the website.

Pure functions only: numbers in, human wording out. No I/O.
"""
from . import evaluate

_COMPASS_16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
               "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]

RATING_WORD = {"green": "GOOD", "yellow": "OKAY", "red": "POOR"}


def compass(deg):
    if deg is None:
        return "?"
    return _COMPASS_16[int((deg % 360) / 22.5 + 0.5) % 16]


def rating(score):
    """0-100 internal score -> 1.0-10.0 surf rating."""
    return max(1.0, min(10.0, round(score / 10.0, 1)))


def rating_band(r):
    """red < 5, yellow 5-7.5, green > 7.5."""
    if r < 5.0:
        return "red"
    if r <= 7.5:
        return "yellow"
    return "green"


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
