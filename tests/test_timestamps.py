"""
Tests for the shared timestamp helpers and full-ISO emission in
``scripts/reprocess-sessions.py`` (audit IC4 / A-Medium #6 / A-CF4).

Pins two contracts:

* The shared helper preserves a full ISO timestamp verbatim, upgrades
  a date-only string to ``T00:00:00+00:00``, and falls back to
  ``now_iso`` for empty / unparseable input.
* ``reprocess-sessions.format_memories`` always emits a full ISO
  timestamp on the ``created_at`` field — never the date-only form
  that the schema (TIMESTAMPTZ NOT NULL) and downstream sort key
  cannot handle cleanly.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


# Match an ISO-8601 datetime with timezone offset. Anchored at start
# only — fractional seconds and offset shape both vary.
ISO_REGEX = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:\d{2}|Z)$"
)


@pytest.fixture(scope="module")
def ts():
    """Load the shared timestamp helpers."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    import _timestamps  # noqa: WPS433
    return _timestamps


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
# now_iso shape
# ---------------------------------------------------------------------------


def test_now_iso_is_full_iso(ts):
    """``now_iso`` emits a full ISO timestamp with timezone offset."""
    out = ts.now_iso()
    assert ISO_REGEX.match(out), f"Not full ISO: {out!r}"
    # Round-trip through fromisoformat
    parsed = datetime.fromisoformat(out.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None


# ---------------------------------------------------------------------------
# coerce_to_iso — preserves valid input, upgrades date-only, falls back
# ---------------------------------------------------------------------------


def test_coerce_preserves_full_iso(ts):
    """A full ISO timestamp is returned verbatim."""
    full = "2026-04-26T15:23:14.123456+00:00"
    assert ts.coerce_to_iso(full) == full


def test_coerce_preserves_z_suffix(ts):
    """A ``Z`` suffix is normalised to ``+00:00``."""
    out = ts.coerce_to_iso("2026-04-26T15:23:14Z")
    assert out == "2026-04-26T15:23:14+00:00"


def test_coerce_upgrades_date_only(ts):
    """Date-only ``YYYY-MM-DD`` is upgraded to midnight UTC.

    Pins the audit IC4 / A-Medium #6 fix: previously the date-only
    string flowed straight through to ``created_at`` and broke parsing
    in session-start retrieval.
    """
    out = ts.coerce_to_iso("2026-04-26")
    assert out == "2026-04-26T00:00:00+00:00"


def test_coerce_empty_uses_fallback(ts):
    """Empty / None input falls back to the ``fallback`` argument."""
    fallback = "2026-04-30T12:00:00+00:00"
    assert ts.coerce_to_iso("", fallback=fallback) == fallback
    assert ts.coerce_to_iso(None, fallback=fallback) == fallback


def test_coerce_empty_no_fallback_uses_now(ts):
    """With no fallback, empty input returns the current UTC time."""
    out = ts.coerce_to_iso("")
    assert ISO_REGEX.match(out)


def test_coerce_unparseable_uses_fallback(ts):
    """Unparseable input falls back rather than raising."""
    fallback = "2026-04-30T12:00:00+00:00"
    assert ts.coerce_to_iso("not a date", fallback=fallback) == fallback


# ---------------------------------------------------------------------------
# reprocess-sessions writer — never emits date-only timestamps
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_extracted():
    """One minimal extracted record."""
    return [
        {
            "category": "context",
            "content": "Test memory",
            "research_tags": [],
            "confidence": "medium",
        }
    ]


def test_format_memories_emits_full_iso_for_date_only_session_date(
    reprocess_module, sample_extracted
):
    """A date-only ``session_date`` produces a full ISO ``created_at``.

    Pins the audit IC4 fix at the writer side — even when historical
    session metadata only carries the date, the emitted record matches
    the schema's TIMESTAMPTZ shape.
    """
    out = reprocess_module.format_memories(
        sample_extracted,
        session_id="test-session",
        project="-foo",
        session_date="2026-04-26",
        custom_id="c-0",
    )
    assert len(out) == 1
    created = out[0]["created_at"]
    assert ISO_REGEX.match(created), f"Not full ISO: {created!r}"
    # Specifically the upgraded form — midnight UTC.
    assert created == "2026-04-26T00:00:00+00:00"


def test_format_memories_preserves_full_iso(reprocess_module, sample_extracted):
    """A full-ISO ``session_date`` is preserved verbatim."""
    full = "2026-04-26T15:23:14.123456+00:00"
    out = reprocess_module.format_memories(
        sample_extracted,
        session_id="test-session",
        project="-foo",
        session_date=full,
        custom_id="c-0",
    )
    assert out[0]["created_at"] == full


def test_format_memories_empty_session_date_uses_now(
    reprocess_module, sample_extracted
):
    """Missing ``session_date`` falls back to the current UTC time."""
    out = reprocess_module.format_memories(
        sample_extracted,
        session_id="test-session",
        project="-foo",
        session_date="",
        custom_id="c-0",
    )
    created = out[0]["created_at"]
    assert ISO_REGEX.match(created)
    # Should be tz-aware and parseable
    parsed = datetime.fromisoformat(created)
    assert parsed.tzinfo is not None
    # And approximately now (within a generous margin)
    now = datetime.now(timezone.utc)
    delta = abs((now - parsed).total_seconds())
    assert delta < 60, f"created_at not close to now: {created} vs {now.isoformat()}"
