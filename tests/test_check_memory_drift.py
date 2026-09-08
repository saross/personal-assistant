"""
Tests for ``scripts/check-memory-drift.py`` — the ``--recover`` path.

Audit round two, tranche 3a:

* Finding P8 (lens A-M6) — the recovery SELECT omitted ``is_active`` and
  the history fields, so a memory retired by ``/forget`` came back
  **active** (``sync-to-postgres.py`` reads
  ``record.get("is_active", True)``) with its revision history destroyed.
  The recovery was documented as lossless.
* Finding P9 (lens A-M7) — this was the only canonical writer that took
  no flock, on the one path where the records being written are the last
  surviving copy of the data.

``psql`` is stubbed; no database is contacted.
"""

from __future__ import annotations

import fcntl
import importlib.util
import json
import logging
import multiprocessing
import os
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture(scope="module")
def drift_mod():
    """Load the hyphenated script as a module."""
    path = SCRIPTS_DIR / "check-memory-drift.py"
    spec = importlib.util.spec_from_file_location("check_memory_drift", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_memory_drift"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def quiet_log() -> logging.Logger:
    """Logger that records nothing to disk."""
    log = logging.getLogger("test-memory-drift")
    log.handlers = []
    log.addHandler(logging.NullHandler())
    return log


def _pg_row(mid: str, **overrides) -> dict:
    """Build a row shaped like ``row_to_json`` output for the recovery query."""
    row = {
        "id": mid,
        "session_id": "sess-1",
        "project": "-home-shawn-personal-assistant",
        "source": "extraction",
        "category": "decision",
        "content": f"content of {mid}",
        "confidence": "high",
        "research_tags": ["audit"],
        "source_context": "test",
        "created_at": "2026-09-01T00:00:00.000000+00:00",
        "licence": None,
        "extractor_model_id": "claude-haiku",
        "source_message_uuid": None,
        "summary": "a summary",
        "why": None,
        "how_to_apply": None,
        "anchors": [],
        "verified": None,
        "deadline_at": None,
        "zotero_key": None,
        "links": [],
        "revisions": [],
        "superseded_by": None,
        "is_active": True,
        "decayed_at": None,
    }
    row.update(overrides)
    return row


def _stub_psql(monkeypatch, drift_mod, rows: list[dict]) -> None:
    """Point ``_psql`` at canned ``row_to_json`` output."""
    payload = "\n".join(json.dumps(row) for row in rows) + "\n"
    monkeypatch.setattr(drift_mod, "_psql", lambda sql: payload)


# ---------------------------------------------------------------------------
# P8 — a soft-deleted memory must not come back active
# ---------------------------------------------------------------------------


class TestSoftDeleteIsPreserved:
    """``--recover`` must not undo a ``/forget``."""

    def test_forgotten_record_recovers_as_inactive(
        self, drift_mod, monkeypatch,
    ):
        """
        ``/forget`` writes ``is_active: false`` plus a ``revisions``
        entry. The recovery query did not select either, so the rebuilt
        line carried neither — and ``sync-to-postgres.py`` defaults a
        missing ``is_active`` to TRUE, quietly reactivating the memory.
        The mutation this kills: dropping ``is_active`` from the SELECT
        (or the ``record["is_active"] = False`` assignment).
        """
        revisions = [{"revised_at": "2026-09-02T00:00:00+00:00",
                      "action": "forget", "reason": "superseded"}]
        _stub_psql(monkeypatch, drift_mod, [
            _pg_row("m-forgotten", is_active=False, revisions=revisions),
        ])

        lines, soft_deleted = drift_mod._pg_records(["m-forgotten"])

        record = json.loads(lines[0])
        assert record["is_active"] is False
        assert record["revisions"] == revisions
        assert soft_deleted == ["m-forgotten"]

    def test_decayed_record_recovers_as_inactive(self, drift_mod, monkeypatch):
        """apply-decay.py and archive-memories.py set decayed_at too."""
        _stub_psql(monkeypatch, drift_mod, [
            _pg_row(
                "m-decayed", is_active=False,
                decayed_at="2026-08-01T00:00:00+00:00",
            ),
        ])
        lines, soft_deleted = drift_mod._pg_records(["m-decayed"])
        assert json.loads(lines[0])["is_active"] is False
        assert soft_deleted == ["m-decayed"]

    def test_active_record_keeps_the_native_shape(self, drift_mod, monkeypatch):
        """
        An ordinary record must NOT gain an ``is_active`` key: the
        docstring promises a recovered line is shaped like a natively
        written one, and the extraction hook omits the field.
        """
        _stub_psql(monkeypatch, drift_mod, [_pg_row("m-active")])
        lines, soft_deleted = drift_mod._pg_records(["m-active"])
        record = json.loads(lines[0])
        assert "is_active" not in record
        assert soft_deleted == []

    def test_history_fields_survive_recovery(self, drift_mod, monkeypatch):
        """``links``, ``revisions``, and ``superseded_by`` are preserved."""
        _stub_psql(monkeypatch, drift_mod, [
            _pg_row(
                "m-linked",
                links=[{"id": "m-other", "relation": "supports"}],
                revisions=[{"revised_at": "2026-09-02T00:00:00+00:00",
                            "action": "update"}],
                superseded_by="m-newer",
            ),
        ])
        record = json.loads(drift_mod._pg_records(["m-linked"])[0][0])
        assert record["links"] == [{"id": "m-other", "relation": "supports"}]
        assert record["revisions"][0]["action"] == "update"
        assert record["superseded_by"] == "m-newer"

    def test_recover_writes_the_inactive_flag_to_the_canonical(
        self, drift_mod, monkeypatch, tmp_path, quiet_log,
    ):
        """End-to-end: the line appended to the canonical is inactive."""
        canonical = tmp_path / "memories.jsonl"
        canonical.write_text("", encoding="utf-8")
        monkeypatch.setattr(drift_mod, "MEMORIES_FILE", canonical)
        _stub_psql(monkeypatch, drift_mod, [
            _pg_row("m-forgotten", is_active=False),
        ])

        result = drift_mod.DriftResult(pg_only=["m-forgotten"])
        assert drift_mod.recover(result, quiet_log) == 1

        written = json.loads(canonical.read_text(encoding="utf-8").strip())
        assert written["is_active"] is False


# ---------------------------------------------------------------------------
# P9 — the recovery append takes the shared canonical lock
# ---------------------------------------------------------------------------


class TestRecoveryTakesTheLock:
    """Every other canonical writer holds a flock; so must this one."""

    def test_recover_waits_for_an_exclusive_holder(
        self, drift_mod, monkeypatch, tmp_path, quiet_log,
    ):
        """
        A bulk rewriter holds ``LOCK_EX`` on the canonical while it
        rewrites and renames. An unlocked appender writes straight into
        the middle of that, and its records — the last surviving copy of
        the data on this code path — are lost with the orphaned inode.

        Deterministic form: the parent holds ``LOCK_EX``, a forked child
        runs ``recover``, and the file must stay empty until the parent
        releases. The mutation this kills: reverting the append to a
        plain ``MEMORIES_FILE.open("a")``.
        """
        canonical = tmp_path / "memories.jsonl"
        canonical.write_text("", encoding="utf-8")
        monkeypatch.setattr(drift_mod, "MEMORIES_FILE", canonical)
        _stub_psql(monkeypatch, drift_mod, [_pg_row("m-recovered")])
        result = drift_mod.DriftResult(pg_only=["m-recovered"])

        def _child() -> None:
            """Run the recovery inside the forked child."""
            drift_mod.recover(result, quiet_log)

        # ``fork`` so the child inherits the monkeypatched module state.
        ctx = multiprocessing.get_context("fork")
        proc = ctx.Process(target=_child)

        holder = os.open(str(canonical), os.O_RDWR)
        try:
            fcntl.flock(holder, fcntl.LOCK_EX)
            proc.start()
            # Ample time for an unlocked appender to finish.
            time.sleep(1.0)
            assert canonical.read_text(encoding="utf-8") == "", (
                "recover wrote to the canonical while a rewriter held "
                "LOCK_EX"
            )
        finally:
            fcntl.flock(holder, fcntl.LOCK_UN)
            os.close(holder)

        proc.join(timeout=30)
        assert proc.exitcode == 0
        written = canonical.read_text(encoding="utf-8").strip()
        assert json.loads(written)["id"] == "m-recovered"

    def test_recovered_lines_land_after_existing_content(
        self, drift_mod, monkeypatch, tmp_path, quiet_log,
    ):
        """Appending, not overwriting: existing records survive."""
        canonical = tmp_path / "memories.jsonl"
        canonical.write_text(
            json.dumps({"id": "m-existing"}) + "\n", encoding="utf-8",
        )
        monkeypatch.setattr(drift_mod, "MEMORIES_FILE", canonical)
        _stub_psql(monkeypatch, drift_mod, [_pg_row("m-recovered")])

        drift_mod.recover(
            drift_mod.DriftResult(pg_only=["m-recovered"]), quiet_log,
        )

        ids = [
            json.loads(line)["id"]
            for line in canonical.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert ids == ["m-existing", "m-recovered"]

    def test_stash_only_lines_are_appended_verbatim(
        self, drift_mod, monkeypatch, tmp_path, quiet_log,
    ):
        """Stash recovery is unchanged by the P8/P9 work."""
        canonical = tmp_path / "memories.jsonl"
        canonical.write_text("", encoding="utf-8")
        monkeypatch.setattr(drift_mod, "MEMORIES_FILE", canonical)
        raw = json.dumps({"id": "m-stashed", "content": "from a stash"})

        count = drift_mod.recover(
            drift_mod.DriftResult(stash_only=[("stash@{0}", [raw])]),
            quiet_log,
        )

        assert count == 1
        assert canonical.read_text(encoding="utf-8").strip() == raw


# ---------------------------------------------------------------------------
# Re-audit lows — short writes, an unbounded retry, and a dropped field
# ---------------------------------------------------------------------------


class TestRecoveryWriteRobustness:
    """The recovery append is the last surviving copy of these records."""

    def test_short_writes_do_not_truncate_a_record(
        self, drift_mod, monkeypatch, tmp_path, quiet_log,
    ):
        """
        ``os.write`` may write fewer bytes than it was given. Ignoring the
        return silently truncated the payload — half a JSON line in the
        canonical, unparseable, and the data gone. The mutation this
        kills: replacing ``_write_all`` with a bare ``os.write``.
        """
        canonical = tmp_path / "memories.jsonl"
        canonical.write_text("", encoding="utf-8")
        monkeypatch.setattr(drift_mod, "MEMORIES_FILE", canonical)
        _stub_psql(monkeypatch, drift_mod, [
            _pg_row("m-one"), _pg_row("m-two"),
        ])

        real_write = os.write

        def _stingy_write(fd, data):
            """Write at most 7 bytes per call, as a slow pipe might."""
            return real_write(fd, bytes(data[:7]))

        monkeypatch.setattr(os, "write", _stingy_write)
        drift_mod.recover(
            drift_mod.DriftResult(pg_only=["m-one", "m-two"]), quiet_log,
        )
        monkeypatch.undo()

        lines = [
            line for line in
            canonical.read_text(encoding="utf-8").splitlines() if line.strip()
        ]
        assert len(lines) == 2
        ids = sorted(json.loads(line)["id"] for line in lines)
        assert ids == ["m-one", "m-two"]

    def test_lock_retry_is_bounded(
        self, drift_mod, monkeypatch, tmp_path,
    ):
        """
        A rewriter renaming in a tight loop would spin the inode-identity
        retry forever. It now gives up loudly. The mutation this kills:
        restoring ``while True``.
        """
        canonical = tmp_path / "memories.jsonl"
        canonical.write_text("", encoding="utf-8")
        real_stat = os.stat

        class _ShiftedInode:
            """A stat result whose inode never matches the open fd's."""

            def __init__(self, real) -> None:
                self.st_ino = real.st_ino + 1

        calls = {"n": 0}
        # Stop faking a little past the retry budget so an unbounded loop
        # ends the test cleanly ("DID NOT RAISE") instead of hanging.
        give_up_after = drift_mod.MAX_LOCK_ATTEMPTS + 5

        def _always_different(path, *args, **kwargs):
            """Fake the inode for the canonical only; delegate otherwise.

            Narrow on purpose: a blanket ``os.stat`` patch also catches
            pytest's own tmp-directory cleanup, which asks for st_mode.
            """
            result = real_stat(path, *args, **kwargs)
            if str(path) == str(canonical) and calls["n"] < give_up_after:
                calls["n"] += 1
                return _ShiftedInode(result)
            return result

        monkeypatch.setattr(os, "stat", _always_different)
        try:
            with pytest.raises(RuntimeError, match="stable handle"):
                with drift_mod._shared_locked_append_fd(canonical):
                    pass
        finally:
            monkeypatch.undo()

        assert calls["n"] == drift_mod.MAX_LOCK_ATTEMPTS, (
            "the retry budget was not honoured exactly"
        )

    def test_decayed_at_is_carried_into_the_recovered_record(
        self, drift_mod, monkeypatch,
    ):
        """
        The decay timestamp is the only surviving evidence of *when* a
        record was retired once PostgreSQL is rebuilt from the canonical.
        The mutation this kills: dropping the ``decayed_at`` assignment.
        """
        _stub_psql(monkeypatch, drift_mod, [
            _pg_row(
                "m-decayed", is_active=False,
                decayed_at="2026-08-01T00:00:00+00:00",
            ),
        ])
        record = json.loads(drift_mod._pg_records(["m-decayed"])[0][0])
        assert record["decayed_at"] == "2026-08-01T00:00:00+00:00"
        assert record["is_active"] is False

    def test_active_record_gains_no_decayed_at(self, drift_mod, monkeypatch):
        """An ordinary record keeps the shape the extraction hook writes."""
        _stub_psql(monkeypatch, drift_mod, [_pg_row("m-active")])
        record = json.loads(drift_mod._pg_records(["m-active"])[0][0])
        assert "decayed_at" not in record


# ---------------------------------------------------------------------------
# Round 4a-2, finding M1 — a recovered record must not plant a raw separator
# ---------------------------------------------------------------------------

#: A Unicode LINE SEPARATOR: legal inside a JSON string, and a line break to
#: ``str.splitlines()`` but not to ``"\n"``-splitting or file iteration.
LINE_SEPARATOR = "\u2028"


class TestRecoveredRecordsStayEscaped:
    """The recovery path appends to the canonical; it must serialise as the
    extraction hook does."""

    def test_separator_in_recovered_content_is_escaped(
        self, drift_mod, monkeypatch,
    ) -> None:
        """Kills ``json.dumps(record)`` -> ``json.dumps(record,
        ensure_ascii=False)``: that writes the separator raw, and the next
        reader that splits on Unicode line boundaries tears the recovered
        record into two unparseable fragments.
        """
        content = f"Recovered paragraph one{LINE_SEPARATOR}paragraph two."
        _stub_psql(monkeypatch, drift_mod,
                   [_pg_row("m-separator", content=content)])

        lines, _soft_deleted = drift_mod._pg_records(["m-separator"])

        assert len(lines) == 1
        assert LINE_SEPARATOR not in lines[0], "the separator must stay escaped"
        assert "\\u2028" in lines[0]
        assert json.loads(lines[0])["content"] == content

    def test_recovered_line_survives_a_newline_split(
        self, drift_mod, monkeypatch, tmp_path, quiet_log,
    ) -> None:
        """The appended file still has one line per recovered record."""
        content = f"Trench A{LINE_SEPARATOR}Trench B."
        _stub_psql(monkeypatch, drift_mod,
                   [_pg_row("m-sep-a", content=content),
                    _pg_row("m-sep-b")])
        canonical = tmp_path / "memories.jsonl"
        canonical.write_text("", encoding="utf-8")
        monkeypatch.setattr(drift_mod, "MEMORIES_FILE", canonical)

        result = drift_mod.DriftResult(pg_only=["m-sep-a", "m-sep-b"])
        assert drift_mod.recover(result, quiet_log) == 2

        written = canonical.read_text(encoding="utf-8")
        assert written.count("\n") == 2
        assert LINE_SEPARATOR not in written
