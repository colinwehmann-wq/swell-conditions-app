"""A break's own history, and what the rating scale is measured against.

A "10" should mean the same thing at every break: the best that break gets. There are no free
surf-quality records to learn that from, but there are 12+ years of NOAA buoy, wind and tide
records. So for each break we replay that history through the break's own idea of ideal (its
size band, swell window, tide and wind) to get a raw score for every daylight hour, keep each
day's best, and rank today's conditions against those days. The raw scores at fixed percentiles
(`evaluate.RATING_PERCENTILES`) are the break's *anchors*; between two anchors the rating is
interpolated. We also record what the days at the top actually looked like: that is the break's
benchmark: the conditions a 7 or a 9 has meant there.

Everything here is pure: parsed series in, numbers out. `tools/build_benchmarks.py` does the
downloading and writes `benchmarks.json`, which `config.spot_config` merges into each break.

The history is from a buoy, not from the break, so heights are the buoy's *swell* height (the
same quantity the live scoring uses), estimated from the standard record's total wave height.
"""
import datetime
import hashlib
import json
import math

from . import evaluate

M_TO_FT = 3.28084

# Swell height as a share of total wave height, by dominant period. Measured by pairing the
# buoys' standard record with their own swell/wind-wave split (.spec) over 45 days at all four
# offshore buoys: consistently ~0.70 for long-period swell, lower for short-period seas.
SWELL_FRACTION = ((9.0, 0.45), (12.0, 0.62), (None, 0.70))

# The config keys the score reads. If any changes, the break's anchors are out of date.
SCORING_KEYS = ("height_ok_ft", "height_ideal_ft", "period_min_s", "period_ideal_s", "swell_dir_deg",
                "offshore_dir_deg", "wind_ideal_kn", "wind_max_kn", "tide_ok_ft", "tide_ideal_ft", "buoys")

# Report days per year at these ratings, and describe the typical day at these.
REPORT_RATINGS = (5, 6, 7, 8, 9, 10)
TYPICAL_RATINGS = (7, 9)


def swell_fraction(period_s):
    for limit, share in SWELL_FRACTION:
        if limit is None or period_s < limit:
            return share


def signature(cfg):
    """Fingerprint of everything the anchors depend on: the scoring maths, the break's settings
    and how the history is read. benchmarks.json stores it; a test compares."""
    payload = {
        "version": evaluate.SCORING_VERSION,
        "weights": evaluate.WEIGHTS,
        "peak": [evaluate.PEAK_PERIOD_EXTRA_S, evaluate.PEAK_PERIOD_CAP_S, evaluate.PEAK_PERIOD_SHARE,
                 evaluate.SIZE_PEAK_WEIGHT, evaluate.TIDE_PEAK_WEIGHT, evaluate.DIR_PEAK_WEIGHT],
        "percentiles": evaluate.RATING_PERCENTILES,
        "fraction": SWELL_FRACTION,
        "break": {k: cfg[k] for k in SCORING_KEYS},
    }
    return hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]


# ------------------------------------------------------------------------------------ history

def daylight_hours(waves, wind, tide_height, sun):
    """Every daylight hour for which waves, wind and tide are all known, as
    (date, hour, swell_ft, period_s, direction, wind_kn, wind_dir, tide_ft).

    waves {hour datetime: (total Hs m, dominant period s, mean direction deg)}; wind {hour datetime:
    (kn, deg)}; tide_height(datetime) -> ft or None; sun {date: (sunrise, sunset)} as datetimes.
    Daylight runs from the hour of sunrise to the hour the light runs out (`evaluate.last_row_start`):
    the same rule the live scoring uses, so the history and the live rating cover the same hours.
    """
    for day, (rise, set_) in sorted(sun.items()):
        if not rise or not set_:
            continue
        t = rise.replace(minute=0, second=0, microsecond=0)
        last = evaluate.last_row_start(set_)
        while t <= last:
            w, wk = waves.get(t), wind.get(t)
            tide = tide_height(t) if w and wk else None
            if w and wk and tide is not None:
                hs, period, direction = w
                yield (day, t.hour, hs * swell_fraction(period) * M_TO_FT, period, direction, wk[0], wk[1], tide)
            t += datetime.timedelta(hours=1)


def daily_best(hours, cfg):
    """{date: (best raw score that day, the conditions at that hour)}."""
    best = {}
    for day, hour, h, p, d, wk, wd, tide in hours:
        raw, _ = evaluate.raw_score(h, p, d, wk, wd, tide, cfg)
        if day not in best or raw > best[day][0]:
            best[day] = (raw, (h, p, d, wk, wd, tide, hour))
    return best


# ----------------------------------------------------------------------------------- anchors

def quantile(sorted_values, pct):
    """Linear-interpolated percentile (0-100) of an already sorted list."""
    if not sorted_values:
        raise ValueError("no values")
    pos = (len(sorted_values) - 1) * pct / 100.0
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def anchors(raw_scores):
    """The raw scores at RATING_PERCENTILES, strictly ascending (equal neighbours are nudged apart
    so the interpolation in `evaluate.to_rating_score` never divides by zero)."""
    vals = sorted(raw_scores)
    out = [round(quantile(vals, p), 3) for p in evaluate.RATING_PERCENTILES]
    for i in range(1, len(out)):
        if out[i] <= out[i - 1]:
            out[i] = round(out[i - 1] + 0.001, 3)
    return out


# ------------------------------------------------------------------------------- the benchmark

def _circular_mean(degrees):
    x = sum(math.sin(math.radians(d)) for d in degrees)
    y = sum(math.cos(math.radians(d)) for d in degrees)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def _median(values):
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def typical_day(days_at_or_above):
    """Median conditions at each day's best hour: what that rating has looked like here."""
    conds = [c for _raw, c in days_at_or_above]
    return {
        "days": len(conds),
        "size_ft": round(_median([c[0] for c in conds]), 1),
        "period_s": round(_median([c[1] for c in conds]), 1),
        "swell_dir_deg": round(_circular_mean([c[2] for c in conds])),
        "wind_kn": round(_median([c[3] for c in conds])),
        "tide_ft": round(_median([c[5] for c in conds]), 1),
        "hour": round(_median([c[6] for c in conds])),
    }


def build(hours, cfg):
    """Everything benchmarks.json holds for one break, from its hourly history."""
    daily = daily_best(hours, cfg)
    if len(daily) < 365:
        raise ValueError("%s: only %d days of history; need at least a year" % (cfg.get("name"), len(daily)))
    raws = [raw for raw, _ in daily.values()]
    ancs = anchors(raws)
    years = len(daily) / 365.25
    rated = [(evaluate.to_rating_score(raw, ancs) / 10.0, raw, c) for raw, c in daily.values()]
    per_year = {str(r): round(sum(1 for x in rated if x[0] >= r) / years, 1) for r in REPORT_RATINGS}
    typical = {}
    for r in TYPICAL_RATINGS:
        top = [(raw, c) for rating, raw, c in rated if rating >= r]
        if top:
            typical[str(r)] = typical_day(top)
    dates = sorted(daily)
    return {
        "signature": signature(cfg),
        "anchors": ancs,
        "history": {"first": str(dates[0]), "last": str(dates[-1]), "days": len(daily), "buoy": cfg["buoys"][0]},
        "days_per_year": per_year,
        "typical": typical,
    }
