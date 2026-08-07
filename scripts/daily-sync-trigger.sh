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

# Note: deliberately `-uo pipefail` without `-e`. This script must always
# exit 0 (see "Exit codes" above) so a sync failure does not break the
# SessionStart hook chain or block the session itself; with `-e` an early
# command failure would short-circuit past the explicit error handling
# below.
set -uo pipefail

LOCK_FILE="${HOME}/.cache/daily-sync-last-run"
TODAY="$(date +%Y-%m-%d)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYNC_SCRIPT="${SCRIPT_DIR}/daily-sync.sh"

mkdir -p "$(dirname "$LOCK_FILE")"

# cc-archives completeness gate (B7, 2026-07-22): surface transcript-
# partial state at EVERY session start, not just on sync days. The gate
# file is written by daily-sync.sh's cc-archives pass; a non-zero first
# line means that many session.meta.json files record a transcript hash
# whose transcript is absent locally (and not written off). Silence on
# this state is how meta-only shells went unnoticed for weeks.
GATE_FILE="${HOME}/.cache/cc-archives-gate"
if [[ -f "$GATE_FILE" ]]; then
    GATE_COUNT="$(head -1 "$GATE_FILE" 2>/dev/null)"
    if [[ "$GATE_COUNT" =~ ^[0-9]+$ ]] && [[ "$GATE_COUNT" -gt 0 ]]; then
        echo "[cc-archives gate] ${GATE_COUNT} archived session(s) lack a local transcript — run daily-sync at home to pull, or see plan B7/B6 (${GATE_FILE} lists them)" >&2
    fi
fi

# Syncthing mesh gate (2026-08-07): the four-device mesh sat dead for three
# months — rpi-server's container had exited and never restarted, and
# amd-tower's had come up on a detached bind mount with the WRONG DEVICE ID,
# so it connected to nobody while `docker ps` reported it healthy. Nothing
# anywhere reported either fault. Same remedy as the cc-archives gate: check
# often, and say something at every session start until it is fixed.
#
# Re-checked at most every 15 minutes so session start stays snappy (the
# check SSHes to rpi-server); otherwise the cached verdict is surfaced.
SYNCTHING_GATE="${HOME}/.cache/syncthing-gate"
SYNCTHING_CHECK="${SCRIPT_DIR}/syncthing-health.sh"
if [[ -x "$SYNCTHING_CHECK" ]]; then
    if [[ ! -f "$SYNCTHING_GATE" ]] || [[ -n "$(find "$SYNCTHING_GATE" -mmin +15 2>/dev/null)" ]]; then
        "$SYNCTHING_CHECK" --quiet >/dev/null 2>&1
    fi
    if [[ -f "$SYNCTHING_GATE" ]]; then
        ST_COUNT="$(head -1 "$SYNCTHING_GATE" 2>/dev/null)"
        if [[ "$ST_COUNT" =~ ^[0-9]+$ ]] && [[ "$ST_COUNT" -gt 0 ]]; then
            echo "[syncthing gate] ${ST_COUNT} problem(s) with the Syncthing mesh:" >&2
            tail -n +3 "$SYNCTHING_GATE" | sed 's/^/  /' >&2
        fi
    fi
fi

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
    # Differentiate benign lock contention (exit 1 — another sync /
    # commit-data is already running, common when interactive
    # commit-data.sh runs during the first session of the day) from
    # genuine failure (exit 2 = git error, 3 = resolver error, 4 =
    # unexpected JSONL shrink). Both leave the lock file unset so
    # the next session retries.
    case "$rc" in
        1)
            echo "[daily-sync-trigger] lock contention (another sync / commit-data is running); will retry next session" >&2
            ;;
        *)
            echo "[daily-sync-trigger] sync failed (exit $rc) — lock not updated; will retry next session" >&2
            ;;
    esac
fi

exit 0
