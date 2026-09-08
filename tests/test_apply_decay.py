"""
Tests for apply-decay.py — decay logic, category handling, and edge cases.

Tests use an in-memory mock of the database cursor to verify SQL logic
without requiring a running PostgreSQL instance. Integration tests that
hit a real database are marked with @pytest.mark.integration.
"""

import importlib
import importlib.util
import logging
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Import the decay module (hyphenated filename requires importlib)
_decay_path = Path(__file__).parent.parent / "scripts" / "apply-decay.py"
_spec = importlib.util.spec_from_file_location("apply_decay", _decay_path)
decay_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(decay_mod)

# archive-memories.py is hyphenated; load it under an importable alias so the
# PERMANENT_OVERRIDES cross-check below can compare the two lists.
_archive_path = Path(__file__).parent.parent / "scripts" / "archive-memories.py"
_archive_spec = importlib.util.spec_from_file_location(
    "archive_memories_for_overrides", _archive_path
)
_archive_mod = importlib.util.module_from_spec(_archive_spec)
_archive_spec.loader.exec_module(_archive_mod)
sys.modules["archive_memories_for_overrides"] = _archive_mod


# ============================================================================
# Shared fixtures
# ============================================================================


@pytest.fixture()
def mock_db():
    """Create mock psycopg2 connection and cursor with context manager support.

    The cursor's ``fetchone`` returns ``("1",)`` when the most recent
    SQL contained ``meta`` (the schema-version assertion added under
    audit IC5) and ``None`` otherwise. Tests that need a different
    fetchone shape can override on the returned ``mock_cur``.
    """
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_cur.__enter__ = MagicMock(return_value=mock_cur)
    mock_cur.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value = mock_cur
    mock_cur.fetchall.return_value = []

    last_sql = {"value": ""}

    def _exec(sql, *args, **kwargs):
        last_sql["value"] = sql
        return None

    def _fetchone():
        if "meta" in last_sql["value"]:
            return ("3",)
        return None

    mock_cur.execute.side_effect = _exec
    mock_cur.fetchone.side_effect = _fetchone
    return mock_conn, mock_cur


# ============================================================================
# Logging setup
# ============================================================================


class TestSetupLogging:
    """Verify logging configuration."""

    @pytest.fixture(autouse=True)
    def _clean_logger(self):
        """Remove handlers added by setup_logging() after each test."""
        yield
        logger = logging.getLogger("apply-decay")
        logger.handlers.clear()

    def test_returns_logger(self, tmp_path, monkeypatch):
        """setup_logging should return a Logger instance."""
        monkeypatch.setattr(decay_mod, "LOG_DIR", tmp_path)
        monkeypatch.setattr(decay_mod, "LOG_FILE", tmp_path / "test-decay.log")
        logger = decay_mod.setup_logging()
        assert isinstance(logger, logging.Logger)
        assert logger.name == "apply-decay"

    def test_creates_log_directory(self, tmp_path, monkeypatch):
        """Log directory should be created if it doesn't exist."""
        log_dir = tmp_path / "nested" / "logs"
        monkeypatch.setattr(decay_mod, "LOG_DIR", log_dir)
        monkeypatch.setattr(decay_mod, "LOG_FILE", log_dir / "decay.log")
        decay_mod.setup_logging()
        assert log_dir.exists()

    def test_log_file_created(self, tmp_path, monkeypatch):
        """Log file should be created after setup."""
        monkeypatch.setattr(decay_mod, "LOG_DIR", tmp_path)
        log_file = tmp_path / "test-decay.log"
        monkeypatch.setattr(decay_mod, "LOG_FILE", log_file)
        logger = decay_mod.setup_logging()
        logger.info("test message")
        for handler in logger.handlers:
            handler.flush()
        assert log_file.exists()


# ============================================================================
# Decay logic — SQL construction and execution
# ============================================================================


class TestApplyDecayDryRun:
    """Dry run should query but not update."""

    def test_dry_run_executes_select_not_update(self, mock_db):
        """Dry run should run preview SQL (SELECT), not decay SQL (UPDATE).

        Note: under audit IC5 the schema-version assertion runs a
        ``SELECT … FROM meta`` first; we filter that out and assert on
        the substantive decay query only.
        """
        mock_conn, mock_cur = mock_db
        logger = logging.getLogger("test-dry-run")

        with patch("psycopg2.connect", return_value=mock_conn):
            decay_mod.apply_decay(logger, dry_run=True)

        decay_calls = [
            c for c in mock_cur.execute.call_args_list
            if not ("meta" in c.args[0] and "schema_version" in c.args[0])
        ]
        assert len(decay_calls) == 1
        executed_sql = decay_calls[0].args[0]
        assert "SELECT" in executed_sql
        assert "UPDATE" not in executed_sql

    def test_dry_run_reports_count(self, mock_db):
        """Dry run should log the count of memories that would decay."""
        mock_conn, mock_cur = mock_db
        mock_cur.fetchall.return_value = [
            ("id-1", "progress", "some progress...", datetime.now(), None),
            ("id-2", "context", "some context...", datetime.now(), None),
        ]

        logger = MagicMock()

        with patch("psycopg2.connect", return_value=mock_conn):
            decay_mod.apply_decay(logger, dry_run=True)

        logger.info.assert_any_call(
            "[DRY RUN] Would decay %d memories:", 2
        )


class TestApplyDecayReal:
    """Real execution should UPDATE memories."""

    def test_real_run_executes_update(self, mock_db):
        """Real run should execute UPDATE SQL.

        Note: under audit IC5 the schema-version assertion runs a
        ``SELECT … FROM meta`` first; we filter that out and assert on
        the substantive decay query only.
        """
        mock_conn, mock_cur = mock_db
        logger = logging.getLogger("test-real-run")

        with patch("psycopg2.connect", return_value=mock_conn):
            decay_mod.apply_decay(logger, dry_run=False)

        decay_calls = [
            c for c in mock_cur.execute.call_args_list
            if not ("meta" in c.args[0] and "schema_version" in c.args[0])
        ]
        assert len(decay_calls) == 1
        executed_sql = decay_calls[0].args[0]
        assert "UPDATE" in executed_sql
        assert "is_active = FALSE" in executed_sql
        assert "decayed_at = NOW()" in executed_sql

    def test_real_run_logs_decayed_memories(self, mock_db):
        """Real run should log details of decayed memories."""
        mock_conn, mock_cur = mock_db
        mock_cur.fetchall.return_value = [
            ("id-1", "progress", "milestone reached", datetime.now(), None),
        ]

        logger = MagicMock()

        with patch("psycopg2.connect", return_value=mock_conn):
            decay_mod.apply_decay(logger, dry_run=False)

        logger.info.assert_any_call("Decayed %d memories:", 1)


# ============================================================================
# Error handling
# ============================================================================


class TestApplyDecayErrors:
    """Error conditions should be handled gracefully."""

    def test_missing_psycopg2(self):
        """Should log error if psycopg2 is not importable."""
        import sys
        logger = MagicMock()

        # Temporarily hide psycopg2 from the import system
        real_module = sys.modules.get("psycopg2")
        sys.modules["psycopg2"] = None  # type: ignore[assignment]
        try:
            # Re-execute apply_decay so it hits the local import
            decay_mod.apply_decay(logger)
        finally:
            if real_module is not None:
                sys.modules["psycopg2"] = real_module
            else:
                sys.modules.pop("psycopg2", None)

        logger.error.assert_called()

    def test_connection_failure(self):
        """Should log warning if database is unreachable."""
        import psycopg2
        logger = MagicMock()

        with patch("psycopg2.connect", side_effect=psycopg2.OperationalError("refused")):
            decay_mod.apply_decay(logger)

        logger.warning.assert_called()
        warning_msg = logger.warning.call_args[0][0]
        assert "Cannot connect" in warning_msg

    def test_query_error(self, mock_db):
        """Should log error if SQL execution fails.

        The schema-version assertion (audit IC5) issues a query first;
        this test forces that one to succeed and the subsequent decay
        query to raise — the decay error path is what we are pinning.
        """
        mock_conn, mock_cur = mock_db

        # Override the mock's execute to handle two distinct cases:
        # (1) the schema-version SELECT returns ``("1",)`` via fetchone,
        # (2) the decay query raises ``Exception("syntax error")``.
        last_sql = {"value": ""}

        def _exec(sql, *args, **kwargs):
            last_sql["value"] = sql
            if "meta" in sql and "schema_version" in sql:
                return None
            raise Exception("syntax error")

        def _fetchone():
            if "meta" in last_sql["value"]:
                return ("3",)
            return None

        mock_cur.execute.side_effect = _exec
        mock_cur.fetchone.side_effect = _fetchone

        logger = MagicMock()

        with patch("psycopg2.connect", return_value=mock_conn):
            decay_mod.apply_decay(logger, dry_run=False)

        logger.error.assert_called()


# ============================================================================
# SQL correctness — verify the WHERE clause handles both paths
# ============================================================================


class TestDecaySQL:
    """Verify the decay SQL covers the expected cases."""

    @staticmethod
    def _get_executed_sql(dry_run: bool) -> str:
        """Helper: run apply_decay with mocks and return the decay SQL.

        The schema-version assertion (audit IC5) issues a ``SELECT
        value FROM meta`` before the decay query — this helper filters
        it out and returns the substantive decay SQL only.
        """
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cur
        mock_cur.fetchall.return_value = []

        last_sql = {"value": ""}

        def _exec(sql, *args, **kwargs):
            last_sql["value"] = sql
            return None

        def _fetchone():
            if "meta" in last_sql["value"]:
                return ("3",)
            return None

        mock_cur.execute.side_effect = _exec
        mock_cur.fetchone.side_effect = _fetchone

        logger = logging.getLogger("test-sql")

        with patch("psycopg2.connect", return_value=mock_conn):
            decay_mod.apply_decay(logger, dry_run=dry_run)

        # Find the first decay SQL — skip the schema-version SELECT.
        for call in mock_cur.execute.call_args_list:
            sql = call.args[0]
            if "meta" in sql and "schema_version" in sql:
                continue
            return sql
        raise AssertionError(
            "No decay SQL was executed — only schema-version checks ran."
        )

    def test_standard_decay_uses_created_at(self):
        """Non-commitment categories should decay based on created_at."""
        sql = self._get_executed_sql(dry_run=False)
        assert "m.category != 'commitment'" in sql
        assert "m.created_at < NOW()" in sql

    def test_commitment_decay_uses_deadline_at(self):
        """Commitment category should decay based on deadline_at with fallback."""
        sql = self._get_executed_sql(dry_run=False)
        assert "m.category = 'commitment'" in sql
        assert "COALESCE(m.deadline_at, m.created_at)" in sql

    def test_only_active_memories_targeted(self):
        """Decay should only target currently active memories."""
        sql = self._get_executed_sql(dry_run=False)
        assert "m.is_active = TRUE" in sql

    def test_only_configured_categories_targeted(self):
        """Decay should only target categories with non-NULL decay_days."""
        sql = self._get_executed_sql(dry_run=False)
        assert "c.decay_days IS NOT NULL" in sql

    def test_dry_run_and_real_share_where_clause(self):
        """Dry run and real run should use the same WHERE logic."""
        dry_sql = self._get_executed_sql(dry_run=True)
        real_sql = self._get_executed_sql(dry_run=False)

        # Extract the WHERE clause content (after WHERE keyword)
        # Both should contain the same decay_where conditions
        for condition in [
            "m.is_active = TRUE",
            "c.decay_days IS NOT NULL",
            "m.category != 'commitment'",
            "COALESCE(m.deadline_at, m.created_at)",
        ]:
            assert condition in dry_sql, f"Missing in dry run SQL: {condition}"
            assert condition in real_sql, f"Missing in real run SQL: {condition}"


# ============================================================================
# Integration tests (require running PostgreSQL)
# ============================================================================


@pytest.mark.integration
class TestApplyDecayIntegration:
    """
    Integration tests that hit the real PostgreSQL database.

    Run with: pytest -m integration tests/test_apply_decay.py
    Skip by default in CI.
    """

    def test_idempotent_run(self):
        """Running decay twice should not fail or change already-decayed memories."""
        logger = logging.getLogger("test-integration")
        logger.setLevel(logging.INFO)

        # First run
        decay_mod.apply_decay(logger, dry_run=False)

        # Second run should succeed with 0 decayed
        decay_mod.apply_decay(logger, dry_run=False)

    def test_dry_run_does_not_modify(self):
        """Dry run should not change any is_active flags."""
        import psycopg2
        conn = psycopg2.connect(dbname=decay_mod.DB_NAME)
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM memories WHERE is_active = TRUE")
        before = cur.fetchone()[0]

        logger = logging.getLogger("test-integration-dry")
        decay_mod.apply_decay(logger, dry_run=True)

        cur.execute("SELECT COUNT(*) FROM memories WHERE is_active = TRUE")
        after = cur.fetchone()[0]

        assert before == after

        cur.close()
        conn.close()


# ============================================================================
# The decay predicate, executed rather than pattern-matched
#
# Audit 2026-09-08, round 4a, findings A18 and B7. The predicate was asserted
# by substring, so NOW() - interval -> NOW() + interval, < -> >, and
# AND m.is_active -> OR all stayed green. The production ``decay_where`` text
# is translated into SQLite here and RUN against fixture rows, so a mutation
# is caught by the rows it selects, not by the characters it contains.
# ============================================================================

import re  # noqa: E402
import sqlite3  # noqa: E402
from datetime import timedelta, timezone  # noqa: E402

#: The instant every fixture row is aged against.
_AS_OF = datetime(2031, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _days_before(days: int) -> str:
    """An ISO timestamp ``days`` before the pinned reference instant."""
    return (_AS_OF - timedelta(days=days)).isoformat()


def _capture_decay_where() -> str:
    """Run apply_decay against a recording cursor and return the SQL it built.

    Taking the predicate from the SQL the script actually executes (rather
    than re-typing it here) is what makes this a test of production code.
    """
    executed: list[str] = []

    class _Cur:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            executed.append(sql)

        def fetchone(self):
            return ("3",)

        def fetchall(self):
            return []

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def cursor(self):
            return _Cur()

        def close(self):
            return None

    logger = logging.getLogger("apply-decay-sql-capture")
    with patch("psycopg2.connect", return_value=_Conn()):
        decay_mod.apply_decay(logger, dry_run=True)

    preview = next(sql for sql in executed if "content_preview" in sql)
    return preview.split("JOIN category_config c ON", 1)[1]


def _to_sqlite(where: str) -> str:
    """Translate the PostgreSQL predicate into an equivalent SQLite one.

    Only the dialect is rewritten — the interval arithmetic, the timestamp
    coercion, the boolean literal, and the array membership. Every operator
    and connective the test is about is left exactly as production wrote it,
    so a mutation to one changes which rows come back.
    """
    sql = " ".join(
        line.split("--", 1)[0] for line in where.splitlines()
    )
    sql = " ".join(sql.split())
    sql = sql.replace("(c.decay_days || ' days')::INTERVAL", "c.decay_days")
    sql = sql.replace("NOW()", "julianday(:now)")
    sql = sql.replace(
        "COALESCE(m.deadline_at, m.created_at)",
        "julianday(COALESCE(m.deadline_at, m.created_at))",
    )
    sql = re.sub(r"m\.created_at\s*([<>]=?)", r"julianday(m.created_at) \1", sql)
    sql = sql.replace("m.is_active = TRUE", "m.is_active = 1")
    permanent = ", ".join(
        f"'{category}'" for category in decay_mod.PERMANENT_OVERRIDES
    )
    sql = sql.replace("m.category <> ALL(%s)", f"m.category NOT IN ({permanent})")
    assert "%s" not in sql, f"an untranslated parameter remains: {sql}"
    return sql


#: (id, category, created days ago, deadline days ago or None, is_active)
_FIXTURE_ROWS = [
    ("old-progress", "progress", 400, None, 1),
    ("fresh-progress", "progress", 5, None, 1),
    ("old-but-inactive", "progress", 400, None, 0),
    ("overdue-commitment", "commitment", 400, 400, 1),
    ("future-commitment", "commitment", 400, -10, 1),
    ("legacy-gotcha", "gotcha", 400, None, 1),
    ("legacy-pattern", "pattern", 400, None, 1),
    ("permanent-feedback", "feedback", 400, None, 1),
]

#: category -> decay_days. gotcha/pattern carry a LEGACY finite window, the
#: exact shape PERMANENT_OVERRIDES exists to neutralise; feedback is NULL.
_FIXTURE_CONFIG = [
    ("progress", 30),
    ("commitment", 30),
    ("gotcha", 180),
    ("pattern", 180),
    ("feedback", None),
]


def _select_decayable() -> list[str]:
    """Ids the production predicate selects from the fixture rows."""
    db = sqlite3.connect(":memory:")
    db.execute(
        "CREATE TABLE memories (id TEXT, category TEXT, created_at TEXT, "
        "deadline_at TEXT, is_active INTEGER)"
    )
    db.execute("CREATE TABLE category_config (category TEXT, decay_days INT)")
    for mid, category, created, deadline, active in _FIXTURE_ROWS:
        db.execute(
            "INSERT INTO memories VALUES (?, ?, ?, ?, ?)",
            (mid, category, _days_before(created),
             None if deadline is None else _days_before(deadline), active),
        )
    db.executemany(
        "INSERT INTO category_config VALUES (?, ?)", _FIXTURE_CONFIG
    )
    where = _to_sqlite(_capture_decay_where())
    rows = db.execute(
        f"SELECT m.id FROM memories m JOIN category_config c ON {where}",
        {"now": _AS_OF.isoformat()},
    ).fetchall()
    db.close()
    return sorted(r[0] for r in rows)


class TestDecayPredicateSemantics:
    """What the predicate actually selects, run rather than pattern-matched."""

    def test_selects_exactly_the_past_decay_active_rows(self):
        """Kills NOW() - interval -> NOW() + interval, < -> >, and AND -> OR.

        Each of those mutations changes this set: the arithmetic flip and the
        operator flip select the FRESH rows instead of the stale ones, and
        turning the is_active conjunction into a disjunction pulls in
        old-but-inactive.
        """
        assert _select_decayable() == [
            "old-progress", "overdue-commitment",
        ]

    def test_a_legacy_window_cannot_decay_a_permanent_category(self):
        """gotcha/pattern survive a finite decay_days in category_config.

        Kills the mutation that deletes ``AND m.category <> ALL(%s)``: the
        fixture gives both categories a legacy 180-day window, exactly the
        row schema.sql's ON CONFLICT DO NOTHING cannot repair.
        """
        selected = _select_decayable()
        assert "legacy-gotcha" not in selected
        assert "legacy-pattern" not in selected

    def test_permanent_overrides_mirror_archive_memories(self):
        """The two lists must not drift apart."""
        archive = importlib.import_module("archive_memories_for_overrides")
        assert set(decay_mod.PERMANENT_OVERRIDES) == set(
            archive.PERMANENT_OVERRIDES
        )


class TestSchemaVersionGuard:
    """The version check must actually run before any decay query."""

    def test_meta_query_precedes_the_decay_query(self, mock_db):
        """Kills the mutation that deletes the assert_schema_version call."""
        mock_conn, mock_cur = mock_db
        with patch("psycopg2.connect", return_value=mock_conn):
            decay_mod.apply_decay(logging.getLogger("apply-decay"), dry_run=True)

        executed = [call.args[0] for call in mock_cur.execute.call_args_list]
        assert "meta" in executed[0], "the schema-version guard did not run first"
        assert any("content_preview" in sql for sql in executed[1:])
