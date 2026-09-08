#!/usr/bin/env bash
# daily-sync.sh — Daily multi-machine sync for personal-assistant + pa-data.
#
# Handles the common two-way sync pattern:
#   1. Each machine's extraction hook appends memories locally during the day.
#   2. At sync time, commit local captures, pull remote captures from the
#      other machine(s), resolve append-only conflicts automatically, push.
#
# Safe to run at any time. Invoked from the SessionStart hook via
# scripts/daily-sync-trigger.sh; also fine to run interactively.
#
# Usage:
#   scripts/daily-sync.sh              # normal sync
#   scripts/daily-sync.sh --dry-run    # show what would happen, no changes
#
# Exit codes:
#   0 — success (no-op or synced)
#   1 — another instance is running (flock busy)
#   2 — git operation failed unexpectedly
#   3 — merge-conflict resolver failed
#   4 — unexpected JSONL shrink detected (push aborted; see shrink report)
#
# Locking: uses flock on a file in the log dir to prevent concurrent runs.
# Logging: appends to logs/daily-sync.log on every invocation.

set -euo pipefail

# ---------------------------------------------------------------------------
# Paths and setup
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PA_DIR="$(dirname "$SCRIPT_DIR")"
DATA_DIR="$PA_DIR/data"
LOG_DIR="$PA_DIR/logs"
LOG_FILE="$LOG_DIR/daily-sync.log"
LOCK_FILE="$LOG_DIR/daily-sync.lock"
RESOLVER="$SCRIPT_DIR/resolve-merge-conflicts.py"

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=1
fi

# audit S19: an unwritable or missing log directory aborted the script
# under `set -e` with status 1 and no message of its own — and
# daily-sync-trigger.sh maps exit 1 to "lock contention (another sync /
# commit-data is running)", an actively wrong diagnosis for a broken
# checkout. Fail with the git-error code and say what is wrong. `log`
# cannot be used here: it writes to a file inside this directory.
if ! mkdir -p "$LOG_DIR" 2>/dev/null || [[ ! -w "$LOG_DIR" ]]; then
    echo "[daily-sync] ERROR: log directory $LOG_DIR is missing or not writable" >&2
    echo "[daily-sync] (is the data submodule initialised? logs/ is a symlink into it)" >&2
    exit 2
fi

# audit M4: the L4 fix for an unset HOME was applied to the trigger only.
# Here, `set -u` makes the first bare $HOME abort with "unbound variable"
# and status 1 — which the trigger then reports as lock contention — and
# an unwritable ~/.cache kills a HALF-COMPLETED run at a gate write, after
# commits and pushes have already happened. Every gate this script writes
# lives under ~/.cache, so check once, up front, and exit with the code
# that means "something is broken" rather than "someone else is running".
if [[ -z "${HOME:-}" ]]; then
    echo "[daily-sync] ERROR: HOME is unset; the gate files this script writes have nowhere to go" >&2
    exit 2
fi
# audit L2 (third re-audit): a HOME naming a directory that does not
# exist is as broken as an unset one, and `mkdir -p` below would silently
# conjure the whole path — writing gate files into a tree nothing else
# reads, on a machine whose home is (say) not yet mounted.
if [[ ! -d "$HOME" ]]; then
    echo "[daily-sync] ERROR: HOME ($HOME) is not a directory; refusing to create it" >&2
    exit 2
fi
CACHE_DIR="$HOME/.cache"
if ! mkdir -p "$CACHE_DIR" 2>/dev/null || [[ ! -w "$CACHE_DIR" ]]; then
    echo "[daily-sync] ERROR: $CACHE_DIR is missing or not writable; gate files cannot be written" >&2
    exit 2
fi

# ---------------------------------------------------------------------------
# Config (data/config/sync.json) — read with safe defaults. Rollback
# switches flip individual features without touching code.
# ---------------------------------------------------------------------------

CONFIG_FILE="$PA_DIR/data/config/sync.json"
read_cfg() {
    # read_cfg <key> <default>
    # Prints the config value on stdout. If jq parsing fails (e.g. the
    # file is corrupt), prints the default AND writes a warning to
    # stderr so the failure isn't silent.
    #
    # Audit 2026-05-02 E-Medium: previous implementation interpolated
    # both the key and default raw into the jq filter
    # (`(.${key} // ${default})`), which mishandled non-bareword defaults
    # (e.g. a string like "foo" parsed as a reference to bareword `foo`)
    # and was injection-shaped if the key ever came from external data.
    # Bind both via `--arg`: the key with dynamic-field syntax `.[$k]`,
    # and the default through jq's `//` operator. `fromjson?` lets the
    # default round-trip booleans / numbers / null when the underlying
    # value is the literal string equivalent.
    local key="$1" default="$2" value jq_stderr
    if ! command -v jq >/dev/null 2>&1 || [ ! -f "$CONFIG_FILE" ]; then
        printf '%s' "$default"
        return
    fi
    jq_stderr=$(mktemp)
    if value=$(jq -r --arg k "$key" --arg d "$default" \
            '.[$k] // $d' "$CONFIG_FILE" 2>"$jq_stderr"); then
        rm -f "$jq_stderr"
        printf '%s' "$value"
    else
        echo "[daily-sync] WARNING: could not parse $CONFIG_FILE; using default $default for $key" >&2
        cat "$jq_stderr" >&2
        rm -f "$jq_stderr"
        printf '%s' "$default"
    fi
}

RETRY_ON_REJECT="$(read_cfg retry_on_push_reject true)"
DETECT_JSONL_SHRINK="$(read_cfg detect_jsonl_shrink true)"
RETRY_ATTEMPTS=3
RETRY_BACKOFF=5

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

log() {
    local ts
    ts="$(date +'%Y-%m-%d %H:%M:%S')"
    printf '[%s] %s\n' "$ts" "$*" | tee -a "$LOG_FILE" >&2
}

fail() {
    # audit M3 (third re-audit): EVERY non-zero exit must leave a gate
    # line naming the reason. The rebase and push paths — a rebase on
    # unsupported paths, a push rejected three times, a pull that is not
    # fast-forwardable — all wedge the sync until a human intervenes, and
    # all of them exited 2 having written nothing but a log line and a
    # stderr message the SessionStart hook chain never surfaces.
    #
    # Blocks that raised a more specific gate keep it: this only fills the
    # gap. The gate itself is rendered once, at exit.
    log "ERROR: $*"
    # audit M1 (fourth re-audit): APPEND, unconditionally. Skipping when a
    # gate already existed meant the non-fatal withheld-bump gate — which
    # a healthy-ish run can raise — swallowed the reason for a real
    # failure later in the same run: sync-symlinks.sh failing left the
    # operator reading about a submodule pointer.
    add_sync_gate_detail "daily-sync FAILED and will keep failing until this is resolved: $*"
    exit "${2:-2}"
}

# ---------------------------------------------------------------------------
# Sync gate (audit S3/S17)
#
# Some failures leave a conflicted tree that every LATER run trips over as
# well, so the sync stops running at all until a human intervenes. A log
# line is not enough for that: this repo has three times found that a
# signal emitted but not surfaced is indistinguishable from no signal (see
# the channel-fix note in daily-sync-trigger.sh). Write the state to a gate
# file in the same layout as the other gates the trigger reads — first line
# a problem count, remaining lines the detail — so it is surfaced at every
# session start until the sync completes cleanly again.
# ---------------------------------------------------------------------------
SYNC_GATE="$CACHE_DIR/daily-sync-gate"
#: What this run did to its own stashes, so the NEXT run can say whose
#: markers a half-merged tree holds without guessing (audit C-B).
STASH_STATE_FILE="$CACHE_DIR/daily-sync-stash-state"

# audit C1 (fifth re-audit): the gate is built in MEMORY during the run and
# rendered exactly once, from the EXIT handler. Writers used to touch the
# file directly — some truncating it, some appending — so a wedged sync
# appended the same paragraph on every run and the trigger relayed all N
# copies, while a truncating writer could erase a diagnosis another block
# had just recorded. The file now reflects the problems of the LATEST run
# only, each exactly once; a clean run renders "0" and clears itself.
sync_gate_details=()
#: Set at the one point the run is known to have done all of its work.
#: Until then, anything it writes to the gate ADDS to what is already
#: there rather than replacing it: a run that stopped early cannot have
#: established that the previous run's findings are resolved.
sync_run_completed=0

add_sync_gate_detail() {
    # add_sync_gate_detail <detail>
    # Record a problem for this run. Order is preserved — the diagnosis of
    # what stopped the run has to reach the reader before any recovery
    # advice (audit L5) — and a repeat of something already recorded is
    # dropped rather than said twice.
    local detail="$1" existing
    for existing in ${sync_gate_details[@]+"${sync_gate_details[@]}"}; do
        [[ "$existing" == "$detail" ]] && return 0
    done
    sync_gate_details+=("$detail")
}

#: SHAs write_stash_state has already emitted a row for this run, so the
#: precedence below is applied once per ENTRY rather than once per record.
stash_state_written_shas=()

append_stash_state_row() {
    # append_stash_state_row <repo> <sha> <state> <newline-separated paths>
    #
    # One row per PATH — or a single path-less row for a state that
    # carries none — and nothing at all for a SHA a higher-precedence
    # state has already claimed, or for an entry no longer on the stack (a
    # stash that is gone cannot be the source of anything).
    local repo="$1" sha="$2" state="$3" paths="$4" written path
    for written in ${stash_state_written_shas[@]+"${stash_state_written_shas[@]}"}; do
        [[ "$written" == "$sha" ]] && return 0
    done
    stash_ref_for "$repo" "$sha" >/dev/null || return 0
    stash_state_written_shas+=("$sha")
    if [[ -z "$paths" ]]; then
        printf '%s\t%s\t%s\t\n' "$repo" "$sha" "$state" \
            >> "$STASH_STATE_FILE" 2>/dev/null || true
        return 0
    fi
    while IFS= read -r path; do
        [[ -n "$path" ]] || continue
        printf '%s\t%s\t%s\t%s\n' "$repo" "$sha" "$state" "$path" \
            >> "$STASH_STATE_FILE" 2>/dev/null || true
    done <<<"$paths"
    return 0
}

write_stash_state() {
    # One row per stash-and-path this run put into a working tree:
    #
    #     <repo><TAB><sha><TAB>partial|applied|conflicted<TAB><one path>
    #
    # audit C2 (ninth re-audit). A row names a stash TOGETHER WITH a path
    # it produced, so the next run can attribute markers path by path
    # instead of blaming whatever it finds. The file is unlinked first, so
    # an unwritable path cannot keep serving stale content, and a failure
    # to write is a warning: the next run then finds nothing and says so,
    # which is the safe direction.
    #
    # audit L1 (tenth re-audit): ONE PATH PER ROW. The paths used to be
    # comma-joined into one field and word-split on the way back, so
    # `notes/a b.md` and `notes/a,b.md` were each read as two paths,
    # matched nothing, and lost their attribution — for exactly the
    # filenames a human is most likely to create. A TAB-delimited field is
    # safe: git C-quotes any path holding a tab or a newline, and neither
    # a space nor a comma is a delimiter here.
    #
    # audit M3 (tenth re-audit): ONE STATE PER SHA, in the precedence
    # stranded_stashes uses on the read side — `partial` outranks
    # `applied` outranks `conflicted`. A conflicted-then-resolved entry
    # whose drop failed used to emit BOTH a conflicted row and an applied
    # row, and the stale conflicted row was then matched against an
    # unrelated conflict in the same path on a later run.
    local record sha repo paths
    if [[ $DRY_RUN -eq 1 ]]; then
        return 0
    fi
    mkdir -p "$(dirname "$STASH_STATE_FILE")" 2>/dev/null || true
    rm -f "$STASH_STATE_FILE" 2>/dev/null || true
    if ! : > "$STASH_STATE_FILE" 2>/dev/null; then
        log "WARNING: could not write $STASH_STATE_FILE; the next run will not be able to attribute any conflict markers to a stash"
        return 0
    fi
    stash_state_written_shas=()
    for record in ${partial_stash_records[@]+"${partial_stash_records[@]}"}; do
        sha="${record%%$'\t'*}"
        paths="${record##*$'\t'}"
        repo="${record#*$'\t'}"
        repo="${repo%%$'\t'*}"
        append_stash_state_row "$repo" "$sha" partial "$paths"
    done
    for sha in ${applied_stash_shas[@]+"${applied_stash_shas[@]}"}; do
        # An applied entry is never a marker source; the row exists so the
        # next run can say "this one's content is already in your tree",
        # and it carries no paths for exactly that reason.
        for repo in "$DATA_DIR" "$PA_DIR"; do
            stash_ref_for "$repo" "$sha" >/dev/null || continue
            append_stash_state_row "$repo" "$sha" applied ""
            break
        done
    done
    for record in ${conflicted_stash_records[@]+"${conflicted_stash_records[@]}"}; do
        sha="${record%%$'\t'*}"
        paths="${record##*$'\t'}"
        repo="${record#*$'\t'}"
        repo="${repo%%$'\t'*}"
        append_stash_state_row "$repo" "$sha" conflicted "$paths"
    done
    return 0
}

gate_line_class() {
    # gate_line_class <line>
    # The KIND of statement a gate line makes. A later run's line
    # supersedes an earlier one only when the two make the same kind of
    # statement about the same subject (audit M2, tenth re-audit): a SHA
    # in the text is not enough on its own, because a line may merely
    # LIST an entry it says nothing about.
    #
    # Matched on the phrases the gate writers below own. `unattributed`
    # is checked first because that line lists other stashes; `partial`
    # before `applied` because a partly-applied entry is also one that
    # was not dropped. Anything unrecognised is `other`, which carries no
    # key at all and therefore supersedes nothing.
    local line="$1"
    case "$line" in
        *"cannot identify"*)                        printf 'unattributed' ;;
        *"these markers ARE that stash's content"*) printf 'attribution' ;;
        *"only PARTLY"*|*"restored only part"*)     printf 'partial' ;;
        *"UNRECOVERED"*)                            printf 'unrecovered' ;;
        *"WITH CONFLICTS"*|*"did not apply cleanly"*|*" conflicted."*)
                                                    printf 'conflicted' ;;
        *"ALREADY unmerged"*|*"BLOCKED by an earlier"*)
                                                    printf 'blocked' ;;
        *"could not drop"*)                         printf 'applied' ;;
        *"REFUSED"*)                                printf 'refused' ;;
        *)                                          printf 'other' ;;
    esac
}

gate_sha_keys() {
    # gate_sha_keys <line> — `stash:<sha8>` for every SHA on the line.
    #
    # One namespace for every statement about the STATE of an entry
    # (`unrecovered`, `conflicted`, `blocked`, `applied`, `partial`,
    # `refused`, `attribution`), because those states are mutually
    # exclusive descriptions of one thing: a later run saying "its markers
    # are in your tree" must retire an earlier run's "its work is nowhere
    # else, pop it" (audit M1, ninth re-audit). What must NOT happen is a
    # line that merely LISTS an entry retiring a claim about it, and that
    # is decided by the class, not by the namespace.
    local line="$1" sha
    while read -r sha; do
        [[ -n "$sha" ]] && printf 'stash:%s\n' "$sha"
    done < <(grep -oE '\b[0-9a-f]{8}\b' <<<"$line" || true)
    return 0
}

gate_claim_keys() {
    # gate_claim_keys <line>
    # What THIS RUN's line claims, and may therefore supersede. A line
    # this cannot classify claims nothing — it neither supersedes nor is
    # protected, which is what the gate did before any of this existed.
    local line="$1" class
    class="$(gate_line_class "$line")"
    case "$class" in
        other)
            return 0
            ;;
        unattributed)
            # Deliberately claims no SHA: the SHAs on this line are a
            # listing of what is on the stack, not a claim about any of
            # them (audit M2, tenth re-audit). Its own singleton key means
            # a later "cannot identify" replaces an earlier one.
            printf 'unattributed\n'
            return 0
            ;;
        attribution)
            # Attribution is exactly the resolution of "cannot identify"
            # for the same markers, so it retires that line too.
            printf 'unattributed\n'
            ;;
    esac
    gate_sha_keys "$line"
    return 0
}

gate_subject_keys() {
    # gate_subject_keys <line>
    # What a PREVIOUS run's line is about, and may therefore be superseded
    # on. Unlike a claim, an unclassifiable line still has a subject: an
    # earlier run's free-text line naming a stash is retired by this run's
    # word about that stash.
    local line="$1"
    if [[ "$(gate_line_class "$line")" == "unattributed" ]]; then
        printf 'unattributed\n'
        return 0
    fi
    gate_sha_keys "$line"
    return 0
}

render_sync_gate() {
    # Write the gate file: first line a problem count, then one line per
    # problem. Never fatal — a gate that cannot be written must not turn a
    # working sync into a failing one, and every call site logs as well.
    #
    # Never under --dry-run: the usage banner promises no changes, and a
    # dry run that left a gate behind would nag at every session start.
    #
    # audit C1 (sixth re-audit): and NEVER when this run has nothing to
    # say. Writing an empty gate from the EXIT trap meant a run that did
    # no work — lock contention, a SIGTERM, a Ctrl-C — cleared a wedge a
    # previous run had raised, and the trigger reads the gate BEFORE
    # starting the sync, so the next session start was silent while the
    # tree was still wedged. Clearing is a separate act, and only the one
    # place that knows the run finished everything may do it.
    if [[ $DRY_RUN -eq 1 ]] || [[ ${#sync_gate_details[@]} -eq 0 ]]; then
        return 0
    fi
    # A run that did not COMPLETE — interrupted, or failed part-way — has
    # not established that the problems a previous run recorded are gone,
    # so it adds to them rather than replacing them (audit M1, seventh
    # re-audit: a failing run used to erase the previous run's "was
    # interrupted mid-rebase" line, which was the only record of why the
    # tree was in the state it was). A run that got to the end replaces:
    # its findings are current. Repeats are dropped either way.
    if [[ $sync_run_completed -eq 0 ]] && [[ -f "$SYNC_GATE" ]]; then
        local -a _ours=("${sync_gate_details[@]}")
        local _previous _mine _keys _our_keys=""
        # audit M1 (ninth re-audit): this run's word about a given stash
        # supersedes an earlier run's. Keeping both left contradictory
        # advice about the same SHA standing side by side — "pop it" from
        # one run and "delete it" from the next.
        #
        # audit M2 (tenth re-audit): but only when both lines make the
        # SAME KIND of claim about that stash. The SHAs used to be
        # harvested from the whole line, so the generic "this run cannot
        # identify these markers" line — which LISTS every entry on the
        # stack precisely because it can attribute nothing — superseded
        # every still-true, specific line about every one of them. A
        # blocked stash's "its work is nowhere else" survived exactly one
        # further run before a line that said nothing about it erased it.
        for _mine in "${_ours[@]}"; do
            _keys="$(gate_claim_keys "$_mine")"
            [[ -n "$_keys" ]] && _our_keys+="$_keys"$'\n'
        done
        sync_gate_details=()
        while IFS= read -r _previous; do
            [[ -n "$_previous" ]] || continue
            _keys="$(gate_subject_keys "$_previous")"
            if [[ -n "$_keys" ]] && [[ -n "$_our_keys" ]] \
                    && printf '%s\n' "$_keys" \
                        | grep -qxF -f <(printf '%s' "$_our_keys"); then
                continue
            fi
            add_sync_gate_detail "$_previous"
        done < <(tail -n +2 "$SYNC_GATE" 2>/dev/null || true)
        for _previous in "${_ours[@]}"; do
            add_sync_gate_detail "$_previous"
        done
    fi
    mkdir -p "$(dirname "$SYNC_GATE")" 2>/dev/null || true
    printf '%s\n' "${#sync_gate_details[@]}" \
        "${sync_gate_details[@]}" \
        > "$SYNC_GATE" 2>/dev/null || true
}

clear_sync_gate() {
    # Called from ONE place: the end of the script, where the run is known
    # to have completed every step. Not from the trap — an interrupted or
    # contended run has not established that anything is fixed.
    if [[ $DRY_RUN -eq 1 ]] || [[ ${#sync_gate_details[@]} -gt 0 ]]; then
        return 0
    fi
    mkdir -p "$(dirname "$SYNC_GATE")" 2>/dev/null || true
    printf '0\n' > "$SYNC_GATE" 2>/dev/null || true
    return 0
}

on_signal() {
    # on_signal <name> <status>
    # A killed run leaves the tree mid-operation; SessionStart's 90 s
    # timeout makes that a routine event, not a hypothetical. Exit on a
    # status the trigger will not mistake for benign lock contention (1),
    # and leave a gate line saying what happened — the EXIT trap renders
    # it on the way out.
    local name="$1" status="$2"
    log "INTERRUPTED by $name — exiting $status"
    add_sync_gate_detail \
        "daily-sync was INTERRUPTED by $name before it finished. The tree may be mid-operation and a stash it pushed may still be on the stack: check git -C $DATA_DIR status and git -C $DATA_DIR stash list before the next session."
    exit "$status"
}
trap 'on_signal SIGINT 130' INT
trap 'on_signal SIGTERM 143' TERM

# Render on the way out, however the run ends. This early trap covers the
# failures that happen before the stash machinery exists — an uninitialised
# submodule, an unopenable lock — which would otherwise exit having recorded
# a reason nobody ever sees. It is replaced further down by the full EXIT
# handler, which renders the gate as its own last act.
render_on_early_exit() {
    # The early trap renders the gate, and nothing else.
    #
    # audit M1 (tenth re-audit): it used to call write_stash_state too,
    # before the stash arrays that function reads exist — so the very run
    # that READ the sidecar (check_interrupted_state, naming whose markers
    # a half-merged tree holds) truncated it on the way out, and the next
    # run decayed to the generic "this run cannot identify" wording. The
    # sidecar is rewritten only from the full EXIT handler, after this
    # run's own stash bookkeeping has run. A row left standing costs
    # nothing: previously_recorded_stashes drops any row whose entry has
    # left the stack or whose path is not unmerged now.
    #
    # audit M1 (eleventh re-audit): with ONE exception. Two blocks record
    # a partly-applied entry BEFORE the full handler exists —
    # carry_forward_partial_stashes and reconcile_orphaned_stashes, the
    # second of which then `fail`s — and their finding is the only record
    # that a file is in no commit and no tree. Without this the next clean
    # run erases it.
    local -a _pending=(${partial_stash_records[@]+"${partial_stash_records[@]}"})
    if [[ ${#_pending[@]} -gt 0 ]]; then
        write_stash_state
    fi
    render_sync_gate
}
trap render_on_early_exit EXIT

# ---------------------------------------------------------------------------
# push_with_retry — push the current branch, rebasing on rejection.
#
# On non-fast-forward rejection (race with another machine's push), the
# function fetches origin, runs `git pull --rebase`, and re-pushes up to
# RETRY_ATTEMPTS times. Conflict resolution differs by repo:
#   - Data submodule: JSONL/vocab conflicts go through the append-safe
#     resolver (scripts/resolve-merge-conflicts.py). Any other file is
#     considered unknown and aborts.
#   - Parent repo: submodule-pointer conflicts on `data` are resolved by
#     taking our version (we just pushed the data submodule, so our
#     bump-to-new-SHA is authoritative over origin's stale pointer).
#     Any other file aborts.
#
# Config: retry_on_push_reject=false disables retry and preserves the
# original fail-fast behaviour.
#
# Must be called from inside the repository that is being pushed.
# ---------------------------------------------------------------------------
push_with_retry() {
    local context="$1"  # "data submodule" or "parent repo"
    local attempt
    for attempt in $(seq 1 "$RETRY_ATTEMPTS"); do
        if git push origin main >>"$LOG_FILE" 2>&1; then
            log "$context: pushed to origin (attempt $attempt/$RETRY_ATTEMPTS)"
            return 0
        fi
        if [[ "$RETRY_ON_REJECT" != "true" ]]; then
            fail "$context push failed (retry disabled — manual resolution required)"
        fi
        if [[ "$attempt" -eq "$RETRY_ATTEMPTS" ]]; then
            fail "$context push failed after $RETRY_ATTEMPTS attempts (diverged remote — manual resolution required)"
        fi
        log "$context push attempt $attempt/$RETRY_ATTEMPTS rejected — fetching + rebasing"
        git fetch origin main >>"$LOG_FILE" 2>&1 \
            || fail "$context: fetch failed during retry"
        # GIT_EDITOR=true prevents the commit-message editor from opening
        # during rebase --continue on git versions that ignore
        # core.editor for that specific path.
        if ! GIT_EDITOR=true git pull --rebase origin main >>"$LOG_FILE" 2>&1; then
            log "$context: rebase raised conflicts — resolving"
            local -a rebase_conflicts=()
            while IFS= read -r _line; do
                if [[ "$_line" =~ ^(UU|AA|DD|AU|UA|DU|UD)\ (.+)$ ]]; then
                    rebase_conflicts+=("${BASH_REMATCH[2]}")
                fi
            done < <(git status --porcelain)
            if [[ ${#rebase_conflicts[@]} -eq 0 ]]; then
                git rebase --abort >>"$LOG_FILE" 2>&1 || true
                fail "$context: rebase failed but no unmerged paths detected — manual intervention needed"
            fi
            # Partition conflicts: JSONL/vocab go to the resolver; the
            # `data` submodule pointer is resolved by trust-ours; any
            # other path aborts.
            local -a jsonl_conflicts=()
            local -a submodule_conflicts=()
            local -a unknown_conflicts=()
            local _f
            for _f in "${rebase_conflicts[@]}"; do
                if is_memory_append_file "$_f"; then
                    jsonl_conflicts+=("$_f")
                elif [[ "$_f" == "data" ]]; then
                    submodule_conflicts+=("$_f")
                else
                    unknown_conflicts+=("$_f")
                fi
            done
            if [[ ${#unknown_conflicts[@]} -gt 0 ]]; then
                git rebase --abort >>"$LOG_FILE" 2>&1 || true
                fail "$context: rebase produced conflicts on unsupported paths (${unknown_conflicts[*]}) — manual resolution required"
            fi
            if [[ ${#jsonl_conflicts[@]} -gt 0 ]]; then
                local -a jsonl_paths=()
                for _f in "${jsonl_conflicts[@]}"; do
                    jsonl_paths+=("$(pwd)/$_f")
                done
                timeout 60 "$PA_DIR/venv/bin/python3" "$RESOLVER" --quiet-if-clean \
                    "${jsonl_paths[@]}" >>"$LOG_FILE" 2>&1 \
                    || { git rebase --abort >>"$LOG_FILE" 2>&1 || true; fail "$context: resolver failed during rebase" 3; }
                # audit C2: the same invariant on the rebase path. The
                # list is captured BEFORE the abort restores the tree
                # (audit M2), because after it there is nothing to find.
                memory_files_with_markers
                if [[ ${#MEMORY_MARKER_RECORDS[@]} -gt 0 ]]; then
                    local -a _marked=()
                    _marked=("${MEMORY_MARKER_RECORDS[@]}")
                    git rebase --abort >>"$LOG_FILE" 2>&1 || true
                    refuse_memory_markers "$context rebase" "${_marked[@]}"
                fi
                git add "${jsonl_conflicts[@]}" >>"$LOG_FILE" 2>&1 \
                    || { git rebase --abort >>"$LOG_FILE" 2>&1 || true; fail "$context: git add after resolver failed"; }
            fi
            if [[ ${#submodule_conflicts[@]} -gt 0 ]]; then
                # Our bump-to-new-SHA is authoritative because we just
                # pushed the submodule; origin's pointer is stale.
                #
                # audit S4: during a rebase git-checkout(1) defines
                # --ours as the branch being rebased ONTO (origin) and
                # --theirs as the work being replayed (ours), so --ours
                # named the stale side — the opposite of the comment
                # above. (For a gitlink the flag decides nothing either
                # way: neither form touches the index, and the `git add`
                # below records the submodule's checked-out HEAD. Use
                # the flag that means what it says regardless.)
                for _f in "${submodule_conflicts[@]}"; do
                    git checkout --theirs -- "$_f" >>"$LOG_FILE" 2>&1 \
                        || { git rebase --abort >>"$LOG_FILE" 2>&1 || true; fail "$context: checkout --theirs failed on $_f"; }
                    git add "$_f" >>"$LOG_FILE" 2>&1 \
                        || { git rebase --abort >>"$LOG_FILE" 2>&1 || true; fail "$context: git add after trust-ours failed"; }
                done
            fi
            GIT_EDITOR=true git rebase --continue >>"$LOG_FILE" 2>&1 \
                || { git rebase --abort >>"$LOG_FILE" 2>&1 || true; fail "$context: rebase --continue failed"; }
            log "$context: rebase conflicts resolved (${rebase_conflicts[*]})"
        fi
        sleep "$RETRY_BACKOFF"
    done
    # Defensive: loop should have returned or failed by now
    fail "$context push: retry loop exited abnormally"
}

# ---------------------------------------------------------------------------
# Lock (prevents overlap with a concurrent invocation on this machine)
# ---------------------------------------------------------------------------

# audit S19: a failed redirect here aborts with status 1, which the
# trigger would report as lock contention. The writability check above
# makes that unlikely; check anyway so the diagnosis is never wrong.
if ! exec 9>"$LOCK_FILE"; then
    fail "cannot open lock file $LOCK_FILE"
fi
if ! flock -n 9; then
    log "Another daily-sync is running (lock held). Exiting."
    exit 1
fi

HOST="$(hostname -s)"
log "=== daily-sync start on $HOST (dry-run=$DRY_RUN) ==="

# ---------------------------------------------------------------------------
# Append-only memory files.
#
# These are dirty on essentially every run (the extraction hook appends to
# them continuously), which is why the stash below exists at all. They are
# append-only, so committing them is always safe — unlike prose files such
# as wiki/continuity.md or tasks/inbox.md, which a concurrent Claude session
# may be part-way through editing and which must never be swept into an
# automatic commit (see CLAUDE.md, "Concurrent sessions").
# ---------------------------------------------------------------------------
MEMORY_APPEND_FILES=(memories/memories.jsonl memories/tag-vocabulary.txt)

is_memory_append_file() {
    # is_memory_append_file <path>
    # True for a path the append-safe resolver may union — i.e. one of
    # MEMORY_APPEND_FILES. audit L1: three conflict partitions each
    # repeated that list as a literal `case` pattern, so adding a file to
    # the array above would have silently left all three routing it to
    # "unsupported" (or, worse, one of them to the resolver).
    local candidate="$1" known
    for known in "${MEMORY_APPEND_FILES[@]}"; do
        [[ "$candidate" == "$known" ]] && return 0
    done
    return 1
}

venv_python_checked=0
#: Set by memory_files_with_markers; one `path<TAB>line<TAB>text` record per
#: problem, or `path<TAB>resolvable<TAB>` for a file the resolver can fix.
MEMORY_MARKER_RECORDS=()

require_venv_python() {
    # audit C3 (sixth re-audit): a missing or broken venv interpreter made
    # every `--check` fail, which the guard then reported as a verdict
    # about the corpus — accusing a clean file of holding conflict markers
    # and telling the operator to edit lines that are not there. Establish
    # that the interpreter runs before anything is concluded from it.
    [[ $venv_python_checked -eq 1 ]] && return 0
    if ! "$PA_DIR/venv/bin/python3" -c 'pass' >/dev/null 2>&1; then
        add_sync_gate_detail \
            "daily-sync STOPPED: the virtual environment interpreter $PA_DIR/venv/bin/python3 is missing or will not run, so the corpus cannot be checked. This says NOTHING about memories.jsonl. Run setup.sh (or repair the venv), then run the sync again."
        fail "venv interpreter $PA_DIR/venv/bin/python3 is missing or broken; refusing to judge the corpus without it"
    fi
    venv_python_checked=1
    return 0
}

memory_files_with_markers() {
    # Print one TAB-separated record per problem the corpus has:
    #
    #     <path><TAB><line number><TAB><what is wrong>       (needs a human)
    #     <path><TAB>resolvable<TAB>                         (run the resolver)
    #
    # Must be called from inside the data submodule.
    #
    # Content, not index state (audit C2, second re-audit): reading the
    # porcelain code meant a marker-laden memories.jsonl that somebody had
    # `git add`ed looked like a plain modification and was committed.
    #
    # The classification is the RESOLVER's, via `--check` (audit C2, fifth
    # re-audit): the two used to keep separate patterns and disagree, which
    # wedged the sync behind advice to run a resolver that then declined.
    #
    # audit C2 (sixth re-audit): only 0, 1, and 3 say anything about the
    # corpus. Every other code means the CHECKER failed — an undecodable
    # byte used to exit 1 through an uncaught traceback, so the sync gated
    # the traceback as "marker-shaped lines" and parsed its lines as paths.
    # It sets MEMORY_MARKER_RECORDS rather than printing, because a caller
    # capturing it with $( ) would run the whole thing in a SUBSHELL —
    # where an added gate line is discarded and a `fail` exits nothing but
    # the subshell. Found while wiring the checker-failure path.
    local f detail errors rc _record
    MEMORY_MARKER_RECORDS=()
    require_venv_python
    # An unguarded `mktemp` failure aborts under set -e with status 1,
    # which daily-sync-trigger.sh reports as benign lock contention.
    errors="$(mktemp 2>/dev/null)" || fail "could not create a temporary file for the corpus check"
    for f in "${MEMORY_APPEND_FILES[@]}"; do
        [[ -f "$f" ]] || continue
        rc=0
        # audit (low, seventh re-audit): bounded. This runs inside a
        # SessionStart hook with a 90 s budget; a checker that hangs would
        # take the whole session with it. A timeout is a checker failure,
        # not a corpus verdict — `timeout` exits 124, which the `*)` arm
        # below already treats as one.
        detail="$(timeout 60 "$PA_DIR/venv/bin/python3" "$RESOLVER" --check "$f" 2>"$errors")" || rc=$?
        case "$rc" in
            0)
                ;;
            1)
                MEMORY_MARKER_RECORDS+=("$(printf '%s\tresolvable\t' "$f")")
                ;;
            3)
                # The resolver's own records, passed through untouched.
                while IFS= read -r _record; do
                    [[ -n "$_record" ]] && MEMORY_MARKER_RECORDS+=("$_record")
                done <<<"$detail"
                ;;
            2)
                log "corpus check: $f vanished between the status scan and the check"
                ;;
            127)
                # audit (low, eighth re-audit): 127 is "could not execute",
                # which here means the `timeout` binary or the interpreter
                # is missing — a broken toolchain, not a broken checker,
                # and certainly nothing about the corpus.
                add_sync_gate_detail \
                    "daily-sync STOPPED: could not run the corpus check on $f — a required tool is missing (exit 127; the 'timeout' binary and $PA_DIR/venv/bin/python3 are what it needs): $(tr '\n' ' ' <"$errors"). This says NOTHING about the file's contents. Install the missing tool, then run the sync again."
                rm -f "$errors"
                fail "corpus check could not be run on $f (exit 127: a required tool is missing)"
                ;;
            *)
                add_sync_gate_detail \
                    "daily-sync STOPPED: the corpus checker itself failed on $f (exit $rc): $(tr '\n' ' ' <"$errors"). This says NOTHING about the file's contents — do not edit it on the strength of this. Fix the checker, then run the sync again."
                rm -f "$errors"
                fail "corpus check failed on $f (exit $rc); refusing to guess at its contents"
                ;;
        esac
    done
    rm -f "$errors"
    return 0
}

refuse_memory_markers() {
    # refuse_memory_markers <what-was-about-to-happen> <records>
    # The invariant: no append-only memory file whose content holds a
    # conflict marker is ever staged or committed, by any block. Every
    # consumer of memories.jsonl parses it as JSONL, so a published marker
    # breaks extraction, recall, and the drift check on both machines at
    # once — and the corpus is append-only, so nothing later repairs it.
    #
    # The records are passed in rather than re-scanned (audit M2, third
    # re-audit): the rebase call sites have to `git rebase --abort` first,
    # which restores the working tree and takes the markers with it.
    #
    # audit C2 (sixth re-audit): ONLY well-formed `path<TAB>line<TAB>text`
    # records are read. Anything else — a traceback, a stray warning — is
    # ignored rather than parsed as a file path.
    local context="$1"
    shift
    local line path field text
    local -a resolvable=() manual=() details=() unparsed=()
    for line in "$@"; do
        [[ -n "$line" ]] || continue
        if [[ "$line" != *$'\t'*$'\t'* ]]; then
            unparsed+=("$line")
            continue
        fi
        path="${line%%$'\t'*}"
        field="${line#*$'\t'}"
        text="${field#*$'\t'}"
        field="${field%%$'\t'*}"
        if [[ -z "$path" ]]; then
            unparsed+=("$line")
        elif [[ "$field" == "resolvable" ]]; then
            resolvable+=("$path")
        elif [[ "$field" =~ ^[0-9]+$ ]]; then
            manual+=("$path")
            details+=("$path line $field: $text")
        else
            # audit M3 (seventh re-audit): FAIL CLOSED. A record this
            # cannot read is a reason to refuse, never a reason to
            # proceed: dropping it silently meant a corpus whose only
            # problem was on line 13 was staged and pushed when the line
            # number failed a too-narrow pattern.
            unparsed+=("$line")
        fi
    done
    if [[ ${#unparsed[@]} -gt 0 ]]; then
        add_sync_gate_detail \
            "daily-sync STOPPED: the corpus checker returned ${#unparsed[@]} record(s) this script could not read — ${unparsed[*]}. Refusing to stage anything on the strength of a verdict it does not understand. This is a bug in the sync, not in your corpus."
        fail "$context: unreadable record(s) from the corpus check; refusing to stage or commit"
    fi
    if [[ ${#resolvable[@]} -eq 0 ]] && [[ ${#manual[@]} -eq 0 ]]; then
        return 0
    fi
    # audit C2 (fifth re-audit): the advice has to match what the resolver
    # will actually do. Telling the operator to run it on a file it refuses
    # is what wedged a sync permanently.
    if [[ ${#manual[@]} -gt 0 ]]; then
        add_sync_gate_detail \
            "daily-sync STOPPED: ${manual[*]} hold marker-shaped lines the resolver will NOT touch — ${details[*]}. Edit those LINES by hand in $DATA_DIR, then run the sync again. Do NOT run resolve-merge-conflicts.py on them (it refuses, by design) and do NOT 'git add' them."
    fi
    if [[ ${#resolvable[@]} -gt 0 ]]; then
        add_sync_gate_detail \
            "daily-sync STOPPED: ${resolvable[*]} hold unresolved conflict blocks. Resolve with: $PA_DIR/venv/bin/python3 $SCRIPT_DIR/resolve-merge-conflicts.py ${resolvable[*]/#/$DATA_DIR/} — then run the sync again. Do NOT 'git add' them by hand: staging markers is how they reach origin."
    fi
    fail "$context: ${manual[*]-}${resolvable[*]-} hold conflict markers; refusing to stage or commit them"
}

refuse_if_memory_markers() {
    # refuse_if_memory_markers <what-was-about-to-happen>
    # Scan now and refuse if anything is marked. Only for call sites that
    # do not disturb the working tree first.
    local context="$1"
    memory_files_with_markers
    if [[ ${#MEMORY_MARKER_RECORDS[@]} -gt 0 ]]; then
        refuse_memory_markers "$context" "${MEMORY_MARKER_RECORDS[@]}"
    fi
    return 0
}

# ---------------------------------------------------------------------------
# resolve_rebase_conflicts — shared conflict partitioning for rebase paths.
#
# Routes memories.jsonl / tag-vocabulary.txt to the append-safe resolver and
# the `data` submodule pointer to trust-ours; ANY other conflicted path is
# unsupported and aborts, because silently guessing on a prose file is how
# a concurrent session's work gets destroyed.
#
# Returns 0 if the rebase was carried to completion, non-zero after aborting.
# Must be called from inside the repository being rebased.
# ---------------------------------------------------------------------------
resolve_rebase_conflicts() {
    local context="$1"
    local -a conflicts=() jsonl=() submodule=() unknown=()
    local _line _f
    while IFS= read -r _line; do
        if [[ "$_line" =~ ^(UU|AA|DD|AU|UA|DU|UD)\ (.+)$ ]]; then
            conflicts+=("${BASH_REMATCH[2]}")
        fi
    done < <(git status --porcelain)
    if [[ ${#conflicts[@]} -eq 0 ]]; then
        git rebase --abort >>"$LOG_FILE" 2>&1 || true
        log "$context: rebase failed with no unmerged paths — aborted"
        return 1
    fi
    for _f in "${conflicts[@]}"; do
        if is_memory_append_file "$_f"; then
            jsonl+=("$_f")
        elif [[ "$_f" == "data" ]]; then
            submodule+=("$_f")
        else
            unknown+=("$_f")
        fi
    done
    if [[ ${#unknown[@]} -gt 0 ]]; then
        git rebase --abort >>"$LOG_FILE" 2>&1 || true
        log "$context: rebase conflicts on unsupported paths (${unknown[*]}) — aborted"
        return 1
    fi
    if [[ ${#jsonl[@]} -gt 0 ]]; then
        local -a paths=()
        for _f in "${jsonl[@]}"; do paths+=("$(pwd)/$_f"); done
        if ! timeout 60 "$PA_DIR/venv/bin/python3" "$RESOLVER" --quiet-if-clean \
                "${paths[@]}" >>"$LOG_FILE" 2>&1; then
            git rebase --abort >>"$LOG_FILE" 2>&1 || true
            log "$context: resolver failed during rebase — aborted"
            return 1
        fi
        # audit C2: never stage a marker, on any path. Captured before
        # the abort restores the tree (audit M2).
        local -a marked_before_abort=()
        memory_files_with_markers
        if [[ ${#MEMORY_MARKER_RECORDS[@]} -gt 0 ]]; then
            marked_before_abort=("${MEMORY_MARKER_RECORDS[@]}")
            git rebase --abort >>"$LOG_FILE" 2>&1 || true
            refuse_memory_markers "$context rebase" "${marked_before_abort[@]}"
        fi
        git add "${jsonl[@]}" >>"$LOG_FILE" 2>&1 || {
            git rebase --abort >>"$LOG_FILE" 2>&1 || true; return 1; }
    fi
    # audit S4: --theirs is our side during a rebase (see the twin site in
    # push_with_retry); the `git add` is what actually fixes a gitlink.
    for _f in "${submodule[@]}"; do
        git checkout --theirs -- "$_f" >>"$LOG_FILE" 2>&1 && \
            git add "$_f" >>"$LOG_FILE" 2>&1 || {
                git rebase --abort >>"$LOG_FILE" 2>&1 || true; return 1; }
    done
    GIT_EDITOR=true git rebase --continue >>"$LOG_FILE" 2>&1 || {
        git rebase --abort >>"$LOG_FILE" 2>&1 || true
        log "$context: rebase --continue failed — aborted"; return 1; }
    log "$context: rebase conflicts resolved (${conflicts[*]})"
    return 0
}

# ---------------------------------------------------------------------------
# Stash bookkeeping (audit C1)
#
# A run can push MORE THAN ONE stash. The branch-switch guard below stashes
# on a detached HEAD, and the pre-pull block stashes again if anything went
# dirty in between — a concurrent session writing tasks/inbox.md, or the
# agent-mail archiver leaving files behind. The previous single boolean plus
# a single `git stash pop` popped only the newest and silently left the
# older one on the stack, with the day's memory appends inside it, while the
# run exited 0 and cleared the gate.
#
# Every stash a run pushes is now recorded BY COMMIT SHA:
#   - nothing is popped that this run did not push (a plain `git stash pop`
#     takes whatever is on top, which may be a concurrent session's);
#   - the index is re-resolved before each pop, because indices shift;
#   - they are popped oldest-first, which is the order the changes were
#     made. Note what this does NOT buy: two stashes that touch the same
#     file do not merge. The first pop restores the file and git REFUSES
#     the second ("your local changes would be overwritten"), whichever
#     order they are tried in. Ordering only decides which of the two is
#     left on the stack — and the EXIT handler gates that one by SHA.
# ---------------------------------------------------------------------------
data_stash_shas=()
parent_stash_shas=()

push_stash() {
    # push_stash <repo> <message> [pathspec ...]
    # Stash <repo>'s working tree (untracked files included) and print the
    # new entry's commit SHA. Returns non-zero if the push failed, or if it
    # did not actually create an entry.
    #
    # audit M3: `git stash push` exits 0 when it saves NOTHING — a pathspec
    # that matches no dirty file, a tree whose only change is one stash
    # cannot take — and refs/stash then still points at whatever was on top
    # before, which may be a concurrent session's stash. Returning that SHA
    # would make this run pop and drop somebody else's work. Compare
    # refs/stash before and after, and accept only a genuinely new entry.
    local repo="$1" message="$2"
    shift 2
    local before after
    before="$(git -C "$repo" rev-parse --verify --quiet refs/stash || true)"
    git -C "$repo" stash push -u -m "$message" "$@" >>"$LOG_FILE" 2>&1 || return 1
    after="$(git -C "$repo" rev-parse --verify --quiet refs/stash || true)"
    [[ -n "$after" ]] || return 1
    [[ "$after" != "$before" ]] || return 1
    printf '%s' "$after"
}

stash_ref_for() {
    # stash_ref_for <repo> <sha>
    # Print the `stash@{n}` selector that currently names <sha>, or return
    # non-zero if that entry is no longer on the stack (already popped, or
    # dropped by hand between our push and our pop).
    local repo="$1" want="$2" line
    while IFS= read -r line; do
        if [[ "${line%% *}" == "$want" ]]; then
            printf '%s' "${line#* }"
            return 0
        fi
    done < <(git -C "$repo" stash list --format='%H %gd')
    return 1
}

apply_stash_by_sha() {
    # apply_stash_by_sha <repo> <sha>
    # Apply the stash entry named by <sha>. A stash entry is a commit, so
    # this cannot be aimed at the wrong one — unlike a `stash@{n}`
    # selector, which is a POSITION and is re-read by git at the moment
    # the command runs. Returns git's own exit status: non-zero means the
    # apply conflicted or was refused, and git preserves the entry.
    git -C "$1" stash apply "$2" >>"$LOG_FILE" 2>&1
}

drop_stash_by_sha() {
    # drop_stash_by_sha <repo> <sha>
    # Drop the entry named by <sha>, resolving its selector IMMEDIATELY
    # before the drop and never reusing one resolved earlier.
    #
    # audit C2 (fourth re-audit): the stash-pop path resolved a selector,
    # then ran a pop and a resolver subprocess, and only then dropped by
    # that stale selector. A concurrent session dropping its own stash in
    # that window renumbered the stack — and this destroyed that session's
    # stash (an untracked file that was in no commit anywhere), left our
    # own entry behind, and exited 0.
    local repo="$1" sha="$2" ref
    if ! ref="$(stash_ref_for "$repo" "$sha")"; then
        log "WARNING: stash ${sha:0:8} is no longer on $repo's stack; nothing dropped"
        return 1
    fi
    if ! git -C "$repo" stash drop "$ref" >>"$LOG_FILE" 2>&1; then
        log "WARNING: could not drop stash ${sha:0:8} ($ref) in $repo"
        return 1
    fi
    return 0
}

# audit M2 (fifth re-audit): every stash whose contents reached the working
# tree, whether the apply was clean or conflicted-then-resolved. A drop that
# fails afterwards leaves an entry on the stack whose work is NOT lost — and
# telling the operator to pop it, as the stranded-stash line did, duplicates
# every record in it.
applied_stash_shas=()
#: Entries whose apply CONFLICTED and was then abandoned. Their content is
#: in the tree as conflict markers: neither lost nor usable (audit M1,
#: sixth re-audit — these were told "UNRECOVERED, recover with stash pop",
#: which would apply the same content a second time on top of the markers).
conflicted_stash_shas=()
#: `<sha><TAB><repo><TAB><comma-separated paths>` for each conflicted apply,
#: so the sidecar can say WHICH markers a stash produced (audit C2).
conflicted_stash_records=()
#: Entries git refused because the index was already unmerged. Their work
#: is intact and only in the stash (audit C1).
blocked_stash_shas=()
#: Entries only PART of which reached the tree: the tracked half applied
#: (cleanly or as markers) and the untracked half did not, so the entry
#: still holds the only copy of files that are in no commit and no tree
#: (audit S27, tenth re-audit). Never droppable, never "refused".
partial_stash_shas=()
#: `<sha><TAB><repo><TAB><newline-separated unrestored paths>` for each.
partial_stash_records=()

unrestored_untracked_paths() {
    # unrestored_untracked_paths <repo> <sha>
    # Print every path in the stash entry's UNTRACKED tree (`<sha>^3`)
    # that is missing from the working tree or differs from the copy the
    # entry holds — i.e. every file whose only copy is still inside it.
    #
    # audit S27 (tenth re-audit). `git stash apply` restores the untracked
    # tree AFTER merging the tracked one, and abandons the whole untracked
    # half the moment one of its paths already exists ("<path> already
    # exists, no checkout" / "could not restore untracked files from
    # stash"). ONE command therefore both writes conflict markers for a
    # tracked path and leaves an untracked file unrestored — measured on
    # git 2.48.1. The tracked half then resolves, and dropping the entry
    # destroys the only copy of the untracked file: it is in no commit, no
    # index, and no working tree, so nothing else in this script can see
    # it. This is the predicate the drop guard below is built on.
    #
    # `ls-tree -z` gives raw (unquoted) paths, which is what the
    # filesystem comparison needs; the newline-joined result carries a
    # path holding a space or a comma correctly, and shares the whole
    # script's one limitation — a path holding a newline.
    local repo="$1" sha="$2" entry blob path
    git -C "$repo" rev-parse --verify --quiet "${sha}^3" >/dev/null 2>&1 || return 0
    while IFS= read -r -d '' entry; do
        [[ -n "$entry" ]] || continue
        # "<mode> <type> <object><TAB><path>"
        blob="${entry%%$'\t'*}"
        blob="${blob##* }"
        path="${entry#*$'\t'}"
        if [[ ! -e "$repo/$path" ]]; then
            printf '%s\n' "$path"
        elif [[ "$(git -C "$repo" hash-object -- "$repo/$path" 2>/dev/null || true)" \
                != "$blob" ]]; then
            printf '%s\n' "$path"
        fi
    done < <(git -C "$repo" ls-tree -r -z "${sha}^3" 2>/dev/null || true)
    return 0
}

record_partial_stash() {
    # record_partial_stash <repo> <sha> <newline-separated paths>
    # Idempotent: the classifier and the drop guard can both reach the
    # same entry, and it must be named once.
    local repo="$1" sha="$2" paths="$3" entry
    for entry in ${partial_stash_shas[@]+"${partial_stash_shas[@]}"}; do
        [[ "$entry" == "$sha" ]] && return 0
    done
    partial_stash_shas+=("$sha")
    partial_stash_records+=("$(printf '%s\t%s\t%s' "$sha" "$repo" "$paths")")
    return 0
}

stash_was_partial() {
    # stash_was_partial <sha>
    local sha="$1" entry
    for entry in ${partial_stash_shas[@]+"${partial_stash_shas[@]}"}; do
        [[ "$entry" == "$sha" ]] && return 0
    done
    return 1
}

stash_was_blocked() {
    # stash_was_blocked <sha>
    local sha="$1" entry
    for entry in ${blocked_stash_shas[@]+"${blocked_stash_shas[@]}"}; do
        [[ "$entry" == "$sha" ]] && return 0
    done
    return 1
}

record_conflicted_stash() {
    # record_conflicted_stash <repo> <sha> <newline-separated paths>
    # audit L1 (tenth re-audit): the paths stay newline-separated. They
    # used to be comma-joined here and word-split on the way back out of
    # the sidecar, which lost every path holding a space or a comma.
    local repo="$1" sha="$2" paths="$3"
    conflicted_stash_shas+=("$sha")
    conflicted_stash_records+=("$(printf '%s\t%s\t%s' "$sha" "$repo" "$paths")")
}

stash_was_conflicted() {
    # stash_was_conflicted <sha>
    local sha="$1" entry
    for entry in ${conflicted_stash_shas[@]+"${conflicted_stash_shas[@]}"}; do
        [[ "$entry" == "$sha" ]] && return 0
    done
    return 1
}

stash_was_applied() {
    # stash_was_applied <sha>
    local sha="$1" applied
    for applied in ${applied_stash_shas[@]+"${applied_stash_shas[@]}"}; do
        [[ "$applied" == "$sha" ]] && return 0
    done
    return 1
}

drop_applied_stash() {
    # drop_applied_stash <repo> <sha> <label>
    # The entry's contents are in the working tree; the entry itself has to
    # go, or the next run applies it again and duplicates those records.
    #
    # audit S27 (tenth re-audit): THE INVARIANT, enforced at the one place
    # that drops an applied entry. An entry is never dropped while any
    # file in its untracked tree is missing from the working tree or
    # differs from the copy it holds — because that copy is then the only
    # one anywhere. `git stash apply` can conflict on a tracked path and
    # silently give up on the untracked half in the same command; the
    # conflicted-then-resolved path then reached this function with rc 0
    # and a clean gate, and the file was gone.
    local repo="$1" sha="$2" label="$3" unrestored
    unrestored="$(unrestored_untracked_paths "$repo" "$sha")"
    if [[ -n "$unrestored" ]]; then
        record_partial_stash "$repo" "$sha" "$unrestored"
        log "$label: NOT dropping $(describe_stash "$repo" "$sha") — it still holds the only copy of ${unrestored//$'\n'/, }"
        return 1
    fi
    applied_stash_shas+=("$sha")
    if drop_stash_by_sha "$repo" "$sha"; then
        return 0
    fi
    # audit L2 (ninth re-audit): the log, not the gate. The applied group
    # in the EXIT handler gates this once, naming every such entry in
    # full; saying it per stash as well told the operator twice.
    log "$label: applied $(describe_stash "$repo" "$sha") but could not drop it"
    return 1
}

apply_then_drop() {
    # apply_then_drop <repo> <sha> <label>
    # Returns non-zero only if the APPLY failed; the caller decides what a
    # conflicted apply means. A failed drop is reported by the helper above.
    local repo="$1" sha="$2" label="$3"
    apply_stash_by_sha "$repo" "$sha" || return 1
    drop_applied_stash "$repo" "$sha" "$label" || true
    return 0
}

stranded_stashes() {
    # stranded_stashes <repo> <sha>...
    # Print "<state> <sha8> <stash@{n}> <message>" per recorded stash still
    # on <repo>'s stack, where <state> is `applied` (its work is in the
    # tree) or `unrecovered` (its work is in no commit and no tree).
    local repo="$1"
    shift
    local sha ref subject state
    for sha in "$@"; do
        ref="$(stash_ref_for "$repo" "$sha")" || continue
        subject="$(git -C "$repo" log -1 --format=%s "$sha" 2>/dev/null || true)"
        # Order matters. `applied` outranks `conflicted`: an apply that
        # conflicted and was then RESOLVED has its content in the tree in
        # usable form, and the advice is "delete the entry", not "resolve
        # the markers" that are no longer there. Only an apply that
        # conflicted and was abandoned stays `conflicted` — nothing marks
        # it applied, because nothing ever used it.
        #
        # audit S27 (tenth re-audit): and `partial` outranks `applied`,
        # because a partly-applied entry is the one case where "delete
        # the entry" destroys the only copy of something.
        if stash_was_partial "$sha"; then
            state=partial
        elif stash_was_applied "$sha"; then
            state=applied
        elif stash_was_conflicted "$sha"; then
            state=conflicted
        elif stash_was_blocked "$sha"; then
            state=blocked
        else
            state=unrecovered
        fi
        printf '%s %s %s %s\n' "$state" "${sha:0:8}" "$ref" "$subject"
    done
}

# Recorded stashes are never removed from these lists: a popped entry
# disappears from the stack, so "still resolvable by SHA" is exactly "still
# unrecovered". That is what the EXIT handler below checks.
#
# stash_restore_allowed is cleared the moment the tree may be half-merged
# or a pop was refused: re-popping into that state would corrupt it.
stash_restore_allowed=1

# ---------------------------------------------------------------------------
# reconcile_orphaned_stashes — CRASH-SAFE recovery, runs at START of a run.
#
# ⚠ THIS IS THE LOAD-BEARING FIX (2026-08-20). daily-sync runs as a child of
# a Claude Code SessionStart hook with a 90s timeout, so it can be killed
# mid-run — and a killed shell does not run its EXIT trap. The existing
# `restore_stash_on_exit` trap is therefore necessary but NOT sufficient:
# on 2026-08-19 a run stashed at 10:20:34, died before its pop, released
# the flock (fd closed on process death), and a second run started at
# 10:20:37 onto the now-clean tree. 41 memory records were orphaned that
# way across two incidents (2026-07-18 and 2026-08-19).
#
# Nothing the dying process does can be relied upon, so recovery must
# happen at the START of the NEXT run. That is what this does.
# ---------------------------------------------------------------------------
reconcile_orphaned_stashes() {
    # Ask the drift detector which stashes still hold records found nowhere
    # else. This is deliberately NOT "pop every daily-sync stash": once a
    # stash has been recovered by other means its records are already in the
    # canonical file, and re-applying it would either conflict or duplicate.
    # The detector owns that judgement because it is the thing that can see
    # all three stores. If it cannot run (PostgreSQL down), it exits non-zero
    # and prints nothing — and "unknown" must mean "touch nothing".
    local -a orphans=()
    local ref sha
    while IFS= read -r ref; do
        [[ -n "$ref" ]] || continue
        # audit (low, second re-audit): the detector hands back `stash@{n}`
        # selectors produced by ANOTHER process. An index is a position,
        # not an identity — one concurrent `git stash push` or `drop`
        # renumbers the stack, and stash@{2} is then somebody else's work.
        # Resolve each selector to a commit SHA the moment it is read, and
        # do every pop below by SHA, like the rest of this script.
        sha="$(git rev-parse --verify --quiet "${ref}^{commit}" 2>/dev/null || true)"
        if [[ -z "$sha" ]]; then
            log "ORPHANED STASH: $ref no longer resolves (already recovered?) — skipping"
            continue
        fi
        orphans+=("$sha")
    done < <("$PA_DIR/venv/bin/python3" "$SCRIPT_DIR/check-memory-drift.py" \
                 --list-recoverable-stashes 2>>"$LOG_FILE" || true)
    [[ ${#orphans[@]} -eq 0 ]] && return 0

    log "ORPHANED STASH: ${#orphans[@]} stash(es) hold memory records found"
    log "  nowhere else — from a previous run killed before it could pop."
    local i
    # Oldest last in `git stash list`, so walk backwards to replay in order.
    for (( i=${#orphans[@]}-1 ; i>=0 ; i-- )); do
        sha="${orphans[i]}"
        if [[ $DRY_RUN -eq 1 ]]; then
            log "  [dry-run] would pop ${sha:0:8}"
            continue
        fi
        if ! ref="$(stash_ref_for "$DATA_DIR" "$sha")"; then
            log "  ${sha:0:8} is no longer on the stack — skipping"
            continue
        fi
        # audit L1 (third re-audit): apply by COMMIT, drop by selector.
        # `git stash pop <selector>` re-reads the selector at pop time, so
        # a concurrent `git stash push` between the resolution above and
        # the pop would silently shift it onto somebody else's entry.
        # A stash entry is a commit: `git stash apply <sha>` cannot be
        # aimed at the wrong one. The drop still needs a selector, so
        # re-resolve it immediately afterwards, when the window is a
        # single command wide and applying the wrong entry is no longer
        # possible.
        snapshot_before_apply "$DATA_DIR"
        if apply_stash_by_sha "$DATA_DIR" "$sha"; then
            # audit (low, fourth re-audit): applied is not recovered. An
            # entry still on the stack is applied again next run and
            # duplicates every record in it, so drop_applied_stash reports
            # a failed drop and only a clean one earns the word.
            if drop_applied_stash "$DATA_DIR" "$sha" "orphan recovery"; then
                log "  recovered ${sha:0:8}"
            elif stash_was_partial "$sha"; then
                # audit S27: the drop was refused because the entry still
                # holds the only copy of an untracked file. The partial
                # group in the EXIT handler names it, and its paths, in
                # full; saying it here as well would tell the operator
                # twice, and "delete the entry" below would be wrong.
                log "  applied ${sha:0:8} only partly — its entry is kept"
            else
                # audit L2 (ninth re-audit): the applied GROUP in the exit
                # handler covers the run's own stashes, but not an orphan
                # — those SHAs are never in data_stash_shas, so nothing
                # else would say this.
                add_sync_gate_detail \
                    "daily-sync applied orphaned stash $(describe_stash "$DATA_DIR" "$sha") in $DATA_DIR and could not drop it. Its contents are ALREADY in the working tree — delete the entry if it is still there. Do NOT pop it: that would duplicate every record in it."
            fi
        else
            # A conflicted pop leaves the tree half-merged and preserves the
            # stash. Do NOT try to tidy up: `git checkout -- .` here would
            # destroy a concurrent session's uncommitted prose edits. Stop
            # and let a human resolve it — the stash is still intact.
            #
            # audit S17: this wedges every LATER session too. The tree
            # stays conflicted, the extraction hook keeps appending to a
            # now-invalid JSONL, and each run re-enters this function,
            # fails again ("cannot pop, you have unmerged files"), and
            # never reaches the sync. Nothing surfaced that state but the
            # log, so write the gate as well.
            stash_restore_allowed=0
            # audit S27 (tenth re-audit): the same apply can conflict on a
            # tracked path AND fail to restore an untracked one. Say so:
            # "resolve the markers" alone would leave the untracked file
            # inside an entry the operator then deletes.
            classify_apply_failure "$DATA_DIR" "$sha"
            if [[ "$apply_outcome" == "partial" ]]; then
                record_partial_stash "$DATA_DIR" "$sha" "$apply_outcome_untracked"
                add_sync_gate_detail \
                    "daily-sync STOPPED: orphaned stash ${sha:0:8} ($ref) restored only part of itself — ${apply_outcome_untracked//$'\n'/, } exist ONLY inside the entry, and whatever it did apply is in $DATA_DIR now. Recover those files (git -C $DATA_DIR checkout ${sha}^3 -- <path>), resolve any markers, and only then delete the entry."
                fail "ORPHANED STASH ${sha:0:8} ($ref) restored only part of itself; the entry is preserved and holds the only copy of ${apply_outcome_untracked//$'\n'/, }"
            fi
            add_sync_gate_detail \
                "daily-sync STOPPED: orphaned stash ${sha:0:8} ($ref) did not apply cleanly; $DATA_DIR is conflicted and every session start will fail here until it is resolved by hand (git -C $DATA_DIR status; git -C $DATA_DIR stash show -p $ref)"
            fail "ORPHANED STASH ${sha:0:8} ($ref) did not apply cleanly; tree is conflicted and the stash is preserved. Resolve by hand: git -C $DATA_DIR stash show -p $ref"
        fi
    done
}

# ---------------------------------------------------------------------------
# Data submodule sync
# ---------------------------------------------------------------------------

# audit S19: on an uninitialised submodule (first run on a new machine, or
# after `git submodule deinit`) this `cd` aborted under `set -e` with
# status 1 — reported by the trigger as lock contention. Worse, when
# data/ exists but holds no .git, every `git` call below silently
# operates on the PARENT repository instead of the submodule, because git
# walks up to the enclosing work tree.
if [[ ! -e "$DATA_DIR/.git" ]]; then
    fail "data submodule is not initialised ($DATA_DIR/.git absent) — run: git -C $PA_DIR submodule update --init"
fi
cd "$DATA_DIR" || fail "cannot enter the data submodule at $DATA_DIR"

# audit M1/M2 (seventh re-audit): say what a previous run left behind
# BEFORE trying to work around it. A run killed mid-rebase leaves
# rebase-merge/ and an unmerged tree; the next run used to trip over that
# three steps later and gate "stash push before branch switch failed",
# never mentioning the rebase. And an unmerged corpus reached
# reconcile_orphaned_stashes first, whose generic advice replaced the
# specific "resolve the markers, then delete the entry".
unmerged_paths() {
    # unmerged_paths <repo> — one path per line, sorted, possibly empty.
    #
    # The sort is load-bearing, not cosmetic: classify_apply_failure feeds
    # two of these lists to `comm`, which compares them with the LOCALE's
    # collating sequence, while git emits paths in byte order. On a repo
    # holding `B.md` and `a.md` the two orders disagree, and unsorted
    # input makes comm report a path that was already unmerged as new —
    # i.e. blame this apply for somebody else's conflict.
    #
    # audit L3 (tenth re-audit): the parent's `data` gitlink is excluded,
    # exactly as the parent stash's own pathspec excludes it. The parent
    # stash can never contain the gitlink, so a conflict there can never
    # be a parent stash's doing — and attributing one to a stash is how an
    # entry gets deleted. `git status --porcelain` in
    # check_interrupted_state still sees it, so it is not hidden, only
    # kept out of the stash attribution.
    local repo="$1"
    local -a pathspec=()
    [[ "$repo" == "$PA_DIR" ]] && pathspec=(-- ':!data')
    git -C "$repo" diff --name-only --diff-filter=U \
        ${pathspec[@]+"${pathspec[@]}"} 2>/dev/null | sort -u || true
}

#: Set by classify_apply_failure: `partial`, `conflicted`, `blocked`, or
#: `refused`; the paths THIS apply left unmerged; and the paths of the
#: entry's untracked tree it did not restore.
apply_outcome=""
apply_outcome_paths=""
apply_outcome_untracked=""
#: What the tree looked like immediately before an apply, so an apply that
#: did NOTHING can be told from one that did half of what it was asked.
apply_before_unmerged=""
apply_before_status=""

snapshot_before_apply() {
    # snapshot_before_apply <repo>
    # Call immediately before every `git stash apply`; classify_apply_failure
    # reads what it records.
    apply_before_unmerged="$(unmerged_paths "$1")"
    apply_before_status="$(git -C "$1" status --porcelain 2>/dev/null || true)"
    return 0
}

classify_apply_failure() {
    # classify_apply_failure <repo> <sha>
    #
    # audit C1 (ninth re-audit): by what THIS apply changed, not by
    # whether the repository happens to hold any unmerged path. Scanning
    # the whole repository meant that once stash 1 conflicted, stash 2 —
    # which git then REFUSES outright, leaving its entry untouched — was
    # recorded as conflicted too, and the gate condemned the only copy of
    # its records.
    #
    # audit S27 (tenth re-audit): four outcomes, not three. An apply that
    # put PART of the entry in the tree and left the rest inside it is
    # neither `conflicted` (resolving the markers does not make the entry
    # safe to drop) nor `refused` (the tree is emphatically not
    # untouched). It is `partial`, and the only outcome that must survive
    # every later "delete the entry" instinct.
    local repo="$1" sha="$2" after new_paths after_status
    after="$(unmerged_paths "$repo")"
    # audit L2 (tenth re-audit): no `grep -v '^$'` filter. `printf '%s\n'`
    # puts an empty line on BOTH sides, so comm suppresses it and can
    # never emit one — the filter was dead from the day it was written.
    new_paths="$(comm -13 <(printf '%s\n' "$apply_before_unmerged") \
        <(printf '%s\n' "$after") || true)"
    after_status="$(git -C "$repo" status --porcelain 2>/dev/null || true)"
    apply_outcome_untracked="$(unrestored_untracked_paths "$repo" "$sha")"
    if [[ -n "$new_paths" ]]; then
        # The apply certainly ran: it wrote markers. Whether it also
        # finished is what the untracked tree says.
        if [[ -n "$apply_outcome_untracked" ]]; then
            apply_outcome="partial"
        else
            apply_outcome="conflicted"
        fi
        apply_outcome_paths="$new_paths"
    elif [[ "$after_status" != "$apply_before_status" ]] \
            && [[ -n "$apply_outcome_untracked" ]]; then
        # No markers, but the tree changed and the untracked half did not
        # land: the tracked changes merged cleanly and git then gave up on
        # the untracked files. Measured on git 2.48.1.
        apply_outcome="partial"
        apply_outcome_paths=""
    elif [[ -n "$apply_before_unmerged" ]]; then
        # git refused because the index was ALREADY unmerged; it never
        # reached the untracked half, so an unrestored path there says
        # nothing. The entry is intact and its work is nowhere else:
        # resolve the earlier conflict, then pop this one.
        apply_outcome="blocked"
        apply_outcome_paths=""
    else
        apply_outcome="refused"
        apply_outcome_paths=""
    fi
    return 0
}

describe_stash() {
    # describe_stash <repo> <sha>
    # "<sha8> <selector> <subject>" — never name a stash by fewer than all
    # three (audit C-B, eighth re-audit). A bare sha8 is not something an
    # operator can act on, and a bare selector is a moving target.
    local repo="$1" sha="$2" ref subject
    ref="$(stash_ref_for "$repo" "$sha")" || ref="(no longer on the stack)"
    subject="$(git -C "$repo" log -1 --format=%s "$sha" 2>/dev/null || true)"
    printf '%s %s %s' "${sha:0:8}" "$ref" "$subject"
}

list_stash_entries() {
    # list_stash_entries <repo> — every entry, identified in full.
    git -C "$1" stash list --format='%H %gd %s' 2>/dev/null \
        | while read -r _sha _rest; do printf '%s %s; ' "${_sha:0:8}" "$_rest"; done
}

previously_recorded_stashes() {
    # previously_recorded_stashes <repo> <state> <current-unmerged-paths>
    #
    # Stashes an EARLIER run recorded in <state> (`conflicted` or
    # `partial`), still on the stack, AND whose recorded paths intersect
    # the paths that are unmerged now. Only those may be described as the
    # source of these markers — path by path (audit C2, ninth re-audit). A
    # stale row about a stash that conflicted last week says nothing about
    # a fresh conflict somewhere else, and acting on it means deleting
    # work.
    #
    # `grep -qxF` — anchored, not a substring search. Without `-x`, a row
    # recording `notes/a.md` would claim the markers in `notes/a.md.bak`,
    # which is a different file and somebody else's conflict.
    #
    # audit L1 (tenth re-audit): one path per ROW, so a path holding a
    # space or a comma survives the round trip. Two passes because the
    # rows for one entry have to be gathered back together.
    local repo="$1" want_state="$2" current="$3"
    local entry_repo sha state path shared known candidate
    local -a matched=()
    [[ -f "$STASH_STATE_FILE" ]] || return 0
    while IFS=$'\t' read -r entry_repo sha state path; do
        [[ "$entry_repo" == "$repo" ]] || continue
        [[ "$state" == "$want_state" ]] || continue
        # An applied row carries no path and is never a marker source; so
        # is any row whose path field is empty.
        [[ -n "$path" ]] || continue
        stash_ref_for "$repo" "$sha" >/dev/null || continue
        printf '%s\n' "$current" | grep -qxF -- "$path" || continue
        for known in ${matched[@]+"${matched[@]}"}; do
            [[ "$known" == "$sha" ]] && continue 2
        done
        matched+=("$sha")
    done < "$STASH_STATE_FILE"
    for candidate in ${matched[@]+"${matched[@]}"}; do
        shared=""
        while IFS=$'\t' read -r entry_repo sha state path; do
            [[ "$sha" == "$candidate" ]] || continue
            [[ "$state" == "$want_state" ]] || continue
            [[ -n "$path" ]] || continue
            printf '%s\n' "$current" | grep -qxF -- "$path" || continue
            shared+="$path "
        done < "$STASH_STATE_FILE"
        printf '%s (its markers are in %s); ' \
            "$(describe_stash "$repo" "$candidate")" "${shared% }"
    done
    return 0
}

carry_forward_partial_stashes() {
    # Re-record every entry an EARLIER run left partly applied that is
    # still on the stack and still holds the only copy of something.
    #
    # audit S27 (tenth re-audit). Without this the warning lives exactly
    # one run: the gate is replaced by whatever the next run has to say,
    # and a run with nothing to say clears it — while the file is still in
    # no commit and no tree. Re-recording puts the entry back into this
    # run's own bookkeeping, so the EXIT handler raises the same gate line
    # again, and keeps raising it until the files are recovered. It costs
    # one `ls-tree` per recorded row.
    local repo sha state path unrestored seen
    local -a done_shas=()
    [[ -f "$STASH_STATE_FILE" ]] || return 0
    while IFS=$'\t' read -r repo sha state path; do
        [[ "$state" == "partial" ]] || continue
        [[ "$repo" == "$DATA_DIR" ]] || [[ "$repo" == "$PA_DIR" ]] || continue
        # audit low (eleventh re-audit): the sidecar holds one row per
        # PATH, and re-deriving an entry's state re-reads its whole
        # untracked tree. Once per entry, not once per row.
        for seen in ${done_shas[@]+"${done_shas[@]}"}; do
            [[ "$seen" == "$sha" ]] && continue 2
        done
        done_shas+=("$sha")
        stash_ref_for "$repo" "$sha" >/dev/null || continue
        unrestored="$(unrestored_untracked_paths "$repo" "$sha")"
        [[ -n "$unrestored" ]] || continue
        record_partial_stash "$repo" "$sha" "$unrestored"
    done < "$STASH_STATE_FILE"
    return 0
}

check_interrupted_state() {
    # check_interrupted_state <repo> <label>
    # Name what a previous run left behind, before anything works around
    # it. A run killed mid-operation — routine, under SessionStart's 90 s
    # budget — used to be discovered three steps later as "stash push
    # before branch switch failed".
    local repo="$1" label="$2" git_dir op abort_cmd continue_cmd unmerged named
    git_dir="$(git -C "$repo" rev-parse --absolute-git-dir 2>/dev/null || true)"
    op=""
    abort_cmd=""
    continue_cmd=""
    if [[ -n "$git_dir" ]]; then
        if [[ -d "$git_dir/rebase-merge" ]]; then
            op="rebase"
        elif [[ -d "$git_dir/rebase-apply" ]]; then
            # audit M2 (eighth re-audit): rebase-apply is `git am`'s
            # directory too, and `git rebase --abort` is not the way out of
            # a half-applied mailbox. `applying` is the file am leaves.
            if [[ -f "$git_dir/rebase-apply/applying" ]]; then
                op="git am"
                abort_cmd="git -C $repo am --abort"
                continue_cmd="git -C $repo am --continue"
            else
                op="rebase"
            fi
        elif [[ -f "$git_dir/CHERRY_PICK_HEAD" ]]; then
            op="cherry-pick"
        elif [[ -f "$git_dir/REVERT_HEAD" ]]; then
            op="revert"
        elif [[ -f "$git_dir/MERGE_HEAD" ]]; then
            op="merge"
            abort_cmd="git -C $repo merge --abort"
            continue_cmd="git -C $repo commit"
        elif [[ -f "$git_dir/BISECT_LOG" ]]; then
            # audit M2 (ninth re-audit): a bisect was invisible here, and
            # the branch guard then checked out main in the middle of one
            # — destroying somebody's session and exiting 0. A bisect is a
            # human's working state: say it is there and move nothing.
            op="bisect"
            abort_cmd="git -C $repo bisect reset"
            # No continue_cmd: a bisect has no "--continue", and the
            # branch below never offers one for it (audit L4, tenth
            # re-audit — the bisect arm used to set one, so a bisect
            # that ALSO held unmerged paths was told to "finish it"
            # with `git bisect reset`, which throws the bisect away).
        fi
    fi
    if [[ -n "$op" ]] && [[ -z "$abort_cmd" ]]; then
        abort_cmd="git -C $repo $op --abort"
        continue_cmd="git -C $repo $op --continue"
    fi

    unmerged="$(git -C "$repo" status --porcelain | grep -E '^(UU|AA|DD|AU|UA|DU|UD) ' || true)"

    if [[ -n "$op" ]]; then
        # audit L4 (tenth re-audit): the bisect arm comes FIRST, whether
        # or not paths are unmerged. A bisect is a human's working state
        # in either case, there is no `git bisect --continue` to offer,
        # and the advice for the other operations ("resolve them and
        # finish it") is wrong for one.
        if [[ "$op" == "bisect" ]]; then
            add_sync_gate_detail \
                "daily-sync STOPPED: a git bisect is in progress in $repo ($label). That is somebody's working state and this script will not move HEAD out of it. Finish or abandon the bisect ($abort_cmd), then run the sync again."
        elif [[ -n "$unmerged" ]]; then
            add_sync_gate_detail \
                "daily-sync STOPPED: a previous run was interrupted mid-$op in $repo ($label), and paths are still unresolved — ${unmerged//$'\n'/, }. Resolve them and finish it ($continue_cmd), or throw the whole operation away ($abort_cmd). Nothing will sync until one or the other is done."
        else
            # audit M3 (eighth re-audit): an operation in progress with
            # NOTHING unresolved is a resolution waiting to be committed.
            # Aborting it discards work somebody has already done.
            add_sync_gate_detail \
                "daily-sync STOPPED: a $op is in progress in $repo ($label) with nothing left unresolved — somebody resolved it and did not finish. Complete it: $continue_cmd. Do NOT abort: that would throw away the resolution."
        fi
        fail "$label: a $op is in progress in $repo"
    fi

    if [[ -n "$unmerged" ]]; then
        # audit C-B (eighth re-audit): only claim a stash put these markers
        # here if an earlier run RECORDED doing exactly that. The blanket
        # "delete any stash entry this left behind" was advice to destroy
        # the only copy of an orphan — given before reconciliation had so
        # much as listed what was on the stack.
        local _current_unmerged partly
        _current_unmerged="$(unmerged_paths "$repo")"
        named="$(previously_recorded_stashes "$repo" conflicted "$_current_unmerged")"
        # audit S27 (tenth re-audit): a PARTLY applied entry produced
        # these markers too — but it also still holds the only copy of
        # files it could not restore, so "delete that entry" is the one
        # instruction that must not be given about it.
        partly="$(previously_recorded_stashes "$repo" partial "$_current_unmerged")"
        if [[ -n "$partly" ]]; then
            add_sync_gate_detail \
                "daily-sync STOPPED: $repo ($label) has unmerged paths — ${unmerged//$'\n'/, }. A previous run applied ${partly%; } and it conflicted, so these markers ARE that stash's content — but only PARTLY: the same entry still holds the only copy of untracked files it could not write. Resolve the markers, then recover those files (git -C $repo checkout <sha>^3 -- <path>) BEFORE you delete the entry. Do NOT pop it: that would apply the same content again."
        elif [[ -n "$named" ]]; then
            add_sync_gate_detail \
                "daily-sync STOPPED: $repo ($label) has unmerged paths — ${unmerged//$'\n'/, }. A previous run applied ${named%; } and it conflicted, so these markers ARE that stash's content. Resolve them, then delete that entry. Do NOT pop it: that would apply the same content again."
        else
            local entries
            entries="$(list_stash_entries "$repo")"
            [[ -n "$entries" ]] || entries="(none)"
            add_sync_gate_detail \
                "daily-sync STOPPED: $repo ($label) has unmerged paths from an operation this run cannot identify — ${unmerged//$'\n'/, }. Resolve them by hand. Do NOT touch any stash entry until the sync has run far enough to reconcile orphans; the entries on the stack right now are: ${entries%; }."
        fi
        fail "$label: $repo has unmerged paths left by a previous run"
    fi
    return 0
}
# audit M1 (eighth re-audit): BOTH repositories are checked — a rebase
# left in the parent went entirely unnoticed, and the run exited 0.
# audit M3 (ninth re-audit): but each one before ITS OWN half, not both
# up front. A human mid-rebase in the parent repo is no reason to stop
# memory sync, which is the half that loses data when it does not run;
# the parent check happens further down, just before the parent half.
check_interrupted_state "$DATA_DIR" "data submodule"

# audit S27: an entry an earlier run only PARTLY applied keeps being
# reported until its unrestored files are back, in either repository.
carry_forward_partial_stashes

# The corpus guard runs before recovery too: an unmerged or marker-laden
# corpus has advice of its own, and reconcile's generic orphan message
# used to replace it.
refuse_if_memory_markers "start of run"

# Crash-safe recovery FIRST — before anything reads or writes the tree.
reconcile_orphaned_stashes

# Stash local changes FIRST (typically memories.jsonl + tag-vocabulary.txt
# from extraction hooks). Stashing works on any ref including detached
# HEAD, and leaves a clean tree so the subsequent checkout/pull cannot
# trip over "local changes would be overwritten".



# If any step between a `git stash push` and its explicit pop below aborts
# (e.g. pull fails in any non-interactive env without an SSH agent),
# restore every stash this run pushed, so the user's working tree is not
# silently buried in a stash stack that grows unbounded.
#
# audit C1 (second re-audit): restoring is best-effort, and there are states
# in which it must NOT be attempted — a half-merged tree, or a pop git
# refused outright ("your local changes would be overwritten", which is what
# two of this run's own stashes touching one file produce). The invariant
# that matters is the one after it: a run must never exit while a stash it
# pushed is still on the stack without saying so, by SHA and message, where
# session start will show it.
restore_stash_on_exit() {
    local _i _ref _sha _repo _line _entry _stranded=()
    local -a _shas=()
    if [[ $stash_restore_allowed -eq 1 ]]; then
        for _repo in "$DATA_DIR" "$PA_DIR"; do
            local -a _shas=()
            if [[ "$_repo" == "$DATA_DIR" ]]; then
                _shas=(${data_stash_shas[@]+"${data_stash_shas[@]}"})
            else
                _shas=(${parent_stash_shas[@]+"${parent_stash_shas[@]}"})
            fi
            [[ ${#_shas[@]} -gt 0 ]] || continue
            for (( _i=0; _i<${#_shas[@]}; _i++ )); do
                _sha="${_shas[_i]}"
                stash_ref_for "$_repo" "$_sha" >/dev/null || continue
                # audit C2 (seventh re-audit): an entry still on the stack
                # is not necessarily unapplied. One whose DROP failed has
                # its content in the tree already — applying it again puts
                # the same content on top of itself, which for a corpus
                # that was committed in between means `UU` markers in the
                # live memories.jsonl, with rc 0.
                # audit L5 (ninth re-audit): stash_was_conflicted IS
                # consulted — an earlier iteration of THIS loop can record
                # one, and re-applying it would put the same content on
                # top of the markers it just wrote.
                # audit S27 (tenth re-audit): a PARTLY applied entry is in
                # the same position — its tracked half is already in the
                # tree, and re-applying would layer it on itself.
                if stash_was_applied "$_sha" || stash_was_conflicted "$_sha" \
                        || stash_was_partial "$_sha"; then
                    log "not restoring ${_sha:0:8} in $_repo — this run already applied it"
                    continue
                fi
                log "WARNING: aborting before stash pop — restoring ${_sha:0:8} in $_repo"
                snapshot_before_apply "$_repo"
                if ! apply_then_drop "$_repo" "$_sha" "restore"; then
                    # audit C-A (eighth re-audit): the apply failed, and
                    # HOW it failed decides the advice. audit C1 (ninth):
                    # decided by what THIS apply changed, so a second
                    # stash that git refused because the first one had
                    # already left the index unmerged is not condemned as
                    # the source of those markers.
                    classify_apply_failure "$_repo" "$_sha"
                    case "$apply_outcome" in
                        partial)
                            # audit S27: NOT "refused, the tree is
                            # untouched" — half of this entry is in the
                            # tree and the other half is only in the
                            # entry, which is why it must not be dropped.
                            record_partial_stash "$_repo" "$_sha" "$apply_outcome_untracked"
                            log "ERROR: restoring $(describe_stash "$_repo" "$_sha") restored only part of it; ${apply_outcome_untracked//$'\n'/, } exist only inside the entry"
                            ;;
                        conflicted)
                            record_conflicted_stash "$_repo" "$_sha" "$apply_outcome_paths"
                            log "ERROR: restoring $(describe_stash "$_repo" "$_sha") conflicted; its content is in the tree as markers in ${apply_outcome_paths//$'\n'/, }"
                            ;;
                        blocked)
                            blocked_stash_shas+=("$_sha")
                            log "ERROR: restoring $(describe_stash "$_repo" "$_sha") was blocked by an earlier conflict; the entry is intact"
                            ;;
                        *)
                            log "ERROR: restoring $(describe_stash "$_repo" "$_sha") was refused; the tree is untouched and the stash is preserved"
                            ;;
                    esac
                fi
            done
        done
    fi

    # The invariant. Anything of ours still on a stack needs saying — but
    # the advice depends on whether its work reached the tree (audit M2).
    local _applied=() _conflicted=() _blocked=()
    # audit S27: the partial group is rendered from its OWN records rather
    # than from stranded_stashes, because the operator needs the paths —
    # "one of your stashes is half-applied" is not something anyone can
    # act on. Entries no longer on the stack are skipped, as everywhere.
    local _p_record _p_sha _p_repo _p_paths
    local -a _partial=()
    for _p_record in ${partial_stash_records[@]+"${partial_stash_records[@]}"}; do
        _p_sha="${_p_record%%$'\t'*}"
        _p_paths="${_p_record##*$'\t'}"
        _p_repo="${_p_record#*$'\t'}"
        _p_repo="${_p_repo%%$'\t'*}"
        stash_ref_for "$_p_repo" "$_p_sha" >/dev/null || continue
        _partial+=("$(describe_stash "$_p_repo" "$_p_sha") in $_p_repo still holds the only copy of ${_p_paths//$'\n'/, } — recover each with: git -C $_p_repo checkout ${_p_sha}^3 -- <path> (inspect first: git -C $_p_repo show ${_p_sha}^3:<path>)")
    done
    for _repo in "$DATA_DIR" "$PA_DIR"; do
        if [[ "$_repo" == "$DATA_DIR" ]]; then
            _shas=(${data_stash_shas[@]+"${data_stash_shas[@]}"})
            _line="data submodule"
        else
            _shas=(${parent_stash_shas[@]+"${parent_stash_shas[@]}"})
            _line="parent repo"
        fi
        [[ ${#_shas[@]} -gt 0 ]] || continue
        while IFS= read -r _entry; do
            [[ -n "$_entry" ]] || continue
            if [[ "$_entry" == partial\ * ]]; then
                # Already named above, with its paths.
                continue
            elif [[ "$_entry" == applied\ * ]]; then
                _applied+=("$_line: ${_entry#applied }")
            elif [[ "$_entry" == conflicted\ * ]]; then
                _conflicted+=("$_line: ${_entry#conflicted }")
            elif [[ "$_entry" == blocked\ * ]]; then
                _blocked+=("$_line: ${_entry#blocked }")
            else
                _stranded+=("$_line: ${_entry#unrecovered }")
            fi
        done < <(stranded_stashes "$_repo" "${_shas[@]}")
    done
    if [[ ${#_stranded[@]} -gt 0 ]]; then
        log "STRANDED STASH: ${#_stranded[@]} stash(es) this run pushed hold unrecovered work:"
        for _i in "${_stranded[@]}"; do log "  $_i"; done
        add_sync_gate_detail \
            "daily-sync left ${#_stranded[@]} of its own stash(es) UNRECOVERED — they hold work that is in no commit: ${_stranded[*]}. Recover with: git -C <repo> stash pop <ref> (inspect first: git -C <repo> stash show -p <ref>)"
    fi
    if [[ ${#_conflicted[@]} -gt 0 ]]; then
        log "CONFLICTED STASH: ${#_conflicted[@]} stash(es) applied with conflicts:"
        for _i in "${_conflicted[@]}"; do log "  $_i"; done
        add_sync_gate_detail \
            "daily-sync applied ${#_conflicted[@]} of its own stash(es) WITH CONFLICTS: ${_conflicted[*]}. Their content is already in the tree as conflict markers — resolve the markers, then DELETE the entry (git stash drop <ref>). Do NOT pop it: that would apply the same content again on top of the markers."
    fi
    if [[ ${#_blocked[@]} -gt 0 ]]; then
        log "BLOCKED STASH: ${#_blocked[@]} stash(es) could not be applied because of an earlier conflict:"
        for _i in "${_blocked[@]}"; do log "  $_i"; done
        add_sync_gate_detail \
            "daily-sync could not apply ${#_blocked[@]} of its own stash(es) because the index was ALREADY unmerged: ${_blocked[*]}. Their entries are intact and their work is nowhere else. Resolve the earlier conflict first, then pop these — do not delete them."
    fi
    if [[ ${#_partial[@]} -gt 0 ]]; then
        log "PARTIAL STASH: ${#_partial[@]} stash(es) were only PARTLY applied:"
        for _i in "${_partial[@]}"; do log "  $_i"; done
        add_sync_gate_detail \
            "daily-sync applied ${#_partial[@]} of its own stash(es) only PARTLY: ${_partial[*]}. Their tracked changes are in the working tree; the untracked files named are NOT, and exist ONLY inside the stash entry — in no commit, no index, and no working tree. Recover them first. Do NOT delete the entry until you have, and do NOT pop it: that would apply the tracked half a second time."
    fi
    if [[ ${#_applied[@]} -gt 0 ]]; then
        log "APPLIED STASH: ${#_applied[@]} stash(es) were applied but not dropped:"
        for _i in "${_applied[@]}"; do log "  $_i"; done
        add_sync_gate_detail \
            "daily-sync applied ${#_applied[@]} of its own stash(es) and could not drop them: ${_applied[*]}. Their contents are ALREADY in the working tree — delete the entries (git stash drop <ref>). Do NOT pop them: that would duplicate every record in them."
    fi

    # audit C-B (eighth re-audit): record what this run did to its own
    # stashes, so the NEXT run can say whose markers a half-merged tree
    # holds instead of guessing — and can name them in full.
    write_stash_state

    # audit C1 (fifth re-audit): the gate is rendered here, once, after
    # every writer has had its say — including the stranded check above.
    render_sync_gate
}
trap restore_stash_on_exit EXIT

# ---------------------------------------------------------------------------
# Ensure we are on main BEFORE anything commits (audit S5).
#
# The submodule sometimes ends up in detached HEAD after certain git
# operations — `sync-symlinks.sh` runs `git submodule update`, which checks
# the recorded SHA out detached whenever the parent pointer and the
# submodule HEAD disagree, and `setup.sh` does the same. This guard used to
# sit BELOW the agent-mail archive and the append-only memory commit, so on
# a detached HEAD those commits were made on an unreachable ref and the
# `git checkout main` here then reverted memories.jsonl to main's content —
# losing the just-appended records from the working tree as well. They
# survived only in the reflog. That is the same record-loss class the
# reconcile_orphaned_stashes block above was written for (41 records, two
# incidents).
#
# The guard needs a clean-enough tree, which the stash below normally
# provides. On the detached path only, stash first — the common path (on
# main already) still commits before stashing, which is what usually empties
# the tree and means no stash is taken at all.
# ---------------------------------------------------------------------------
current_branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$current_branch" != "main" ]]; then
    log "data submodule on '$current_branch' — switching to main"
    if [[ $DRY_RUN -eq 0 ]]; then
        if [[ -n "$(git status --porcelain)" ]]; then
            log "data submodule: stashing local changes before the branch switch"
            _sha="$(push_stash "$DATA_DIR" \
                "daily-sync branch-switch on $HOST $(date +'%Y-%m-%d %H:%M')")" \
                || fail "stash push before branch switch failed"
            data_stash_shas+=("$_sha")
        fi
        git checkout main >>"$LOG_FILE" 2>&1 \
            || fail "failed to switch data submodule to main"
    fi
fi

# ---------------------------------------------------------------------------
# Agent-mail archive (2026-09-08). Copies every message and receipt from
# ~/agent-mail into data/agent-mail/ (append-only) and rebuilds its JSONL
# index, committing with an explicit pathspec so nothing else pending in
# the submodule is swept. Runs BEFORE the rest of the submodule sync so its
# commit is pushed by it. Failure is logged, never fatal: mail is still on
# disk.
#
# audit S5: placed after the branch guard above, because it commits into
# the data submodule and a commit made on a detached HEAD is orphaned by
# the checkout.
# audit S9: `--dry-run` promises "show what would happen, no changes"
# (usage banner), but this call had no guard, so a dry run copied files
# into data/agent-mail/ and made a commit.
# ---------------------------------------------------------------------------
if [[ $DRY_RUN -eq 0 ]]; then
    if ! "$PA_DIR/venv/bin/python3" "$SCRIPT_DIR/archive-agent-mail.py" --commit --quiet \
            >>"$LOG_FILE" 2>&1; then
        log "WARNING: agent-mail archive failed (see log); continuing"
    fi
else
    log "[dry-run] would archive agent-mail into the data submodule"
fi

# ---------------------------------------------------------------------------
# abort_on_jsonl_shrink — the invariant on EVERY commit of the corpus.
#
# No commit this script makes may record fewer lines of memories.jsonl than
# the previous commit's version unless it carries the `Rewrite-Class: bulk`
# trailer. Compare committed-tree line counts (HEAD~1 vs HEAD) — NOT
# working-tree counts, which would both already reflect the resolver's
# output and thus always match. On a shrink: undo the commit, write a
# report, and exit 4 before anything is pushed.
#
# audit S23 (tenth re-audit): this used to live inline in the auto-sync
# commit block and nowhere else, so it saw only the commit that block
# makes. The append-only block above commits memories.jsonl FIRST and
# usually empties the tree, which sends the auto-sync block down its
# "nothing to commit" branch — and the ahead-of-origin push below then
# publishes the append-only commit unchecked. A corpus already truncated on
# disk when the run started therefore reached origin with the detector
# switched on and rc 0. Called from both commit sites now.
#
# Scope is memories.jsonl alone, as before: tag-vocabulary.txt is the other
# append-only file, but /tags gardening legitimately prunes it, and a guard
# that wedges the sync on ordinary editing is worse than none.
#
# Must be called from inside the data submodule, immediately after a commit.
# ---------------------------------------------------------------------------
abort_on_jsonl_shrink() {
    # abort_on_jsonl_shrink <context>
    local context="$1" git_show_err lines_before lines_after head_msg shrink_report
    local target="memories/memories.jsonl"
    [[ "$DETECT_JSONL_SHRINK" == "true" ]] || return 0
    # `git show HEAD~1:path | wc -l` correctly counts trailing-\n-terminated
    # lines from the committed tree. HEAD~1 might not exist on a brand-new
    # branch — guard with rev-parse.
    git rev-parse --verify --quiet "HEAD~1" >/dev/null 2>&1 || return 0
    # Audit 2026-05-02 (E daily-sync.sh:336-337): previously both
    # `git show` calls discarded stderr and `wc -l` returned 0 on any
    # error, so a path move (e.g. memories renamed) would evade the
    # shrink check entirely. Capture stderr to a temp file and log a
    # WARN if either side errors so the failure is visible.
    git_show_err=$(mktemp 2>/dev/null) \
        || fail "could not create a temporary file for the shrink check"
    if ! lines_before=$(git show "HEAD~1:$target" 2>"$git_show_err" | wc -l); then
        lines_before=0
    fi
    if [[ -s "$git_show_err" ]]; then
        log "WARN: git show HEAD~1:$target emitted stderr — shrink check may be unreliable. Detail: $(tr '\n' ' ' <"$git_show_err")"
    fi
    : >"$git_show_err"
    if ! lines_after=$(git show "HEAD:$target" 2>"$git_show_err" | wc -l); then
        lines_after=0
    fi
    if [[ -s "$git_show_err" ]]; then
        log "WARN: git show HEAD:$target emitted stderr — shrink check may be unreliable. Detail: $(tr '\n' ' ' <"$git_show_err")"
    fi
    rm -f "$git_show_err"
    [[ "$lines_after" -lt "$lines_before" ]] || return 0
    head_msg="$(git log -1 --format=%B)"
    if echo "$head_msg" | grep -q "^Rewrite-Class: bulk"; then
        return 0
    fi
    # audit low (eleventh re-audit): a `.log` name, because the private
    # data submodule's .gitignore covers `logs/*.log` and `logs/*.jsonl`
    # and NOT `logs/*.txt` — so the auto-sync block's `git add -A` would
    # have committed the shrink report itself into the corpus repo.
    shrink_report="$LOG_DIR/daily-sync-shrink-$(date +'%Y-%m-%d-%H%M%S').log"
    {
        echo "Detected unexpected shrink in memories.jsonl during daily-sync."
        echo "Commit site:     $context"
        echo "Before (HEAD~1): $lines_before lines"
        echo "After  (HEAD):   $lines_after lines"
        echo "Delta:           $((lines_after - lines_before))"
        echo ""
        echo "Head commit (pre-push):"
        echo "$head_msg"
        echo ""
        echo "git diff --stat HEAD~1..HEAD -- $target:"
        git diff --stat "HEAD~1..HEAD" -- "$target"
    } > "$shrink_report" 2>&1
    log "SHRINK DETECTED ($context): $lines_before -> $lines_after lines. Report: $shrink_report"
    # Undo the commit so origin is not polluted with a suspect shrink.
    # Files remain on disk for inspection.
    #
    # audit low (eleventh re-audit): --mixed, not --soft. A soft reset
    # leaves the truncated corpus STAGED, so the very next block's
    # `git add -A`/`git commit` re-commits it — and the operator, running
    # `git status` to see what happened, is told the shrink is ready to
    # commit. --mixed keeps the file on disk and unstages it.
    if ! git reset --mixed "HEAD~1" >>"$LOG_FILE" 2>&1; then
        log "WARNING: failed to reset HEAD~1 after shrink detection; manual recovery may be needed"
    fi
    fail "data submodule: unexpected shrink detected at the $context (see $shrink_report). Push aborted. If intentional, commit with 'Rewrite-Class: bulk' trailer and retry." 4
}

abort_on_published_shrink() {
    # abort_on_published_shrink <context>
    #
    # The same invariant, one step further out: nothing this script PUSHES
    # may shrink the corpus against what origin already holds, whoever
    # made the commit.
    #
    # audit M4 (eleventh re-audit): abort_on_jsonl_shrink covers the two
    # commits this script makes. It says nothing about a commit made by
    # commit-data.sh, by monthly-archive.py, or by hand — and the
    # ahead-of-origin push below publishes whatever is on the branch. A
    # truncation committed by anything else therefore reached origin
    # unexamined, which is the same data loss by another door.
    #
    # Trailer-aware over the WHOLE unpushed range: a deliberate bulk
    # rewrite is one commit in it carrying `Rewrite-Class: bulk`. Nothing
    # is reset here — these commits are not necessarily ours to undo — so
    # the run stops with the branch intact and the gate says what to look
    # at.
    #
    # Must be called from inside the data submodule, immediately before a
    # push.
    local context="$1" lines_before lines_after shrink_report
    local target="memories/memories.jsonl"
    [[ "$DETECT_JSONL_SHRINK" == "true" ]] || return 0
    # No origin/main means the S1 guard has already withheld the bump and
    # there is nothing to compare against.
    git rev-parse --verify --quiet origin/main >/dev/null 2>&1 || return 0
    lines_before=$(git show "origin/main:$target" 2>/dev/null | wc -l) || lines_before=0
    lines_after=$(git show "HEAD:$target" 2>/dev/null | wc -l) || lines_after=0
    [[ "$lines_after" -lt "$lines_before" ]] || return 0
    if git log --format=%B origin/main..HEAD 2>/dev/null \
            | grep -q "^Rewrite-Class: bulk"; then
        log "corpus shrank against origin/main but the range carries a Rewrite-Class: bulk trailer — allowed"
        return 0
    fi
    shrink_report="$LOG_DIR/daily-sync-shrink-$(date +'%Y-%m-%d-%H%M%S').log"
    {
        echo "Refusing to publish: memories.jsonl is shorter than origin's copy."
        echo "Push site:            $context"
        echo "origin/main:          $lines_before lines"
        echo "HEAD:                 $lines_after lines"
        echo "Delta:                $((lines_after - lines_before))"
        echo ""
        echo "Unpushed commits (git log --oneline origin/main..HEAD):"
        git log --oneline origin/main..HEAD
        echo ""
        echo "git diff --stat origin/main..HEAD -- $target:"
        git diff --stat "origin/main..HEAD" -- "$target"
    } > "$shrink_report" 2>&1
    log "SHRINK DETECTED against origin ($context): $lines_before -> $lines_after lines. Report: $shrink_report"
    add_sync_gate_detail \
        "daily-sync STOPPED: the unpushed commits in $DATA_DIR would publish a memories.jsonl SHORTER than origin's ($lines_before -> $lines_after lines) and none of them carries a 'Rewrite-Class: bulk' trailer. Nothing has been pushed and nothing was undone — the commits are still on the branch. Read $shrink_report, then either fix the history or re-commit the rewrite with the trailer."
    fail "data submodule: refusing to publish a corpus shorter than origin's (see $shrink_report)" 4
}

# Commit the append-only memory files BEFORE considering a stash. They are
# dirty on nearly every run, so this usually empties the tree and no stash
# is taken at all — which removes the failure mode rather than handling it.
# A commit survives a kill; an un-popped stash is invisible until someone
# goes looking. Explicit pathspec, so a concurrent session's edits to any
# other file are untouched.
committed_memory_appends=0
if [[ $DRY_RUN -eq 0 ]]; then
    # audit C2: before anything is staged. Unconditional, because a
    # marker-laden corpus need not be dirty — an earlier run may already
    # have committed one.
    refuse_if_memory_markers "append-only commit"
    memory_dirty=()
    for _mf in "${MEMORY_APPEND_FILES[@]}"; do
        _mf_status="$(git status --porcelain -- "$_mf")"
        [[ -n "$_mf_status" ]] || continue
        # An UNMERGED path is "dirty" too, and add/add or delete/delete
        # conflicts leave no markers for the content check above to find.
        if [[ "$_mf_status" =~ ^(UU|AA|DD|AU|UA|DU|UD)\  ]]; then
            add_sync_gate_detail \
                "daily-sync STOPPED: $_mf is unmerged in $DATA_DIR. Resolve it — $PA_DIR/venv/bin/python3 $SCRIPT_DIR/resolve-merge-conflicts.py $DATA_DIR/$_mf for a text conflict, otherwise by hand — then run the sync again. Do NOT 'git add' it while markers remain."
            fail "$_mf is unmerged; refusing to stage or commit it"
        fi
        memory_dirty+=("$_mf")
    done
    if [[ ${#memory_dirty[@]} -gt 0 ]]; then
        log "data submodule: committing append-only memory files (${memory_dirty[*]})"
        git add -- "${memory_dirty[@]}" >>"$LOG_FILE" 2>&1 || fail "git add of memory files failed"
        if git commit -q -m "chore(memories): append-only capture from $HOST $(date +'%Y-%m-%d %H:%M')" \
                -- "${memory_dirty[@]}" >>"$LOG_FILE" 2>&1; then
            committed_memory_appends=1
            # audit S23: the corpus can already be short when the run
            # starts — this block is where such a truncation is committed,
            # and the ahead-of-origin push below publishes it whether or
            # not the auto-sync block ever runs.
            abort_on_jsonl_shrink "append-only commit"
        else
            log "data submodule: nothing to commit for memory files (raced)"
        fi
    fi
fi

if [[ -n "$(git status --porcelain)" ]]; then
    log "data submodule has local changes; stashing for pull"
    if [[ $DRY_RUN -eq 0 ]]; then
        _sha="$(push_stash "$DATA_DIR" "daily-sync on $HOST $(date +'%Y-%m-%d %H:%M')")" \
            || fail "stash push failed"
        data_stash_shas+=("$_sha")
    fi
fi

# Pull remote. Fast-forward is still the expected case and is tried first.
# It is no longer guaranteed: committing the memory appends above can leave
# a local commit, so origin having moved makes this a divergence rather than
# a fast-forward. Fall back to a rebase, which is the correct operation for
# an append-only file, and reuse the append-safe resolver on conflict.
log "data submodule: pulling origin/main"
if [[ $DRY_RUN -eq 0 ]]; then
    if ! git pull --ff-only origin main >>"$LOG_FILE" 2>&1; then
        log "data submodule: not fast-forwardable — rebasing local commits onto origin"
        if ! GIT_EDITOR=true git pull --rebase origin main >>"$LOG_FILE" 2>&1; then
            resolve_rebase_conflicts "data submodule" \
                || fail "data submodule pull failed (rebase unresolvable — manual resolution required)"
        fi
    fi
fi

# Pop the stashes this run pushed and resolve conflicts if they arise.
# audit C1: EVERY recorded stash, oldest first — not just whatever happens
# to be on top of the stack.
if [[ ${#data_stash_shas[@]} -gt 0 ]] && [[ $DRY_RUN -eq 0 ]]; then
    log "data submodule: popping ${#data_stash_shas[@]} stashed change set(s)"
    # Oldest first — the order the changes were made. Two stashes that
    # touch the same file cannot both apply: the second pop is refused,
    # and the entry it names is gated by the EXIT handler. The list is
    # NOT cleared here: an entry that pops leaves the stack, so whatever
    # is still resolvable at exit is still unrecovered.
    for (( _si=0; _si<${#data_stash_shas[@]}; _si++ )); do
        _sha="${data_stash_shas[_si]}"
        if ! stash_ref_for "$DATA_DIR" "$_sha" >/dev/null; then
            log "data submodule: stash ${_sha:0:8} is no longer on the stack — skipping"
            continue
        fi
        snapshot_before_apply "$DATA_DIR"
        if ! apply_stash_by_sha "$DATA_DIR" "$_sha"; then
            # The apply either left the tree conflicted (git preserves the
            # entry) or refused to apply at all. Either way the EXIT
            # handler must not try again: into a half-merged tree that
            # corrupts it, and into a refusal it just fails again.
            stash_restore_allowed=0
            # audit M1 (sixth re-audit): if it conflicted, its content IS
            # in the tree — as markers. That is neither lost work to pop
            # nor clean work to delete, and it gets its own advice.
            # audit C1 (ninth): by what THIS apply changed.
            classify_apply_failure "$DATA_DIR" "$_sha"
            if [[ "$apply_outcome" == "partial" ]]; then
                # audit S27 (tenth re-audit): STOP HERE. Resolving the
                # markers below and dropping the entry — which is what
                # the conflicted path does, with rc 0 and a clean gate —
                # destroys the only copy of the untracked files this
                # apply could not write. Recovering them means choosing
                # between the entry's copy and whatever is in the tree,
                # which is a decision for a human, not a resolver.
                record_partial_stash "$DATA_DIR" "$_sha" "$apply_outcome_untracked"
                add_sync_gate_detail \
                    "daily-sync STOPPED: applying stash $(describe_stash "$DATA_DIR" "$_sha") in $DATA_DIR succeeded only PARTLY — it restored the tracked changes but NOT ${apply_outcome_untracked//$'\n'/, }, and those files exist ONLY inside the entry. Recover them (git -C $DATA_DIR checkout ${_sha}^3 -- <path>; inspect with git -C $DATA_DIR show ${_sha}^3:<path>), resolve any conflict markers, and only then delete the entry."
                fail "data submodule: applying stash ${_sha:0:8} restored only part of it — ${apply_outcome_untracked//$'\n'/, } are still only in the entry; manual recovery required"
            fi
            if [[ "$apply_outcome" == "conflicted" ]]; then
                record_conflicted_stash "$DATA_DIR" "$_sha" "$apply_outcome_paths"
            elif [[ "$apply_outcome" == "blocked" ]]; then
                blocked_stash_shas+=("$_sha")
            fi
            log "stash pop raised conflicts — running resolver"
            conflicted_files=()
            while IFS= read -r line; do
                # Any unmerged state: UU (both modified), AA (both added),
                # DD (both deleted), and the mixed forms AU/UA/DU/UD.
                # See git status(1), "Short Format" § Porcelain.
                if [[ "$line" =~ ^(UU|AA|DD|AU|UA|DU|UD)\ (.+)$ ]]; then
                    conflicted_files+=("${BASH_REMATCH[2]}")
                fi
            done < <(git status --porcelain)

            if [[ ${#conflicted_files[@]} -eq 0 ]]; then
                # audit C1 (second re-audit): `git stash pop` REFUSES
                # outright — rc 1, "your local changes would be
                # overwritten", nothing unmerged — when applying it would
                # clobber the working tree. Two stashes this run pushed
                # that touch the same file do exactly that: the first pop
                # restores the file, the second is refused. The tree is
                # untouched and the entry is still on the stack, so the
                # EXIT handler's stranded-stash check gates it by SHA and
                # message; do not try to be cleverer than that here.
                fail "applying stash ${_sha:0:8} was refused (nothing unmerged) — the stash is preserved; see the gate line for how to recover it"
            fi

            # audit S3: partition exactly as the rebase path does
            # (resolve_rebase_conflicts, see its header). The resolver
            # strips conflict markers and unions both sides — correct for
            # append-only files, destructive for anything else. Feeding it
            # every conflicted path meant a conflicted tasks/inbox.md or
            # wiki/continuity.md was silently rewritten as an interleaved
            # union with duplicate lines dropped, then committed and
            # pushed. Silently guessing on a prose file is how a
            # concurrent session's work gets destroyed.
            unsupported_conflicts=()
            resolvable_conflicts=()
            for f in "${conflicted_files[@]}"; do
                if is_memory_append_file "$f"; then
                    resolvable_conflicts+=("$f")
                else
                    unsupported_conflicts+=("$f")
                fi
            done
            if [[ ${#unsupported_conflicts[@]} -gt 0 ]]; then
                # Leave the tree exactly as git left it: half-merged, with
                # the stash still on the stack (git preserves the entry
                # when a pop conflicts). Anything tidier — `git checkout
                # -- .`, a re-pop — would risk the very edits at stake.
                add_sync_gate_detail \
                    "daily-sync STOPPED: stash pop conflicted on ${unsupported_conflicts[*]} in $DATA_DIR; conflict markers and the stash are preserved. Resolve by hand (git -C $DATA_DIR status), then the next session syncs."
                fail "stash pop conflicted on unsupported paths (${unsupported_conflicts[*]}) — manual resolution required; conflict markers and the stash are preserved"
            fi

            # Build absolute paths for the resolver
            resolver_paths=()
            for f in "${resolvable_conflicts[@]}"; do
                resolver_paths+=("$DATA_DIR/$f")
            done

            timeout 60 "$PA_DIR/venv/bin/python3" "$RESOLVER" --quiet-if-clean \
                "${resolver_paths[@]}" >>"$LOG_FILE" 2>&1 \
                || fail "resolve-merge-conflicts.py failed" 3

            # audit C2: the resolver is supposed to have removed every
            # marker from these files; stage them only once that is true.
            refuse_if_memory_markers "post-resolver stage"
            git add "${resolvable_conflicts[@]}" >>"$LOG_FILE" 2>&1 \
                || fail "git add after resolver failed"
            # audit C1: drop the entry we actually applied, and audit C2:
            # resolve its selector NOW, not before the resolver ran. A
            # stale selector here destroyed a concurrent session's stash.
            # Its contents are in the tree either way (audit M2).
            drop_applied_stash "$DATA_DIR" "$_sha" "data submodule" || true
            # audit M1 (third re-audit): the conflict is resolved, staged,
            # and its stash dropped, so the tree is no longer half-merged
            # and later stashes are safe to restore again. Without this
            # reset the flag was a one-way latch: a conflicted pop here
            # left the EXIT handler unable to restore the PARENT stash on
            # any later abort, silently reverting settings.json.
            stash_restore_allowed=1
            log "conflicts resolved: ${conflicted_files[*]}"
        else
            # A clean apply. `git stash pop` used to drop the entry for us;
            # apply does not, so drop it explicitly — by SHA, resolved now.
            drop_applied_stash "$DATA_DIR" "$_sha" "data submodule" || true
        fi
    done
fi

# Commit + push if there's anything to commit.
if [[ $DRY_RUN -eq 0 ]] && [[ -n "$(git status --porcelain)" ]]; then
    log "data submodule: committing merged local changes"
    # audit C2: `git add -A` sweeps whatever is dirty, so this is the last
    # place a marker-laden corpus could slip into a commit and be pushed.
    refuse_if_memory_markers "auto-sync commit"
    git add -A >>"$LOG_FILE" 2>&1
    git commit -m "chore(auto-sync): daily sync from $HOST $(date +'%Y-%m-%d')" \
        >>"$LOG_FILE" 2>&1 || fail "data commit failed"
    abort_on_jsonl_shrink "auto-sync commit"
    abort_on_published_shrink "auto-sync commit"
    push_with_retry "data submodule"
else
    log "data submodule: nothing to commit"
fi

# audit S1: the block above pushes only when it made a commit itself. A
# commit made EARLIER in this run — the append-only memory commit above,
# or archive-agent-mail.py's own commit — usually empties the tree, so
# the block takes its "nothing to commit" branch and never pushes; the
# parent pointer bump referencing that commit is pushed anyway, leaving
# origin's personal-assistant naming a pa-data SHA the other machine
# cannot fetch ("reference is not a tree"). Observed live 2026-09-08
# 09:29; monthly-archive.py:522-539 already carries a local workaround
# for the same hole. Push whenever HEAD is ahead of its upstream rather
# than only when this block committed. origin/main is used rather than
# @{u} because that is the ref push_with_retry actually pushes to, and
# a submodule clone does not always have upstream tracking configured.
data_publishable=1
if [[ $DRY_RUN -eq 0 ]]; then
    if git rev-parse --verify --quiet origin/main >/dev/null 2>&1; then
        unpushed="$(git rev-list --count origin/main..HEAD 2>/dev/null || echo 0)"
        if [[ "$unpushed" -gt 0 ]]; then
            log "data submodule: $unpushed commit(s) ahead of origin/main — pushing"
            # audit M4: this push publishes commits nothing in this run
            # made or inspected.
            abort_on_published_shrink "ahead-of-origin push"
            push_with_retry "data submodule"
        fi
    else
        # audit M1: without origin/main there is no way to tell whether the
        # submodule HEAD has been published, so the check above cannot run
        # — and falling through to the parent bump would publish a pointer
        # to a possibly-unpushed commit, which is precisely the S1 state
        # this block exists to prevent. Withhold the bump instead.
        data_publishable=0
        log "data submodule: no origin/main ref — cannot verify that HEAD is published"
    fi
fi

# ---------------------------------------------------------------------------
# Parent repo sync
# ---------------------------------------------------------------------------

cd "$PA_DIR"

# Ensure the parent repo is on main before any pull / commit / push.
# `push_with_retry` hardcodes `git push origin main` and the rebase
# paths above pull `origin main` regardless of the local branch — on
# a feature branch the bump commit would land on the feature branch
# while the (unchanged) local main was published, silently orphaning
# the bump. Mirrors the data-half guard at line 268-275 and the
# parallel guard added to commit-data.sh in `db957e5`.
# audit M3 (ninth re-audit): the parent's turn, immediately before
# anything touches it, so the data half has already run.
check_interrupted_state "$PA_DIR" "parent repo"

parent_current_branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$parent_current_branch" != "main" ]]; then
    log "parent repo on '$parent_current_branch' — switching to main"
    if [[ $DRY_RUN -eq 0 ]]; then
        git checkout main >>"$LOG_FILE" 2>&1 \
            || fail "failed to switch parent repo to main"
    fi
fi

# Stash any uncommitted parent-repo changes (typical case: per-machine
# settings.json edits) before the pull, mirroring the data-submodule
# guard above. Without this, `git pull --ff-only` aborts on a dirty
# tree and the EXIT trap is what keeps the work safe. The submodule
# pointer (`data`) is intentionally excluded from the stash via
# pathspec so the bump-detection diff below still sees it.
if [[ -n "$(git status --porcelain -- ':!data')" ]]; then
    log "parent repo has local changes; stashing for pull"
    if [[ $DRY_RUN -eq 0 ]]; then
        _sha="$(push_stash "$PA_DIR" \
            "daily-sync parent on $HOST $(date +'%Y-%m-%d %H:%M')" -- ':!data')" \
            || fail "parent stash push failed"
        parent_stash_shas+=("$_sha")
    fi
fi

log "parent repo: pulling origin/main"
if [[ $DRY_RUN -eq 0 ]]; then
    git pull --ff-only origin main >>"$LOG_FILE" 2>&1 \
        || fail "parent pull failed (not fast-forwardable — manual merge needed)"
fi

# Pop the parent stash before the bump-detection diff so any locally
# modified files are back in the working tree. Conflicts here are
# unexpected (parent-repo files are rarely touched by remotes) and
# warrant manual intervention rather than the JSONL resolver.
if [[ ${#parent_stash_shas[@]} -gt 0 ]] && [[ $DRY_RUN -eq 0 ]]; then
    log "parent repo: popping ${#parent_stash_shas[@]} stashed change set(s)"
    # audit C1: same treatment as the data half — pop the entries this run
    # pushed, by SHA, oldest first, leaving the list intact so the EXIT
    # handler can gate anything that did not come back.
    for (( _si=0; _si<${#parent_stash_shas[@]}; _si++ )); do
        _sha="${parent_stash_shas[_si]}"
        if ! stash_ref_for "$PA_DIR" "$_sha" >/dev/null; then
            log "parent repo: stash ${_sha:0:8} is no longer on the stack — skipping"
            continue
        fi
        snapshot_before_apply "$PA_DIR"
        if ! apply_stash_by_sha "$PA_DIR" "$_sha"; then
            # The entry is preserved by git either way, and the EXIT
            # handler must not try again.
            stash_restore_allowed=0
            #
            # audit M3: this wedges every later run — the next
            # `git stash push -u -- ':!data'` refuses while a path is
            # unmerged — and nothing but the log said so.
            #
            # audit C1 (seventh re-audit): CONFLICTED and REFUSED are
            # different states with opposite advice, and the parent half
            # had neither. A conflicted apply put its content in the tree
            # as markers — popping it again would apply the same content
            # on top of them — while a refused one left the tree untouched
            # and its work only in the stash, where a pop is exactly right.
            #
            # audit S27 (tenth re-audit): and PARTIAL is a fourth state
            # this branch used to call REFUSED — telling the operator
            # "the tree was left untouched and the work is only in the
            # stash" about a tree that had just been half-written, and
            # inviting a pop that git refuses again for the same reason.
            classify_apply_failure "$PA_DIR" "$_sha"
            if [[ "$apply_outcome" == "partial" ]]; then
                record_partial_stash "$PA_DIR" "$_sha" "$apply_outcome_untracked"
                add_sync_gate_detail \
                    "daily-sync STOPPED: applying parent-repo stash $(describe_stash "$PA_DIR" "$_sha") in $PA_DIR restored only part of it — ${apply_outcome_untracked//$'\n'/, } exist ONLY inside the entry, and the rest is already in the tree. Recover those files (git -C $PA_DIR checkout ${_sha}^3 -- <path>) before you delete the entry, and do NOT pop it."
                fail "parent repo: applying stash ${_sha:0:8} restored only part of it — manual recovery required"
            fi
            if [[ "$apply_outcome" == "conflicted" ]]; then
                # audit L9 (eighth re-audit): the diagnosis only. The
                # recovery advice comes from the conflicted group in the
                # EXIT handler, which names every such entry in full —
                # saying it here as well told the operator twice.
                record_conflicted_stash "$PA_DIR" "$_sha" "$apply_outcome_paths"
                add_sync_gate_detail \
                    "daily-sync STOPPED: applying parent-repo stash $(describe_stash "$PA_DIR" "$_sha") in $PA_DIR conflicted."
                fail "parent repo: applying stash ${_sha:0:8} raised conflicts — manual resolution required"
            fi
            if [[ "$apply_outcome" == "blocked" ]]; then
                blocked_stash_shas+=("$_sha")
                add_sync_gate_detail \
                    "daily-sync STOPPED: applying parent-repo stash $(describe_stash "$PA_DIR" "$_sha") was BLOCKED by an earlier unresolved conflict in $PA_DIR. Its entry is intact. Resolve that conflict first, then pop this one."
                fail "parent repo: applying stash ${_sha:0:8} was blocked by an earlier conflict"
            fi
            add_sync_gate_detail \
                "daily-sync STOPPED: applying parent-repo stash $(describe_stash "$PA_DIR" "$_sha") in $PA_DIR was REFUSED — the tree was left untouched and the work is only in the stash. Clear whatever collides (git -C $PA_DIR status), then pop it: git -C $PA_DIR stash pop <ref>."
            fail "parent repo: applying stash ${_sha:0:8} was refused — manual resolution required"
        else
            drop_applied_stash "$PA_DIR" "$_sha" "parent repo" || true
        fi
    done
fi

# Bump submodule pointer if the data submodule moved.
if [[ $DRY_RUN -eq 0 ]] && ! git diff --quiet data; then
    # audit M1: only publish a pointer we know is fetchable. The data half
    # sets data_publishable=0 when it could not confirm the submodule HEAD
    # reached origin; bumping anyway is how origin comes to name a pa-data
    # SHA the other machine cannot fetch (audit S1).
    if [[ $data_publishable -eq 1 ]]; then
        log "parent repo: data submodule pointer moved — committing bump"
        git add data >>"$LOG_FILE" 2>&1
        git commit -m "chore(auto-sync): bump data pointer from $HOST $(date +'%Y-%m-%d')" \
            >>"$LOG_FILE" 2>&1 || fail "parent commit failed"
        push_with_retry "parent repo"
    else
        log "parent repo: pointer moved but the data submodule is not verifiably published — bump WITHHELD"
        add_sync_gate_detail \
            "daily-sync: the data submodule has no origin/main ref, so the parent pointer bump was withheld — publishing it would name a pa-data commit the other machine cannot fetch. Check the submodule's remote (git -C $DATA_DIR remote -v) and fetch it."
    fi
else
    log "parent repo: nothing to commit"
fi

# ---------------------------------------------------------------------------
# cc-archives sync — keep local ~/cc-archives/ and the canonical store at
# ~/mnt/rpi-shares/cc-archives-consolidated/ convergent (Phase 0 Step 8,
# landed 2026-05-22; metadata-convergence passes added 2026-05-28).
#
# Architecture: rpi-server's SSD share holds the canonical store;
# working machines hold full local mirrors at ~/cc-archives/. The
# production archive hook writes to the local mirror.
#
# Three passes:
#   1. Append-only UP (--ignore-existing): pushes NEW sessions, subagents,
#      v2-backups, and metas for brand-new sessions up to canonical. Never
#      overwrites, never deletes — canonical is authoritative for anything
#      already present. This is the common-case daily path.
#   2. Metadata UP (--update): propagates IN-PLACE metadata rewrites
#      (e.g. a --upgrade-to-v13 re-summarisation run on this machine) up to
#      canonical. The append-only pass cannot do this — --ignore-existing
#      skips every path already present, so a rewritten session.meta.json
#      would otherwise never reach the source of truth (the gap that
#      stranded the 2026-05-26/28 v1.3 upgrade on amd-tower until fixed by
#      hand). Newest-mtime-wins; scoped to the mutable-in-place files only.
#   3. Metadata DOWN (--update): pulls canonical's newer metas back to the
#      local mirror, so a re-summarisation run done on ANOTHER machine
#      reaches this one. Keeps mirrors convergent without a manual
#      cross-machine push.
#
# Transcripts/subagents are append-only and never change, so passes 2-3
# deliberately exclude them — only session.meta.json and CATALOG.json get
# rewritten in place. Newest-mtime-wins is acceptable here: each session is
# effectively owned by its origin machine and bulk rewrites are rare and
# run from a single machine, so cross-machine write collisions on the same
# meta are not expected.
#
# Conservative semantics retained:
# - Skip silently if rpi-shares isn't mounted (Shawn may be travelling,
#   network may be down). Don't fail the whole daily-sync over this.
# - Mount-presence check uses `df` grep to distinguish a live SSHFS
#   mount from the silent-empty-dir failure mode where ~/mnt/rpi-shares/
#   exists locally but isn't backed by rpi-server. This guard also
#   protects the DOWN pass from pulling an empty dir over the local mirror.
# ---------------------------------------------------------------------------

if [[ $DRY_RUN -eq 0 ]]; then
    CC_ARCHIVES_LOCAL="$HOME/cc-archives"
    CC_ARCHIVES_CANONICAL="$HOME/mnt/rpi-shares/cc-archives-consolidated"

    # Self-healing mount (2026-08-22). The mount was manual (an interactive
    # alias), so this pass silently skipped on every day nobody mounted by
    # hand — 30 skips vs 25 successes between 2026-06-08 and 2026-08-20,
    # leaving the canonical store the STALEST of the three copies. Attempt
    # the mount ourselves before deciding to skip: fast SSH probe first so
    # an away-from-home machine skips in ~5s instead of hanging, then the
    # same sshfs invocation as the `mount-rpi-shares` alias (reconnect
    # keeps it healthy across suspends; leave it mounted afterwards).
    if [[ ! -d "$CC_ARCHIVES_CANONICAL" ]] \
            || ! df "$CC_ARCHIVES_CANONICAL" 2>/dev/null | tail -1 | grep -q "rpi-server"; then
        if command -v sshfs >/dev/null 2>&1 \
                && ssh -o BatchMode=yes -o ConnectTimeout=5 rpi-server true >/dev/null 2>&1; then
            log "cc-archives sync: rpi-shares not mounted — attempting self-mount"
            # A dead FUSE endpoint (laptop suspended past the reconnect
            # window) blocks a fresh mount — lazily unmount it first.
            if mount | grep -q "$HOME/mnt/rpi-shares"; then
                fusermount -uz "$HOME/mnt/rpi-shares" >>"$LOG_FILE" 2>&1 || true
            fi
            mkdir -p "$HOME/mnt/rpi-shares"
            if timeout 20 sshfs -o compression=no,ServerAliveInterval=15,reconnect \
                    shawn@rpi-server:/opt/encrypted/workspace/shares \
                    "$HOME/mnt/rpi-shares" >>"$LOG_FILE" 2>&1; then
                log "cc-archives sync: self-mount succeeded"
            else
                log "cc-archives sync: self-mount FAILED (see log) — will skip"
            fi
        else
            log "cc-archives sync: rpi-server unreachable (away from home?) — will skip"
        fi
    fi

    # rsync filter for the metadata-convergence passes: descend into all
    # directories, transfer only the in-place-mutable files, exclude
    # everything else (transcripts, subagents — handled by the append-only
    # pass). -rt (not -a) avoids needless group/owner/perm churn on the
    # shared store.
    CC_META_FILTER=(
        --include='*/'
        --include='session.meta.json'
        --include='CATALOG.json'
        --exclude='*'
    )

    if [[ ! -d "$CC_ARCHIVES_CANONICAL" ]]; then
        log "cc-archives sync: mount point missing ($CC_ARCHIVES_CANONICAL) — skipped"
    elif ! df "$CC_ARCHIVES_CANONICAL" 2>/dev/null | tail -1 | grep -q "rpi-server"; then
        log "cc-archives sync: rpi-shares not mounted (silent-empty-dir state) — skipped"
    elif [[ ! -d "$CC_ARCHIVES_LOCAL" ]]; then
        log "cc-archives sync: $CC_ARCHIVES_LOCAL missing — nothing to push"
    else
        log "cc-archives sync [1/4]: append-only push $CC_ARCHIVES_LOCAL/ → canonical"
        if rsync -a --ignore-existing --stats \
            "$CC_ARCHIVES_LOCAL/" "$CC_ARCHIVES_CANONICAL/" \
            >>"$LOG_FILE" 2>&1; then
            log "cc-archives sync [1/4]: complete"
        else
            log "cc-archives sync [1/4]: rsync exited non-zero (see log)"
        fi

        log "cc-archives sync [2/4]: metadata --update push → canonical"
        if rsync -rt --update --stats "${CC_META_FILTER[@]}" \
            "$CC_ARCHIVES_LOCAL/" "$CC_ARCHIVES_CANONICAL/" \
            >>"$LOG_FILE" 2>&1; then
            log "cc-archives sync [2/4]: complete"
        else
            log "cc-archives sync [2/4]: rsync exited non-zero (see log)"
        fi

        log "cc-archives sync [3/4]: metadata --update pull canonical → local"
        if rsync -rt --update --stats "${CC_META_FILTER[@]}" \
            "$CC_ARCHIVES_CANONICAL/" "$CC_ARCHIVES_LOCAL/" \
            >>"$LOG_FILE" 2>&1; then
            log "cc-archives sync [3/4]: complete"
        else
            log "cc-archives sync [3/4]: rsync exited non-zero (see log)"
        fi

        # Pass 4 (B7 decision, 2026-07-22): append-only transcript pull,
        # canonical → local. Passes 1–3 push transcripts up and sync
        # metadata both ways, but never pull transcripts down — so a
        # machine only held transcripts for sessions it archived itself,
        # and sessions archived on the other machine appeared locally as
        # meta-only shells (discovered via the abductive-anchor retro-
        # matching, 2026-07-22). Working machines now carry full mirrors:
        # zbook needs offline completeness when travelling, and symmetric
        # full mirrors keep every consumer (search-sessions, matching
        # agents) single-path. See wiki/planning/
        # session-archiving-upgrade-plan-2026-07-21.md items B7/E3a.
        log "cc-archives sync [4/4]: append-only transcript pull canonical → local"
        if rsync -a --ignore-existing --stats \
            "$CC_ARCHIVES_CANONICAL/" "$CC_ARCHIVES_LOCAL/" \
            >>"$LOG_FILE" 2>&1; then
            log "cc-archives sync [4/4]: complete"
        else
            log "cc-archives sync [4/4]: rsync exited non-zero (see log)"
        fi

        # Completeness gate (B7): count metas that record a transcript
        # hash (archive.jsonl_sha256) but have no sibling transcript on
        # disk and no explicit transcript_lost write-off marker. Result
        # goes to a machine-local status file; daily-sync-trigger.sh
        # surfaces a warning at every session start while the count is
        # non-zero. This makes transcript-partial state explicit instead
        # of silent — the failure mode that hid the meta-only shells.
        GATE_FILE="$CACHE_DIR/cc-archives-gate"
        # audit L3: every other call in this script uses $PA_DIR; this one
        # hardcoded ~/personal-assistant, so a run from a worktree or a
        # relocated checkout would use another tree's interpreter (or none).
        "$PA_DIR/venv/bin/python3" - "$CC_ARCHIVES_LOCAL" "$GATE_FILE" <<'PYEOF' >>"$LOG_FILE" 2>&1 || log "cc-archives gate: check failed (see log)"
import json, sys
from pathlib import Path
root, gate = Path(sys.argv[1]), Path(sys.argv[2])
missing = []
for meta_p in root.rglob("session.meta.json"):
    try:
        m = json.load(open(meta_p))
    except Exception:
        continue
    arch = m.get("archive", {}) or {}
    if not arch.get("jsonl_sha256"):
        continue                      # no transcript ever recorded
    if arch.get("transcript_lost"):
        continue                      # explicitly written off (B6)
    d = meta_p.parent
    if not (d / "session.jsonl.gz").exists() and not (d / "session.jsonl").exists():
        missing.append(str(d.relative_to(root)))
gate.parent.mkdir(parents=True, exist_ok=True)
lines = [str(len(missing))] + sorted(missing)[:20]
if len(missing) > 20:
    lines.append(f"... +{len(missing) - 20} more")
gate.write_text("\n".join(lines) + "\n")
print(f"cc-archives gate: {len(missing)} meta(s) lack a local transcript")
PYEOF
        if [[ -f "$GATE_FILE" ]]; then
            log "cc-archives gate: $(head -1 "$GATE_FILE") missing transcript(s) recorded to $GATE_FILE"
        fi

        # cc-archives → Cloudflare R2 (Phase 0e offsite backup). Runs AFTER
        # the local⇄canonical convergence above so R2 mirrors the
        # up-to-date source of truth. push-archives-to-r2.sh is
        # self-contained (own .env load, mount + remote checks) and exits
        # non-zero on skip (1) or rclone error (2); wrap in `if` so a
        # backup hiccup never aborts the rest of daily-sync under set -e.
        #
        # Single-owner gate: only the designated host pushes to R2. All
        # working machines converge to the same canonical store, so every
        # machine would otherwise push byte-identical content (idempotent
        # under `copy`, but wasteful). The push also only works at home
        # (needs the rpi-shares mount), and amd-tower is the always-on home
        # desktop — the natural sole owner. This also means other machines'
        # rclone version is irrelevant to the backup (only the owner needs
        # rclone >= 1.64 for clean R2 uploads).
        R2_PUSH_HOST="AMD-tower-ubuntu"
        if [[ "$HOST" == "$R2_PUSH_HOST" ]]; then
            log "cc-archives → R2: starting offsite push"
            if bash "$SCRIPT_DIR/push-archives-to-r2.sh" >>"$LOG_FILE" 2>&1; then
                log "cc-archives → R2: complete"
            else
                log "cc-archives → R2: push skipped or errored (rc=$?; see r2-push.log)"
            fi
        else
            log "cc-archives → R2: skipped (push owner is $R2_PUSH_HOST, this is $HOST)"
        fi
    fi
fi

# ---------------------------------------------------------------------------
# Symlink sync (heals skill/command/agent drift after new files land)
# ---------------------------------------------------------------------------

if [[ $DRY_RUN -eq 0 ]]; then
    log "refreshing ~/.claude/ symlinks + global CLAUDE.md"
    bash "$SCRIPT_DIR/sync-symlinks.sh" --quiet >>"$LOG_FILE" 2>&1 \
        || fail "sync-symlinks.sh failed (symlink drift NOT healed this run)"
fi

# ---------------------------------------------------------------------------
# Memory-store drift check (added 2026-08-20)
#
# This script stashes uncommitted data-submodule changes before pulling and
# pops them afterwards. The extraction hook appends to memories.jsonl
# continuously, so there are almost always uncommitted appends inside that
# window. If a run does not reach its pop -- on 2026-08-19 a second
# daily-sync started mid-run and the first never popped -- those appends are
# orphaned into a stash nobody looks at. 41 records were lost that way (38
# surviving only in PostgreSQL, 3 surviving only in a July stash).
#
# The check is read-only and never recovers automatically: recovery appends
# to the canonical store, which is a human decision. It only reports.
# ---------------------------------------------------------------------------

if [[ $DRY_RUN -eq 0 ]]; then
    # Gate file mirrors the cc-archives / syncthing gates: first line is a
    # problem count (0 = clean), remaining lines describe the problem.
    # daily-sync-trigger.sh surfaces a non-zero count at EVERY session
    # start — a detector that reports only into a log nobody reads is
    # indistinguishable from no detector (2026-08-20 incident; inbox row
    # "Surface drift at SESSION START").
    MEMORY_DRIFT_GATE="$CACHE_DIR/memory-drift-gate"
    if "$PA_DIR/venv/bin/python3" "$SCRIPT_DIR/check-memory-drift.py" \
            --quiet-if-clean >>"$LOG_FILE" 2>&1; then
        log "memory drift check: clean"
        # audit M4: guarded like write_sync_gate — a gate that cannot be
        # written must not abort a run that has already committed and
        # pushed. The log line beside it still records the state.
        printf '0\n' > "$MEMORY_DRIFT_GATE" 2>/dev/null || \
            log "WARNING: could not write $MEMORY_DRIFT_GATE"
    else
        rc=$?
        if [[ $rc -eq 2 ]]; then
            log "memory drift check: COULD NOT RUN (rc=2; see memory-drift.log)"
            # Unknown is not clean: surface it rather than staying silent.
            printf '1\nmemory drift check COULD NOT RUN (PostgreSQL down?) — state unknown; see logs/memory-drift.log\n' \
                > "$MEMORY_DRIFT_GATE" 2>/dev/null || \
                log "WARNING: could not write $MEMORY_DRIFT_GATE"
        else
            log "memory drift check: *** DRIFT DETECTED *** — canonical memory"
            log "  records survive in only one store. See logs/memory-drift.log."
            log "  Recover: venv/bin/python3 scripts/check-memory-drift.py --recover"
            log "  DO NOT run rebuild-postgres.py until this is clean."
            printf '1\nmemory records survive in only ONE store — run scripts/check-memory-drift.py (then --recover); do NOT rebuild-postgres until clean\n' \
                > "$MEMORY_DRIFT_GATE" 2>/dev/null || \
                log "WARNING: could not write $MEMORY_DRIFT_GATE"
        fi
    fi
fi

# ---------------------------------------------------------------------------
# Archive drift check (added 2026-08-22) — the transcript instance of the
# source↔destination reconciliation class-fix. Compares this machine's raw
# ~/.claude/projects sessions (substantive only, 48h grace) against the
# archive mirror and writes ~/.cache/cc-archive-drift-gate; the trigger
# surfaces a non-zero count at session start. Read-only; the remedy is
# bulk-archive.py, run by a human. First run (2026-08-22) found two
# substantive sessions that had leaked — the class is live, not historical.
# ---------------------------------------------------------------------------

if [[ $DRY_RUN -eq 0 ]]; then
    if "$PA_DIR/venv/bin/python3" "$SCRIPT_DIR/check-archive-drift.py" \
            --quiet-if-clean >>"$LOG_FILE" 2>&1; then
        log "archive drift check: clean"
    else
        rc=$?
        if [[ $rc -eq 2 ]]; then
            log "archive drift check: COULD NOT RUN (rc=2)"
        else
            log "archive drift check: *** DRIFT DETECTED *** — un-archived raw sessions; see ~/.cache/cc-archive-drift-gate"
        fi
    fi
fi

# audit C1 (sixth re-audit): the single point at which this run is known
# to have done all of its work. Anything that exits earlier — contention,
# a signal, a failure — leaves whatever gate is already on disk alone.
sync_run_completed=1
clear_sync_gate

log "=== daily-sync complete on $HOST ==="
