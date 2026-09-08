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
    """Stand-in for ``psycopg2.Error``."""


class _OperationalError(_Error):
    """Stand-in for ``psycopg2.OperationalError``."""


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
        code = indexer.main(["--archive-root", str(archive_root)])
        assert code == 3

    def test_healthy_run_returns_zero(
        self, indexer, monkeypatch, archive_root,
    ):
        """The happy path is unchanged by the new guards."""
        _install_fake_psycopg2(monkeypatch)
        monkeypatch.setattr(indexer, "assert_schema_version", lambda conn: None)
        code = indexer.main(["--archive-root", str(archive_root)])
        assert code == 0
