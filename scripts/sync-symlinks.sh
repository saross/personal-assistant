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

did() {
    # Narrate a completed action, or what --dry-run WOULD do. Round 4d-2:
    # every line below said "pruned"/"linked" in the past tense even under
    # --dry-run, so a preview read as a report of work already done.
    if [[ $DRY_RUN -eq 1 ]]; then
        say "  would $1"
    else
        say "  $2"
    fi
}

did_verbose() {
    # As `did`, but the completed form is suppressed by --quiet. A dry
    # run always narrates: telling the operator what would happen is the
    # whole point of the flag, quiet or not.
    if [[ $DRY_RUN -eq 1 ]]; then
        say "  would $1"
    else
        say_verbose "  $2"
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
                    did "prune the stale $label symlink $(basename "$link")" \
                        "$(basename "$link") — pruned stale $label symlink"
                    removed=$((removed + 1))
                fi
                ;;
        esac
    done
    if [ "$removed" -gt 0 ]; then
        did "prune $removed stale $label symlink(s)" \
            "pruned $removed stale $label symlink(s)"
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
            did "update the $label symlink" "$label — updated symlink"
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
        did "link $label" "$label — linked"
    fi
}

# ---------------------------------------------------------------------------
# Step 1: Submodule init/update (idempotent; no-op once up to date)
# ---------------------------------------------------------------------------

say "[1/8] Ensuring data submodule is initialised..."
cd "$PA_DIR"

#: The remedy for a non-empty, UNINITIALISED data/ — and ONLY for that
#: state. Named once so step 1 and the step-7 pre-check cannot drift apart.
#:
#: Round 4d-5 (C1): this string was printed for every non-worktree run
#: that reached the pre-check, including one whose submodule is perfectly
#: initialised and merely missing a file. data/ is the PRIVATE pa-data
#: submodule; telling an operator to delete it destroys uncommitted work,
#: and the parenthesised rationale is simply false in that state. Every
#: use is now gated on $submodule_state.
DATA_REMEDY="remove $PA_DIR/data entirely (git will not clone into a \
non-empty directory), then re-run this script."

say_data_remedy() {
    # Print the remedy that fits the submodule's ACTUAL state. The
    # destructive one is reachable only when git says the submodule has no
    # checkout at all, so nothing of the operator's can be inside it.
    if [ -z "$submodule_state" ]; then
        say "  Remedy: no data submodule is declared in this checkout, so"
        say "    $COMPOSER_LOCAL cannot appear. Check .gitmodules."
    elif [ "${submodule_state#-}" != "$submodule_state" ]; then
        say "  Remedy: $DATA_REMEDY"
    else
        say "  Remedy: data/ IS initialised, so this is a missing file"
        say "    inside the submodule, not a missing submodule. Look there:"
        say "      git -C $PA_DIR/data status -- global-claude-md/"
        say "    and restore it. Do NOT delete $PA_DIR/data — it is the"
        say "    private pa-data submodule and may hold uncommitted work."
    fi
}
#: The composer's only data/-borne source; step 7 fails without it.
COMPOSER_LOCAL="$PA_DIR/data/global-claude-md/local.md"
SKIP_COMPOSE=0
# Audit round 4d (E10): run this ONLY when data/ is uninitialised. On an
# already-initialised submodule `git submodule update` checks out the
# gitlink SHA recorded in the superproject, which detaches data/ from its
# branch; commits a concurrent session has made inside data/ but not yet
# pointed at from the superproject become unreferenced. This step exists
# solely to populate an empty data/, so an uninitialised data/ is the only
# case in which it should run.
#
# Round 4d-2: ask git, not the directory listing. `git submodule status`
# prefixes an UNINITIALISED submodule with "-"; anything else (" ", "+",
# "U") means it has a checkout.
#
# Round 4d-3 (M1/M2): git saying "uninitialised" is necessary but not
# sufficient, because `git submodule update --init` CLONES into data/ and
# git refuses to clone into a directory that is not empty:
#
#     fatal: destination path '.../data' already exists and is not an
#     empty directory.
#
# Two states reach that error. A linked WORKTREE is one: its data/ holds
# empty stub directories and git reports the submodule uninitialised, so
# round 4d-2's rule sent --allow-worktree straight into an init that
# cannot succeed, and `set -e` aborted at step 1 — leaving the escape
# hatch inoperative for the only case it was added for, and ~/.claude
# never touched. (The comment that stood here claimed the opposite of
# what the code did.) A worktree's data/ belongs to the main checkout and
# is never this script's to populate, so it is skipped outright.
#
# The other is a clone whose data/ holds a stray file. Round 4d-2 made
# that case attempt the init; verified against a throwaway superproject,
# git fails there too. Attempting it and aborting the whole run is worse
# than saying plainly what a human has to clear.
#
# In a linked worktree $PA_DIR/.git is a FILE holding a "gitdir:" pointer;
# in an ordinary clone it is a directory.
#
# Round 4d-5 (L-b): "is .git a file" is not quite the question. A
# SUBMODULE checkout of this repository also has a .git file, and it is
# not a worktree — its data/ is its own to initialise. The pointer says
# which is which: git writes ".git/worktrees/<name>" for a linked
# worktree and ".git/modules/<name>" for a submodule. Matching on that is
# exact, and needs no git binary, which matters because this step runs
# before anything has verified git works.
IS_WORKTREE=0
if [ -f "$PA_DIR/.git" ] &&
   grep -qE '^gitdir:.*/\.git/worktrees/' "$PA_DIR/.git" 2>/dev/null; then
    IS_WORKTREE=1
fi

submodule_state="$(git submodule status -- data 2>/dev/null || true)"
if [ -z "$submodule_state" ]; then
    say_verbose "  No data submodule declared — nothing to initialise."
elif [ "${submodule_state#-}" = "$submodule_state" ]; then
    say_verbose "  Submodule already initialised — leaving it alone."
elif [ $IS_WORKTREE -eq 1 ]; then
    # Round 4d-4 (M1): $ALLOW_WORKTREE must NOT appear in this test. It is
    # the operator saying "I know this is a worktree, proceed anyway" —
    # not evidence about the checkout. Treating the flag as the fact made
    # a plain clone run with --allow-worktree announce itself a worktree,
    # skip an init it genuinely needed, relink all of ~/.claude at that
    # clone, and then die at step 7 on the missing local source: the
    # half-migrated state this whole guard exists to prevent, reached by a
    # new route. $IS_WORKTREE is derived from the checkout itself and
    # already covers every case the flag was standing in for.
    say "  Worktree checkout — data/ belongs to the main checkout, skipping."
elif [ -n "$(ls -A "$PA_DIR/data" 2>/dev/null || true)" ]; then
    # Round 4d-4 (M2): the remedy here used to offer
    # "run 'git submodule update --init' by hand", which is the very
    # command that cannot work — git refuses to clone into a non-empty
    # directory, by hand or otherwise (verified against git 2.48.1 on a
    # throwaway superproject). Emptying data/ is the only thing that
    # helps, so it is the only thing offered.
    say "  WARNING: data/ is uninitialised but not empty, so git cannot"
    say "    clone into it. $DATA_REMEDY"
else
    run_action git submodule update --init --recursive --quiet
    did_verbose "have the submodule ready" "Submodule ready."
fi

# Round 4d-4 (M2): step 7 composes ~/.claude/CLAUDE.md from three sources,
# one of which lives in data/. If that source is absent the composer
# CANNOT succeed — and discovering it at step 7, after steps 2-6 have
# relinked every ~/.claude symlink, leaves exactly the half-migrated
# machine this script works to avoid, with step 1's warning long scrolled
# away. Decide it here instead, while nothing has been changed yet.
#
# Round 4d-5 (M-a): the DRY_RUN exemption used to sit on this whole
# block, so a preview never set SKIP_COMPOSE, step 7 ran the composer
# anyway, and the composer died on the very file the block had just
# established was missing — a dry run exiting 1 where the real run exits
# 0. Only the STOP is exempt from --dry-run; the skip applies either way.
if [ ! -f "$COMPOSER_LOCAL" ]; then
    if [ $IS_WORKTREE -eq 1 ]; then
        # A worktree's data/ is the main checkout's, so this is expected
        # rather than broken. Steps 2-6 are what --allow-worktree is for;
        # step 7 is skipped and said so, twice.
        say "  NOTE: $COMPOSER_LOCAL is absent (data/ belongs to the main"
        say "    checkout), so step 7 will be SKIPPED and"
        say "    $CLAUDE_DIR/CLAUDE.md left as it is."
        SKIP_COMPOSE=1
    elif [ $DRY_RUN -eq 1 ]; then
        # L-c, decided in round 4d-5: a preview changes nothing, so it
        # must not fail, and it must run to the end — a preview that
        # stops two thirds of the way through is not a preview. It says
        # plainly that the real run would refuse, then narrates the rest.
        #
        # Round 4d-6 (L5): and it prints the SAME remedy the real run
        # would. A preview whose whole job is to show what would happen
        # was withholding the one line the operator needs to act on.
        say "  NOTE: $COMPOSER_LOCAL is missing, so a REAL run would"
        say "    refuse at step 1. This preview continues, and step 7"
        say "    will be skipped."
        say_data_remedy
        SKIP_COMPOSE=1
    else
        say "ERROR: $COMPOSER_LOCAL is missing, so step 7 cannot succeed."
        say "  Stopping now, before any symlink is changed, rather than"
        say "  relinking $CLAUDE_DIR and failing half-way through."
        say_data_remedy
        exit 1
    fi
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
if [[ $SKIP_COMPOSE -eq 1 ]]; then
    # Decided at step 1, repeated here so the reason is beside the gap it
    # explains rather than scrolled off the top of a cron log (round
    # 4d-4, M2).
    say "  SKIPPED: $COMPOSER_LOCAL is absent, so there is nothing to"
    say "    compose from. $CLAUDE_DIR/CLAUDE.md is unchanged."
elif [[ $DRY_RUN -eq 1 ]]; then
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
        if [[ $DRY_RUN -eq 1 ]]; then
            say "  Missing dependencies: $missing_imports — would install just those"
        else
            say "  Missing dependencies: $missing_imports — installing just those..."
        fi
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
            did "have installed them" "Dependencies installed."
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
