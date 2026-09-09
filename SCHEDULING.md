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

## Later: cloud backup (optional)

The local agent only runs while the Mac is on. For an always-on version, push
this repo to GitHub and create a Claude cloud routine (min 1-hour interval) whose
prompt is roughly:

> Run `python3 check.py --quiet`. If it prints a line starting with `>>> NOTIFY:`,
> `curl -H "Title: <that spot> surf" -d "<the block>" https://ntfy.sh/HangLoose123`.

The checker is self-contained and needs no secrets, so it runs the same in the
cloud as locally.
