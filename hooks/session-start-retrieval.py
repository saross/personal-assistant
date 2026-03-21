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
  memories are surfaced first, with recency as a tiebreaker. This
  enables cross-project reasoning (e.g., a fieldmark decision relevant
  to paper methodology surfaces when working on the paper).

  Constraint spotlight (Phase 1b): error_mode and prompt_effectiveness
  memories get a dedicated retrieval pass and output section, separate
  from the general permanent slots. This prevents them being crowded
  out by the much larger decision/architecture pool. Constraints are
  scored by tag overlap across all projects (no project boundary).

  Slot allocation (90 total):
    Same-project: 25 recent + 35 permanent = 60
    Other-project: 5 recent + 15 permanent = 20
    Constraints: 10 (error_mode + prompt_effectiveness)

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

# Scratchpad size threshold — warn when distillation is needed
SCRATCHPAD_WARN_LINES = 150

# How many days of recent memories to include
RECENT_DAYS = 7

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
# Compact Level 1 format allows higher slot counts within similar
# attention budget (~1,300 tokens for 90 memories at ~0.13% of 1M context).
MAX_RECENT_SAME = 25
MAX_RECENT_OTHER = 5
MAX_PERMANENT_SAME = 35
MAX_PERMANENT_OTHER = 15

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
    """Parse the created_at timestamp from a memory record."""
    ts = mem.get("created_at", "")
    if not ts:
        return None
    try:
        # Handle both Z suffix and +00:00 format
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


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

    # Let same-project absorb unused other-project slots (and vice versa)
    # so total capacity is preserved when one bucket is underutilised
    other_take = other[:MAX_RECENT_OTHER]
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

    other_take = other[:MAX_PERMANENT_OTHER]
    same_limit = MAX_PERMANENT_SAME + (MAX_PERMANENT_OTHER - len(other_take))
    merged = same[:same_limit] + other_take
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

    return candidates[:MAX_CONSTRAINTS]


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
    created = mem.get("created_at", "")[:10]  # Just the date

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
) -> str:
    """Format all retrieved memories into a context string."""
    sections = []

    if recent:
        lines = [format_memory(m) for m in recent]
        sections.append(
            f"## Recent Memories (last 7 days) \u2014 {len(recent)} {'item' if len(recent) == 1 else 'items'}\n"
            + "\n".join(f"- {entry}" for entry in lines)
        )

    if constraints:
        lines = [format_memory(m) for m in constraints]
        sections.append(
            f"## Relevant Constraints \u2014 {len(constraints)} {'item' if len(constraints) == 1 else 'items'}\n"
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

    header = (
        "# Memory Context\n\n"
        "The following memories were retrieved from previous sessions.\n"
        "Use `/recall [query]` to retrieve full memory content "
        "when a topic needs deeper context.\n\n"
    )
    return header + "\n\n".join(sections)


# ============================================================================
# Scratchpad
# ============================================================================


def load_scratchpad() -> str:
    """
    Load the scratchpad file for context injection.

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

    if not memories:
        # No memories yet — skip memory retrieval but still load scratchpad
        scratchpad = load_scratchpad()
        if scratchpad:
            print(
                "# Scratchpad\n\n"
                "Claude's learning log — update during sessions when "
                "corrections, preferences, or patterns are noticed.\n"
                "Path: ~/personal-assistant/data/scratchpad.md\n\n"
                + scratchpad
            )
        sys.exit(0)

    # Build tag profile from same-project memories for cross-project relevance
    project_tags = collect_project_tags(memories, current_project)

    # Retrieve relevant memories with project-aware, tag-relevance bucketing
    cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)
    recent = retrieve_recent(memories, cutoff, current_project, project_tags)

    # Track IDs actually included in recent so permanent retrieval
    # fills gaps correctly
    recent_ids = {m.get("id") for m in recent if m.get("id")}
    permanent = retrieve_permanent(
        memories, recent_ids, current_project, project_tags
    )

    # Constraint spotlight — dedicated slots for error_mode/prompt_effectiveness
    # (excluded from PERMANENT_CATEGORIES so they only appear here).
    # Only exclude recent_ids to avoid duplication with the recent section.
    constraints = retrieve_constraints(
        memories, recent_ids, current_project, project_tags
    )

    # Format context
    context = format_context(recent, permanent, constraints)

    # Load scratchpad (Claude's self-correction learning log)
    scratchpad = load_scratchpad()

    # Combine outputs — memories and scratchpad are independent sections
    parts = []
    if context:
        parts.append(context)
    if scratchpad:
        parts.append(
            "# Scratchpad\n\n"
            "Claude's learning log — update during sessions when "
            "corrections, preferences, or patterns are noticed.\n"
            "Path: ~/personal-assistant/data/scratchpad.md\n\n"
            + scratchpad
        )

    if not parts:
        sys.exit(0)

    # Inject into session context — plain text stdout is added as
    # additionalContext for SessionStart hooks
    print("\n\n".join(parts))


if __name__ == "__main__":
    main()
