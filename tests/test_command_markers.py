"""
Tests for the shared ``COMMAND_MARKERS`` module (audit IC1 / A-Critical
#3 fix).

Pins two contracts:

* The marker list is the strict, document-header form — bare slash names
  ("/remember", "/recall", ...) MUST NOT match plain prose mentioning a
  command.
* Both writers (``hooks/extraction-hook.py`` and
  ``scripts/reprocess-sessions.py``) import the SAME object — they
  cannot drift after this batch lands.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
HOOKS_DIR = PROJECT_ROOT / "hooks"


@pytest.fixture(scope="module")
def shared_markers() -> tuple[str, ...]:
    """Load COMMAND_MARKERS from the shared module."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    from _command_markers import COMMAND_MARKERS  # noqa: WPS433
    return COMMAND_MARKERS


@pytest.fixture(scope="module")
def extraction_hook_module():
    """Load hooks/extraction-hook.py as a module (hyphenated filename)."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location(
        "extraction_hook", HOOKS_DIR / "extraction-hook.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def reprocess_module():
    """Load scripts/reprocess-sessions.py as a module."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    spec = importlib.util.spec_from_file_location(
        "reprocess_sessions", SCRIPTS_DIR / "reprocess-sessions.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Strictness contract — false-positive cases the previous bare-string list
# would have falsely matched as command boundaries.
# ---------------------------------------------------------------------------


# These strings are user prose mentioning a slash-command name in
# passing — none of them should be classified as a command exchange.
PROSE_FALSE_POSITIVES = [
    "I should /remember to look at this later.",
    "Don't forget to /recall the previous decision.",
    "We could use /capture for those quick thoughts.",
    "Let's run /standup tomorrow morning.",
    "The /track command is for time tracking.",
    "End-of-Session Reflection notes go in the reflection doc.",
    "When you say `/remember`, do you mean the command?",
    "After /done is invoked, the task moves to done/.",
    "// random comment with /focus mentioned",
]


@pytest.mark.parametrize("prose", PROSE_FALSE_POSITIVES)
def test_prose_does_not_match_marker(shared_markers, prose):
    """User prose mentioning a slash command must not trigger filtering.

    Pins the audit IC1 fix: the previous bare-string list ``"/remember"``
    matched any of these, silently dropping the user message AND the
    next assistant response from extraction.
    """
    assert not any(marker in prose for marker in shared_markers), (
        f"Prose {prose!r} falsely matched a command marker — strictness "
        f"regression."
    )


# ---------------------------------------------------------------------------
# Positive cases — actual document headers that MUST match.
# ---------------------------------------------------------------------------


# Document-header form — exactly what each command skill emits at the
# top of the synthesised user message.
COMMAND_HEADERS = [
    "# /remember — Manual Memory Capture",
    "# /recall — Search Memories",
    "# /capture — Quick Inbox Capture",
    "# /craft — Quick Craft Notebook Entry",
    "# /focus — Manage Focus Slots",
    "# /done — Mark Task Complete",
    "# /standup — Daily Accountability Check",
    "# /recap — End-of-Day Recap",
    "# /track — Time Tracking",
    "# /weekly-review — Weekly Review",
    "# /retro — Monthly System Retrospective",
    "# /sync-board — GitHub Issues Sync",
    "# /process-email — Email Triage",
    "# End-of-Session Reflection",
]


@pytest.mark.parametrize("header", COMMAND_HEADERS)
def test_document_header_matches(shared_markers, header):
    """Each canonical command document header is matched as a marker."""
    assert any(marker in header for marker in shared_markers), (
        f"Header {header!r} did not match any marker — coverage regression."
    )


# ---------------------------------------------------------------------------
# Identity contract — both consumers reference the same tuple.
# ---------------------------------------------------------------------------


def test_extraction_hook_uses_shared_markers(
    shared_markers, extraction_hook_module
):
    """extraction-hook.COMMAND_MARKERS must be the same object as the
    shared module's tuple.

    Tests identity (``is``) not equality, so a future refactor that
    re-defines the constant locally would fail this even if the values
    happen to match by chance.
    """
    assert extraction_hook_module.COMMAND_MARKERS is shared_markers


def test_reprocess_sessions_uses_shared_markers(
    shared_markers, reprocess_module
):
    """reprocess-sessions.COMMAND_MARKERS must be the same object as
    the shared module's tuple."""
    assert reprocess_module.COMMAND_MARKERS is shared_markers


def test_marker_count_matches_documented(shared_markers):
    """The marker list has the expected size — 13 slash commands plus
    the reflection-protocol marker.

    Bumping this number is fine when adding a new slash command, but
    the test forces a deliberate update rather than silent drift.
    """
    assert len(shared_markers) == 14
