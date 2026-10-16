# Swell Conditions App

A surf-alert system for San Diego County. It pulls live data from NOAA
buoys, tide predictions, and a wind/wave forecast, scores 27 breaks against
per-spot criteria, and sends a plain-language phone notification — with the best
time window — only when a spot is actually worth paddling out. It runs unattended
in GitHub Actions on a schedule.

**How it's built**

- **Dependency-free Python** (standard library only), so the scheduled job has
  nothing to install and little to break.
- **Live buoy data, sanity-checked.** NDBC buoy readings are the source of truth;
  the forecast model is calibrated to the buoy so its trend carries through
  without its coastal bias. Falls back to the model if a buoy goes offline.
- **Scoring with hard gates.** A weighted 0–100 score (height, period, swell
  direction, wind, tide) plus pass/fail gates, so a good swell with a blown-out
  wind never reads as "go."
- **Look-ahead alerts.** At each run it checks whether a good window opens before
  the *next* scheduled check and warns you early.
- **De-duplicated alerts** with state kept in the GitHub Actions cache, plus a
  daily digest and a heartbeat footer.
- **306 unit tests** covering the scoring, tide interpolation, scheduling clock, and
  feed parsing, run in CI on every push. See [`ROADMAP.md`](ROADMAP.md) for the
  review and what's planned next.

Breaks: **27, from Oceanside to the Mexican border** (the list is `SPOTS` in [`config.py`](config.py)).
Five of them are flagged `mine` (Swami's, Grandview, Beacon's, Blacks, Oceanside Harbor): only those reach
the owner's private phone topic and private digest. Every break gets its own public opt-in topic.

## Data sources (all free, no API key)

| What | Source |
|------|--------|
| Live waves / swell / period / direction | NDBC real-time buoys `46224` (Oceanside Offshore) and `46225` (Torrey Pines Outer) — `.spec` feed |
| Tide (hi/lo + interpolated height) | NOAA CO-OPS, station `9410230` La Jolla |
| Hourly wind + wave forecast (for the peak-window calc) | Open-Meteo Marine + Forecast APIs |
| Sunrise / sunset | Open-Meteo daily |

If a buoy is offline, the spot falls back to the Open-Meteo wave model and says so.

## Usage

```bash
python3 check.py               # evaluate all spots, print report, push alerts for anything newly GO
python3 check.py --report      # report only, no alerts, no state written
python3 check.py --quiet       # print nothing unless there's an alert (use this from cron)
python3 check.py --force       # (re)send alerts for every GO spot
python3 check.py --spot blacks # one spot (substring match)
python3 check.py --json        # machine-readable dump
python3 check.py --now 2026-09-09T06:30   # pretend it's this local time (debug the alert format)
```

`--now` holds the **live** buoy reading fixed and shifts only the tide / wind /
sun / daylight math, so it's for previewing what an alert looks like — not a real
forecast for that future time. The scheduled runs read the buoy fresh each time.

No dependencies — Python 3.9+ standard library only.

## What counts as "GO"

Per spot, scored 0–100 from five factors (weights in `sources/evaluate.py`):
wave height in range, swell period, swell direction hitting the break, wind
(offshore/light), and tide. A spot is **GO** when the score clears
`alert_score_min` (default 66) **and** it passes hard gates: height in the OK
band, period at or above the minimum, and wind not blown out.

Verdicts: `GO` (on now) · `LATER` (a window opens later today) · `MARGINAL` · `FLAT`.

**Upcoming-window alerts.** At each run the checker looks ahead to the next
scheduled check (`CHECK_TIMES` in `config.py`). If a GO-quality window *starts*
before that next check, you get a heads-up now — "Grandview turns on around
10 AM" — even though it isn't good yet, so you don't have to wait for the next
check to find out. These de-dupe like GO alerts (re-sent on a new day, when the
window shifts more than an hour, or when it flips to GO).

### Rating (1–10)

The report and alerts lead with a rating = score ÷ 10, colour-coded:

| Rating | Colour | Meaning |
|--------|--------|---------|
| **7.6–10** | 🟢 green | genuinely good — go |
| **5.0–7.5** | 🟡 yellow | rideable / marginal |
| **1.0–4.9** | 🔴 red | not worth it |

If any hard gate fails (blown out, too small, flat) the rating is capped at 4.8
(red) no matter how good the swell is — the number in the terminal is also
ANSI-coloured. Change the cap via `RATING_GATE_CAP` in `sources/evaluate.py`.

The **peak window** is the longest run of daylight hours that stay above the
alert score; "best" is the top-scoring hour in it. If nothing qualifies today,
it looks at tomorrow.

## Tuning

Everything is in [`config.py`](config.py). Each spot can override any default:
height range, period minimum, swell-direction arc, offshore wind arc, wind
ceiling, tide bands, the alert score, which buoys, and the tide station. Comments
in the file explain each field. Start by adjusting `height_ok_ft` /
`height_ideal_ft` and `alert_score_min` to match your standards.

## Notifications

Console output always. Add channels with environment variables:

| Env var | Effect |
|---------|--------|
| `NTFY_TOPIC` | POST alerts to `https://ntfy.sh/<topic>` — install the free **ntfy** app, subscribe to that topic, done. Set `NTFY_SERVER` to use a self-hosted server. |
| `SURF_WEBHOOK_URL` | POST `{title, text}` JSON — Slack / Discord / custom incoming webhook. |
| `SURF_MACOS_NOTIFY=1` | Local macOS notification banner (only when this Mac runs the check). |
| `HEALTHCHECK_URL` | GET this URL after a successful scheduled run — point it at a [healthchecks.io](https://healthchecks.io) check (free) and it emails you if the job stops running at all. |

A phone alert reads in plain language, e.g.:

```
Swami's: go surf — GOOD, 9/10        ← notification title

🟢 Swami's looks GOOD (8.8/10)
Waves: chest-high, solid, lined-up swell
Wind: no wind — glassy and clean
When: go now — stays good until about 11 AM
Tide: Medium tide, coming in

(buoy: 3.6 ft, 10 sec, from the SSW; wind 2 kt)
```

The wording maps from the raw numbers in `format_alert` / the `_*_words` helpers
in `check.py` — tweak the phrasing or thresholds there.

Alert de-dupe state (what's already been sent, plus a `_meta` block with the last
run / last GO alert time) lives in `.state.json` — gitignored locally, and in the
GitHub Actions cache when running in CI. A spot re-alerts when it flips to GO, on
a new day, or when its peak window shifts by more than an hour. The morning digest
footer reports when the last GO alert fired, so a long flat stretch reads as
"working, no swell" rather than "maybe broken".

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Stdlib `unittest`, no dependencies. Covers the scoring curves, compass-arc
wraparound, hard gates, window finding, tide interpolation, the next-check clock,
and NDBC feed parsing. Runs on every push via `.github/workflows/tests.yml`.

## The website

A static site, rebuilt on every scheduled run and deployed to GitHub Pages:

- **Right now** — the county's five best breaks this minute, ranked by rating, each with a "what to bring" pick
- **Find a break** — a search box that knows nicknames ("PB", "15th street", "the cliffs") and an
  "All breaks" directory, north to south, filterable as you type. The search is plain script over the
  page's own data, so there's no server
- **A headline that keeps up** — the top of the page names the next peak worth catching and
  moves on to the following one the moment the clock passes it, without waiting for a rebuild
  (the page carries every upcoming peak and picks from the visitor's own clock; the pick is
  written in both Python and JavaScript and a test keeps the two identical)
- **Week ahead** — a 7-day matrix of the best daylight hour for those five, with size ranges
- **Spot pages** — an hour-by-hour chart (with a table view), the next 7 days, what
  the break likes, and a subscribe button
- **Opt-in alerts** — every spot has its own public [ntfy](https://ntfy.sh) topic and
  there's a daily-digest topic. Visitors tap a button to subscribe; the site never
  sees who they are. The catch: ntfy topics are public, so anyone who knows a name
  can read *and post* to it. Names carry a random suffix (see `config.py`) to avoid
  collisions, and the workflow only publishes to them from scheduled runs.
- **Open data** — the same numbers are published as `data/latest.json`.
- **Photos** — a full-bleed photo behind the home hero and each spot page, and a thumbnail
  beside every spot name. They're Creative Commons images from Wikimedia Commons; the file,
  crop point and licence for each live in [`sitegen/media.py`](sitegen/media.py), the credits are
  printed on the page and in the footer, and a test fails if a spot is missing a photo or a credit.
  Images are resized to web weight (under ~500 KB each) and the slow zoom stops for visitors who
  prefer reduced motion.

Build it locally (no alerts are sent in `--report` mode):

```bash
python3 check.py --report --site _site
python3 -m http.server 8000 --directory _site     # then open http://localhost:8000
```

**Board picks** come from `sources/boards.py` — a transparent rule of thumb
(longboard / fish / shortboard / performance board) based on size, period and wind;
every pick carries a one-line reason. **Enabling Pages:** repo Settings → Pages →
Source: *GitHub Actions* (the repo must be public on a free plan).

## Adding or tuning a break

Everything about a break lives in one entry in `SPOTS` in [`config.py`](config.py): name, area,
coordinates, which offshore buoys to read, and optional overrides (size range, swell window, tide
range, nicknames for search). Anything not overridden takes the defaults. Add an entry, run the
tests (`tests/test_roster.py` checks coordinates, buoys, ranges and nicknames), and the break
gets a page, a directory listing, a search entry and its own alert topic on the next build.

The size, tide and swell-window settings for the newer breaks are starting points based on how
each stretch of coast generally behaves. Someone who surfs a break will know better, and fixing
one is a one-line change. Coordinates come from OpenStreetMap beaches; the forecast models are
8–25 km grids, so a few hundred metres never changes the answer. Only the four *offshore* buoys
are used: the nearshore ones read lower and from a different angle because the swell has already
bent on its way in, and the scoring thresholds assume an offshore reading.

## Forecast accuracy

Every scheduled run also appends to an accuracy log: what five wave models predicted at the
two buoys for the next 72 hours, and what the buoys then measured. `tools/skill_report.py`
turns that into error tables by model and lead time, with a "assume nothing changes"
(persistence) baseline that a model has to beat. The log lives on its own `forecast-log` branch
(never on `main`); the report is printed in each Actions run's summary. Turn it on locally with
`python3 check.py --report --log-dir forecast-log`, then `python3 tools/skill_report.py`.

The reasoning, and what comes after measuring (blending models, scoring both swell trains, then
upstream buoys, wind and nearshore transformation), is in
[`docs/FORECAST_PLAN.md`](docs/FORECAST_PLAN.md).

## Running it automatically

See [`SCHEDULING.md`](SCHEDULING.md).
