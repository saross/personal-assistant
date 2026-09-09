#!/usr/bin/env bash
# compose-global-claude-md.sh — Compose ~/.claude/CLAUDE.md from the shared
# (portable), Claude-overlay, and local (private) instruction sources.
#
# Layering (Sol-integration plan §6, Phase 2):
#   1. global-agent-guidance/common.md   — portable, agent-neutral guidance.
#      SHARED editing surface: Claude and Sol may both propose changes to it,
#      and Sol's gpt-hub installer composes the same file into
#      ~/.codex/AGENTS.md. Nothing harness-specific belongs here.
#   2. global-claude-md/claude.md        — Claude-owned overlay: commands,
#      tools, models, and Claude-owned stores. Never read by Sol's composer.
#   3. data/global-claude-md/local.md    — private machine detail (network
#      topology, server guardrails), from the pa-data submodule.
#
# This composer writes only Claude's output. It must never write
# ~/.codex/AGENTS.md, and Sol's installer must never write ~/.claude/CLAUDE.md.
#
# Usage:
#   bash scripts/compose-global-claude-md.sh
#   bash scripts/compose-global-claude-md.sh --dry-run
#   bash scripts/compose-global-claude-md.sh --target /path/to/CLAUDE.md
#
# Any other argument is a usage error (exit 2). The sources are resolved
# from this script's own location, but the default target is the LIVE
# ~/.claude/CLAUDE.md, so running the script from a worktree would
# overwrite the operator's global instructions with a branch's content.
# It therefore refuses to write the default target from anywhere but
# $HOME/personal-assistant unless --target says otherwise.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PA_DIR="$(dirname "$SCRIPT_DIR")"

COMMON="$PA_DIR/global-agent-guidance/common.md"
OVERLAY="$PA_DIR/global-claude-md/claude.md"
LOCAL="$PA_DIR/data/global-claude-md/local.md"
TARGET="${HOME}/.claude/CLAUDE.md"

usage() {
    echo "Usage: compose-global-claude-md.sh [--dry-run]" \
         "[--target <path>] [--allow-foreign-root]" >&2
}

DRY_RUN=false
# Deliberate, named bypass of the live-checkout provenance guard below.
# sync-symlinks.sh passes it through from its own --allow-worktree, so a
# migration the operator actually asked for does not die half-done.
ALLOW_FOREIGN_ROOT=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)
            # Audit round 4d (E13): only this exact spelling used to be
            # recognised, and "--dryrun" silently overwrote the target.
            DRY_RUN=true
            shift
            ;;
        --target)
            if [[ $# -lt 2 || -z "$2" ]]; then
                echo "ERROR: --target needs a path" >&2
                usage
                exit 2
            fi
            TARGET="$2"
            shift 2
            ;;
        --allow-foreign-root)
            ALLOW_FOREIGN_ROOT=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: unknown argument: $1" >&2
            usage
            exit 2
            ;;
    esac
done

# Refuse to write into a directory. `mv` onto an existing directory moves
# the temporary file INSIDE it, so `--target <a directory>` used to exit 0
# having composed nothing and left a stray dot-file behind (round 4d-2).
if [[ -d "$TARGET" ]]; then
    echo "ERROR: --target must name a file, not a directory: $TARGET" >&2
    exit 2
fi

# Audit round 4d (E11), tightened in round 4d-2: the sources come from
# $SCRIPT_DIR but the protected artefact is the LIVE ~/.claude/CLAUDE.md,
# so a run from a git worktree would replace the operator's global
# instructions with whatever that branch happens to contain.
#
# The guard is keyed on the TARGET'S IDENTITY, not on the absence of
# --target: naming the live file explicitly is exactly the case that
# needs stopping, and round 4d's version waved it straight through.
#
# resolve_path <path> — absolute, symlink-resolved path, for a file that
# need not exist yet (its parent directory must).
resolve_path() {
    local path="$1" dir base resolved
    # Round 4d-3: resolve the LEAF too when it exists. Resolving only the
    # directory left a symlink FILE naming the live CLAUDE.md
    # unrecognised — `--target ~/link-to-claude-md` compared as itself,
    # so the guard did not fire. (The write would not have gone THROUGH
    # the link: `mv` replaces the link itself. It would have destroyed the
    # operator's symlink and left the live file stale but present, which
    # is its own quiet failure and is exactly the intent the guard exists
    # to catch.)
    # `-e` alone is FALSE for a dangling symlink (round 4d-4, L5), so a
    # link naming the live CLAUDE.md before that file exists slipped past
    # the guard and was replaced by a regular file. `-L` catches it, and
    # `readlink -f` canonicalises a link whose target does not exist yet.
    if [[ -e "$path" || -L "$path" ]]; then
        resolved="$(readlink -f -- "$path" 2>/dev/null || true)"
        if [[ -n "$resolved" ]]; then
            printf '%s\n' "$resolved"
            return 0
        fi
    fi
    dir="$(dirname "$path")"
    base="$(basename "$path")"
    if [[ -d "$dir" ]]; then
        printf '%s/%s\n' "$(cd "$dir" && pwd -P)" "$base"
    else
        printf '%s\n' "$path"
    fi
}

LIVE_ROOT="${HOME}/personal-assistant"
LIVE_TARGET="$(resolve_path "${HOME}/.claude/CLAUDE.md")"
# --dry-run writes nothing, so there is nothing for the guard to protect;
# inspecting what a foreign checkout WOULD compose is the flag's purpose.
if [[ "$DRY_RUN" == false && "$ALLOW_FOREIGN_ROOT" == false \
      && "$(resolve_path "$TARGET")" == "$LIVE_TARGET" ]]; then
    if [[ -e "$LIVE_ROOT" || -L "$LIVE_ROOT" ]]; then
        # An unusable live root — a plain file, or a symlink that does not
        # resolve — means provenance cannot be established at all. Refuse
        # rather than guess.
        if [[ ! -d "$LIVE_ROOT" ]]; then
            echo "ERROR: $LIVE_ROOT is not a usable checkout; refusing to" \
                 "write the live $LIVE_TARGET" >&2
            exit 2
        fi
        live_real="$(cd "$LIVE_ROOT" && pwd -P)"
        pa_real="$(cd "$PA_DIR" && pwd -P)"
        if [[ "$live_real" != "$pa_real" ]]; then
            echo "ERROR: refusing to write $LIVE_TARGET from $PA_DIR" \
                 "(not $live_real); pass --target <path> to compose" \
                 "somewhere else" >&2
            exit 2
        fi
    else
        # No checkout at $LIVE_ROOT at all. On a real machine this script
        # lives inside that checkout, so this state is a fresh bootstrap
        # from a clone at some other path — or a test with a pinned HOME.
        # There is no live checkout whose instructions could be clobbered,
        # so this proceeds, loudly.
        echo "WARNING: no checkout at $LIVE_ROOT; composing $LIVE_TARGET" \
             "from $PA_DIR without a provenance check" >&2
    fi
fi

# Verify source files exist.
if [[ ! -f "$COMMON" ]]; then
    echo "ERROR: Shared common section not found: $COMMON" >&2
    exit 1
fi

if [[ ! -f "$OVERLAY" ]]; then
    echo "ERROR: Claude overlay not found: $OVERLAY" >&2
    exit 1
fi

if [[ ! -f "$LOCAL" ]]; then
    echo "ERROR: Local section not found: $LOCAL" >&2
    # Round 4d-4 (M2): this used to advise `git submodule update --init`,
    # which is the one command that cannot help when data/ exists and is
    # not empty — git refuses to clone into a non-empty directory
    # (verified against git 2.48.1).
    #
    # Round 4d-5 (C1): "not empty" was the WRONG test for choosing between
    # the two remedies. An initialised submodule is also non-empty, so a
    # perfectly healthy data/ that merely lacked this one file was met with
    # "Remove $PA_DIR/data entirely" — advice that destroys uncommitted
    # work in the private pa-data submodule. Branch on whether the
    # submodule has a CHECKOUT (git leaves a .git file inside one) rather
    # than on whether the directory has bytes in it.
    if [[ -e "$PA_DIR/data/.git" ]]; then
        echo "  data/ is initialised, so this is a missing file inside the" >&2
        echo "  submodule rather than a missing submodule. Look there:" >&2
        echo "    git -C $PA_DIR/data status -- global-claude-md/" >&2
        echo "  Do NOT delete $PA_DIR/data: it is the private pa-data" >&2
        echo "  submodule and may hold uncommitted work." >&2
    elif [[ -d "$PA_DIR/data" ]] && [[ -n "$(ls -A "$PA_DIR/data" 2>/dev/null)" ]]; then
        echo "  data/ exists, is not empty, and has no submodule checkout," >&2
        echo "  so git cannot clone into it. Remove $PA_DIR/data, then run:" >&2
        echo "    git -C $PA_DIR submodule update --init" >&2
    else
        echo "  (Is the data submodule initialised?" \
             "Run: git -C $PA_DIR submodule update --init)" >&2
    fi
    exit 1
fi

# Compose the file.
#
# Audit 2026-05-02 E-Medium: a previous implementation captured each source
# file via `$(cat …)`, which strips trailing newlines (POSIX text-file
# convention violated) and then silently overwrote any user edits to the
# generated file. We now (a) prepend a generated-file banner so users see
# the file is mechanically composed, and (b) stream the inputs through
# `cat` directly to preserve trailing newlines.
GENERATED_BANNER="<!--
  Generated by scripts/compose-global-claude-md.sh — do not edit by hand.
  Edit the source files instead:
    common (shared with Sol): ${COMMON}
    Claude overlay:           ${OVERLAY}
    local (private):          ${LOCAL}
  Any direct edits to this file will be silently overwritten on the next
  sync (sync-symlinks.sh runs the composer at the end of every daily-sync
  and at every SessionStart).
-->
"

# Emit the composed document on stdout. Blank lines separate the banner and
# each source section.
compose() {
    printf '%s\n' "$GENERATED_BANNER"
    cat "$COMMON"
    printf '\n'
    cat "$OVERLAY"
    printf '\n'
    cat "$LOCAL"
}

if $DRY_RUN; then
    # Materialise once to a temporary file. Piping `compose` straight into
    # `head` makes `head` close the pipe early, which under `set -o pipefail`
    # fails the whole script with SIGPIPE (exit 141) — a latent bug in the
    # pre-Phase-2 version of this script.
    PREVIEW="$(mktemp)"
    trap 'rm -f "$PREVIEW"' EXIT
    compose > "$PREVIEW"
    echo "=== Would write to: $TARGET ==="
    head -10 "$PREVIEW"
    echo "..."
    tail -5 "$PREVIEW"
    echo ""
    echo "Total lines: $(wc -l < "$PREVIEW")"
    echo "Total bytes: $(wc -c < "$PREVIEW")"
else
    mkdir -p "$(dirname "$TARGET")"
    # Audit 2026-09-08 S13: compose into a temporary file in the SAME
    # directory, then rename. `compose > "$TARGET"` truncated the target
    # before the first byte was written, so any failure inside compose (the
    # data submodule unmounted between the check above and the write, ENOSPC,
    # an unreadable source) left ~/.claude/CLAUDE.md truncated — silently
    # dropping the outbound-message rule and the ownership boundaries — and
    # `set -e` then aborted without restoring it. mv(1) within one directory
    # is atomic: a reader sees either the previous file or the complete new
    # one, never a partial write.
    TMP_TARGET="$(mktemp "$(dirname "$TARGET")/.CLAUDE.md.XXXXXX")"
    trap 'rm -f "$TMP_TARGET"' EXIT
    compose > "$TMP_TARGET"
    # mktemp creates 0600; the composed instructions are ordinary readable
    # config, so restore the mode a plain redirect would have produced.
    chmod 0644 "$TMP_TARGET"
    mv "$TMP_TARGET" "$TARGET"
    echo "Composed $TARGET from:"
    # Byte counts matter for the cross-harness instruction budget (plan §6):
    # common.md is also loaded by Codex, where oversized global instructions
    # silently displace nearer, more specific project files.
    printf '  common:  %s (%s lines, %s bytes)\n' \
        "$COMMON" "$(wc -l < "$COMMON")" "$(wc -c < "$COMMON")"
    printf '  overlay: %s (%s lines, %s bytes)\n' \
        "$OVERLAY" "$(wc -l < "$OVERLAY")" "$(wc -c < "$OVERLAY")"
    printf '  local:   %s (%s lines, %s bytes)\n' \
        "$LOCAL" "$(wc -l < "$LOCAL")" "$(wc -c < "$LOCAL")"
    printf '  output:  %s (%s lines, %s bytes)\n' \
        "$TARGET" "$(wc -l < "$TARGET")" "$(wc -c < "$TARGET")"
fi
