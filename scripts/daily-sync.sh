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
if [[ -n "$(git status --porcelain)" ]]; then
    has_local_changes=1
    log "data submodule has local changes; stashing for pull"
    if [[ $DRY_RUN -eq 0 ]]; then
        git stash push -u -m "daily-sync on $HOST $(date +'%Y-%m-%d %H:%M')" \
            >>"$LOG_FILE" 2>&1 || fail "stash push failed"
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
    fi
fi

# Commit + push if there's anything to commit.
if [[ $DRY_RUN -eq 0 ]] && [[ -n "$(git status --porcelain)" ]]; then
    log "data submodule: committing merged local changes"
    git add -A >>"$LOG_FILE" 2>&1
    git commit -m "chore(auto-sync): daily sync from $HOST $(date +'%Y-%m-%d')" \
        >>"$LOG_FILE" 2>&1 || fail "data commit failed"
    git push origin main >>"$LOG_FILE" 2>&1 \
        || fail "data push failed (diverged remote — needs manual resolution)"
    log "data submodule: pushed to origin"
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
    git push origin main >>"$LOG_FILE" 2>&1 \
        || fail "parent push failed (diverged remote — needs manual resolution)"
    log "parent repo: pushed submodule bump"
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
