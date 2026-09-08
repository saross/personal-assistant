"""
Tests for ``scripts/_sync_cursor.py`` — the shared quarantine and
cursor-file helpers used by every sync script.

Audit round two:

* Finding P14 (lens A-M12) — ``quarantine_record`` appended
  unconditionally, so a halted cursor re-quarantined the same poison line
  on every five-minute cron tick (288 duplicate entries per line per day).
* Finding P16 (lens A-M14) — three processes read-modify-write
  ``memories/sync-cursors.json`` with neither a lock nor an atomic
  rename, so an interleaving lost a cursor advance and a kill part-way
  through a write truncated every cursor at once.

No database, no network: these exercise filesystem behaviour only.
"""

from __future__ import annotations

import fcntl
import json
import multiprocessing
import os
import sys
import time
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import _sync_cursor  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_fingerprint_cache():
    """Start every test with an empty quarantine-fingerprint cache."""
    _sync_cursor._FINGERPRINT_CACHE.clear()
    yield
    _sync_cursor._FINGERPRINT_CACHE.clear()


def _entries(path: Path) -> list[dict]:
    """Read a quarantine file back into a list of entry dicts."""
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ============================================================================
# P14 — quarantine dedup
# ============================================================================


class TestQuarantineDedup:
    """``quarantine_record`` must not re-append an identical entry."""

    def test_repeated_identical_record_appends_once(self, tmp_path: Path) -> None:
        """
        The exact A-M12 shape: a halted cursor re-reads the same slice
        every tick, so the same ``(reason, record)`` pair arrives over and
        over. Only the first append should reach disk.
        """
        quarantine = tmp_path / "quarantine.jsonl"
        record = {"line_number": 42, "raw_line": '{"id": "broken"'}

        for _ in range(12):  # one hour of five-minute cron ticks
            assert _sync_cursor.quarantine_record(
                quarantine, record, "parse_failure",
            ) is True

        assert len(_entries(quarantine)) == 1

    def test_dedup_survives_a_fresh_process_cache(self, tmp_path: Path) -> None:
        """
        Dedup must read the file, not merely remember this process's own
        appends — cron starts a new process every tick.
        """
        quarantine = tmp_path / "quarantine.jsonl"
        record = {"line_number": 7, "raw_line": "poison"}

        _sync_cursor.quarantine_record(quarantine, record, "parse_failure")
        _sync_cursor._FINGERPRINT_CACHE.clear()  # simulate a new process
        _sync_cursor.quarantine_record(quarantine, record, "parse_failure")

        assert len(_entries(quarantine)) == 1

    def test_distinct_records_are_all_kept(self, tmp_path: Path) -> None:
        """Dedup keys on the whole ``(reason, record)`` pair, nothing coarser."""
        quarantine = tmp_path / "quarantine.jsonl"
        _sync_cursor.quarantine_record(
            quarantine, {"line_number": 1, "raw_line": "a"}, "parse_failure",
        )
        _sync_cursor.quarantine_record(
            quarantine, {"line_number": 2, "raw_line": "a"}, "parse_failure",
        )
        _sync_cursor.quarantine_record(
            quarantine, {"line_number": 1, "raw_line": "a"}, "missing_id",
        )

        assert len(_entries(quarantine)) == 3

    def test_key_order_does_not_defeat_dedup(self, tmp_path: Path) -> None:
        """Two dicts differing only in key order are one entry."""
        quarantine = tmp_path / "quarantine.jsonl"
        _sync_cursor.quarantine_record(
            quarantine, {"a": 1, "b": 2}, "parse_failure",
        )
        _sync_cursor._FINGERPRINT_CACHE.clear()
        _sync_cursor.quarantine_record(
            quarantine, {"b": 2, "a": 1}, "parse_failure",
        )

        assert len(_entries(quarantine)) == 1

    def test_dedup_can_be_disabled(self, tmp_path: Path) -> None:
        """``dedup=False`` restores the old append-always behaviour."""
        quarantine = tmp_path / "quarantine.jsonl"
        for _ in range(3):
            _sync_cursor.quarantine_record(
                quarantine, {"x": 1}, "parse_failure", dedup=False,
            )
        assert len(_entries(quarantine)) == 3

    def test_entry_shape_is_unchanged(self, tmp_path: Path) -> None:
        """The declared schema (reason/quarantined_at/record) still holds."""
        quarantine = tmp_path / "quarantine.jsonl"
        _sync_cursor.quarantine_record(quarantine, {"x": 1}, "parse_failure")
        entry = _entries(quarantine)[0]
        assert set(entry) == {"reason", "quarantined_at", "record"}
        assert entry["reason"] == "parse_failure"
        assert entry["record"] == {"x": 1}


# ============================================================================
# P16 — atomic, locked cursor writes
# ============================================================================


def _child_update(args: tuple[str, str, int]) -> None:
    """Set one cursor key from a separate process (module-level for pickling)."""
    cursor_path, key, value = args
    _sync_cursor.update_cursor_file(Path(cursor_path), {key: value})


class TestCursorFileUpdates:
    """``update_cursor_file`` — merge semantics, atomicity, and locking."""

    def test_merges_without_dropping_other_keys(self, tmp_path: Path) -> None:
        """Setting one cursor must preserve the other two syncs' cursors."""
        cursor = tmp_path / "sync-cursors.json"
        cursor.write_text(
            json.dumps({
                "postgres_sync_line": 10,
                "sessions_sync_timestamp": "2026-09-01T00:00:00",
                "zotero_sync_line": 3,
            }),
            encoding="utf-8",
        )

        _sync_cursor.update_cursor_file(cursor, {"postgres_sync_line": 11})

        data = json.loads(cursor.read_text(encoding="utf-8"))
        assert data == {
            "postgres_sync_line": 11,
            "sessions_sync_timestamp": "2026-09-01T00:00:00",
            "zotero_sync_line": 3,
        }

    def test_creates_the_file_when_missing(self, tmp_path: Path) -> None:
        """A first run with no cursor file writes a complete object."""
        cursor = tmp_path / "nested" / "sync-cursors.json"
        _sync_cursor.update_cursor_file(cursor, {"postgres_sync_line": 1})
        assert json.loads(cursor.read_text(encoding="utf-8")) == {
            "postgres_sync_line": 1,
        }

    def test_corrupt_file_is_replaced_not_appended_to(self, tmp_path: Path) -> None:
        """A truncated/corrupt cursor file yields a clean object."""
        cursor = tmp_path / "sync-cursors.json"
        cursor.write_text('{"postgres_sync_line": 1', encoding="utf-8")
        _sync_cursor.update_cursor_file(cursor, {"postgres_sync_line": 5})
        assert json.loads(cursor.read_text(encoding="utf-8")) == {
            "postgres_sync_line": 5,
        }

    def test_delete_keys_removes_only_those_keys(self, tmp_path: Path) -> None:
        """``delete_keys`` supports the rebuild script's reset semantics."""
        cursor = tmp_path / "sync-cursors.json"
        cursor.write_text(
            json.dumps({"a": 1, "b": 2, "c": 3}), encoding="utf-8",
        )
        _sync_cursor.update_cursor_file(cursor, delete_keys=("b", "missing"))
        assert json.loads(cursor.read_text(encoding="utf-8")) == {"a": 1, "c": 3}

    def test_write_leaves_no_temp_file_behind(self, tmp_path: Path) -> None:
        """The temp file used for the atomic rename must not survive."""
        cursor = tmp_path / "sync-cursors.json"
        _sync_cursor.update_cursor_file(cursor, {"postgres_sync_line": 1})
        strays = [
            p.name for p in tmp_path.iterdir()
            if p.name.startswith("sync-cursors.json") and p.suffix == ".tmp"
        ]
        assert strays == []

    def test_no_partial_file_is_ever_visible(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        A write that dies part-way must leave the previous cursor intact.

        This is the truncation half of A-M14: ``write_text`` opened the
        real path with ``"w"``, so a kill between truncate and write reset
        every cursor in the file to nothing.
        """
        cursor = tmp_path / "sync-cursors.json"
        original = {"postgres_sync_line": 10, "zotero_sync_line": 3}
        cursor.write_text(json.dumps(original), encoding="utf-8")

        def _boom(src, dst):
            raise KeyboardInterrupt("killed mid-write")

        monkeypatch.setattr(os, "replace", _boom)
        with pytest.raises(KeyboardInterrupt):
            _sync_cursor.update_cursor_file(cursor, {"postgres_sync_line": 11})

        # The old content survives in full — no truncation, no data loss.
        assert json.loads(cursor.read_text(encoding="utf-8")) == original

    def test_a_second_process_waits_for_the_lock(self, tmp_path: Path) -> None:
        """
        A writer must block while another holds the cursor lock.

        This is the interleaving half of A-M14, made deterministic: the
        parent holds ``cursor_file_lock``, a child calls
        ``update_cursor_file``, and the file must stay untouched until the
        parent releases. Unlocked read-modify-write (the old shape)
        finishes immediately and the assertion inside the lock fails.
        """
        cursor = tmp_path / "sync-cursors.json"
        cursor.write_text(
            json.dumps({"postgres_sync_line": 1}), encoding="utf-8",
        )

        ctx = multiprocessing.get_context("fork")
        proc = ctx.Process(
            target=_child_update,
            args=((str(cursor), "postgres_sync_line", 2),),
        )
        with _sync_cursor.cursor_file_lock(cursor):
            proc.start()
            # Give the child ample time to run to completion if nothing
            # were serialising it.
            time.sleep(1.0)
            held = json.loads(cursor.read_text(encoding="utf-8"))
            assert held == {"postgres_sync_line": 1}, (
                "the child wrote while another process held the lock"
            )
        proc.join(timeout=30)

        assert proc.exitcode == 0
        assert json.loads(cursor.read_text(encoding="utf-8")) == {
            "postgres_sync_line": 2,
        }


class TestReadCursorFile:
    """``read_cursor_file`` degrades to ``{}`` rather than raising."""

    def test_missing_file(self, tmp_path: Path) -> None:
        """No file at all reads as an empty cursor object."""
        assert _sync_cursor.read_cursor_file(tmp_path / "nope.json") == {}

    def test_malformed_json(self, tmp_path: Path) -> None:
        """Malformed JSON reads as empty rather than raising."""
        path = tmp_path / "sync-cursors.json"
        path.write_text("{not json", encoding="utf-8")
        assert _sync_cursor.read_cursor_file(path) == {}

    def test_non_object_json(self, tmp_path: Path) -> None:
        """A JSON array is not a cursor object; treat it as empty."""
        path = tmp_path / "sync-cursors.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        assert _sync_cursor.read_cursor_file(path) == {}


# ============================================================================
# Re-audit finding M3 — compare-and-set against a concurrent rebuild
# ============================================================================


class TestCompareAndSet:
    """A key a rebuild removed must not be written back."""

    def test_missing_expected_key_raises(self, tmp_path: Path) -> None:
        """
        The rebuild cleared the cursors while a sync was mid-cycle.
        Writing the sync's position back would tell the next run that rows
        the rebuild destroyed are already synced. The mutation this kills:
        ignoring ``expect_present``.
        """
        cursor = tmp_path / "sync-cursors.json"
        cursor.write_text(json.dumps({"other": 1}), encoding="utf-8")

        with pytest.raises(_sync_cursor.CursorKeyVanished):
            _sync_cursor.update_cursor_file(
                cursor, {"postgres_sync_line": 99},
                expect_present=("postgres_sync_line",),
            )

        # And nothing was written.
        assert json.loads(cursor.read_text(encoding="utf-8")) == {"other": 1}

    def test_present_key_is_written(self, tmp_path: Path) -> None:
        """The ordinary path: the key is still there, so the write lands."""
        cursor = tmp_path / "sync-cursors.json"
        cursor.write_text(
            json.dumps({"postgres_sync_line": 10}), encoding="utf-8",
        )
        _sync_cursor.update_cursor_file(
            cursor, {"postgres_sync_line": 11},
            expect_present=("postgres_sync_line",),
        )
        assert json.loads(
            cursor.read_text(encoding="utf-8")
        )["postgres_sync_line"] == 11

    def test_first_ever_write_is_allowed(self, tmp_path: Path) -> None:
        """
        With no ``expect_present`` a missing key is fine — that is a first
        run, or the first run after a deliberate rebuild.
        """
        cursor = tmp_path / "sync-cursors.json"
        _sync_cursor.update_cursor_file(cursor, {"postgres_sync_line": 1})
        assert json.loads(
            cursor.read_text(encoding="utf-8")
        )["postgres_sync_line"] == 1

    def test_apply_cursor_update_does_not_take_the_lock(
        self, tmp_path: Path,
    ) -> None:
        """
        ``apply_cursor_update`` is for callers already holding the lock.
        Taking it again would deadlock — flock is per open file
        description, so a second ``open`` in the same process conflicts
        with the first.
        """
        cursor = tmp_path / "sync-cursors.json"
        cursor.write_text(json.dumps({"a": 1}), encoding="utf-8")
        with _sync_cursor.cursor_file_lock(cursor):
            _sync_cursor.apply_cursor_update(cursor, {"b": 2})
        assert json.loads(cursor.read_text(encoding="utf-8")) == {"a": 1, "b": 2}


class TestDurability:
    """Re-audit, low finding: the rename must be durable, not just the data."""

    def test_parent_directory_is_fsynced_after_the_rename(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        Without an fsync on the directory, a power failure can lose the
        rename even though the new file's contents reached the disk — the
        cursor silently reverts to its pre-write value. The mutation this
        kills: removing the directory fsync after ``os.replace``.
        """
        cursor = tmp_path / "sync-cursors.json"
        fsynced_dirs: list[str] = []
        real_fsync = os.fsync

        def _record_fsync(fd: int) -> None:
            try:
                if os.path.isdir(f"/proc/self/fd/{fd}"):
                    fsynced_dirs.append(os.readlink(f"/proc/self/fd/{fd}"))
            except OSError:  # pragma: no cover — platform variation
                pass
            real_fsync(fd)

        monkeypatch.setattr(os, "fsync", _record_fsync)
        _sync_cursor.update_cursor_file(cursor, {"postgres_sync_line": 1})
        monkeypatch.undo()

        assert str(tmp_path) in fsynced_dirs, (
            f"the cursor file's directory was never fsynced: {fsynced_dirs}"
        )


class TestLockedRead:
    """Low finding L1 — the compare-and-set needs one atomic observation."""

    def test_read_is_taken_under_the_lock(self, tmp_path: Path) -> None:
        """
        Reading the position and the key's presence with two unlocked
        calls leaves a window in which a rebuild lands between them. The
        mutation this kills: replacing ``read_cursor_file_locked`` with a
        plain ``read_cursor_file``.
        """
        cursor = tmp_path / "sync-cursors.json"
        cursor.write_text(
            json.dumps({"postgres_sync_line": 7}), encoding="utf-8",
        )
        lock_path = cursor.with_name(cursor.name + ".lock")
        observed = {"locked": None}

        real_read = _sync_cursor.read_cursor_file

        def _probe(path):
            """Check, from inside the read, that the lock is held."""
            with open(lock_path, "a", encoding="utf-8") as probe:
                try:
                    fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    observed["locked"] = True
                else:
                    observed["locked"] = False
                    fcntl.flock(probe.fileno(), fcntl.LOCK_UN)
            return real_read(path)

        _sync_cursor.read_cursor_file = _probe
        try:
            data = _sync_cursor.read_cursor_file_locked(cursor)
        finally:
            _sync_cursor.read_cursor_file = real_read

        assert data == {"postgres_sync_line": 7}
        assert observed["locked"] is True, (
            "the cursor was read without holding the lock"
        )
