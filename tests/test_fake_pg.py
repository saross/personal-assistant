"""
Self-tests for ``tests/_fake_pg.py`` — the harness the retrieval tests trust.

A fake database is only worth having if a wrong answer from it fails a
test. Two audit findings came from it answering confidently instead:

* **L-1** — the ``COUNT(*) FILTER`` branch hard-coded ``active_memories``,
  so ``fetch-memories``' coverage query could be mutated to count over the
  base table and the test whose docstring claimed to kill that still
  passed. Reverting the derivation must now fail something.
* **L-7** — the fake silently mis-answered three shapes. A ``DELETE`` was
  parsed as though ``DELETE`` were the select list and answered
  ``[(None,)]`` — a write that looked like a successful read. An unknown
  column came back as ``None`` for every row. A ``GROUP BY`` tail was
  ignored, so the fake returned ungrouped rows as though they were groups.

These tests pin the harness's own contract, so a future simplification of
it cannot quietly re-weaken every test that depends on it.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fake_pg import (  # noqa: E402
    CannedDB, FakeMemoryDB, UnsupportedSQL, connect_factory,
)

_COLUMNS = "id, category, content, created_at"


def _rows() -> list[dict[str, Any]]:
    """Two active rows, one forgotten, one decayed, one un-embedded."""
    return [
        {"id": "live-a", "category": "decision", "content": "alpha",
         "created_at": "2026-03-01T00:00:00+00:00", "embedding": [1.0, 0.0]},
        {"id": "live-b", "category": "decision", "content": "beta",
         "created_at": "2026-03-02T00:00:00+00:00", "embedding": None},
        {"id": "forgotten", "category": "decision", "content": "gamma",
         "created_at": "2026-03-03T00:00:00+00:00", "embedding": None,
         "is_active": False},
        {"id": "decayed", "category": "decision", "content": "delta",
         "created_at": "2026-03-04T00:00:00+00:00", "embedding": None,
         "decayed": True},
    ]


class TestCountBranchDerivesItsTable:
    """Audit L-1: the COUNT(*) FILTER shape must honour the table named."""

    def test_view_and_base_table_give_different_answers(self) -> None:
        """Kills: hard-coding ``active_memories`` in the COUNT branch.

        Without this, a production query mutated to count over the base
        table is answered from the view anyway, and the mutation passes.
        """
        db = FakeMemoryDB(_rows())
        view_rows, _ = db.run(
            "SELECT COUNT(*) FILTER (WHERE embedding IS NULL), "
            "COUNT(*) FROM active_memories", [],
        )
        base_rows, _ = db.run(
            "SELECT COUNT(*) FILTER (WHERE embedding IS NULL), "
            "COUNT(*) FROM memories", [],
        )
        # The view drops the forgotten and the decayed row; the base table
        # keeps them, and both are un-embedded.
        assert view_rows == [(1, 2)]
        assert base_rows == [(3, 4)]
        assert view_rows != base_rows, "the two tables must be distinguishable"


class TestRefusesWhatItCannotEmulate:
    """Audit L-7: silence is the failure mode that matters."""

    @pytest.mark.parametrize("sql", [
        "DELETE FROM memories",
        "DELETE FROM memories WHERE id = %s",
        "INSERT INTO memories (id) VALUES (%s)",
        "UPDATE memories SET is_active = %s WHERE id = %s",
        "TRUNCATE memories",
        "DROP TABLE memories",
    ])
    def test_writes_are_refused_never_answered(self, sql: str) -> None:
        """Kills: parsing a write as a read.

        ``DELETE FROM memories`` used to partition on " FROM " and treat
        ``DELETE`` as the select list, returning ``[(None,)]``. A mutation
        that turned a read path into a destructive write would have looked
        like a passing test.
        """
        db = FakeMemoryDB(_rows())
        with pytest.raises(UnsupportedSQL, match="read-only|not a SELECT"):
            db.run(sql, [])

    def test_the_refusal_is_an_assertion_error(self) -> None:
        """So an unexpected shape reads as a harness defect. A production
        ``except Exception`` still catches it; the tests stay honest by
        asserting on returned rows, which a swallowed raise cannot supply."""
        assert issubclass(UnsupportedSQL, AssertionError)

    @pytest.mark.parametrize("clause", [
        "GROUP BY category", "HAVING COUNT(*) > 1", "OFFSET 10",
    ])
    def test_ignored_clauses_are_refused(self, clause: str) -> None:
        """Kills: parsing on and ignoring the tail.

        An ignored GROUP BY returns ungrouped rows as though they were
        groups — wrong rows, confidently.
        """
        db = FakeMemoryDB(_rows())
        with pytest.raises(UnsupportedSQL):
            db.run(f"SELECT {_COLUMNS} FROM active_memories {clause}", [])

    def test_unknown_select_column_is_refused(self) -> None:
        """Kills: ``row.get(col)`` answering None for a column that is not
        there — a typo, or a real new column, read as "the value is null"."""
        db = FakeMemoryDB(_rows())
        with pytest.raises(UnsupportedSQL, match="unknown column"):
            db.run("SELECT id, nonexistent_column FROM active_memories", [])

    def test_unknown_table_is_refused(self) -> None:
        db = FakeMemoryDB(_rows())
        with pytest.raises(AssertionError, match="unknown table"):
            db.run(f"SELECT {_COLUMNS} FROM sessions", [])

    def test_unknown_where_condition_is_refused(self) -> None:
        """A new filter must be implemented, not silently dropped."""
        db = FakeMemoryDB(_rows())
        with pytest.raises(AssertionError, match="unhandled condition"):
            db.run(
                f"SELECT {_COLUMNS} FROM active_memories WHERE licence = %s",
                ["CC-BY"],
            )

    def test_unknown_order_by_is_refused(self) -> None:
        db = FakeMemoryDB(_rows())
        with pytest.raises(AssertionError, match="unhandled ORDER BY"):
            db.run(f"SELECT {_COLUMNS} FROM active_memories ORDER BY id DESC", [])


class TestSupportedShapesStillWork:
    """The guards must not reject the queries the suite actually runs."""

    def test_view_filters_forgotten_and_decayed(self) -> None:
        db = FakeMemoryDB(_rows())
        rows, _ = db.run(f"SELECT {_COLUMNS} FROM active_memories", [])
        assert {r[0] for r in rows} == {"live-a", "live-b"}

    def test_base_table_keeps_everything(self) -> None:
        db = FakeMemoryDB(_rows())
        rows, _ = db.run(f"SELECT {_COLUMNS} FROM memories", [])
        assert len(rows) == 4

    def test_schema_version_probe_is_answered(self) -> None:
        db = FakeMemoryDB([], schema_version="7")
        rows, _ = db.run(
            "SELECT value FROM meta WHERE key = 'schema_version'", [],
        )
        assert rows == [("7",)]

    def test_where_order_and_limit_compose(self) -> None:
        db = FakeMemoryDB(_rows())
        rows, _ = db.run(
            f"SELECT {_COLUMNS} FROM active_memories WHERE TRUE "
            "AND category = %s ORDER BY created_at DESC LIMIT %s",
            ["decision", 1],
        )
        assert [r[0] for r in rows] == ["live-b"]

    def test_every_call_is_recorded(self) -> None:
        """Tests assert on the statement as well as the rows."""
        db = FakeMemoryDB(_rows())
        db.run(f"SELECT {_COLUMNS} FROM active_memories", [])
        assert len(db.calls) == 1
        assert db.calls[0][0].startswith("SELECT")


class TestCannedDB:
    """The recording engine used where the SQL text is the thing tested."""

    def test_replays_rows_and_records_calls(self) -> None:
        db = CannedDB([("a", 1)], [("col_a",), ("col_b",)])
        rows, description = db.run("SELECT anything AT ALL", ["p"])
        assert rows == [("a", 1)]
        assert description == [("col_a",), ("col_b",)]
        assert db.calls == [("SELECT anything AT ALL", ["p"])]


class TestConnectRecorder:
    """Connection kwargs are asserted on by the timeout tests."""

    def test_records_kwargs_and_hands_out_closable_connections(self) -> None:
        connect = connect_factory(FakeMemoryDB(_rows()))
        conn = connect(dbname="claude_memories", connect_timeout=5)
        assert connect.calls == [{"dbname": "claude_memories", "connect_timeout": 5}]
        assert conn.closed is False
        conn.close()
        assert connect.connections[0].closed is True


class TestOrderByWithoutWhere:
    """Audit L-7: the clauses are peeled off the FROM tail, in SQL order.

    ORDER BY used to be looked for inside the WHERE text, so a statement
    with an ORDER BY and no WHERE came back unsorted — the harness
    answering rather than refusing, again. No production query has that
    shape today, which is exactly why it went unnoticed.
    """

    def test_order_by_applies_without_a_where_clause(self) -> None:
        db = FakeMemoryDB(_rows())
        rows, _ = db.run(
            f"SELECT {_COLUMNS} FROM active_memories "
            "ORDER BY created_at DESC", [],
        )
        assert [r[0] for r in rows] == ["live-b", "live-a"]

    def test_order_by_and_limit_without_a_where_clause(self) -> None:
        db = FakeMemoryDB(_rows())
        rows, _ = db.run(
            f"SELECT {_COLUMNS} FROM active_memories "
            "ORDER BY created_at ASC LIMIT %s", [1],
        )
        assert [r[0] for r in rows] == ["live-a"]

    def test_limit_without_where_or_order_by(self) -> None:
        db = FakeMemoryDB(_rows())
        rows, _ = db.run(f"SELECT {_COLUMNS} FROM memories LIMIT %s", [2])
        assert len(rows) == 2
