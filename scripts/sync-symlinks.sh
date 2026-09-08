#!/usr/bin/env bash
# sync-symlinks.sh — Refresh ~/.claude/ symlinks + global CLAUDE.md.
#
# The cheap, idempotent subset of setup.sh: ensures that every command,
# skill, agent, and output style in this repo is linked into the
# locations Claude Code reads from, and that settings.json + the
# composed global CLAUDE.md are up to date. Safe to run on every sync — it performs filesystem checks
# only and only updates links when they are missing or wrong.
#
# Designed to be called from both:
#   - setup.sh (during new-machine bootstrap)
#   - daily-sync.sh (end of each daily cron run, to heal drift)
#
# Idempotent: also verifies declared Python dependencies
# (requirements.txt) are present and installs any missing ones — only the
# missing ones, and never with --upgrade — so that session-archive hooks
# and other machine-spanning automation can't silently fail when a venv
# drifts without an unattended run also re-resolving every other package.
# Does NOT create the venv itself — that's still bootstrap-only (run
# setup.sh on a fresh machine).
#
# Usage:
#   bash scripts/sync-symlinks.sh [--quiet] [--dry-run]
#
# --dry-run prints every filesystem action (symlink, prune, mkdir,
# submodule init, pip install) and executes none. Any other argument is a
# usage error (exit 2).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PA_DIR="$(dirname "$SCRIPT_DIR")"
CLAUDE_DIR="${HOME}/.claude"

# C4 (2026-05-19): track dependency-install failures so we exit non-zero
# at end of script. Previously a failed pip install was logged but the
# script still exited 0, hiding the failure from daily-sync.sh / cron.
DEPS_FAILED=0

# Optional flags, accepted in any order:
#   --quiet     suppress "already correct" lines so cron logs stay slim.
#               Changes and errors are always printed.
#   --dry-run   print every action this run would take and execute none.
#               Added by audit round 4d (E5): the script's riskiest steps
#               (pruning symlinks, installing packages, initialising a
#               submodule) had no way to be inspected before they ran.
#   --allow-worktree
#               proceed even though this checkout is not the live
#               $HOME/personal-assistant. Round 4d-2: without the guard
#               below, a worktree run repointed every live ~/.claude
#               symlink at the worktree in steps 2-6 and then died in
#               step 7 when the composer refused, leaving the operator's
#               configuration half-migrated to a branch.
QUIET=0
DRY_RUN=0
ALLOW_WORKTREE=0
USAGE="Usage: sync-symlinks.sh [--quiet] [--dry-run] [--allow-worktree]"
for arg in "$@"; do
    case "$arg" in
        --quiet)          QUIET=1 ;;
        --dry-run)        DRY_RUN=1 ;;
        --allow-worktree) ALLOW_WORKTREE=1 ;;
        -h|--help)
            echo "$USAGE"
            exit 0
            ;;
        *)
            echo "ERROR: unknown argument: $arg" >&2
            echo "$USAGE" >&2
            exit 2
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Live-checkout guard (round 4d-2)
#
# Every step below writes into the LIVE $HOME/.claude: symlinks in steps
# 2-6, then the global CLAUDE.md in step 7. Run from a git worktree, the
# link steps silently repointed the operator's whole configuration at that
# worktree and step 7 then exited non-zero (the composer has its own
# guard), leaving the machine half-migrated to a branch with no message
# saying so. Refuse before step 1 instead, so nothing is half-done.
#
# --dry-run is exempt: inspecting what a worktree run WOULD do is exactly
# what the flag is for, and it changes nothing.
# ---------------------------------------------------------------------------
LIVE_ROOT="${HOME}/personal-assistant"
if [[ $ALLOW_WORKTREE -eq 0 && $DRY_RUN -eq 0 && -d "$LIVE_ROOT" ]]; then
    live_real="$(cd "$LIVE_ROOT" && pwd -P)"
    pa_real="$(cd "$PA_DIR" && pwd -P)"
    if [[ "$live_real" != "$pa_real" ]]; then
        echo "ERROR: refusing to relink $CLAUDE_DIR from $pa_real" >&2
        echo "  (the live checkout is $live_real). A worktree run would" >&2
        echo "  repoint every ~/.claude symlink at this branch. Re-run" >&2
        echo "  from the live checkout, or pass --dry-run to inspect," >&2
        echo "  or --allow-worktree if you really mean it." >&2
        exit 2
    fi
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

run_action() {
    # Execute "$@" — or, under --dry-run, print it and change nothing.
    # Every filesystem mutation in this script goes through here so that
    # --dry-run is a property of one function rather than a promise made
    # separately at each call site.
    if [[ $DRY_RUN -eq 1 ]]; then
        say "  would run: $*"
        return 0
    fi
    "$@"
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
                # Only a DANGLING link into $src_dir is pruned, and only
                # with plain `rm` — never `rm -r`. A real directory, a
                # real file, and a link pointing anywhere else all fall
                # through untouched (audit round 4d, ET5).
                if [ ! -e "$target" ]; then
                    run_action rm "$link"
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
            # Audit 2026-09-08 S11: -n (--no-dereference) is mandatory here.
            # When $target is a symlink to a DIRECTORY (every skill link —
            # step 4), plain `ln -sf` follows the link and creates the new
            # symlink INSIDE the old target directory instead of retargeting
            # the link. The retarget then silently fails, the script logs
            # "updated symlink" on every run, and a stray symlink is
            # deposited into the old source directory.
            run_action ln -sfn "$src" "$target"
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
        run_action ln -s "$src" "$target"
        say "  $label — linked"
    fi
}

# ---------------------------------------------------------------------------
# Step 1: Submodule init/update (idempotent; no-op once up to date)
# ---------------------------------------------------------------------------

say "[1/8] Ensuring data submodule is initialised..."
cd "$PA_DIR"
# Audit round 4d (E10): run this ONLY when data/ is uninitialised. On an
# already-initialised submodule `git submodule update` checks out the
# gitlink SHA recorded in the superproject, which detaches data/ from its
# branch; commits a concurrent session has made inside data/ but not yet
# pointed at from the superproject become unreferenced. This step exists
# solely to populate an empty data/, so an uninitialised data/ is the only
# case in which it should run.
#
# Round 4d-2: ask git, not the directory listing. "Is data/ non-empty?"
# answered yes for a fresh clone whose data/ happened to hold one stray
# file, and the submodule was then never initialised — the opposite
# failure. `git submodule status` prefixes an UNINITIALISED submodule with
# "-"; anything else (" ", "+", "U") means it has a checkout. A worktree
# whose data/ holds empty stub directories is still uninitialised by that
# test, so it still skips.
submodule_state="$(git submodule status -- data 2>/dev/null || true)"
if [ -z "$submodule_state" ]; then
    say_verbose "  No data submodule declared — nothing to initialise."
elif [ "${submodule_state#-}" != "$submodule_state" ]; then
    run_action git submodule update --init --recursive --quiet
    say_verbose "  Submodule ready."
else
    say_verbose "  Submodule already initialised — leaving it alone."
fi

# ---------------------------------------------------------------------------
# Step 2: settings.json symlink
# ---------------------------------------------------------------------------

say "[2/8] Linking settings.json..."
# Audit round 4d (NEW): every later step mkdir -p's its own subdirectory,
# but nothing created $CLAUDE_DIR itself, so on a machine without a
# ~/.claude (a genuinely fresh bootstrap through setup.sh) `ln -s` failed
# here and set -e aborted before any link was made.
#
# Mode 0700 explicitly (round 4d-2): ~/.claude holds settings.json and the
# composed global instructions, and under a permissive umask a bare
# `mkdir -p` would create it world-readable. -m applies only when the
# directory is created, so an existing ~/.claude keeps its own mode.
run_action mkdir -m 700 -p "$CLAUDE_DIR"
ensure_symlink "$PA_DIR/settings.json" "$CLAUDE_DIR/settings.json" "settings.json"

# ---------------------------------------------------------------------------
# Step 3: Command symlinks
# ---------------------------------------------------------------------------

say "[3/8] Linking commands..."
run_action mkdir -p "$CLAUDE_DIR/commands"
prune_stale_symlinks "$CLAUDE_DIR/commands" "$PA_DIR/commands" "command"
for cmd in "$PA_DIR"/commands/*.md; do
    [ -f "$cmd" ] || continue
    ensure_symlink "$cmd" "$CLAUDE_DIR/commands/$(basename "$cmd")" "$(basename "$cmd")"
done

# ---------------------------------------------------------------------------
# Step 4: Skill symlinks
# ---------------------------------------------------------------------------

say "[4/8] Linking skills..."
run_action mkdir -p "$CLAUDE_DIR/skills"
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

say "[5/8] Linking agents..."
run_action mkdir -p "$CLAUDE_DIR/agents"
prune_stale_symlinks "$CLAUDE_DIR/agents" "$PA_DIR/agents" "agent"
for agent_file in "$PA_DIR"/agents/*.md; do
    [ -f "$agent_file" ] || continue
    ensure_symlink "$agent_file" "$CLAUDE_DIR/agents/$(basename "$agent_file")" "$(basename "$agent_file")"
done

# ---------------------------------------------------------------------------
# Step 6: Output-style symlinks
#
# Output styles follow the same repo-source + symlink pattern as skills
# (added 2026-07-18, Workstream G). Claude Code reads user-level styles
# from ~/.claude/output-styles/; per-project styles in a repo's
# .claude/output-styles/ are unaffected by this step.
# ---------------------------------------------------------------------------

say "[6/8] Linking output styles..."
run_action mkdir -p "$CLAUDE_DIR/output-styles"
prune_stale_symlinks "$CLAUDE_DIR/output-styles" "$PA_DIR/output-styles" "output-style"
for style_file in "$PA_DIR"/output-styles/*.md; do
    [ -f "$style_file" ] || continue
    ensure_symlink "$style_file" "$CLAUDE_DIR/output-styles/$(basename "$style_file")" "$(basename "$style_file")"
done

# ---------------------------------------------------------------------------
# Step 7: Compose global CLAUDE.md
# ---------------------------------------------------------------------------

say "[7/8] Composing global CLAUDE.md..."
# The composer has its own live-checkout guard, so --allow-worktree has to
# reach it too (round 4d-2): otherwise the override left steps 2-6 done and
# step 7 refusing — the half-migrated state the guard above exists to stop.
compose_args=()
[[ $ALLOW_WORKTREE -eq 1 ]] && compose_args+=(--allow-foreign-root)
if [[ $DRY_RUN -eq 1 ]]; then
    # The composer has its own --dry-run, so pass the flag through rather
    # than skipping the step: the operator still sees what would be written.
    bash "$PA_DIR/scripts/compose-global-claude-md.sh" --dry-run \
        "${compose_args[@]}" >/dev/null
    say "  would compose $CLAUDE_DIR/CLAUDE.md"
else
    bash "$PA_DIR/scripts/compose-global-claude-md.sh" \
        "${compose_args[@]}" >/dev/null
    say_verbose "  Composed."
fi

# ---------------------------------------------------------------------------
# Step 8: Verify Python dependencies (cc-session-toolkit and friends)
#
# Why this lives in sync-symlinks rather than setup.sh-only:
# session-archive hooks (`cc_session_toolkit.cli archive` on
# SessionEnd/PreCompact) silently fail when the package is missing from
# the venv. Drift between machines — or a reformatted box — should not
# require the user to remember a manual pip step. The check is cheap
# in the common case (a handful of import probes); install only runs
# when something is actually missing.
# ---------------------------------------------------------------------------

say "[8/8] Verifying Python dependencies..."
if [ ! -d "$PA_DIR/venv" ]; then
    say "  WARNING: venv/ not present — run setup.sh to bootstrap."
elif [ ! -f "$PA_DIR/requirements.txt" ]; then
    say "  WARNING: requirements.txt missing — cannot verify deps."
else
    # Probe each declared top-level package and report the MISSING ones by
    # name. Import name differs from pip name in some cases
    # (psycopg2-binary → psycopg2, cc-session-toolkit → cc_session_toolkit)
    # so the list is hand-maintained alongside requirements.txt.
    missing_imports="$("$PA_DIR/venv/bin/python3" -c "
import importlib.util
required = ['anthropic', 'psycopg2', 'pytest', 'mcp', 'pyzotero', 'cc_session_toolkit']
print(' '.join(m for m in required if importlib.util.find_spec(m) is None))
" 2>/dev/null)" || missing_imports="PROBE_FAILED"

    if [ "$missing_imports" = "PROBE_FAILED" ]; then
        say "  WARNING: dependency probe failed — cannot verify deps."
    elif [ -z "$missing_imports" ]; then
        say_verbose "  All declared dependencies present."
    else
        # Audit round 4d (E9): install ONLY the missing distributions, and
        # never with --upgrade. `pip install --upgrade -r requirements.txt`
        # re-resolves every declared dependency — unattended, from cron and
        # from SessionStart — so a single missing import could silently
        # move anthropic, mcp, or psycopg2 to a new major version on a
        # machine nobody was watching. The requirement string is read back
        # out of requirements.txt so the git+ssh specification for
        # cc-session-toolkit is not duplicated here.
        say "  Missing dependencies: $missing_imports — installing just those..."
        specs=()
        for import_name in $missing_imports; do
            case "$import_name" in
                psycopg2)           pip_name="psycopg2-binary" ;;
                cc_session_toolkit) pip_name="cc-session-toolkit" ;;
                *)                  pip_name="$import_name" ;;
            esac
            spec="$(grep -E "^[[:space:]]*${pip_name}([[:space:]]|[<>=!~@]|\$)" \
                        "$PA_DIR/requirements.txt" | head -n 1 || true)"
            # Fall back to the bare distribution name if requirements.txt
            # has been reformatted out from under the grep, so a missing
            # dependency is still installable.
            specs+=("${spec:-$pip_name}")
        done
        # C4 (2026-05-19): capture pip's exit code explicitly. The
        # earlier ``&& ... || ...`` form swallowed the failure — bash's
        # short-circuit ``||`` makes the whole expression exit 0 once
        # the warning ``say`` runs, and ``set -e`` does not re-trigger.
        # Result: the self-heal could fail silently and cron would
        # report success, defeating this step's whole purpose.
        if run_action "$PA_DIR/venv/bin/pip" install --quiet "${specs[@]}"; then
            say "  Dependencies installed."
        else
            pip_exit=$?
            say "  ERROR: pip install failed (exit $pip_exit); archive hooks will continue to fail silently. Resolve before next session."
            DEPS_FAILED=1
        fi
    fi
fi

# C4 (2026-05-19): surface dependency-install failure to the caller
# (daily-sync.sh / cron) by exiting non-zero. All other steps having
# succeeded is not enough — a missing dep silently breaks SessionEnd
# archiving on every machine that re-syncs from a broken state.
if [ "${DEPS_FAILED:-0}" -eq 1 ]; then
    say "sync-symlinks FAILED (dependency install)."
    exit 1
fi

say "sync-symlinks complete."
