#!/usr/bin/env python3
"""
SessionStart hook for Claude Code — memory retrieval and context injection.

Fires at the beginning of each session (startup, resume, clear, compact).
Reads the canonical memories.jsonl and injects relevant memories into
Claude's context via the additionalContext field.

Retrieval strategy (project-aware):
  Memories are split into same-project and other-project buckets.
  Same-project memories (including legacy memories with no project field)
  get more slots than other-project memories.

  Slot allocation (40 total):
    Same-project: 15 recent + 20 permanent = 35
    Other-project: 2 recent + 3 permanent = 5

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

# Project-aware slot allocation
MAX_RECENT_SAME = 15
MAX_RECENT_OTHER = 2
MAX_PERMANENT_SAME = 20
MAX_PERMANENT_OTHER = 3

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
) -> list[dict]:
    """
    Get memories from the last N days, split by project affinity.

    Same-project memories (including legacy) get MAX_RECENT_SAME slots.
    Other-project memories get MAX_RECENT_OTHER slots.
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
    other.sort(key=_sort_key, reverse=True)

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
) -> list[dict]:
    """
    Get permanent high-value memories not already in the recent list,
    split by project affinity.

    Same-project memories get MAX_PERMANENT_SAME slots.
    Other-project memories get MAX_PERMANENT_OTHER slots.
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
    other.sort(key=_sort_key, reverse=True)

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
    tags = mem.get("research_tags", [])
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

    # Retrieve relevant memories with project-aware bucketing
    cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)
    recent = retrieve_recent(memories, cutoff, current_project)

    # Track IDs actually included in recent so permanent retrieval
    # fills gaps correctly
    recent_ids = {m.get("id") for m in recent if m.get("id")}
    permanent = retrieve_permanent(memories, recent_ids, current_project)

    # Format context
    context = format_context(recent, permanent)

    if not context:
        sys.exit(0)

    # Inject into session context — plain text stdout is added as
    # additionalContext for SessionStart hooks
    print(context)


if __name__ == "__main__":
    main()
