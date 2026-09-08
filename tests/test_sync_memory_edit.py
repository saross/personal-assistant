"""
Tests for scripts/sync_memory_edit.py — the P8 surgical PG-reconcile helper
that propagates a /forget or /update edit to PostgreSQL.

Covers find_record, the pure extract_values defaults, reconcile_pg's UPDATE
(via an injected fake connection — no live DB), and main()'s exit codes
(reconciled / not-yet-in-PG / id-not-found / PG-unavailable).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import _schema_version  # noqa: E402
import sync_memory_edit as sme  # noqa: E402

#: Read from the module the guard lives in, so a schema bump cannot quietly
#: turn the fake connection's answer into a permanent mismatch.
SCHEMA_VERSION = _schema_version.EXPECTED_SCHEMA_VERSION


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )


# ============================================================================
# find_record
# ============================================================================


def test_find_record_hit(tmp_path: Path) -> None:
    p = tmp_path / "memories.jsonl"
    _write_jsonl(p, [{"id": "a", "content": "x"}, {"id": "b", "content": "y"}])
    rec = sme.find_record("b", memories_path=p)
    assert rec is not None and rec["content"] == "y"


def test_find_record_miss(tmp_path: Path) -> None:
    p = tmp_path / "memories.jsonl"
    _write_jsonl(p, [{"id": "a", "content": "x"}])
    assert sme.find_record("zzz", memories_path=p) is None


def test_find_record_skips_malformed(tmp_path: Path) -> None:
    p = tmp_path / "memories.jsonl"
    p.write_text(
        'not json\n{"id": "a", "content": "x"}\n\n', encoding="utf-8"
    )
    assert sme.find_record("a", memories_path=p)["content"] == "x"


def test_find_record_missing_file(tmp_path: Path) -> None:
    assert sme.find_record("a", memories_path=tmp_path / "nope.jsonl") is None


# ============================================================================
# extract_values — defaults mirror the PG column defaults
# ============================================================================


def test_extract_values_defaults() -> None:
    vals = sme.extract_values({"id": "a", "content": "hello"})
    assert vals == {
        "is_active": True,
        "content": "hello",
        "confidence": "medium",
        "verified": None,
        "anchors": [],
        "revisions": [],
    }


def test_extract_values_forget() -> None:
    """A /forget'd record carries is_active False + a revisions entry."""
    rec = {"id": "a", "content": "x", "is_active": False,
           "revisions": [{"action": "forget"}]}
    vals = sme.extract_values(rec)
    assert vals["is_active"] is False
    assert vals["revisions"] == [{"action": "forget"}]


def test_extract_values_update_clears_verification() -> None:
    """An /update resets verified->None and anchors->[]; mirror that."""
    rec = {"id": "a", "content": "new", "verified": None, "anchors": [],
           "confidence": "low"}
    vals = sme.extract_values(rec)
    assert vals["content"] == "new"
    assert vals["verified"] is None
    assert vals["anchors"] == []
    assert vals["confidence"] == "low"


def test_extract_values_non_list_anchors_coerced() -> None:
    """A malformed non-list anchors/revisions degrades to []."""
    vals = sme.extract_values({"id": "a", "content": "x", "anchors": "oops"})
    assert vals["anchors"] == []


# ============================================================================
# reconcile_pg — via an injected fake connection (no live DB)
# ============================================================================


class _FakeCursor:
    """Records the SQL text and parameters it was actually handed.

    ``execute`` takes ``params`` optionally so the schema-version guard's
    parameterless ``SELECT`` runs against it too, and ``fetchone`` answers
    that guard with the version the code expects.
    """

    def __init__(self, rowcount: int) -> None:
        self.calls: list[tuple] = []
        self.rowcount = rowcount

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self.calls.append((sql, params))

    def fetchone(self):
        return (SCHEMA_VERSION,)


class _FakeConn:
    def __init__(self, rowcount: int = 1) -> None:
        self.cur = _FakeCursor(rowcount)
        self.closed = False
        self.entered = 0

    def __enter__(self):
        self.entered += 1
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return self.cur

    def close(self) -> None:
        self.closed = True


def _update_call(conn: _FakeConn) -> tuple:
    """The single UPDATE the reconcile issued (not the schema-guard SELECT)."""
    updates = [c for c in conn.cur.calls if c[0].lstrip().startswith("UPDATE")]
    assert len(updates) == 1, f"expected one UPDATE, got {conn.cur.calls}"
    return updates[0]


def test_reconcile_pg_issues_update_and_returns_rowcount() -> None:
    """The literal SQL, its parameter order, and the committing context.

    Kills, together: ``WHERE id=%s`` -> ``WHERE id!=%s`` (which would blank
    every OTHER row), a swapped parameter order, and dropping ``conn`` from
    the ``with`` (the UPDATE would be discarded on close while the command
    still printed "PostgreSQL reconciled").
    """
    conn = _FakeConn(rowcount=1)
    rec = {"id": "2026-06-05-abc", "content": "x", "is_active": False,
           "anchors": [{"type": "file"}], "revisions": [{"action": "forget"}]}
    n = sme.reconcile_pg(rec, connect=lambda: conn)
    assert n == 1
    assert conn.closed is True
    assert conn.entered == 1, "the UPDATE must run inside `with conn`"

    sql, params = _update_call(conn)
    # Asserted against the literal text, not against the module constant:
    # comparing the constant with itself let WHERE id!=%s stay green.
    assert sql == (
        "UPDATE memories SET is_active=%s, content=%s, confidence=%s, "
        "verified=%s, anchors=%s, revisions=%s, "
        "embedding = CASE WHEN content IS DISTINCT FROM %s THEN NULL "
        "ELSE embedding END "
        "WHERE id=%s"
    )
    # is_active, content, confidence, verified, Json(anchors),
    # Json(revisions), content again (the embedding comparison), id
    assert params[0] is False
    assert params[1] == "x"
    assert params[2] == "medium"
    assert params[3] is None
    assert params[6] == "x"
    assert params[7] == "2026-06-05-abc"
    # anchors + revisions are psycopg2 Json wrappers over the original lists.
    assert params[4].adapted == [{"type": "file"}]
    assert params[5].adapted == [{"action": "forget"}]


def test_reconcile_pg_clears_the_embedding_when_content_changes() -> None:
    """The embedding is invalidated by comparing old content with new.

    Kills the mutation that drops the ``embedding = CASE ...`` clause: the
    refill paths select ``WHERE embedding IS NULL``, so without it semantic
    recall keeps matching the pre-edit wording forever. The comparison
    parameter must be the NEW content, so an unchanged record keeps its
    embedding.
    """
    conn = _FakeConn(rowcount=1)
    sme.reconcile_pg({"id": "a", "content": "revised wording"},
                     connect=lambda: conn)
    sql, params = _update_call(conn)
    assert "embedding = CASE WHEN content IS DISTINCT FROM %s" in sql
    assert "THEN NULL" in sql
    assert params[6] == "revised wording"


def test_reconcile_pg_checks_the_schema_version() -> None:
    """A pre-v2 mirror is caught before the UPDATE, not after.

    Kills the mutation that deletes the ``assert_schema_version`` call.
    """
    conn = _FakeConn(rowcount=1)
    sme.reconcile_pg({"id": "a", "content": "x"}, connect=lambda: conn)
    assert any(
        "schema_version" in sql for sql, _params in conn.cur.calls
    ), "the schema-version guard did not run"


def test_reconcile_pg_refuses_on_a_schema_mismatch() -> None:
    """A wrong version raises rather than issuing the UPDATE."""

    class _StaleCursor(_FakeCursor):
        def fetchone(self):
            return ("0",)

    class _StaleConn(_FakeConn):
        def __init__(self) -> None:
            super().__init__()
            self.cur = _StaleCursor(1)

    conn = _StaleConn()
    with pytest.raises(_schema_version.SchemaVersionError):
        sme.reconcile_pg({"id": "a", "content": "x"}, connect=lambda: conn)
    assert not [c for c in conn.cur.calls
                if c[0].lstrip().startswith("UPDATE")]
    assert conn.closed is True


def test_reconcile_pg_rowcount_zero_when_absent() -> None:
    conn = _FakeConn(rowcount=0)
    n = sme.reconcile_pg({"id": "ghost", "content": "x"}, connect=lambda: conn)
    assert n == 0


# ============================================================================
# main — exit codes
# ============================================================================


def test_main_id_not_found(tmp_path: Path) -> None:
    p = tmp_path / "memories.jsonl"
    _write_jsonl(p, [{"id": "a", "content": "x"}])
    rc = sme.main(["--id", "missing", "--memories", str(p)])
    assert rc == sme.EXIT_NOT_FOUND


def test_main_reconciled(tmp_path: Path, monkeypatch) -> None:
    p = tmp_path / "memories.jsonl"
    _write_jsonl(p, [{"id": "a", "content": "x", "is_active": False}])
    monkeypatch.setattr(sme, "reconcile_pg", lambda rec, **kw: 1)
    rc = sme.main(["--id", "a", "--memories", str(p)])
    assert rc == sme.EXIT_OK


def test_main_not_yet_in_pg(tmp_path: Path, monkeypatch) -> None:
    p = tmp_path / "memories.jsonl"
    _write_jsonl(p, [{"id": "a", "content": "x"}])
    monkeypatch.setattr(sme, "reconcile_pg", lambda rec, **kw: 0)
    rc = sme.main(["--id", "a", "--memories", str(p)])
    assert rc == sme.EXIT_OK  # benign — sync will insert it


def test_main_pg_unavailable(tmp_path: Path, monkeypatch) -> None:
    p = tmp_path / "memories.jsonl"
    _write_jsonl(p, [{"id": "a", "content": "x"}])

    def _boom(rec, **kw):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(sme, "reconcile_pg", _boom)
    rc = sme.main(["--id", "a", "--memories", str(p)])
    assert rc == sme.EXIT_PG_UNAVAILABLE


def test_main_operational_error_labelled_unreachable(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A connection-level failure keeps the 'PostgreSQL unreachable' label."""
    import psycopg2

    p = tmp_path / "memories.jsonl"
    _write_jsonl(p, [{"id": "a", "content": "x"}])

    def _boom(rec, **kw):
        raise psycopg2.OperationalError("connection refused")

    monkeypatch.setattr(sme, "reconcile_pg", _boom)
    rc = sme.main(["--id", "a", "--memories", str(p)])
    assert rc == sme.EXIT_PG_UNAVAILABLE
    assert "unreachable" in capsys.readouterr().err


def test_main_query_error_not_labelled_unreachable(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A query-level failure (e.g. schema mismatch) must NOT claim
    'unreachable' — that mislabel sent the 2026-07-04 zbook diagnosis down
    the wrong path. It points at schema.sql + rebuild instead."""
    p = tmp_path / "memories.jsonl"
    _write_jsonl(p, [{"id": "a", "content": "x"}])

    def _boom(rec, **kw):
        raise RuntimeError('column "verified" does not exist')

    monkeypatch.setattr(sme, "reconcile_pg", _boom)
    rc = sme.main(["--id", "a", "--memories", str(p)])
    assert rc == sme.EXIT_PG_UNAVAILABLE
    err = capsys.readouterr().err
    assert "unreachable" not in err
    assert "query failed" in err
    assert "schema" in err


def test_main_malformed_record_no_content(tmp_path: Path) -> None:
    """A record present in JSONL but missing 'content' errors clearly (not PG-unavailable)."""
    p = tmp_path / "memories.jsonl"
    _write_jsonl(p, [{"id": "a"}])  # no 'content' key
    rc = sme.main(["--id", "a", "--memories", str(p)])
    assert rc == sme.EXIT_NOT_FOUND
