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

    def test_pg_orphans_still_clean(self) -> None:
        """Orphans in PG (only_in_postgres) do not fail the audit."""
        result = audit_mod.AuditResult(
            source_name="memories",
            canonical_count=9,
            postgres_count=10,
            only_in_canonical=[],
            only_in_postgres=["orphan"],
        )
        assert result.is_clean is True
