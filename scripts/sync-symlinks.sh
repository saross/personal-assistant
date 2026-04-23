#!/usr/bin/env bash
# sync-symlinks.sh — Refresh ~/.claude/ symlinks + global CLAUDE.md.
#
# The cheap, idempotent subset of setup.sh: ensures that every command,
# skill, and agent in this repo is linked into the locations Claude Code
# reads from, and that settings.json + the composed global CLAUDE.md are
# up to date. Safe to run on every sync — it performs filesystem checks
# only and only updates links when they are missing or wrong.
#
# Designed to be called from both:
#   - setup.sh (during new-machine bootstrap)
#   - daily-sync.sh (end of each daily cron run, to heal drift)
#
# Does NOT create the Python venv or install dependencies — those are
# bootstrap concerns, not daily-sync concerns. Run setup.sh explicitly
# for a fresh machine.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PA_DIR="$(dirname "$SCRIPT_DIR")"
CLAUDE_DIR="${HOME}/.claude"

# Optional: --quiet suppresses "already correct" lines so cron logs stay
# slim. Changes and errors are always printed.
QUIET=0
if [[ "${1:-}" == "--quiet" ]]; then
    QUIET=1
fi

say() {
    # Print unconditionally (used for headings, changes, errors).
    echo "$@"
}

say_verbose() {
    # Print only when not --quiet.
    if [[ $QUIET -eq 0 ]]; then
        echo "$@"
    fi
}

# ---------------------------------------------------------------------------
# Helper: ensure a symlink at $target points to $src. Creates/updates as
# needed. If a real file (not a symlink) already exists at $target, leaves
# it alone and reports a warning (user intervention required).
# ---------------------------------------------------------------------------

# Helper: prune any symlink under $dir that points into $src_dir but whose
# target no longer exists.  Catches renames and deletions so a removed
# source file doesn't leave an orphan symlink behind (e.g. the /review ->
# /weekly-review rename on 2026-04-23).  Leaves non-symlinks and symlinks
# pointing outside $src_dir alone.
prune_stale_symlinks() {
    local dir="$1"
    local src_dir="$2"
    local label="$3"
    [ -d "$dir" ] || return 0
    local removed=0
    local link
    for link in "$dir"/*; do
        [ -L "$link" ] || continue
        local target
        target="$(readlink "$link")"
        case "$target" in
            "$src_dir"/*)
                if [ ! -e "$target" ]; then
                    rm "$link"
                    say "  $(basename "$link") — pruned stale $label symlink"
                    removed=$((removed + 1))
                fi
                ;;
        esac
    done
    return 0
}

ensure_symlink() {
    local src="$1"
    local target="$2"
    local label="$3"

    if [ -L "$target" ]; then
        local current
        current="$(readlink "$target")"
        if [ "$current" != "$src" ]; then
            ln -sf "$src" "$target"
            say "  $label — updated symlink"
        else
            say_verbose "  $label — already correct"
        fi
    elif [ -e "$target" ]; then
        say "  $label — WARNING: file exists (not a symlink), skipping"
    else
        ln -s "$src" "$target"
        say "  $label — linked"
    fi
}

# ---------------------------------------------------------------------------
# Step 1: Submodule init/update (idempotent; no-op once up to date)
# ---------------------------------------------------------------------------

say "[1/6] Ensuring data submodule is initialised..."
cd "$PA_DIR"
git submodule update --init --recursive --quiet
say_verbose "  Submodule ready."

# ---------------------------------------------------------------------------
# Step 2: settings.json symlink
# ---------------------------------------------------------------------------

say "[2/6] Linking settings.json..."
ensure_symlink "$PA_DIR/settings.json" "$CLAUDE_DIR/settings.json" "settings.json"

# ---------------------------------------------------------------------------
# Step 3: Command symlinks
# ---------------------------------------------------------------------------

say "[3/6] Linking commands..."
mkdir -p "$CLAUDE_DIR/commands"
prune_stale_symlinks "$CLAUDE_DIR/commands" "$PA_DIR/commands" "command"
for cmd in "$PA_DIR"/commands/*.md; do
    [ -f "$cmd" ] || continue
    ensure_symlink "$cmd" "$CLAUDE_DIR/commands/$(basename "$cmd")" "$(basename "$cmd")"
done

# ---------------------------------------------------------------------------
# Step 4: Skill symlinks
# ---------------------------------------------------------------------------

say "[4/6] Linking skills..."
mkdir -p "$CLAUDE_DIR/skills"
prune_stale_symlinks "$CLAUDE_DIR/skills" "$PA_DIR/skills" "skill"
for skill_dir in "$PA_DIR"/skills/*/; do
    [ -d "$skill_dir" ] || continue
    skill_name="$(basename "$skill_dir")"
    # Strip trailing slash for the symlink target (ln -s prefers no slash)
    ensure_symlink "${skill_dir%/}" "$CLAUDE_DIR/skills/$skill_name" "$skill_name"
done

# ---------------------------------------------------------------------------
# Step 5: Agent symlinks
# ---------------------------------------------------------------------------

say "[5/6] Linking agents..."
mkdir -p "$CLAUDE_DIR/agents"
prune_stale_symlinks "$CLAUDE_DIR/agents" "$PA_DIR/agents" "agent"
for agent_file in "$PA_DIR"/agents/*.md; do
    [ -f "$agent_file" ] || continue
    ensure_symlink "$agent_file" "$CLAUDE_DIR/agents/$(basename "$agent_file")" "$(basename "$agent_file")"
done

# ---------------------------------------------------------------------------
# Step 6: Compose global CLAUDE.md
# ---------------------------------------------------------------------------

say "[6/6] Composing global CLAUDE.md..."
bash "$PA_DIR/scripts/compose-global-claude-md.sh" >/dev/null
say_verbose "  Composed."

say "sync-symlinks complete."
