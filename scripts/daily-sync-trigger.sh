#!/usr/bin/env bash
# daily-sync-trigger.sh — once-per-day SessionStart wrapper for daily-sync.sh.
#
# Replaces the cron-based 07:30 schedule. Fires from a Claude Code
# SessionStart hook on every session start, but only runs the actual sync
# the first time on a given calendar day (per-machine lock file). Inherits
# the user's interactive SSH agent automatically — no cron-env auth issues.
#
# Lock file: ~/.cache/daily-sync-last-run (machine-local, survives reboots).
# Contains today's date (YYYY-MM-DD) on success; absent or stale otherwise.
# On sync failure, the lock is NOT updated so the next session retries.
#
# Exit codes:
#   0 — already ran today, OR sync ran successfully, OR sync failed (we
#       still exit 0 so a sync failure doesn't break the SessionStart
#       hook chain or block the session itself; the failure is logged).
#
# Concurrent-session protection: daily-sync.sh has its own flock; if two
# sessions race past the lock check (rare) only one sync proceeds.

set -uo pipefail

LOCK_FILE="${HOME}/.cache/daily-sync-last-run"
TODAY="$(date +%Y-%m-%d)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYNC_SCRIPT="${SCRIPT_DIR}/daily-sync.sh"

mkdir -p "$(dirname "$LOCK_FILE")"

# Already ran today? Exit silently — dominant path on every session after the
# first of the day.
if [[ -f "$LOCK_FILE" ]] && [[ "$(cat "$LOCK_FILE" 2>/dev/null)" == "$TODAY" ]]; then
    exit 0
fi

# First session of the day on this machine — run the sync. Output goes to
# stderr so Claude Code surfaces it in the session-start log. daily-sync.sh
# itself logs to logs/daily-sync.log.
echo "[daily-sync-trigger] first session of $TODAY — running daily-sync.sh" >&2

if "$SYNC_SCRIPT" >&2; then
    echo "$TODAY" > "$LOCK_FILE"
    echo "[daily-sync-trigger] sync complete" >&2
else
    rc=$?
    echo "[daily-sync-trigger] sync failed (exit $rc) — lock not updated; will retry next session" >&2
fi

exit 0
