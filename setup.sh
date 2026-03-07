#!/usr/bin/env bash
# setup.sh — Bootstrap personal-assistant on a new machine.
#
# Initialises the data submodule, creates command and skill
# symlinks in ~/.claude/, and optionally sets up the Python
# virtual environment.
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
# Step 1: Initialise and update submodule
# ------------------------------------------------------------
echo "[1/4] Initialising data submodule..."
cd "$PA_DIR"
git submodule update --init --recursive
echo "  Done."

# ------------------------------------------------------------
# Step 2: Create command symlinks in ~/.claude/commands/
# ------------------------------------------------------------
echo "[2/4] Creating command symlinks..."
mkdir -p "$CLAUDE_DIR/commands"

for cmd in "$PA_DIR"/commands/*.md; do
    cmd_name="$(basename "$cmd")"
    target="$CLAUDE_DIR/commands/$cmd_name"
    if [ -L "$target" ]; then
        # Update existing symlink to point to new location
        current="$(readlink "$target")"
        if [ "$current" != "$cmd" ]; then
            ln -sf "$cmd" "$target"
            echo "  $cmd_name — updated symlink"
        else
            echo "  $cmd_name — already correct"
        fi
    elif [ -e "$target" ]; then
        echo "  $cmd_name — file exists (not a symlink), skipping"
    else
        ln -s "$cmd" "$target"
        echo "  $cmd_name — linked"
    fi
done

# ------------------------------------------------------------
# Step 3: Create skill symlinks in ~/.claude/skills/
# ------------------------------------------------------------
echo "[3/4] Creating skill symlinks..."
mkdir -p "$CLAUDE_DIR/skills"

for skill_dir in "$PA_DIR"/skills/*/; do
    skill_name="$(basename "$skill_dir")"
    target="$CLAUDE_DIR/skills/$skill_name"
    if [ -L "$target" ]; then
        current="$(readlink "$target")"
        if [ "$current" != "${skill_dir%/}" ]; then
            ln -sf "${skill_dir%/}" "$target"
            echo "  $skill_name — updated symlink"
        else
            echo "  $skill_name — already correct"
        fi
    elif [ -e "$target" ]; then
        echo "  $skill_name — exists (not a symlink), skipping"
    else
        ln -s "${skill_dir%/}" "$target"
        echo "  $skill_name — linked"
    fi
done

# ------------------------------------------------------------
# Step 4: Python virtual environment (optional)
# ------------------------------------------------------------
echo "[4/4] Python virtual environment..."
if [ -d "$PA_DIR/venv" ]; then
    echo "  venv/ already exists."
else
    echo "  Creating venv..."
    python3 -m venv "$PA_DIR/venv"
    echo "  Installing dependencies..."
    "$PA_DIR/venv/bin/pip" install --quiet anthropic psycopg2-binary pytest
    echo "  Done."
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Remaining manual steps:"
echo "  1. Copy your .env file (ANTHROPIC_API_KEY) into $PA_DIR/"
echo "  2. Verify hooks in ~/.claude/settings.json point to $PA_DIR/hooks/"
echo "  3. Set up cron job:"
echo "     */5 * * * * $PA_DIR/venv/bin/python3 $PA_DIR/scripts/sync-to-postgres.py >> $PA_DIR/logs/sync-cron.log 2>&1"
echo "  4. Set up PostgreSQL if needed:"
echo "     psql -d claude_memories < $PA_DIR/scripts/schema.sql"
