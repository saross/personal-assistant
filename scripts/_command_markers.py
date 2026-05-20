#!/usr/bin/env python3
"""
Shared slash-command markers for transcript extraction filters.

Background
----------
Both ``hooks/extraction-hook.py`` and ``scripts/reprocess-sessions.py``
filter out slash-command exchanges before sending transcripts to Haiku
for memory extraction. The two scripts had drifted: the live hook used
fully-qualified document headers (em-dash + section title) while the
reprocess script used bare slash-command names like ``"/remember"``.

The drift was an active correctness bug: any user prose that merely
*mentioned* ``/remember`` (or any other command name) caused the
reprocess script to silently drop the user message **and** the next
assistant response. This connects to the 851-record re-id event of
2026-04-14 (see ``scripts/dedup-memories.py:16``).

Audit refs
----------
* ``reports/audit-2026-05-02/SUMMARY.md`` — A-Critical #3, A-CF3, IC1
  (writer-side fix in this batch).
* ``reports/audit-2026-05-02/cluster-A-memory-pipeline.md`` — Critical
  #3 narrative.

Strict-form rationale
---------------------
The markers below are the document headers emitted by each slash-command
skill at the top of the user message Claude Code synthesises. They
contain a leading ``# ``, the literal command name, an em-dash
(``—``), and the human-readable command title. The em-dash plus
the deliberate spacing make false positives in user prose effectively
impossible.

The reflection-protocol marker is similar in shape but produced by the
``reflect`` skill rather than a ``/``-prefixed command — it is filtered
because the reflection document itself is the canonical record;
extracting from it would create lossy duplicates.

Both consumers MUST import ``COMMAND_MARKERS`` from this module rather
than redefining it locally.
"""

# Strict markers — fully-qualified document headers, never bare slash
# names. Tuple (rather than list) makes accidental mutation noisy.
COMMAND_MARKERS: tuple[str, ...] = (
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
    # Verified 2026-05-20 against ``commands/sync-board.md`` header.
    "# /sync-board — GitHub Projects Board Sync",
    "# /process-email — Email Triage",
    "# /forget — Soft-delete Memory",
    "# /update — Revise Memory",
    # Reflection protocol — reflection docs are the canonical record;
    # extracting from them creates lossy duplicates.
    "# End-of-Session Reflection",
    # v2 (2026-05-16) — autonomous memory-write announce lines.
    # Claude emits these when self-invoking /remember, /forget, or
    # /update outside of an explicit slash-command invocation; the
    # extraction hook skips them so the announce turn isn't re-extracted
    # as a fresh memory. The leading "# " plus specific phrasing makes
    # prose false-positives negligible. See:
    # planning/memory-system-v2-design.md change D (announce-and-save).
    "# Saved to memory:",
    "# Forgot memory:",
    "# Updated memory:",
)


def is_command_exchange(content: str) -> bool:
    """Return True iff *content* begins or contains a known command marker.

    Uses substring containment (``marker in content``) to match the
    historical filter behaviour at the call sites. The markers are
    long enough — and contain a literal em-dash — that prose-level
    false positives are not a concern.
    """
    return any(marker in content for marker in COMMAND_MARKERS)
