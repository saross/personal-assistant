#!/usr/bin/env python3
"""
SessionStart hook for Claude Code — memory retrieval and context injection.

Fires at the beginning of each session (startup, resume, clear, compact).
Reads the canonical memories.jsonl and injects relevant memories into
Claude's context via the additionalContext field.

Retrieval strategy (project-aware, tag-relevance-scored):
  Memories are split into same-project and other-project buckets.
  Same-project memories (including legacy memories with no project field)
  get more slots than other-project memories.

  Cross-project memories are ranked by tag overlap with the current
  project's tag profile — memories sharing tags with same-project
  memories are surfaced first, with recency as a tiebreaker. A per-
  project cap (MAX_OTHER_PROJECT_CAP) prevents any single project
  (notably map-reader-llm, which dominates the corpus) from filling
  all cross-project slots and drowning out other signal.

  Constraint spotlight (Phase 1b): error_mode and prompt_effectiveness
  memories get a dedicated retrieval pass and output section, separate
  from the general permanent slots. This prevents them being crowded
  out by the much larger decision/architecture pool. Constraints are
  scored by tag overlap across all projects (no project boundary).

  Middle-aged bucket (2026-04-24): gotcha and pattern categories are
  documented as 180-day decay but were previously ephemeral (only
  recent-bucket visibility). They now get their own 7-to-180-day
  window so hard-won lessons don't vanish after a week.

  Slot allocation (68 total, revised 2026-04-24 to reduce Opus 4.7
  confabulation-gravity from high-volume decision/architecture pool):
    Same-project:  25 recent + 20 permanent         = 45
    Other-project:  5 recent +  8 permanent         = 13
    Middle-aged:   10 (gotcha + pattern, 7–180d)   = 10
    Constraints:   10 (error_mode + prompt_effectiveness) = 10

Note: commitment and waiting_for items are excluded — they duplicate
the Task Status banner from the accountability hook.
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Shared project-id encoder. Both this hook (which derives the id from
# cwd to filter memories) and the extraction hook (which writes the id
# into the ``project`` field) MUST agree byte-for-byte. Centralised in
# scripts/project_id.py to prevent the two from drifting (audit IC3,
# C-C4, C-X3).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from project_id import encode_project_id  # noqa: E402
import digest as digest_selector  # noqa: E402  (pure Vector 2 selector)

# ============================================================================
# Configuration
# ============================================================================

PA_DIR = Path.home() / "personal-assistant"
MEMORIES_FILE = PA_DIR / "memories" / "memories.jsonl"
SCRATCHPAD_FILE = PA_DIR / "data" / "scratchpad.md"
SCRATCHPADS_DIR = PA_DIR / "data" / "scratchpads"

# ----------------------------------------------------------------------------
# Vector 2 — session-start digest (Stage 1) flag, default OFF.
#
# When enabled, main() emits the compact ≤1,500 B digest (scripts/digest.py)
# in place of the four-bucket recall dump. Gating is MACHINE-LOCAL by
# design: the rollout is amd-tower only (design §8), and `data/` is a
# submodule synced to zbook + rpi-server, so the signal must NOT live in
# the repo or it would propagate. Precedence:
#   1. env var PA_DIGEST_STAGE1 (truthy → on, falsy → off; overrides both
#      directions — used for testing / per-session override),
#   2. else the machine-local sentinel file ~/.pa-digest-stage1 exists → on,
#   3. else OFF (legacy four-bucket hook).
# Rollback is `rm ~/.pa-digest-stage1` or `PA_DIGEST_STAGE1=0`.
DIGEST_FLAG_ENV = "PA_DIGEST_STAGE1"
DIGEST_SENTINEL = Path.home() / ".pa-digest-stage1"
DIGEST_LOG = PA_DIR / "data" / "logs" / "digest.log"
# Truthy / falsy spellings accepted from the env override (case-insensitive).
_TRUTHY = {"1", "true", "on", "yes"}
_FALSY = {"0", "false", "off", "no", ""}

# ----------------------------------------------------------------------------
# Vector 2b — scratchpad load-path byte budget (design wiki/planning/
# vector-2b-design.md). After Vector 2 digested the recall dump to ~1.5 KB,
# the ~15.5 KB scratchpad became the dominant session-start payload term.
#
# Two independent mechanisms, both byte-based:
#   1. A byte WARN (always on) — nudges `/retro` distillation, the human,
#      principle-preserving lever. Replaces the old line-based warn, which
#      never fired (the 29 KB bloat lived in ~99 long lines, not >150 lines).
#   2. A byte BUDGET (flag-gated) — a regrowth guard-rail. When the Vector 2b
#      flag is ON, the scratchpad content is passed through
#      digest.cap_markdown_to_budget() (whole `##` sections only, never split,
#      visible trim marker). Under Fork A (guard-rail) the budgets sit ABOVE
#      the current sizes, so nothing is trimmed today — the cap only bites on
#      silent regrowth.
#
# Flag gating mirrors the Vector 2 PASS 2 pattern EXACTLY and for the same
# reason: the scratchpad is injected in BOTH hook modes, and the Vector 2 §8
# observation window is live on amd-tower (review booked 2026-06-13). A
# separate machine-local flag (default OFF → byte-identical output) keeps that
# window unconfounded and earns Vector 2b its own observation window.
# Precedence: env PA_SCRATCHPAD_BUDGET (truthy/falsy) → sentinel
# ~/.pa-scratchpad-budget → OFF. Neither lives in the synced `data/` submodule.
# Warn thresholds sit ABOVE the clean post-distillation floor and BELOW the
# trim budget, so the warn is a "approaching the cap, distil soon" nudge that
# fires only on genuine REGROWTH — not a perpetual nag for a distillation that
# was already done at zero principle loss (global floor 15,484 B on 2026-05-30;
# largest per-project map-reader 5,134 B). See vector-2b-design.md §8b.
SCRATCHPAD_WARN_BYTES = 17_000  # 15.5 KB floor < warn < 18 KB budget
PROJECT_SCRATCHPAD_WARN_BYTES = 7_000  # 5.1 KB floor < warn < 8 KB budget
SCRATCHPAD_BUDGET_BYTES = 18_000  # Fork A guard-rail — above today's 15,484 B
PROJECT_SCRATCHPAD_BUDGET_BYTES = 8_000  # above the largest (map-reader 5,134 B)
SCRATCHPAD_FLAG_ENV = "PA_SCRATCHPAD_BUDGET"
SCRATCHPAD_SENTINEL = Path.home() / ".pa-scratchpad-budget"

# ----------------------------------------------------------------------------
# Vector 2c — focus-aware + project-scoped digest selection (design wiki/
# planning/vector-2c-design.md). Two changes to the digest's verified-entry
# selection, behind ONE machine-local flag (default OFF → byte-identical to
# the Vector 2 digest, so the live §8 window — review 2026-06-13 — stays
# unconfounded; enable after that review by `touch ~/.pa-digest-focus`):
#   1. Focus-aware ranking — the active FOCUS.md slot projects become the
#      primary ranking key, so the digest surfaces focus-relevant verified
#      entries rather than recency-random ones (Option 3: ranking + a thin
#      legibility label, NOT a redundant focus block — the `# Task Status`
#      hook already prints the slots).
#   2. Hard project scope — in a project repo the verified/fallback pools are
#      filtered to that project; the personal-assistant hub is exempt (the
#      hub nulls current_project for cross-project visibility, so scope is
#      None there and focus ranking does the cross-project prioritisation).
# Precedence mirrors the other two flags exactly: env PA_DIGEST_FOCUS
# (truthy/falsy) → sentinel ~/.pa-digest-focus → OFF. Neither lives in the
# synced `data/` submodule.
FOCUS_FLAG_ENV = "PA_DIGEST_FOCUS"
FOCUS_SENTINEL = Path.home() / ".pa-digest-focus"
FOCUS_FILE = PA_DIR / "tasks" / "FOCUS.md"

# How many days of recent memories to include
RECENT_DAYS = 14

# How far back the middle-aged bucket reaches (matches the documented
# 180-day decay for gotcha/pattern in memory-system-reference.md)
MIDDLE_AGED_DAYS = 180

# High-value permanent categories (always included regardless of age)
# Must match all categories marked "permanent" in CLAUDE.md
PERMANENT_CATEGORIES = {
    # Research Methodology
    "methodology",
    "ethics",
    "provenance",
    "hypothesis",
    "limitation",
    "openness",
    "source_insight",
    # LLM Interaction Research (error_mode and prompt_effectiveness
    # excluded — they flow through retrieve_constraints() exclusively)
    "surprise",
    "self_reflection",
    # Project / Architecture
    "decision",
    "architecture",
    # GTD (contact is permanent)
    "contact",
    # Retrospective (permanent categories only)
    "slip",
    "blocker_excuse",
    # System Adaptation (permanent only)
    "system_evolution",
}

# Project-aware slot allocation (tag-relevance-scored for cross-project).
# Reduced 2026-04-24 from 35/15 to 20/8 to cut confabulation-gravity
# from the high-volume decision/architecture pool — Opus 4.7 welds
# together adjacent fragments when too many specific identifiers sit
# in context at once.
MAX_RECENT_SAME = 25
MAX_RECENT_OTHER = 5
MAX_PERMANENT_SAME = 20
MAX_PERMANENT_OTHER = 8

# Per-project cap on cross-project slots. With map-reader-llm holding
# ~38% of the entire memory corpus, tag-relevance scoring alone lets
# it dominate other-project retrieval. Cap prevents any single foreign
# project from filling more than this many cross-project slots in
# either the recent or permanent bucket.
MAX_OTHER_PROJECT_CAP = 3

# Middle-aged bucket — gotcha and pattern categories are documented
# as 180-day decay but were previously ephemeral (visible only in the
# 7-day recent window). They now get their own 7–180-day bucket so
# hard-won lessons don't silently vanish after a week.
MIDDLE_AGED_CATEGORIES = {"gotcha", "pattern"}
MAX_MIDDLE_AGED = 10

# Constraint spotlight — dedicated slots for error_mode/prompt_effectiveness
# These categories are high-value for preventing repeated mistakes and
# applying proven techniques, but get outnumbered by decisions/architecture
# in the permanent slots. Dedicated retrieval guarantees visibility.
CONSTRAINT_CATEGORIES = {"error_mode", "prompt_effectiveness"}
MAX_CONSTRAINTS = 10

# Audit C-C3 (2026-05-02): the canonical ``memories.jsonl`` is
# append-only with newest records at (broadly) the bottom; the file
# is not strictly date-monotonic because of backfills, but newest
# records are always appended at the end. Previously we read the
# whole file into RAM via ``read_text().splitlines()``; on a slow
# disk this could push the 10-second hook timeout, and the failure
# mode was silent (truncated stdout, no signal).
#
# Fix: stream the file backwards, decoding one line at a time, and
# stop after ``MAX_LOAD_RECORDS`` records. The cap must be generous
# enough to cover the full retrieval window — recent (14d), middle-
# aged (180d), and permanent (any age) — so it is sized well above
# the current corpus (~24k records / ~310 records/day at audit
# time, i.e. ~75 days). 50000 records is ~160 days at present
# growth rate; the corpus today fits entirely inside the cap with
# ~2× headroom, while bounding worst-case load under future
# growth.
MAX_LOAD_RECORDS = 50000

# How large a chunk to read when streaming the file backwards. Sized
# to comfortably hold a few hundred lines of typical memory records
# (~700 bytes/line). Tuned for I/O efficiency, not correctness — any
# value works.
REVERSE_READ_CHUNK_BYTES = 64 * 1024

# ============================================================================
# Memory Loading
# ============================================================================


# Module-level diagnostics surfaced at end of main() so silent drops are
# visible. Audit 2026-05-02 (C-M6, C-M7): per-line failures used to be
# swallowed without any signal — a future bug in extraction or a
# truncated write would silently strip memories from retrieval.
_load_stats: dict = {
    "json_decode_errors": 0,
    "json_decode_first_line": None,  # 1-indexed line number of first failure
    # Track unique memory records that produced a bad timestamp; using a
    # set keyed on id() keeps the count honest even though parse_created_at
    # is called many times per record across the retrieval passes.
    "bad_timestamp_ids": set(),
    "bad_timestamp_first_marker": None,  # id (or summary excerpt) of first
}


def _iter_lines_reverse(path: Path, chunk_size: int = REVERSE_READ_CHUNK_BYTES):
    """Yield ``(line_number, line_bytes)`` from ``path`` in reverse order.

    Streams the file from the end, reading ``chunk_size`` bytes at a
    time, and yields each line newest-first along with its 1-indexed
    line number (where line 1 is the first line of the file). The
    decoder for the line text is left to the caller so errors can be
    routed through the existing ``_load_stats`` counters.

    Why backwards: ``memories.jsonl`` is append-only with newest
    records at the bottom. Reading newest-first lets retrieval cap the
    scan at ``MAX_LOAD_RECORDS`` while still seeing the most relevant
    records — see C-C3 in reports/audit-2026-05-02/cluster-C-hooks.md.

    The implementation is adapted from the well-known stdlib pattern
    (the ``file_read_backwards`` recipe). It tolerates files that do
    not end with a trailing newline.
    """
    with path.open("rb") as fh:
        fh.seek(0, 2)  # End of file
        total_size = fh.tell()
        # First pass: count newlines to derive the 1-indexed line number
        # of the *last* line. Cheaper than a second seek-and-count
        # because we already need to read the bytes.
        # We accumulate line numbers from the bottom up: start at the
        # total newline count, decrement as we yield.
        # Avoid an extra full-file scan by counting newlines lazily as
        # we walk backwards through chunks — initial line_no is the
        # 1-indexed position of the final non-empty line, which equals
        # the count of '\n' bytes if the file ends with '\n', else
        # count('\n') + 1.
        # Compute the total newline count up front in a streaming pass
        # — this keeps the logic correct even when the trailing line
        # has no newline.
        fh.seek(0)
        newline_count = 0
        while True:
            buf = fh.read(chunk_size)
            if not buf:
                break
            newline_count += buf.count(b"\n")
        # Determine the 1-indexed line number of the last record.
        # If file ends with a newline, the final line is newline_count;
        # otherwise it is newline_count + 1 (the unterminated tail).
        fh.seek(max(total_size - 1, 0))
        ends_with_newline = total_size > 0 and fh.read(1) == b"\n"
        last_line_no = newline_count if ends_with_newline else newline_count + 1

        # Now walk backwards.
        position = total_size
        leftover = b""
        current_line_no = last_line_no
        while position > 0:
            read_size = min(chunk_size, position)
            position -= read_size
            fh.seek(position)
            chunk = fh.read(read_size) + leftover
            # If we are not at the very start, the first fragment in
            # this chunk may be a partial line — defer it to the next
            # iteration by stashing it in ``leftover``.
            if position > 0:
                first_nl = chunk.find(b"\n")
                if first_nl == -1:
                    leftover = chunk
                    continue
                leftover = chunk[: first_nl + 1]
                rest = chunk[first_nl + 1:]
            else:
                leftover = b""
                rest = chunk
            # Split ``rest`` into lines, preserving order. The trailing
            # newline (if any) yields an empty final element which we
            # skip.
            lines = rest.split(b"\n")
            if lines and lines[-1] == b"":
                lines = lines[:-1]
            # Yield newest-first.
            for line in reversed(lines):
                yield current_line_no, line
                current_line_no -= 1
        # Emit any remaining leftover (the very first line of the file
        # when no further chunks remain).
        if leftover:
            tail = leftover
            if tail.endswith(b"\n"):
                tail = tail[:-1]
            if tail:
                yield current_line_no, tail


def load_all_memories(max_records: int = MAX_LOAD_RECORDS) -> list[dict]:
    """Load up to ``max_records`` memories, newest-first.

    Audit C-C3 (2026-05-02): the previous implementation called
    ``MEMORIES_FILE.read_text().splitlines()`` which materialises the
    whole 23k-line / ~19 MB file plus a list of decoded strings on
    every session start, against a 10-second hook timeout. We now
    stream the file backwards (newest-first) and stop after
    ``max_records`` successfully-decoded records, bounding the load
    irrespective of corpus growth.

    Per-line ``JSONDecodeError``s are counted (not raised) so a single
    truncated line does not block session start, but the count and the
    first offending line number are surfaced via stderr at the end of
    ``main()`` so the failure is visible. The diagnostics from Batch 1
    (``_load_stats``, ``_record_bad_timestamp``) continue to be called
    per-line.

    Returned list is sorted oldest-first to preserve the prior
    behaviour expected by callers: the retrieval functions sort by
    ``_sort_key`` themselves, but list order otherwise was historically
    file-order.
    """
    if not MEMORIES_FILE.exists():
        return []

    memories: list[dict] = []
    try:
        iterator = _iter_lines_reverse(MEMORIES_FILE)
        for line_num, raw in iterator:
            if len(memories) >= max_records:
                break
            try:
                line = raw.decode("utf-8").strip()
            except UnicodeDecodeError:
                # Treat decode failure the same as a JSON decode
                # failure — count it and move on. Surfacing happens
                # via the same end-of-main() summary.
                _load_stats["json_decode_errors"] += 1
                if _load_stats["json_decode_first_line"] is None:
                    _load_stats["json_decode_first_line"] = line_num
                continue
            if not line:
                continue
            try:
                memories.append(json.loads(line))
            except json.JSONDecodeError:
                # Audit C-M7: count and remember the first offending
                # line so the end-of-main() summary can point at the
                # corruption.
                _load_stats["json_decode_errors"] += 1
                if _load_stats["json_decode_first_line"] is None:
                    _load_stats["json_decode_first_line"] = line_num
                continue
    except OSError as exc:
        # Permission errors, disk failures, etc. — surface and return
        # what we have rather than crashing the hook (audit C-L9).
        print(
            f"[retrieval] WARN: failed to read {MEMORIES_FILE}: {exc}",
            file=sys.stderr,
        )
        return memories

    # Reverse so callers see oldest-first, matching prior behaviour.
    memories.reverse()
    return memories


def _record_bad_timestamp(mem: dict) -> None:
    """Record a memory whose created_at could not be parsed.

    Called from `parse_created_at` on every failure path. Deduplicates
    by Python `id()` so multiple retrieval passes over the same dict do
    not inflate the count.
    """
    marker = id(mem)
    if marker in _load_stats["bad_timestamp_ids"]:
        return
    _load_stats["bad_timestamp_ids"].add(marker)
    if _load_stats["bad_timestamp_first_marker"] is None:
        _load_stats["bad_timestamp_first_marker"] = (
            mem.get("id") or (mem.get("summary") or "")[:60] or "<no id>"
        )


def parse_created_at(mem: dict) -> datetime | None:
    """Parse the created_at timestamp from a memory record.

    Always returns a tz-aware datetime (assumes UTC if the stored string
    has no timezone) so callers can compare against tz-aware cutoffs
    without TypeError.

    Returns None on a missing or unparseable timestamp; per-record
    failures are de-duplicated and counted so the end-of-main() summary
    can surface silent drops (audit C-M6).
    """
    ts = mem.get("created_at", "")
    if not ts:
        _record_bad_timestamp(mem)
        return None
    try:
        # Handle both Z suffix and +00:00 format
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        _record_bad_timestamp(mem)
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def derive_project(cwd: str) -> str | None:
    """
    Derive the project identifier from the current working directory.

    Thin wrapper over :func:`scripts.project_id.encode_project_id` —
    keeps the call sites in this module untouched while routing the
    encoding through the shared helper. Both writers (the extraction
    hook) and readers (this hook) reference the same source of truth
    so they cannot drift (audit IC3).
    """
    return encode_project_id(cwd)


def is_same_project(mem: dict, current_project: str | None) -> bool:
    """
    Determine whether a memory belongs to the current project.

    Memories without a project field (legacy, pre-project-tagging)
    are treated as same-project to avoid penalising existing memories.
    """
    mem_project = mem.get("project")
    # No project field → legacy memory → treat as same-project
    if not mem_project:
        return True
    # No current project known → treat everything as same-project
    if not current_project:
        return True
    return mem_project == current_project


def collect_project_tags(
    memories: list[dict],
    current_project: str | None,
) -> set[str]:
    """
    Collect all tags from same-project memories to build a relevance profile.

    Used for scoring cross-project memories by tag overlap — memories
    sharing tags with the current project's corpus are more likely to
    be relevant even though they belong to a different project.
    """
    tags: set[str] = set()
    for mem in memories:
        if not is_same_project(mem, current_project):
            continue
        mem_tags = mem.get("research_tags") or []
        if isinstance(mem_tags, str):
            mem_tags = [mem_tags]
        tags.update(str(t).lower() for t in mem_tags)
    return tags


def tag_overlap_score(mem: dict, project_tags: set[str]) -> int:
    """
    Score a memory by how many of its tags overlap with the project tag set.

    Returns the count of overlapping tags. Zero means no tag relevance
    to the current project. When project_tags is empty, always returns 0
    (falls back to recency-only sorting).
    """
    if not project_tags:
        return 0
    mem_tags = mem.get("research_tags") or []
    if isinstance(mem_tags, str):
        mem_tags = [mem_tags]
    mem_tag_set = {str(t).lower() for t in mem_tags}
    return len(mem_tag_set & project_tags)


def apply_per_project_cap(
    memories: list[dict],
    limit: int,
    cap: int = MAX_OTHER_PROJECT_CAP,
) -> list[dict]:
    """
    Take the top ``limit`` memories while capping contributions from any
    single project at ``cap`` entries.

    The input list is assumed to be pre-sorted in desired preference order
    (e.g., by tag overlap then recency). Memories without a project field
    are treated as a single bucket keyed on None — they share the cap with
    each other.

    Prevents one high-volume foreign project from crowding out signal from
    smaller projects in the cross-project slot allocation.
    """
    counts: dict[str | None, int] = {}
    taken: list[dict] = []
    for mem in memories:
        if len(taken) >= limit:
            break
        project = mem.get("project") or None
        if counts.get(project, 0) >= cap:
            continue
        taken.append(mem)
        counts[project] = counts.get(project, 0) + 1
    return taken


# ============================================================================
# Retrieval Logic
# ============================================================================


def _sort_key(mem: dict) -> datetime:
    """Return parsed datetime for sorting; epoch for unparseable timestamps.

    Defence-in-depth: writers (extraction-hook, reprocess-sessions) all
    emit full ISO-8601 timestamps now (audit IC4 fix in batch 4), so
    the ``datetime.min`` substitution should be unreachable on records
    written after that batch landed. The fallback is kept to absorb
    legacy malformed records still on disk and any future writer that
    forgets to use scripts/_timestamps.now_iso.
    """
    return parse_created_at(mem) or datetime.min.replace(tzinfo=timezone.utc)


def retrieve_recent(
    memories: list[dict],
    cutoff: datetime,
    current_project: str | None,
    project_tags: set[str] | None = None,
) -> list[dict]:
    """
    Get memories from the last N days, split by project affinity.

    Same-project memories (including legacy) get MAX_RECENT_SAME slots.
    Other-project memories get MAX_RECENT_OTHER slots, ranked by tag
    overlap with the current project's tag profile (recency as tiebreaker).
    Returns the merged list, sorted most-recent first.
    """
    same = []
    other = []

    # Exclude commitment/waiting_for — they duplicate the Task Status
    # banner from the accountability hook.
    excluded_categories = {"commitment", "waiting_for"}

    for mem in memories:
        created = parse_created_at(mem)
        if not created or created < cutoff:
            continue
        if mem.get("category") in excluded_categories:
            continue
        if is_same_project(mem, current_project):
            same.append(mem)
        else:
            other.append(mem)

    same.sort(key=_sort_key, reverse=True)

    # Cross-project: prefer tag-relevant memories, recency as tiebreaker
    _tags = project_tags or set()
    other.sort(
        key=lambda m: (tag_overlap_score(m, _tags), _sort_key(m)),
        reverse=True,
    )

    # Per-project cap prevents a single foreign project (e.g. map-reader-llm,
    # which dominates the corpus) from filling all cross-project slots.
    other_take = apply_per_project_cap(other, MAX_RECENT_OTHER)
    # Let same-project absorb unused other-project slots (and vice versa)
    # so total capacity is preserved when one bucket is underutilised
    same_limit = MAX_RECENT_SAME + (MAX_RECENT_OTHER - len(other_take))
    merged = same[:same_limit] + other_take
    merged.sort(key=_sort_key, reverse=True)
    return merged


def retrieve_permanent(
    memories: list[dict],
    recent_ids: set[str],
    current_project: str | None,
    project_tags: set[str] | None = None,
) -> list[dict]:
    """
    Get permanent high-value memories not already in the recent list,
    split by project affinity.

    Same-project memories get MAX_PERMANENT_SAME slots.
    Other-project memories get MAX_PERMANENT_OTHER slots, ranked by
    tag overlap with the current project (recency as tiebreaker).
    Unused other-project slots overflow to same-project.
    """
    same = []
    other = []

    for mem in memories:
        if mem.get("category") not in PERMANENT_CATEGORIES:
            continue
        if mem.get("id") in recent_ids:
            continue
        if is_same_project(mem, current_project):
            same.append(mem)
        else:
            other.append(mem)

    same.sort(key=_sort_key, reverse=True)

    # Cross-project: prefer tag-relevant memories, recency as tiebreaker
    _tags = project_tags or set()
    other.sort(
        key=lambda m: (tag_overlap_score(m, _tags), _sort_key(m)),
        reverse=True,
    )

    other_take = apply_per_project_cap(other, MAX_PERMANENT_OTHER)
    same_limit = MAX_PERMANENT_SAME + (MAX_PERMANENT_OTHER - len(other_take))
    merged = same[:same_limit] + other_take
    merged.sort(key=_sort_key, reverse=True)
    return merged


def retrieve_middle_aged(
    memories: list[dict],
    already_ids: set[str],
    current_project: str | None,
    project_tags: set[str] | None = None,
) -> list[dict]:
    """
    Retrieve gotcha and pattern memories aged 7–180 days.

    Documented decay for these categories is 180 days, but the
    recent-only retrieval logic (and their exclusion from
    PERMANENT_CATEGORIES) made them invisible after 7 days in practice.
    This restores the documented tenure.

    Filters:
    - Category in MIDDLE_AGED_CATEGORIES
    - Age strictly older than RECENT_DAYS (to avoid duplication with the
      recent bucket) and no older than MIDDLE_AGED_DAYS
    - Not already in ``already_ids`` (usually the recent bucket's ids)

    Scoring: same-project first, then cross-project ordered by tag
    overlap with recency as tiebreaker. Per-project cap applied to
    the cross-project portion.
    """
    now = datetime.now(timezone.utc)
    lower = now - timedelta(days=MIDDLE_AGED_DAYS)
    upper = now - timedelta(days=RECENT_DAYS)

    same = []
    other = []
    for mem in memories:
        if mem.get("category") not in MIDDLE_AGED_CATEGORIES:
            continue
        if mem.get("id") in already_ids:
            continue
        created = parse_created_at(mem)
        if not created:
            continue
        # Strictly older than recent window, within 180-day decay
        if created >= upper or created < lower:
            continue
        if is_same_project(mem, current_project):
            same.append(mem)
        else:
            other.append(mem)

    _tags = project_tags or set()
    same.sort(key=_sort_key, reverse=True)
    other.sort(
        key=lambda m: (tag_overlap_score(m, _tags), _sort_key(m)),
        reverse=True,
    )

    # 70/30 split of the budget between same and cross-project, with
    # unused slots on either side overflowing to the other bucket
    same_quota = (MAX_MIDDLE_AGED * 7 + 9) // 10  # ceil of 0.7
    other_quota = MAX_MIDDLE_AGED - same_quota
    same_take = same[:same_quota]
    other_take = apply_per_project_cap(other, other_quota)
    # Overflow unused slots
    shortfall = (same_quota - len(same_take)) + (other_quota - len(other_take))
    if shortfall > 0:
        remaining_same = same[len(same_take):]
        remaining_other = [
            m for m in other if m not in other_take
        ]
        extras = remaining_same[:shortfall]
        still_short = shortfall - len(extras)
        if still_short > 0:
            extras += apply_per_project_cap(remaining_other, still_short)
        same_take = same_take + extras

    merged = same_take + other_take
    merged.sort(key=_sort_key, reverse=True)
    return merged


def retrieve_constraints(
    memories: list[dict],
    already_ids: set[str],
    current_project: str | None,
    project_tags: set[str] | None = None,
) -> list[dict]:
    """
    Retrieve constraint-type memories for the dedicated spotlight section.

    Constraints (error_mode, prompt_effectiveness) are cross-cutting —
    a fieldmark API validation error_mode is relevant when working on
    the paper if both share the 'validation' tag. Unlike retrieve_permanent,
    there is no same-project/other-project split; all constraint memories
    are scored uniformly by tag relevance regardless of origin project.

    Args:
        memories: Full list of loaded memories.
        already_ids: IDs already selected by recent retrieval
            (excluded to avoid duplication).
        current_project: Derived project identifier from cwd.
        project_tags: Tag profile from same-project memories.

    Returns:
        Up to MAX_CONSTRAINTS constraint memories, ranked by tag overlap
        then recency.
    """
    _tags = project_tags or set()
    candidates = []

    for mem in memories:
        if mem.get("category") not in CONSTRAINT_CATEGORIES:
            continue
        if mem.get("id") in already_ids:
            continue
        candidates.append(mem)

    # Score by tag overlap (cross-cutting, ignores project boundary),
    # then recency as tiebreaker
    candidates.sort(
        key=lambda m: (tag_overlap_score(m, _tags), _sort_key(m)),
        reverse=True,
    )

    # Per-project cap — map-reader-llm has the largest constraint pool
    # (~500+ error_mode entries). Without the cap it floods the spotlight.
    # Same-project constraints get no cap (you always want your own
    # project's constraints); cap applies to foreign projects.
    same = [m for m in candidates if is_same_project(m, current_project)]
    other = [m for m in candidates if not is_same_project(m, current_project)]
    capped_other = apply_per_project_cap(other, MAX_CONSTRAINTS)
    merged = same + capped_other
    # Re-rank merged by original score ordering
    score = {id(m): i for i, m in enumerate(candidates)}
    merged.sort(key=lambda m: score.get(id(m), 1_000_000))
    return merged[:MAX_CONSTRAINTS]


# ============================================================================
# Formatting
# ============================================================================


# Audit C-M12 (2026-05-02): pre-summary-extraction memories have no
# ``summary`` field, so ``format_memory`` falls back to the full
# ``content``. Some legacy records carry multi-thousand-character
# content fields; up to 68 such memories per session would otherwise
# expand the additionalContext payload by hundreds of kilobytes and
# re-introduce the fragment-welding surface the compact Level-1 format
# was designed to remove. Cap the fallback at 300 characters with an
# explicit truncation marker so the user (and Claude) can see the
# truncation rather than mistaking the prefix for the whole memory.
CONTENT_FALLBACK_MAX_CHARS = 300


def format_memory(mem: dict) -> str:
    """
    Format a single memory as a compact Level 1 index entry.

    Compact format prioritises content-first reading flow:
    ``[category] summary | tag1, tag2 [YYYY-MM-DD]``

    Confidence is omitted (available via ``/recall``).

    When the memory has no ``summary`` field we fall back to
    ``content``, but truncate to :data:`CONTENT_FALLBACK_MAX_CHARS`
    with a visible ``…[truncated]`` marker (audit C-M12). Memories
    whose ``summary`` is present are emitted in full — summaries are
    already bounded by the extraction hook.
    """
    category = mem.get("category", "unknown")
    summary = mem.get("summary")
    if summary:
        # Summaries are already bounded by the extraction hook —
        # emit verbatim.
        content = summary
    else:
        raw_content = mem.get("content", "") or ""
        if len(raw_content) > CONTENT_FALLBACK_MAX_CHARS:
            content = (
                raw_content[:CONTENT_FALLBACK_MAX_CHARS].rstrip()
                + "… [truncated; use /recall for full content]"
            )
        else:
            content = raw_content
    tags = mem.get("research_tags") or []
    if isinstance(tags, str):
        tags = [tags]
    created = (mem.get("created_at") or "")[:10]  # Just the date

    line = f"[{category}] {content}"
    if tags:
        line += f" | {', '.join(str(t) for t in tags)}"
    if created:
        line += f" [{created}]"

    return line


def format_context(
    recent: list[dict],
    permanent: list[dict],
    constraints: list[dict] | None = None,
    middle_aged: list[dict] | None = None,
) -> str:
    """Format all retrieved memories into a context string."""
    sections = []

    if recent:
        lines = [format_memory(m) for m in recent]
        sections.append(
            f"## Recent Memories (last {RECENT_DAYS} days) \u2014 {len(recent)} {'item' if len(recent) == 1 else 'items'}\n"
            + "\n".join(f"- {entry}" for entry in lines)
        )

    if constraints:
        lines = [format_memory(m) for m in constraints]
        sections.append(
            f"## Relevant Constraints \u2014 {len(constraints)} {'item' if len(constraints) == 1 else 'items'}\n"
            + "\n".join(f"- {entry}" for entry in lines)
        )

    if middle_aged:
        lines = [format_memory(m) for m in middle_aged]
        sections.append(
            f"## Gotchas & Patterns ({RECENT_DAYS}\u2013{MIDDLE_AGED_DAYS} days) \u2014 {len(middle_aged)} {'item' if len(middle_aged) == 1 else 'items'}\n"
            + "\n".join(f"- {entry}" for entry in lines)
        )

    if permanent:
        lines = [format_memory(m) for m in permanent]
        sections.append(
            f"## Key Decisions & Knowledge \u2014 {len(permanent)} {'item' if len(permanent) == 1 else 'items'}\n"
            + "\n".join(f"- {entry}" for entry in lines)
        )

    if not sections:
        return ""

    # Tier 2 autonomous retrieval instructions — tells CC how and
    # when to fetch full memory content mid-conversation.
    sections.append(
        "## Retrieval Instructions\n\n"
        "The summaries above are a compact index. When the "
        "conversation touches a topic matching tags in this "
        "index, you should retrieve full memory content.\n\n"
        "**How to fetch:**\n\n"
        "```bash\n"
        "python3 ~/personal-assistant/scripts/fetch-memories.py "
        "--tag <tag-name>\n"
        "python3 ~/personal-assistant/scripts/fetch-memories.py "
        "--query \"search terms\"\n"
        "python3 ~/personal-assistant/scripts/fetch-memories.py "
        "--category decision --query \"topic\"\n"
        "```\n\n"
        "**Protocol:**\n\n"
        "1. When you recognise a topic match, announce: "
        "\"I have memories about [topic] — shall I retrieve "
        "the details?\"\n"
        "2. Wait for user confirmation before running the "
        "fetch command.\n"
        "3. Run the script via Bash and incorporate the results "
        "into your response.\n\n"
        "**When NOT to fetch:**\n\n"
        "- Trivial or passing mentions of a topic\n"
        "- Topics where full content has already been retrieved "
        "this session\n"
        "- When the user is focused on an unrelated task and "
        "the match is tangential\n"
        "- When the user has not confirmed after your "
        "announcement\n\n"
        "**Manual alternative:** The user can also invoke "
        "`/recall [query]` directly at any time."
    )

    header = (
        "# Memory Context\n\n"
        "The following memories were retrieved from previous sessions.\n"
        "Use `/recall [query]` to retrieve full memory content "
        "when a topic needs deeper context.\n\n"
        "**Anti-confabulation:** these entries are pointers, not "
        "authorities. Any specific number, filename, path, "
        "identifier, commit hash, config value, or quoted text "
        "cited in a memory is frozen at write-time and may be "
        "stale. Before citing any such specific to Shawn, re-read "
        "the source file. If you cannot re-verify within the turn, "
        "say \"I'd need to re-read X to be sure\" rather than "
        "guess — even when the summary feels sufficient.\n\n"
    )
    return header + "\n\n".join(sections)


# ============================================================================
# Scratchpad
# ============================================================================


def load_scratchpad() -> str:
    """
    Load the global scratchpad file for context injection.

    Returns the file contents as a string, or empty string if the file
    does not exist or is empty.

    Vector 2b: warns to stderr when the file exceeds SCRATCHPAD_WARN_BYTES
    (byte-based — the old line-based warn never fired at 29 KB / 99 lines),
    and, when the Vector 2b flag is enabled, caps the content to
    SCRATCHPAD_BUDGET_BYTES via the shared section-aware primitive. Under
    Fork A the budget sits above the current size, so the cap is a regrowth
    backstop and does not trim today; the returned content is byte-identical
    to the file whenever nothing is dropped.
    """
    if not SCRATCHPAD_FILE.exists():
        return ""

    content = SCRATCHPAD_FILE.read_text().strip()
    if not content:
        return ""

    byte_count = len(content.encode("utf-8"))
    if byte_count > SCRATCHPAD_WARN_BYTES:
        print(
            f"[scratchpad] {byte_count} bytes — consider running /retro "
            f"to distil (threshold: {SCRATCHPAD_WARN_BYTES})",
            file=sys.stderr,
        )

    if scratchpad_budget_enabled():
        content, trimmed = digest_selector.cap_markdown_to_budget(
            content, SCRATCHPAD_BUDGET_BYTES
        )
        if trimmed:
            print(
                f"[scratchpad] trimmed to byte budget "
                f"({SCRATCHPAD_BUDGET_BYTES} B) — run /retro to distil",
                file=sys.stderr,
            )

    return content


def load_project_scratchpad(cwd: str) -> tuple[str, Path | None]:
    """
    Load a per-project scratchpad keyed on the basename of the cwd.

    Per-project scratchpads live in ``data/scratchpads/<project>.md``
    and are loaded only when ``Path(cwd).name`` matches the file stem.
    This keeps project-specific identifiers (paths, config values,
    experiment IDs) out of every session's context, reducing the
    fragment-welding that drives Opus 4.7 confabulation.

    Returns (content, path_used). Content is the empty string when no
    matching file exists or the file is empty. The path is returned so
    the caller can include it in the injected context header.
    """
    if not cwd:
        return "", None
    name = Path(cwd).name
    if not name:
        return "", None
    path = SCRATCHPADS_DIR / f"{name}.md"
    if not path.exists():
        return "", None
    content = path.read_text().strip()
    if not content:
        return "", None

    # Vector 2b: byte-warn + flag-gated cap on its own (smaller) budget.
    # Per-project files are already relevance-gated by cwd, so their budget
    # is generous; the cap is purely a regrowth backstop.
    byte_count = len(content.encode("utf-8"))
    if byte_count > PROJECT_SCRATCHPAD_WARN_BYTES:
        print(
            f"[scratchpad:{name}] {byte_count} bytes — consider running "
            f"/retro to distil (threshold: {PROJECT_SCRATCHPAD_WARN_BYTES})",
            file=sys.stderr,
        )

    if scratchpad_budget_enabled():
        content, trimmed = digest_selector.cap_markdown_to_budget(
            content, PROJECT_SCRATCHPAD_BUDGET_BYTES
        )
        if trimmed:
            print(
                f"[scratchpad:{name}] trimmed to byte budget "
                f"({PROJECT_SCRATCHPAD_BUDGET_BYTES} B) — run /retro to distil",
                file=sys.stderr,
            )

    return content, path


# ============================================================================
# Main
# ============================================================================


def _emit_load_diagnostics() -> None:
    """Print a single-line stderr summary if any silent drops occurred.

    Audit C-M6 / C-M7: previously, JSON parse failures and unparseable
    timestamps were swallowed without any signal. This makes those
    failure modes visible without flooding stderr in the happy path.
    """
    json_errors = _load_stats["json_decode_errors"]
    bad_ts = len(_load_stats["bad_timestamp_ids"])
    if json_errors == 0 and bad_ts == 0:
        return
    bits = []
    if json_errors:
        bits.append(
            f"{json_errors} JSON parse error"
            f"{'s' if json_errors != 1 else ''}"
            f" (first at line {_load_stats['json_decode_first_line']})"
        )
    if bad_ts:
        bits.append(
            f"{bad_ts} unparseable created_at"
            f"{'s' if bad_ts != 1 else ''}"
            f" (first: {_load_stats['bad_timestamp_first_marker']})"
        )
    print(
        f"[retrieval] WARN: dropped memories — {'; '.join(bits)}",
        file=sys.stderr,
    )


def digest_mode_enabled() -> bool:
    """Return whether the Vector 2 Stage 1 digest replaces the recall dump.

    Machine-local gate (design §8, amd-tower-only rollout). Precedence:
    env override ``PA_DIGEST_STAGE1`` first (either direction), then the
    sentinel file ``~/.pa-digest-stage1``, else OFF. Neither signal lives
    in the synced ``data/`` submodule, so enabling on amd-tower does not
    leak to zbook / rpi-server.

    An env value that is neither clearly truthy nor clearly falsy is
    treated as OFF (fail-safe to the legacy hook) and warned to stderr.
    """
    raw = os.environ.get(DIGEST_FLAG_ENV)
    if raw is not None:
        val = raw.strip().lower()
        if val in _TRUTHY:
            return True
        if val in _FALSY:
            return False
        print(
            f"[retrieval] WARN: {DIGEST_FLAG_ENV}={raw!r} is not a "
            f"recognised on/off value — treating as OFF (legacy hook)",
            file=sys.stderr,
        )
        return False
    return DIGEST_SENTINEL.exists()


def scratchpad_budget_enabled() -> bool:
    """Return whether the Vector 2b scratchpad byte budget is active.

    Independent machine-local gate, mirroring :func:`digest_mode_enabled`
    so the two Vector passes roll out (and roll back) the same way without
    coupling. Precedence: env override ``PA_SCRATCHPAD_BUDGET`` first
    (either direction), then the sentinel ``~/.pa-scratchpad-budget``, else
    OFF. Neither signal lives in the synced ``data/`` submodule, so enabling
    on amd-tower does not leak to zbook / rpi-server — and OFF means the
    scratchpad is injected exactly as before (byte-identical), leaving the
    live Vector 2 §8 observation window unconfounded.

    An env value that is neither clearly truthy nor clearly falsy is treated
    as OFF (fail-safe to today's behaviour) and warned to stderr.
    """
    raw = os.environ.get(SCRATCHPAD_FLAG_ENV)
    if raw is not None:
        val = raw.strip().lower()
        if val in _TRUTHY:
            return True
        if val in _FALSY:
            return False
        print(
            f"[retrieval] WARN: {SCRATCHPAD_FLAG_ENV}={raw!r} is not a "
            f"recognised on/off value — treating as OFF (no scratchpad cap)",
            file=sys.stderr,
        )
        return False
    return SCRATCHPAD_SENTINEL.exists()


def focus_digest_enabled() -> bool:
    """Return whether Vector 2c focus-aware + scoped selection is active.

    Independent machine-local gate, mirroring :func:`digest_mode_enabled`
    and :func:`scratchpad_budget_enabled` so all three Vector passes roll
    out (and back) identically without coupling. Precedence: env override
    ``PA_DIGEST_FOCUS`` first (either direction), then the sentinel
    ``~/.pa-digest-focus``, else OFF. Neither signal lives in the synced
    ``data/`` submodule, and OFF means the digest selects exactly as the
    Vector 2 digest does (byte-identical), leaving the live §8 window
    unconfounded.

    An env value that is neither clearly truthy nor clearly falsy is
    treated as OFF (fail-safe to the Vector 2 digest) and warned to stderr.
    """
    raw = os.environ.get(FOCUS_FLAG_ENV)
    if raw is not None:
        val = raw.strip().lower()
        if val in _TRUTHY:
            return True
        if val in _FALSY:
            return False
        print(
            f"[retrieval] WARN: {FOCUS_FLAG_ENV}={raw!r} is not a "
            f"recognised on/off value — treating as OFF (Vector 2 digest)",
            file=sys.stderr,
        )
        return False
    return FOCUS_SENTINEL.exists()


def load_focus_profile() -> tuple[set[str], str]:
    """Parse the active FOCUS.md slot projects into a coarse focus profile.

    Returns ``(keywords, label)``:
      - ``keywords`` — lowercased last-path-segments of each active slot's
        ``- **Project:** …`` line (``research/inscriptions`` → ``inscriptions``,
        ``business/efn`` → ``efn``), for coarse matching in
        :func:`digest_selector.focus_score`.
      - ``label`` — the same segments, deduped and order-preserved, joined
        for the digest's one-line legibility cue.

    Only the bulleted ``**Project:**`` lines are read; the Paused table uses
    pipe-delimited cells (not ``**Project:**`` bullets), so paused projects
    are excluded by construction. Fail-soft: any read/parse problem returns
    ``(set(), "")`` so the digest degrades to its prior ranking rather than
    breaking session start.
    """
    try:
        text = FOCUS_FILE.read_text(encoding="utf-8")
    except OSError:
        return set(), ""
    keywords: set[str] = set()
    label_tokens: list[str] = []
    for raw_line in text.splitlines():
        m = re.match(r"\s*-\s*\*\*Project:\*\*\s*(.+?)\s*$", raw_line)
        if not m:
            continue
        value = m.group(1).strip()
        if not value:
            continue
        segment = value.rsplit("/", 1)[-1].strip()
        if not segment:
            continue
        kw = segment.lower()
        keywords.add(kw)
        if segment not in label_tokens:
            label_tokens.append(segment)
    return keywords, ", ".join(label_tokens)


def build_session_digest(
    memories: list[dict],
    project_tags: set[str],
    *,
    project_id: str | None = None,
    focus_keywords: set[str] | None = None,
    focus_label: str | None = None,
) -> str:
    """Build the Stage 1 digest text and append one ``digest.log`` line.

    Thin wrapper over the pure :func:`digest_selector.build_digest` so
    ``main()`` stays readable. The log write is best-effort and never
    raises — a logging failure must not break session start. Returns the
    rendered digest text (already ≤ byte budget). The Vector 2c arguments
    (``project_id`` / ``focus_keywords`` / ``focus_label``) default to the
    pre-2c behaviour, so the flag-OFF call site is byte-identical.
    """
    now = datetime.now(timezone.utc)
    result = digest_selector.build_digest(
        memories,
        now=now,
        project_tags=project_tags,
        project_id=project_id,
        focus_keywords=focus_keywords,
        focus_label=focus_label,
    )
    try:
        DIGEST_LOG.parent.mkdir(parents=True, exist_ok=True)
        with DIGEST_LOG.open("a", encoding="utf-8") as fh:
            fh.write(digest_selector.digest_log_line(result, now=now) + "\n")
    except OSError as exc:  # best-effort instrumentation; never fail the hook
        print(f"[retrieval] WARN: could not write {DIGEST_LOG}: {exc}",
              file=sys.stderr)
    return result.text


def main() -> None:
    """
    SessionStart hook entry point.

    Reads hook input from stdin, loads relevant memories, and outputs
    them as additionalContext for the session.
    """
    # Parse hook input
    try:
        hook_input = json.loads(sys.stdin.read())
    except json.JSONDecodeError as exc:
        # Audit C-M7: surface stdin parse failures rather than silently
        # treat the session as having no cwd. Without `cwd` the project
        # tagging is incorrect, so a malformed payload here meaningfully
        # degrades retrieval — the operator should see it.
        print(
            f"[retrieval] WARN: hook stdin was not valid JSON: {exc}",
            file=sys.stderr,
        )
        hook_input = {}

    # Derive current project from working directory
    cwd = hook_input.get("cwd", "")
    current_project = derive_project(cwd)

    # Personal-assistant is the cross-project hub — it needs visibility
    # into all projects, so skip project-aware filtering entirely.
    # Use the shared encoder so this comparison cannot drift from the
    # writer-side encoding (audit IC3).
    pa_project = encode_project_id(str(PA_DIR))
    if current_project == pa_project:
        current_project = None

    # Load memories
    memories = load_all_memories()

    # Build scratchpad parts (used in both with-memories and empty paths)
    scratchpad = load_scratchpad()
    project_scratchpad, project_scratchpad_path = load_project_scratchpad(cwd)

    scratchpad_sections = []
    if scratchpad:
        scratchpad_sections.append(
            "# Scratchpad\n\n"
            "Claude's learning log — update during sessions when "
            "corrections, preferences, or patterns are noticed.\n"
            "Path: ~/personal-assistant/data/scratchpad.md\n\n"
            + scratchpad
        )
    if project_scratchpad and project_scratchpad_path is not None:
        scratchpad_sections.append(
            f"# Project Scratchpad ({project_scratchpad_path.stem})\n\n"
            "Per-project learning log — loaded because cwd matches "
            f"`{project_scratchpad_path.stem}`.\n"
            f"Path: {project_scratchpad_path}\n\n"
            + project_scratchpad
        )

    if not memories:
        # No memories yet — skip memory retrieval but still load scratchpad
        if scratchpad_sections:
            print("\n\n".join(scratchpad_sections))
        _emit_load_diagnostics()
        sys.exit(0)

    # Build tag profile from same-project memories for cross-project relevance
    project_tags = collect_project_tags(memories, current_project)

    # Vector 2 Stage 1 (machine-local flag): emit the compact digest in
    # place of the four-bucket recall dump. The four retrieve_* passes are
    # skipped entirely — the digest does its own verified-true selection
    # against the loaded corpus and project tag profile.
    if digest_mode_enabled():
        # Vector 2c (independent machine-local flag): when ON, rank by the
        # active FOCUS.md slots and hard-scope to the current project (the
        # hub case is current_project=None → no scope, cross-project focus
        # ranking). When OFF, the params stay at their pre-2c defaults so
        # the digest is byte-identical to today's.
        if focus_digest_enabled():
            focus_keywords, focus_label = load_focus_profile()
            digest_project_id = current_project
        else:
            focus_keywords, focus_label, digest_project_id = set(), "", None
        context = build_session_digest(
            memories,
            project_tags,
            project_id=digest_project_id,
            focus_keywords=focus_keywords,
            focus_label=focus_label,
        )
        parts = [context] if context else []
        parts.extend(scratchpad_sections)
        if not parts:
            _emit_load_diagnostics()
            sys.exit(0)
        print("\n\n".join(parts))
        _emit_load_diagnostics()
        return

    # Retrieve relevant memories with project-aware, tag-relevance bucketing
    cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)
    recent = retrieve_recent(memories, cutoff, current_project, project_tags)

    # Track IDs actually included in recent so later retrieval
    # fills gaps correctly
    recent_ids = {m.get("id") for m in recent if m.get("id")}

    permanent = retrieve_permanent(
        memories, recent_ids, current_project, project_tags
    )

    # Middle-aged bucket — gotcha/pattern in the 14–180 day window,
    # excluding anything already pulled into recent or permanent.
    # ``taken_ids`` accumulates ids already claimed by earlier buckets;
    # each subsequent retrieval extends it, avoiding cross-bucket
    # duplication (audit C-L3 — variable was previously misnamed
    # ``middle_ids``).
    taken_ids = recent_ids | {m.get("id") for m in permanent if m.get("id")}
    middle_aged = retrieve_middle_aged(
        memories, taken_ids, current_project, project_tags
    )

    # Constraint spotlight — dedicated slots for error_mode/prompt_effectiveness
    # (excluded from PERMANENT_CATEGORIES so they only appear here).
    # Exclude everything pulled by other buckets to avoid duplication.
    all_ids = taken_ids | {m.get("id") for m in middle_aged if m.get("id")}
    constraints = retrieve_constraints(
        memories, all_ids, current_project, project_tags
    )

    # Format context
    context = format_context(recent, permanent, constraints, middle_aged)

    # Combine outputs — memories and scratchpad are independent sections
    parts = []
    if context:
        parts.append(context)
    parts.extend(scratchpad_sections)

    if not parts:
        _emit_load_diagnostics()
        sys.exit(0)

    # Inject into session context — plain text stdout is added as
    # additionalContext for SessionStart hooks
    print("\n\n".join(parts))
    _emit_load_diagnostics()


if __name__ == "__main__":
    main()
