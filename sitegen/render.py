"""HTML for the public site.

Plain string templates, no dependencies. Every value that came from data goes
through `esc`. Ratings are a *status* encoding (eight named steps in four colour tiers), so each one
ships as icon + number + label, never colour alone.
"""
import datetime
import html
import json
from urllib.parse import urlparse

from sources import words

from . import media

_CLS = {"green": "good", "yellow": "ok", "orange": "serious", "red": "poor"}
_ICO = {"green": "✓", "yellow": "!", "orange": "▼", "red": "✕"}

_BOARD_BLURBS = [
    ("Longboard", "Small or mushy waves. Paddle power and glide do the work."),
    ("Midlength", "Small to chest-high, soft but clean. Glide and easy paddling, still turns."),
    ("Fish", "Waist-high and bumpy, or short-period. Short, wide and forgiving."),
    ("Shortboard", "Solid, workable waves. The everyday all-rounder."),
    ("Performance board", "Chest-high or bigger, long-period and clean. Hollow, powerful faces."),
]

_THEME_BOOT = ("<script>(function(){try{var t=localStorage.getItem('theme');"
               "if(t==='light'||t==='dark'){document.documentElement.setAttribute('data-theme',t)}}"
               "catch(e){}})()</script>")

_FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E"
            "%3Ctext y='.9em' font-size='90'%3E%F0%9F%8C%8A%3C/text%3E%3C/svg%3E")

_NUMBER_WORDS = {3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}

_IOS = "https://apps.apple.com/us/app/ntfy/id1625396347"
_ANDROID = "https://play.google.com/store/apps/details?id=io.heckel.ntfy"


# ------------------------------------------------------------------------ helpers

def esc(v):
    return html.escape("" if v is None else str(v), quote=True)


def _dt(iso):
    return datetime.datetime.fromisoformat(iso)


def _clock(iso):
    return _dt(iso).strftime("%I:%M %p").lstrip("0")


def _hour(iso):
    return _dt(iso).strftime("%I %p").lstrip("0")


def _short_hour(iso):
    d = _dt(iso)
    return "%d%s" % (d.hour % 12 or 12, "a" if d.hour < 12 else "p")


def _f(x):
    if x is None:
        return "?"
    s = "%.1f" % x
    return s[:-2] if s.endswith(".0") else s


def _range(lo, hi):
    if lo is None or hi is None:
        return "—"
    return "%s ft" % _f(lo) if _f(lo) == _f(hi) else "%s–%s ft" % (_f(lo), _f(hi))


def chip(rating, band, label, size=""):
    return ('<span class="chip chip-%s %s"><span class="chip-ico" aria-hidden="true">%s</span>'
            '<span class="chip-num">%.1f</span><span class="chip-lbl">%s</span></span>'
            % (_CLS[band], size, _ICO[band], rating, esc(label)))


def cond_line(c):
    parts = []
    if c.get("height_ft") is not None:
        size = "%s ft" % _f(c["height_ft"])
        if c.get("period_s") is not None:
            size += " at %d s" % c["period_s"]
        if c.get("swell_dir"):
            size += " from the %s" % c["swell_dir"]
        parts.append(size)
    if c.get("wind_kn") is not None:
        wind = "%d kt %s" % (c["wind_kn"], c.get("wind_dir") or "")
        parts.append(wind.strip() + (" (glassy)" if c["wind_kn"] < 4 else ""))
    tide = c.get("words", {}).get("tide")
    if tide:
        parts.append(tide)
    return " · ".join(parts)


def window_text(spot):
    w = spot.get("window")
    if not w:
        return "No window worth it in the next day"
    return "Best %s: %s–%s, peak %s" % (w.get("day") or "today", _hour(w["start"]), _hour(w["end"]), _clock(w["peak"]))


# ------------------------------------------------------------------------ photos

def _photo_credit(p):
    return ('Photo: <a href="%s" rel="noopener">%s</a> · <a href="%s" rel="noopener">%s</a>'
            % (esc(p["source"]), esc(p["author"]), esc(p["licence"][1]), esc(p["licence"][0])))


def _hero_bg(slug, prefix, decorative=True):
    """Full-bleed photo behind a hero, plus its visible credit. Empty if there's no photo."""
    p = media.photo(slug)
    if not p:
        # No photo for this break yet: a deep-water gradient keeps the hero looking like the rest.
        return '<div class="hero-bg hero-bg-plain" aria-hidden="true"></div>', ""
    img = ('<div class="hero-bg"%s><img src="%sassets/img/%s" alt="%s" width="%d" height="%d" '
           'style="object-position:%s" decoding="async" fetchpriority="high"></div>'
           % (' aria-hidden="true"' if decorative else "", prefix, esc(p["file"]),
              "" if decorative else esc(p["alt"]), p["w"], p["h"], esc(p["pos"])))
    return img, '<p class="photo-credit">%s</p>' % _photo_credit(p)


def _thumb(slug, prefix):
    p = media.photo(slug)
    if not p:
        return ('<a class="row-photo row-photo-plain" href="%sspots/%s/" tabindex="-1" aria-hidden="true">'
                '<span>≈</span></a>' % (prefix, esc(slug)))
    file, w, h = media.tile(p)
    return ('<a class="row-photo" href="%sspots/%s/" tabindex="-1" aria-hidden="true">'
            '<img src="%sassets/img/%s" alt="" width="%d" height="%d" loading="lazy" decoding="async" '
            'style="object-position:%s"></a>'
            % (prefix, esc(slug), prefix, esc(file), w, h, esc(p["pos"])))


def _photo_credits(payload):
    items = []
    for s in payload["spots"]:
        p = media.photo(s["slug"])
        if p:
            items.append('<li><strong>%s</strong> — <a href="%s" rel="noopener">%s</a>, '
                         '<a href="%s" rel="noopener">%s</a>, cropped and resized</li>'
                         % (esc(s["name"]), esc(p["source"]), esc(p["author"]),
                            esc(p["licence"][1]), esc(p["licence"][0])))
    return "".join(items)


# ------------------------------------------------------------------------- shell

def _header(prefix):
    return (
        '<header class="top"><div class="wrap top-in">'
        '<a class="brand" href="%(p)s"><span class="brand-mark" aria-hidden="true">≈</span>Swell Check</a>'
        '<nav class="nav" id="nav" aria-label="Primary">'
        '<a href="%(p)s#now">Now</a><a href="%(p)smap/">Map</a><a href="%(p)sbreaks/">All breaks</a><a href="%(p)s#week">Week</a>'
        '<a href="%(p)s#alerts">Alerts</a><a href="%(p)s#how">How it works</a></nav>'
        '<a class="top-cta" href="%(p)sprofile/">My alerts</a>'
        '<button class="menu" type="button" aria-label="Menu" aria-expanded="false" aria-controls="nav" data-menu hidden>'
        '<span aria-hidden="true">☰</span></button>'
        '<button class="theme" type="button" aria-label="Switch colour theme" data-theme-toggle>'
        '<span aria-hidden="true">◐</span></button>'
        '</div></header>' % {"p": prefix or "./"}
    )


def _footer(payload):
    s = payload["sources"]
    return (
        '<footer class="foot"><div class="wrap">'
        '<div class="foot-grid">'
        '<div><h2 class="foot-h">Data</h2><ul class="plain">'
        '<li>%s</li><li>%s</li><li>%s</li>'
        '<li>Maps: imagery and map data from <a href="https://www.usgs.gov/programs/national-geospatial-program/national-map" '
        'rel="noopener">USGS The National Map</a>, drawn with <a href="https://leafletjs.com" rel="noopener">Leaflet</a></li></ul></div>'
        '<div><h2 class="foot-h">About</h2>'
        '<p>An open-source project. The scoring, the tests and the roadmap are all in the '
        '<a href="%s">repository</a>. The raw numbers behind every page are in '
        '<a href="%sdata/latest.json">latest.json</a>.</p></div>'
        '<div><h2 class="foot-h">Please note</h2>'
        '<p>Informational only. Forecasts are wrong, buoys go offline, and the ocean is dangerous — '
        'check conditions yourself and surf within your ability.</p></div>'
        '</div><div class="foot-credits"><h2 class="foot-h">Photos</h2>'
        '<p>From Wikimedia Commons, used under Creative Commons licences.</p><ul class="plain">%s</ul></div>'
        '</div></footer>'
        % (esc(s["waves"]), esc(s["tides"]), esc(s["forecast"]), esc(payload["repo_url"]),
           esc(payload["site_url"].rstrip("/") + "/"), _photo_credits(payload))
    )


def _sheet(html):
    """Everything under a photo hero. The hero stays put behind it and this slides up over the
    photo (see .curtain / .sheet in style.css); on a page with no photo it is just a wrapper."""
    return '<div class="sheet">%s</div>' % html


def _json_for_script(obj):
    """JSON safe to place inside a <script> element: nothing in it can close the tag or open a comment."""
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    for raw, safe in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"),
                      (" ", "\\u2028"), (" ", "\\u2029")):
        text = text.replace(raw, safe)
    return text


def _og_image(payload, slug):
    p = media.photo(slug)
    if not p:
        return ""
    url = "%s/assets/img/%s" % (payload["site_url"].rstrip("/"), p["file"])
    return '<meta property="og:image" content="%s"><meta name="twitter:card" content="summary_large_image">' % esc(url)


def _shell(title, description, body, prefix, payload, extra_class="", og_slug=None, scripts=(), styles=()):
    return (
        '<!doctype html><html lang="en"><head>'
        '<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>%s</title><meta name="description" content="%s">'
        '<meta name="theme-color" content="#f9f9f7" media="(prefers-color-scheme: light)">'
        '<meta name="theme-color" content="#0d0d0d" media="(prefers-color-scheme: dark)">'
        '<meta property="og:title" content="%s"><meta property="og:description" content="%s">'
        '<meta property="og:type" content="website">%s'
        '<link rel="icon" href="%s">%s'
        '%s<link rel="stylesheet" href="%sassets/style.css"></head>'
        '<body class="%s"><a class="skip" href="#main">Skip to content</a>%s'
        '<main id="main">%s</main>%s'
        '<div id="tip" class="tip" role="tooltip" hidden></div>'
        '%s<script src="%sassets/site.js" defer></script></body></html>'
        % (esc(title), esc(description), esc(title), esc(description), _og_image(payload, og_slug), _FAVICON, _THEME_BOOT,
           "".join('<link rel="stylesheet" href="%sassets/%s">' % (prefix, esc(s)) for s in styles), prefix, esc(extra_class), _header(prefix), body, _footer(payload),
           "".join('<script src="%sassets/%s" defer></script>' % (prefix, esc(s)) for s in scripts), prefix)
    )


# --------------------------------------------------------------------- components

def subscribe_buttons(name, ntfy, label=None):
    return (
        '<div class="subs" role="group" aria-label="Subscribe to %(n)s alerts">'
        '<a class="btn btn-primary" href="%(app)s">%(l)s</a>'
        '<a class="btn" href="%(web)s" rel="noopener" target="_blank">Subscribe on the web</a>'
        '<button class="btn btn-ghost" type="button" data-copy="%(t)s">Copy topic</button></div>'
        % {"n": esc(name), "app": esc(ntfy["app_url"]), "web": esc(ntfy["web_url"]),
           "t": esc(ntfy["topic"]), "l": esc(label or "Open in ntfy app")}
    )


def _place(spot):
    """The line under a break's name. Where the area is the same word as the name (Pacific Beach
    in Pacific Beach) it says nothing, so name the county instead."""
    area = spot["area"]
    return "San Diego County" if area.strip().lower() == spot["name"].strip().lower() else area


def _finder_form():
    """The break search box. Hidden until the script runs, since it can't work without it; the
    pages that carry it also link to the full directory, which does."""
    return (
        '<form class="finder" role="search" data-finder hidden>'
        '<label class="sr" for="finder-q">Find a break</label>'
        '<input id="finder-q" class="finder-input" type="search" name="q" autocomplete="off" '
        'spellcheck="false" placeholder="Find a break: try Windansea, PB or Swami\'s" '
        'role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="finder-results">'
        '<ul id="finder-results" class="finder-results" role="listbox" hidden></ul>'
        '<p class="sr" role="status" data-finder-status></p>'
        '</form>'
    )


def _spot_row(spot):
    c = spot["now"]
    board = spot.get("board")
    board_html = ""
    if board:
        board_html = ('<p class="board"><span class="tag">Bring</span> <strong>%s</strong> — %s</p>'
                      % (esc(board["label"]), esc(board["why"])))
    words_line = ", ".join(x for x in (c["words"]["size"], c["words"]["power"]) if x)
    return (
        '<article class="row">%(thumb)s<div class="row-name"><h3><a href="spots/%(slug)s/">%(name)s</a></h3>'
        '<p class="muted">%(area)s</p></div>'
        '<div class="row-rate">%(chip)s</div>'
        '<div class="row-body"><p class="cond">%(cond)s</p><p class="words">%(words)s</p>%(board)s</div>'
        '<div class="row-when"><p>%(when)s</p></div></article>'
        % {"slug": esc(spot["slug"]), "name": esc(spot["name"]), "area": esc(_place(spot)),
           "thumb": _thumb(spot["slug"], ""),
           "chip": chip(spot["rating"], spot["band"], spot["label"], "chip-lg"),
           "cond": esc(cond_line(c)), "words": esc(words_line[:1].upper() + words_line[1:]),
           "board": board_html, "when": esc(window_text(spot))}
    )


def _matrix(payload, spots=None):
    spots = payload["spots"] if spots is None else spots
    dates = sorted({d["date"] for s in spots for d in s["outlook"]})
    if not dates:
        return '<p class="muted">The forecast outlook isn\'t available right now.</p>'
    first = {d["date"]: d for s in spots for d in s["outlook"]}
    head = "".join(
        '<th scope="col"><span class="d-w">%s</span><span class="d-d">%s</span></th>'
        % (esc(first[d]["weekday"]), esc(first[d]["day"])) for d in dates)
    rows = []
    for s in spots:
        by_date = {d["date"]: d for d in s["outlook"]}
        cells = []
        for d in dates:
            e = by_date.get(d)
            if not e:
                cells.append('<td class="cell-empty"><span class="muted">—</span></td>')
                continue
            rng = _range(*e["height_range_ft"])
            board = (e.get("board") or {}).get("label", "")
            tip = "|".join([
                "%s · %s %s" % (s["name"], e["weekday"], e["day"]),
                "%.1f / 10 — %s" % (e["rating"], e["label"]),
                "%s · peak ~%s" % (rng, _clock(e["peak"])),
                "Bring: %s" % board if board else "",
                "%s confidence" % e["confidence"].capitalize(),
            ])
            aria = "%s, %s %s: %s, %.1f out of 10, %s." % (s["name"], e["weekday"], e["day"], e["label"], e["rating"], rng)
            cells.append(
                '<td><a class="cell" href="spots/%s/#week" data-tip="%s" aria-label="%s">%s'
                '<span class="cell-size">%s</span></a></td>'
                % (esc(s["slug"]), esc(tip), esc(aria), chip(e["rating"], e["band"], e["label"], "chip-sm"), esc(rng)))
        rows.append('<tr><th scope="row"><a href="spots/%s/">%s</a></th>%s</tr>' % (esc(s["slug"]), esc(s["name"]), "".join(cells)))
    return (
        '<div class="matrix-wrap"><table class="matrix"><caption class="sr">Best rating by spot and day, '
        'with the expected size range</caption><thead><tr><th scope="col"><span class="sr">Spot</span></th>%s</tr></thead>'
        '<tbody>%s</tbody></table></div>' % (head, "".join(rows))
    )


def _typical_line(t):
    hour = "%d %s" % (t["hour"] % 12 or 12, "AM" if t["hour"] < 12 else "PM")
    return ('<li>%s about %s ft at %d s, swell from the %s (%d°), %d kt wind, a %s ft tide, '
            'usually best around %s</li>'
            % (chip(t["rating"], words.rating_band(t["rating"]), t["label"], "chip-pill"),
               _f(t["size_ft"]), round(t["period_s"]), esc(t["swell_dir"]), t["swell_dir_deg"], t["wind_kn"],
               _f(t["tide_ft"]), hour))


def _rated_section(spot):
    """What the numbers mean *here*: the typical conditions on this break's own 7 and 9 days."""
    b = spot.get("benchmark")
    if not b:
        return ""
    rows = []
    for rating in ("9", "7"):
        t = b["typical"].get(rating)
        if t:
            rows.append(_typical_line(dict(t, rating=float(rating) + 0.5)))
    if not rows:
        return ""
    return (
        '<section class="sec"><div class="wrap"><h2>How %s is rated</h2>'
        '<p class="sec-lede">Ratings are measured against this break\'s own best days, from %d years of NOAA buoy, wind and '
        'tide records. A 9 or better has turned up about %d days a year here, a 7 or better about %d.</p>'
        '<ul class="plain likes">%s</ul>'
        '<p class="note">Typical conditions at the best hour of those days, measured at the offshore buoy, so wave size at '
        'the beach will look different.</p></div></section>'
        % (esc(spot["name"]), b["years"], round(b["days_per_year"]["9"]), round(b["days_per_year"]["7"]), "".join(rows))
    )


def _legend():
    items = [(9.5, "9 and up"), (8.5, "8 to 8.9"), (7.5, "7 to 7.9"), (6.5, "6 to 6.9"),
             (5.5, "5 to 5.9"), (4.5, "4 to 4.9"), (3.5, "3 to 3.9"), (2.0, "below 3")]
    return (
        '<ul class="legend" aria-label="Rating key">%s</ul>'
        '<p class="note">Each break is rated against its own best: a 10 is the best conditions that break gets, measured '
        'from over twelve years of buoy, wind and tide history, so a 7 at Swami\'s and a 7 at La Jolla Shores are equally '
        'good days for each. A failed hard gate — blown-out wind, too small, too short a period — caps the day at Poor, '
        'however good the swell looks. Beyond day 3 the forecast is a rough guide, not a promise.</p>'
        % "".join('<li>%s <span class="muted">%s</span></li>'
                  % (chip(r, words.rating_band(r), words.rating_label(r), "chip-pill"), span) for r, span in items)
    )


def timeline_chart(spot, now_iso):
    rows = spot["timeline"]
    if not rows:
        return '<p class="muted">No daylight hours to chart for today.</p>'
    now = _dt(now_iso)
    peak_i = max(range(len(rows)), key=lambda i: rows[i]["rating"])
    cols, trs = [], []
    for i, r in enumerate(rows):
        t = _dt(r["time"])
        is_now = t <= now < t + datetime.timedelta(hours=1)
        pct = max(6.0, min(100.0, r["rating"] * 10.0))
        size = "%s ft" % _f(r["height_ft"]) if r["height_ft"] is not None else "—"
        wind = "%d kt" % r["wind_kn"] if r["wind_kn"] is not None else "—"
        per = "%d s" % r["period_s"] if r["period_s"] is not None else "—"
        tide = "%s ft" % _f(r["tide_ft"]) if r["tide_ft"] is not None else "—"
        tip = "|".join(["%s%s" % (_hour(r["time"]), " · now" if is_now else ""),
                        "%.1f / 10 — %s" % (r["rating"], r["label"]),
                        "%s at %s" % (size, per), "Wind %s" % wind, "Tide %s" % tide])
        aria = "%s: %s, %.1f out of 10, %s at %s, wind %s." % (_hour(r["time"]), r["label"], r["rating"], size, per, wind)
        val = '<span class="val">%.1f</span>' % r["rating"] if i == peak_i else ""
        cols.append(
            '<div class="col%s" tabindex="0" role="img" data-tip="%s" aria-label="%s">'
            '<div class="slot"><div class="bar b-%s" style="height:%.0f%%">%s</div></div>'
            '<div class="xl">%s</div></div>'
            % (" is-now" if is_now else "", esc(tip), esc(aria), _CLS[r["band"]], pct, val, esc(_short_hour(r["time"]))))
        trs.append("<tr><th scope=\"row\">%s</th><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                   % (esc(_hour(r["time"])), "%.1f (%s)" % (r["rating"], esc(r["label"])), esc(size), esc(per), esc(wind), esc(tide)))
    grid = "".join('<i class="grid" style="--y:%s"></i>' % y for y in ("0", "0.5", "1"))
    yaxis = "".join('<span style="--y:%s">%s</span>' % (y, lab) for y, lab in (("0", "10"), ("0.5", "5"), ("1", "0")))
    return (
        '<figure class="chart"><div class="plot"><div class="yaxis" aria-hidden="true">%s</div>'
        '<div class="cols">%s%s</div></div>'
        '<figcaption class="muted">Rating (1–10) for each daylight hour. Hover or focus a bar for the details.</figcaption>'
        '</figure>'
        '<details class="tv"><summary>View as a table</summary><div class="tbl-wrap"><table class="tbl">'
        '<thead><tr><th scope="col">Hour</th><th scope="col">Rating</th><th scope="col">Size</th>'
        '<th scope="col">Period</th><th scope="col">Wind</th><th scope="col">Tide</th></tr></thead>'
        '<tbody>%s</tbody></table></div></details>' % (yaxis, grid, "".join(cols), "".join(trs))
    )


# -------------------------------------------------------------------------- pages

def index_page(payload):
    h = payload["headline"]
    spots = {s["slug"]: s for s in payload["spots"]}
    # The big number is the rating the headline is about (a coming peak's, or right now's). It is
    # always in the page, hidden when there's nothing to show, so the script can fill it in later.
    fig = h.get("fig")
    figure = (
        '<a class="hero-fig" data-hero="fig" href="%s"%s><span class="fig-num" data-hero="num">%s</span>'
        '<span class="fig-meta">%s<span class="fig-name" data-hero="name">%s</span></span></a>'
        % ("spots/%s/" % esc(fig["slug"]) if fig else "./", "" if fig else " hidden",
           "%.1f" % fig["rating"] if fig else "",
           chip(fig["rating"], fig["band"], fig["label"], "chip-pill") if fig
           else chip(0, "red", "", "chip-pill"),
           esc(fig["name"]) if fig else ""))
    bg, credit = _hero_bg(media.HERO_SLUG, "")
    hero = (
        '<section class="hero%s" data-hero="root" data-anchor="%s">%s<div class="wrap hero-in">'
        '<div class="hero-text" aria-live="polite">'
        '<p class="kicker" data-hero="kicker">%s</p><h1 data-hero="title">%s</h1>'
        '<p class="lede" data-hero="sub">%s</p>'
        '<p class="meta"><time datetime="%s" data-age>Updated %s</time> · '
        'Live NOAA buoys, tides and a 7-day forecast</p></div>%s</div>%s</section>'
        '<script type="application/json" id="peaks-data">%s</script>'
        % (" has-photo curtain" if bg else "", esc(h.get("anchor") or ""), bg, esc(h["kicker"]), esc(h["title"]),
           esc(h["sub"]), esc(payload["generated"]), esc(payload["generated_label"]), figure, credit,
           _json_for_script(payload.get("peaks", [])))
    )
    top = [spots[slug] for slug in payload["top"]]
    total = len(payload["spots"])
    count = _NUMBER_WORDS.get(len(top), str(len(top)))
    finder = (
        '<section class="finder-sec"><div class="wrap">%s'
        '<p class="finder-alt"><a href="map/">See every break on the map →</a></p>'
        '<p class="finder-alt"><a href="breaks/">Browse all %d breaks, Oceanside to the border →</a></p>'
        '<p class="finder-alt"><a href="profile/">Get alerts for the conditions you like →</a></p>'
        '</div></section>'
        '<script type="application/json" id="breaks-data">%s</script>'
        % (_finder_form(), total, _json_for_script(payload.get("breaks", [])))
    )
    now_sec = (
        '<section id="now" class="sec"><div class="wrap"><h2>Right now</h2>'
        '<p class="sec-lede">The %s best breaks in San Diego County this minute, out of the %d we track.</p>'
        '<div class="rows">%s</div>'
        '<p class="more"><a class="btn" href="breaks/">See all %d breaks</a></p></div></section>'
        % (count, total, "".join(_spot_row(s) for s in top), total)
    )
    week = (
        '<section id="week" class="sec"><div class="wrap"><h2>The week ahead</h2>'
        '<p class="sec-lede">The best daylight hour each day for the %s breaks above. Tap a cell for the details, '
        'or <a href="breaks/">look up any other break</a>.</p>'
        '%s%s</div></section>' % (count, _matrix(payload, top), _legend())
    )
    boards = (
        '<section id="boards" class="sec"><div class="wrap"><h2>Which board to bring</h2>'
        '<p class="sec-lede">Every spot above comes with a pick. It\'s a rule of thumb built from the size, '
        'the period and the wind — and it shows its reasoning.</p><dl class="boards">%s</dl></div></section>'
        % "".join('<div><dt>%s</dt><dd>%s</dd></div>' % (esc(n), esc(b)) for n, b in _BOARD_BLURBS)
    )
    alerts = (
        '<section id="alerts" class="sec"><div class="wrap"><h2>Get the alerts</h2>'
        '<p class="sec-lede">A notification only when a break is genuinely worth paddling out for — '
        'plus a heads-up when a good window is about to open. No account, no email.</p>'
        '<div class="cta-card"><div><h3>Alerts tuned to you</h3>'
        '<p>Pick your breaks and what you call ideal: wave height, wind, swell direction, tide. We message you about an hour '
        'before those conditions peak, so you know exactly when to go.</p></div>'
        '<a class="btn btn-primary" href="profile/">Set up my alerts</a></div>'
        '<p class="sec-lede">Or follow a break or the county\'s daily digest, the same alerts for everyone:</p>'
        '<ol class="steps"><li><strong>Get ntfy.</strong> A free, open-source notification app: '
        '<a href="%s" rel="noopener">iPhone</a> · <a href="%s" rel="noopener">Android</a> · or use it in the browser.</li>'
        '<li><strong>Pick your breaks.</strong> Every one of the %d breaks has its own channel: '
        '<a href="breaks/">find yours</a> and tap Subscribe on its page. Or take the daily digest below.</li>'
        '<li><strong>That\'s it.</strong> Unsubscribe any time from inside the app.</li></ol>'
        '<ul class="sub-list"><li><div><strong>Daily digest</strong><span class="muted"> the county\'s best %s breaks, every morning</span></div>%s</li></ul>'
        '<p class="note">Privacy: this site never sees who subscribes. The trade-off is that ntfy channels are public — '
        'anyone who knows a channel name can read it or post to it — so treat them as a broadcast, not a private line.</p>'
        '</div></section>' % (_IOS, _ANDROID, total, count, subscribe_buttons("the daily digest", payload["digest"], "Open digest in ntfy"))
    )
    how = (
        '<section id="how" class="sec"><div class="wrap"><h2>How it works</h2><ol class="how">'
        '<li><h3>Buoys first</h3><p>Wave size, period and direction come from live NOAA buoy readings. The forecast model is '
        'calibrated to the buoy, so its trend carries through without its coastal bias — and if a buoy goes offline the system says so '
        'and falls back to the model.</p></li>'
        '<li><h3>Score, then gate</h3><p>Height, period, swell direction, wind and tide become a score, and the score becomes a 1–10 rating measured against that break\'s own best days. '
        'Hard gates sit on top: a great swell with a blown-out wind never reads as good.</p></li>'
        '<li><h3>Look ahead</h3><p>A 7-day forecast and NOAA tide predictions find each day\'s best hour and any window worth the trip. '
        'It also warns early when a good window opens before the next check.</p></li>'
        '<li><h3>Say it plainly</h3><p>Notifications skip the jargon — "chest-high, glassy, low tide going out" — and show their numbers underneath.</p></li>'
        '</ol><p class="note">Built in dependency-free Python, rebuilt several times a day by GitHub Actions, with a test suite that runs on every change. '
        '<a href="%s">Read the code and the roadmap.</a></p></div></section>' % esc(payload["repo_url"])
    )
    return _shell("Swell Check — surf conditions for San Diego County",
                  "Live surf conditions, a 7-day outlook and opt-in alerts for %d breaks from Oceanside to the border." % total,
                  hero + _sheet(finder + now_sec + week + boards + alerts + how), "", payload, "home", media.HERO_SLUG,
                  scripts=("peaks.js", "search.js"))


def breaks_page(payload):
    """Every break, north to south, grouped by area, with live ratings and a filter box."""
    by_slug = {s["slug"]: s for s in payload["spots"]}
    groups = {}
    for b in payload["breaks"]:
        groups.setdefault(b["area"], []).append(b)
    sections = []
    for area, items in groups.items():
        lis = []
        for b in items:
            s = by_slug[b["slug"]]
            lis.append(
                '<li class="dir-item" data-break data-name="%s" data-area="%s" data-aliases="%s">'
                '<a class="dir-link" href="../spots/%s/"><span class="dir-name">%s</span>'
                '<span class="dir-size muted">%s</span></a>%s</li>'
                % (esc(b["name"]), esc(b["area"]), esc(" ".join(b["aliases"])), esc(b["slug"]), esc(b["name"]),
                   esc(b["size"] or "no reading"), chip(b["rating"], b["band"], b["label"], "chip-sm")))
        sections.append('<section class="dir-group" data-group><h2 class="dir-h">%s</h2>'
                        '<ul class="dir-list plain">%s</ul></section>' % (esc(area), "".join(lis)))
    total = len(payload["breaks"])
    head = (
        '<section class="page-head"><div class="wrap"><p class="crumb"><a href="../">← San Diego County</a></p>'
        '<h1>All %d breaks</h1><p class="lede">Oceanside to the border, north to south, with live ratings. '
        'Tap one for its hour-by-hour chart and the week ahead.</p>%s</div></section>' % (total, _finder_form())
    )
    body = (
        head + '<section class="sec dir" data-directory><div class="wrap"><div class="dir-groups">%s</div>'
        '<p class="dir-empty muted" data-empty hidden>No break matches that. Try a beach, a neighbourhood or a nickname like "PB".</p>'
        '<p class="note">Each break\'s size range, tide and swell window are starting points based on how that stretch of coast '
        'generally behaves, not gospel. They live in <a href="%s/blob/main/config.py">config.py</a> and are easy to tune.</p>'
        '</div></section>' % ("".join(sections), esc(payload["repo_url"]))
    )
    return _shell("All breaks — Swell Check",
                  "Live surf ratings for all %d breaks in San Diego County, Oceanside to the border." % total,
                  body, "../", payload, "breaks", scripts=("search.js",))


_COMPASS_16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def _hour_options(selected):
    out = []
    for h in range(24):
        label = "%d %s" % (h % 12 or 12, "AM" if h < 12 else "PM")
        out.append('<option value="%d"%s>%s</option>' % (h, " selected" if h == selected else "", label))
    return "".join(out)


def _dir_options():
    return '<option value="">any direction</option>' + "".join(
        '<option value="%s">%s</option>' % (("%g" % (i * 22.5)), name) for i, name in enumerate(_COMPASS_16))


def _map_points(payload):
    """What the map needs for each break: where it is, how it rates, and what to say about it."""
    out = []
    for s in payload["spots"]:
        p = media.photo(s["slug"])
        out.append({
            "slug": s["slug"], "name": s["name"], "place": _place(s), "lat": s["lat"], "lon": s["lon"],
            "rating": s["rating"], "band": s["band"], "label": s["label"],
            "cond": cond_line(s["now"]), "when": window_text(s),
            "href": "../spots/%s/" % s["slug"],
            "thumb": ("../assets/img/%s" % media.tile(p)[0]) if p else None,
        })
    return out


def map_page(payload):
    """A map of every break; tap a pin for its card. Leaflet draws it (assets/vendor/leaflet, assets/map.js)."""
    points = _map_points(payload)
    legend = "".join('<li><span class="pin pin-%s pin-key" aria-hidden="true"><span class="pin-ico">%s</span></span> %s</li>'
                     % (band, ico, esc(text)) for band, ico, text in (
                         ("green", "✓", "7 and up"), ("yellow", "!", "5 to 7"), ("orange", "▼", "3 to 5"), ("red", "✕", "under 3")))
    names = "".join('<li><a href="../spots/%s/">%s</a> <span class="muted">%s</span></li>'
                    % (esc(p["slug"]), esc(p["name"]), esc(p["place"])) for p in points)
    body = (
        '<section class="map-page"><div class="map-wrap" data-map-root>'
        '<div id="map" class="map" role="region" aria-label="Map of surf breaks in San Diego County"></div>'
        '<div class="map-title"><h1>Surf map</h1><p>%d breaks. Tap one for its conditions.</p></div>'
        '<div class="map-mode" role="group" aria-label="Map style">'
        '<button type="button" data-mode="satellite" aria-pressed="true">Satellite</button>'
        '<button type="button" data-mode="map" aria-pressed="false">Map</button></div>'
        '<ul class="map-legend plain" aria-label="Rating key">%s</ul>'
        '<aside class="map-card" data-card hidden aria-live="polite">'
        '<button class="map-card-x" type="button" data-card-close aria-label="Close">×</button>'
        '<img class="map-card-photo" data-card-photo alt="" width="160" height="107" hidden>'
        '<div class="map-card-body"><h2 data-card-name></h2><p class="muted" data-card-place></p>'
        '<span class="chip chip-pill" data-card-chip></span>'
        '<p class="map-card-cond" data-card-cond></p><p class="muted" data-card-when></p>'
        '<a class="btn btn-primary" data-card-link href="#">Open</a></div></aside>'
        '<noscript><p class="map-noscript">The map needs JavaScript. The list below works without it.</p></noscript>'
        '</div><script type="application/json" id="map-data">%s</script></section>'
        '<section class="sec"><div class="wrap"><details class="map-list"><summary>All %d breaks as a list</summary>'
        '<ul class="plain">%s</ul></details></div></section>'
        % (len(points), legend, _json_for_script(points), len(points), names)
    )
    return _shell("Surf map — Swell Check",
                  "Every surf break in San Diego County on a satellite map, with live ratings. Tap one for its conditions.",
                  body, "../", payload, "map", scripts=("vendor/leaflet/leaflet.js", "map.js"),
                  styles=("vendor/leaflet/leaflet.css",))


def profile_page(payload):
    """Pick breaks and ideal conditions; the script (assets/profile.js) saves them to the profile service."""
    groups = {}
    for b in payload["breaks"]:
        groups.setdefault(b["area"], []).append(b)
    picks = "".join(
        '<fieldset class="pf-area"><legend>%s</legend>%s</fieldset>' % (
            esc(area), "".join('<label class="pf-check"><input type="checkbox" name="break" value="%s"> %s</label>'
                               % (esc(b["slug"]), esc(b["name"])) for b in items))
        for area, items in groups.items())
    head = (
        '<section class="page-head"><div class="wrap"><p class="crumb"><a href="../">← San Diego County</a></p>'
        '<h1>My alerts</h1><p class="lede">Choose your breaks and what you call ideal. When those conditions are about to '
        'line up at one of them, you get a notification about an hour before the peak. No account, no email.</p></div></section>'
    )
    form = (
        '<section class="sec"><div class="wrap pf" data-profile-root data-api="%s">'
        '<noscript><p class="note">This page needs JavaScript to save your profile.</p></noscript>'
        '<form class="pf-form" novalidate>'
        '<h2>Your breaks</h2><div class="pf-breaks">%s</div>'
        '<h2>Your ideal conditions</h2>'
        '<div class="pf-grid">'
        '<label class="pf-field">Wave height, from <span class="muted">ft</span><input name="height_min" type="number" step="0.5" min="0" max="30" inputmode="decimal"></label>'
        '<label class="pf-field">to <span class="muted">ft</span><input name="height_max" type="number" step="0.5" min="0" max="30" inputmode="decimal"></label>'
        '<label class="pf-field">Swell period at least <span class="muted">seconds</span><input name="period_min" type="number" step="1" min="0" max="25" inputmode="decimal"></label>'
        '</div>'
        '<fieldset class="pf-wind"><legend>Wind</legend>'
        '<label class="pf-radio"><input type="radio" name="wind" value="offshore"> Offshore only <span class="muted">(or glassy calm)</span></label>'
        '<label class="pf-radio"><input type="radio" name="wind" value="light"> Light, any direction</label>'
        '<label class="pf-radio"><input type="radio" name="wind" value="any"> I don\'t mind</label>'
        '<label class="pf-field pf-inline">Top speed <span class="muted">knots</span><input name="wind_max" type="number" step="1" min="0" max="40" inputmode="decimal"></label>'
        '</fieldset>'
        '<div class="pf-grid">'
        '<label class="pf-field">Swell from<select name="dir_from">%s</select></label>'
        '<label class="pf-field">to<select name="dir_to">%s</select></label>'
        '</div>'
        '<div class="pf-grid">'
        '<label class="pf-field">Tide, lowest <span class="muted">ft, blank = any</span><input name="tide_min" type="number" step="0.5" min="-3" max="8" inputmode="decimal"></label>'
        '<label class="pf-field">highest <span class="muted">ft</span><input name="tide_max" type="number" step="0.5" min="-3" max="8" inputmode="decimal"></label>'
        '</div>'
        '<h2>Your alerts</h2>'
        '<div class="pf-grid">'
        '<label class="pf-field">Tell me<select name="lead_min"><option value="30">30 minutes before the peak</option>'
        '<option value="60">an hour before the peak</option><option value="90">90 minutes before</option>'
        '<option value="120">2 hours before</option><option value="180">3 hours before</option></select></label>'
        '<label class="pf-field">Only if it lasts<select name="min_hours"><option value="1">at least 1 hour</option>'
        '<option value="2">at least 2 hours</option><option value="3">at least 3 hours</option></select></label>'
        '</div>'
        '<div class="pf-grid pf-quiet"><label class="pf-check"><input type="checkbox" name="quiet_on"> Quiet hours</label>'
        '<label class="pf-field">from<select name="quiet_from">%s</select></label>'
        '<label class="pf-field">until<select name="quiet_to">%s</select></label></div>'
        '<ul class="pf-errors" data-pf-errors role="alert" hidden></ul>'
        '<div class="pf-actions"><button class="btn btn-primary" type="submit" data-pf-save>Save my profile</button>'
        '<button class="btn btn-ghost" type="button" data-pf-delete hidden>Delete my profile</button>'
        '<span class="pf-status muted" data-pf-status role="status" aria-live="polite"></span></div>'
        '</form>'
        '<div class="pf-saved" data-pf-saved hidden>'
        '<h2>Get the alerts on your phone</h2>'
        '<ol class="how-small"><li>Install the free <a href="%s" rel="noopener">ntfy</a> app (<a href="%s" rel="noopener">Android</a>).</li>'
        '<li>Subscribe to your private channel: <div class="subs"><a class="btn btn-primary" data-pf-app href="#">Open in ntfy app</a>'
        '<a class="btn" data-pf-web href="#" rel="noopener" target="_blank">Subscribe on the web</a>'
        '<button class="btn btn-ghost" type="button" data-pf-copy-topic>Copy topic</button></div>'
        '<p class="note">Your channel is <code data-pf-topic></code>. Keep it to yourself: anyone who knows it can read your alerts.</p></li>'
        '<li>Check it works: <button class="btn" type="button" data-pf-test>Send me a test alert</button></li></ol>'
        '<h2>Your private link</h2>'
        '<p class="sec-lede">This link opens your profile on any device. Anyone who has it can change it, so keep it private.</p>'
        '<div class="subs"><input class="pf-link" data-pf-link type="text" readonly aria-label="Your private link">'
        '<button class="btn" type="button" data-pf-copy-link>Copy link</button></div>'
        '</div></div></section>'
        % (esc(payload.get("profiles_api", "")), picks, _dir_options(), _dir_options(), _hour_options(22), _hour_options(4),
           _IOS, _ANDROID)
    )
    return _shell("My alerts — Swell Check",
                  "Choose your breaks and ideal conditions and get a surf alert about an hour before they line up.",
                  head + form, "../", payload, "profile", scripts=("profile.js",))


def spot_page(spot, payload):
    c = spot["now"]
    board = spot.get("board")

    def stat(label, value, sub=""):
        return '<div class="stat"><dt>%s</dt><dd>%s</dd><dd class="stat-sub">%s</dd></div>' % (esc(label), esc(value), esc(sub))

    sec = spot.get("secondary_swell")
    dir_note = [("%d°" % c["swell_dir_deg"]) if c["swell_dir_deg"] is not None else ""]
    if sec:
        dir_note.append("plus %s %s ft at %d s%s" % (
            sec["dir"] or "a second swell", _f(sec["height_ft"]), sec["period_s"],
            "" if sec["in_window"] else ", off-angle"))
    stats = "".join([
        stat("Size", "%s ft" % _f(c["height_ft"]) if c["height_ft"] is not None else "—", c["words"]["size"]),
        stat("Period", "%d s" % c["period_s"] if c["period_s"] is not None else "—", c["words"]["power"]),
        stat("Swell from", c["swell_dir"] or "—", " · ".join(x for x in dir_note if x)),
        stat("Wind", "%d kt %s" % (c["wind_kn"], c["wind_dir"] or "") if c["wind_kn"] is not None else "—", c["words"]["wind"]),
        stat("Tide", "%s ft" % _f(c["tide_ft"]) if c["tide_ft"] is not None else "—", c["words"]["tide"]),
    ])
    buoy = spot.get("buoy")
    buoy_txt = ("Live reading from NOAA buoy %s, %d min old%s." % (buoy["id"], buoy["age_minutes"], " (stale — showing the model)" if buoy["stale"] else "")
                if buoy else "No buoy reading right now — showing the forecast model.")
    bg, credit = _hero_bg(spot["slug"], "../../", decorative=False)
    hero = (
        '<section class="spot-hero%s">%s<div class="wrap"><p class="crumb"><a href="../../">← San Diego County</a> · <a href="../../breaks/">All breaks</a> · <a href="../../map/#%s">On the map</a></p>'
        '<div class="spot-hero-in"><div><p class="kicker">%s</p><h1>%s</h1><p class="lede">%s</p>'
        '<p class="meta"><time datetime="%s" data-age>Updated %s</time> · %s</p></div>'
        '<div class="hero-fig static"><span class="fig-num">%.1f</span><span class="fig-meta">%s</span></div></div></div>%s</section>'
        % (" has-photo curtain" if bg else "", bg, esc(spot["slug"]), esc(_place(spot)), esc(spot["name"]), esc(spot["notes"]),
           esc(payload["generated"]), esc(payload["generated_label"]),
           esc(buoy_txt), spot["rating"], chip(spot["rating"], spot["band"], spot["label"], "chip-pill"), credit)
    )
    now_sec = '<section class="sec"><div class="wrap"><h2>Right now</h2><dl class="stats">%s</dl></div></section>' % stats
    today = (
        '<section id="today" class="sec"><div class="wrap"><h2>%s, hour by hour</h2>'
        '<p class="sec-lede">%s</p>%s%s</div></section>'
        % (esc(spot.get("timeline_label", "Today")), esc(window_text(spot)),
           timeline_chart(spot, payload["generated"]), _legend())
    )
    items = []
    for d in spot["outlook"]:
        peak_board = (d.get("board") or {}).get("label")
        w = d.get("window")
        win = "Window %s–%s" % (_hour(w["start"]), _hour(w["end"])) if w else "No window worth it"
        lead = "Today" if d["lead_days"] == 0 else "Tomorrow" if d["lead_days"] == 1 else ""
        items.append(
            '<li class="wk"><div class="wk-day"><strong>%s</strong> %s<small>%s</small></div>'
            '<div class="wk-rate">%s</div>'
            '<div class="wk-body"><p>%s · peaks around %s · %s</p>%s</div>'
            '<div class="wk-conf muted">%s confidence</div></li>'
            % (esc(d["weekday"]), esc(d["day"]), esc(lead), chip(d["rating"], d["band"], d["label"], "chip-sm"),
               esc(_range(*d["height_range_ft"])), esc(_clock(d["peak"])), esc(win),
               '<p class="board"><span class="tag">Bring</span> %s</p>' % esc(peak_board) if peak_board else "",
               esc(d["confidence"].capitalize())))
    week = (
        '<section id="week" class="sec"><div class="wrap"><h2>The next %d days</h2>'
        '<p class="sec-lede">Model forecast, nudged to match the live buoy. Confidence drops the further out you look.</p>'
        '<ol class="week">%s</ol></div></section>' % (len(spot["outlook"]), "".join(items))
        if items else "")
    bring = ""
    if board:
        bring = (
            '<section class="sec"><div class="wrap"><h2>What to bring</h2><div class="bring"><p class="bring-name">%s</p>'
            '<p>%s</p><p class="note">Based on the conditions right now. See <a href="../../#boards">how the picks work</a>.</p></div></div></section>'
            % (esc(board["label"]), esc(board["why"])))
    ideal = spot["ideal"]
    likes = (
        '<section class="sec"><div class="wrap"><h2>What %s likes</h2><ul class="plain likes">'
        '<li><strong>Swell:</strong> from the %s to the %s (%d°–%d°)</li>'
        '<li><strong>Size:</strong> about %s–%s ft is ideal</li>'
        '<li><strong>Period:</strong> at least %d s, with %d s or more best</li>'
        '<li><strong>Tide:</strong> %s–%s ft</li>'
        '<li><strong>Wind:</strong> offshore, or under about %d kt</li></ul></div></section>'
        % (esc(spot["name"]), esc(ideal["swell_dir"][0]), esc(ideal["swell_dir"][1]),
           ideal["swell_dir_deg"][0], ideal["swell_dir_deg"][1], _f(ideal["height_ft"][0]), _f(ideal["height_ft"][1]),
           ideal["period_min_s"], ideal["period_ideal_s"], _f(ideal["tide_ft"][0]), _f(ideal["tide_ft"][1]), ideal["wind_max_kn"])
    )
    likes += _rated_section(spot)
    alerts = (
        '<section id="alerts" class="sec"><div class="wrap"><h2>Get %s alerts</h2>'
        '<div class="cta-card"><div><h3>Want it tuned to your conditions?</h3>'
        '<p>Set your own size, wind and tide, and get told about an hour before they line up here and at your other breaks.</p></div>'
        '<a class="btn btn-primary" href="../../profile/">Set up my alerts</a></div>'
        '<p class="sec-lede">Or one notification whenever %s is rated worth paddling out for. Needs the free '
        '<a href="%s" rel="noopener">ntfy</a> app (<a href="%s" rel="noopener">Android</a>) — no account.</p>%s'
        '<p class="note">ntfy channels are public: anyone who knows the name can read or post to it.</p></div></section>'
        % (esc(spot["name"]), esc(spot["name"]), _IOS, _ANDROID, subscribe_buttons(spot["name"], spot["ntfy"])))
    body = hero + _sheet(now_sec + today + week + bring + likes + alerts)
    return _shell("%s — Swell Check" % spot["name"],
                  "Live conditions, today's best window and a 7-day outlook for %s, %s." % (spot["name"], spot["area"]),
                  body, "../../", payload, "spot", spot["slug"])


def not_found_page(payload):
    # GitHub Pages serves this at any depth, so asset paths must be absolute.
    prefix = urlparse(payload["site_url"]).path.rstrip("/") + "/"
    body = ('<section class="hero"><div class="wrap"><p class="kicker">404</p><h1>That page wiped out.</h1>'
            '<p class="lede"><a href="%s">Head back to the conditions.</a></p></div></section>' % esc(prefix))
    return _shell("Not found — Swell Check", "Page not found.", body, prefix, payload)
