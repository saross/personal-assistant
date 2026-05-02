"""
Tests for the shared schema-version assertion (audit IC5 / B-X1).

Pins three contracts:

* The expected version constant matches the seeded ``meta`` row in
  ``scripts/schema.sql`` — bumping one without the other is caught.
* A live PG instance with the correct ``meta.schema_version`` row
  passes the assertion (smoke-test against the live database when
  available).
* A mismatch raises :class:`SchemaVersionError` and prints to stderr.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
SCHEMA_SQL = SCRIPTS_DIR / "schema.sql"


@pytest.fixture(scope="module")
def schema_module():
    """Load the shared schema-version helper."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    import _schema_version  # noqa: WPS433
    return _schema_version


# ---------------------------------------------------------------------------
# Constant parity — schema.sql and _schema_version.py stay in lockstep
# ---------------------------------------------------------------------------


def test_expected_version_matches_schema_sql(schema_module):
    """The ``EXPECTED_SCHEMA_VERSION`` constant matches the value
    seeded by ``scripts/schema.sql``.

    Pins the audit IC5 contract: bumping the migration without bumping
    the constant (or vice versa) is a deployment-breaking inconsistency.
    """
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    # Find the seeded value: ('schema_version', '<value>')
    m = re.search(
        r"\('schema_version',\s*'([^']+)'\)",
        sql,
    )
    assert m is not None, "schema.sql does not seed schema_version"
    seeded = m.group(1)
    assert schema_module.EXPECTED_SCHEMA_VERSION == seeded, (
        f"Mismatch: _schema_version.py expects "
        f"{schema_module.EXPECTED_SCHEMA_VERSION!r}, schema.sql seeds "
        f"{seeded!r}. Both literals must be bumped together."
    )


# ---------------------------------------------------------------------------
# Mismatch path — error printed to stderr, exception raised
# ---------------------------------------------------------------------------


def _build_fake_conn(returned_value):
    """Build a fake psycopg-style connection that returns a single row.

    Yields ``returned_value`` from ``cursor().fetchone()``. ``None``
    simulates a missing ``meta`` row; a tuple simulates a present one.
    """
    cur = MagicMock()
    cur.fetchone.return_value = returned_value
    cur.execute.return_value = None
    cur_ctx = MagicMock()
    cur_ctx.__enter__.return_value = cur
    cur_ctx.__exit__.return_value = False
    conn = MagicMock()
    conn.cursor.return_value = cur_ctx
    return conn


def test_assertion_passes_on_match(schema_module):
    """Matching version passes silently."""
    conn = _build_fake_conn(("1",))
    schema_module.assert_schema_version(conn, expected="1")


def test_assertion_raises_on_mismatch(schema_module, capsys):
    """Mismatching version raises ``SchemaVersionError`` and prints to
    stderr — this is the audit B-X1 contract.
    """
    conn = _build_fake_conn(("2",))
    with pytest.raises(schema_module.SchemaVersionError) as exc_info:
        schema_module.assert_schema_version(conn, expected="1")

    captured = capsys.readouterr()
    # Error message mentions both the expected and actual values
    assert "schema_version mismatch" in str(exc_info.value)
    assert "'1'" in str(exc_info.value)
    assert "'2'" in str(exc_info.value)
    assert "schema_version mismatch" in captured.err


def test_assertion_raises_on_missing_row(schema_module, capsys):
    """Missing ``meta.schema_version`` row raises with a clear hint."""
    conn = _build_fake_conn(None)
    with pytest.raises(schema_module.SchemaVersionError):
        schema_module.assert_schema_version(conn, expected="1")
    captured = capsys.readouterr()
    assert "schema_version mismatch" in captured.err


def test_assertion_raises_on_db_error(schema_module, capsys):
    """A DB error (e.g., missing ``meta`` table) raises with diagnostic
    context rather than letting the underlying exception escape opaquely.
    """
    conn = MagicMock()
    cur_ctx = MagicMock()
    cur_ctx.__enter__.side_effect = RuntimeError("relation \"meta\" does not exist")
    conn.cursor.return_value = cur_ctx

    with pytest.raises(schema_module.SchemaVersionError):
        schema_module.assert_schema_version(conn, expected="1")
    captured = capsys.readouterr()
    assert "schema_version check failed" in captured.err


# ---------------------------------------------------------------------------
# Live-database smoke test (skipped if PG unavailable)
# ---------------------------------------------------------------------------


def test_live_pg_assertion_passes(schema_module):
    """The live ``claude_memories`` database has the seeded version.

    Skips silently when psycopg2 / PG is not available — local CI
    environments and the live deployment both run this.
    """
    psycopg2 = pytest.importorskip("psycopg2")
    try:
        conn = psycopg2.connect(dbname="claude_memories")
    except psycopg2.OperationalError:
        pytest.skip("PostgreSQL not reachable")

    try:
        schema_module.assert_schema_version(conn)
    finally:
        conn.close()
