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
    cur.fetchall.return_value = []

    # fetchone answers the schema-version probe with a version and the
    # "already indexed at this mtime?" probe with nothing. A blanket
    # truthy return makes every file look already-indexed, which silently
    # short-circuits any test that does not pass ``force``.
    last_sql = {"value": ""}

    def _execute(sql, *args, **kwargs):
        last_sql["value"] = str(sql)
        return None

    def _fetchone():
        if "meta" in last_sql["value"]:
            return (schema_version,)
        return None

    cur.execute.side_effect = _execute
    cur.fetchone.side_effect = _fetchone

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


@pytest.fixture(autouse=True)
def pinned_refusal_file(indexer, tmp_path, monkeypatch):
    """Keep the refusal memory inside the test's tmp directory.

    It lives in ~/.cache in production; a test writing the real one would
    make the next real run skip files it should have indexed.
    """
    path = tmp_path / "cache" / "index-session-content-refusals.json"
    monkeypatch.setattr(indexer, "REFUSAL_FILE", path)
    return path


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
        self, indexer, monkeypatch, archive_root, pinned_refusal_file,
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

        indexer.index_archive(
            archive_root, None, False, False, pinned_refusal_file,
        )

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

        with pytest.raises(indexer.IndexerAbort) as excinfo:
            indexer.index_archive(archive_root, None, False, False)

        assert excinfo.value.exit_code == 2
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
        with pytest.raises(indexer.IndexerAbort) as excinfo:
            indexer.index_archive(archive_root, None, False, False)
        assert excinfo.value.exit_code == 3

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
        self, indexer, monkeypatch, tmp_path, pinned_refusal_file,
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
        indexed, skipped, chunks, refused = indexer.index_archive(
            archive, None, False, True, pinned_refusal_file,
        )

        assert indexed == 1, "the healthy file was not indexed"
        assert chunks == 1
        assert refused == 1

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

        with pytest.raises(indexer.IndexerAbort) as excinfo:
            indexer.index_archive(archive, None, False, True)
        assert excinfo.value.exit_code == 3

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

        with pytest.raises(indexer.IndexerAbort) as excinfo:
            indexer.index_archive(archive, None, False, True)
        assert excinfo.value.exit_code == 4


# ---------------------------------------------------------------------------
# Second re-audit, findings M3 and M4
# ---------------------------------------------------------------------------


class TestRefusalMemory:
    """
    M3 — a refused file was re-parsed and re-refused on every run, for
    ever, and reported nothing. The incremental skip is keyed on
    ``source_mtime`` in ``session_chunks``, and a refused file writes no
    row there, so it never became "already indexed".
    """

    def _archive(self, tmp_path: Path, name: str = "aaa-poison") -> Path:
        """One indexable session."""
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
                "message": {"role": "user", "content": "hello"},
            }) + "\n",
            encoding="utf-8",
        )
        return tmp_path

    def _refuse_everything(self, cur, sql, values, page_size=None, fetch=False):
        """PostgreSQL refuses this file's rows on content grounds."""
        raise _DataError("value too long for type character varying", "22001")

    def test_a_refusal_is_remembered(
        self, indexer, monkeypatch, tmp_path, pinned_refusal_file,
    ):
        """
        The mutation this kills: dropping the ``known_refusals[rel_path]``
        assignment, so nothing is remembered.
        """
        archive = self._archive(tmp_path)
        _install_fake_psycopg2(monkeypatch)
        monkeypatch.setattr(indexer, "assert_schema_version", lambda conn: None)
        sys.modules["psycopg2.extras"].execute_values.side_effect = (
            self._refuse_everything
        )

        indexer.index_archive(archive, None, False, True, pinned_refusal_file)

        remembered = indexer.load_refusals(pinned_refusal_file)
        assert list(remembered) == [
            "personal-assistant/aaa-poison/session.jsonl",
        ]

    def test_a_remembered_refusal_is_not_reparsed(
        self, indexer, monkeypatch, tmp_path, pinned_refusal_file,
    ):
        """
        Second run: the file must be skipped without the database being
        asked again — and still counted as refused so it is reported.
        """
        archive = self._archive(tmp_path)
        _install_fake_psycopg2(monkeypatch)
        monkeypatch.setattr(indexer, "assert_schema_version", lambda conn: None)
        sys.modules["psycopg2.extras"].execute_values.side_effect = (
            self._refuse_everything
        )
        indexer.index_archive(archive, None, False, True, pinned_refusal_file)

        calls = {"n": 0}

        def _count(cur, sql, values, page_size=None, fetch=False):
            calls["n"] += 1
            return self._refuse_everything(cur, sql, values, page_size, fetch)

        sys.modules["psycopg2.extras"].execute_values.side_effect = _count

        indexed, skipped, chunks, refused = indexer.index_archive(
            archive, None, False, False, pinned_refusal_file,
        )

        assert calls["n"] == 0, "the refused file was sent to PostgreSQL again"
        assert refused == 1
        assert skipped == 1

    def test_a_changed_file_is_retried(
        self, indexer, monkeypatch, tmp_path, pinned_refusal_file,
    ):
        """
        The memory is keyed on ``archive_path`` *and* ``source_mtime``, so
        repairing the transcript makes the next run try it again.
        """
        archive = self._archive(tmp_path)
        transcript = archive / "personal-assistant" / "aaa-poison" / "session.jsonl"
        _install_fake_psycopg2(monkeypatch)
        monkeypatch.setattr(indexer, "assert_schema_version", lambda conn: None)
        sys.modules["psycopg2.extras"].execute_values.side_effect = (
            self._refuse_everything
        )
        indexer.index_archive(archive, None, False, True, pinned_refusal_file)

        # Repair the file: new content, new mtime.
        transcript.write_text(
            json.dumps({
                "type": "user",
                "message": {"role": "user", "content": "repaired"},
            }) + "\n",
            encoding="utf-8",
        )
        os.utime(transcript, (0, 0))
        sys.modules["psycopg2.extras"].execute_values.side_effect = None
        sys.modules["psycopg2.extras"].execute_values.return_value = None

        indexed, skipped, chunks, refused = indexer.index_archive(
            archive, None, False, False, pinned_refusal_file,
        )

        assert indexed == 1, "the repaired file was not retried"
        assert refused == 0
        assert indexer.load_refusals(pinned_refusal_file) == {}

    def test_force_ignores_the_memory(
        self, indexer, monkeypatch, tmp_path, pinned_refusal_file,
    ):
        """``--force`` is the operator saying "try them again anyway"."""
        archive = self._archive(tmp_path)
        _install_fake_psycopg2(monkeypatch)
        monkeypatch.setattr(indexer, "assert_schema_version", lambda conn: None)
        sys.modules["psycopg2.extras"].execute_values.side_effect = (
            self._refuse_everything
        )
        indexer.index_archive(archive, None, False, True, pinned_refusal_file)

        calls = {"n": 0}

        def _count(cur, sql, values, page_size=None, fetch=False):
            calls["n"] += 1
            return None

        sys.modules["psycopg2.extras"].execute_values.side_effect = _count
        indexer.index_archive(archive, None, False, True, pinned_refusal_file)

        assert calls["n"] == 1, "--force did not retry the refused file"

    def test_main_exits_five_when_a_file_was_refused(
        self, indexer, monkeypatch, tmp_path, pinned_refusal_file,
    ):
        """
        A refusal used to be one line in a "Done:" message that otherwise
        reads like success. The mutation this kills: returning 0 when
        ``refused`` is non-zero.
        """
        archive = self._archive(tmp_path)
        _install_fake_psycopg2(monkeypatch)
        monkeypatch.setattr(indexer, "assert_schema_version", lambda conn: None)
        monkeypatch.setattr(os, "nice", lambda increment: 0)
        sys.modules["psycopg2.extras"].execute_values.side_effect = (
            self._refuse_everything
        )

        code = indexer.main(["--archive-root", str(archive), "--force"])

        assert code == 5

    def test_corrupt_refusal_memory_reads_as_empty(
        self, indexer, pinned_refusal_file,
    ):
        """The memory is an optimisation, never a gate on correctness."""
        pinned_refusal_file.parent.mkdir(parents=True, exist_ok=True)
        pinned_refusal_file.write_text("{not json", encoding="utf-8")
        assert indexer.load_refusals(pinned_refusal_file) == {}


class TestMidRunAbortsHaveExitCodes:
    """M4 — a mid-run fault must not traceback out of ``main``."""

    def _archive(self, tmp_path: Path) -> Path:
        session_dir = tmp_path / "personal-assistant" / "sess"
        session_dir.mkdir(parents=True)
        (session_dir / "session.meta.json").write_text(
            json.dumps({
                "session": {"id": "sess"},
                "project": {"name": "personal-assistant"},
            }),
            encoding="utf-8",
        )
        (session_dir / "session.jsonl").write_text(
            json.dumps({
                "type": "user",
                "message": {"role": "user", "content": "hello"},
            }) + "\n",
            encoding="utf-8",
        )
        return tmp_path

    @pytest.mark.parametrize("exc,expected", [
        (_OperationalError("server closed the connection"), 3),
        (_ProgrammingError("permission denied", "42501"), 4),
    ])
    def test_main_returns_the_code_instead_of_tracebacking(
        self, indexer, monkeypatch, tmp_path, pinned_refusal_file,
        exc, expected,
    ):
        """
        ``main`` caught only ImportError, so a mid-run outage or REVOKE
        produced a raw traceback while the identical fault at connect time
        degraded politely. The mutation this kills: removing the
        ``except IndexerAbort`` clause from ``main``.
        """
        archive = self._archive(tmp_path)
        _install_fake_psycopg2(monkeypatch)
        monkeypatch.setattr(indexer, "assert_schema_version", lambda conn: None)
        monkeypatch.setattr(os, "nice", lambda increment: 0)

        def _raise(cur, sql, values, page_size=None, fetch=False):
            raise exc

        sys.modules["psycopg2.extras"].execute_values.side_effect = _raise

        code = indexer.main(["--archive-root", str(archive), "--force"])

        assert code == expected


class TestNulCountsAreReported:
    """L3 — the counts ``sanitise_nuls`` returns were being discarded."""

    def test_stats_dict_accumulates_the_count(self, indexer):
        """
        Text was being silently altered on the way into the index. The
        mutation this kills: dropping the ``stats`` accumulation.
        """
        stats: dict[str, int] = {"nuls_removed": 0}
        indexer.extract_turn_text(
            {
                "type": "user",
                "message": {"role": "user", "content": "a\x00b\x00c"},
            },
            stats=stats,
        )
        indexer.extract_turn_text(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "d\x00e"}],
                },
            },
            stats=stats,
        )
        assert stats["nuls_removed"] == 3

    def test_stats_is_optional(self, indexer):
        """Callers that do not care must not have to pass a dict."""
        assert indexer.extract_turn_text({
            "type": "user",
            "message": {"role": "user", "content": "a\x00b"},
        }) == "ab"
