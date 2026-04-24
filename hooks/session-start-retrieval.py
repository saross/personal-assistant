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
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# ============================================================================
# Configuration
# ============================================================================

PA_DIR = Path.home() / "personal-assistant"
MEMORIES_FILE = PA_DIR / "memories" / "memories.jsonl"
SCRATCHPAD_FILE = PA_DIR / "data" / "scratchpad.md"
SCRATCHPADS_DIR = PA_DIR / "data" / "scratchpads"

# Scratchpad size threshold — warn when distillation is needed
SCRATCHPAD_WARN_LINES = 150

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

# ============================================================================
# Memory Loading
# ============================================================================


def load_all_memories() -> list[dict]:
    """Load all memories from the canonical JSONL file."""
    if not MEMORIES_FILE.exists():
        return []

    memories = []
    for line in MEMORIES_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            memories.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    return memories


def parse_created_at(mem: dict) -> datetime | None:
    """Parse the created_at timestamp from a memory record.

    Always returns a tz-aware datetime (assumes UTC if the stored string
    has no timezone) so callers can compare against tz-aware cutoffs
    without TypeError.
    """
    ts = mem.get("created_at", "")
    if not ts:
        return None
    try:
        # Handle both Z suffix and +00:00 format
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def derive_project(cwd: str) -> Optional[str]:
    """
    Derive the project identifier from the current working directory.

    Matches the encoding used by Claude Code for project directories
    under ~/.claude/projects/ (path separators replaced with hyphens).
    """
    if not cwd:
        return None
    return str(Path(cwd).resolve()).replace("/", "-")


def is_same_project(mem: dict, current_project: Optional[str]) -> bool:
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
    current_project: Optional[str],
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
    counts: dict[Optional[str], int] = {}
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
    """Return parsed datetime for sorting; epoch for unparseable timestamps."""
    return parse_created_at(mem) or datetime.min.replace(tzinfo=timezone.utc)


def retrieve_recent(
    memories: list[dict],
    cutoff: datetime,
    current_project: Optional[str],
    project_tags: Optional[set[str]] = None,
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
    current_project: Optional[str],
    project_tags: Optional[set[str]] = None,
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
    current_project: Optional[str],
    project_tags: Optional[set[str]] = None,
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
    current_project: Optional[str],
    project_tags: Optional[set[str]] = None,
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


def format_memory(mem: dict) -> str:
    """
    Format a single memory as a compact Level 1 index entry.

    Compact format prioritises content-first reading flow:
    ``[category] summary | tag1, tag2 [YYYY-MM-DD]``

    Confidence is omitted (available via ``/recall``).
    """
    category = mem.get("category", "unknown")
    content = mem.get("summary") or mem.get("content", "")
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
    does not exist or is empty. Warns to stderr if the file exceeds
    SCRATCHPAD_WARN_LINES, recommending distillation via /retro.
    """
    if not SCRATCHPAD_FILE.exists():
        return ""

    content = SCRATCHPAD_FILE.read_text().strip()
    if not content:
        return ""

    line_count = len(content.splitlines())
    if line_count > SCRATCHPAD_WARN_LINES:
        print(
            f"[scratchpad] {line_count} lines — consider running /retro "
            f"to distil (threshold: {SCRATCHPAD_WARN_LINES})",
            file=sys.stderr,
        )

    return content


def load_project_scratchpad(cwd: str) -> tuple[str, Optional[Path]]:
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
    return content, path


# ============================================================================
# Main
# ============================================================================


def main() -> None:
    """
    SessionStart hook entry point.

    Reads hook input from stdin, loads relevant memories, and outputs
    them as additionalContext for the session.
    """
    # Parse hook input
    try:
        hook_input = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        hook_input = {}

    # Derive current project from working directory
    cwd = hook_input.get("cwd", "")
    current_project = derive_project(cwd)

    # Personal-assistant is the cross-project hub — it needs visibility
    # into all projects, so skip project-aware filtering entirely
    pa_project = str(PA_DIR.resolve()).replace("/", "-")
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
        sys.exit(0)

    # Build tag profile from same-project memories for cross-project relevance
    project_tags = collect_project_tags(memories, current_project)

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
    # excluding anything already pulled into recent or permanent
    middle_ids = recent_ids | {m.get("id") for m in permanent if m.get("id")}
    middle_aged = retrieve_middle_aged(
        memories, middle_ids, current_project, project_tags
    )

    # Constraint spotlight — dedicated slots for error_mode/prompt_effectiveness
    # (excluded from PERMANENT_CATEGORIES so they only appear here).
    # Exclude everything pulled by other buckets to avoid duplication.
    all_ids = middle_ids | {m.get("id") for m in middle_aged if m.get("id")}
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
        sys.exit(0)

    # Inject into session context — plain text stdout is added as
    # additionalContext for SessionStart hooks
    print("\n\n".join(parts))


if __name__ == "__main__":
    main()
