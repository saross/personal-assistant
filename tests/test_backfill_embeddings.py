"""
Tests for scripts/backfill-embeddings.py — focusing on the ``--catch-up``
flag added by Batch 6 of the 2026-05-02 audit.

The backfill function delegates to ``psycopg2`` (DB) and ``embed`` (Ollama
HTTP). Both are mocked here so the tests exercise control flow only:

* default mode aborts after a batch where every embedding fails;
* catch-up mode skips past such a batch and continues;
* catch-up mode is idempotent on re-invocation.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Import the hyphenated module via importlib.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

_path = SCRIPTS_DIR / "backfill-embeddings.py"
_spec = importlib.util.spec_from_file_location("backfill_embeddings", _path)
backfill_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backfill_mod)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_logger() -> logging.Logger:
    """Quiet logger for use inside tests."""
    log = logging.getLogger("test-backfill")
    log.handlers = []
    log.addHandler(logging.NullHandler())
    log.setLevel(logging.CRITICAL)
    return log


def _stub_db_connection(missing_count: int):
    """
    Build a MagicMock that satisfies the psycopg2 connection contract
    used by ``backfill``.
    """
    conn = MagicMock(name="conn")
    cur = MagicMock(name="cur")
    cur.__enter__ = lambda self: self
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchone.return_value = (missing_count,)
    conn.cursor.return_value = cur
    return conn, cur


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCatchUpFlag:
    """Behavioural difference between default and ``--catch-up`` modes."""

    def test_default_mode_aborts_on_all_failed_batch(self):
        """
        When every embedding in a batch fails, default mode breaks out
        of the loop and reports the abort. Sustained Ollama outages
        therefore surface in cron logs.
        """
        # Two pretend rows; embeddings come back as all-None (failure).
        rows = [
            ("id-1", "content-1", "", ""),
            ("id-2", "content-2", "", ""),
        ]
        conn, cur = _stub_db_connection(missing_count=2)
        # First fetch returns the rows; subsequent calls (if any) empty.
        cur.fetchall.side_effect = [rows, []]

        with patch.object(backfill_mod, "psycopg2") as pg_mock, \
             patch.object(backfill_mod, "is_ollama_available", return_value=True), \
             patch.object(backfill_mod, "assert_schema_version"), \
             patch.object(backfill_mod, "generate_embeddings", return_value=[None, None]), \
             patch.object(backfill_mod, "update_embeddings", return_value=0):
            pg_mock.connect.return_value = conn
            pg_mock.extras = MagicMock()

            backfill_mod.backfill(
                batch_size=2,
                limit=0,
                dry_run=False,
                logger=_make_logger(),
                catch_up=False,
            )

        # The abort path closes the connection exactly once.
        conn.close.assert_called_once()

    def test_catch_up_mode_skips_past_failed_batch(self):
        """
        catch-up mode keeps going after an all-failed batch. The next
        ``fetch_batch`` is called with a larger ``offset`` so the loop
        does not retry the poisoned rows; it picks up fresh data.
        """
        # Three batches of two rows. Batch 1 all-fails, batch 2 succeeds,
        # batch 3 returns empty so the loop terminates.
        batch_1 = [("id-1", "c1", "", ""), ("id-2", "c2", "", "")]
        batch_2 = [("id-3", "c3", "", ""), ("id-4", "c4", "", "")]
        conn, cur = _stub_db_connection(missing_count=4)
        cur.fetchall.side_effect = [batch_1, batch_2, []]

        # First batch: every embedding None. Second batch: both succeed.
        embed_returns = [
            [None, None],
            [[0.1] * 768, [0.2] * 768],
        ]
        update_returns = [0, 2]

        # Capture the ``offset`` argument the script supplied to each
        # fetch_batch invocation by spying on cur.execute.
        executed = []

        def _execute(*args, **kwargs) -> None:
            executed.append(args)

        cur.execute.side_effect = _execute

        with patch.object(backfill_mod, "psycopg2") as pg_mock, \
             patch.object(backfill_mod, "is_ollama_available", return_value=True), \
             patch.object(backfill_mod, "assert_schema_version"), \
             patch.object(
                 backfill_mod, "generate_embeddings",
                 side_effect=embed_returns,
             ), \
             patch.object(
                 backfill_mod, "update_embeddings",
                 side_effect=update_returns,
             ):
            pg_mock.connect.return_value = conn
            pg_mock.extras = MagicMock()

            backfill_mod.backfill(
                batch_size=2,
                limit=0,
                dry_run=False,
                logger=_make_logger(),
                catch_up=True,
            )

        # Three execute calls: 1 for count_missing, then one per fetch.
        # The fetch calls carry (batch_size, offset). After the all-failed
        # first batch, offset must advance to 2 so we are not stuck on
        # the same poisoned rows.
        fetch_calls = [
            args[1] for args in executed
            if len(args) >= 2 and "WHERE embedding IS NULL" in args[0]
            and "ORDER BY" in args[0]
        ]
        assert len(fetch_calls) >= 2
        # First fetch: offset 0
        assert fetch_calls[0] == (2, 0)
        # Second fetch: offset advanced past the failed batch
        assert fetch_calls[1] == (2, 2)
        conn.close.assert_called_once()

    def test_catch_up_mode_returns_to_offset_zero_after_success(self):
        """
        After a successful batch in catch-up mode, the offset resets to
        0 because the embedded rows are no longer ``WHERE embedding IS
        NULL`` and a fresh fetch from offset 0 yields the next-oldest
        slice. This makes catch-up behave correctly under partial
        progress.
        """
        batch_1 = [("id-1", "c1", "", ""), ("id-2", "c2", "", "")]
        batch_2 = [("id-3", "c3", "", ""), ("id-4", "c4", "", "")]
        conn, cur = _stub_db_connection(missing_count=4)
        cur.fetchall.side_effect = [batch_1, batch_2, []]

        embed_returns = [
            [[0.1] * 768, [0.2] * 768],
            [[0.3] * 768, [0.4] * 768],
        ]
        update_returns = [2, 2]

        executed = []

        def _execute(*args, **kwargs) -> None:
            executed.append(args)

        cur.execute.side_effect = _execute

        with patch.object(backfill_mod, "psycopg2") as pg_mock, \
             patch.object(backfill_mod, "is_ollama_available", return_value=True), \
             patch.object(backfill_mod, "assert_schema_version"), \
             patch.object(
                 backfill_mod, "generate_embeddings",
                 side_effect=embed_returns,
             ), \
             patch.object(
                 backfill_mod, "update_embeddings",
                 side_effect=update_returns,
             ):
            pg_mock.connect.return_value = conn
            pg_mock.extras = MagicMock()

            backfill_mod.backfill(
                batch_size=2,
                limit=0,
                dry_run=False,
                logger=_make_logger(),
                catch_up=True,
            )

        fetch_calls = [
            args[1] for args in executed
            if len(args) >= 2 and "WHERE embedding IS NULL" in args[0]
            and "ORDER BY" in args[0]
        ]
        # Both fetch calls used offset 0 — the second succeeds because
        # the rows from the first batch are no longer NULL.
        assert all(params[1] == 0 for params in fetch_calls), (
            f"After a successful batch the offset must reset to 0; "
            f"got {fetch_calls}"
        )

    def test_catch_up_idempotent_on_empty_db(self):
        """
        Running catch-up against a DB with no NULL embeddings is a
        no-op (just logs the count and returns). Re-invoking is the
        same.
        """
        conn, cur = _stub_db_connection(missing_count=0)
        cur.fetchall.side_effect = [[]]

        with patch.object(backfill_mod, "psycopg2") as pg_mock, \
             patch.object(backfill_mod, "is_ollama_available", return_value=True), \
             patch.object(backfill_mod, "assert_schema_version"), \
             patch.object(backfill_mod, "generate_embeddings") as gen_mock, \
             patch.object(backfill_mod, "update_embeddings") as upd_mock:
            pg_mock.connect.return_value = conn
            pg_mock.extras = MagicMock()

            backfill_mod.backfill(
                batch_size=10,
                limit=0,
                dry_run=False,
                logger=_make_logger(),
                catch_up=True,
            )

        gen_mock.assert_not_called()
        upd_mock.assert_not_called()
        conn.close.assert_called_once()
