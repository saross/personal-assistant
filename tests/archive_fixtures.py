"""
Synthetic transcript and archive fixtures for the session-archive pipeline.

Every byte here is invented. Nothing is copied from a real transcript, a real
archive entry, or the operator's notes: this is a public repository and those
sources are private. The *shapes* are real — top-level ``type``, ``uuid``,
``parentUuid``, ``timestamp``, ``sessionId``, ``cwd``, ``isMeta``,
``isSidechain``, ``isCompactSummary``, ``tool_use``/``tool_result`` blocks,
``thinking`` blocks, and a ``subagents/`` directory — because the scripts
under test parse exactly those fields. The words are not.

Used by ``test_archive_substance.py``, ``test_check_archive_drift.py``,
``test_bulk_archive.py``, ``test_normalise_archive_storage.py``, and
``test_reprocess_sessions.py``.
"""

from __future__ import annotations

import gzip
import json
import os
import time
import uuid as uuid_module
from pathlib import Path
from typing import Any

#: A deterministic stand-in for a working directory. Never a real project.
SAMPLE_CWD = "/home/tester/Workshop/lantern-survey"


def make_uuid(seed: int) -> str:
    """Return a stable, obviously synthetic UUID string for *seed*."""
    return str(uuid_module.UUID(int=seed))


def prose_record(
    role: str,
    text: str,
    *,
    index: int,
    parent: str | None = None,
    session_id: str = "",
    is_meta: bool = False,
    is_sidechain: bool = False,
    is_compact_summary: bool = False,
    timestamp: str = "2026-03-02T09:00:00Z",
    cwd: str = SAMPLE_CWD,
    structured: bool = False,
) -> dict[str, Any]:
    """Build one conversational transcript record in the production shape.

    *structured* wraps the text in a ``text`` content block rather than a bare
    string; both forms occur in real transcripts and both must be counted.
    """
    content: Any = [{"type": "text", "text": text}] if structured else text
    record: dict[str, Any] = {
        "type": role,
        "uuid": make_uuid(index),
        "parentUuid": parent,
        "sessionId": session_id,
        "timestamp": timestamp,
        "cwd": cwd,
        "version": "2.0.14",
        "message": {"role": role, "content": content},
    }
    if is_meta:
        record["isMeta"] = True
    if is_sidechain:
        record["isSidechain"] = True
    if is_compact_summary:
        record["isCompactSummary"] = True
    return record


def tool_use_record(
    index: int, *, tool: str = "Edit", file_path: str = f"{SAMPLE_CWD}/plan.md",
    session_id: str = "", timestamp: str = "2026-03-02T09:00:30Z",
) -> dict[str, Any]:
    """An assistant record whose content is a ``tool_use`` block."""
    return {
        "type": "assistant",
        "uuid": make_uuid(index),
        "parentUuid": make_uuid(index - 1),
        "sessionId": session_id,
        "timestamp": timestamp,
        "cwd": SAMPLE_CWD,
        "message": {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "Weighing the two options."},
                {
                    "type": "tool_use",
                    "id": f"toolu_{index:04d}",
                    "name": tool,
                    "input": {"file_path": file_path},
                },
            ],
        },
    }


def tool_result_record(
    index: int, *, session_id: str = "",
    timestamp: str = "2026-03-02T09:00:45Z",
) -> dict[str, Any]:
    """A user record whose content is a ``tool_result`` block, not prose."""
    return {
        "type": "user",
        "uuid": make_uuid(index),
        "parentUuid": make_uuid(index - 1),
        "sessionId": session_id,
        "timestamp": timestamp,
        "cwd": SAMPLE_CWD,
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": f"toolu_{index - 1:04d}",
                    "content": "wrote 4 lines" * 400,
                }
            ],
        },
    }


def write_transcript(path: Path, records: list[dict[str, Any]]) -> Path:
    """Write *records* as JSONL at *path*, creating parents. Returns *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    return path


def substantive_records(
    session_id: str, *, turns: int = 1, chars_per_turn: int = 15_000,
) -> list[dict[str, Any]]:
    """Records whose prose comfortably clears the 4,000-character floor.

    Defaults to ONE exchange of 15,000 characters each way — the two-turn,
    large-session shape that the turn-count filter used to discard and the
    drift gate used to report forever (audit finding AR1).
    """
    filler_q = "How should the survey grid be laid out on the terrace? "
    filler_a = "Lay it out along the contour, then step it downslope. "
    records: list[dict[str, Any]] = []
    index = 1
    parent: str | None = None
    for turn in range(turns):
        question = (filler_q * (chars_per_turn // len(filler_q) + 1))[
            :chars_per_turn
        ]
        answer = (filler_a * (chars_per_turn // len(filler_a) + 1))[
            :chars_per_turn
        ]
        records.append(prose_record(
            "user", question, index=index, parent=parent,
            session_id=session_id,
            timestamp=f"2026-03-02T09:{turn * 2:02d}:00Z",
        ))
        parent = make_uuid(index)
        index += 1
        records.append(prose_record(
            "assistant", answer, index=index, parent=parent,
            session_id=session_id, structured=True,
            timestamp=f"2026-03-02T09:{turn * 2 + 1:02d}:00Z",
        ))
        parent = make_uuid(index)
        index += 1
    return records


def trivial_records(session_id: str, *, turns: int = 5) -> list[dict[str, Any]]:
    """Many short turns: below the prose floor but above any turn count."""
    records: list[dict[str, Any]] = []
    index = 1
    parent: str | None = None
    for turn in range(turns):
        records.append(prose_record(
            "user", "next?", index=index, parent=parent, session_id=session_id,
            timestamp=f"2026-03-02T10:{turn * 2:02d}:00Z",
        ))
        parent = make_uuid(index)
        index += 1
        records.append(prose_record(
            "assistant", "done", index=index, parent=parent,
            session_id=session_id,
            timestamp=f"2026-03-02T10:{turn * 2 + 1:02d}:00Z",
        ))
        parent = make_uuid(index)
        index += 1
    return records


def age_file(path: Path, *, hours: float) -> None:
    """Backdate *path*'s mtime by *hours*, so grace-window logic can be tested."""
    when = time.time() - hours * 3600
    os.utime(path, (when, when))


def make_raw_store(root: Path, *, project_key: str = "-home-tester-Workshop"
                   ) -> Path:
    """Create an empty synthetic ``~/.claude/projects``-shaped store."""
    project_dir = root / project_key
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir


def make_archive_entry(
    archive_root: Path,
    session_id: str,
    *,
    project: str = "lantern-survey",
    entry_name: str = "2026-03-02_survey-grid",
    records: list[dict[str, Any]] | None = None,
    with_transcript: bool = True,
    purpose: str = "Planned the survey grid.",
) -> Path:
    """Create one synthetic archive entry (meta + gzipped transcript).

    Returns the entry directory. Mirrors the v1.1 layout the pipeline reads:
    ``<root>/<project>/<entry>/session.meta.json`` plus
    ``session.jsonl.gz``.
    """
    entry = archive_root / project / entry_name
    entry.mkdir(parents=True, exist_ok=True)
    body = records if records is not None else substantive_records(session_id)
    raw = "".join(json.dumps(record) + "\n" for record in body).encode("utf-8")
    if with_transcript:
        with gzip.open(entry / "session.jsonl.gz", "wb") as handle:
            handle.write(raw)
    meta = {
        "schema_version": "1.1",
        "session": {"id": session_id, "started_at": "2026-03-02T09:00:00Z"},
        "project": {"name": project},
        "statistics": {"turns": len(body) // 2, "duration_minutes": 20},
        "auto_generated": {"purpose": purpose, "title": "Survey grid", "tags": []},
        "archive": {
            "jsonl_path": "session.jsonl.gz",
            "jsonl_bytes": len(raw),
            "jsonl_bytes_uncompressed": len(raw),
            "jsonl_compression": "gzip",
        },
    }
    (entry / "session.meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    return entry
