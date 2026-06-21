#!/usr/bin/env bash
# =============================================================================
# search-archives-safe.sh — crash-proof full-text search over cc-archives .gz
# =============================================================================
#
# WHY THIS EXISTS
# ---------------
# On 2026-06-21 an ad-hoc transcript search locked the machine hard (mouse
# froze, all fans to maximum, OOM). Root cause (see
# ~/Code/inscriptions/planning/archive-search-crash-diagnosis-2026-06-21.md):
#
#   R0  `zcat | tr '\n' ' ' | grep -oiE '.{0,120}…'` collapsed each ~25 MB
#       JSONL transcript into ONE ~25 MB line, then ran a large bounded-quantifier
#       regex over that single line — near-quadratic scan, one core pinned, whole
#       line held resident.
#   R1  ~5 such pipelines were left running concurrently in the background,
#       racing the harness's own search hook → all 16 cores saturated, swap thrash.
#   R2  No nice/ionice/timeout/cgroup/concurrency-cap anywhere.
#
# This wrapper makes every one of those impossible. It is the FALLBACK path for
# ad-hoc grep; the everyday path is the indexed search (scripts/search-sessions.py
# / the /search-sessions skill / the search_sessions MCP tool), which never reads
# a .gz at query time.
#
# ENGINE NOTE — why not ripgrep/grep
# ----------------------------------
# On this machine `rg` and `grep` are shell FUNCTIONS that route to the Claude
# Code executable, not standalone binaries (the harness's own ripgrep was itself
# part of the crash). So the actual scan is done by a pure-Python streaming engine
# (scripts/_scan_archives.py) which has no such dependency and is fully bounded.
# This wrapper's job is to impose the OS-level safety limits AROUND that engine.
#
# THE INVARIANTS IT ENFORCES (all from the diagnosis §4)
# ------------------------------------------------------
#   (a) NEVER collapses newlines. The Python engine is strictly line-oriented and
#       streams one line at a time; there is no `tr` anywhere in this path.
#   (b) Memory-bounded: one line (plus a tiny context buffer) resident at a time,
#       with a per-line length guard so even a pathological line is truncated.
#   (c) Strictly ONE search at a time, enforced by a non-blocking flock: a second
#       invocation refuses rather than stacking load (the R1/R3 amplifier).
#   (d) Wraps the run in nice + ionice + timeout, and — when available — a
#       systemd-run --user cgroup scope with hard MemoryMax / CPUQuota caps, so
#       even a mistake stays inside its own scope without touching the desktop.
#   It runs in the FOREGROUND and never backgrounds itself.
#
# USAGE
# -----
#   scripts/search-archives-safe.sh PATTERN [PATH] [-- EXTRA_RG_ARGS...]
#   scripts/search-archives-safe.sh PATTERN [PATH] --and SECOND_PATTERN
#
#   PATTERN        Python regex (case-insensitive by default).
#   PATH           archive subtree to search (default: ~/cc-archives).
#   --and PAT2     AND-filter: a line must match BOTH PATTERN and PAT2. Note this
#                  is SAME-LINE (= same JSONL record = same transcript turn), not
#                  cross-turn proximity. For "X near Y across turns", use the
#                  indexed search (Postgres FTS), not this fallback.
#   -- ...         everything after `--` is passed verbatim to the scan engine.
#
# ENVIRONMENT OVERRIDES (sensible safe defaults; tighten freely)
#   SAS_TIMEOUT     wall-clock kill, seconds            (default 120)
#   SAS_MEMMAX      cgroup MemoryMax                    (default 2G)
#   SAS_CPUQUOTA    cgroup CPUQuota (400% ≈ 4/16 cores) (default 400%)
#   SAS_CONTEXT     engine context lines (-C)           (default 2)
#   SAS_MAXLINE     per-line truncation guard, chars    (default 1000000)
#   SAS_NO_CGROUP   set to 1 to skip the cgroup scope even if available
#
# EXIT CODES: 0 matches; 1 no matches (grep convention); 2 bad invocation
#             (path/engine/python missing); 124 timed out; 3 refused
#             (another search already running).
# =============================================================================

set -euo pipefail

# --- Defaults ---------------------------------------------------------------
ARCHIVE_DEFAULT="${HOME}/cc-archives"
SAS_TIMEOUT="${SAS_TIMEOUT:-120}"
SAS_MEMMAX="${SAS_MEMMAX:-2G}"
SAS_CPUQUOTA="${SAS_CPUQUOTA:-400%}"
SAS_CONTEXT="${SAS_CONTEXT:-2}"
SAS_MAXLINE="${SAS_MAXLINE:-1000000}"
SAS_NO_CGROUP="${SAS_NO_CGROUP:-0}"
LOCKFILE="${TMPDIR:-/tmp}/cc-archive-search.lock"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="${SCRIPT_DIR}/_scan_archives.py"

# --- Argument parsing -------------------------------------------------------
if [[ $# -lt 1 || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    sed -n '2,69p' "$0"   # print the whole header block (through EXIT CODES) as help
    exit 0
fi

PATTERN="$1"; shift
SEARCH_PATH="$ARCHIVE_DEFAULT"
AND_PATTERN=""
EXTRA_ARGS=()

# First non-flag arg (if present) is the path.
if [[ $# -gt 0 && "${1:-}" != --* ]]; then
    SEARCH_PATH="$1"; shift
fi
while [[ $# -gt 0 ]]; do
    case "$1" in
        --and) AND_PATTERN="${2:?--and needs a pattern}"; shift 2 ;;
        --)    shift; EXTRA_ARGS+=("$@"); break ;;
        *)     EXTRA_ARGS+=("$1"); shift ;;
    esac
done

if [[ ! -e "$SEARCH_PATH" ]]; then
    echo "search-archives-safe: path not found: $SEARCH_PATH" >&2
    exit 2
fi
if [[ ! -f "$ENGINE" ]]; then
    echo "search-archives-safe: scan engine not found: $ENGINE" >&2
    exit 2
fi
# Use the venv python if present (matches the rest of the hub's tooling),
# else the system python3 — both can read gzip line-by-line. Fail loudly with
# exit 2 if neither exists, so a missing interpreter is never mistaken for the
# exit-1 "no matches" result.
PYTHON="${SCRIPT_DIR}/../venv/bin/python3"
if [[ ! -x "$PYTHON" ]]; then
    PYTHON="$(command -v python3 || true)"
    if [[ -z "$PYTHON" ]]; then
        echo "search-archives-safe: python3 not found (need the venv or a system python3)." >&2
        exit 2
    fi
fi

# --- Build the resource-limit wrapper prefix --------------------------------
# Always: nice (CPU yield) + ionice (I/O yield) + timeout (hard kill).
LIMIT_PREFIX=(nice -n 19 ionice -c3 timeout "$SAS_TIMEOUT")

# Belt-and-braces: a per-run cgroup scope, if a user systemd instance is usable.
# This is the SAME systemd-run pattern the project already uses for sapphire
# compute — not a new mechanism. If unavailable we degrade to nice/ionice/timeout,
# which is still safe; we just lose the hard memory ceiling.
#
# NB: `systemctl is-system-running` exits NON-ZERO for "degraded" (one failed
# unit is enough) even though the manager is fully usable and systemd-run works.
# Test the STATE STRING, not the exit status, or a degraded-but-usable system
# silently loses the OOM ceiling this wrapper exists to provide. `|| true` keeps
# the non-zero exit from aborting under `set -e`.
CGROUP_PREFIX=()
_user_systemd_state="$(systemctl --user is-system-running 2>/dev/null || true)"
if [[ "$SAS_NO_CGROUP" != "1" ]] && command -v systemd-run >/dev/null 2>&1 \
        && [[ "$_user_systemd_state" == "running" || "$_user_systemd_state" == "degraded" ]]; then
    CGROUP_PREFIX=(systemd-run --user --scope --quiet
                   -p "MemoryMax=${SAS_MEMMAX}" -p "CPUQuota=${SAS_CPUQUOTA}")
    CGROUP_NOTE="cgroup MemoryMax=${SAS_MEMMAX} CPUQuota=${SAS_CPUQUOTA}"
else
    CGROUP_NOTE="cgroup unavailable — using nice/ionice/timeout only (still safe)"
fi

# --- engine invocation ------------------------------------------------------
# The Python engine streams each .gz line-by-line, applies a bounded regex with a
# per-line length guard, and prints path:lineno: matches. AND-filtering and
# context are handled inside the engine (no second process, no `tr`, no pipe).
# Optionals (and any EXTRA_ARGS flags) come first; then a literal `--` so that a
# PATTERN beginning with `-` (e.g. the very common `->`) is taken as the search
# pattern, not parsed as an option.
ENGINE_ARGS=("$ENGINE" -C "$SAS_CONTEXT" --max-line "$SAS_MAXLINE")
[[ -n "$AND_PATTERN" ]] && ENGINE_ARGS+=(--and "$AND_PATTERN")
ENGINE_ARGS+=("${EXTRA_ARGS[@]}")
ENGINE_ARGS+=(-- "$PATTERN" "$SEARCH_PATH")

echo "search-archives-safe: foreground search (do NOT relaunch if it seems slow)" >&2
echo "  pattern : $PATTERN${AND_PATTERN:+   --and: $AND_PATTERN}" >&2
echo "  path    : $SEARCH_PATH" >&2
echo "  limits  : nice 19, ionice idle, timeout ${SAS_TIMEOUT}s, $CGROUP_NOTE" >&2

# --- Run, holding a non-blocking lock so a second search cannot stack --------
# flock -n: if another search holds the lock, refuse immediately (exit 3) rather
# than queue or stack. This is the structural fix for the R1/R3 background
# pile-up that caused the crash.
exec 9>"$LOCKFILE"
if ! flock -n 9; then
    echo "search-archives-safe: REFUSED — another archive search is already running." >&2
    echo "  Wait for it to finish; do not stack searches (that is what crashed the machine)." >&2
    exit 3
fi

# Single bounded engine process, wrapped in the cgroup scope (if any) and the
# nice/ionice/timeout limits. No pipeline, no second process, no newline collapse.
"${CGROUP_PREFIX[@]}" "${LIMIT_PREFIX[@]}" "$PYTHON" "${ENGINE_ARGS[@]}"
