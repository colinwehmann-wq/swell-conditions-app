"""Which board to bring: a transparent rule-of-thumb, not a black box.

Inputs are the same numbers the rest of the app uses (swell height in feet,
period in seconds, wind). The first matching rule wins, and every result carries a
one-line reason so the site can show its work.
"""

LONGBOARD = "longboard"
FISH = "fish"
SHORTBOARD = "shortboard"
PERFORMANCE = "performance"

LABELS = {
    LONGBOARD: "Longboard",
    FISH: "Fish",
    SHORTBOARD: "Shortboard",
    PERFORMANCE: "Performance board",
}


def _pick(key, why):
    return {"key": key, "label": LABELS[key], "why": why}


def recommend(height_ft, period_s, wind_kn=None, wind_rel=None):
    """Return {"key", "label", "why"} for the given conditions, or None if the
    size or period is unknown.

    "Clean" means the face should be tidy: light wind, or any offshore wind.
    """
    if height_ft is None or period_s is None:
        return None

    clean = wind_kn is None or wind_kn < 8 or wind_rel == "offshore"

    if height_ft < 2.5:
        return _pick(LONGBOARD, "Small waves: you want paddle power and glide to catch them.")
    if period_s < 8:
        if height_ft < 3.5:
            return _pick(LONGBOARD, "Short-period, mushy swell: volume and length keep you moving.")
        return _pick(FISH, "Short-period swell with some size: a wide, forgiving fish handles the mush.")
    if height_ft < 3.5:
        if period_s >= 13 and clean:
            return _pick(SHORTBOARD, "Small but long-period and clean: these waves have more punch than they look.")
        return _pick(FISH, "Waist-high and soft: a fish holds speed through the flat sections.")
    if height_ft >= 6:
        return _pick(PERFORMANCE, "Overhead and powerful: bring a refined board you trust, and consider a step-up.")
    if height_ft >= 4 and period_s >= 12 and clean:
        return _pick(PERFORMANCE, "Chest-high-plus, long-period and clean: the kind of wave a performance board rewards.")
    if period_s < 10 or not clean:
        if height_ft < 4.5:
            return _pick(FISH, "Bumpy or middling swell: a fish stays loose and forgiving.")
        return _pick(SHORTBOARD, "Some size but not much polish: a standard shortboard is the safe all-rounder.")
    return _pick(SHORTBOARD, "Solid, workable waves: a standard shortboard is the right tool.")
