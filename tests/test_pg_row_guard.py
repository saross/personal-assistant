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
    """Stand-in for ``psycopg2.Error``.

    Carries ``pgcode`` like the real class: PostgreSQL's SQLSTATE for a
    server-side error, ``None`` for one psycopg2 raised client-side.
    """

    def __init__(self, message: str = "", pgcode: str | None = None) -> None:
        super().__init__(message)
        self.pgcode = pgcode


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
    """Stand-in for ``psycopg2.ProgrammingError``.

    Two very different faults share this class in psycopg2 2.9.12, which is
    what re-audit finding C1 turned on: ``InsufficientPrivilege`` (42501),
    ``UndefinedTable`` (42P01), and ``UndefinedColumn`` (42703) are
    server-side environment faults carrying a SQLSTATE, while "can't adapt
    type 'dict'" is raised client-side with no SQLSTATE and is entirely
    about the row.
    """


class _InternalError(_DatabaseError):
    """Stand-in for ``psycopg2.InternalError`` — e.g. InFailedSqlTransaction."""


class _NotSupportedError(_DatabaseError):
    """Stand-in for ``psycopg2.NotSupportedError``."""


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
    module.InternalError = _InternalError
    module.NotSupportedError = _NotSupportedError
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


class TestClassifyPgError:
    """The three-way split introduced by re-audit finding C1."""

    @pytest.mark.parametrize("exc", [
        _OperationalError("server closed the connection unexpectedly"),
        _InterfaceError("connection already closed"),
    ])
    def test_connection_failures_are_outages(self, exc) -> None:
        """These say nothing about the row — retry, hold the cursor."""
        assert _pg_row_guard.classify_pg_error(exc, _fake_psycopg2()) == "outage"
        assert _pg_row_guard.is_outage_error(exc, _fake_psycopg2()) is True

    @pytest.mark.parametrize("exc", [
        # Verified against psycopg2 2.9.12: these three are ProgrammingError.
        _ProgrammingError("permission denied for table memories", "42501"),
        _ProgrammingError('relation "memories" does not exist', "42P01"),
        _ProgrammingError('column "is_active" does not exist', "42703"),
        # And this one is InternalError.
        _InternalError(
            "current transaction is aborted, commands ignored", "25P02",
        ),
        _NotSupportedError("feature not supported", "0A000"),
    ])
    def test_environment_faults_are_not_row_errors(self, exc) -> None:
        """
        A REVOKE, a half-applied migration, or an aborted transaction
        refuses every row alike. Classed as a row error (the pre-re-audit
        behaviour on this branch), the replay quarantined the whole slice
        and advanced the cursor past it — after a cursor reset that is
        42k rows into a quarantine file, with exit 0. The mutation this
        kills: dropping ENVIRONMENT_ERROR_NAMES back into the row class.
        """
        assert (
            _pg_row_guard.classify_pg_error(exc, _fake_psycopg2())
            == "environment"
        )
        assert _pg_row_guard.is_outage_error(exc, _fake_psycopg2()) is False

    @pytest.mark.parametrize("exc", [
        _DataError("unsupported Unicode escape sequence", "22P05"),
        _IntegrityError(
            'null value in column "project" violates not-null', "23502",
        ),
        ValueError("A string literal cannot contain NUL (0x00) characters"),
        TypeError("not JSON serialisable"),
    ])
    def test_content_failures_are_row_errors(self, exc) -> None:
        """
        These are permanent and row-specific: retrying reproduces them
        exactly, and the row is genuinely at fault.
        """
        assert _pg_row_guard.classify_pg_error(exc, _fake_psycopg2()) == "row"

    def test_client_side_adaptation_error_stays_a_row_error(self) -> None:
        """
        psycopg2 raises ProgrammingError client-side when it cannot adapt a
        value ("can't adapt type 'dict'"). It carries no SQLSTATE, and it is
        entirely about the row — treating it as an environment fault would
        stall the cursor on one malformed record.
        """
        exc = _ProgrammingError("can't adapt type 'dict'")
        assert exc.pgcode is None
        assert _pg_row_guard.classify_pg_error(exc, _fake_psycopg2()) == "row"

    def test_missing_class_on_the_module_is_tolerated(self) -> None:
        """
        A partial stand-in module must not make the classifier throw. With
        no SQLSTATE and no recognisable class it falls to the conservative
        default — hold, do not quarantine.
        """
        partial = types.ModuleType("psycopg2")
        partial.Error = _Error
        verdict = _pg_row_guard.classify_pg_error(_DataError("x"), partial)
        assert verdict in ("row", "environment", "outage")

    @pytest.mark.parametrize("pgcode,expected", [
        # Row: the content of this row is wrong.
        ("21000", "row"),      # cardinality_violation
        ("22001", "row"),      # string_data_right_truncation
        ("22007", "row"),      # invalid_datetime_format
        ("22P02", "row"),      # invalid_text_representation
        ("22P05", "row"),      # untranslatable_character — a NUL in jsonb
        ("23502", "row"),      # not_null_violation
        ("23505", "row"),      # unique_violation
        ("23503", "row"),      # foreign_key_violation
        # Outage: connection exception, and only that.
        ("08006", "outage"),   # connection_failure
        ("08003", "outage"),   # connection_does_not_exist
        # Environment: reachable, wrong state.
        ("0A000", "environment"),  # feature_not_supported
        ("25P02", "environment"),  # in_failed_sql_transaction
        ("3D000", "environment"),  # invalid_catalog_name
        ("3F000", "environment"),  # invalid_schema_name
        ("42501", "environment"),  # insufficient_privilege
        ("42P01", "environment"),  # undefined_table
        ("42703", "environment"),  # undefined_column
        ("53100", "environment"),  # disk_full
        ("53300", "environment"),  # too_many_connections
        ("54000", "environment"),  # program_limit_exceeded
        ("55P03", "environment"),  # lock_not_available
        ("57014", "environment"),  # query_canceled
        ("57P01", "environment"),  # admin_shutdown
        ("58030", "environment"),  # io_error
        ("XX000", "environment"),  # internal_error
        ("40P01", "environment"),  # deadlock_detected — conservative default
    ])
    def test_sqlstate_class_matrix(self, pgcode, expected) -> None:
        """
        The SQLSTATE decides, not the Python class (second re-audit, C1).
        The same ``OperationalError`` class carries both 08006 (a closed
        socket, retry) and 53100 (a full disk, tell someone); the same
        ``ProgrammingError`` carries both 42501 (a REVOKE) and a
        client-side adaptation failure with no SQLSTATE at all. The
        mutation this kills: classifying by exception class.
        """
        # Deliberately the *wrong* class for several of these, to prove the
        # SQLSTATE is what is being read.
        exc = _OperationalError("something happened", pgcode)
        assert _pg_row_guard.classify_pg_error(exc, _fake_psycopg2()) == expected

    def test_disk_full_is_not_an_outage(self) -> None:
        """
        M5: psycopg2 raises DiskFull as OperationalError, so it was routed
        to "PostgreSQL may be stopped", cursor held, exit 0 — a full disk
        reported as a maybe-outage, silently, every five minutes.
        """
        exc = _OperationalError("could not extend file: No space left", "53100")
        assert (
            _pg_row_guard.classify_pg_error(exc, _fake_psycopg2())
            == "environment"
        )
        assert _pg_row_guard.is_outage_error(exc, _fake_psycopg2()) is False

    def test_connection_error_without_a_sqlstate_is_an_outage(self) -> None:
        """A closed socket never gets as far as a SQLSTATE."""
        exc = _OperationalError("server closed the connection unexpectedly")
        assert exc.pgcode is None
        assert (
            _pg_row_guard.classify_pg_error(exc, _fake_psycopg2()) == "outage"
        )


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

    def _execute_values(self, poison_ids: set[str], error_factory):
        """Return an ``execute_values`` stand-in refusing the given ids."""

        def _call(cur, sql, values, page_size=None, fetch=False):
            offending = [row[0] for row in values if row[0] in poison_ids]
            if offending:
                raise error_factory(offending[0])
            return [(row[0],) for row in values]

        return _call

    def test_healthy_rows_land_and_poison_is_reported(
        self, conn: MagicMock, logger: logging.Logger,
    ) -> None:
        """Two good rows insert; the third is named as poison."""
        rows = [("a", 1), ("bad", 2), ("c", 3)]
        returned, poison, status, _detail = _pg_row_guard.insert_rows_individually(
            conn, "INSERT ... VALUES %s RETURNING id", rows,
            psycopg2_module=_fake_psycopg2(),
            execute_values=self._execute_values(
                {"bad"}, lambda rid: _DataError(f"refused {rid}", "22P05"),
            ),
            logger=logger,
        )
        assert returned == {"a", "c"}
        assert [pid for pid, _ in poison] == ["bad"]
        assert status == "row"

    def test_single_refused_row_stays_a_row_fault(
        self, conn: MagicMock, logger: logging.Logger,
    ) -> None:
        """
        A one-row slice that fails is the case the replay exists for:
        there is no "all alike" evidence with a single row, so it must be
        quarantined rather than stalling the cursor forever.
        """
        returned, poison, status, _detail = _pg_row_guard.insert_rows_individually(
            conn, "INSERT ... VALUES %s RETURNING id", [("only", 1)],
            psycopg2_module=_fake_psycopg2(),
            execute_values=self._execute_values(
                {"only"}, lambda rid: _DataError("bad timestamp", "22007"),
            ),
            logger=logger,
        )
        assert returned == set()
        assert [pid for pid, _ in poison] == ["only"]
        assert status == "row"

    def test_correlated_poison_is_still_quarantined(
        self, conn: MagicMock, logger: logging.Logger,
    ) -> None:
        """
        Two rows failing identically is ordinary, not evidence of an
        environment fault: two archived sessions from one LLM run both
        carrying a NUL raise the same 22P05. An earlier version of this
        branch held the cursor here — re-creating the exact stall the
        branch exists to fix, with no escape. The mutation this kills:
        reinstating an "every row failed alike" rule.
        """
        rows = [("nul-a", 1), ("nul-b", 2)]
        returned, poison, status, _detail = _pg_row_guard.insert_rows_individually(
            conn, "INSERT ... VALUES %s RETURNING id", rows,
            psycopg2_module=_fake_psycopg2(),
            execute_values=self._execute_values(
                {"nul-a", "nul-b"},
                lambda rid: _DataError(
                    "unsupported Unicode escape sequence", "22P05",
                ),
            ),
            logger=logger,
        )
        assert status == "row"
        assert [pid for pid, _ in poison] == ["nul-a", "nul-b"]
        assert returned == set()

    @pytest.mark.parametrize("n_rows,expected", [
        # Below the threshold, correlated poison is ordinary and must
        # still be quarantined so the cursor advances — two archived
        # sessions from one LLM run both carrying a NUL is the live case.
        (2, "row"),
        (4, "row"),
        # At and above it, a migration that added a NOT NULL column looks
        # exactly the same, and quarantining would be data loss.
        (5, "correlated"),
        (200, "correlated"),
    ])
    def test_correlated_batches_hold_only_above_the_threshold(
        self, conn: MagicMock, logger: logging.Logger, n_rows, expected,
    ) -> None:
        """
        Finding C3: a whole batch refused under 21/22/23 — a migration
        adding a NOT NULL column, a unique index ON CONFLICT does not
        name — quarantined up to 200 rows a tick and advanced at exit 0.
        The mutation this kills: removing the correlated check, or
        dropping MIN_ROWS_FOR_CORRELATED to 1.
        """
        rows = [(f"r{i}", i) for i in range(n_rows)]
        returned, poison, status, detail = (
            _pg_row_guard.insert_rows_individually(
                conn, "INSERT ... VALUES %s RETURNING id", rows,
                psycopg2_module=_fake_psycopg2(),
                execute_values=self._execute_values(
                    {row[0] for row in rows},
                    lambda rid: _IntegrityError(
                        'null value in column "project"', "23502",
                    ),
                ),
                logger=logger,
                quarantine_cap=1000,
            )
        )
        assert status == expected
        if expected == "correlated":
            assert poison == [], "nothing may be quarantined on a hold"
            assert detail == "23502", "the gate text needs the SQLSTATE"
        else:
            assert len(poison) == n_rows

    def test_the_escape_hatch_forces_the_per_row_path(
        self, conn: MagicMock, logger: logging.Logger,
    ) -> None:
        """
        Once the operator has checked the schema and concluded the rows
        really are poison, one run quarantines them. The mutation this
        kills: ignoring ``quarantine_anyway``.
        """
        rows = [(f"r{i}", i) for i in range(8)]
        returned, poison, status, _detail = (
            _pg_row_guard.insert_rows_individually(
                conn, "INSERT ... VALUES %s RETURNING id", rows,
                psycopg2_module=_fake_psycopg2(),
                execute_values=self._execute_values(
                    {row[0] for row in rows},
                    lambda rid: _DataError("value too long", "22001"),
                ),
                logger=logger,
                quarantine_cap=1000,
                quarantine_anyway=True,
            )
        )
        assert status == "row"
        assert len(poison) == 8

    def test_one_success_defeats_the_correlated_hold(
        self, conn: MagicMock, logger: logging.Logger,
    ) -> None:
        """
        A row that landed proves the schema accepts this shape, so the
        rest are poison by demonstration and are quarantined.
        """
        rows = [(f"r{i}", i) for i in range(8)]
        returned, poison, status, _detail = (
            _pg_row_guard.insert_rows_individually(
                conn, "INSERT ... VALUES %s RETURNING id", rows,
                psycopg2_module=_fake_psycopg2(),
                execute_values=self._execute_values(
                    {f"r{i}" for i in range(1, 8)},
                    lambda rid: _DataError("value too long", "22001"),
                ),
                logger=logger,
                quarantine_cap=1000,
            )
        )
        assert status == "row"
        assert returned == {"r0"}
        assert len(poison) == 7

    def test_mixed_sqlstates_are_not_correlated(
        self, conn: MagicMock, logger: logging.Logger,
    ) -> None:
        """
        Eight rows failing for eight reasons is poison, not a schema
        fault: the hold requires ONE SQLSTATE across the batch.
        """
        rows = [(f"r{i}", i) for i in range(8)]

        def _call(cur, sql, values, page_size=None, fetch=False):
            rid = values[0][0]
            code = "22001" if int(rid[1:]) % 2 else "23502"
            raise _DataError(f"refused {rid}", code)

        returned, poison, status, _detail = (
            _pg_row_guard.insert_rows_individually(
                conn, "INSERT ... VALUES %s RETURNING id", rows,
                psycopg2_module=_fake_psycopg2(),
                execute_values=_call,
                logger=logger,
                quarantine_cap=1000,
            )
        )
        assert status == "row"
        assert len(poison) == 8

    def test_all_rows_refused_but_differently_is_still_row_poison(
        self, conn: MagicMock, logger: logging.Logger,
    ) -> None:
        """
        Distinct SQLSTATEs mean distinct faults in distinct rows — the
        all-alike rule must not swallow a genuinely poisoned slice.
        """
        codes = {"a": "22P05", "b": "23502"}

        def _call(cur, sql, values, page_size=None, fetch=False):
            rid = values[0][0]
            raise _DataError(f"refused {rid}", codes[rid])


        returned, poison, status, _detail = _pg_row_guard.insert_rows_individually(
            conn, "INSERT ... VALUES %s RETURNING id", [("a", 1), ("b", 2)],
            psycopg2_module=_fake_psycopg2(),
            execute_values=_call,
            logger=logger,
        )
        assert status == "row"
        assert [pid for pid, _ in poison] == ["a", "b"]

    def test_one_success_makes_the_rest_row_faults(
        self, conn: MagicMock, logger: logging.Logger,
    ) -> None:
        """
        A single successful insert proves the environment is healthy, so
        identical failures on the others are per-row by demonstration.
        """
        rows = [("good", 1), ("a", 2), ("b", 3)]
        returned, poison, status, _detail = _pg_row_guard.insert_rows_individually(
            conn, "INSERT ... VALUES %s RETURNING id", rows,
            psycopg2_module=_fake_psycopg2(),
            execute_values=self._execute_values(
                {"a", "b"}, lambda rid: _DataError("same fault", "22P05"),
            ),
            logger=logger,
        )
        assert status == "row"
        assert returned == {"good"}
        assert [pid for pid, _ in poison] == ["a", "b"]

    def test_environment_error_mid_replay_stops_immediately(
        self, conn: MagicMock, logger: logging.Logger,
    ) -> None:
        """
        A REVOKE part-way through must stop the replay, quarantine
        nothing, and report an environment fault — not quarantine the
        remaining rows one by one.
        """
        def _call(cur, sql, values, page_size=None, fetch=False):
            rid = values[0][0]
            if rid == "a":
                return [(rid,)]
            raise _ProgrammingError(
                "permission denied for table memories", "42501",
            )

        returned, poison, status, _detail = _pg_row_guard.insert_rows_individually(
            conn, "INSERT ... VALUES %s RETURNING id",
            [("a", 1), ("b", 2), ("c", 3)],
            psycopg2_module=_fake_psycopg2(),
            execute_values=_call,
            logger=logger,
        )
        assert status == "environment"
        assert poison == []
        assert returned == {"a"}

    def test_quarantine_cap_stops_the_run(
        self, conn: MagicMock, logger: logging.Logger,
    ) -> None:
        """
        Beyond the cap the run holds and reports rather than quarantining:
        hundreds of refusals in one tick is a symptom, and every
        quarantined row is one the cursor then skips. The mutation this
        kills: removing the cap check from the replay loop.
        """
        rows = [(f"r{i}", i) for i in range(20)]

        def _call(cur, sql, values, page_size=None, fetch=False):
            rid = values[0][0]
            raise _DataError(f"refused {rid}", "22001")

        returned, poison, status, detail = _pg_row_guard.insert_rows_individually(
            conn, "INSERT ... VALUES %s RETURNING id", rows,
            psycopg2_module=_fake_psycopg2(),
            execute_values=_call,
            logger=logger,
            quarantine_cap=5,
        )
        assert status == "cap_exceeded", (
            "a cap overflow must not read as an environment fault"
        )
        assert poison == []
        assert detail == "5", "the gate text needs the cap that was hit"

    def test_under_the_cap_still_quarantines(
        self, conn: MagicMock, logger: logging.Logger,
    ) -> None:
        """The cap must not fire on an ordinary handful of poison rows."""
        rows = [(f"r{i}", i) for i in range(4)]

        def _call(cur, sql, values, page_size=None, fetch=False):
            rid = values[0][0]
            if rid in ("r1", "r2"):
                raise _DataError(f"refused {rid}", "22001")
            return [(rid,)]

        returned, poison, status, _detail = _pg_row_guard.insert_rows_individually(
            conn, "INSERT ... VALUES %s RETURNING id", rows,
            psycopg2_module=_fake_psycopg2(),
            execute_values=_call,
            logger=logger,
            quarantine_cap=5,
        )
        assert status == "row"
        assert [pid for pid, _ in poison] == ["r1", "r2"]

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

        returned, poison, status, _detail = _pg_row_guard.insert_rows_individually(
            conn, "INSERT ... VALUES %s RETURNING id",
            [("a", 1), ("b", 2), ("c", 3)],
            psycopg2_module=_fake_psycopg2(),
            execute_values=_call,
            logger=logger,
        )
        assert returned == {"a"}
        assert poison == []
        assert status == "outage"
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
            execute_values=self._execute_values(
                {"bad"}, lambda rid: _DataError(f"refused {rid}", "22P05"),
            ),
            logger=logger,
        )
        assert conn.__enter__.call_count == 3

    def test_rolls_back_before_replaying(
        self, conn: MagicMock, logger: logging.Logger,
    ) -> None:
        """
        Re-audit finding M1: called from inside an aborted transaction —
        a caller that did not use ``with conn:`` — every statement would
        fail with InFailedSqlTransaction and the FIRST GOOD ROW would be
        quarantined. The replay now rolls back first. The mutation this
        kills: removing the opening ``conn.rollback()``.
        """
        aborted = {"value": True}

        def _rollback():
            aborted["value"] = False

        conn.rollback.side_effect = _rollback

        def _call(cur, sql, values, page_size=None, fetch=False):
            if aborted["value"]:
                raise _InternalError(
                    "current transaction is aborted, commands ignored "
                    "until end of transaction block",
                    "25P02",
                )
            rid = values[0][0]
            if rid == "bad":
                raise _DataError("genuinely bad row", "22P05")
            return [(rid,)]

        returned, poison, status, _detail = _pg_row_guard.insert_rows_individually(
            conn, "INSERT ... VALUES %s RETURNING id",
            [("good", 1), ("bad", 2)],
            psycopg2_module=_fake_psycopg2(),
            execute_values=_call,
            logger=logger,
        )

        conn.rollback.assert_called_once()
        assert returned == {"good"}, "the first good row was not quarantined"
        assert [pid for pid, _ in poison] == ["bad"]
        assert status == "row"

    def test_rollback_failure_is_tolerated(
        self, conn: MagicMock, logger: logging.Logger,
    ) -> None:
        """A rollback on a dead connection must not mask the real error."""
        conn.rollback.side_effect = _OperationalError("connection is closed")

        def _call(cur, sql, values, page_size=None, fetch=False):
            raise _OperationalError("server closed the connection")

        _returned, poison, status, _detail = _pg_row_guard.insert_rows_individually(
            conn, "INSERT ... VALUES %s RETURNING id", [("a", 1)],
            psycopg2_module=_fake_psycopg2(),
            execute_values=_call,
            logger=logger,
        )
        assert status == "outage"
        assert poison == []


class TestMalformedSqlstate:
    """
    Finding M3 — a ``pgcode`` that is not a five-character string is
    metadata this code does not understand, and guessing from a prefix
    would be worse than admitting so. It classifies as ENVIRONMENT: the
    safe direction, since unrecognisable metadata is not evidence that
    the row is at fault.
    """

    @pytest.mark.parametrize("pgcode", ["", "2", "22", "220011", 22001, b"22001"])
    def test_a_malformed_pgcode_is_an_environment_fault(self, pgcode) -> None:
        """
        The mutation this kills: accepting any ``pgcode`` of length two or
        more, which read "2" as class "2" and bytes as a string.
        """
        exc = _DataError("something", pgcode)
        assert (
            _pg_row_guard.classify_pg_error(exc, _fake_psycopg2())
            == "environment"
        )

    def test_a_well_formed_pgcode_still_classifies(self) -> None:
        """Exactly five characters is what SQLSTATE is defined as."""
        exc = _DataError("value too long", "22001")
        assert _pg_row_guard.sqlstate_class(exc) == "22"
        assert _pg_row_guard.classify_pg_error(exc, _fake_psycopg2()) == "row"

    def test_no_pgcode_at_all_is_still_client_side(self) -> None:
        """``None`` and "malformed" must not be conflated."""
        exc = _ProgrammingError("can't adapt type 'dict'")
        assert _pg_row_guard.sqlstate_class(exc) is None
        assert _pg_row_guard.classify_pg_error(exc, _fake_psycopg2()) == "row"


class TestTransientRemedy:
    """
    Finding M4 — a deadlock is not fixed by adjusting grants, and telling
    an operator to do that at 2 a.m. wastes the one thing the gate buys.
    """

    @pytest.mark.parametrize("state_class", ["40", "57"])
    def test_transient_classes_say_so(self, state_class) -> None:
        """The mutation this kills: one remedy string for every class."""
        remedy = _pg_row_guard.environment_remedy(state_class)
        assert "transient" in remedy.lower()
        assert "retries automatically" in remedy
        assert "grants" not in remedy

    @pytest.mark.parametrize("state_class", ["42", "53", "3D", "XX"])
    def test_persistent_classes_name_the_fix(self, state_class) -> None:
        """These really do need grants, schema, or migration state."""
        remedy = _pg_row_guard.environment_remedy(state_class)
        assert "Fix the database" in remedy

    def test_deadlock_is_still_held_not_quarantined(self) -> None:
        """Transient is about the *remedy*, not about advancing anyway."""
        exc = _OperationalError("deadlock detected", "40P01")
        assert (
            _pg_row_guard.classify_pg_error(exc, _fake_psycopg2())
            == "environment"
        )


class TestNegativeCapHandling:
    """
    Low finding — ``max(0, explicit)`` quietly turned ``--quarantine-cap
    -1`` into "stop at the first refusal", which is not what anyone
    typing a negative number meant. Both sources behave identically now.
    """

    def test_a_negative_flag_falls_back_to_the_default(self, caplog) -> None:
        """The mutation this kills: restoring ``max(0, explicit)``."""
        logger = logging.getLogger("test-cap")
        with caplog.at_level(logging.WARNING):
            cap = _pg_row_guard.resolve_quarantine_cap(-1, logger=logger)
        assert cap == _pg_row_guard.DEFAULT_QUARANTINE_CAP
        assert "negative" in caplog.text

    def test_a_negative_env_var_falls_back_to_the_default(
        self, monkeypatch, caplog,
    ) -> None:
        """Same handling from the environment."""
        monkeypatch.setenv("PA_PG_QUARANTINE_CAP", "-5")
        logger = logging.getLogger("test-cap")
        with caplog.at_level(logging.WARNING):
            cap = _pg_row_guard.resolve_quarantine_cap(logger=logger)
        assert cap == _pg_row_guard.DEFAULT_QUARANTINE_CAP

    def test_zero_is_honoured_from_both_sources(self, monkeypatch) -> None:
        """Zero is a deliberate "stop at the first refusal", not a slip."""
        assert _pg_row_guard.resolve_quarantine_cap(0) == 0
        monkeypatch.setenv("PA_PG_QUARANTINE_CAP", "0")
        assert _pg_row_guard.resolve_quarantine_cap() == 0


class TestQuarantineAnywayResolution:
    """The escape hatch is per-run, from either the flag or the variable."""

    def test_the_flag_wins(self) -> None:
        """An explicit flag needs no variable."""
        assert _pg_row_guard.resolve_quarantine_anyway(True) is True

    @pytest.mark.parametrize("value", ["1", "true", "yes", "ON"])
    def test_the_variable_is_honoured(self, monkeypatch, value) -> None:
        """Several spellings, because operators type what they remember."""
        monkeypatch.setenv("PA_PG_QUARANTINE_ANYWAY", value)
        assert _pg_row_guard.resolve_quarantine_anyway() is True

    @pytest.mark.parametrize("value", ["", "0", "no", "maybe"])
    def test_anything_else_is_off(self, monkeypatch, value) -> None:
        """The default must be the safe one."""
        monkeypatch.setenv("PA_PG_QUARANTINE_ANYWAY", value)
        assert _pg_row_guard.resolve_quarantine_anyway() is False
