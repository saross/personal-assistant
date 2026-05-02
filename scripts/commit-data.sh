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

git add -A
echo "=== Data changes ==="
git status --short

if git diff --cached --quiet; then
    echo "No data changes to commit."
    exit 0
fi

git commit -m "$MSG

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
git push origin main

cd "$PA_DIR"
git add data
git commit -m "chore: update data submodule reference

$MSG

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"

echo ""
echo "Done. Data committed and submodule reference updated."
echo "Run 'git push origin main' to push the parent repo."
