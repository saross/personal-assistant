"""
Tests for ``scripts/index-session-content.py``.

Audit round two, tranche 3a, finding P5 (lens A-M2 and A-M3): this was
the only PostgreSQL-touching script in the tranche with no
schema-version guard, and an unguarded ``psycopg2.connect`` that turned
a stopped database into a raw traceback rather than the degradation
every sibling script performs.

psycopg2 is a stand-in module here — no database is contacted, and the
archive fixtures are plain files under ``tmp_path``.
"""

from __future__ import annotations

import gzip
import importlib.util
import json
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture(scope="module")
def indexer():
    """Load the hyphenated script as a module."""
    path = SCRIPTS_DIR / "index-session-content.py"
    spec = importlib.util.spec_from_file_location("index_session_content", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["index_session_content"] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Fake psycopg2
# ---------------------------------------------------------------------------


class _Error(Exception):
    """Stand-in for ``psycopg2.Error``.

    Carries ``pgcode`` like the real class: PostgreSQL's SQLSTATE for a
    server-side error, ``None`` for one psycopg2 raised client-side.
    """

    def __init__(self, message: str = "", pgcode: str | None = None) -> None:
        super().__init__(message)
        self.pgcode = pgcode


class _OperationalError(_Error):
    """Stand-in for ``psycopg2.OperationalError``."""


class _InterfaceError(_Error):
    """Stand-in for ``psycopg2.InterfaceError``."""


class _DataError(_Error):
    """Stand-in for ``psycopg2.DataError`` — this row's content is wrong."""


class _ProgrammingError(_Error):
    """Stand-in for ``psycopg2.ProgrammingError`` — e.g. a REVOKE."""


class _InternalError(_Error):
    """Stand-in for ``psycopg2.InternalError``."""


def _install_fake_psycopg2(
    monkeypatch: pytest.MonkeyPatch,
    *,
    raise_on_connect: bool = False,
    schema_version: str = "3",
) -> MagicMock:
    """Install a stand-in psycopg2 and return the connection mock."""
    fake = types.ModuleType("psycopg2")
    fake_extras = types.ModuleType("psycopg2.extras")
    fake.Error = _Error
    fake.OperationalError = _OperationalError
    fake.InterfaceError = _InterfaceError
    fake.DataError = _DataError
    fake.ProgrammingError = _ProgrammingError
    fake.InternalError = _InternalError

    cur = MagicMock()
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchone.return_value = (schema_version,)
    cur.fetchall.return_value = []

    conn = MagicMock()
    conn.cursor.return_value = cur

    if raise_on_connect:
        fake.connect = MagicMock(
            side_effect=_OperationalError(
                "could not connect to server: Connection refused"
            )
        )
    else:
        fake.connect = MagicMock(return_value=conn)

    fake_extras.execute_values = MagicMock(return_value=None)
    monkeypatch.setitem(sys.modules, "psycopg2", fake)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", fake_extras)
    return conn


@pytest.fixture
def archive_root(tmp_path: Path) -> Path:
    """A minimal archive tree with one gzipped transcript."""
    session_dir = tmp_path / "personal-assistant" / "2026-09-01T10-00_abc"
    session_dir.mkdir(parents=True)
    (session_dir / "session.meta.json").write_text(
        json.dumps({
            "session": {"id": "abc-123"},
            "project": {"name": "personal-assistant"},
        }),
        encoding="utf-8",
    )
    turns = [
        {"type": "user", "message": {"role": "user", "content": "hello"}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "hi there"}],
            },
        },
    ]
    with gzip.open(session_dir / "session.jsonl.gz", "wt") as handle:
        for turn in turns:
            handle.write(json.dumps(turn) + "\n")
    return tmp_path


# ---------------------------------------------------------------------------
# P5 — schema-version guard
# ---------------------------------------------------------------------------


class TestSchemaVersionGuard:
    """schema.sql's stated contract, finally honoured by this script."""

    def test_schema_version_is_asserted_before_any_query(
        self, indexer, monkeypatch, archive_root,
    ):
        """
        Every other PG-touching script asserts ``meta.schema_version``
        before issuing a query; this one issued its DELETE and INSERT
        against whatever shape it found. The mutation this kills:
        removing the ``assert_schema_version`` call.
        """
        _install_fake_psycopg2(monkeypatch)
        seen = {"called": False}

        def _assert(conn):
            seen["called"] = True

        monkeypatch.setattr(indexer, "assert_schema_version", _assert)

        indexer.index_archive(archive_root, None, False, False)

        assert seen["called"] is True

    def test_mismatched_schema_exits_two_without_writing(
        self, indexer, monkeypatch, archive_root,
    ):
        """
        A version mismatch must stop before any DELETE runs — the
        consequence, not merely the exit code.
        """
        conn = _install_fake_psycopg2(monkeypatch)

        def _mismatch(_conn):
            raise indexer.SchemaVersionError("expected 3, found 4")

        monkeypatch.setattr(indexer, "assert_schema_version", _mismatch)

        with pytest.raises(SystemExit) as excinfo:
            indexer.index_archive(archive_root, None, False, False)

        assert excinfo.value.code == 2
        assert sys.modules["psycopg2.extras"].execute_values.call_count == 0
        conn.close.assert_called_once()


# ---------------------------------------------------------------------------
# P5 — a Postgres outage degrades rather than tracebacks
# ---------------------------------------------------------------------------


class TestPostgresOutage:
    """A stopped database is not critical: the archive tree is canonical."""

    def test_unreachable_database_returns_none(
        self, indexer, monkeypatch, archive_root,
    ):
        """
        ``psycopg2.connect`` was unguarded and ``main`` caught only
        ``ImportError``, so a stopped PostgreSQL produced a traceback.
        The mutation this kills: removing the ``except
        psycopg2.OperationalError`` around ``connect``.
        """
        _install_fake_psycopg2(monkeypatch, raise_on_connect=True)
        assert indexer.index_archive(archive_root, None, False, False) is None

    def test_main_reports_exit_code_three(
        self, indexer, monkeypatch, archive_root,
    ):
        """The documented outage exit code, asserted end to end."""
        _install_fake_psycopg2(monkeypatch, raise_on_connect=True)
        # ``main`` renices itself to be a polite background citizen;
        # niceness cannot be lowered again, so never let it touch the
        # pytest process.
        monkeypatch.setattr(os, "nice", lambda increment: 0)
        code = indexer.main(["--archive-root", str(archive_root)])
        assert code == 3

    def test_healthy_run_returns_zero(
        self, indexer, monkeypatch, archive_root,
    ):
        """The happy path is unchanged by the new guards."""
        _install_fake_psycopg2(monkeypatch)
        monkeypatch.setattr(indexer, "assert_schema_version", lambda conn: None)
        monkeypatch.setattr(os, "nice", lambda increment: 0)
        code = indexer.main(["--archive-root", str(archive_root)])
        assert code == 0


# ---------------------------------------------------------------------------
# Re-audit finding M4 — NUL sanitising and per-file refusal handling
# ---------------------------------------------------------------------------


class TestTranscriptTextIsSanitised:
    """A NUL in transcript prose must never reach ``session_chunks.text``."""

    def test_nul_is_stripped_from_a_turn(self, indexer):
        """
        The same LLM-generated prose that put NULs into two
        session.meta.json files is what this indexes. PostgreSQL cannot
        store U+0000 in a text column, and psycopg2 raises ValueError
        before the statement is even sent — which is not a psycopg2.Error
        and escaped every handler. The mutation this kills: dropping the
        ``sanitise_nuls`` call from ``extract_turn_text``.
        """
        record = {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "ran\x00 the sweep"}],
            },
        }
        assert indexer.extract_turn_text(record) == "ran the sweep"

    def test_a_turn_that_is_only_nuls_is_skipped(self, indexer):
        """Nothing left after stripping means nothing worth indexing."""
        record = {
            "type": "user",
            "message": {"role": "user", "content": "\x00\x00"},
        }
        assert indexer.extract_turn_text(record) is None

    def test_ordinary_text_is_untouched(self, indexer):
        """The sanitiser must not alter clean prose."""
        record = {
            "type": "user",
            "message": {"role": "user", "content": "a normal question"},
        }
        assert indexer.extract_turn_text(record) == "a normal question"


class TestRefusedFileIsSkipped:
    """
    Aborting on the first poison file blocked every later file forever:
    the incremental skip is keyed on ``source_mtime``, so an unindexed
    file is retried next run, discovery is sorted, and the run died at the
    same file every time before reaching the rest.
    """

    def _two_file_archive(self, tmp_path: Path) -> Path:
        """Build an archive with two indexable sessions, in sorted order."""
        for name in ("aaa-poison", "bbb-healthy"):
            session_dir = tmp_path / "personal-assistant" / name
            session_dir.mkdir(parents=True)
            (session_dir / "session.meta.json").write_text(
                json.dumps({
                    "session": {"id": name},
                    "project": {"name": "personal-assistant"},
                }),
                encoding="utf-8",
            )
            (session_dir / "session.jsonl").write_text(
                json.dumps({
                    "type": "user",
                    "message": {"role": "user", "content": f"hello {name}"},
                }) + "\n",
                encoding="utf-8",
            )
        return tmp_path

    def test_refused_file_does_not_stop_the_run(
        self, indexer, monkeypatch, tmp_path,
    ):
        """
        The first file is refused; the second must still be indexed. The
        mutation this kills: removing the per-file try/except so the
        exception propagates out of the loop.
        """
        archive = self._two_file_archive(tmp_path)
        _install_fake_psycopg2(monkeypatch)
        monkeypatch.setattr(indexer, "assert_schema_version", lambda conn: None)

        def _refuse_first(cur, sql, values, page_size=None, fetch=False):
            if any("aaa-poison" in str(value) for value in values[0]):
                raise _DataError("value too long for type character varying")
            return None

        sys.modules["psycopg2.extras"].execute_values.side_effect = _refuse_first

        # ``force`` so the incremental mtime skip does not short-circuit
        # both files before either reaches the INSERT.
        indexed, skipped, chunks = indexer.index_archive(
            archive, None, False, True,
        )

        assert indexed == 1, "the healthy file was not indexed"
        assert chunks == 1

    def test_outage_still_aborts_the_run(self, indexer, monkeypatch, tmp_path):
        """
        A database that went away is not a poison file. Continuing would
        report every remaining file as refused.
        """
        archive = self._two_file_archive(tmp_path)
        _install_fake_psycopg2(monkeypatch)
        monkeypatch.setattr(indexer, "assert_schema_version", lambda conn: None)

        def _gone(cur, sql, values, page_size=None, fetch=False):
            raise _OperationalError("server closed the connection unexpectedly")

        sys.modules["psycopg2.extras"].execute_values.side_effect = _gone

        with pytest.raises(_OperationalError):
            indexer.index_archive(archive, None, False, True)

    def test_environment_fault_aborts_the_run(
        self, indexer, monkeypatch, tmp_path,
    ):
        """A REVOKE or a missing column is not a poison file either."""
        archive = self._two_file_archive(tmp_path)
        _install_fake_psycopg2(monkeypatch)
        monkeypatch.setattr(indexer, "assert_schema_version", lambda conn: None)

        def _revoke(cur, sql, values, page_size=None, fetch=False):
            raise _ProgrammingError(
                "permission denied for table session_chunks", "42501",
            )

        sys.modules["psycopg2.extras"].execute_values.side_effect = _revoke

        with pytest.raises(_ProgrammingError):
            indexer.index_archive(archive, None, False, True)
