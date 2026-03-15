#!/usr/bin/env bash
# setup.sh — Bootstrap personal-assistant on a new machine.
#
# Initialises the data submodule, creates command and skill
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
# Step 1: Initialise and update submodule
# ------------------------------------------------------------
echo "[1/7] Initialising data submodule..."
cd "$PA_DIR"
git submodule update --init --recursive
echo "  Done."

# ------------------------------------------------------------
# Step 2: Symlink settings.json
# ------------------------------------------------------------
echo "[2/7] Symlinking settings.json..."
SETTINGS_SRC="$PA_DIR/settings.json"
SETTINGS_DST="$CLAUDE_DIR/settings.json"
if [ -L "$SETTINGS_DST" ]; then
    current="$(readlink "$SETTINGS_DST")"
    if [ "$current" != "$SETTINGS_SRC" ]; then
        ln -sf "$SETTINGS_SRC" "$SETTINGS_DST"
        echo "  settings.json — updated symlink"
    else
        echo "  settings.json — already correct"
    fi
elif [ -e "$SETTINGS_DST" ]; then
    echo "  settings.json — file exists (not a symlink)"
    echo "  Back up and remove it, then re-run setup to create symlink:"
    echo "    cp $SETTINGS_DST ${SETTINGS_DST}.bak && rm $SETTINGS_DST"
else
    ln -s "$SETTINGS_SRC" "$SETTINGS_DST"
    echo "  settings.json — linked"
fi
echo "  NOTE: Read(/home/shawn/**) permission uses an absolute path."
echo "  Update if your home directory differs."

# ------------------------------------------------------------
# Step 3: Create command symlinks
# ------------------------------------------------------------
echo "[3/7] Creating command symlinks..."
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
# Step 4: Create skill symlinks
# ------------------------------------------------------------
echo "[4/7] Creating skill symlinks..."
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
# Step 5: Python virtual environment
# ------------------------------------------------------------
echo "[5/7] Python virtual environment..."
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
# Step 6: Compose global CLAUDE.md
# ------------------------------------------------------------
echo "[6/7] Composing global CLAUDE.md..."
bash "$PA_DIR/scripts/compose-global-claude-md.sh"

# ------------------------------------------------------------
# Step 7: Verify symlinks
# ------------------------------------------------------------
echo "[7/7] Verifying setup..."
ERRORS=0
for check in "$SETTINGS_DST" "$CLAUDE_DIR/commands" "$CLAUDE_DIR/skills"; do
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
