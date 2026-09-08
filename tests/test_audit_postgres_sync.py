"""
Smoke tests for scripts/audit-postgres-sync.py.

Covers JSONL id extraction, archive id extraction, and the AuditResult
``is_clean`` predicate without touching a real PostgreSQL instance.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
from pathlib import Path

import pytest

# Import the audit module (hyphenated filename requires importlib).
# Register in sys.modules before exec so that @dataclass can look up the
# module's namespace during class construction.
_audit_path = (
    Path(__file__).parent.parent / "scripts" / "audit-postgres-sync.py"
)
_spec = importlib.util.spec_from_file_location("audit_postgres_sync", _audit_path)
audit_mod = importlib.util.module_from_spec(_spec)
sys.modules["audit_postgres_sync"] = audit_mod
_spec.loader.exec_module(audit_mod)


@pytest.fixture
def logger() -> logging.Logger:
    """Quiet logger for test runs."""
    return logging.getLogger("test-audit")


class TestReadJsonlIds:
    """Canonical id extraction from a JSONL file."""

    def test_collects_all_ids(self, tmp_path: Path, logger: logging.Logger) -> None:
        """Every valid line contributes its id to the set."""
        jsonl = tmp_path / "memories.jsonl"
        jsonl.write_text(
            "\n".join(
                json.dumps({"id": f"mem-{i}", "content": "x"}) for i in range(3)
            )
            + "\n",
            encoding="utf-8",
        )
        ids = audit_mod._read_jsonl_ids(jsonl, logger)
        assert ids == {"mem-0", "mem-1", "mem-2"}

    def test_dedupes_repeated_ids(
        self, tmp_path: Path, logger: logging.Logger
    ) -> None:
        """Duplicate ids collapse to a single set entry."""
        jsonl = tmp_path / "memories.jsonl"
        jsonl.write_text(
            json.dumps({"id": "dup"}) + "\n" + json.dumps({"id": "dup"}) + "\n",
            encoding="utf-8",
        )
        ids = audit_mod._read_jsonl_ids(jsonl, logger)
        assert ids == {"dup"}

    def test_skips_blank_and_malformed(
        self, tmp_path: Path, logger: logging.Logger
    ) -> None:
        """Blank lines and malformed JSON are tolerated."""
        jsonl = tmp_path / "memories.jsonl"
        jsonl.write_text(
            "\n"
            + "{not json\n"
            + json.dumps({"id": "ok-1"}) + "\n"
            + "   \n"
            + json.dumps({"no_id": True}) + "\n"
            + json.dumps({"id": "ok-2"}) + "\n",
            encoding="utf-8",
        )
        ids = audit_mod._read_jsonl_ids(jsonl, logger)
        assert ids == {"ok-1", "ok-2"}


class TestReadArchiveIds:
    """Canonical id extraction from session.meta.json files."""

    def test_recurses_and_extracts(
        self, tmp_path: Path, logger: logging.Logger
    ) -> None:
        """Session ids are found recursively beneath the archive root."""
        for project, sid in [("proj-a", "sess-1"), ("proj-b", "sess-2")]:
            d = tmp_path / project / "2026-04-23_xyz"
            d.mkdir(parents=True)
            (d / "session.meta.json").write_text(
                json.dumps({"session": {"id": sid}}),
                encoding="utf-8",
            )

        ids = audit_mod._read_session_archive_ids(tmp_path, logger)
        assert ids == {"sess-1", "sess-2"}

    def test_missing_root_returns_empty(
        self, tmp_path: Path, logger: logging.Logger
    ) -> None:
        """A nonexistent archive root yields an empty set."""
        ids = audit_mod._read_session_archive_ids(
            tmp_path / "does-not-exist", logger
        )
        assert ids == set()


class TestAuditResult:
    """Semantics of the AuditResult container."""

    def test_is_clean_when_no_canonical_missing(self) -> None:
        """An empty only_in_canonical means the audit is clean."""
        result = audit_mod.AuditResult(
            source_name="memories",
            canonical_count=10,
            postgres_count=10,
            only_in_canonical=[],
            only_in_postgres=[],
        )
        assert result.is_clean is True

    def test_not_clean_when_canonical_missing(self) -> None:
        """Any canonical id missing from PG means the audit is dirty."""
        result = audit_mod.AuditResult(
            source_name="memories",
            canonical_count=10,
            postgres_count=9,
            only_in_canonical=["missing-id"],
            only_in_postgres=[],
        )
        assert result.is_clean is False

    def test_a_memories_orphan_fails_the_audit(self) -> None:
        """A PG row with no canonical line is reachable by /recall.

        Audit 2026-09-08, finding AN9: ``only_in_postgres`` was ignored
        entirely, so a row the corpus does not contain — and cannot be
        re-derived from — reported "in sync".
        """
        result = audit_mod.AuditResult(
            source_name="memories",
            canonical_count=9,
            postgres_count=10,
            only_in_canonical=[],
            only_in_postgres=["orphan"],
            strict_orphans=True,
        )
        assert result.is_clean is False

    def test_a_sessions_orphan_does_not(self) -> None:
        """~/cc-archives on one machine is a mirror, not the union."""
        result = audit_mod.AuditResult(
            source_name="sessions",
            canonical_count=9,
            postgres_count=10,
            only_in_canonical=[],
            only_in_postgres=["orphan"],
            strict_orphans=False,
        )
        assert result.is_clean is True

    def test_divergent_content_fails_the_audit(self) -> None:
        """Membership agreeing is not the same as the stores agreeing."""
        result = audit_mod.AuditResult(
            source_name="memories",
            canonical_count=10,
            postgres_count=10,
            only_in_canonical=[],
            only_in_postgres=[],
            divergent=["2031-03-02-aaaabbbbcccc"],
            strict_orphans=True,
        )
        assert result.is_clean is False


class TestReadArchivePartitionIds:
    """Cold-store partition id extraction for --archive-parity."""

    def test_unions_across_partitions(
        self, tmp_path: Path, logger: logging.Logger
    ) -> None:
        """Ids from every memories-archive-*.jsonl partition are unioned."""
        (tmp_path / "memories-archive-2026-05.jsonl").write_text(
            json.dumps({"id": "a"}) + "\n" + json.dumps({"id": "b"}) + "\n",
            encoding="utf-8",
        )
        (tmp_path / "memories-archive-2026-06.jsonl").write_text(
            json.dumps({"id": "b"}) + "\n" + json.dumps({"id": "c"}) + "\n",
            encoding="utf-8",
        )
        ids = audit_mod._read_archive_partition_ids(tmp_path, logger)
        assert ids == {"a", "b", "c"}

    def test_ignores_non_partition_files(
        self, tmp_path: Path, logger: logging.Logger
    ) -> None:
        """Only files matching the partition glob are read."""
        (tmp_path / "memories-archive-2026-06.jsonl").write_text(
            json.dumps({"id": "a"}) + "\n", encoding="utf-8"
        )
        # A decoy that must NOT be read (e.g. the live file or a run log).
        (tmp_path / "archive-runs.jsonl").write_text(
            json.dumps({"id": "should-be-ignored"}) + "\n", encoding="utf-8"
        )
        ids = audit_mod._read_archive_partition_ids(tmp_path, logger)
        assert ids == {"a"}

    def test_missing_dir_returns_empty(
        self, tmp_path: Path, logger: logging.Logger
    ) -> None:
        """A nonexistent archive directory yields an empty set."""
        ids = audit_mod._read_archive_partition_ids(
            tmp_path / "nope", logger
        )
        assert ids == set()

    def test_empty_dir_returns_empty(
        self, tmp_path: Path, logger: logging.Logger
    ) -> None:
        """A directory with no partitions yields an empty set."""
        ids = audit_mod._read_archive_partition_ids(tmp_path, logger)
        assert ids == set()


class TestArchiveParityResult:
    """Asymmetric pass/fail semantics of ArchiveParityResult."""

    def test_clean_when_no_leak(self) -> None:
        """Archived ids absent from PG do NOT fail parity."""
        result = audit_mod.ArchiveParityResult(
            archive_count=100,
            archived_in_pg=40,
            archived_not_in_pg=60,
            leaked_active=[],
        )
        assert result.is_clean is True

    def test_dirty_when_archived_id_still_active(self) -> None:
        """An archived id still is_active=TRUE is a recall leak (failure)."""
        result = audit_mod.ArchiveParityResult(
            archive_count=100,
            archived_in_pg=100,
            archived_not_in_pg=0,
            leaked_active=["leaked-1"],
        )
        assert result.is_clean is False


# ============================================================================
# The reconciliation engine, driven against a fake connection
# (findings ANT1 / ANT2 / AN4 / AN9)
# ============================================================================

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fake_audit_pg import (  # noqa: E402
    FakeDatabase, WriteAttempted, connect_factory,
)


def _corpus(tmp_path: Path, records: list[dict]) -> Path:
    """Write a synthetic canonical JSONL and return its path."""
    path = tmp_path / "memories.jsonl"
    path.write_text(
        "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8",
    )
    return path


def _mem(mid: str, content: str = "a note", **kw) -> dict:
    """One synthetic memory record / row (the fields the audit compares)."""
    row = {"id": mid, "content": content, "is_active": True, "verified": "true"}
    row.update(kw)
    return row


@pytest.fixture
def fake_pg(monkeypatch):
    """Patch ``psycopg2.connect`` to hand out one fake connection.

    Returns a callable taking a :class:`FakeDatabase` and returning the
    connection object, so a test can inspect every statement afterwards.
    """
    import psycopg2

    def install(db: FakeDatabase):
        conn, connect = connect_factory(db)
        monkeypatch.setattr(psycopg2, "connect", connect)
        return conn

    return install


class TestAuditMemoriesAgainstAFakeConnection:
    """The set differences, the fingerprint comparison, and the SQL itself."""

    def test_missing_rows_are_reported_in_the_right_direction(
        self, tmp_path, logger, fake_pg,
    ) -> None:
        """Kills the swapped-set-difference mutation.

        The canonical holds an id PostgreSQL lacks and PostgreSQL holds one
        the canonical lacks; swapping the two subtractions puts each in the
        other's list.
        """
        corpus = _corpus(tmp_path, [_mem("m-1"), _mem("m-2")])
        fake_pg(FakeDatabase(memories=[_mem("m-1"), _mem("m-9")]))
        result = audit_mod.audit_memories(corpus, logger)
        assert result.only_in_canonical == ["m-2"]
        assert result.only_in_postgres == ["m-9"]
        assert result.is_clean is False

    def test_identical_stores_are_clean(self, tmp_path, logger, fake_pg) -> None:
        """The control: agreement on membership AND content passes."""
        corpus = _corpus(tmp_path, [_mem("m-1"), _mem("m-2")])
        fake_pg(FakeDatabase(memories=[_mem("m-1"), _mem("m-2")]))
        result = audit_mod.audit_memories(corpus, logger)
        assert (result.only_in_canonical, result.only_in_postgres) == ([], [])
        assert result.divergent == []
        assert result.is_clean is True

    @pytest.mark.parametrize("field,pg_value", [
        ("content", "an EDITED note"),
        ("is_active", False),
        ("verified", "false"),
    ])
    def test_identical_ids_with_different_rows_are_not_in_sync(
        self, tmp_path, logger, fake_pg, field, pg_value,
    ) -> None:
        """Kills the mutation comparing id sets only (finding AN9).

        The sync inserts ON CONFLICT DO NOTHING, so an edited record is
        exactly what cannot propagate — and every id matched.
        """
        corpus = _corpus(tmp_path, [_mem("m-1")])
        fake_pg(FakeDatabase(memories=[_mem("m-1", **{field: pg_value})]))
        result = audit_mod.audit_memories(corpus, logger)
        assert result.only_in_canonical == []
        assert result.divergent == ["m-1"]
        assert result.is_clean is False

    def test_a_missing_is_active_reads_as_active_on_both_sides(
        self, tmp_path, logger, fake_pg,
    ) -> None:
        """The column defaults TRUE; an absent JSONL field must match it."""
        record = _mem("m-1")
        del record["is_active"]
        corpus = _corpus(tmp_path, [record])
        fake_pg(FakeDatabase(memories=[_mem("m-1", is_active=True)]))
        assert audit_mod.audit_memories(corpus, logger).divergent == []

    def test_a_duplicate_canonical_id_is_reported(
        self, tmp_path, logger, fake_pg,
    ) -> None:
        """Two lines, one id: PostgreSQL keeps one of them (finding AN9)."""
        corpus = _corpus(
            tmp_path, [_mem("m-1"), _mem("m-1", content="second copy")],
        )
        fake_pg(FakeDatabase(memories=[_mem("m-1", content="second copy")]))
        result = audit_mod.audit_memories(corpus, logger)
        assert result.duplicate_canonical_ids == ["m-1"]
        assert result.canonical_count == 1

    def test_the_audit_selects_from_memories_and_nothing_else(
        self, tmp_path, logger, fake_pg,
    ) -> None:
        """Kills the mutation hard-coding another table into the query."""
        corpus = _corpus(tmp_path, [_mem("m-1")])
        conn = fake_pg(FakeDatabase(memories=[_mem("m-1")]))
        audit_mod.audit_memories(corpus, logger)
        selects = [s for s in conn.executed_sql if s.startswith("SELECT id")]
        assert selects == ["SELECT id, content, is_active, verified FROM memories"]

    def test_nothing_but_selects_ever_runs(
        self, tmp_path, logger, fake_pg,
    ) -> None:
        """Read-only becomes a property, not a claim (finding ANT2).

        The fake raises on any write verb and on commit(); this asserts the
        weaker, checkable version too — every statement is a SELECT and the
        transaction ends in a rollback.
        """
        corpus = _corpus(tmp_path, [_mem("m-1")])
        conn = fake_pg(FakeDatabase(memories=[_mem("m-1")]))
        audit_mod.audit_memories(corpus, logger)
        assert conn.executed_sql, "the audit issued no SQL at all"
        assert all(s.upper().startswith("SELECT") for s in conn.executed_sql)
        assert conn.rollbacks >= 1 and conn.closed
        assert conn.readonly is True

    def test_a_write_would_be_caught(self, tmp_path, logger, fake_pg) -> None:
        """The net itself: prove the fake fails a caller that writes."""
        conn = fake_pg(FakeDatabase(memories=[]))
        with pytest.raises(WriteAttempted):
            with conn.cursor() as cur:
                cur.execute("DELETE FROM memories WHERE FALSE")
        with pytest.raises(WriteAttempted):
            conn.commit()


class TestAuditSessionsAgainstAFakeConnection:
    """The sessions branch reads its own table."""

    def test_sessions_are_reconciled_against_the_sessions_table(
        self, tmp_path, logger, fake_pg,
    ) -> None:
        """Kills the mutation hard-coding "memories" into _read_postgres_ids."""
        directory = tmp_path / "proj" / "2031-02-02_x"
        directory.mkdir(parents=True)
        (directory / "session.meta.json").write_text(
            json.dumps({"session": {"id": "sess-1"}}), encoding="utf-8",
        )
        conn = fake_pg(FakeDatabase(
            memories=[_mem("m-1")],
            sessions=[{"id": "sess-1"}, {"id": "sess-2"}],
        ))
        result = audit_mod.audit_sessions(tmp_path, logger)
        assert result.only_in_canonical == []
        assert result.only_in_postgres == ["sess-2"]
        # A partial local mirror is expected, so the orphan does not fail.
        assert result.is_clean is True
        assert "SELECT id FROM sessions" in conn.executed_sql


class TestArchiveParityAgainstAFakeConnection:
    """The leak check, its id filter, and its exit-code consequence."""

    def _partition(self, tmp_path: Path, ids: list[str]) -> Path:
        directory = tmp_path / "archive"
        directory.mkdir()
        (directory / "memories-archive-2031-02.jsonl").write_text(
            "".join(json.dumps({"id": i}) + "\n" for i in ids), encoding="utf-8",
        )
        return directory

    def test_an_archived_id_still_active_is_a_leak(
        self, tmp_path, logger, fake_pg,
    ) -> None:
        """Kills the inverted-leak mutation (``is True`` -> ``is not True``)."""
        directory = self._partition(tmp_path, ["a-1", "a-2"])
        fake_pg(FakeDatabase(memories=[
            _mem("a-1", is_active=True), _mem("a-2", is_active=False),
        ]))
        result = audit_mod.audit_archive_parity(directory, logger)
        assert result.leaked_active == ["a-1"]
        assert result.archived_in_pg == 2
        assert result.archived_not_in_pg == 0
        assert result.is_clean is False

    def test_an_archived_id_absent_from_pg_is_benign(
        self, tmp_path, logger, fake_pg,
    ) -> None:
        """The asymmetric semantics, exercised rather than asserted on a stub."""
        directory = self._partition(tmp_path, ["a-1", "a-2"])
        fake_pg(FakeDatabase(memories=[_mem("a-1", is_active=False)]))
        result = audit_mod.audit_archive_parity(directory, logger)
        assert (result.archived_in_pg, result.archived_not_in_pg) == (1, 1)
        assert result.is_clean is True

    def test_the_query_filters_to_the_archived_ids(
        self, tmp_path, logger, fake_pg,
    ) -> None:
        """Kills the mutation dropping ``WHERE id = ANY(%s)``.

        Without the filter every active row in the table looks archived, and
        an ordinary live memory is reported as a recall leak.
        """
        directory = self._partition(tmp_path, ["a-1"])
        conn = fake_pg(FakeDatabase(memories=[
            _mem("a-1", is_active=False), _mem("live-1", is_active=True),
        ]))
        result = audit_mod.audit_archive_parity(directory, logger)
        assert result.leaked_active == []
        sql, params = next(
            (s, p) for s, p in conn.statements if "is_active FROM memories" in s
        )
        assert sql == "SELECT id, is_active FROM memories WHERE id = ANY(%s)"
        assert params == (["a-1"],)


class TestSchemaDriftIsRaisedNotExited:
    """A schema bump must not kill a caller that can still report (AN4)."""

    def test_the_reader_raises_instead_of_exiting(self, logger, fake_pg) -> None:
        """Kills the mutation restoring ``sys.exit(2)`` inside the reader."""
        fake_pg(FakeDatabase(memories=[], schema_version="999"))
        with pytest.raises(audit_mod.SchemaVersionError):
            audit_mod._read_postgres_active_map(["a-1"], logger)

    def test_main_still_exits_2_on_schema_drift(
        self, tmp_path, logger, fake_pg, monkeypatch, capsys,
    ) -> None:
        """The script's own contract is unchanged: exit 2, not a traceback."""
        corpus = _corpus(tmp_path, [_mem("m-1")])
        fake_pg(FakeDatabase(memories=[_mem("m-1")], schema_version="999"))
        monkeypatch.setattr(
            sys, "argv", ["audit-postgres-sync.py", "--memories-file", str(corpus)],
        )
        assert audit_mod.main() == 2


class TestMainExitCodes:
    """main()'s documented exit codes, driven end to end."""

    def _run(self, monkeypatch, corpus: Path, extra: list[str] | None = None):
        monkeypatch.setattr(
            sys, "argv",
            ["audit-postgres-sync.py", "--memories-file", str(corpus)]
            + (extra or []),
        )
        return audit_mod.main()

    def test_clean_stores_exit_zero(
        self, tmp_path, fake_pg, monkeypatch, capsys,
    ) -> None:
        corpus = _corpus(tmp_path, [_mem("m-1")])
        fake_pg(FakeDatabase(memories=[_mem("m-1")]))
        assert self._run(monkeypatch, corpus) == 0
        assert "only in canonical:       0" in capsys.readouterr().out

    def test_a_missing_row_exits_one(
        self, tmp_path, fake_pg, monkeypatch, capsys,
    ) -> None:
        """Kills the mutation returning 0 regardless of is_clean."""
        corpus = _corpus(tmp_path, [_mem("m-1"), _mem("m-2")])
        fake_pg(FakeDatabase(memories=[_mem("m-1")]))
        assert self._run(monkeypatch, corpus) == 1
        assert "missing from PostgreSQL" in capsys.readouterr().out

    def test_a_divergent_row_exits_one(
        self, tmp_path, fake_pg, monkeypatch, capsys,
    ) -> None:
        corpus = _corpus(tmp_path, [_mem("m-1")])
        fake_pg(FakeDatabase(memories=[_mem("m-1", content="edited")]))
        assert self._run(monkeypatch, corpus) == 1
        assert "differ in content" in capsys.readouterr().out

    def test_a_missing_corpus_exits_two(
        self, tmp_path, fake_pg, monkeypatch,
    ) -> None:
        fake_pg(FakeDatabase(memories=[]))
        assert self._run(monkeypatch, tmp_path / "absent.jsonl") == 2

    def test_a_recall_leak_exits_one(
        self, tmp_path, fake_pg, monkeypatch, capsys,
    ) -> None:
        """Kills the mutation dropping archive_clean from the exit decision."""
        corpus = _corpus(tmp_path, [_mem("m-1")])
        directory = tmp_path / "archive"
        directory.mkdir()
        (directory / "memories-archive-2031-02.jsonl").write_text(
            json.dumps({"id": "a-1"}) + "\n", encoding="utf-8",
        )
        fake_pg(FakeDatabase(memories=[
            _mem("m-1"), _mem("a-1", is_active=True),
        ]))
        # a-1 is in PostgreSQL but not the canonical: strict orphans would
        # fail the run anyway, so point the memories audit at both ids.
        corpus = _corpus(tmp_path, [_mem("m-1"), _mem("a-1")])
        rc = self._run(
            monkeypatch, corpus,
            ["--archive-parity", "--archive-dir", str(directory)],
        )
        assert rc == 1
        assert "recall leak" in capsys.readouterr().out
