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
#      `apply -3`; or `data` is tracked in the parent as ordinary files
#      rather than a submodule — in every case nothing was staged
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

# Third re-audit: `data` must be a gitlink (mode 160000) in the parent index,
# or absent. If it is tracked as ordinary files, the pointer bump's
# `git add -- data` would commit the private submodule's CONTENTS into the
# public parent. Checked here, before anything is committed or pushed, so
# exit 2 keeps its "nothing happened" meaning (fourth re-audit).
DATA_MODES="$(git -C "$PA_DIR" ls-files -s -- data | cut -c1-6 | sort -u | tr '\n' ' ')"
if [[ -n "$DATA_MODES" && "$DATA_MODES" != "160000 " ]]; then
    echo "ERROR: data is tracked in the parent as ordinary files (modes: $DATA_MODES)," >&2
    echo "  not as a submodule. Refusing to commit its contents into the parent." >&2
    exit 2
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
    echo "    git -C data bisect reset       # after a bisect" >&2
    echo "  Unmerged paths with no merge in progress (a conflicted stash pop or" >&2
    echo "  apply): resolve each path by hand, then 'git -C data add -- <path>'." >&2
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

# A parent with no commit yet has no pointer to update (and the branch query
# below would die on an unborn HEAD after the data was already pushed).
if ! git rev-parse -q --verify HEAD >/dev/null; then
    echo "NOTE: parent repository has no commit yet; no submodule pointer to update."
    exit 0
fi

# Second and third re-audits: a previous run may have committed and pushed
# the data submodule and died before the pointer bump below, leaving the
# parent with a stale pointer and every later run saying "nothing to do".
# If this run committed nothing, bump when — and only when — the recorded
# pointer is BEHIND data's HEAD and that HEAD is already on origin. The
# recorded SHA and the checkout's HEAD are read directly: `git diff` is
# silenced by diff.ignoreSubmodules or submodule.<name>.ignore.
RECORDED="$(git rev-parse -q --verify HEAD:data 2>/dev/null || true)"
DATA_HEAD="$(git -C data rev-parse HEAD)"
if [[ $DATA_COMMITTED -eq 0 ]]; then
    if [[ -z "$RECORDED" || "$RECORDED" == "$DATA_HEAD" ]]; then
        exit 0                      # nothing recorded yet, or pointer current
    fi
    # Direction matters. The parent being AHEAD (pulled without
    # `git submodule update`) shows the same inequality, and bumping then
    # rolled the pointer back for every other machine (third re-audit).
    if ! git -C data merge-base --is-ancestor "$RECORDED" "$DATA_HEAD" 2>/dev/null; then
        echo "NOTE: the parent's data pointer (${RECORDED:0:7}) is not behind the data"
        echo "  checkout (${DATA_HEAD:0:7}): the checkout is behind the parent"
        echo "  (git submodule update) or they diverged. Nothing committed."
        exit 0
    fi
    # Refresh the tracking ref so a stale one cannot give a false exit 3; never
    # prompt for credentials here (an expired token would block on the tty),
    # and never let a failed fetch abort the run — the next test says why.
    GIT_TERMINAL_PROMPT=0 git -C data fetch --quiet origin main 2>/dev/null || true
    if ! git -C data merge-base --is-ancestor "$DATA_HEAD" origin/main 2>/dev/null; then
        echo "ERROR: the parent's data pointer is stale and data's HEAD (${DATA_HEAD:0:7})" >&2
        echo "  is not on origin/main. If that commit is this machine's own dead run," >&2
        echo "  push it and re-run; if it is another session's, leave it to that" >&2
        echo "  session. Nothing committed." >&2
        exit 3
    fi
    echo "Parent pointer is stale but data's HEAD is already on origin — bumping it."
fi

# Mirror the branch check on the parent repo: pushing a submodule pointer
# bump from a non-main branch is the same silent-data-loss shape.
PARENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$PARENT_BRANCH" != "main" ]]; then
    echo "WARNING: parent repo is on branch '$PARENT_BRANCH', not 'main'." >&2
    echo "  The submodule reference is NOT committed or pushed from here; the data" >&2
    echo "  itself is on origin. Commit the bump yourself once you have decided" >&2
    echo "  where it should land." >&2
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
if [[ $DATA_COMMITTED -eq 1 ]]; then
    echo "Done. Data committed and submodule reference updated."
else
    echo "Done. Submodule reference updated to the already-pushed data commit."
fi
echo "Run 'git push origin main' to push the parent repo."
