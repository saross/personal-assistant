#!/usr/bin/env bash
# daily-sync.sh — Daily multi-machine sync for personal-assistant + pa-data.
#
# Handles the common two-way sync pattern:
#   1. Each machine's extraction hook appends memories locally during the day.
#   2. At sync time, commit local captures, pull remote captures from the
#      other machine(s), resolve append-only conflicts automatically, push.
#
# Safe to run at any time. Designed for cron but also fine interactively.
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
    local key="$1" default="$2" value jq_stderr
    if ! command -v jq >/dev/null 2>&1 || [ ! -f "$CONFIG_FILE" ]; then
        printf '%s' "$default"
        return
    fi
    jq_stderr=$(mktemp)
    if value=$(jq -r "(.${key} // ${default})" "$CONFIG_FILE" 2>"$jq_stderr"); then
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
# Data submodule sync
# ---------------------------------------------------------------------------

cd "$DATA_DIR"

# Stash local changes FIRST (typically memories.jsonl + tag-vocabulary.txt
# from extraction hooks). Stashing works on any ref including detached
# HEAD, and leaves a clean tree so the subsequent checkout/pull cannot
# trip over "local changes would be overwritten".
has_local_changes=0
stash_pending=0
# If any step between `git stash push` and the explicit pop below aborts
# (e.g. pull fails because the cron env has no SSH agent), restore the
# stash so the user's working tree is not silently buried in a stash
# stack that grows unbounded. Cleared once the explicit pop completes.
restore_stash_on_exit() {
    if [[ "$stash_pending" -eq 1 ]]; then
        log "WARNING: aborting before stash pop — restoring stashed local changes"
        if ! git -C "$DATA_DIR" stash pop >>"$LOG_FILE" 2>&1; then
            log "ERROR: automatic stash restore raised conflicts; stash left in place (see 'git stash list')"
        fi
    fi
}
trap restore_stash_on_exit EXIT
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

# Pull remote. After stashing, this should fast-forward.
log "data submodule: pulling origin/main"
if [[ $DRY_RUN -eq 0 ]]; then
    git pull --ff-only origin main >>"$LOG_FILE" 2>&1 \
        || fail "data submodule pull failed (not fast-forwardable)"
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
            lines_before=$(git show "HEAD~1:memories/memories.jsonl" 2>/dev/null | wc -l)
            lines_after=$(git show "HEAD:memories/memories.jsonl" 2>/dev/null | wc -l)
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

log "parent repo: pulling origin/main"
if [[ $DRY_RUN -eq 0 ]]; then
    git pull --ff-only origin main >>"$LOG_FILE" 2>&1 \
        || fail "parent pull failed (not fast-forwardable — manual merge needed)"
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
# Symlink sync (heals skill/command/agent drift after new files land)
# ---------------------------------------------------------------------------

if [[ $DRY_RUN -eq 0 ]]; then
    log "refreshing ~/.claude/ symlinks + global CLAUDE.md"
    bash "$SCRIPT_DIR/sync-symlinks.sh" --quiet >>"$LOG_FILE" 2>&1 \
        || fail "sync-symlinks.sh failed (symlink drift NOT healed this run)"
fi

log "=== daily-sync complete on $HOST ==="
