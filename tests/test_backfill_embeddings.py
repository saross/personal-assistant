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


# ---------------------------------------------------------------------------
# Audit round two, findings P6 and P7
# ---------------------------------------------------------------------------


class _FakePsycopg2Error(Exception):
    """Stand-in for ``psycopg2.Error``."""


class _FakePsycopg2OperationalError(_FakePsycopg2Error):
    """Stand-in for ``psycopg2.OperationalError`` — the server is gone."""


class _FakePsycopg2InterfaceError(_FakePsycopg2Error):
    """Stand-in for ``psycopg2.InterfaceError`` — connection already closed."""


class _FakePsycopg2DataError(_FakePsycopg2Error):
    """Stand-in for ``psycopg2.DataError`` — the batch's content is wrong."""


def _fetch_params(executed: list[tuple]) -> list[tuple]:
    """Extract the (limit, offset) parameters of each fetch_batch query."""
    return [
        args[1] for args in executed
        if len(args) >= 2 and "WHERE embedding IS NULL" in args[0]
        and "ORDER BY" in args[0]
    ]


class TestLimitIsHonoured:
    """Finding P6 (lens A-M4) — ``--limit N`` must be a real ceiling."""

    def test_limit_clamps_the_fetch(self):
        """
        ``--limit 5 --batch-size 200`` used to embed 200 records: the
        LIMIT sent to PostgreSQL was the batch size, and the loop only
        re-checked its allowance after the batch was already embedded and
        written. The mutation this kills: passing ``batch_size`` rather
        than ``min(batch_size, to_process - total_embedded)`` to
        ``fetch_batch``.
        """
        rows = [(f"id-{i}", f"c{i}", "", "") for i in range(5)]
        conn, cur = _stub_db_connection(missing_count=1000)
        cur.fetchall.side_effect = [rows, []]

        executed = []
        cur.execute.side_effect = lambda *args, **kw: executed.append(args)

        with patch.object(backfill_mod, "psycopg2") as pg_mock, \
             patch.object(backfill_mod, "is_ollama_available", return_value=True), \
             patch.object(backfill_mod, "assert_schema_version"), \
             patch.object(
                 backfill_mod, "generate_embeddings",
                 return_value=[[0.1] * 768] * 5,
             ), \
             patch.object(backfill_mod, "update_embeddings", return_value=5):
            pg_mock.connect.return_value = conn
            pg_mock.extras = MagicMock()

            backfill_mod.backfill(
                batch_size=200, limit=5, dry_run=False,
                logger=_make_logger(), catch_up=False,
            )

        params = _fetch_params(executed)
        assert params, "no fetch_batch query was issued"
        assert params[0] == (5, 0), (
            f"--limit 5 must clamp the first fetch to 5 rows; got {params[0]}"
        )

    def test_limit_larger_than_batch_size_still_batches(self):
        """A limit above the batch size leaves batching alone."""
        rows = [(f"id-{i}", f"c{i}", "", "") for i in range(2)]
        conn, cur = _stub_db_connection(missing_count=1000)
        cur.fetchall.side_effect = [rows, rows, []]

        executed = []
        cur.execute.side_effect = lambda *args, **kw: executed.append(args)

        with patch.object(backfill_mod, "psycopg2") as pg_mock, \
             patch.object(backfill_mod, "is_ollama_available", return_value=True), \
             patch.object(backfill_mod, "assert_schema_version"), \
             patch.object(
                 backfill_mod, "generate_embeddings",
                 return_value=[[0.1] * 768] * 2,
             ), \
             patch.object(backfill_mod, "update_embeddings", return_value=2):
            pg_mock.connect.return_value = conn
            pg_mock.extras = MagicMock()

            backfill_mod.backfill(
                batch_size=2, limit=4, dry_run=False,
                logger=_make_logger(), catch_up=False,
            )

        params = _fetch_params(executed)
        assert params[0] == (2, 0)
        assert params[1] == (2, 0)

    def test_no_limit_uses_the_full_batch_size(self):
        """``--limit 0`` (the default) still fetches whole batches."""
        rows = [(f"id-{i}", f"c{i}", "", "") for i in range(3)]
        conn, cur = _stub_db_connection(missing_count=3)
        cur.fetchall.side_effect = [rows, []]

        executed = []
        cur.execute.side_effect = lambda *args, **kw: executed.append(args)

        with patch.object(backfill_mod, "psycopg2") as pg_mock, \
             patch.object(backfill_mod, "is_ollama_available", return_value=True), \
             patch.object(backfill_mod, "assert_schema_version"), \
             patch.object(
                 backfill_mod, "generate_embeddings",
                 return_value=[[0.1] * 768] * 3,
             ), \
             patch.object(backfill_mod, "update_embeddings", return_value=3):
            pg_mock.connect.return_value = conn
            pg_mock.extras = MagicMock()

            backfill_mod.backfill(
                batch_size=200, limit=0, dry_run=False,
                logger=_make_logger(), catch_up=False,
            )

        assert _fetch_params(executed)[0] == (3, 0)


class TestDatabaseFailuresDuringUpdate:
    """Finding P7 (lens A-M5) — ``--catch-up`` must survive a DB refusal."""

    def _stub_pg_module(self, monkeypatch, execute_batch_side_effect):
        """Point the module's psycopg2 at a stand-in with the real classes."""
        pg_mock = MagicMock()
        pg_mock.Error = _FakePsycopg2Error
        pg_mock.OperationalError = _FakePsycopg2OperationalError
        pg_mock.InterfaceError = _FakePsycopg2InterfaceError
        pg_mock.DataError = _FakePsycopg2DataError
        pg_mock.extras.execute_batch.side_effect = execute_batch_side_effect
        monkeypatch.setattr(backfill_mod, "psycopg2", pg_mock)
        return pg_mock

    def test_refused_batch_returns_zero_and_rolls_back(self, monkeypatch):
        """
        A refused UPDATE used to propagate out of ``backfill`` uncaught,
        leaving the connection in an aborted-transaction state and
        tracebacking the process. It must now roll back and report zero,
        which the caller handles like an all-failed embedding batch.
        The mutation this kills: removing the try/except around
        ``execute_batch``.
        """
        def _refuse(*args, **kwargs):
            raise _FakePsycopg2DataError("expected 768 dimensions, not 1024")

        self._stub_pg_module(monkeypatch, _refuse)
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__ = lambda self: self
        cur.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cur

        updated = backfill_mod.update_embeddings(
            conn, [("id-1", [0.1] * 768)], logger=_make_logger(),
        )

        assert updated == 0
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_outage_during_update_is_re_raised(self, monkeypatch):
        """
        An unreachable database is not a per-batch failure: continuing
        would walk the whole table reporting zero progress. It must
        propagate so the caller can stop.
        """
        def _gone(*args, **kwargs):
            raise _FakePsycopg2OperationalError("server closed the connection")

        self._stub_pg_module(monkeypatch, _gone)
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__ = lambda self: self
        cur.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cur

        with pytest.raises(_FakePsycopg2OperationalError):
            backfill_mod.update_embeddings(
                conn, [("id-1", [0.1] * 768)], logger=_make_logger(),
            )

    def test_catch_up_continues_past_a_refused_batch(self):
        """
        End-to-end: batch 1 is refused by the database, batch 2 succeeds,
        and the run finishes normally rather than tracebacking.
        """
        batch_1 = [("id-1", "c1", "", ""), ("id-2", "c2", "", "")]
        batch_2 = [("id-3", "c3", "", ""), ("id-4", "c4", "", "")]
        conn, cur = _stub_db_connection(missing_count=4)
        cur.fetchall.side_effect = [batch_1, batch_2, []]

        with patch.object(backfill_mod, "psycopg2") as pg_mock, \
             patch.object(backfill_mod, "is_ollama_available", return_value=True), \
             patch.object(backfill_mod, "assert_schema_version"), \
             patch.object(
                 backfill_mod, "generate_embeddings",
                 return_value=[[0.1] * 768, [0.2] * 768],
             ), \
             patch.object(
                 backfill_mod, "update_embeddings", side_effect=[0, 2],
             ):
            pg_mock.connect.return_value = conn
            pg_mock.Error = _FakePsycopg2Error
            pg_mock.extras = MagicMock()

            backfill_mod.backfill(
                batch_size=2, limit=0, dry_run=False,
                logger=_make_logger(), catch_up=True,
            )

        conn.close.assert_called_once()

    def test_outage_mid_run_stops_cleanly(self):
        """An outage aborts the loop with a message, not a traceback."""
        batch_1 = [("id-1", "c1", "", "")]
        conn, cur = _stub_db_connection(missing_count=4)
        cur.fetchall.side_effect = [batch_1, []]

        with patch.object(backfill_mod, "psycopg2") as pg_mock, \
             patch.object(backfill_mod, "is_ollama_available", return_value=True), \
             patch.object(backfill_mod, "assert_schema_version"), \
             patch.object(
                 backfill_mod, "generate_embeddings",
                 return_value=[[0.1] * 768],
             ), \
             patch.object(
                 backfill_mod, "update_embeddings",
                 side_effect=_FakePsycopg2OperationalError("server gone"),
             ):
            pg_mock.connect.return_value = conn
            pg_mock.Error = _FakePsycopg2Error
            pg_mock.extras = MagicMock()

            backfill_mod.backfill(
                batch_size=2, limit=0, dry_run=False,
                logger=_make_logger(), catch_up=True,
            )

        conn.close.assert_called_once()
