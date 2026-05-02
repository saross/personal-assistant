#!/usr/bin/env bash
# commit-data.sh — Commit and push data submodule changes, then
# update the parent repo's submodule reference.
#
# Usage:
#   bash scripts/commit-data.sh "chore: sync memories from session"
#   bash scripts/commit-data.sh  # uses default message
#
# Locking: takes the same logs/daily-sync.lock used by daily-sync.sh
# so the two scripts cannot interleave on the data submodule's git
# index. Audit 2026-05-02 (E-Critical lock-gap): without this lock,
# a commit-data.sh run alongside an in-flight daily-sync rebase or
# stash could corrupt the merge state or lose the resolver output.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PA_DIR="$(dirname "$SCRIPT_DIR")"
MSG="${1:-chore: sync data}"

# Acquire the daily-sync lock before touching the data submodule.
# Non-blocking: if daily-sync is already running, exit cleanly rather
# than queue indefinitely from an interactive shell.
LOG_DIR="$PA_DIR/logs"
LOCK_FILE="$LOG_DIR/daily-sync.lock"
mkdir -p "$LOG_DIR"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "Another daily-sync or commit-data is running (lock held). Exiting." >&2
    exit 1
fi

cd "$PA_DIR/data"

# Refuse to run unless the data submodule is on `main`. The previous
# implementation hardcoded `git push origin main`, which on a detached
# HEAD or feature branch silently pushed the *unchanged* local main
# (orphaning the new commit) — see Audit 2026-05-02 E-Critical
# (commit-data.sh:29 push-to-wrong-branch). `daily-sync.sh:257-264`
# already enforces a similar branch check; mirror that defence here.
DATA_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$DATA_BRANCH" != "main" ]]; then
    echo "ERROR: data submodule is on branch '$DATA_BRANCH', not 'main'." >&2
    echo "  Refusing to commit + push. Switch to main and try again, or" >&2
    echo "  push manually if you intend to publish a topic branch." >&2
    exit 1
fi

git add -A
echo "=== Data changes ==="
git status --short

if git diff --cached --quiet; then
    echo "No data changes to commit."
    exit 0
fi

git commit -m "$MSG

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
# Use HEAD:main rather than a bare `main` ref so the push fails loudly
# if the local branch ever diverges from the expected name (defence in
# depth — the explicit branch check above should already have caught it).
git push origin HEAD:main

cd "$PA_DIR"

# Mirror the branch check on the parent repo: pushing a submodule pointer
# bump from a non-main branch is the same silent-data-loss shape.
PARENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$PARENT_BRANCH" != "main" ]]; then
    echo "WARNING: parent repo is on branch '$PARENT_BRANCH', not 'main'." >&2
    echo "  Submodule reference will be committed locally but not pushed." >&2
    echo "  Push manually once you have decided where the bump should land." >&2
    exit 0
fi

git add data
git commit -m "chore: update data submodule reference

$MSG

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"

echo ""
echo "Done. Data committed and submodule reference updated."
echo "Run 'git push origin main' to push the parent repo."
