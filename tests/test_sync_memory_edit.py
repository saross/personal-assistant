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

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import sync_memory_edit as sme  # noqa: E402


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
    def __init__(self, rowcount: int) -> None:
        self.calls: list[tuple] = []
        self.rowcount = rowcount

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql: str, params: tuple) -> None:
        self.calls.append((sql, params))


class _FakeConn:
    def __init__(self, rowcount: int = 1) -> None:
        self.cur = _FakeCursor(rowcount)
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return self.cur

    def close(self) -> None:
        self.closed = True


def test_reconcile_pg_issues_update_and_returns_rowcount() -> None:
    conn = _FakeConn(rowcount=1)
    rec = {"id": "2026-06-05-abc", "content": "x", "is_active": False,
           "anchors": [{"type": "file"}], "revisions": [{"action": "forget"}]}
    n = sme.reconcile_pg(rec, connect=lambda: conn)
    assert n == 1
    assert conn.closed is True
    sql, params = conn.cur.calls[0]
    assert sql == sme.UPDATE_SQL
    # is_active, content, confidence, verified, Json(anchors), Json(revisions), id
    assert params[0] is False
    assert params[1] == "x"
    assert params[6] == "2026-06-05-abc"
    # anchors + revisions are psycopg2 Json wrappers over the original lists.
    assert params[4].adapted == [{"type": "file"}]
    assert params[5].adapted == [{"action": "forget"}]


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
