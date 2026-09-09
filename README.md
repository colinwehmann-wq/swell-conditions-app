# Swell Conditions App

Checks live buoy + tide + wind data for five North County San Diego breaks and
tells you when it's worth paddling out — plus the best window and peak time.

Spots: **Swami's, Grandview, Beacon's, Blacks, Oceanside Harbor**

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

State of what's already been alerted lives in `.state.json` (gitignored). A spot
re-alerts when it flips to GO, on a new day, or when its peak window shifts.

## Running it automatically

See [`SCHEDULING.md`](SCHEDULING.md).
