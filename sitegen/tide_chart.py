"""The tide graph on a break's page: one day's curve, with the daylight hours shaded and the highs and lows labelled.

`build_day` turns the tide predictions (a `sources.tides.TideSeries`) into plain data that travels in the site's JSON;
`tide_svg` draws that data as a small inline SVG with no script, so it works everywhere and is read out sensibly by a
screen reader (a title and a description that spells out the highs and lows).
"""
import datetime
import math

# Drawn on a phone-sized canvas (it scales up on a wide screen), so the text is big enough to read at 375 px wide.
HEIGHT_PX = 270
WIDTH_PX = 420
PAD = {"l": 34, "r": 14, "t": 34, "b": 40}


def _floor_hour(dt):
    return dt.replace(minute=0, second=0, microsecond=0)


def build_day(series, day, sunrise, sunset, step_minutes=30):
    """One day's tide as data, or None when there are no predictions for it.

    The graph runs from the hour before sunrise to the hour after sunset, with a point every `step_minutes` and every
    high and low inside that span. Times are ISO strings in the series' own timezone.
    """
    if series is None or not getattr(series, "ext", None) or sunrise is None or sunset is None:
        return None
    start = _floor_hour(sunrise) - datetime.timedelta(hours=1)
    end = _floor_hour(sunset) + datetime.timedelta(hours=2)
    points = []
    t = start
    while t <= end:
        h = series.height(t)
        if h is not None:
            points.append([t.isoformat(), round(h, 2)])
        t += datetime.timedelta(minutes=step_minutes)
    if len(points) < 4:
        return None
    extremes = [{"time": when.isoformat(), "ft": round(ft, 1), "type": kind}
                for when, ft, kind in series.ext if start <= when <= end]
    return {"date": day.isoformat(), "start": start.isoformat(), "end": end.isoformat(),
            "sunrise": sunrise.isoformat(), "sunset": sunset.isoformat(), "points": points, "extremes": extremes}


def _t(iso):
    return datetime.datetime.fromisoformat(iso)


def _clock(dt):
    return dt.strftime("%I:%M %p").lstrip("0")


def _axis_label(dt):
    h = dt.hour % 12 or 12
    return "%d%s" % (h, "a" if dt.hour < 12 else "p")


def describe(td):
    """The highs and lows in words: 'High 4.3 ft at 11:42 AM, low 0.4 ft at 5:50 PM'."""
    parts = ["%s %.1f ft at %s" % ("High" if e["type"] == "H" else "Low", e["ft"], _clock(_t(e["time"]))) for e in td["extremes"]]
    return ", ".join(parts[:1] + [p[0].lower() + p[1:] for p in parts[1:]]) if parts else ""


def tide_svg(td, now_iso=None):
    """The graph as an SVG string. `now_iso` draws a 'Now' marker when it falls inside the day shown."""
    start, end = _t(td["start"]), _t(td["end"])
    span = (end - start).total_seconds()
    heights = [p[1] for p in td["points"]]
    lo = math.floor(min(heights + [0.0]) - 0.3)
    hi = math.ceil(max(heights) + 0.6)
    left, right = PAD["l"], WIDTH_PX - PAD["r"]
    top, bottom = PAD["t"], HEIGHT_PX - PAD["b"]

    def x(dt):
        return left + (right - left) * ((dt - start).total_seconds() / span)

    def y(ft):
        return bottom - (bottom - top) * ((ft - lo) / float(hi - lo))

    coords = [(x(_t(t)), y(h)) for t, h in td["points"]]
    line = "M" + " L".join("%.1f,%.1f" % c for c in coords)
    area = "%s L%.1f,%.1f L%.1f,%.1f Z" % (line, coords[-1][0], bottom, coords[0][0], bottom)

    out = ['<svg class="tide" viewBox="0 0 %d %d" role="img" aria-labelledby="tide-t tide-d" focusable="false">' % (WIDTH_PX, HEIGHT_PX),
           '<title id="tide-t">Tide for the day</title>',
           '<desc id="tide-d">%s.</desc>' % (describe(td) or "No highs or lows in daylight")]

    sr, ss = _t(td["sunrise"]), _t(td["sunset"])
    out.append('<rect class="tide-day" x="%.1f" y="%d" width="%.1f" height="%d"/>' % (x(sr), top, x(ss) - x(sr), bottom - top))
    out.append('<text class="tide-sun" x="%.1f" y="%d" text-anchor="start">sunrise %s</text>' % (x(sr) + 4, top - 10, _clock(sr)))
    out.append('<text class="tide-sun" x="%.1f" y="%d" text-anchor="end">sunset %s</text>' % (x(ss) - 4, top - 10, _clock(ss)))

    for ft in range(lo, hi + 1):
        out.append('<line class="tide-grid%s" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/>' % (" tide-zero" if ft == 0 else "", left, right, y(ft), y(ft)))
        out.append('<text class="tide-tick" x="%d" y="%.1f" text-anchor="end" dominant-baseline="middle">%d</text>' % (left - 8, y(ft), ft))
    out.append('<text class="tide-unit" x="%d" y="%d">ft</text>' % (4, top - 10))

    tick = _floor_hour(start)
    if tick < start:
        tick += datetime.timedelta(hours=1)
    while tick <= end:
        if tick.hour % 2 == 0:
            out.append('<text class="tide-tick" x="%.1f" y="%d" text-anchor="middle">%s</text>' % (x(tick), bottom + 22, _axis_label(tick)))
        tick += datetime.timedelta(hours=1)

    out.append('<path class="tide-area" d="%s"/>' % area)
    out.append('<path class="tide-line" d="%s"/>' % line)

    if now_iso:
        now = _t(now_iso)
        if start <= now <= end:
            out.append('<line class="tide-now" x1="%.1f" x2="%.1f" y1="%d" y2="%d"/>' % (x(now), x(now), top, bottom))
            out.append('<text class="tide-nowlabel" x="%.1f" y="%d" text-anchor="middle">now</text>' % (x(now), bottom + 20 + 14))

    for e in td["extremes"]:
        when = _t(e["time"])
        cx, cy = x(when), y(e["ft"])
        high = e["type"] == "H"
        anchor = "start" if cx < left + 44 else "end" if cx > right - 44 else "middle"
        out.append('<circle class="tide-dot" cx="%.1f" cy="%.1f" r="4"/>' % (cx, cy))
        # A high's labels sit above its dot, a low's below, so neither lands on the curve.
        value_y, time_y = (cy - 25, cy - 11) if high else (cy + 21, cy + 35)
        out.append('<text class="tide-label" x="%.1f" y="%.1f" text-anchor="%s">%.1f ft</text>' % (cx, value_y, anchor, e["ft"]))
        out.append('<text class="tide-labelsub" x="%.1f" y="%.1f" text-anchor="%s">%s</text>' % (cx, time_y, anchor, _clock(when)))
    out.append("</svg>")
    return "".join(out)
