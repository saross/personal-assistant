"""
Shared fixtures for personal-assistant test suite.

Provides temporary directories and sample data for hook testing
without touching the real memory system.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add project root to path so we can import hook modules
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "hooks"))


# ---------------------------------------------------------------------------
# HOME belongs to the suite, not to the operator
#
# Every script here resolves ``~`` — gate files, sidecars, refusal
# memories, lock files, the daily-sync marker — and the hermeticity guard
# below watches that directory for writes the suite should not have made.
# Watching the OPERATOR'S home made the guard wrong in both directions:
# it blamed the suite for other processes' writes (after merge, cron
# rewrites the memories gate every five minutes, so a full run would fail
# at random), and it could only ever catch a leak after the damage was
# done (ninth re-audit, finding M5).
#
# So the suite gets a home of its own, and the guard watches THAT. The
# repoint happens at import time rather than in a fixture because several
# modules bake ``Path.home()`` into constants when they are imported, and
# a fixture runs far too late to change what those constants mean.
#
# A test that genuinely needs the real checkout must find it from
# ``__file__`` or an explicit environment variable — never from ``~``.
# ---------------------------------------------------------------------------

#: Held for the life of the process; its finaliser removes the directory.
_SUITE_HOME = tempfile.TemporaryDirectory(prefix="pa-test-home-")
#: The operator's real home, kept only so a test can assert we left it.
REAL_HOME = os.environ.get("HOME")
os.environ["HOME"] = _SUITE_HOME.name
os.environ.pop("XDG_CACHE_HOME", None)
Path(_SUITE_HOME.name, ".cache").mkdir(parents=True, exist_ok=True)
# A minimal identity, so a throwaway repository can commit without
# borrowing the operator's name or failing outright.
Path(_SUITE_HOME.name, ".gitconfig").write_text(
    "[user]\n\tname = Personal Assistant Tests\n"
    "\temail = tests@personal-assistant.invalid\n",
    encoding="utf-8",
)


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
            "project": "-home-shawn-test-project",
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
            "project": "-home-shawn-test-project",
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




# ---------------------------------------------------------------------------
# Hermeticity: the suite must not write ~/.cache at all
#
# Three separate times during the September 2026 audit a test wrote a real
# gate, sidecar, or refusal-memory file, putting a fabricated
# infrastructure problem in front of Shawn at his next session start. Each
# time the fix was another fixture, and each time the next new test forgot
# it. This asserts the property itself, once, for the whole run.
#
# HOME is the suite's own now (see above), so nothing here can reach the
# operator's files even if a test tries — and the guard is measuring a
# directory no other process writes, so it accuses only the suite.
# ---------------------------------------------------------------------------

#: Files under ~/.cache the assistant's infrastructure owns. A test that
#: creates, modifies, or DELETES one of these has escaped its tmp
#: directory, and every one of them is read at session start and relayed
#: to Shawn — so a stray write fabricates an infrastructure problem and a
#: stray delete hides a real one (eighth re-audit, finding M7).
_PIPELINE_CACHE_GLOBS = (
    "postgres-sync-*",
    "index-session-content-*",
    "daily-sync-gate",
    "daily-sync-last-run",
    "memory-drift-gate",
    "cc-archives-gate",
    "cc-archive-drift-gate",
    "syncthing-gate",
)


def _pipeline_cache_snapshot() -> dict[str, tuple[int, int]]:
    """Map every watched cache file to ``(mtime_ns, size)``.

    Size as well as mtime: a rewrite within the same clock tick can leave
    the mtime alone, and the whole point of this fixture is to catch the
    write nobody meant to make.
    """
    cache = Path.home() / ".cache"
    snapshot: dict[str, tuple[int, int]] = {}
    if not cache.is_dir():
        return snapshot
    for pattern in _PIPELINE_CACHE_GLOBS:
        for path in cache.glob(pattern):
            try:
                stat = path.stat()
            except OSError:
                continue
            snapshot[str(path)] = (stat.st_mtime_ns, stat.st_size)
    return snapshot


@pytest.fixture(scope="session", autouse=True)
def no_real_cache_writes():
    """Fail the run if the suite touched a real pipeline file in ~/.cache.

    Also fails if a test left ``HOME`` pointing somewhere else: this
    guard resolves ``~`` at call time, so a test that repoints HOME and
    does not put it back moves the very thing being watched and makes the
    check vacuous.
    """
    home_before = os.environ.get("HOME")
    assert home_before == _SUITE_HOME.name, (
        "HOME was moved off the suite's own directory before the first "
        "test ran"
    )
    before = _pipeline_cache_snapshot()
    yield
    after = _pipeline_cache_snapshot()
    home_after = os.environ.get("HOME")

    # HOME first: a repointed HOME means the snapshot above was taken of
    # a different directory, so every other verdict here is meaningless
    # and the diagnosis has to name the real cause.
    assert home_after == home_before, (
        "a test left HOME repointed "
        f"({home_before!r} -> {home_after!r}); the hermeticity guard here "
        "resolves ~ at call time, so the rest of the run was watching the "
        "wrong directory. Use monkeypatch.setenv, which restores it."
    )

    created = sorted(set(after) - set(before))
    deleted = sorted(set(before) - set(after))
    modified = sorted(
        path for path in set(after) & set(before)
        if after[path] != before[path]
    )
    assert not created and not modified and not deleted, (
        "the test suite wrote to the operator's real ~/.cache — a "
        "fabricated infrastructure problem would appear at their next "
        "session start, or a real one would have vanished.\n"
        f"  created:  {created}\n"
        f"  modified: {modified}\n"
        f"  deleted:  {deleted}"
    )
