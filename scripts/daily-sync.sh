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

mkdir -p "$LOG_DIR"

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
                case "$_f" in
                    memories/memories.jsonl|memories/tag-vocabulary.txt)
                        jsonl_conflicts+=("$_f")
                        ;;
                    data)
                        submodule_conflicts+=("$_f")
                        ;;
                    *)
                        unknown_conflicts+=("$_f")
                        ;;
                esac
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
                git add "${jsonl_conflicts[@]}" >>"$LOG_FILE" 2>&1 \
                    || { git rebase --abort >>"$LOG_FILE" 2>&1 || true; fail "$context: git add after resolver failed"; }
            fi
            if [[ ${#submodule_conflicts[@]} -gt 0 ]]; then
                # Our bump-to-new-SHA is authoritative because we just
                # pushed the submodule; origin's pointer is stale.
                for _f in "${submodule_conflicts[@]}"; do
                    git checkout --ours -- "$_f" >>"$LOG_FILE" 2>&1 \
                        || { git rebase --abort >>"$LOG_FILE" 2>&1 || true; fail "$context: checkout --ours failed on $_f"; }
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

exec 9>"$LOCK_FILE"
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
        case "$_f" in
            memories/memories.jsonl|memories/tag-vocabulary.txt) jsonl+=("$_f") ;;
            data) submodule+=("$_f") ;;
            *) unknown+=("$_f") ;;
        esac
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
        git add "${jsonl[@]}" >>"$LOG_FILE" 2>&1 || {
            git rebase --abort >>"$LOG_FILE" 2>&1 || true; return 1; }
    fi
    for _f in "${submodule[@]}"; do
        git checkout --ours -- "$_f" >>"$LOG_FILE" 2>&1 && \
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
    local ref
    while IFS= read -r ref; do
        [[ -n "$ref" ]] && orphans+=("$ref")
    done < <("$PA_DIR/venv/bin/python3" "$SCRIPT_DIR/check-memory-drift.py" \
                 --list-recoverable-stashes 2>>"$LOG_FILE" || true)
    [[ ${#orphans[@]} -eq 0 ]] && return 0

    log "ORPHANED STASH: ${#orphans[@]} stash(es) hold memory records found"
    log "  nowhere else — from a previous run killed before it could pop."
    local i
    # Oldest last in `git stash list`, so walk backwards to replay in order.
    for (( i=${#orphans[@]}-1 ; i>=0 ; i-- )); do
        ref="${orphans[i]}"
        if [[ $DRY_RUN -eq 1 ]]; then
            log "  [dry-run] would pop $ref"
            continue
        fi
        if git stash pop "$ref" >>"$LOG_FILE" 2>&1; then
            log "  recovered $ref"
        else
            # A conflicted pop leaves the tree half-merged and preserves the
            # stash. Do NOT try to tidy up: `git checkout -- .` here would
            # destroy a concurrent session's uncommitted prose edits. Stop
            # and let a human resolve it — the stash is still intact.
            fail "ORPHANED STASH $ref did not apply cleanly; tree is conflicted and the stash is preserved. Resolve by hand: git -C $DATA_DIR stash show -p $ref"
        fi
    done
}

# ---------------------------------------------------------------------------
# Data submodule sync
# ---------------------------------------------------------------------------

cd "$DATA_DIR"

# Crash-safe recovery FIRST — before anything reads or writes the tree.
reconcile_orphaned_stashes

# Stash local changes FIRST (typically memories.jsonl + tag-vocabulary.txt
# from extraction hooks). Stashing works on any ref including detached
# HEAD, and leaves a clean tree so the subsequent checkout/pull cannot
# trip over "local changes would be overwritten".
has_local_changes=0
stash_pending=0
# If any step between `git stash push` and the explicit pop below aborts
# (e.g. pull fails in any non-interactive env without an SSH agent),
# restore the stash so the user's working tree is not silently buried
# in a stash stack that grows unbounded. Cleared once the explicit pop
# completes.
parent_stash_pending=0
restore_stash_on_exit() {
    if [[ "$stash_pending" -eq 1 ]]; then
        log "WARNING: aborting before stash pop — restoring stashed local changes (data submodule)"
        if ! git -C "$DATA_DIR" stash pop >>"$LOG_FILE" 2>&1; then
            log "ERROR: automatic stash restore raised conflicts; stash left in place (see 'git stash list')"
        fi
    fi
    if [[ "$parent_stash_pending" -eq 1 ]]; then
        log "WARNING: aborting before stash pop — restoring stashed local changes (parent repo)"
        if ! git -C "$PA_DIR" stash pop >>"$LOG_FILE" 2>&1; then
            log "ERROR: automatic stash restore raised conflicts; stash left in place (see 'git stash list')"
        fi
    fi
}
trap restore_stash_on_exit EXIT
# Commit the append-only memory files BEFORE considering a stash. They are
# dirty on nearly every run, so this usually empties the tree and no stash
# is taken at all — which removes the failure mode rather than handling it.
# A commit survives a kill; an un-popped stash is invisible until someone
# goes looking. Explicit pathspec, so a concurrent session's edits to any
# other file are untouched.
committed_memory_appends=0
if [[ $DRY_RUN -eq 0 ]]; then
    memory_dirty=()
    for _mf in "${MEMORY_APPEND_FILES[@]}"; do
        if [[ -n "$(git status --porcelain -- "$_mf")" ]]; then
            memory_dirty+=("$_mf")
        fi
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
    has_local_changes=1
    log "data submodule has local changes; stashing for pull"
    if [[ $DRY_RUN -eq 0 ]]; then
        git stash push -u -m "daily-sync on $HOST $(date +'%Y-%m-%d %H:%M')" \
            >>"$LOG_FILE" 2>&1 || fail "stash push failed"
        stash_pending=1
    fi
fi

# Ensure we are on main (the submodule sometimes ends up in detached HEAD
# after certain git operations, e.g. a commit-data.sh run before a pull).
# Safe no-op if already on main; safe on a clean tree after the stash.
current_branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$current_branch" != "main" ]]; then
    log "data submodule on '$current_branch' — switching to main"
    if [[ $DRY_RUN -eq 0 ]]; then
        git checkout main >>"$LOG_FILE" 2>&1 \
            || fail "failed to switch data submodule to main"
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

# Pop stash and resolve conflicts if they arise.
if [[ $has_local_changes -eq 1 ]]; then
    log "data submodule: popping stashed local changes"
    if [[ $DRY_RUN -eq 0 ]]; then
        if ! git stash pop >>"$LOG_FILE" 2>&1; then
            # `git stash pop` applied the stash to the working tree but
            # left it conflicted; the stash entry is preserved by git
            # in this case. Clear the trap flag — re-popping in the
            # restore handler would corrupt the half-merged tree.
            stash_pending=0
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
                fail "stash pop failed but no unmerged paths detected — bailing for manual intervention"
            fi

            # Build absolute paths for the resolver
            resolver_paths=()
            for f in "${conflicted_files[@]}"; do
                resolver_paths+=("$DATA_DIR/$f")
            done

            "$PA_DIR/venv/bin/python3" "$RESOLVER" --quiet-if-clean \
                "${resolver_paths[@]}" >>"$LOG_FILE" 2>&1 \
                || fail "resolve-merge-conflicts.py failed" 3

            git add "${conflicted_files[@]}" >>"$LOG_FILE" 2>&1 \
                || fail "git add after resolver failed"
            git stash drop >>"$LOG_FILE" 2>&1 || true
            log "conflicts resolved: ${conflicted_files[*]}"
        fi
        # Pop succeeded (or resolver applied + stash dropped); the trap
        # no longer needs to restore anything.
        stash_pending=0
    fi
fi

# Commit + push if there's anything to commit.
if [[ $DRY_RUN -eq 0 ]] && [[ -n "$(git status --porcelain)" ]]; then
    log "data submodule: committing merged local changes"
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
parent_has_local_changes=0
if [[ -n "$(git status --porcelain -- ':!data')" ]]; then
    parent_has_local_changes=1
    log "parent repo has local changes; stashing for pull"
    if [[ $DRY_RUN -eq 0 ]]; then
        git stash push -u -m "daily-sync parent on $HOST $(date +'%Y-%m-%d %H:%M')" \
            -- ':!data' >>"$LOG_FILE" 2>&1 || fail "parent stash push failed"
        parent_stash_pending=1
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
if [[ $parent_has_local_changes -eq 1 ]] && [[ $DRY_RUN -eq 0 ]]; then
    log "parent repo: popping stashed local changes"
    if ! git stash pop >>"$LOG_FILE" 2>&1; then
        # Stash applied but conflicted; entry is preserved by git.
        # Clear the flag so the EXIT trap does not re-pop and corrupt
        # the half-merged tree.
        parent_stash_pending=0
        fail "parent repo: stash pop raised conflicts — manual resolution required"
    fi
    parent_stash_pending=0
fi

# Bump submodule pointer if the data submodule moved.
if [[ $DRY_RUN -eq 0 ]] && ! git diff --quiet data; then
    log "parent repo: data submodule pointer moved — committing bump"
    git add data >>"$LOG_FILE" 2>&1
    git commit -m "chore(auto-sync): bump data pointer from $HOST $(date +'%Y-%m-%d')" \
        >>"$LOG_FILE" 2>&1 || fail "parent commit failed"
    push_with_retry "parent repo"
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
        GATE_FILE="$HOME/.cache/cc-archives-gate"
        "$HOME/personal-assistant/venv/bin/python3" - "$CC_ARCHIVES_LOCAL" "$GATE_FILE" <<'PYEOF' >>"$LOG_FILE" 2>&1 || log "cc-archives gate: check failed (see log)"
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
    MEMORY_DRIFT_GATE="$HOME/.cache/memory-drift-gate"
    if "$PA_DIR/venv/bin/python3" "$SCRIPT_DIR/check-memory-drift.py" \
            --quiet-if-clean >>"$LOG_FILE" 2>&1; then
        log "memory drift check: clean"
        printf '0\n' > "$MEMORY_DRIFT_GATE"
    else
        rc=$?
        if [[ $rc -eq 2 ]]; then
            log "memory drift check: COULD NOT RUN (rc=2; see memory-drift.log)"
            # Unknown is not clean: surface it rather than staying silent.
            printf '1\nmemory drift check COULD NOT RUN (PostgreSQL down?) — state unknown; see logs/memory-drift.log\n' \
                > "$MEMORY_DRIFT_GATE"
        else
            log "memory drift check: *** DRIFT DETECTED *** — canonical memory"
            log "  records survive in only one store. See logs/memory-drift.log."
            log "  Recover: venv/bin/python3 scripts/check-memory-drift.py --recover"
            log "  DO NOT run rebuild-postgres.py until this is clean."
            printf '1\nmemory records survive in only ONE store — run scripts/check-memory-drift.py (then --recover); do NOT rebuild-postgres until clean\n' \
                > "$MEMORY_DRIFT_GATE"
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

log "=== daily-sync complete on $HOST ==="
