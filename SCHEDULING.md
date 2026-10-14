# Running it automatically

There are two ways to run the checker on a schedule. The cloud runner is the
primary one; the local macOS agent is an optional alternative.

## Cloud runner — GitHub Actions (always on)

`.github/workflows/surf-check.yml` runs the check in GitHub's cloud on a cron
schedule, independent of whether your computer is on.

**Setup (one time):**

1. Fork or push this repo to your own GitHub account.
2. Pick a hard-to-guess ntfy topic name (e.g. `surf-` plus random characters) and
   subscribe to it in the **ntfy** app on your phone (free, no account needed).
3. Add it as a repository secret: repo → Settings → Secrets and variables →
   Actions → New repository secret → name `NTFY_TOPIC`, value = your topic.
4. Optional: add a `HEALTHCHECK_URL` secret pointing at a free
   [healthchecks.io](https://healthchecks.io) check — you'll get an email if the
   workflow ever stops running entirely.
5. Test it: repo → Actions → "surf check" → "Run workflow". Tick **digest** to
   force a summary notification, or **force** to re-send any current alerts.

**How it works:** the workflow runs `python3 check.py --quiet` at the cron times
(UTC; each local check is scheduled twice, an hour apart, to cover both PDT and
PST). The 05:15 run also passes `--digest` for a daily summary. Alert de-dupe
state (`.state.json`) is stored in the **GitHub Actions cache** — restored at the
start of each run and saved at the end, keyed by run id with a rolling
`surf-state-` prefix. GitHub's scheduler can fire 5–20 minutes late.

**Change the schedule:** edit the `cron:` lines in the workflow (5-field cron,
UTC) and push. Keep `CHECK_TIMES` in `config.py` roughly in step with them — it's
what lets the app say "a good window opens before the next check."

GitHub disables scheduled workflows on repos with 60 days of no commits, so make a
commit every so often (or rely on the `HEALTHCHECK_URL` ping to tell you when it
has gone quiet).

## Local alternative — macOS LaunchAgent

Runs the same checker from your own Mac. It only fires while the Mac is awake
(missed runs catch up on wake).

| File | Role |
|------|------|
| `run.sh` | what the agent calls — loads `.env`, runs `check.py`, trims `logs/run.log` |
| `com.example.swellconditions.plist` | the schedule (05:30, 10:30, 15:00 local) — a template |
| `.env.example` | copy to `.env` and set `NTFY_TOPIC` (`.env` is gitignored) |

```bash
cp .env.example .env            # then edit NTFY_TOPIC
cp com.example.swellconditions.plist ~/Library/LaunchAgents/
# edit the three paths inside the copied plist to point at this checkout, then:
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.example.swellconditions.plist

launchctl kickstart -p gui/$(id -u)/com.example.swellconditions   # run it now
launchctl bootout gui/$(id -u)/com.example.swellconditions        # stop it
```

If you run both the cloud runner and the local agent you'll get each alert twice —
pick one.

## Testing notifications

```bash
NTFY_TOPIC=<your-topic> python3 check.py --test-alert          # sample push
NTFY_TOPIC=<your-topic> python3 check.py --notify beacon       # on-demand check for one spot
NTFY_TOPIC=<your-topic> python3 check.py --digest --quiet      # the daily summary
```

`--now 2026-09-09T06:30 --force` previews what an alert looks like at a given time
(it holds the live buoy reading fixed, so it's for formatting, not forecasting).
