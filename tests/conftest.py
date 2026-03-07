"""
Shared fixtures for personal-assistant test suite.

Provides temporary directories and sample data for hook testing
without touching the real memory system.
"""

import json
import sys
from pathlib import Path

import pytest

# Add project root to path so we can import hook modules
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "hooks"))


@pytest.fixture
def tmp_pa_dir(tmp_path):
    """Create a temporary personal-assistant directory structure."""
    (tmp_path / "memories").mkdir()
    (tmp_path / "tasks").mkdir()
    (tmp_path / "logs").mkdir()
    return tmp_path


@pytest.fixture
def sample_memories():
    """Sample memory records for testing."""
    return [
        {
            "id": "2026-02-07-abc123",
            "session_id": "test-session-1",
            "source": "extraction",
            "category": "decision",
            "content": "Use PostgreSQL for memory queries.",
            "confidence": "high",
            "research_tags": ["database", "architecture"],
            "source_context": "Phase 2 planning",
            "created_at": "2026-02-07T10:00:00+00:00",
        },
        {
            "id": "2026-02-07-def456",
            "session_id": "test-session-1",
            "source": "manual",
            "category": "commitment",
            "content": "Finish results section by Friday.",
            "confidence": "high",
            "research_tags": ["llm-history-paper", "deadline"],
            "source_context": "Manual capture via /remember",
            "created_at": "2026-02-07T12:00:00+00:00",
            "deadline_at": "2026-02-13T15:00:00+11:00",
        },
        {
            "id": "2026-02-08-ghi789",
            "session_id": "test-session-2",
            "source": "extraction",
            "category": "progress",
            "content": "Phase 3 implementation complete.",
            "confidence": "medium",
            "research_tags": ["gtd-implementation"],
            "source_context": "Session summary",
            "created_at": "2026-02-08T09:00:00+00:00",
        },
    ]


@pytest.fixture
def sample_focus_md():
    """Sample FOCUS.md content with 3 slots."""
    return """# Current Focus

**Last updated:** 2026-02-08 (standup)
**Focus check:** 3 of 3 slots filled

---

## Slot 1: LLM-History-Paper

- **Project:** research/llm-history-paper
- **Started:** 2026-02-06
- **Deadline:** 2026-02-28
- **Why this matters:** End-of-February deadline.
- **Next action:** Write results section.
- **Blocked by:** Nothing

---

## Slot 2: fieldmark-docs-staging

- **Project:** business/fieldmark-docs-staging
- **Started:** 2026-02-08
- **Deadline:** None
- **Why this matters:** EFN startup documentation.
- **Next action:** Review pipeline output.
- **Blocked by:** Nothing

---

## Slot 3: ANU Teaching Prep

- **Project:** teaching/anu-digital-humanities
- **Started:** 2026-02-08
- **Deadline:** 2026-02-25
- **Why this matters:** First class 25 Feb.
- **Next action:** Check Canvas access.
- **Blocked by:** Possibly Canvas access

---

## Paused (Must Finish Focus Before Resuming)

| Item | Project | Paused Since | Why Paused |
|------|---------|--------------|------------|

---

## Rules

1. **Max 3 focus items.** (Raised from 2 on 2026-02-08.)
2. **Finish or explicitly abandon** before starting something new.
3. **If stuck for 3+ days**, something is wrong. Surface it.
4. **Paused items are paused**, not "also working on." Don't touch them.
"""


@pytest.fixture
def sample_system_md():
    """Sample SYSTEM.md content."""
    return """# System Configuration

Last updated: 2026-02-08

## Parameters

| Parameter | Current | Default | Notes |
|-----------|---------|---------|-------|
| focus_limit | 3 | 2 | Max items in FOCUS.md |
| escalation_question_day | 3 | 3 | When to start asking questions |
| escalation_confront_day | 7 | 7 | When to get confrontational |
| escalation_abandon_day | 14 | 14 | When to discuss abandonment |
"""


@pytest.fixture
def sample_inbox_md():
    """Sample inbox.md with a mix of checked and unchecked items."""
    return """# Inbox

Quick captures. Process daily during standup.

---

- [ ] 2026-02-08 10:00 | Check Brian's email about figure layout
- [ ] 2026-02-08 11:30 | Look into Canvas LMS API
- [x] 2026-02-08 09:15 | ANU teaching slot → Processed: added to focus
"""


@pytest.fixture
def sample_waiting_for_md():
    """Sample waiting-for.md with data rows and placeholders."""
    return """# Waiting For

Items blocked on others. Review weekly.

---

| Item | Waiting On | Since | Last Poked | Next Action If No Response |
|------|------------|-------|------------|---------------------------|
| Canvas LMS access | ANU IT support | 2026-02-07 | 2026-02-07 | Follow up Monday |
| — | — | — | — | — |
"""


def write_jsonl(path: Path, records: list[dict]) -> None:
    """Helper to write a list of dicts as JSONL."""
    with open(path, "w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")
