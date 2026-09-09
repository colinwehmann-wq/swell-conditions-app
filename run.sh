#!/bin/zsh
# Wrapper the LaunchAgent calls. Sets notification env, runs the check,
# appends a timestamped block to logs/run.log, and keeps that log bounded.

cd "$(dirname "$0")" || exit 1

# --- notification channels ---------------------------------------------------
export NTFY_TOPIC="HangLoose123"       # phone push via the ntfy app
export SURF_MACOS_NOTIFY="1"           # also drop a macOS banner when the Mac is awake
# export SURF_WEBHOOK_URL="https://..." # optional Slack/Discord webhook

mkdir -p logs
LOG="logs/run.log"

{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z') ====="
  /usr/bin/python3 check.py
  echo
} >> "$LOG" 2>&1

# trim to the last ~1500 lines so it never grows without bound
if [ -f "$LOG" ]; then
  tail -n 1500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi
