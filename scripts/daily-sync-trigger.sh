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

# audit L4: `set -u` makes a bare ${HOME} abort with status 1 when HOME is
# unset — a systemd unit, a bare cron environment, `env -i` — which breaks
# the always-exit-0 contract this script exists to keep (see "Exit codes"
# above): the SessionStart hook chain would be broken by the one guard
# meant to protect it. Degrade instead: every read below tolerates a
# missing file, and a lock that cannot be written just means the sync is
# retried next session.
# audit M2 (fourth re-audit): check HOME BEFORE creating anything. The
# `mkdir -p` below used to run first and silently conjured the whole path,
# so on the production path — where the trigger is what actually starts
# the sync — daily-sync.sh's own "refuse a HOME that does not exist" guard
# never saw a missing HOME: the trigger had just created it. Gate files
# would then accumulate in a phantom tree nothing reads, on a machine
# whose home is (say) not yet mounted.
#
# Still exit 0, always: this script exists to keep the SessionStart hook
# chain alive (see "Exit codes" above). Say so on STDOUT, which is the
# only channel that reaches the session context, and touch nothing.
# audit (low, fifth re-audit): the relay header is printed at most once
# per session. Gates render before the sync and the sync's own failure
# renders after it, so a session with both used to carry two headers and
# read like two separate reports.
gate_header_printed=0
relay() {
    # relay <line>... — surface to STDOUT, under one header.
    if [[ $gate_header_printed -eq 0 ]]; then
        echo "# ⚠ Infra gates — RELAY THESE TO SHAWN at session start"
        gate_header_printed=1
    fi
    printf '%s\n' "$@"
}

if [[ -z "${HOME:-}" ]] || [[ ! -d "${HOME}" ]]; then
    relay "[daily-sync gate] HOME (${HOME:-<unset>}) is unset or not a directory, so the daily sync cannot run and no gate files can be read. Nothing has been created."
    exit 0
fi

CACHE_DIR="${HOME}/.cache"

LOCK_FILE="${CACHE_DIR}/daily-sync-last-run"
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
# Seven gates, same format (first line = problem count, rest = detail):
#   cc-archives-gate      metas whose transcript is absent locally (E4)
#   syncthing-gate        mesh health (identity, binds, folder, peers)
#   memory-drift-gate     memory records surviving in only one store
#   cc-archive-drift-gate substantive raw sessions never archived
#   postgres-sync-memories-gate   the memory sync stopped, or quarantined
#   postgres-sync-sessions-gate   the session sync stopped, or quarantined
#   index-session-content-gate    transcripts left out of the search index
# ---------------------------------------------------------------------------
GATE_LINES=()

GATE_FILE="${CACHE_DIR}/cc-archives-gate"
if [[ -f "$GATE_FILE" ]]; then
    GATE_COUNT="$(head -1 "$GATE_FILE" 2>/dev/null)"
    if [[ "$GATE_COUNT" =~ ^[0-9]+$ ]] && [[ "$GATE_COUNT" -gt 0 ]]; then
        GATE_LINES+=("[cc-archives gate] ${GATE_COUNT} archived session(s) lack a local transcript — run daily-sync at home to pull (${GATE_FILE} lists them)")
    fi
fi

# Syncthing: re-checked at most every 15 minutes so session start stays
# snappy (the check SSHes to rpi-server); otherwise the cached verdict.
SYNCTHING_GATE="${CACHE_DIR}/syncthing-gate"
SYNCTHING_CHECK="${SCRIPT_DIR}/syncthing-health.sh"
if [[ -x "$SYNCTHING_CHECK" ]]; then
    if [[ ! -f "$SYNCTHING_GATE" ]] || [[ -n "$(find "$SYNCTHING_GATE" -mmin +15 2>/dev/null)" ]]; then
        "$SYNCTHING_CHECK" --quiet >/dev/null 2>&1
    fi
    if [[ -f "$SYNCTHING_GATE" ]]; then
        ST_COUNT="$(head -1 "$SYNCTHING_GATE" 2>/dev/null)"
        if [[ "$ST_COUNT" =~ ^[0-9]+$ ]] && [[ "$ST_COUNT" -gt 0 ]]; then
            GATE_LINES+=("[syncthing gate] ${ST_COUNT} problem(s) with the Syncthing mesh (personal-docs sync, NOT cc-archives):")
            # audit S10: syncthing-health.sh writes two layouts — the
            # normal path emits `count`, a `checked …` line, then the
            # problems; the early-exit path (expectations file missing)
            # emits `count` then the problems with no `checked` line. A
            # fixed `tail -n +3` swallowed the only detail line of the
            # second layout, so the header was printed with nothing under
            # it. Skip the optional `checked …` line instead of a fixed
            # offset, so both layouts render.
            while IFS= read -r _gl; do
                [[ -z "$_gl" ]] && continue
                # Only the gate's own timestamp header, whose exact shape
                # is `checked <date> <time> on <host>` (syncthing-health.sh
                # writes it with `date '+%Y-%m-%d %H:%M:%S'`). Audit L4: a
                # `checked *` glob would also swallow a genuine problem
                # line that happened to start with the word.
                [[ "$_gl" =~ ^checked\ [0-9]{4}-[0-9]{2}-[0-9]{2}\ [0-9]{2}:[0-9]{2}:[0-9]{2}\ on\  ]] \
                    && continue
                GATE_LINES+=("  ${_gl}")
            done < <(tail -n +2 "$SYNCTHING_GATE")
        fi
    fi
fi

DRIFT_GATE="${CACHE_DIR}/memory-drift-gate"
if [[ -f "$DRIFT_GATE" ]]; then
    DRIFT_COUNT="$(head -1 "$DRIFT_GATE" 2>/dev/null)"
    if [[ "$DRIFT_COUNT" =~ ^[0-9]+$ ]] && [[ "$DRIFT_COUNT" -gt 0 ]]; then
        GATE_LINES+=("[memory-drift gate] $(tail -n +2 "$DRIFT_GATE" | head -1)")
    fi
fi

# audit S3/S17: a sync that wedges on a conflicted tree stops running at
# all — every later session re-enters the same failure and bails — and
# until now that state was visible only in logs/daily-sync.log.
SYNC_GATE="${CACHE_DIR}/daily-sync-gate"
if [[ -f "$SYNC_GATE" ]]; then
    SYNC_COUNT="$(head -1 "$SYNC_GATE" 2>/dev/null)"
    if [[ "$SYNC_COUNT" =~ ^[0-9]+$ ]] && [[ "$SYNC_COUNT" -gt 0 ]]; then
        # EVERY detail line, not just the first: a wedged sync can record
        # both the diagnosis (what stopped it) and a stranded stash (where
        # the unrecovered work is), and the operator needs both.
        GATE_LINES+=("[daily-sync gate] the sync is stuck and will not run until this is resolved:")
        while IFS= read -r _sl; do
            [[ -n "$_sl" ]] && GATE_LINES+=("  ${_sl}")
        done < <(tail -n +2 "$SYNC_GATE")
    fi
fi

ARCHIVE_DRIFT_GATE="${CACHE_DIR}/cc-archive-drift-gate"
if [[ -f "$ARCHIVE_DRIFT_GATE" ]]; then
    AD_COUNT="$(head -1 "$ARCHIVE_DRIFT_GATE" 2>/dev/null)"
    if [[ "$AD_COUNT" =~ ^[0-9]+$ ]] && [[ "$AD_COUNT" -gt 0 ]]; then
        GATE_LINES+=("[archive-drift gate] ${AD_COUNT} substantive raw session(s) not archived — run scripts/bulk-archive.py (${ARCHIVE_DRIFT_GATE} lists them)")
    fi
fi

# PostgreSQL pipeline gates (added 2026-09-08, audit round two finding C2;
# split per script by the third re-audit, finding C1).
#
# ONE FILE PER SCRIPT, deliberately. A single shared file meant a clean
# run of the memory sync erased the session sync's alarm on the next cron
# tick — five minutes of visibility for a fault that needs a human. Each
# script clears only its own gate, and only after a cycle that actually
# completed.
#
# Raised on: exit 4 (environment fault — reachable database, wrong state),
# exit 6 (a rebuild cleared the cursor mid-run), a cap overflow, a
# correlated batch refusal, or rows quarantined (data that left the
# pipeline). Lowered by the next completed cycle with nothing to report.
#
# These are the gates the September 2026 incident argued for: the sessions
# table sat three weeks stale behind an error in a log nobody reads.
#
# --- Is each pipeline script still running? -----------------------------
#
# The two kinds of gate here fail in completely different ways, and a
# single wall-clock rule cannot describe both (ninth re-audit, M4).
#
#   postgres-sync-memories-gate  is written by cron every five minutes.
#       Silence for half an hour means the cron entry is gone. Measured
#       from the LATER of the gate's own mtime and the machine's boot,
#       because a gate cannot be refreshed while the machine is off — and
#       with a short grace after boot, so the first session back does not
#       report a script that has not had its turn yet.
#
#   postgres-sync-sessions-gate and index-session-content-gate are
#       written by session hooks. Wall-clock age says nothing about them:
#       a fortnight of no sessions, or one very long session, leaves them
#       untouched and everything is fine. They are only late when a
#       SESSION HAS ENDED and the hook did not run — which is exactly
#       "there is a session.meta.json newer than the gate".
#
# Every override is validated before use: these values are expanded
# inside $(( )), where bash evaluates a non-numeric value as an
# arithmetic EXPRESSION and an array subscript runs a command
# substitution (eighth re-audit, M6).
_pa_gate_minutes() {
    # $1 = the value from the environment, $2 = the shipped default.
    if [[ "${1:-}" =~ ^[0-9]+$ ]] && (( 10#${1} > 0 )); then
        printf '%s' "$(( 10#${1} ))"
    else
        printf '%s' "$2"
    fi
}
PG_CRON_STALE_MINUTES="$(_pa_gate_minutes "${PA_GATE_STALE_MINUTES:-}" 30)"
PG_BOOT_GRACE_MINUTES="$(_pa_gate_minutes "${PA_GATE_BOOT_GRACE_MINUTES:-}" 10)"
PG_HOOK_LAG_MINUTES="$(_pa_gate_minutes "${PA_HOOK_GATE_LAG_MINUTES:-}" 15)"
# How far ahead of now a gate's timestamp may sit before it is called
# impossible rather than rounding. Not an override: a second of skew is
# filesystem noise, a minute of it is a clock that moved.
PG_FUTURE_TOLERANCE_SECONDS=60

# Where session archives land. A session.meta.json newer than a
# hook-written gate is the evidence that the hook did not run.
PG_ARCHIVE_ROOT="${PA_CC_ARCHIVES:-${HOME}/cc-archives}"
#: Say the liveness check is off at most once, however many gates use it.
_pg_archive_reported=0

# Uptime, for the boot reference and the post-boot grace. Overridable so
# the guard can be tested without a reboot.
PG_UPTIME_FILE="${PA_UPTIME_FILE:-/proc/uptime}"
PG_UPTIME_SECONDS=""
PG_BOOT_EPOCH=""
_pg_uptime_raw=""
_pg_uptime_rest=""
PG_NOW="$(date +%s)"
if [[ -r "$PG_UPTIME_FILE" ]]; then
    read -r _pg_uptime_raw _pg_uptime_rest < "$PG_UPTIME_FILE" || true
    if [[ "$_pg_uptime_raw" =~ ^([0-9]+) ]]; then
        PG_UPTIME_SECONDS="${BASH_REMATCH[1]}"
        PG_BOOT_EPOCH=$(( PG_NOW - PG_UPTIME_SECONDS ))
    fi
fi

for _pg_gate_name in postgres-sync-memories-gate \
                     postgres-sync-sessions-gate \
                     index-session-content-gate; do
    _pg_gate_file="${HOME}/.cache/${_pg_gate_name}"
    # The sidecar is written by the same run that renders the gate, so it
    # is independent evidence that the script is alive. A run that saved
    # its state but could not write the gate is not a dead script, and
    # saying so would send Shawn after the wrong thing (eighth re-audit,
    # low).
    _pg_state_file="${_pg_gate_file}.state.json"
    if [[ ! -f "$_pg_gate_file" ]] && [[ ! -f "$_pg_state_file" ]]; then
        GATE_LINES+=("[${_pg_gate_name%-gate} gate] has NEVER been written — that script has not completed a run on this machine. Check the cron entry and the session hooks.")
        continue
    fi
    if [[ ! -f "$_pg_gate_file" ]]; then
        GATE_LINES+=("[${_pg_gate_name%-gate} gate] the script is running but its gate file is missing — whatever it found is not reaching session start. Check the permissions on ${HOME}/.cache.")
    fi

    _pg_newest=0
    for _pg_witness in "$_pg_gate_file" "$_pg_state_file"; do
        [[ -f "$_pg_witness" ]] || continue
        _pg_mtime="$(stat -c %Y "$_pg_witness" 2>/dev/null)" || _pg_mtime=""
        if [[ "$_pg_mtime" =~ ^[0-9]+$ ]] && (( _pg_mtime > _pg_newest )); then
            _pg_newest="$_pg_mtime"
        fi
    done

    if (( _pg_newest == 0 )); then
        continue
    fi

    if [[ "$_pg_gate_name" == "postgres-sync-memories-gate" ]]; then
        # A file cannot have been written in the future. A clock stepped
        # backwards (an NTP correction, a VM restored from a snapshot, a
        # copy that kept its old stamp) leaves one dated ahead of PG_NOW,
        # and the subtraction below then yields a NEGATIVE age, which can
        # never exceed the window: the staleness rule falls silent for
        # exactly as long as the skew lasts — precisely the window in
        # which a dead cron would otherwise be caught. So the stamp counts
        # as "now" for the age, and the anomaly is reported, because a
        # check that cannot run is not a clean bill of health (the
        # archive-root rule above, applied here; eleventh re-audit
        # follow-up L6).
        #
        # Only this branch clamps. The hook gates below compare two files
        # to each other, which a skewed clock shifts equally, so the raw
        # stamp is the right one there.
        _pg_written="$_pg_newest"
        if (( _pg_written > PG_NOW )); then
            if (( _pg_written - PG_NOW > PG_FUTURE_TOLERANCE_SECONDS )); then
                GATE_LINES+=("[${_pg_gate_name%-gate} gate] its timestamp is $(( (_pg_written - PG_NOW) / 60 ))m in the FUTURE — this machine's clock has moved backwards since it was written, so the gate's age says nothing and the staleness check for it is OFF until a run rewrites it. A sync that had stopped would not be reported. Check the clock (timedatectl).")
            fi
            _pg_written="$PG_NOW"
        fi
        # Cron-written: silence itself is the signal, and the question is
        # only which silence we are measuring.
        #
        #   Gate written since boot → its own age against the stale
        #       window. Cron has been running and stopped.
        #   Gate older than the boot → the UPTIME against the grace. Cron
        #       has not run at all since the machine came up, and after a
        #       few minutes that is the whole story; waiting out the full
        #       stale window here only delays the news (tenth re-audit,
        #       finding M2, which is why the grace was inert before).
        if [[ -n "$PG_BOOT_EPOCH" ]] && (( PG_BOOT_EPOCH > _pg_written )); then
            _pg_age_minutes=$(( PG_UPTIME_SECONDS / 60 ))
            if (( _pg_age_minutes > PG_BOOT_GRACE_MINUTES )); then
                GATE_LINES+=("[${_pg_gate_name%-gate} gate] has not been written in the ${_pg_age_minutes}m since this machine booted — the sync runs every five minutes, so it is not running. Check the cron entry.")
            fi
        else
            _pg_age_minutes=$(( (PG_NOW - _pg_written) / 60 ))
            if (( _pg_age_minutes > PG_CRON_STALE_MINUTES )); then
                GATE_LINES+=("[${_pg_gate_name%-gate} gate] has not been written for ${_pg_age_minutes}m — the sync runs every five minutes, so it is not running. Check the cron entry.")
            fi
        fi
    else
        # Hook-written: only a session that ENDED without the hook
        # running is evidence. Wall-clock age is not — a long session, or
        # a fortnight away, leaves these untouched and nothing is wrong.
        if [[ -d "$PG_ARCHIVE_ROOT" ]]; then
            # -H so a SYMLINKED archive root is followed. find's default
            # is -P, which treats the root itself as a link, matches
            # nothing under it, and reports every hook as healthy for
            # ever (tenth re-audit, finding M3).
            _pg_late="$(find -H "$PG_ARCHIVE_ROOT" -name session.meta.json \
                -newermt "@$(( _pg_newest + PG_HOOK_LAG_MINUTES * 60 ))" \
                -print -quit 2>/dev/null)"
            if [[ -n "$_pg_late" ]]; then
                GATE_LINES+=("[${_pg_gate_name%-gate} gate] a session was archived more than ${PG_HOOK_LAG_MINUTES}m after this gate was last written (${_pg_late}) — the session hooks are not running. Check the PreCompact and SessionEnd hooks in ~/.claude/settings.json.")
            fi
        elif (( _pg_archive_reported == 0 )); then
            # A check that cannot run is not a clean bill of health, and
            # saying nothing is how a mistyped path becomes permanent
            # silence (tenth re-audit, finding M4).
            _pg_archive_reported=1
            GATE_LINES+=("[hook gates] liveness checking for the session sync and the content indexer is OFF: the archive root ${PG_ARCHIVE_ROOT} does not exist. A hook that stopped running would not be reported. Check the path, or set PA_CC_ARCHIVES.")
        fi
    fi

    _pg_count="$(head -1 "$_pg_gate_file" 2>/dev/null)"
    if [[ "$_pg_count" =~ ^[0-9]+$ ]] && [[ "$_pg_count" -gt 0 ]]; then
        # EVERY detail line, not just the first: since the fifth re-audit
        # these gates carry one line per INDEPENDENT problem (an outage,
        # a fault, quarantined rows, ...), and printing only the first
        # would silently drop the rest.
        GATE_LINES+=("[${_pg_gate_name%-gate} gate] ${_pg_count} problem(s):")
        while IFS= read -r _pg_line; do
            [[ -n "$_pg_line" ]] && GATE_LINES+=("  ${_pg_line}")
        done < <(tail -n +2 "$_pg_gate_file")
    fi
done
unset _pg_gate_name _pg_gate_file _pg_state_file _pg_count _pg_line
unset _pg_witness _pg_mtime _pg_newest _pg_written
unset _pg_uptime_raw _pg_uptime_rest
unset _pg_age_minutes _pg_late _pg_archive_reported

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
    relay "${GATE_LINES[@]}"
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
    if echo "$TODAY" > "$LOCK_FILE" 2>/dev/null; then
        echo "[daily-sync-trigger] sync complete" >&2
    else
        # Without the lock there is no once-a-day gate: the sync runs
        # again at EVERY session start, which is minutes of git per
        # session. A raw redirection error on stderr said none of that to
        # anyone who could act on it.
        echo "[daily-sync-trigger] could not write $LOCK_FILE" >&2
        relay "[daily-sync gate] the once-a-day lock ($LOCK_FILE) could not be written, so the sync will run again at EVERY session start until that path is writable."
    fi
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
            # audit (low, fourth re-audit): stderr never reaches the
            # session context — this script's own channel note says so —
            # and the sync's gate file explains WHY it failed but not that
            # it just failed again this minute. Put the exit code where
            # the session can see it. daily-sync.sh writes its reason into
            # the gate above; this is the "and it happened just now" half.
            relay "[daily-sync gate] the sync just failed (exit $rc); it will retry next session. See the daily-sync gate lines above for why, or logs/daily-sync.log."
            ;;
    esac
fi

exit 0
