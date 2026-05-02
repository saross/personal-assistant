"""
Concurrency tests for the memory-canonical flock unification (IC1).

These tests pin the contract introduced by Batch 3 of the audit
2026-05-02 fix series: a shared/exclusive ``flock(2)`` on
``memories.jsonl`` (and ``tag-vocabulary.txt``) so the
``hooks/extraction-hook.py`` appender no longer races against bulk
rewriters in ``scripts/dedup-memories.py``,
``scripts/tag-gardening.py``, ``scripts/reprocess-sessions.py``, and
``scripts/backfill-summaries.py``.

Pinning behaviour:

* :class:`TestLockJsonlForRewrite` — the LOCK_EX context manager
  exposed by ``_bulk_rewrite_guard.lock_jsonl_for_rewrite``.
* :class:`TestSharedAppender` — multiple LOCK_SH appenders may run
  concurrently and a LOCK_EX rewriter waits for them to drain.
* :class:`TestRewriterBlocksAppender` — the load-bearing race: an
  appender that fires while a rewriter holds LOCK_EX must wait for
  the rewrite to complete and its bytes must land in the post-rewrite
  file, not be silently overwritten.

The third test is the one that would have caught the IC1 bug had it
existed at design time.
"""

from __future__ import annotations

import fcntl
import json
import multiprocessing
import os
import sys
import textwrap
import time
from pathlib import Path

import pytest

# scripts/ is importable via the sys.path insertion used elsewhere in
# the repo. Use the same pattern here.
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from _bulk_rewrite_guard import lock_jsonl_for_rewrite  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _shared_locked_append(target: Path, lines: list[str]) -> None:
    """Replicate the extraction-hook's LOCK_SH append path.

    Kept in-test (rather than importing from the hook module) so the
    test pins the byte-for-byte contract the hook is expected to
    satisfy, not whatever the hook happens to do today. Includes the
    open-flock-fstat-vs-stat retry loop that closes the
    rename-under-fd race; without it, a rewriter that renames between
    our ``os.open`` and ``flock`` would leave us appending to an
    orphan inode and silently losing the bytes.
    """
    payload = "".join(lines).encode("utf-8")
    while True:
        fd = os.open(
            str(target),
            os.O_WRONLY | os.O_APPEND | os.O_CREAT,
            0o644,
        )
        fcntl.flock(fd, fcntl.LOCK_SH)
        try:
            if os.fstat(fd).st_ino == os.stat(target).st_ino:
                break
        except FileNotFoundError:
            pass
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)
    try:
        os.lseek(fd, 0, os.SEEK_END)
        os.write(fd, payload)
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)


def _spawn_appender_subprocess(
    target_path: Path,
    n_lines: int,
    delay_before_first_write_s: float = 0.0,
) -> "multiprocessing.Process":
    """Spawn a subprocess that runs an LOCK_SH appender.

    Subprocess (rather than thread) so the flock is genuinely held by
    a different OS-level locker, mirroring the cross-process race.
    """
    code = textwrap.dedent(
        f"""
        import fcntl, os, time
        target = {str(target_path)!r}
        n = {n_lines}
        delay = {delay_before_first_write_s}
        if delay:
            time.sleep(delay)
        payload = ("".join(
            "APPEND-{{:03d}}\\n".format(i) for i in range(n)
        )).encode("utf-8")
        while True:
            fd = os.open(target, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
            fcntl.flock(fd, fcntl.LOCK_SH)
            try:
                if os.fstat(fd).st_ino == os.stat(target).st_ino:
                    break
            except FileNotFoundError:
                pass
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(fd)
        try:
            os.lseek(fd, 0, os.SEEK_END)
            os.write(fd, payload)
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(fd)
        """
    )
    proc = multiprocessing.Process(
        target=lambda src: exec(src, {"__name__": "__appender__"}),
        args=(code,),
    )
    proc.start()
    return proc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLockJsonlForRewrite:
    """Pin the API surface of ``lock_jsonl_for_rewrite``."""

    def test_acquires_and_releases(self, tmp_path: Path) -> None:
        """The context manager acquires and releases the flock cleanly."""
        target = tmp_path / "memories.jsonl"
        target.write_text("seed\n", encoding="utf-8")

        with lock_jsonl_for_rewrite(target):
            # Inside the lock, an external LOCK_EX request must block.
            # We don't actually attempt to acquire (would deadlock with
            # ourselves on the same fd-table) — instead we verify a
            # non-blocking external acquire would fail.
            fd = os.open(str(target), os.O_RDWR)
            try:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(fd)

        # After the context exits, an external LOCK_EX should succeed.
        fd = os.open(str(target), os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def test_requires_existing_file(self, tmp_path: Path) -> None:
        """A missing canonical raises rather than silently creating one."""
        target = tmp_path / "missing.jsonl"
        with pytest.raises(FileNotFoundError):
            with lock_jsonl_for_rewrite(target):
                pass


class TestSharedAppender:
    """LOCK_SH appenders may run concurrently."""

    def test_two_shared_holders_coexist(self, tmp_path: Path) -> None:
        """Two LOCK_SH holders on the same file do not block each other."""
        target = tmp_path / "memories.jsonl"
        target.write_text("seed\n", encoding="utf-8")

        fd_a = os.open(str(target), os.O_WRONLY | os.O_APPEND)
        fd_b = os.open(str(target), os.O_WRONLY | os.O_APPEND)
        try:
            fcntl.flock(fd_a, fcntl.LOCK_SH)
            # Non-blocking second acquire must succeed immediately.
            fcntl.flock(fd_b, fcntl.LOCK_SH | fcntl.LOCK_NB)
            fcntl.flock(fd_a, fcntl.LOCK_UN)
            fcntl.flock(fd_b, fcntl.LOCK_UN)
        finally:
            os.close(fd_a)
            os.close(fd_b)


class TestRewriterBlocksAppender:
    """The load-bearing race: appender bytes must not be lost."""

    def test_appender_during_rewrite_lands_after_rename(
        self, tmp_path: Path,
    ) -> None:
        """
        Spawn an appender subprocess while a rewriter holds LOCK_EX;
        assert every appended line appears in the final file and was
        NOT silently overwritten by the rewriter's rename.

        This is the IC1 bug as a unit test. Before Batch 3, the
        appender held no flock and the rewriter's rename happened
        without serialising against it; appends landing in the
        original inode after the rewriter read but before its rename
        were silently dropped. With LOCK_SH/LOCK_EX both honoured,
        the appender either lands its bytes BEFORE the rewriter's
        load (in which case they appear in the rewriter's output) or
        AFTER the rename (in which case they appear in the renamed
        file because the appender re-seeks to SEEK_END after acquiring
        LOCK_SH on the new inode).
        """
        target = tmp_path / "memories.jsonl"
        # Seed with 100 records so the rewriter has a non-trivial copy
        # phase. JSON-encoded lines so the format matches production.
        seed_records = [
            json.dumps({"id": f"seed-{i:03d}", "content": "x"}) + "\n"
            for i in range(100)
        ]
        target.write_text("".join(seed_records), encoding="utf-8")

        # Hold LOCK_EX in this process while the appender subprocess
        # runs. The appender will block on flock() until we release.
        n_appender_lines = 100

        with lock_jsonl_for_rewrite(target):
            # Start appender — it should block on flock() until our
            # context manager exits.
            proc = _spawn_appender_subprocess(
                target_path=target,
                n_lines=n_appender_lines,
                delay_before_first_write_s=0.0,
            )
            # Give the subprocess time to start and reach flock().
            # 0.5s is generous; flock() blocks the moment it's hit.
            time.sleep(0.5)

            # While the rewriter holds LOCK_EX, no appender bytes
            # should be visible yet.
            mid_size = target.stat().st_size
            assert mid_size == len("".join(seed_records).encode("utf-8")), (
                "Appender bytes leaked through LOCK_EX — appender did "
                "not honour LOCK_SH or kernel flock semantics broke."
            )

            # Simulate the rewrite: copy current contents, modify
            # (e.g., dedup would drop duplicates here), atomically
            # rename a temp file over the target. Crucially, this
            # rewrite KEEPS all seed records — a real dedup might
            # drop some, but this test pins concurrency, not dedup
            # semantics.
            tmp_path_target = target.with_suffix(target.suffix + ".tmp")
            with open(target, "rb") as f:
                original = f.read()
            tmp_path_target.write_bytes(original)
            os.rename(str(tmp_path_target), str(target))

        # Rewrite released. The appender's flock should now unblock.
        proc.join(timeout=5.0)
        assert not proc.is_alive(), "Appender subprocess did not finish"
        assert proc.exitcode == 0, (
            f"Appender subprocess exited with code {proc.exitcode}"
        )

        # Final file must contain every seed record AND every appender
        # line. No interleaving of bytes (the writes are atomic with
        # respect to each other under flock).
        final_text = target.read_text(encoding="utf-8")
        final_lines = final_text.splitlines()

        # Every seed record present, exactly once.
        seed_ids_seen = sum(
            1 for line in final_lines
            if line.startswith('{"id": "seed-')
        )
        assert seed_ids_seen == 100, (
            f"Expected 100 seed records after rewrite, found "
            f"{seed_ids_seen}. Rewriter may have lost data."
        )

        # Every appender line present.
        append_lines_seen = sum(
            1 for line in final_lines if line.startswith("APPEND-")
        )
        assert append_lines_seen == n_appender_lines, (
            f"Expected {n_appender_lines} appender lines, found "
            f"{append_lines_seen}. Lock did NOT prevent loss — "
            "this is the IC1 bug regressed."
        )

        # Order invariant: every appender line should come AFTER the
        # last seed record, because the appender blocked until after
        # the rewriter's rename completed.
        last_seed_idx = max(
            i for i, line in enumerate(final_lines)
            if line.startswith('{"id": "seed-')
        )
        first_append_idx = min(
            i for i, line in enumerate(final_lines)
            if line.startswith("APPEND-")
        )
        assert first_append_idx > last_seed_idx, (
            "Appender bytes interleaved with rewriter output. "
            "Either the appender wrote before the rename or the "
            "rewriter's atomic-rename did not happen atomically."
        )

    def test_appender_before_rewriter_is_preserved(
        self, tmp_path: Path,
    ) -> None:
        """
        An appender that lands BEFORE the rewriter starts should have
        its bytes carried into the rewritten file. Pinned because the
        tag-gardening / dedup loaders read inside the lock to pick up
        any pre-rewrite appends.
        """
        target = tmp_path / "memories.jsonl"
        target.write_text("seed\n", encoding="utf-8")

        # Appender writes before any rewriter starts.
        _shared_locked_append(target, ["pre-rewrite-1\n", "pre-rewrite-2\n"])

        # Rewriter loads under LOCK_EX, modifies, renames.
        with lock_jsonl_for_rewrite(target):
            content = target.read_text(encoding="utf-8")
            # Apply a transformation: uppercase the seed record only.
            transformed = content.replace("seed\n", "SEED\n")
            tmp_target = target.with_suffix(target.suffix + ".tmp")
            tmp_target.write_text(transformed, encoding="utf-8")
            os.rename(str(tmp_target), str(target))

        final = target.read_text(encoding="utf-8")
        assert "SEED" in final, "Rewriter transformation lost"
        assert "pre-rewrite-1" in final, "Pre-rewrite appender bytes lost"
        assert "pre-rewrite-2" in final, "Pre-rewrite appender bytes lost"


class TestVocabularyFileLock:
    """The same lock pattern works for tag-vocabulary.txt."""

    def test_appender_blocks_during_vocab_rewrite(
        self, tmp_path: Path,
    ) -> None:
        """
        Tag-gardening rewrites tag-vocabulary.txt under LOCK_EX; the
        extraction-hook ``update_vocabulary`` path takes LOCK_SH. The
        same blocking semantics apply — pinned here because the lock
        primitive is path-agnostic but the contract is per-file.
        """
        vocab = tmp_path / "tag-vocabulary.txt"
        vocab.write_text("alpha\nbeta\n", encoding="utf-8")

        # Rewriter holds LOCK_EX; appender subprocess should block.
        proc_done = multiprocessing.Event()

        def append_then_signal() -> None:
            _shared_locked_append(vocab, ["delta\n"])
            proc_done.set()

        proc = multiprocessing.Process(target=append_then_signal)

        with lock_jsonl_for_rewrite(vocab):
            proc.start()
            # Give appender time to hit flock(). 0.3s is generous.
            time.sleep(0.3)
            assert not proc_done.is_set(), (
                "Appender wrote before LOCK_EX released — vocab lock "
                "did not block."
            )
            # Rewriter does its rewrite.
            tmp_vocab = vocab.with_suffix(vocab.suffix + ".tmp")
            tmp_vocab.write_text(
                "alpha\nbeta\ngamma\n", encoding="utf-8",
            )
            os.rename(str(tmp_vocab), str(vocab))

        # After release, appender completes.
        proc.join(timeout=5.0)
        assert proc_done.is_set(), "Appender did not unblock after rewrite"

        final = vocab.read_text(encoding="utf-8")
        assert "gamma" in final, "Rewrite did not land"
        assert "delta" in final, "Appender bytes did not land"
