#!/usr/bin/env bash
# compose-global-claude-md.sh — Compose ~/.claude/CLAUDE.md from
# shared (public) and local (private) sections.
#
# The shared section lives in the public repo and contains coding
# standards, conventions, and methodology — safe to show others.
# The local section lives in pa-data and contains network topology,
# server specs, and operational guardrails — private.
#
# Usage:
#   bash scripts/compose-global-claude-md.sh
#   bash scripts/compose-global-claude-md.sh --dry-run

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PA_DIR="$(dirname "$SCRIPT_DIR")"

SHARED="$PA_DIR/global-claude-md/shared.md"
LOCAL="$PA_DIR/data/global-claude-md/local.md"
TARGET="${HOME}/.claude/CLAUDE.md"

DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
fi

# Verify source files exist
if [[ ! -f "$SHARED" ]]; then
    echo "ERROR: Shared section not found: $SHARED" >&2
    exit 1
fi

if [[ ! -f "$LOCAL" ]]; then
    echo "ERROR: Local section not found: $LOCAL" >&2
    echo "  (Is the data submodule initialised? Run: git submodule update --init)" >&2
    exit 1
fi

# Compose the file
composed="$(cat "$SHARED")

$( cat "$LOCAL")"

if $DRY_RUN; then
    echo "=== Would write to: $TARGET ==="
    echo "$composed" | head -5
    echo "..."
    echo "$composed" | tail -5
    echo ""
    echo "Total lines: $(echo "$composed" | wc -l)"
else
    mkdir -p "$(dirname "$TARGET")"
    echo "$composed" > "$TARGET"
    echo "Composed ~/.claude/CLAUDE.md from:"
    echo "  shared: $SHARED ($(wc -l < "$SHARED") lines)"
    echo "  local:  $LOCAL ($(wc -l < "$LOCAL") lines)"
    echo "  output: $TARGET ($(wc -l < "$TARGET") lines)"
fi
