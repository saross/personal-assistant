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
    log "ERROR: $*"
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

# Most gate writes are followed by `fail`, but not all: audit M1's withheld
# pointer bump is a problem in a run that otherwise completes. Remember that
# so the end-of-run clear does not wipe a gate this very run raised.
sync_gate_problems=0

write_sync_gate() {
    # write_sync_gate <count> [detail ...]
    # Never fatal: a gate that cannot be written must not itself abort a
    # sync, and the log line beside every call site still records the state.
    sync_gate_problems="$1"
    mkdir -p "$(dirname "$SYNC_GATE")" 2>/dev/null || true
    printf '%s\n' "$@" > "$SYNC_GATE" 2>/dev/null || true
}

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
                "$PA_DIR/venv/bin/python3" "$RESOLVER" --quiet-if-clean \
                    "${jsonl_paths[@]}" >>"$LOG_FILE" 2>&1 \
                    || { git rebase --abort >>"$LOG_FILE" 2>&1 || true; fail "$context: resolver failed during rebase" 3; }
                # audit C2: the same invariant on the rebase path.
                if [[ -n "$(memory_files_with_markers)" ]]; then
                    git rebase --abort >>"$LOG_FILE" 2>&1 || true
                    refuse_if_memory_markers "$context rebase"
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

memory_files_with_markers() {
    # Print each MEMORY_APPEND_FILES path whose CONTENT holds a git
    # conflict-marker line. Must be called from inside the data submodule.
    #
    # Content, not index state (audit C2, second re-audit): the previous
    # check read the porcelain code, so a marker-laden memories.jsonl that
    # somebody had `git add`ed read as a plain modification and was
    # committed and pushed — and the advice this script printed told them
    # to run exactly that `git add`.
    local f
    for f in "${MEMORY_APPEND_FILES[@]}"; do
        [[ -f "$f" ]] || continue
        if grep -qE '^(<<<<<<< |>>>>>>> )|^=======$' -- "$f"; then
            printf '%s\n' "$f"
        fi
    done
}

refuse_if_memory_markers() {
    # refuse_if_memory_markers <what-was-about-to-happen>
    # The invariant: no append-only memory file whose content holds a
    # conflict marker is ever staged or committed, by any block. Every
    # consumer of memories.jsonl parses it as JSONL, so a published marker
    # breaks extraction, recall, and the drift check on both machines at
    # once — and the corpus is append-only, so nothing later repairs it.
    local context="$1" marked=() f
    while IFS= read -r f; do
        [[ -n "$f" ]] && marked+=("$f")
    done < <(memory_files_with_markers)
    if [[ ${#marked[@]} -eq 0 ]]; then
        return 0
    fi
    write_sync_gate 1 \
        "daily-sync STOPPED: ${marked[*]} contain git conflict markers and must not be committed. Resolve with: $PA_DIR/venv/bin/python3 $SCRIPT_DIR/resolve-merge-conflicts.py ${marked[*]/#/$DATA_DIR/} — then just run the sync again. Do NOT 'git add' them by hand: staging markers is how they reach origin."
    fail "$context: ${marked[*]} contain conflict markers; refusing to stage or commit them"
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
        if ! "$PA_DIR/venv/bin/python3" "$RESOLVER" --quiet-if-clean \
                "${paths[@]}" >>"$LOG_FILE" 2>&1; then
            git rebase --abort >>"$LOG_FILE" 2>&1 || true
            log "$context: resolver failed during rebase — aborted"
            return 1
        fi
        # audit C2: never stage a marker, on any path.
        if [[ -n "$(memory_files_with_markers)" ]]; then
            git rebase --abort >>"$LOG_FILE" 2>&1 || true
            refuse_if_memory_markers "$context rebase"
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
#   - they are popped oldest-first, so where two of them touch the same
#     file the most recent state ends up on top.
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
        if git stash pop "$ref" >>"$LOG_FILE" 2>&1; then
            log "  recovered ${sha:0:8} ($ref)"
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
            write_sync_gate 1 \
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

# Crash-safe recovery FIRST — before anything reads or writes the tree.
reconcile_orphaned_stashes

# Stash local changes FIRST (typically memories.jsonl + tag-vocabulary.txt
# from extraction hooks). Stashing works on any ref including detached
# HEAD, and leaves a clean tree so the subsequent checkout/pull cannot
# trip over "local changes would be overwritten".


stranded_stashes() {
    # stranded_stashes <repo> <sha>...
    # Print one "<sha8> <stash@{n}> <message>" line per recorded stash that
    # is STILL on <repo>'s stack, i.e. still holding unrecovered work.
    local repo="$1"
    shift
    local sha ref subject
    for sha in "$@"; do
        ref="$(stash_ref_for "$repo" "$sha")" || continue
        subject="$(git -C "$repo" log -1 --format=%s "$sha" 2>/dev/null || true)"
        printf '%s %s %s\n' "${sha:0:8}" "$ref" "$subject"
    done
}

prepend_sync_gate_detail() {
    # Put <detail> at the top of the gate's detail lines, keeping whatever a
    # failing block already recorded. The trigger surfaces the first detail
    # line, and unrecovered work outranks every other diagnosis.
    local detail="$1" existing=() line
    if [[ -f "$SYNC_GATE" ]]; then
        while IFS= read -r line; do existing+=("$line"); done \
            < <(tail -n +2 "$SYNC_GATE" 2>/dev/null || true)
    fi
    write_sync_gate 1 "$detail" ${existing[@]+"${existing[@]}"}
}

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
    local _i _ref _sha _repo _line _stranded=()
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
                _ref="$(stash_ref_for "$_repo" "$_sha")" || continue
                log "WARNING: aborting before stash pop — restoring ${_sha:0:8} in $_repo"
                if ! git -C "$_repo" stash pop "$_ref" >>"$LOG_FILE" 2>&1; then
                    log "ERROR: automatic stash restore raised conflicts; stash left in place (see 'git stash list')"
                fi
            done
        done
    fi

    # The invariant. Anything of ours still on a stack is unrecovered work.
    while IFS= read -r _line; do
        [[ -n "$_line" ]] && _stranded+=("data submodule: $_line")
    done < <(stranded_stashes "$DATA_DIR" ${data_stash_shas[@]+"${data_stash_shas[@]}"})
    while IFS= read -r _line; do
        [[ -n "$_line" ]] && _stranded+=("parent repo: $_line")
    done < <(stranded_stashes "$PA_DIR" ${parent_stash_shas[@]+"${parent_stash_shas[@]}"})
    if [[ ${#_stranded[@]} -gt 0 ]]; then
        log "STRANDED STASH: ${#_stranded[@]} stash(es) this run pushed are still on a stack:"
        for _i in "${_stranded[@]}"; do log "  $_i"; done
        prepend_sync_gate_detail \
            "daily-sync left ${#_stranded[@]} of its own stash(es) UNRECOVERED — they hold work that is in no commit: ${_stranded[*]}. Recover with: git -C <repo> stash pop <ref> (inspect first: git -C <repo> stash show -p <ref>)"
    fi
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
            write_sync_gate 1 \
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
    # Oldest first, so where two of them touch one file the most recent
    # state ends up on top. The list is NOT cleared here: an entry that
    # pops leaves the stack, so whatever is still resolvable at exit is
    # still unrecovered, and the EXIT handler gates exactly that.
    for (( _si=0; _si<${#data_stash_shas[@]}; _si++ )); do
        _sha="${data_stash_shas[_si]}"
        if ! _sref="$(stash_ref_for "$DATA_DIR" "$_sha")"; then
            log "data submodule: stash ${_sha:0:8} is no longer on the stack — skipping"
            continue
        fi
        if ! git stash pop "$_sref" >>"$LOG_FILE" 2>&1; then
            # `git stash pop` either applied the stash and left the tree
            # conflicted (the entry is preserved by git), or refused to
            # apply it at all. Either way the EXIT handler must not try to
            # re-pop: into a half-merged tree that corrupts it, and into a
            # refusal it just fails again.
            stash_restore_allowed=0
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
                fail "stash pop of $_sref was refused (nothing unmerged) — the stash is preserved; see the gate line for how to recover it"
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
                write_sync_gate 1 \
                    "daily-sync STOPPED: stash pop conflicted on ${unsupported_conflicts[*]} in $DATA_DIR; conflict markers and the stash are preserved. Resolve by hand (git -C $DATA_DIR status), then the next session syncs."
                fail "stash pop conflicted on unsupported paths (${unsupported_conflicts[*]}) — manual resolution required; conflict markers and the stash are preserved"
            fi

            # Build absolute paths for the resolver
            resolver_paths=()
            for f in "${resolvable_conflicts[@]}"; do
                resolver_paths+=("$DATA_DIR/$f")
            done

            "$PA_DIR/venv/bin/python3" "$RESOLVER" --quiet-if-clean \
                "${resolver_paths[@]}" >>"$LOG_FILE" 2>&1 \
                || fail "resolve-merge-conflicts.py failed" 3

            # audit C2: the resolver is supposed to have removed every
            # marker from these files; stage them only once that is true.
            refuse_if_memory_markers "post-resolver stage"
            git add "${resolvable_conflicts[@]}" >>"$LOG_FILE" 2>&1 \
                || fail "git add after resolver failed"
            # audit C1: drop the entry we actually popped. A bare
            # `git stash drop` takes stash@{0}, which after a conflicted
            # pop of a lower entry is a DIFFERENT stash — this run's
            # other one, or a concurrent session's.
            git stash drop "$_sref" >>"$LOG_FILE" 2>&1 || true
            log "conflicts resolved: ${conflicted_files[*]}"
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
    # Shrink check (M3): compare committed-tree line counts (HEAD~1 vs
    # HEAD) — NOT working-tree counts, which would both already reflect
    # the resolver's output and thus always match. If memories.jsonl
    # net-shrank in this commit and the commit message doesn't carry
    # `Rewrite-Class: bulk`, undo the commit and bail before pushing so
    # the state can be reviewed.
    if [[ "$DETECT_JSONL_SHRINK" == "true" ]]; then
        # `git show HEAD~1:path | wc -l` correctly counts trailing-\n-terminated
        # lines from the committed tree. HEAD~1 might not exist on a
        # brand-new branch — guard with rev-parse.
        if git rev-parse --verify --quiet "HEAD~1" >/dev/null 2>&1; then
            # Audit 2026-05-02 (E daily-sync.sh:336-337): previously
            # both `git show` calls discarded stderr and `wc -l`
            # returned 0 on any error, so a path move (e.g. memories
            # renamed) would evade the shrink check entirely. Capture
            # stderr to a temp file and log a WARN if either side
            # errors so the failure is visible.
            git_show_err=$(mktemp)
            if ! lines_before=$(git show "HEAD~1:memories/memories.jsonl" 2>"$git_show_err" | wc -l); then
                lines_before=0
            fi
            if [[ -s "$git_show_err" ]]; then
                log "WARN: git show HEAD~1:memories/memories.jsonl emitted stderr — shrink check may be unreliable. Detail: $(tr '\n' ' ' <"$git_show_err")"
            fi
            : >"$git_show_err"
            if ! lines_after=$(git show "HEAD:memories/memories.jsonl" 2>"$git_show_err" | wc -l); then
                lines_after=0
            fi
            if [[ -s "$git_show_err" ]]; then
                log "WARN: git show HEAD:memories/memories.jsonl emitted stderr — shrink check may be unreliable. Detail: $(tr '\n' ' ' <"$git_show_err")"
            fi
            rm -f "$git_show_err"
            if [[ "$lines_after" -lt "$lines_before" ]]; then
                head_msg="$(git log -1 --format=%B)"
                if ! echo "$head_msg" | grep -q "^Rewrite-Class: bulk"; then
                    shrink_report="$LOG_DIR/daily-sync-SHRINK-$(date +'%Y-%m-%d-%H%M%S').txt"
                    {
                        echo "Detected unexpected shrink in memories.jsonl during daily-sync."
                        echo "Before (HEAD~1): $lines_before lines"
                        echo "After  (HEAD):   $lines_after lines"
                        echo "Delta:           $((lines_after - lines_before))"
                        echo ""
                        echo "Head commit (pre-push):"
                        echo "$head_msg"
                        echo ""
                        echo "git diff --stat HEAD~1..HEAD -- memories/memories.jsonl:"
                        git diff --stat "HEAD~1..HEAD" -- memories/memories.jsonl
                    } > "$shrink_report" 2>&1
                    log "SHRINK DETECTED: $lines_before -> $lines_after lines. Report: $shrink_report"
                    # Undo the commit so origin is not polluted with a
                    # suspect shrink. Files remain on disk for inspection.
                    if ! git reset --soft "HEAD~1" >>"$LOG_FILE" 2>&1; then
                        log "WARNING: failed to reset soft HEAD~1 after shrink detection; manual recovery may be needed"
                    fi
                    fail "data submodule: unexpected shrink detected (see $shrink_report). Push aborted. If intentional, commit with 'Rewrite-Class: bulk' trailer and retry." 4
                fi
            fi
        fi
    fi
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
        if ! _sref="$(stash_ref_for "$PA_DIR" "$_sha")"; then
            log "parent repo: stash ${_sha:0:8} is no longer on the stack — skipping"
            continue
        fi
        if ! git stash pop "$_sref" >>"$LOG_FILE" 2>&1; then
            # Stash applied but conflicted (or refused); the entry is
            # preserved by git, and the EXIT handler must not re-pop.
            stash_restore_allowed=0
            #
            # audit M3: this wedges every later run — the next
            # `git stash push -u -- ':!data'` refuses while a path is
            # unmerged — and, like the data half, nothing but the log said
            # so. Gate it before failing.
            write_sync_gate 1 \
                "daily-sync STOPPED: parent-repo stash pop conflicted in $PA_DIR; conflict markers and the stash are preserved, and every session start will fail here until it is resolved by hand (git -C $PA_DIR status)"
            fail "parent repo: stash pop raised conflicts — manual resolution required"
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
        write_sync_gate 1 \
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

# audit S3/S17: the run finished, so whatever wedged state a previous run
# recorded is over. Clearing here (rather than at the top) means the gate
# keeps nagging for exactly as long as the sync is actually stuck — and not
# when THIS run raised a non-fatal problem of its own (audit M1).
if [[ $DRY_RUN -eq 0 ]] && [[ "$sync_gate_problems" -eq 0 ]]; then
    write_sync_gate 0
fi

log "=== daily-sync complete on $HOST ==="
