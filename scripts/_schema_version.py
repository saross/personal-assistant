#!/usr/bin/env python3
"""
Schema-version assertion for PostgreSQL-touching scripts.

Why
---
``scripts/schema.sql`` is the source of truth for the derived
PostgreSQL query layer. Several scripts (sync, fetch, audit, decay,
backfill, MCP, rebuild) read or write that schema. When the schema
evolves but a script is not redeployed, the script can run against
the wrong shape and either silently produce wrong results or raise an
opaque ``KeyError`` deep inside a code path that is hard to attribute.

The audit (IC5, B-X1) flagged the absence of a boot-time assertion as
the missing safety net.

Contract
--------
* ``scripts/schema.sql`` provisions a ``meta`` table with one row
  per key, including a ``schema_version`` row.
* Every PG-touching script calls :func:`assert_schema_version` near
  the start of its main path, **before** issuing any query that
  depends on the schema shape.
* On version mismatch (or missing ``meta`` table / row), the helper
  prints a clear error to stderr and raises :class:`SchemaVersionError`.
  Callers either let it propagate (script exits with non-zero status)
  or catch and translate into a script-specific exit code.

Bumping the version
-------------------
Schema migrations bump ``EXPECTED_SCHEMA_VERSION`` here **and** the
``INSERT … VALUES ('schema_version', '<new>')`` literal in
``scripts/schema.sql``. The two MUST stay in lockstep; a CI hook (or
the next audit pass) should treat any commit changing one without the
other as suspicious.

Audit refs
----------
* ``reports/audit-2026-05-02/SUMMARY.md`` — IC5, B-X1.
* ``reports/audit-2026-05-02/cluster-B-postgres.md`` — B-X1 narrative.
"""

from __future__ import annotations

import sys
from typing import Any

# The expected on-disk schema version. Bump when scripts/schema.sql
# changes in any way that affects column shape, view definition, or
# meta-table content. The literal must match the value seeded by
# scripts/schema.sql in the meta table.
EXPECTED_SCHEMA_VERSION = "3"


class SchemaVersionError(RuntimeError):
    """Raised when the on-disk schema version does not match the script's
    expected version. Callers should let this propagate so the operator
    sees a non-zero exit status."""


def _format_error(actual: str | None, expected: str, hint: str) -> str:
    """Build a single-line error string for stderr."""
    return (
        f"schema_version mismatch: expected {expected!r}, "
        f"got {actual!r}. {hint}"
    )


def assert_schema_version(
    conn: Any,
    expected: str = EXPECTED_SCHEMA_VERSION,
) -> None:
    """Assert the live PG schema version matches *expected*.

    Parameters
    ----------
    conn
        A live psycopg2 connection (or anything that quacks like one
        — the helper only needs ``.cursor()`` returning a context
        manager).
    expected
        The version this script was written against. Defaults to
        :data:`EXPECTED_SCHEMA_VERSION` (the global constant). Tests
        use the parameter to inject mismatches without monkey-patching.

    Raises
    ------
    SchemaVersionError
        On mismatch, missing ``meta`` table, or missing
        ``schema_version`` row. The error is also printed to stderr
        before raising so the operator sees it even if the caller
        swallows the exception.
    """
    actual: str | None = None
    hint = (
        "Run scripts/schema.sql against claude_memories to migrate, "
        "then re-run this script."
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT value FROM meta WHERE key = 'schema_version'"
            )
            row = cur.fetchone()
            actual = row[0] if row else None
    except Exception as exc:  # noqa: BLE001 — translate any DB error
        msg = (
            f"schema_version check failed: {exc}. "
            "Is scripts/schema.sql applied to claude_memories?"
        )
        print(msg, file=sys.stderr, flush=True)
        raise SchemaVersionError(msg) from exc

    if actual != expected:
        msg = _format_error(actual, expected, hint)
        print(msg, file=sys.stderr, flush=True)
        raise SchemaVersionError(msg)
