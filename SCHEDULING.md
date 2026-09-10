# Automated checks

## What's installed

A macOS **LaunchAgent** (`com.colinwehmann.swellconditions`) runs the checker
three times a day at local time:

| Time | Why |
|------|-----|
| 05:30 | dawn patrol — see it before you leave |
| 10:30 | mid-morning glass-off / swell filling in |
| 15:00 | late-day wind drop before sunset (fall/winter) |

If the Mac is asleep at one of those times, the job runs when it next wakes.
Each run appends a full report to `logs/run.log`; macOS/launchd errors go to
`logs/launchd.log`.

You won't get a notification every run — only when a break is **GO** and either
it just turned GO, it's a new day, or its peak window moved. See `should_alert`
in `check.py`.

## Files

| File | Role |
|------|------|
| `run.sh` | what the LaunchAgent calls — sets `NTFY_TOPIC` etc., runs `check.py`, trims the log |
| `com.colinwehmann.swellconditions.plist` | the schedule; a copy is installed at `~/Library/LaunchAgents/` |
| `.state.json` | remembers what was already alerted (gitignored) |

## Phone notifications (ntfy)

1. Install **ntfy** (App Store / Play Store / F-Droid) or open <https://ntfy.sh>.
2. Subscribe to the topic **`HangLoose123`**.
3. That's it — no account. Anyone who guesses the topic can read your alerts, so
   change it if you like: edit `NTFY_TOPIC` in `run.sh` and re-subscribe in the app.

Test the whole chain any time:

```bash
cd "/Users/colinwehmann/Swell Conditions App"
NTFY_TOPIC=HangLoose123 python3 check.py --now 2026-09-09T06:30 --force
```

That simulates a glassy dawn and pushes a real alert for every qualifying spot.

## Managing the schedule

```bash
# stop / start
launchctl bootout  gui/$(id -u)/com.colinwehmann.swellconditions
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.colinwehmann.swellconditions.plist

# run it right now
launchctl kickstart -p gui/$(id -u)/com.colinwehmann.swellconditions

# is it loaded? last exit code?
launchctl print gui/$(id -u)/com.colinwehmann.swellconditions | grep -E "state|last exit code|runs"
```

After editing the `.plist`, copy it to `~/Library/LaunchAgents/` again and
bootout + bootstrap to reload. Changing times only: edit both copies, reload.

To change **how often** it runs, add/remove `<dict>` blocks in
`StartCalendarInterval`.

## Cloud runner — GitHub Actions (always on)

The local agent only runs while the Mac is on. `.github/workflows/surf-check.yml`
runs the same check in GitHub's cloud on a cron schedule regardless of the Mac.

**Setup (one time):**

1. Repo: `github.com/colinwehmann-wq/swell-conditions-app` (private).
2. Push the code:
   ```bash
   cd "/Users/colinwehmann/Swell Conditions App" && git push -u origin main
   ```
   Username `colinwehmann-wq`; password = a fine-grained personal access token
   (github.com/settings/personal-access-tokens → this repo → Contents: read/write).
   macOS keychain remembers it after the first push.
3. Secret `NTFY_TOPIC` = `HangLoose123` is already set under
   repo → Settings → Secrets and variables → Actions.
4. Optional: add a `HEALTHCHECK_URL` secret pointing at a free
   [healthchecks.io](https://healthchecks.io) check — you'll get an email if the
   workflow ever stops running entirely.
5. Test: repo → Actions → "surf check" → "Run workflow".

**How it works:** the workflow runs `python3 check.py --quiet` at the cron times
(UTC; scheduled twice per local check to cover PDT and PST). The `05:15` run also
passes `--digest`. Alert de-dupe state (`.state.json`) is stored in the **GitHub
Actions cache** — restored at the start of each run and saved at the end, keyed by
run id with a rolling `surf-state-` prefix. GitHub's scheduler can fire 5–20 min
late.

**Change the schedule:** edit the `cron:` lines in the workflow (5-field cron, UTC)
and push. GitHub disables cron on repos with **60 days of no commits** — a `git`
push (or the tests workflow on any branch push) resets that clock, so commit
something at least every couple of months, or the `HEALTHCHECK_URL` ping will tell
you when it's gone quiet.

**Avoid double alerts:** once the cloud runs are confirmed, disable the local
agent — `launchctl bootout gui/$(id -u)/com.colinwehmann.swellconditions` — or
keep only one of the two.
