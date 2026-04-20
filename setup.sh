#!/usr/bin/env bash
# setup.sh — Bootstrap personal-assistant on a new machine.
#
# Initialises the data submodule, creates command, skill, and agent
# symlinks in ~/.claude/, composes the global CLAUDE.md, and
# optionally sets up the Python virtual environment.
#
# Usage:
#   cd ~/personal-assistant && bash setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PA_DIR="$SCRIPT_DIR"
CLAUDE_DIR="${HOME}/.claude"

echo "=== Personal Assistant Setup ==="
echo "PA_DIR: $PA_DIR"
echo ""

# ------------------------------------------------------------
# Steps 1–5 + compose CLAUDE.md: delegated to sync-symlinks.sh so
# daily-sync.sh can re-run the same idempotent updates without having
# to duplicate logic here.
# ------------------------------------------------------------
bash "$PA_DIR/scripts/sync-symlinks.sh"
echo ""
echo "  NOTE: Read(/home/shawn/**) permission uses an absolute path."
echo "  Update if your home directory differs."

# ------------------------------------------------------------
# Python virtual environment (bootstrap-only — intentionally left out
# of sync-symlinks.sh, which runs daily)
# ------------------------------------------------------------
echo ""
echo "[venv] Python virtual environment..."
if [ -d "$PA_DIR/venv" ]; then
    echo "  venv/ already exists."
else
    echo "  Creating venv..."
    python3 -m venv "$PA_DIR/venv"
    echo "  Installing dependencies..."
    "$PA_DIR/venv/bin/pip" install --quiet anthropic psycopg2-binary pytest
    echo "  Done."
fi

# ------------------------------------------------------------
# Verify
# ------------------------------------------------------------
echo ""
echo "[verify] Checking setup..."
ERRORS=0
for check in "$CLAUDE_DIR/settings.json" "$CLAUDE_DIR/commands" "$CLAUDE_DIR/skills" "$CLAUDE_DIR/agents"; do
    if [ -e "$check" ]; then
        echo "  OK: $check"
    else
        echo "  MISSING: $check"
        ERRORS=$((ERRORS + 1))
    fi
done

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Remaining manual steps:"
echo "  1. Copy your .env file (ANTHROPIC_API_KEY) into $PA_DIR/"
echo "  2. Set up cron job:"
echo "     */5 * * * * $PA_DIR/venv/bin/python3 $PA_DIR/scripts/sync-to-postgres.py >> $PA_DIR/logs/sync-cron.log 2>&1"
echo "  3. Set up PostgreSQL if needed:"
echo "     psql -d claude_memories < $PA_DIR/scripts/schema.sql"
