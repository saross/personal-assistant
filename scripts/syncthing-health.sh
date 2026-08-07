#!/usr/bin/env bash
# syncthing-health.sh — make silent Syncthing failures loud.
#
# Background (2026-08-07): the whole four-device mesh had been dead since
# early May and nobody noticed for three months. Two independent silent
# failures stacked up:
#
#   1. rpi-server's container exited cleanly on 2026-05-06 with
#      `restart: 'no'`, so it never came back. Nothing reported it.
#   2. amd-tower's container was restarted on 2026-07-14 onto a DETACHED
#      bind mount — /config resolved to a different directory inode than
#      the host path in docker-compose.yml. It booted a stale default
#      config, advertised a DIFFERENT device ID (7OXIKQ7… instead of
#      TNOT4GW…), knew zero peers, and transferred zero bytes — while
#      `docker ps` cheerfully reported "Up 3 weeks".
#
# The lesson: "the process is running" is worthless as a health signal
# here. A Syncthing that has lost its identity looks perfectly healthy
# from the outside. So this script checks the things that actually
# distinguish a working node from a convincing impostor:
#
#   A. container running at all
#   B. bind liveness — host config dir and container /config are the SAME
#      inode (catches the detached-mount failure directly)
#   C. identity — the advertised device ID matches the one pinned in
#      data/config/syncthing-expected.json (catches a reset/stale config
#      even if the bind happens to be fine)
#   D. folder health — expected folder present, no errors, no pull errors
#   E. peer reachability — always-on peers (the rpi hub) must be connected;
#      laptops are allowed to be away
#   F. stuck sync — needBytes unchanged across runs for too long
#
# Output: writes ~/.cache/syncthing-gate. First line is the problem count
# (0 = healthy); remaining lines are one-per-problem descriptions. The
# SessionStart hook surfaces a non-zero count on EVERY session start,
# mirroring the cc-archives gate — silence is the enemy, so a healthy
# mesh prints nothing and a broken one nags every session.
#
# Usage:
#   scripts/syncthing-health.sh              # check, write gate, print summary
#   scripts/syncthing-health.sh --quiet      # write gate only (hook use)
#   scripts/syncthing-health.sh --local-only # skip SSH checks (travelling)
#
# Always exits 0 — a monitoring script must never break the hook chain
# or a session. The gate file carries the verdict, not the exit code.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PA_DIR="$(dirname "$SCRIPT_DIR")"
# Overridable so the self-test can point at a deliberately-broken copy and
# confirm each check actually fires. A monitor nobody has seen fail is not
# a monitor.
EXPECTED_FILE="${SYNCTHING_EXPECTED_FILE:-$PA_DIR/data/config/syncthing-expected.json}"
GATE_FILE="${HOME}/.cache/syncthing-gate"
STATE_FILE="${HOME}/.cache/syncthing-health-state.json"

QUIET=0
LOCAL_ONLY=0
# --simulate-need <bytes> exists purely so the stalled-transfer branch can be
# exercised on a healthy mesh (where needBytes is always 0). Test-only.
SIMULATE_NEED=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --quiet)         QUIET=1 ;;
        --local-only)    LOCAL_ONLY=1 ;;
        --simulate-need) SIMULATE_NEED="$2"; shift ;;
    esac
    shift
done

mkdir -p "$(dirname "$GATE_FILE")"

PROBLEMS=()

note_problem() {
    PROBLEMS+=("$1")
}

if [[ ! -f "$EXPECTED_FILE" ]]; then
    note_problem "expectations file missing ($EXPECTED_FILE) — cannot verify identities"
    printf '%s\n' "${#PROBLEMS[@]}" "${PROBLEMS[@]}" > "$GATE_FILE"
    [[ $QUIET -eq 0 ]] && printf '%s\n' "${PROBLEMS[@]}"
    exit 0
fi

# ---------------------------------------------------------------------------
# Helpers
#
# Every Syncthing query runs *inside* the container via `docker exec`, which
# sidesteps the GUI's TLS + CSRF handling (a plain HTTP call to :8384 returns
# "CSRF Error", which is easy to misread as a dead daemon).
# ---------------------------------------------------------------------------

# read_expected <jq-ish path> — pull a value out of the expectations JSON.
read_expected() {
    python3 -c "
import json, sys
d = json.load(open('$EXPECTED_FILE'))
for key in sys.argv[1:]:
    d = d.get(key) if isinstance(d, dict) else None
    if d is None:
        sys.exit(0)
print(d)
" "$@"
}

FOLDER_ID="$(read_expected folder_id)"

# run_on <ssh_host|""> <command…> — run locally, or over SSH when a host is
# given. Short timeouts: an unreachable machine is a skip, not a hang.
run_on() {
    local host="$1"; shift
    if [[ -z "$host" ]]; then
        bash -c "$*" 2>/dev/null
    else
        ssh -o ConnectTimeout=5 -o BatchMode=yes "$host" "$*" 2>/dev/null
    fi
}

# check_host <label> <ssh_host|""> <container> <config_dir> <expected_id> <always_on>
check_host() {
    local label="$1" host="$2" container="$3" config_dir="$4" expected_id="$5" always_on="$6"
    local prefix="[$label]"

    # Reachability first — an absent laptop is not a fault.
    if [[ -n "$host" ]]; then
        if ! run_on "$host" "true" >/dev/null 2>&1; then
            if [[ "$always_on" == "true" ]]; then
                note_problem "$prefix unreachable over SSH — cannot verify the always-on hub"
            fi
            return
        fi
    fi

    # --- A. container running -------------------------------------------
    local running
    running="$(run_on "$host" "docker inspect -f '{{.State.Running}}' $container 2>/dev/null")"
    if [[ "$running" != "true" ]]; then
        local finished
        finished="$(run_on "$host" "docker inspect -f '{{.State.FinishedAt}}' $container 2>/dev/null")"
        note_problem "$prefix container '$container' is NOT running (last exit: ${finished:-unknown}) — nothing is syncing here"
        return
    fi

    # --- B. bind liveness -----------------------------------------------
    # The failure that started all this: docker inspect still lists the bind,
    # but the container's /config is a different directory. Compare inodes
    # rather than trusting the mount table.
    local host_inode container_inode
    host_inode="$(run_on "$host" "stat -c %i $config_dir 2>/dev/null")"
    container_inode="$(run_on "$host" "docker exec $container stat -c %i /config 2>/dev/null")"
    if [[ -n "$host_inode" && -n "$container_inode" && "$host_inode" != "$container_inode" ]]; then
        note_problem "$prefix config bind is DETACHED — $config_dir (inode $host_inode) is not what the container sees at /config (inode $container_inode); it is running a stale config. Fix: docker compose down && docker compose up -d"
    fi

    # --- C. identity ------------------------------------------------------
    local actual_id
    actual_id="$(run_on "$host" "docker exec $container syncthing cli --home /config show system 2>/dev/null" \
        | python3 -c "import sys,json;print(json.load(sys.stdin).get('myID',''))" 2>/dev/null)"
    if [[ -z "$actual_id" ]]; then
        note_problem "$prefix could not read device ID from the running daemon"
        return
    fi
    if [[ "$actual_id" != "$expected_id" ]]; then
        note_problem "$prefix WRONG IDENTITY — advertising ${actual_id:0:7}… but the mesh expects ${expected_id:0:7}…; peers will refuse it and it will sync nothing"
        return
    fi

    # --- D/E/F. folder health, peers, progress ---------------------------
    # One CLI call each; parsed together so a partial failure still reports.
    local folders conns status
    folders="$(run_on "$host" "docker exec $container syncthing cli --home /config config folders list 2>/dev/null")"
    if ! grep -q "^${FOLDER_ID}$" <<<"$folders"; then
        note_problem "$prefix folder '$FOLDER_ID' is MISSING from the running config"
        return
    fi

    # Folder status has no `syncthing cli` equivalent in v1.29 (`operations
    # folder-status` does not exist — it errors out and returns nothing,
    # which would make this check silently vacuous). Go via the REST API
    # from inside the container instead: -k because the GUI serves a
    # self-signed cert, https because plain HTTP answers "CSRF Error".
    status="$(run_on "$host" "docker exec $container sh -c '
        KEY=\$(sed -n \"s|.*<apikey>\\(.*\\)</apikey>.*|\\1|p\" /config/config.xml)
        curl -sk -H \"X-API-Key: \$KEY\" \"https://localhost:8384/rest/db/status?folder=$FOLDER_ID\"
    ' 2>/dev/null")"
    if [[ -n "$status" ]]; then
        local parsed
        parsed="$(python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
print('%s|%s|%s|%s' % (d.get('state',''), d.get('errors',0), d.get('pullErrors',0), d.get('needBytes',0)))
" <<<"$status" 2>/dev/null)"
        if [[ -n "$parsed" ]]; then
            IFS='|' read -r f_state f_errors f_pull f_need <<<"$parsed"
            [[ "$f_state" == "error" ]] && note_problem "$prefix folder '$FOLDER_ID' is in an ERROR state"
            [[ "${f_errors:-0}" -gt 0 ]] && note_problem "$prefix folder '$FOLDER_ID' reports $f_errors error(s)"
            [[ "${f_pull:-0}" -gt 0 ]] && note_problem "$prefix folder '$FOLDER_ID' reports $f_pull pull error(s)"
            record_progress "$label" "${f_need:-0}"
        fi
    fi

    conns="$(run_on "$host" "docker exec $container syncthing cli --home /config show connections 2>/dev/null")"
    if [[ -n "$conns" ]]; then
        local offline
        offline="$(python3 -c "
import sys, json
exp = json.load(open('$EXPECTED_FILE'))
always = {h['expected_device_id'] for h in exp['hosts'].values() if h.get('always_on')}
names = exp['devices']
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
bad = [names.get(k, k[:7]) for k, v in d.get('connections', {}).items()
       if k in always and not v.get('connected')]
print(', '.join(bad))
" <<<"$conns" 2>/dev/null)"
        if [[ -n "$offline" ]]; then
            note_problem "$prefix cannot reach always-on peer(s): $offline"
        fi
    fi
}

# record_progress <label> <needBytes> — flag a transfer that has not moved.
# Syncthing can sit "syncing" forever on a permission or disk-space problem
# without ever raising a folder error, so compare against the last run.
record_progress() {
    local label="$1" need="$2"
    [[ -n "$SIMULATE_NEED" ]] && need="$SIMULATE_NEED"
    python3 - "$STATE_FILE" "$label" "$need" <<'PYEOF'
import json, os, sys, time
state_file, label, need = sys.argv[1], sys.argv[2], int(sys.argv[3] or 0)
state = {}
if os.path.exists(state_file):
    try:
        state = json.load(open(state_file))
    except Exception:
        state = {}
now = time.time()
prev = state.get(label)
if need == 0:
    state[label] = {"needBytes": 0, "since": now}
elif prev and prev.get("needBytes") == need:
    state[label] = prev                      # unchanged — keep the original timestamp
else:
    state[label] = {"needBytes": need, "since": now}
json.dump(state, open(state_file, "w"), indent=2)
PYEOF

    # Read back how long this figure has been stuck.
    local stuck_hours threshold
    threshold="$(read_expected thresholds stuck_sync_hours)"
    stuck_hours="$(python3 -c "
import json, sys, time
try:
    s = json.load(open('$STATE_FILE'))['$label']
except Exception:
    sys.exit(0)
if s.get('needBytes', 0) > 0:
    print(int((time.time() - s.get('since', time.time())) / 3600))
" 2>/dev/null)"
    if [[ -n "$stuck_hours" && -n "$threshold" ]] && (( stuck_hours >= threshold )); then
        note_problem "[$label] sync has not advanced in ${stuck_hours}h (still ${need} bytes behind) — stalled, not syncing"
    fi
}

# ---------------------------------------------------------------------------
# Run the checks
# ---------------------------------------------------------------------------

THIS_HOST="$(hostname)"

# Iterate the hosts in the expectations file. The local machine is checked
# directly; others only if they declare an ssh_host and --local-only is off.
while IFS='|' read -r label device_id container config_dir ssh_host always_on; do
    [[ -z "$label" ]] && continue
    if [[ "$label" == "$THIS_HOST" ]]; then
        check_host "$label" "" "$container" "$config_dir" "$device_id" "$always_on"
    elif [[ -n "$ssh_host" && $LOCAL_ONLY -eq 0 ]]; then
        check_host "$label" "$ssh_host" "$container" "$config_dir" "$device_id" "$always_on"
    fi
done < <(python3 -c "
import json
d = json.load(open('$EXPECTED_FILE'))
for label, h in d['hosts'].items():
    print('|'.join([
        label,
        h.get('expected_device_id', ''),
        h.get('container', 'syncthing'),
        h.get('config_dir', ''),
        h.get('ssh_host', ''),
        'true' if h.get('always_on') else 'false',
    ]))
")

# ---------------------------------------------------------------------------
# Write the gate
# ---------------------------------------------------------------------------

{
    printf '%s\n' "${#PROBLEMS[@]}"
    printf '%s\n' "checked $(date '+%Y-%m-%d %H:%M:%S') on $THIS_HOST"
    if [[ ${#PROBLEMS[@]} -gt 0 ]]; then
        printf '%s\n' "${PROBLEMS[@]}"
    fi
} > "$GATE_FILE"

if [[ $QUIET -eq 0 ]]; then
    if [[ ${#PROBLEMS[@]} -eq 0 ]]; then
        echo "syncthing-health: mesh OK (identities, binds, folder, peers all verified)"
    else
        echo "syncthing-health: ${#PROBLEMS[@]} problem(s)"
        printf '  - %s\n' "${PROBLEMS[@]}"
    fi
fi

exit 0
