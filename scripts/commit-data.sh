#!/usr/bin/env bash
# commit-data.sh — Commit and push data submodule changes, then
# update the parent repo's submodule reference.
#
# Usage:
#   bash scripts/commit-data.sh "chore: sync memories from session"
#   bash scripts/commit-data.sh  # uses default message
#
# Locking: takes the same logs/daily-sync.lock used by daily-sync.sh
# so the two scripts cannot interleave on the data submodule's git
# index. Audit 2026-05-02 (E-Critical lock-gap): without this lock,
# a commit-data.sh run alongside an in-flight daily-sync rebase or
# stash could corrupt the merge state or lose the resolver output.
#
# Exit codes:
#   0  committed and pushed, or there was genuinely nothing to do
#   1  the lock is held, or the data submodule is not on `main` (a rebase,
#      `git am`, or a bisect that detached HEAD lands here too)
#   2  the data submodule has an unfinished merge, cherry-pick, revert, or
#      bisect, or unmerged index entries left by a conflicted stash pop or
#      `apply -3` — nothing was staged
#   3  this run had nothing of its own, but paths are staged and
#      uncommitted (another session's, or a run that died mid-commit), or
#      the parent's data pointer is stale and data's HEAD is not on origin

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PA_DIR="$(dirname "$SCRIPT_DIR")"
MSG="${1:-chore: sync data}"

# Acquire the daily-sync lock before touching the data submodule.
# Non-blocking: if daily-sync is already running, exit cleanly rather
# than queue indefinitely from an interactive shell.
LOG_DIR="$PA_DIR/logs"
LOCK_FILE="$LOG_DIR/daily-sync.lock"
mkdir -p "$LOG_DIR"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "Another daily-sync or commit-data is running (lock held). Exiting." >&2
    exit 1
fi

cd "$PA_DIR/data"

# Refuse to run unless the data submodule is on `main`. The previous
# implementation hardcoded `git push origin main`, which on a detached
# HEAD or feature branch silently pushed the *unchanged* local main
# (orphaning the new commit) — see Audit 2026-05-02 E-Critical
# (commit-data.sh:29 push-to-wrong-branch). `daily-sync.sh:257-264`
# already enforces a similar branch check; mirror that defence here.
DATA_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$DATA_BRANCH" != "main" ]]; then
    echo "ERROR: data submodule is on branch '$DATA_BRANCH', not 'main'." >&2
    echo "  Refusing to commit + push. Switch to main and try again, or" >&2
    echo "  push manually if you intend to publish a topic branch." >&2
    exit 1
fi

# Re-audit of PR #114 (2026-09-08), CRITICAL: refuse up front when the data
# submodule is mid-merge or mid-rebase. Every commit below names a pathspec,
# which makes it a PARTIAL commit, and git refuses those during a merge
# ("fatal: cannot do a partial commit during a merge", rc 128) — but only
# AFTER `git add` has staged the paths. The next run then finds no UNSTAGED
# changes, prints "No data changes to commit.", and exits 0 while the data
# sits uncommitted: a silent no-op that latches and survives every later run.
# Refuse before touching the index.
GIT_DIR_PATH="$(git rev-parse --git-dir)"
# Second re-audit: a conflicted `git stash pop` or `git apply -3` leaves
# UNMERGED INDEX ENTRIES with no marker file at all, and the marker-file
# test alone let the run stage the conflict markers, commit them, push, and
# exit 0. `ls-files --unmerged` is the check that sees the index itself.
if git rev-parse -q --verify MERGE_HEAD >/dev/null \
    || [ -d "$GIT_DIR_PATH/rebase-merge" ] \
    || [ -d "$GIT_DIR_PATH/rebase-apply" ] \
    || [ -e "$GIT_DIR_PATH/CHERRY_PICK_HEAD" ] \
    || [ -e "$GIT_DIR_PATH/REVERT_HEAD" ] \
    || [ -e "$GIT_DIR_PATH/BISECT_LOG" ] \
    || [ -n "$(git ls-files --unmerged)" ]; then
    echo "ERROR: the data submodule has an unfinished merge/rebase or unmerged paths." >&2
    echo "  NOTHING has been staged. Finish or abort it inside data/ first:" >&2
    echo "    git -C data status" >&2
    echo "    git -C data merge --continue   # or --abort" >&2
    echo "    git -C data rebase --continue  # or --abort" >&2
    exit 2
fi

# Snapshot what is ALREADY staged, before this run touches the index. Anything
# in here that this run does not own belongs to a concurrent session (or to a
# previous run that died after staging) and must be reported, never swept and
# never silently ignored.
mapfile -d '' -t PRESTAGED < <(git diff --cached --name-only -z)

# The unfiltered status: a pathspec-filtered listing hid withheld staged work
# (a fully staged `git mv` vanished from the output while the run still said
# "Done") — re-audit MEDIUM.
echo "=== Data submodule status (full) ==="
git status --short

# Audit 2026-09-08 S16: stage and commit an EXPLICIT pathspec. The previous
# `git add -A` followed by a bare `git commit` swept whatever a CONCURRENT
# session had already staged in the shared index into this commit — the hub
# rule in CLAUDE.md exists for exactly that failure. Collect the paths this
# run means to publish: working-tree changes plus untracked files, i.e.
# everything EXCEPT what is only staged.
mapfile -d '' -t RAW_PATHS < <(
    git diff --name-only -z
    git ls-files --others --exclude-standard -z
)

# De-duplicate, preserving order: `git diff --name-only` lists a conflicted
# path once per stage, and a path can be reported by both commands.
declare -A SEEN=()
DATA_PATHS=()
for _path in ${RAW_PATHS[@]+"${RAW_PATHS[@]}"}; do
    [[ -n "${SEEN[$_path]:-}" ]] && continue
    SEEN["$_path"]=1
    DATA_PATHS+=("$_path")
done

# Staged work this run does not own — reported, never committed here.
WITHHELD=()
for _path in ${PRESTAGED[@]+"${PRESTAGED[@]}"}; do
    [[ -n "${SEEN[$_path]:-}" ]] && continue
    WITHHELD+=("$_path")
done

DATA_COMMITTED=0
if [[ ${#DATA_PATHS[@]} -eq 0 ]]; then
    if [[ ${#WITHHELD[@]} -gt 0 ]]; then
        echo "ERROR: nothing for this run to stage, but these paths are" >&2
        echo "  staged and uncommitted in the data submodule:" >&2
        printf '    %q\n' "${WITHHELD[@]}" >&2
        echo "  They are another session's work, or a previous run that died" >&2
        echo "  mid-commit. Exiting non-zero rather than reporting success on" >&2
        echo "  data that is neither committed nor pushed. If a live session" >&2
        echo "  staged them, let it commit them. Only if you are sure a path is" >&2
        echo "  orphaned, unstage exactly that path and re-run:" >&2
        echo "    git -C data reset -- <path>    # never a bare reset: it would" >&2
        echo "                                   # hand another session's work" >&2
        echo "                                   # to this script's next run" >&2
        exit 3
    fi
    echo "No data changes to commit."
else
    echo "=== Committing these paths ==="
    printf '  %q\n' "${DATA_PATHS[@]}"
    if [[ ${#WITHHELD[@]} -gt 0 ]]; then
        echo "=== Withheld: staged by another session, NOT committed here ==="
        printf '  %q\n' "${WITHHELD[@]}"
    fi

# `git --literal-pathspecs` is load-bearing, not decoration. A pathspec is a
# GLOB by default, so a real filename such as `weird[1].md` matched — and
# committed — a concurrent session's staged `weird1.md` (reproduced during the
# re-audit). `--pathspec-file-nul` does NOT help: it makes the FILE FORMAT
# literal (no C-quoting), not the pathspec matching. Feeding the list on stdin
# additionally removes any argv-length ceiling and all quoting questions.
    printf '%s\0' "${DATA_PATHS[@]}" \
        | git --literal-pathspecs add --pathspec-from-file=- --pathspec-file-nul

    if git --literal-pathspecs diff --cached --quiet -- "${DATA_PATHS[@]}"; then
        echo "No data changes to commit."
    else
        printf '%s\0' "${DATA_PATHS[@]}" \
            | git --literal-pathspecs commit --pathspec-from-file=- --pathspec-file-nul \
                -m "$MSG

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
        DATA_COMMITTED=1

        # Post-condition: name anything this run left staged, so an operator
        # never has to infer it from a "Done" line.
        mapfile -d '' -t STILL_STAGED < <(git diff --cached --name-only -z)
        if [[ ${#STILL_STAGED[@]} -gt 0 ]]; then
            echo "NOTE: still staged in the data submodule, NOT committed by this run:"
            printf '  %q\n' "${STILL_STAGED[@]}"
            echo "  (left for the session that staged them)"
        fi
        # Use HEAD:main rather than a bare `main` ref so the push fails loudly
        # if the local branch ever diverges from the expected name (defence in
        # depth — the explicit branch check above should already have caught it).
        git push origin HEAD:main
    fi
fi

cd "$PA_DIR"

# Second re-audit, medium: a previous run may have committed and pushed the
# data submodule and died before the pointer bump below, leaving the parent
# with a stale pointer and every later run saying "nothing to do". If this
# run committed nothing, bump anyway when the pointer is stale and data's
# HEAD is already on origin; refuse (never silently succeed) when it is not.
if [[ $DATA_COMMITTED -eq 0 ]]; then
    # A parent with no commit yet has no pointer to be stale.
    if ! git rev-parse -q --verify HEAD >/dev/null || git diff HEAD --quiet -- data; then
        exit 0                      # pointer current: genuinely nothing to do
    fi
    if ! git -C data merge-base --is-ancestor HEAD origin/main 2>/dev/null; then
        echo "ERROR: the parent's data pointer is stale and data's HEAD is not on" >&2
        echo "  origin/main (a previous run died before its push?). Push it first:" >&2
        echo "    git -C data push origin HEAD:main" >&2
        exit 3
    fi
    echo "Parent pointer is stale but data's HEAD is already on origin — bumping it."
fi

# Mirror the branch check on the parent repo: pushing a submodule pointer
# bump from a non-main branch is the same silent-data-loss shape.
PARENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$PARENT_BRANCH" != "main" ]]; then
    echo "WARNING: parent repo is on branch '$PARENT_BRANCH', not 'main'." >&2
    echo "  Submodule reference will be committed locally but not pushed." >&2
    echo "  Push manually once you have decided where the bump should land." >&2
    exit 0
fi

# S16: the parent-repo bump is a single-path commit — name the path on the
# commit too, so a concurrent session's staged prose cannot ride along.
# `--literal-pathspecs` for the same reason as above: uniform treatment, and
# no pathspec in this script is ever a glob.
git --literal-pathspecs add -- data
git --literal-pathspecs commit -m "chore: update data submodule reference

$MSG

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>" -- data

echo ""
echo "Done. Data committed and submodule reference updated."
echo "Run 'git push origin main' to push the parent repo."
