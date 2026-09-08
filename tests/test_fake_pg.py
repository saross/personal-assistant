"""
Self-tests for ``tests/_fake_pg.py`` — the harness the retrieval tests trust.

A fake database is only worth having if a wrong answer from it fails a
test, and the harness itself had no tests at all.

Audit L-1: the ``COUNT(*) FILTER`` branch hard-coded ``active_memories``,
so ``fetch-memories``' coverage query could be mutated to count over the
base table and the test whose docstring claimed to kill that still passed.
Round 4b-2 fixed the derivation but nothing pinned it — reverting it left
the whole suite green. It must now fail something.

These tests pin the harness's own contract, so a future simplification of
it cannot quietly re-weaken every test that depends on it.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fake_pg import CannedDB, FakeMemoryDB, connect_factory  # noqa: E402

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
