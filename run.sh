#!/bin/zsh
# Wrapper the LaunchAgent calls. Sets notification env, runs the check,
# appends a timestamped block to logs/run.log, and keeps that log bounded.

cd "$(dirname "$0")" || exit 1

# --- notification channels ---------------------------------------------------
# Secrets live in a gitignored .env next to this script (copy .env.example).
# Supported: NTFY_TOPIC, SURF_WEBHOOK_URL, SURF_MACOS_NOTIFY.
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi
export SURF_MACOS_NOTIFY="${SURF_MACOS_NOTIFY:-1}"   # macOS banner when the Mac is awake

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
