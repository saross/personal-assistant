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
import logging
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

        statuses = [
            _sync_cursor.quarantine_record(quarantine, record, "parse_failure")
            for _ in range(12)  # one hour of five-minute cron ticks
        ]

        assert len(_entries(quarantine)) == 1
        # The first call wrote; the rest reported the duplicate, which is
        # what lets a caller count what actually reached the file rather
        # than what it attempted (sixth re-audit, finding M4).
        assert statuses[0] == _sync_cursor.QUARANTINE_WRITTEN
        assert set(statuses[1:]) == {_sync_cursor.QUARANTINE_DUPLICATE}

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


class TestQuarantineStatuses:
    """
    Finding M4 — a caller counting quarantined rows must count what
    reached the file, and only ``quarantine_record`` knows which is which.
    """

    def test_a_failed_write_is_distinguishable(self, tmp_path: Path) -> None:
        """
        Failure is not a duplicate and not a success: the caller must be
        able to hold its cursor on one and advance on the other. The
        mutation this kills: collapsing the three statuses to a boolean.
        """
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        status = _sync_cursor.quarantine_record(
            blocker / "q.jsonl", {"x": 1}, "parse_failure",
        )
        assert status == _sync_cursor.QUARANTINE_FAILED

    def test_the_three_statuses_are_distinct(self) -> None:
        """They are compared by value all over the sync scripts."""
        assert len({
            _sync_cursor.QUARANTINE_WRITTEN,
            _sync_cursor.QUARANTINE_DUPLICATE,
            _sync_cursor.QUARANTINE_FAILED,
        }) == 3


# ---------------------------------------------------------------------------
# Ninth re-audit, finding M1 — a file that is not there is not a file with
# nothing in it
# ---------------------------------------------------------------------------


class TestCountingQuarantineEntries:
    """
    The gate derives its standing problem from this number, so what the
    function says about a file it cannot see decides whether a real alarm
    survives. A missing quarantine file means the data submodule is
    unmounted far more often than it means the rows were repaired.
    """

    def test_a_missing_file_is_unknown_not_empty(self, tmp_path):
        """
        The mutation this kills: returning 0 for a missing file — the
        gate then lowers every quarantine problem on the machine at the
        next cron tick after the submodule is unmounted.
        """
        assert _sync_cursor.count_quarantine_entries(
            tmp_path / "never-created.jsonl",
        ) is None

    def test_an_unreadable_file_is_unknown(self, tmp_path):
        """A directory where a file should be reads as unknown, not zero."""
        blocker = tmp_path / "quarantine.jsonl"
        blocker.mkdir()
        assert _sync_cursor.count_quarantine_entries(blocker) is None

    def test_an_empty_file_is_zero(self, tmp_path):
        """
        A file that exists and holds nothing IS zero — the guard must not
        amount to never reporting a cleared quarantine.
        """
        path = tmp_path / "quarantine.jsonl"
        path.write_text("", encoding="utf-8")
        assert _sync_cursor.count_quarantine_entries(path) == 0

    def test_blank_lines_are_not_entries(self, tmp_path):
        """The mutation this kills: counting every line, blanks included."""
        path = tmp_path / "quarantine.jsonl"
        path.write_text(
            '{"reason": "a"}\n\n   \n{"reason": "b"}\n\n', encoding="utf-8",
        )
        assert _sync_cursor.count_quarantine_entries(path) == 2

    def test_an_unparseable_line_is_not_an_entry(self, tmp_path):
        """
        The count must equal what an operator can actually find and
        replay — which is what the dedup layer already considers present.
        A line of damage is not a quarantined row. The mutation this
        kills: counting any non-blank line.
        """
        path = tmp_path / "quarantine.jsonl"
        path.write_text(
            '{"reason": "a"}\nnot json at all\n["not", "an", "object"]\n'
            '{"reason": "b"}\n',
            encoding="utf-8",
        )
        assert _sync_cursor.count_quarantine_entries(path) == 2

    def test_a_complete_last_row_with_no_newline_is_counted(self, tmp_path):
        """
        An interrupted write that reached the closing brace produced a
        whole record; the missing newline is a separator problem, not a
        content one. Counting it as nothing made that row invisible to
        the gate for ever, because the deduper still matched it and so
        the row was never written again (tenth re-audit, finding C1).

        The mutation this kills: skipping a trailing line that has no
        newline.
        """
        path = tmp_path / "quarantine.jsonl"
        path.write_text(
            '{"reason": "a"}\n{"reason": "b"}\n{"reason": "c"}',
            encoding="utf-8",
        )
        assert _sync_cursor.count_quarantine_entries(path) == 3

    def test_a_leading_byte_order_mark_hides_no_row(self, tmp_path):
        """
        A file saved as UTF-8-with-BOM must not lose its first record.

        The mark glued itself to the opening brace, ``json.loads``
        rejected ``\ufeff{...}``, and the FIRST quarantined row then
        vanished from every reader at once: uncounted by the gate,
        unmatched by the duplicate check — so a re-offered row appended a
        second copy on every tick — and absent from ``/memory-health``.
        Consistency between the readers was never the issue; they agreed,
        and all three were wrong (eleventh re-audit follow-up L6).

        The mutation this kills: decoding as ``utf-8`` in
        ``read_quarantine_entries``.
        """
        path = tmp_path / "quarantine.jsonl"
        path.write_bytes(
            "\ufeff".encode("utf-8")
            + b'{"reason": "adaptation", "record": {"id": "m1"}}\n'
            + b'{"reason": "adaptation", "record": {"id": "m2"}}\n'
        )

        assert _sync_cursor.count_quarantine_entries(path) == 2
        entries = _sync_cursor.read_quarantine_entries(path)
        assert [entry["record"]["id"] for entry in entries] == ["m1", "m2"]

        # The consequence that costs an operator: the hidden row was
        # re-quarantined on every cron tick, because the duplicate check
        # could not see it either.
        status = _sync_cursor.quarantine_record(
            path, {"id": "m1"}, "adaptation",
        )
        assert status == _sync_cursor.QUARANTINE_DUPLICATE
        assert _sync_cursor.count_quarantine_entries(path) == 2

    def test_a_truly_partial_last_line_is_not_counted(self, tmp_path):
        """
        A write cut off mid-record is not a record. The mutation this
        kills: counting anything non-blank.
        """
        path = tmp_path / "quarantine.jsonl"
        path.write_text(
            '{"reason": "a"}\n{"reason": "b"}\n{"reason": "hal',
            encoding="utf-8",
        )
        assert _sync_cursor.count_quarantine_entries(path) == 2

    def test_a_new_row_after_an_unterminated_one_starts_its_own_line(
        self, tmp_path,
    ):
        """
        A complete row that lost its newline is still a row, so the next
        append must not run onto the end of it — that would turn two
        records into one unreadable line and lose them both. The mutation
        this kills: dropping the separator when the trailing line parses.
        """
        path = tmp_path / "quarantine.jsonl"
        path.write_text('{"reason": "a", "record": 1}', encoding="utf-8")
        _sync_cursor._FINGERPRINT_CACHE.clear()

        _sync_cursor.quarantine_record(path, {"id": "m2"}, "refused")

        assert _sync_cursor.count_quarantine_entries(path) == 2
        for line in path.read_text(encoding="utf-8").splitlines():
            json.loads(line)

    def test_the_counter_and_the_deduper_never_disagree(self, tmp_path):
        """
        The invariant behind finding C1: a row either counts and dedups,
        or does neither. Any file where one says "present" and the other
        says "absent" leaves that row permanently invisible to the gate —
        the deduper refuses to write it again, so the count never rises.

        The mutation this kills: giving either reader its own parsing
        rule.
        """
        cases = {
            "complete rows": '{"reason": "a", "record": 1}\n'
                             '{"reason": "b", "record": 2}\n',
            "last row unterminated": '{"reason": "a", "record": 1}\n'
                                     '{"reason": "b", "record": 2}',
            "damaged last row": '{"reason": "a", "record": 1}\n{"reason": "b',
            "blank lines about": '\n{"reason": "a", "record": 1}\n\n  \n',
            "a non-object line": '{"reason": "a", "record": 1}\n[1, 2]\n',
            "nothing at all": "",
        }
        for label, body in cases.items():
            path = tmp_path / f"q-{abs(hash(label))}.jsonl"
            path.write_text(body, encoding="utf-8")
            _sync_cursor._FINGERPRINT_CACHE.clear()

            counted = _sync_cursor.count_quarantine_entries(path)
            fingerprinted = _sync_cursor._existing_fingerprints(path)

            assert counted == len(fingerprinted), (
                f"{label}: the gate counts {counted} and the deduper sees "
                f"{len(fingerprinted)}"
            )

    def test_a_row_whose_newline_was_lost_is_not_written_twice(
        self, tmp_path,
    ):
        """
        The other half of the invariant: the row counts, AND a re-offer
        of it is recognised as a duplicate. The mutation this kills:
        making the deduper skip the trailing line, which turns every
        interrupted write into a second copy.
        """
        path = tmp_path / "quarantine.jsonl"
        _sync_cursor.quarantine_record(path, {"id": "m1"}, "refused")
        # Strip the trailing newline, as a killed write would leave it.
        text = path.read_text(encoding="utf-8")
        path.write_text(text.rstrip("\n"), encoding="utf-8")
        _sync_cursor._FINGERPRINT_CACHE.clear()

        assert _sync_cursor.count_quarantine_entries(path) == 1

        status = _sync_cursor.quarantine_record(path, {"id": "m1"}, "refused")

        assert status == _sync_cursor.QUARANTINE_DUPLICATE
        assert _sync_cursor.count_quarantine_entries(path) == 1

    def test_an_append_repairs_a_half_written_last_line(self, tmp_path):
        """
        The next append must start a fresh line rather than joining onto
        the partial one, which would turn two entries into one
        unparseable line. The mutation this kills: dropping the
        ``_ends_mid_line`` repair.
        """
        path = tmp_path / "quarantine.jsonl"
        path.write_text(
            '{"reason": "a", "record": 1}\n{"reason": "half',
            encoding="utf-8",
        )

        status = _sync_cursor.quarantine_record(path, {"id": "m2"}, "b")

        assert status == _sync_cursor.QUARANTINE_WRITTEN
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3, lines
        assert lines[1] == '{"reason": "half'
        json.loads(lines[2])
        # The complete entries either side of the damage are countable,
        # and the damaged line is not one of them.
        assert _sync_cursor.count_quarantine_entries(path) == 2


# ---------------------------------------------------------------------------
# Tenth re-audit, finding M1 — every reader must reach the same conclusion
# about a cursor of the wrong type
# ---------------------------------------------------------------------------


class TestNormalisingACursor:
    """
    The cursor file is JSON a rebuild, a merge, or a person can rewrite,
    so its type is not guaranteed. The cycle used to accept the string
    "500" while the gate's type filter rejected it, so the gate saw the
    cursor vanish and reported a rebuild that had not happened.
    """

    @pytest.mark.parametrize("value,expected", [
        (0, 0),
        (500, 500),
        ("500", 500),
        ("  500  ", 500),
        (None, None),
        (-1, None),
        (True, None),        # a bool is an int in Python, never a line
        ("five hundred", None),
        ("5.0", None),
        (5.0, None),
        ({}, None),
        ([], None),
    ])
    def test_a_line_cursor(self, value, expected):
        """The mutation this kills: dropping the digit-string coercion."""
        assert _sync_cursor.normalise_line_cursor(value) == expected

    @pytest.mark.parametrize("value,expected", [
        ("2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z"),
        (None, None),
        ("", None),
        (500, None),
        ({}, None),
    ])
    def test_a_timestamp_cursor(self, value, expected):
        """The sessions cursor is compared lexically; a number is not one."""
        assert _sync_cursor.normalise_timestamp_cursor(value) == expected

    def test_garbage_is_warned_about_but_a_digit_string_is_not(self, caplog):
        """
        Coercing "500" is silent because it is unambiguously the same
        position. Real garbage gets a warning: a cursor nobody can read
        is a problem, and resyncing from zero without saying so hides it.

        The mutation this kills: dropping the warning.
        """
        logger = logging.getLogger("test-normalise")
        with caplog.at_level(logging.WARNING):
            assert _sync_cursor.normalise_line_cursor(
                "500", key="postgres_sync_line", logger=logger,
            ) == 500
        assert caplog.text == ""

        with caplog.at_level(logging.WARNING):
            assert _sync_cursor.normalise_line_cursor(
                {"line": 5}, key="postgres_sync_line", logger=logger,
            ) is None
        assert "not a line number" in caplog.text
        assert "postgres_sync_line" in caplog.text

    def test_an_absent_cursor_is_not_warned_about(self, caplog):
        """A first-ever run has no cursor and that is ordinary."""
        logger = logging.getLogger("test-normalise-absent")
        with caplog.at_level(logging.WARNING):
            assert _sync_cursor.normalise_line_cursor(
                None, logger=logger,
            ) is None
            assert _sync_cursor.normalise_timestamp_cursor(
                None, logger=logger,
            ) is None
        assert caplog.text == ""


# ---------------------------------------------------------------------------
# Eleventh re-audit, finding C1 — one appender, and it repairs the separator
# ---------------------------------------------------------------------------


class TestThereIsOnlyOneAppender:
    """
    The append has a precondition — a file that ends mid-line needs its
    separator first — and a second writer that did not know about it ran
    its record onto the end of a complete row whose newline had been
    lost. Both then vanished from the gate, the health report, the
    duplicate check and the acknowledgement at once.
    """

    def test_the_bare_row_writer_repairs_the_separator(self, tmp_path):
        """
        The end-to-end shape of the defect: ``_write_quarantine`` appends
        an unexpected drop onto a file whose last row lost its newline.
        Both records must survive and both must be countable.

        The mutation this kills: appending directly instead of through
        ``append_quarantine_entry``.
        """
        import importlib.util

        scripts = Path(__file__).resolve().parent.parent / "scripts"
        spec = importlib.util.spec_from_file_location(
            "sync_to_postgres_c1", scripts / "sync-to-postgres.py",
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["sync_to_postgres_c1"] = module
        spec.loader.exec_module(module)

        path = tmp_path / "quarantine.jsonl"
        # A complete row whose newline was lost — which the counter now
        # counts, which is exactly why running onto it loses two rows.
        path.write_text('{"id": "m-first"}', encoding="utf-8")
        module.QUARANTINE_FILE = path
        _sync_cursor._FINGERPRINT_CACHE.clear()

        assert _sync_cursor.count_quarantine_entries(path) == 1

        module._write_quarantine(
            [{"id": "m-second"}], logging.getLogger("test-c1"),
        )

        assert _sync_cursor.count_quarantine_entries(path) == 2, (
            "the new record was run onto the end of the old one"
        )
        for line in path.read_text(encoding="utf-8").splitlines():
            json.loads(line)
        ids = {
            entry.get("id")
            for entry in _sync_cursor.read_quarantine_entries(path)
        }
        assert ids == {"m-first", "m-second"}

    def test_the_appender_repairs_the_separator(self, tmp_path):
        """The unit of the same property, without a script around it."""
        path = tmp_path / "quarantine.jsonl"
        path.write_text('{"id": "a"}', encoding="utf-8")

        assert _sync_cursor.append_quarantine_entry(path, {"id": "b"}) is True

        assert _sync_cursor.count_quarantine_entries(path) == 2
        assert path.read_text(encoding="utf-8").endswith("\n")

    def test_the_appender_reports_a_failure(self, tmp_path):
        """A directory where the file should be is not a silent success."""
        blocked = tmp_path / "quarantine.jsonl"
        blocked.mkdir()
        assert _sync_cursor.append_quarantine_entry(blocked, {"id": "a"}) is (
            False
        )

    def test_no_script_appends_to_a_quarantine_file_itself(self):
        """
        Structural guard: only ``_sync_cursor`` may open a quarantine
        path in append mode. Written because the second writer sat six
        hundred lines from the first and nothing connected them.

        The mutation this kills: opening QUARANTINE_FILE with "a"
        anywhere else.
        """
        import ast

        scripts = Path(__file__).resolve().parent.parent / "scripts"
        offenders: list[str] = []
        for script in sorted(scripts.glob("*.py")):
            if script.name == "_sync_cursor.py":
                continue
            tree = ast.parse(script.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "open"
                ):
                    continue
                target = ast.unparse(node.func.value).lower()
                if "quarantine" not in target:
                    continue
                mode = ast.unparse(node.args[0]) if node.args else ""
                if "a" in mode:
                    offenders.append(f"{script.name}:{node.lineno}")
        assert not offenders, (
            f"a quarantine file is appended to outside the one appender: "
            f"{offenders}"
        )


class TestOneSpellingForATimestamp:
    """
    Eleventh re-audit, L2 — the gate's rebuild check and the cycle's
    newer-than-the-cursor filter both compare ISO instants as text, and
    they were normalising differently. A helper used by only one of two
    readers is a difference of opinion waiting to happen.
    """

    @pytest.mark.parametrize("value,expected", [
        ("2026-09-01T00:00:00Z", "2026-09-01T00:00:00+00:00"),
        ("2026-09-01T00:00:00z", "2026-09-01T00:00:00+00:00"),
        ("2026-09-01T00:00:00+00:00", "2026-09-01T00:00:00+00:00"),
        # Naive is a PREFIX of aware, so it sorts first without this.
        ("2026-09-01T00:00:00", "2026-09-01T00:00:00+00:00"),
        ("2026-09-01T00:00:00+10:00", "2026-09-01T00:00:00+10:00"),
        ("2026-09-01T00:00:00-05:00", "2026-09-01T00:00:00-05:00"),
        ("  2026-09-01T00:00:00Z  ", "2026-09-01T00:00:00+00:00"),
        ("", ""),
    ])
    def test_the_spellings_collapse(self, value, expected):
        """The mutation this kills: handling only an upper-case Z."""
        assert _sync_cursor.comparable_timestamp(value) == expected

    def test_every_spelling_of_one_instant_compares_equal(self):
        """The property the helper exists for, stated directly."""
        spellings = [
            "2026-09-01T00:00:00Z",
            "2026-09-01T00:00:00z",
            "2026-09-01T00:00:00+00:00",
            "2026-09-01T00:00:00",
        ]
        canonical = {
            _sync_cursor.comparable_timestamp(s) for s in spellings
        }
        assert len(canonical) == 1, canonical

    def test_the_gate_and_the_cycle_use_the_same_helper(self):
        """
        Structural: two readers of the same order must share the code
        that defines it. The mutation this kills: either of them growing
        its own ``.replace("Z", ...)`` again.
        """
        scripts = Path(__file__).resolve().parent.parent / "scripts"
        for name in ("_sync_gate.py", "sync-sessions-to-postgres.py"):
            source = (scripts / name).read_text(encoding="utf-8")
            assert "comparable_timestamp" in source, (
                f"{name} does not use the shared helper"
            )
            assert 'replace("Z", "+00:00")' not in source, (
                f"{name} normalises timestamps on its own again"
            )


class TestATimestampCursorMustBeATimestamp:
    """
    Eleventh re-audit, M1 — any non-empty string was accepted. ``'abc'``
    sorts after every real ISO timestamp, so the sessions sync skipped
    every session it found, reported itself idle, and did that for ever
    with nothing on the gate.
    """

    @pytest.mark.parametrize("value", [
        "2026-09-01T00:00:00Z",
        "2026-09-01T00:00:00+00:00",
        "2026-09-01T00:00:00",
        "2026-09-01T00:00:00.123456+00:00",
        "2026-09-01",
    ])
    def test_a_real_timestamp_is_kept_verbatim(self, value):
        """
        Accepted, and returned unchanged: the cursor file's own spelling
        is what gets compared and written back.
        """
        assert _sync_cursor.normalise_timestamp_cursor(value) == value

    @pytest.mark.parametrize("value", [
        "abc",
        "TBD",
        "2026-13-45T99:99:99Z",
        "yesterday",
        "  ",
        "2026/09/01",
    ])
    def test_anything_else_is_absent(self, value):
        """The mutation this kills: accepting any non-empty string."""
        assert _sync_cursor.normalise_timestamp_cursor(value) is None

    def test_the_rejection_is_warned_about(self, caplog):
        """A cursor nobody can read is a problem, not a quiet reset."""
        logger = logging.getLogger("test-ts-cursor")
        with caplog.at_level(logging.WARNING):
            assert _sync_cursor.normalise_timestamp_cursor(
                "abc", key="sessions_sync_archived_at", logger=logger,
            ) is None
        assert "not an ISO-8601 timestamp" in caplog.text
        assert "sessions_sync_archived_at" in caplog.text


class TestANegativeLineCursorIsReported:
    """
    Eleventh re-audit, M3 — a negative line cursor returned None from
    the first branch, before the warning, so it silently reset the
    acknowledged quarantine position and re-raised rows a human had
    dismissed. The docstring had always promised a warning.
    """

    def test_it_is_warned_about(self, caplog):
        """The mutation this kills: returning None before the warning."""
        logger = logging.getLogger("test-neg-cursor")
        with caplog.at_level(logging.WARNING):
            assert _sync_cursor.normalise_line_cursor(
                -17, key="postgres_sync_line", logger=logger,
            ) is None
        assert "not a line number" in caplog.text
        assert "postgres_sync_line" in caplog.text

    def test_zero_is_still_a_position(self, caplog):
        """Nothing synced yet is an ordinary state, not a fault."""
        logger = logging.getLogger("test-zero-cursor")
        with caplog.at_level(logging.WARNING):
            assert _sync_cursor.normalise_line_cursor(
                0, key="postgres_sync_line", logger=logger,
            ) == 0
        assert caplog.text == ""


class TestTheGateTextForABadCursor:
    """
    The warning goes to a log nobody reads; the gate is the surface that
    reaches Shawn. It has to name the value and say what it has cost.
    """

    def test_it_names_the_value_and_the_consequence(self):
        """The mutation this kills: dropping the value from the text."""
        detail = _sync_cursor.cursor_fault_detail(
            "sync-sessions-to-postgres.py",
            "sessions_sync_archived_at",
            Path("/data/sync-cursors.json"),
            "abc",
            "an ISO-8601 timestamp",
        )
        assert "'abc'" in detail
        assert "sessions_sync_archived_at" in detail
        assert "/data/sync-cursors.json" in detail
        assert "acknowledged quarantine position has been reset" in detail
        assert "Repair the cursor file" in detail


# ===========================================================================
# Unsynced-backlog gate (audit 2026-09-08, round 4a, finding A9)
# ===========================================================================


class TestCountJsonlLines:
    """Line counting must agree with every other reader of the canonical."""

    def test_counts_by_newline_not_unicode_boundaries(self, tmp_path):
        """A U+2028 inside a record is not a line break.

        Kills the mutation ``data.count(b"\\n")`` -> ``text.splitlines()``:
        the latter would report a phantom extra line and fabricate a backlog
        on every call.
        """
        path = tmp_path / "memories.jsonl"
        path.write_text(
            json.dumps({"id": "a", "content": "one two"},
                       ensure_ascii=False) + "\n"
            + json.dumps({"id": "b"}) + "\n",
            encoding="utf-8",
        )
        assert _sync_cursor.count_jsonl_lines(path) == 2

    def test_a_final_line_without_a_newline_still_counts(self, tmp_path):
        path = tmp_path / "memories.jsonl"
        path.write_text('{"id": "a"}\n{"id": "b"}', encoding="utf-8")
        assert _sync_cursor.count_jsonl_lines(path) == 2

    def test_missing_and_empty_files_are_zero(self, tmp_path):
        assert _sync_cursor.count_jsonl_lines(tmp_path / "absent.jsonl") == 0
        empty = tmp_path / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        assert _sync_cursor.count_jsonl_lines(empty) == 0


class TestUnsyncedLineBacklog:
    """What counts as PostgreSQL being behind the canonical."""

    def _corpus(self, tmp_path, n):
        path = tmp_path / "memories.jsonl"
        path.write_text(
            "".join(json.dumps({"id": str(i)}) + "\n" for i in range(n)),
            encoding="utf-8",
        )
        return path

    def test_cursor_behind_reports_the_shortfall(self, tmp_path):
        corpus = self._corpus(tmp_path, 5)
        cursor = tmp_path / "sync-cursors.json"
        cursor.write_text(json.dumps({"postgres_sync_line": 2}),
                          encoding="utf-8")
        assert _sync_cursor.unsynced_line_backlog(corpus, cursor) == 3

    def test_cursor_level_or_ahead_reports_zero(self, tmp_path):
        corpus = self._corpus(tmp_path, 5)
        cursor = tmp_path / "sync-cursors.json"
        cursor.write_text(json.dumps({"postgres_sync_line": 5}),
                          encoding="utf-8")
        assert _sync_cursor.unsynced_line_backlog(corpus, cursor) == 0
        cursor.write_text(json.dumps({"postgres_sync_line": 9}),
                          encoding="utf-8")
        assert _sync_cursor.unsynced_line_backlog(corpus, cursor) == 0

    def test_absent_cursor_key_is_not_a_backlog(self, tmp_path):
        """A machine with no PostgreSQL never writes one; do not block it.

        Kills a mutation that treats a missing key as position zero, which
        would refuse every archival sweep on a host without the mirror.
        """
        corpus = self._corpus(tmp_path, 5)
        cursor = tmp_path / "sync-cursors.json"
        assert _sync_cursor.unsynced_line_backlog(corpus, cursor) == 0
        cursor.write_text(json.dumps({"zotero_sync_line": 2}),
                          encoding="utf-8")
        assert _sync_cursor.unsynced_line_backlog(corpus, cursor) == 0

    def test_refusal_text_names_the_remedy(self, tmp_path):
        text = _sync_cursor.postgres_backlog_refusal(
            "archive-memories", 7, tmp_path / "sync-cursors.json")
        assert "7 record(s)" in text
        assert "sync-to-postgres.py first" in text
        assert "Nothing was written." in text


# ===========================================================================
# One definition of "a line" (audit 2026-09-08, round 4a-2, finding M2)
#
# sync-to-postgres SAVED the cursor as a splitlines() count while the bulk
# rewriters' backlog gate COMPARED it against a b"\n" count. A raw U+2028
# below the cursor made the gate read "caught up" with records still unsynced
# beneath it. Both now go through this module.
# ===========================================================================

#: The three code points ``str.splitlines()`` breaks on and ``"\n"``-splitting
#: does not. Each is legal inside a JSON string, so each can reach disk in a
#: record whose writer forgot ``ensure_ascii``.
LINE_SEPARATOR = "\u2028"
PARAGRAPH_SEPARATOR = "\u2029"
NEXT_LINE = "\u0085"


class TestSplitAndCountAgree:
    """``len(split_jsonl_lines(text))`` must equal ``count_jsonl_lines(path)``."""

    CASES = {
        "plain": '{"id": "a"}\n{"id": "b"}\n',
        "no trailing newline": '{"id": "a"}\n{"id": "b"}',
        "blank line": '{"id": "a"}\n\n{"id": "b"}\n',
        "empty": "",
        "raw line separator":
            '{"id": "a", "c": "one' + LINE_SEPARATOR + 'two"}\n{"id": "b"}\n',
        "raw paragraph separator":
            '{"id": "a", "c": "one' + PARAGRAPH_SEPARATOR + 'two"}\n',
        "raw next line":
            '{"id": "a", "c": "one' + NEXT_LINE + 'two"}\n',
    }

    @pytest.mark.parametrize("name", sorted(CASES))
    def test_the_two_halves_agree(self, tmp_path, name):
        """Both halves of the definition must answer the same for every shape."""
        text = self.CASES[name]
        path = tmp_path / "memories.jsonl"
        path.write_text(text, encoding="utf-8")
        assert len(_sync_cursor.split_jsonl_lines(text)) == \
            _sync_cursor.count_jsonl_lines(path), name

    def test_a_raw_separator_makes_splitlines_disagree(self, tmp_path):
        """The divergence this finding is about, reproduced.

        Kills the mutation ``text.split("\\n")`` -> ``text.splitlines()``
        inside ``split_jsonl_lines``: three records, one carrying a raw
        U+2028, count as three by newline and four by splitlines.
        """
        text = (
            '{"id": "a"}\n'
            '{"id": "b", "content": "one' + LINE_SEPARATOR + 'two"}\n'
            '{"id": "c"}\n'
        )
        path = tmp_path / "memories.jsonl"
        path.write_text(text, encoding="utf-8")

        assert len(text.splitlines()) == 4, "the divergence must still exist"
        assert _sync_cursor.count_jsonl_lines(path) == 3
        assert len(_sync_cursor.split_jsonl_lines(text)) == 3


class TestUnusableCursorFailsClosed:
    """A cursor present and unreadable must refuse, never read as no backlog."""

    def _corpus(self, tmp_path, n=5):
        """A throwaway corpus of ``n`` one-line records."""
        path = tmp_path / "memories.jsonl"
        path.write_text(
            "".join(json.dumps({"id": str(i)}) + "\n" for i in range(n)),
            encoding="utf-8",
        )
        return path

    @pytest.mark.parametrize("value", [-1, "not-a-number", True, None, 3.5, []])
    def test_a_present_unusable_cursor_raises(self, tmp_path, value):
        """Kills the mutation that returns 0 for an unusable cursor.

        A negative integer, a non-digit string, a bool, an explicit null, a
        float, and a list are each as unreadable as the next, and each used
        to read as "caught up" while the sweep went on to delete lines.
        """
        corpus = self._corpus(tmp_path)
        cursor = tmp_path / "sync-cursors.json"
        cursor.write_text(json.dumps({"postgres_sync_line": value}),
                          encoding="utf-8")
        with pytest.raises(_sync_cursor.UnusableCursor):
            _sync_cursor.unsynced_line_backlog(corpus, cursor)

    def test_a_malformed_cursor_file_raises(self, tmp_path):
        """An unparseable cursor file is not the same as an absent one."""
        corpus = self._corpus(tmp_path)
        cursor = tmp_path / "sync-cursors.json"
        cursor.write_text("{not json", encoding="utf-8")
        with pytest.raises(_sync_cursor.UnusableCursor):
            _sync_cursor.unsynced_line_backlog(corpus, cursor)

    def test_an_absent_file_or_key_is_still_zero(self, tmp_path):
        """A machine with no PostgreSQL must not be blocked.

        An absent file, a file carrying other cursors, and a readable empty
        object all mean "this host has never synced memories".
        """
        corpus = self._corpus(tmp_path)
        cursor = tmp_path / "sync-cursors.json"
        assert _sync_cursor.unsynced_line_backlog(corpus, cursor) == 0
        cursor.write_text(json.dumps({"zotero_sync_line": 2}), encoding="utf-8")
        assert _sync_cursor.unsynced_line_backlog(corpus, cursor) == 0
        cursor.write_text("{}", encoding="utf-8")
        assert _sync_cursor.unsynced_line_backlog(corpus, cursor) == 0

    def test_refusal_text_names_the_repair(self):
        """The operator is told what to do, not merely that it stopped."""
        text = _sync_cursor.unusable_cursor_refusal("dedup-memories", "why")
        assert "cannot be read" in text
        assert "sync-to-postgres.py" in text
        assert "Nothing was written." in text


class TestReadJsonlLinesIsNewlineSafe:
    """Universal-newline translation must not sit between the two halves.

    Audit round 4a-3, finding M2. ``Path.read_text`` rewrites a lone ``\r``
    (and ``\r\n``) to ``\n`` before any splitting happens, so feeding its
    output to ``split_jsonl_lines`` counted a record that
    ``count_jsonl_lines`` did not -- the cursor was then saved one line ahead
    of the file the backlog gate measures, and the gate read "caught up".
    """

    LONE_CR = b'{"a":1}\r{"b":2}\n'

    def test_the_lone_carriage_return_shape(self, tmp_path):
        """The measured case: split=2, count=1 through read_text.

        Kills the mutation ``read_jsonl_lines(path)`` ->
        ``split_jsonl_lines(path.read_text(encoding="utf-8"))``.
        """
        path = tmp_path / "memories.jsonl"
        path.write_bytes(self.LONE_CR)

        # The defect, demonstrated: read_text turns the \r into a \n.
        assert len(_sync_cursor.split_jsonl_lines(
            path.read_text(encoding="utf-8"))) == 2
        assert _sync_cursor.count_jsonl_lines(path) == 1

        # The fixed reader agrees with the counter.
        assert len(_sync_cursor.read_jsonl_lines(path)) == 1
        assert _sync_cursor.read_jsonl_lines(path) == ['{"a":1}\r{"b":2}']

    @pytest.mark.parametrize("raw", [
        b'{"a":1}\r{"b":2}\n',            # lone CR inside a record
        b'{"a":1}\r\n{"b":2}\n',          # CRLF terminators
        b'{"a":1}\r',                     # trailing lone CR, no newline
        b'{"a":1}\n{"b":2}',              # no trailing newline
        b'',                              # empty
        b'{"a":1}\n\n{"b":2}\n',          # blank line
    ])
    def test_reader_and_counter_agree_on_every_shape(self, tmp_path, raw):
        """The invariant the docstring promises, over the awkward inputs."""
        path = tmp_path / "memories.jsonl"
        path.write_bytes(raw)
        assert len(_sync_cursor.read_jsonl_lines(path)) == \
            _sync_cursor.count_jsonl_lines(path), raw

    def test_a_missing_file_reads_as_no_lines(self, tmp_path):
        """Absent and empty agree with the counter's zero."""
        path = tmp_path / "absent.jsonl"
        assert _sync_cursor.read_jsonl_lines(path) == []
        assert _sync_cursor.count_jsonl_lines(path) == 0


class TestNonObjectCursorFileRefuses:
    """Valid JSON that is not an object is still an unusable cursor.

    Audit round 4a-3, finding M3: ``if not isinstance(parsed, dict)`` could
    be turned into ``if False`` and 181 tests stayed green.
    """

    @pytest.mark.parametrize("body", ["[]", '"3"', "null", "3", "true",
                                      '[{"postgres_sync_line": 2}]'])
    def test_a_valid_json_non_object_raises(self, tmp_path, body):
        """A list, a string, a bare number, or null cannot hold a cursor.

        Kills ``if not isinstance(parsed, dict)`` -> ``if False``: each of
        these parses cleanly, so the malformed-file branch never fires, and
        the run proceeds to delete lines as though there were no backlog.
        """
        corpus = tmp_path / "memories.jsonl"
        corpus.write_text('{"id": "a"}\n{"id": "b"}\n', encoding="utf-8")
        cursor = tmp_path / "sync-cursors.json"
        cursor.write_text(body, encoding="utf-8")

        with pytest.raises(_sync_cursor.UnusableCursor, match="not a JSON"):
            _sync_cursor.unsynced_line_backlog(corpus, cursor)


class TestStrictDecoding:
    """A corpus that is not valid UTF-8 must raise, not be silently mangled.

    Round 4a-4, L5: ``.decode("utf-8")`` -> ``.decode("utf-8", "replace")``
    survived. Replacement characters would change the byte content of every
    record on that line and the reader would report success.
    """

    def test_invalid_utf8_raises_rather_than_being_replaced(self, tmp_path):
        path = tmp_path / "memories.jsonl"
        path.write_bytes(b'{"id": "a"}\n\xff\xfe not utf-8\n{"id": "b"}\n')

        with pytest.raises(UnicodeDecodeError):
            _sync_cursor.read_jsonl_lines(path)

    def test_valid_utf8_still_reads(self, tmp_path):
        path = tmp_path / "memories.jsonl"
        path.write_text('{"id": "a", "c": "kiln — firing"}\n', encoding="utf-8")
        assert len(_sync_cursor.read_jsonl_lines(path)) == 1
