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

# ---------------------------------------------------------------------------
# Infra gates — checked at EVERY session start.
#
# ⚠ CHANNEL FIX (2026-08-22). These gates used to print to stderr, and
# SessionStart-hook stderr NEVER REACHES THE SESSION CONTEXT — only stdout
# does. The Syncthing gate reported 3 problems to stderr at every session
# start for two weeks and nobody (human or Claude) ever saw one. That is
# the general failure this repo has now hit three times: a signal that is
# emitted but not surfaced is indistinguishable from no signal. Gates now
# print to STDOUT under an explicit surface-this header, so the assistant
# sees them in context and relays them to Shawn.
#
# Four gates, same format (first line = problem count, rest = detail):
#   cc-archives-gate      metas whose transcript is absent locally (E4)
#   syncthing-gate        mesh health (identity, binds, folder, peers)
#   memory-drift-gate     memory records surviving in only one store
#   cc-archive-drift-gate substantive raw sessions never archived
# ---------------------------------------------------------------------------
GATE_LINES=()

GATE_FILE="${HOME}/.cache/cc-archives-gate"
if [[ -f "$GATE_FILE" ]]; then
    GATE_COUNT="$(head -1 "$GATE_FILE" 2>/dev/null)"
    if [[ "$GATE_COUNT" =~ ^[0-9]+$ ]] && [[ "$GATE_COUNT" -gt 0 ]]; then
        GATE_LINES+=("[cc-archives gate] ${GATE_COUNT} archived session(s) lack a local transcript — run daily-sync at home to pull (${GATE_FILE} lists them)")
    fi
fi

# Syncthing: re-checked at most every 15 minutes so session start stays
# snappy (the check SSHes to rpi-server); otherwise the cached verdict.
SYNCTHING_GATE="${HOME}/.cache/syncthing-gate"
SYNCTHING_CHECK="${SCRIPT_DIR}/syncthing-health.sh"
if [[ -x "$SYNCTHING_CHECK" ]]; then
    if [[ ! -f "$SYNCTHING_GATE" ]] || [[ -n "$(find "$SYNCTHING_GATE" -mmin +15 2>/dev/null)" ]]; then
        "$SYNCTHING_CHECK" --quiet >/dev/null 2>&1
    fi
    if [[ -f "$SYNCTHING_GATE" ]]; then
        ST_COUNT="$(head -1 "$SYNCTHING_GATE" 2>/dev/null)"
        if [[ "$ST_COUNT" =~ ^[0-9]+$ ]] && [[ "$ST_COUNT" -gt 0 ]]; then
            GATE_LINES+=("[syncthing gate] ${ST_COUNT} problem(s) with the Syncthing mesh (personal-docs sync, NOT cc-archives):")
            while IFS= read -r _gl; do
                GATE_LINES+=("  ${_gl}")
            done < <(tail -n +3 "$SYNCTHING_GATE")
        fi
    fi
fi

DRIFT_GATE="${HOME}/.cache/memory-drift-gate"
if [[ -f "$DRIFT_GATE" ]]; then
    DRIFT_COUNT="$(head -1 "$DRIFT_GATE" 2>/dev/null)"
    if [[ "$DRIFT_COUNT" =~ ^[0-9]+$ ]] && [[ "$DRIFT_COUNT" -gt 0 ]]; then
        GATE_LINES+=("[memory-drift gate] $(tail -n +2 "$DRIFT_GATE" | head -1)")
    fi
fi

ARCHIVE_DRIFT_GATE="${HOME}/.cache/cc-archive-drift-gate"
if [[ -f "$ARCHIVE_DRIFT_GATE" ]]; then
    AD_COUNT="$(head -1 "$ARCHIVE_DRIFT_GATE" 2>/dev/null)"
    if [[ "$AD_COUNT" =~ ^[0-9]+$ ]] && [[ "$AD_COUNT" -gt 0 ]]; then
        GATE_LINES+=("[archive-drift gate] ${AD_COUNT} substantive raw session(s) not archived — run scripts/bulk-archive.py (${ARCHIVE_DRIFT_GATE} lists them)")
    fi
fi

# ---------------------------------------------------------------------------
# Slack dashboard refresh (added 2026-08-22)
#
# Runs on EVERY session start, ahead of the once-per-day gate below. The canvas
# is the away-from-desk surface, so staleness is the exact failure being
# designed against — it is how the GitHub Projects board came to contradict
# FOCUS.md. Two API calls against a 50/min limit is a cheap price for a
# dashboard that always matches the banner.
#
# Non-fatal by construction: a Slack outage, an expired token, or a revoked
# scope must never break SessionStart. The accountability banner is the primary
# surface and depends on none of this.
#
# ⚠ Failures are reported through GATE_LINES, i.e. STDOUT, NOT stderr. This
# script's own channel-fix note above is explicit that SessionStart stderr never
# reaches the session context, and that a signal emitted but not surfaced is
# indistinguishable from no signal — a trap this repo has now hit three times.
# A dashboard that silently stopped refreshing would be precisely that trap
# again, and worse, because the artefact would still be sitting there looking
# authoritative. Success stays silent; only failure is worth anyone's attention.
#
# Skipped silently when the Slack variables are unset, so an unconfigured
# machine is not nagged.
# ---------------------------------------------------------------------------
DASHBOARD_SCRIPT="${SCRIPT_DIR}/publish-dashboard.py"
PA_ENV_FILE="$(dirname "$SCRIPT_DIR")/.env"

if [[ -f "$PA_ENV_FILE" ]] && [[ -f "$DASHBOARD_SCRIPT" ]]; then
    # Subshell so sourced credentials never reach the caller's environment or
    # anything spawned later in the session. Exit status carries the verdict:
    # 0 = refreshed or deliberately skipped, 1 = attempted and failed.
    if ! (
        set -a
        # shellcheck disable=SC1090
        . "$PA_ENV_FILE"
        set +a
        if [[ -z "${SLACK_BOT_TOKEN:-}" ]] || [[ -z "${SLACK_DASHBOARD_CANVAS_ID:-}" ]]; then
            exit 0
        fi
        PY="$(dirname "$SCRIPT_DIR")/venv/bin/python3"
        [[ -x "$PY" ]] || PY=python3
        "$PY" "$DASHBOARD_SCRIPT" --publish >/dev/null 2>&1
    ); then
        GATE_LINES+=("[slack-dashboard gate] refresh FAILED — the canvas is stale and still looks authoritative. Run scripts/publish-dashboard.py --publish to see the error (expired token? revoked scope?)")
    fi
fi

if [[ ${#GATE_LINES[@]} -gt 0 ]]; then
    # STDOUT, deliberately: this block lands in the session context.
    echo "# ⚠ Infra gates — RELAY THESE TO SHAWN at session start"
    printf '%s\n' "${GATE_LINES[@]}"
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
