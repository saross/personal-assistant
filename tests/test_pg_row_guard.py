"""
Tests for ``scripts/_pg_row_guard.py`` — the shared row-level Postgres
guards introduced by audit round two, findings P1 and P2 (lens A-X1,
A-X2).

No database and no network: psycopg2 is represented by stand-in exception
classes with the real hierarchy, and ``execute_values`` by a callable that
records what it was asked to send.
"""

from __future__ import annotations

import logging
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import _pg_row_guard  # noqa: E402


# ============================================================================
# Fake psycopg2 exception hierarchy (mirrors the real one)
# ============================================================================


class _Error(Exception):
    """Stand-in for ``psycopg2.Error``."""


class _InterfaceError(_Error):
    """Stand-in for ``psycopg2.InterfaceError`` — the connection is gone."""


class _DatabaseError(_Error):
    """Stand-in for ``psycopg2.DatabaseError``."""


class _OperationalError(_DatabaseError):
    """Stand-in for ``psycopg2.OperationalError`` — cannot reach the server."""


class _DataError(_DatabaseError):
    """Stand-in for ``psycopg2.DataError`` — this row's content is wrong."""


class _IntegrityError(_DatabaseError):
    """Stand-in for ``psycopg2.IntegrityError`` — constraint violation."""


class _ProgrammingError(_DatabaseError):
    """Stand-in for ``psycopg2.ProgrammingError`` — e.g. can't adapt a dict."""


def _fake_psycopg2() -> types.ModuleType:
    """Build a stand-in psycopg2 module carrying the exception classes."""
    module = types.ModuleType("psycopg2")
    module.Error = _Error
    module.InterfaceError = _InterfaceError
    module.DatabaseError = _DatabaseError
    module.OperationalError = _OperationalError
    module.DataError = _DataError
    module.IntegrityError = _IntegrityError
    module.ProgrammingError = _ProgrammingError
    return module


@pytest.fixture
def logger() -> logging.Logger:
    """Quiet logger for the guard's own log lines."""
    return logging.getLogger("test-pg-row-guard")


@pytest.fixture
def conn() -> MagicMock:
    """A connection mock supporting ``with conn:`` and ``conn.cursor()``."""
    cur = MagicMock()
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    connection = MagicMock()
    connection.cursor.return_value = cur
    connection.__enter__ = MagicMock(return_value=connection)
    connection.__exit__ = MagicMock(return_value=False)
    return connection


# ============================================================================
# is_outage_error
# ============================================================================


class TestIsOutageError:
    """Only connection-level failures count as outages."""

    @pytest.mark.parametrize("exc", [
        _OperationalError("server closed the connection unexpectedly"),
        _InterfaceError("connection already closed"),
    ])
    def test_connection_failures_are_outages(self, exc) -> None:
        """These say nothing about the row — retry, hold the cursor."""
        assert _pg_row_guard.is_outage_error(exc, _fake_psycopg2()) is True

    @pytest.mark.parametrize("exc", [
        _DataError("unsupported Unicode escape sequence"),
        _IntegrityError('null value in column "project" violates not-null'),
        _ProgrammingError("can't adapt type 'dict'"),
        ValueError("A string literal cannot contain NUL (0x00) characters"),
        TypeError("not JSON serialisable"),
    ])
    def test_content_failures_are_not_outages(self, exc) -> None:
        """
        These are permanent and row-specific: retrying reproduces them
        exactly. Classifying them as outages is the P1/P2 defect.
        """
        assert _pg_row_guard.is_outage_error(exc, _fake_psycopg2()) is False

    def test_missing_class_on_the_module_is_tolerated(self) -> None:
        """A partial stand-in module must not make the classifier throw."""
        partial = types.ModuleType("psycopg2")
        partial.Error = _Error
        assert _pg_row_guard.is_outage_error(_DataError("x"), partial) is False


# ============================================================================
# sanitise_nuls
# ============================================================================


class TestSanitiseNuls:
    """NUL is stripped everywhere a string can hide in a JSON document."""

    def test_plain_string(self) -> None:
        """The simplest case, with an accurate removal count."""
        cleaned, removed = _pg_row_guard.sanitise_nuls("a\x00b\x00c")
        assert cleaned == "abc"
        assert removed == 2

    def test_nested_structure(self) -> None:
        """Dicts, lists, and dict keys are all reached."""
        value = {
            "summaries": [{"narrative": "ran\x00 it"}, "plain\x00"],
            "k\x00ey": "v",
            "count": 3,
            "flag": True,
            "nothing": None,
        }
        cleaned, removed = _pg_row_guard.sanitise_nuls(value)
        assert cleaned == {
            "summaries": [{"narrative": "ran it"}, "plain"],
            "key": "v",
            "count": 3,
            "flag": True,
            "nothing": None,
        }
        assert removed == 3

    def test_clean_value_is_returned_unchanged(self) -> None:
        """No NUL means no work and a zero count."""
        value = {"a": ["b", {"c": 1}]}
        cleaned, removed = _pg_row_guard.sanitise_nuls(value)
        assert cleaned == value
        assert removed == 0

    def test_non_string_scalars_pass_through(self) -> None:
        """Numbers and None are returned as-is, not stringified."""
        for scalar in (1, 2.5, None, True):
            cleaned, removed = _pg_row_guard.sanitise_nuls(scalar)
            assert cleaned is scalar
            assert removed == 0


# ============================================================================
# insert_rows_individually
# ============================================================================


class TestInsertRowsIndividually:
    """The per-row replay isolates poison rows from healthy ones."""

    def _execute_values(self, poison_ids: set[str], error: type[Exception]):
        """Return an ``execute_values`` stand-in refusing the given ids."""

        def _call(cur, sql, values, page_size=None, fetch=False):
            offending = [row[0] for row in values if row[0] in poison_ids]
            if offending:
                raise error(f"refused {offending[0]}")
            return [(row[0],) for row in values]

        return _call

    def test_healthy_rows_land_and_poison_is_reported(
        self, conn: MagicMock, logger: logging.Logger,
    ) -> None:
        """Two good rows insert; the third is named as poison."""
        rows = [("a", 1), ("bad", 2), ("c", 3)]
        returned, poison, reachable = _pg_row_guard.insert_rows_individually(
            conn, "INSERT ... VALUES %s RETURNING id", rows,
            psycopg2_module=_fake_psycopg2(),
            execute_values=self._execute_values({"bad"}, _DataError),
            logger=logger,
        )
        assert returned == {"a", "c"}
        assert [pid for pid, _ in poison] == ["bad"]
        assert reachable is True

    def test_every_row_poison(
        self, conn: MagicMock, logger: logging.Logger,
    ) -> None:
        """An all-poison batch quarantines everything and stays reachable."""
        rows = [("x", 1), ("y", 2)]
        returned, poison, reachable = _pg_row_guard.insert_rows_individually(
            conn, "INSERT ... VALUES %s RETURNING id", rows,
            psycopg2_module=_fake_psycopg2(),
            execute_values=self._execute_values({"x", "y"}, _IntegrityError),
            logger=logger,
        )
        assert returned == set()
        assert [pid for pid, _ in poison] == ["x", "y"]
        assert reachable is True

    def test_outage_mid_replay_stops_and_reports_unreachable(
        self, conn: MagicMock, logger: logging.Logger,
    ) -> None:
        """
        Rows after the outage were never attempted, so they are neither
        stored nor quarantined — the caller must hold its cursor.
        """
        calls = {"n": 0}

        def _call(cur, sql, values, page_size=None, fetch=False):
            calls["n"] += 1
            if calls["n"] == 1:
                return [(values[0][0],)]
            raise _OperationalError("server closed the connection")

        returned, poison, reachable = _pg_row_guard.insert_rows_individually(
            conn, "INSERT ... VALUES %s RETURNING id",
            [("a", 1), ("b", 2), ("c", 3)],
            psycopg2_module=_fake_psycopg2(),
            execute_values=_call,
            logger=logger,
        )
        assert returned == {"a"}
        assert poison == []
        assert reachable is False
        # Stopped at the outage rather than ploughing on through row c.
        assert calls["n"] == 2

    def test_each_row_gets_its_own_transaction(
        self, conn: MagicMock, logger: logging.Logger,
    ) -> None:
        """
        One transaction per row is what lets the replay continue past a
        failure — a shared transaction would be aborted after the first.
        """
        rows = [("a", 1), ("bad", 2), ("c", 3)]
        _pg_row_guard.insert_rows_individually(
            conn, "INSERT ... VALUES %s RETURNING id", rows,
            psycopg2_module=_fake_psycopg2(),
            execute_values=self._execute_values({"bad"}, _DataError),
            logger=logger,
        )
        assert conn.__enter__.call_count == 3
