#!/usr/bin/env python3
"""
SessionStart hook for Claude Code — task accountability banner.

Fires at the beginning of each session. Reads FOCUS.md, inbox.md,
and waiting-for.md to display a brief accountability banner.

Separate from session-start-retrieval.py (different concern,
independent failure). Uses only stdlib — no external packages.
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

# ============================================================================
# Configuration
# ============================================================================

PA_DIR = Path.home() / "personal-assistant"
FOCUS_FILE = PA_DIR / "tasks" / "FOCUS.md"
SYSTEM_FILE = PA_DIR / "tasks" / "SYSTEM.md"
INBOX_FILE = PA_DIR / "tasks" / "inbox.md"
WAITING_FILE = PA_DIR / "tasks" / "waiting-for.md"

# Default focus limit — overridden by SYSTEM.md if available
DEFAULT_FOCUS_LIMIT = 3


# ============================================================================
# Parsing Functions
# ============================================================================


def get_focus_limit() -> int:
    """Read focus_limit from SYSTEM.md, falling back to default."""
    if not SYSTEM_FILE.exists():
        return DEFAULT_FOCUS_LIMIT
    content = SYSTEM_FILE.read_text()
    match = re.search(r"focus_limit\s*\|\s*(\d+)", content)
    if match:
        return int(match.group(1))
    return DEFAULT_FOCUS_LIMIT


def count_inbox_items() -> int:
    """Count unchecked items in inbox.md."""
    if not INBOX_FILE.exists():
        return 0
    content = INBOX_FILE.read_text()
    return len(re.findall(r"^- \[ \]", content, re.MULTILINE))


def count_waiting_items() -> int:
    """Count data rows in waiting-for.md table."""
    if not WAITING_FILE.exists():
        return 0
    content = WAITING_FILE.read_text()
    count = 0
    for line in content.splitlines():
        line = line.strip()
        # Skip non-table lines, header row, separator row, and placeholder rows
        if not line.startswith("|"):
            continue
        if "Waiting On" in line:
            continue
        # Skip separator rows (all cells are dashes only, e.g. |------|------|)
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if all(re.match(r'^-+$', c) for c in cells if c):
            continue
        # Skip placeholder rows with only dashes, em-dashes, or empty cells
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if all(c in ("—", "-", "--", "") for c in cells):
            continue
        count += 1
    return count


def parse_focus_slots() -> list[dict]:
    """
    Parse FOCUS.md to extract filled slot information.

    Returns a list of dicts with keys: name, started, deadline, slot_number.
    Empty slots are excluded.
    """
    if not FOCUS_FILE.exists():
        return []

    content = FOCUS_FILE.read_text()
    slots = []

    # Match slot headers: ## Slot N: [Name]
    slot_pattern = re.compile(
        r"^## Slot (\d+): (.+)$", re.MULTILINE
    )

    for match in slot_pattern.finditer(content):
        slot_num = int(match.group(1))
        name = match.group(2).strip()

        # Skip empty slots
        if name == "[Empty]":
            continue

        # Extract fields from the block after this header
        # Find the text between this header and the next --- or ## heading
        start_pos = match.end()
        remaining = content[start_pos:]

        # Find the end of this slot's content (next --- or ## heading)
        end_match = re.search(r"^(---|## )", remaining, re.MULTILINE)
        block = remaining[: end_match.start()] if end_match else remaining

        slot_info = {
            "name": name,
            "slot_number": slot_num,
            "started": None,
            "deadline": None,
        }

        # Parse Started date
        started_match = re.search(
            r"\*\*Started:\*\*\s*(\d{4}-\d{2}-\d{2})", block
        )
        if started_match:
            slot_info["started"] = started_match.group(1)

        # Parse Deadline
        deadline_match = re.search(
            r"\*\*Deadline:\*\*\s*(\d{4}-\d{2}-\d{2}|None)", block
        )
        if deadline_match:
            val = deadline_match.group(1)
            slot_info["deadline"] = val if val != "None" else None

        slots.append(slot_info)

    return slots


def format_deadline_status(deadline_str: str | None) -> str:
    """Format deadline as a human-readable status string."""
    if not deadline_str:
        return ""

    try:
        deadline = datetime.strptime(deadline_str, "%Y-%m-%d").date()
    except ValueError:
        return ""

    today = datetime.now().date()
    delta = (deadline - today).days

    if delta < 0:
        n = abs(delta)
        return f"OVERDUE by {n} {'day' if n == 1 else 'days'}"
    elif delta == 0:
        return "deadline TODAY"
    elif delta <= 7:
        return f"deadline in {delta} {'day' if delta == 1 else 'days'}"
    else:
        return f"deadline {deadline_str}"


def days_in_focus(started_str: str | None) -> int | None:
    """
    Calculate days in focus (1-indexed: start date = day 1).

    Returns None if started_str is missing or unparseable.
    """
    if not started_str:
        return None
    try:
        started = datetime.strptime(started_str, "%Y-%m-%d").date()
        return (datetime.now().date() - started).days + 1
    except ValueError:
        return None


# ============================================================================
# Main
# ============================================================================


def main() -> None:
    """
    SessionStart hook entry point.

    Reads task state and outputs a brief accountability banner
    via stdout (plain text, injected as additionalContext).
    """
    # Consume stdin (required by hook protocol)
    try:
        json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        pass

    # Parse state — degrade gracefully if files are missing
    slots = parse_focus_slots()
    inbox_count = count_inbox_items()
    waiting_count = count_waiting_items()
    focus_limit = get_focus_limit()

    # Build banner
    lines = ["# Task Status", ""]

    if not slots:
        lines.append("Focus: No items in focus. Run /standup or /focus add.")
    else:
        lines.append("Focus:")
        for slot in slots:
            days = days_in_focus(slot["started"])
            day_str = f"(day {days})" if days is not None else ""
            deadline_str = format_deadline_status(slot["deadline"])
            if deadline_str:
                deadline_str = f" [{deadline_str}]"
            lines.append(
                f"  Slot {slot['slot_number']}: "
                f"{slot['name']} {day_str}{deadline_str}"
            )

        # Show empty slots (dynamically based on focus_limit)
        filled_nums = {s["slot_number"] for s in slots}
        for n in range(1, focus_limit + 1):
            if n not in filled_nums:
                lines.append(f"  Slot {n}: [Empty]")

    lines.append(
        f"Inbox: {inbox_count} items | "
        f"Waiting for: {waiting_count} items"
    )
    lines.append("")
    lines.append("Run /standup for full accountability check.")

    print("\n".join(lines))


if __name__ == "__main__":
    main()
