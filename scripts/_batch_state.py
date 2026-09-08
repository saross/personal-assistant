#!/usr/bin/env python3
"""
_batch_state.py — one state file per Batch API job, not one slot per script.

WHY THIS MODULE EXISTS
----------------------
``bulk-archive.py`` and ``reprocess-sessions.py`` each kept the state that
maps a batch's ``custom_id`` values back to their targets in a single file:
``bulk-enrich-batch-state.json``, ``reprocess-batch-state.json``. The
Anthropic Batch API takes up to 24 hours, so submitting a second batch before
applying the first overwrote the first's map — and that map is the only thing
that says which archive entry or which session each reply belongs to. The
first batch then could not be applied at all, or (worse, before the batch-id
checks added alongside this) was applied through the second's map and filed
everything against the wrong target (audit 2026-09-08, finding AR18).

State is now keyed by batch id. The legacy single-slot file is still written,
so an operator or a script that knows only "the last batch" keeps working,
and it is still READ as a fallback — but only when it names the batch being
applied.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

#: Batch ids are opaque provider strings (``msgbatch_01ABC…``). Anything
#: outside this alphabet is refused rather than turned into a path: a batch id
#: reaches this module from the command line, and a filename is not the place
#: to find out that it contained a slash.
_SAFE_BATCH_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class UnsafeBatchId(ValueError):
    """Raised when a batch id cannot be used as a filename component."""


def state_path(state_dir: Path, batch_id: str) -> Path:
    """Return the per-batch state file path for *batch_id* under *state_dir*.

    Raises :class:`UnsafeBatchId` for anything that is not a plain identifier,
    so a crafted or garbled id can never escape *state_dir*.
    """
    if not _SAFE_BATCH_ID.match(batch_id or ""):
        raise UnsafeBatchId(
            f"batch id {batch_id!r} is not a plain identifier; refusing to "
            "use it as a filename"
        )
    return state_dir / f"{batch_id}.json"


def save_state(
    state: dict[str, Any],
    state_dir: Path,
    legacy_file: Path,
) -> Path:
    """Write *state* keyed by its own ``batch_id``, plus the legacy slot.

    Returns the per-batch path. Both writes go through a temporary file and
    an atomic rename, so an interrupted submit cannot leave a half-written
    map that the apply step would read as authoritative.
    """
    batch_id = state.get("batch_id")
    if not isinstance(batch_id, str):
        raise UnsafeBatchId("state has no string batch_id to key on")
    per_batch = state_path(state_dir, batch_id)
    per_batch.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, indent=2) + "\n"
    _atomic_write(per_batch, payload)
    legacy_file.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(legacy_file, payload)
    return per_batch


def load_state(
    batch_id: str,
    state_dir: Path,
    legacy_file: Path,
) -> dict[str, Any] | None:
    """Load the state describing *batch_id*, or ``None`` if there is none.

    Looks first for the per-batch file, then falls back to the legacy
    single-slot file — but only when that file names this same batch. A slot
    describing a different batch is not a fallback; it is the defect.
    """
    per_batch = state_path(state_dir, batch_id)
    for candidate in (per_batch, legacy_file):
        if not candidate.is_file():
            continue
        try:
            state = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(state, dict) and state.get("batch_id") == batch_id:
            return state
    return None


def _atomic_write(path: Path, text: str) -> None:
    """Write *text* to *path* via a temporary file in the same directory."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
