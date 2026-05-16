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
# Idempotent: also verifies declared Python dependencies
# (requirements.txt) are present and installs any missing ones, so that
# session-archive hooks and other machine-spanning automation can't
# silently fail when a venv drifts. Does NOT create the venv itself —
# that's still bootstrap-only (run setup.sh on a fresh machine).

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
    if [ "$removed" -gt 0 ]; then
        say "  pruned $removed stale $label symlink(s)"
    fi
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
        elif [ ! -e "$target" ]; then
            # Audit 2026-05-02 E-Medium: target string matches but the
            # source no longer exists. Previous code reported "already
            # correct" and left the dangling link in place. Warn-only
            # (the link itself is unchanged — re-creating it would be
            # a no-op since the source is still missing) so the user
            # notices and can investigate. The pruning helper handles
            # the deletion case for in-tree symlinks; this catch covers
            # the gap for everything else.
            say "  $label — WARNING: dangling symlink (source missing: $src)"
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

say "[1/7] Ensuring data submodule is initialised..."
cd "$PA_DIR"
git submodule update --init --recursive --quiet
say_verbose "  Submodule ready."

# ---------------------------------------------------------------------------
# Step 2: settings.json symlink
# ---------------------------------------------------------------------------

say "[2/7] Linking settings.json..."
ensure_symlink "$PA_DIR/settings.json" "$CLAUDE_DIR/settings.json" "settings.json"

# ---------------------------------------------------------------------------
# Step 3: Command symlinks
# ---------------------------------------------------------------------------

say "[3/7] Linking commands..."
mkdir -p "$CLAUDE_DIR/commands"
prune_stale_symlinks "$CLAUDE_DIR/commands" "$PA_DIR/commands" "command"
for cmd in "$PA_DIR"/commands/*.md; do
    [ -f "$cmd" ] || continue
    ensure_symlink "$cmd" "$CLAUDE_DIR/commands/$(basename "$cmd")" "$(basename "$cmd")"
done

# ---------------------------------------------------------------------------
# Step 4: Skill symlinks
# ---------------------------------------------------------------------------

say "[4/7] Linking skills..."
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

say "[5/7] Linking agents..."
mkdir -p "$CLAUDE_DIR/agents"
prune_stale_symlinks "$CLAUDE_DIR/agents" "$PA_DIR/agents" "agent"
for agent_file in "$PA_DIR"/agents/*.md; do
    [ -f "$agent_file" ] || continue
    ensure_symlink "$agent_file" "$CLAUDE_DIR/agents/$(basename "$agent_file")" "$(basename "$agent_file")"
done

# ---------------------------------------------------------------------------
# Step 6: Compose global CLAUDE.md
# ---------------------------------------------------------------------------

say "[6/7] Composing global CLAUDE.md..."
bash "$PA_DIR/scripts/compose-global-claude-md.sh" >/dev/null
say_verbose "  Composed."

# ---------------------------------------------------------------------------
# Step 7: Verify Python dependencies (cc-session-toolkit and friends)
#
# Why this lives in sync-symlinks rather than setup.sh-only:
# session-archive hooks (`cc_session_toolkit.cli archive` on
# SessionEnd/PreCompact) silently fail when the package is missing from
# the venv. Drift between machines — or a reformatted box — should not
# require the user to remember a manual pip step. The check is cheap
# in the common case (a handful of import probes); install only runs
# when something is actually missing.
# ---------------------------------------------------------------------------

say "[7/7] Verifying Python dependencies..."
if [ ! -d "$PA_DIR/venv" ]; then
    say "  WARNING: venv/ not present — run setup.sh to bootstrap."
elif [ ! -f "$PA_DIR/requirements.txt" ]; then
    say "  WARNING: requirements.txt missing — cannot verify deps."
else
    # Probe each declared top-level package. Import name differs from
    # pip name in some cases (psycopg2-binary → psycopg2,
    # cc-session-toolkit → cc_session_toolkit) so the list is hand-
    # maintained alongside requirements.txt.
    if "$PA_DIR/venv/bin/python3" -c "
import importlib.util, sys
required = ['anthropic', 'psycopg2', 'pytest', 'mcp', 'pyzotero', 'cc_session_toolkit']
missing = [m for m in required if importlib.util.find_spec(m) is None]
sys.exit(1 if missing else 0)
" 2>/dev/null; then
        say_verbose "  All declared dependencies present."
    else
        say "  Missing one or more declared dependencies — installing from requirements.txt..."
        "$PA_DIR/venv/bin/pip" install --quiet --upgrade -r "$PA_DIR/requirements.txt" \
            && say "  Dependencies installed/updated." \
            || say "  WARNING: pip install failed; archive hooks may continue to silently fail."
    fi
fi

say "sync-symlinks complete."
