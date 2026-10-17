# Roadmap

A running review of where this project stands and what's worth doing next.

## Assessment

**Solid foundation.** Clean module split — `sources/` is one adapter per data feed,
`sources/evaluate.py` is pure scoring logic with no I/O, `check.py` orchestrates
and presents. Zero runtime dependencies (right call for an unattended job). It
degrades gracefully (buoy offline → model fallback, model calibrated to the buoy)
and the score / gate / verdict split is sound. Deployed, scheduled, and
delivering to a phone — verified end to end.

**Known limits.** The scoring weights and thresholds are hand-tuned with no
feedback loop, so a "7/10" is an educated guess. Everything is hard-wired to
North County San Diego. `check.py` is doing a lot (CLI + HTTP orchestration + six
formatters + state I/O).

## Tier 1 — hardening (in progress)

- [x] **Unit tests** — `tests/`, stdlib `unittest`, 69 cases over the scoring
  curves, compass-arc wraparound, gates, window finding, tide interpolation,
  `next_check_after`, and NDBC parsing. CI on every push.
- [x] **State off `main`** — `.state.json` moved from repo commits to the Actions
  cache. Kills the per-run "update alert state" commit churn; workflow drops
  `contents: write`.
- [x] **Heartbeat** — state `_meta` tracks last run / last GO alert; the digest
  footer surfaces "last GO alert: N days ago" so a flat stretch doesn't look
  like a failure. Optional `HEALTHCHECK_URL` ping for external monitoring.
- [x] **Time-aware digest** — "Morning / Midday / Evening check".
- [ ] Move pushes off hand-pasted personal access tokens — `gh auth login` or
  GitHub Desktop.
- [x] Retired the local LaunchAgent (redundant with the cloud runner); it remains
  as an optional template, see `SCHEDULING.md`.

## Tier 2 — real added value

- [x] **Multi-day outlook.** A 7-day outlook per spot (best hour, window, size
  range, board pick, confidence that fades with lead time). Lives on the public
  website rather than in the digest. Still to do: surface it in the digest too.
- [x] **Public website.** Static site on GitHub Pages, rebuilt by the same workflow
  that checks conditions: ranked live conditions, hour-by-hour chart, 7-day matrix,
  board recommender, and opt-in alerts via public per-spot ntfy topics.
- [x] **The whole county.** 27 breaks from Oceanside to the border, a searchable directory, and a
  home page that shows the county's best five. Only the original five reach the owner's phone.
  - [x] Photos for the new breaks (20 free-licensed Commons photos). Bird Rock and Buccaneer Beach
    still show a plain tile: nothing usable turned up. Mission Beach's is the Giant Dipper, not surf.
  - [ ] Have someone who surfs these breaks sanity-check each one's size, tide and swell window.
  - [x] Profiles: people choose their own breaks and ideals on the My alerts page and get a personal alert about an
    hour before they peak (Cloudflare Worker + hourly job; see `worker/`). Next: saved breaks (stars) on the home page.
- [ ] **Website v2.** Per-user thresholds and email/web-push opt-in need a small
  backend (stored subscriptions, unsubscribe links, abuse handling) — deliberately
  out of scope for v1, which keeps the project stateless and data-free.
- [ ] **Forecast accuracy** — see [`docs/FORECAST_PLAN.md`](docs/FORECAST_PLAN.md).
  - [x] Phase 1: log every model's forecast and the buoy readings; score them
    (`tools/skill_report.py`). Collecting data now; trust it after 2–4 weeks.
  - [ ] Phase 2: blend models, weighted by measured error.
  - [x] Phase 3: score both swell trains (backtested; beat primary-only in 16/16 comparisons).
  - [ ] Near-term blend: lean on the live buoy for the first ~12 h, the model after (backtests
    say persistence wins early). Confirm with the live log first.
  - [ ] Phase 4: upstream buoys / wind / nearshore factors, chosen from the data.
- [ ] **Feedback loop.** `check.py --rate <spot> <1-10>` after a session; append
  every evaluation + the real rating to a log; a `tune` script that reports where
  the model over/under-calls. Adjust `WEIGHTS` / thresholds from data, not vibes.
- [ ] **Better swell modelling.** Use Open-Meteo's secondary swell partition;
  score primary + secondary separately and combine. Handle "small but long-period,
  could sneak up" explicitly (that's most marginal days here).

## Tier 3 — polish

- [ ] Split `check.py` → `cli.py` / `presentation.py` / `state.py`; make it an
  installable package (`python -m surfcheck`), drop the `sys.path` hacks.
- [ ] Region as a config profile so the SD specifics (spots, buoys, tide station,
  the PDT/PST cron doubling) aren't scattered.
- [ ] One source of truth for check times — generate `config.CHECK_TIMES` from the
  workflow cron, or vice versa.
- [ ] Static dashboard on GitHub Pages: current report + 7-day outlook, refreshed
  by the workflow.
- [ ] ntfy access token on the topic; optional Slack/Discord mirror via
  `SURF_WEBHOOK_URL`.
- [ ] `CLAUDE.md` with project context for future sessions.

## Data-quality notes (for whoever picks up Tier 2)

- NDBC `.spec` swell direction is compass text (`SSW`), i.e. 22.5° resolution —
  coarse for direction scoring. `MWD` in the `.txt`/`.spec` is in degrees; prefer
  it when present.
- Tide interpolation is a cosine between hi/lo. Fine for "is it mid or full", not
  for precise state near the turn. NOAA also serves 6-minute predictions if that
  ever matters.
- The buoy `stale` cutoff (3 h) and the wind gate (`_wind_score < 0.35`) are
  round-number guesses — prime candidates for the feedback loop to tune.
