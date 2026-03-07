#!/usr/bin/env bash
# commit-data.sh — Commit and push data submodule changes, then
# update the parent repo's submodule reference.
#
# Usage:
#   bash scripts/commit-data.sh "chore: sync memories from session"
#   bash scripts/commit-data.sh  # uses default message

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PA_DIR="$(dirname "$SCRIPT_DIR")"
MSG="${1:-chore: sync data}"

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
