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

  Slot allocation (46 total):
    Same-project: 15 recent + 20 permanent = 35
    Other-project: 3 recent + 8 permanent = 11

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
    # LLM Interaction Research
    "error_mode",
    "surprise",
    "self_reflection",
    "prompt_effectiveness",
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

# Project-aware slot allocation (tag-relevance-scored for cross-project)
MAX_RECENT_SAME = 15
MAX_RECENT_OTHER = 3
MAX_PERMANENT_SAME = 20
MAX_PERMANENT_OTHER = 8

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

    for mem in memories:
        created = parse_created_at(mem)
        if not created or created < cutoff:
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


# ============================================================================
# Formatting
# ============================================================================


def format_memory(mem: dict) -> str:
    """Format a single memory for context injection."""
    category = mem.get("category", "unknown")
    confidence = mem.get("confidence", "medium")
    content = mem.get("content", "")
    tags = mem.get("research_tags") or []
    if isinstance(tags, str):
        tags = [tags]
    created = mem.get("created_at", "")[:10]  # Just the date

    line = f"[{category}] ({confidence}, {created}) {content}"
    if tags:
        line += f" | tags: {', '.join(str(t) for t in tags)}"

    return line


def format_context(
    recent: list[dict],
    permanent: list[dict],
) -> str:
    """Format all retrieved memories into a context string."""
    sections = []

    if recent:
        lines = [format_memory(m) for m in recent]
        sections.append(
            "## Recent Memories (last 7 days)\n" + "\n".join(f"- {l}" for l in lines)
        )

    if permanent:
        lines = [format_memory(m) for m in permanent]
        sections.append(
            "## Key Decisions & Knowledge\n" + "\n".join(f"- {l}" for l in lines)
        )

    if not sections:
        return ""

    header = (
        "# Memory Context\n\n"
        "The following memories were retrieved from previous sessions:\n"
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
        # No memories yet — output nothing
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

    # Format context
    context = format_context(recent, permanent)

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
