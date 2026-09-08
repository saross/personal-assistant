"""
A fake psycopg2 connection that answers the AUDIT queries from seeded rows.

Sibling module
--------------
``tests/_fake_pg.py`` (audit round 4b) does the same job for the RETRIEVAL
queries: ``FakeMemoryDB`` models the filter/order/limit shapes
``fetch-memories.py`` builds. The two were written in parallel rounds against
different query bodies and have not been unified; a later round could fold
this engine in behind that module's cursor, provided the read-only property
below survives the merge — that module's connection neither refuses a write
nor records ``set_session``, and both are asserted here.

Why
---
The reconciliation engines in ``scripts/audit-postgres-sync.py`` and
``scripts/memory-health-report.py`` were unreached by any test: their SQL
strings were never executed against anything, so swapping a set difference,
hard-coding a table name, or turning ``WHERE is_active IS TRUE`` into
``IS NOT NULL`` all survived the full suite (audit 2026-09-08, findings
ANT1-ANT4). Mocking ``fetchall`` to return a canned list would not have
caught them: the assertion has to depend on what the SQL *asks for*.

So this module evaluates a small, explicit subset of SQL against rows the
test seeds. A query the subset does not model raises
:class:`UnsupportedQuery` rather than answering vaguely — a mutation that
rewrites a query into something unmodelled fails loudly instead of passing.

Read-only by construction
-------------------------
Both callers are documented read-only tools. The fake therefore refuses any
statement that is not a ``SELECT`` (or one of the session-settings verbs a
read-only transaction needs) and refuses ``commit()`` outright, so
"this audit never writes" becomes a property the suite enforces rather than
a claim in a docstring. Every statement is recorded in
:attr:`FakeConnection.statements` for tests that want to assert the shape.

Nothing here opens a socket, and no test using it may reach the real
``claude_memories``.
"""

from __future__ import annotations

import re
from typing import Any, Iterable


class UnsupportedQuery(AssertionError):
    """Raised when a statement falls outside the modelled SQL subset."""


class WriteAttempted(AssertionError):
    """Raised when a read-only caller issues a write or a commit."""


#: Statement verbs a read-only caller may legitimately issue.
_READ_VERBS = ("SELECT", "SET", "BEGIN", "ROLLBACK", "SHOW")

#: Statement verbs that must never appear in a read-only tool.
_WRITE_VERBS = (
    "INSERT", "UPDATE", "DELETE", "TRUNCATE", "COPY", "CREATE", "DROP",
    "ALTER", "GRANT", "REVOKE", "MERGE", "REFRESH",
)


def _norm(sql: str) -> str:
    """Collapse whitespace so a query can be matched regardless of layout."""
    return " ".join(sql.split())


class FakeCursor:
    """A psycopg2-shaped cursor that answers from :class:`FakeDatabase`."""

    def __init__(self, db: "FakeDatabase", conn: "FakeConnection") -> None:
        self._db = db
        self._conn = conn
        self._rows: list[tuple] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def execute(self, sql: str, params: Any = None) -> None:
        """Record the statement, refuse writes, and evaluate the query."""
        text = _norm(sql)
        self._conn.statements.append((text, params))
        verb = text.split(" ", 1)[0].upper()
        if verb in _WRITE_VERBS:
            raise WriteAttempted(
                f"read-only caller issued a write statement: {text!r}"
            )
        if verb not in _READ_VERBS:
            raise UnsupportedQuery(f"unmodelled statement: {text!r}")
        if verb != "SELECT":
            self._rows = []
            return
        self._rows = self._db.evaluate(text, params)

    def fetchone(self) -> tuple | None:
        """The first row of the last query, or ``None``."""
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple]:
        """Every row of the last query."""
        return list(self._rows)

    def close(self) -> None:
        """No-op; present so the cursor quacks like psycopg2's."""


class FakeConnection:
    """A psycopg2-shaped connection over a :class:`FakeDatabase`."""

    def __init__(self, db: "FakeDatabase") -> None:
        self.db = db
        #: Every statement executed on this connection, in order.
        self.statements: list[tuple[str, Any]] = []
        self.closed = False
        self.rollbacks = 0
        self.readonly: bool | None = None
        self.autocommit_set: bool | None = None

    def cursor(self) -> FakeCursor:
        """Return a fresh cursor (usable directly or as a context manager)."""
        return FakeCursor(self.db, self)

    def set_session(self, readonly: bool | None = None,
                    autocommit: bool | None = None, **_kw: object) -> None:
        """Record the session flags a read-only caller should be setting."""
        if readonly is not None:
            self.readonly = readonly
        if autocommit is not None:
            self.autocommit_set = autocommit

    def commit(self) -> None:
        """Refuse: a read-only audit has nothing to commit."""
        raise WriteAttempted("read-only caller issued commit()")

    def rollback(self) -> None:
        """Count rollbacks — the correct way to end a read-only transaction."""
        self.rollbacks += 1

    def close(self) -> None:
        """Mark the connection closed."""
        self.closed = True

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, exc_type: object, *_rest: object) -> bool:
        # psycopg2 COMMITS here on a clean exit. A read-only caller must not
        # use ``with conn:`` for that reason, and this reproduces the hazard.
        if exc_type is None:
            self.commit()
        return False

    @property
    def executed_sql(self) -> list[str]:
        """Just the statement texts, for convenient assertions."""
        return [sql for sql, _params in self.statements]


class FakeDatabase:
    """Rows plus a tiny SQL evaluator over them.

    ``memories`` and ``sessions`` are lists of dicts. ``active_memories`` is
    derived (the view's ``is_active = TRUE`` half, three-valued logic
    included: a NULL ``is_active`` is NOT in the view), so a query against
    the view and one against the table give different answers — which is what
    makes the recall-invariant mutation detectable.
    """

    def __init__(
        self,
        *,
        memories: Iterable[dict] | None = None,
        sessions: Iterable[dict] | None = None,
        schema_version: str | None = "3",
    ) -> None:
        self.memories = [dict(r) for r in (memories or [])]
        self.sessions = [dict(r) for r in (sessions or [])]
        self.schema_version = schema_version

    # -- helpers ----------------------------------------------------------

    def _table(self, name: str) -> list[dict]:
        if name == "memories":
            return self.memories
        if name == "sessions":
            return self.sessions
        if name == "active_memories":
            # schema.sql:273 — ``WHERE m.is_active = TRUE``. SQL three-valued
            # logic drops a NULL row from the view, so the fake must too: the
            # Python idiom ``is not False`` KEEPS it, which made the fake
            # disagree with both PostgreSQL and its own IS TRUE clause below
            # (round 4f-3, finding M5). The decay half of the view is not
            # modelled; these tests do not exercise it.
            return [r for r in self.memories if r.get("is_active") is True]
        raise UnsupportedQuery(f"unknown table: {name}")

    @staticmethod
    def _where(rows: list[dict], clause: str, params: Any) -> list[dict]:
        """Apply the modelled WHERE clauses (is_active tests, id = ANY)."""
        clause = clause.strip()
        if not clause:
            return rows
        upper = clause.upper()
        if upper == "IS_ACTIVE IS TRUE":
            return [r for r in rows if r.get("is_active") is True]
        if upper == "IS_ACTIVE IS FALSE":
            return [r for r in rows if r.get("is_active") is False]
        if upper == "IS_ACTIVE IS NOT NULL":
            return [r for r in rows if r.get("is_active") is not None]
        if upper == "IS_ACTIVE IS NULL":
            return [r for r in rows if r.get("is_active") is None]
        if upper == "ID = ANY(%S)":
            wanted = set(map(str, (params or ((),))[0]))
            return [r for r in rows if str(r.get("id")) in wanted]
        raise UnsupportedQuery(f"unmodelled WHERE clause: {clause!r}")

    # -- evaluation -------------------------------------------------------

    def evaluate(self, sql: str, params: Any) -> list[tuple]:
        """Return the rows *sql* selects, as psycopg2-shaped tuples."""
        if re.fullmatch(
            r"SELECT value FROM meta WHERE key = 'schema_version'", sql,
            re.IGNORECASE,
        ):
            return [] if self.schema_version is None else [(self.schema_version,)]

        match = re.fullmatch(
            r"SELECT (?P<cols>.+?) FROM (?P<table>\w+)"
            r"(?: WHERE (?P<where>.+?))?",
            sql, re.IGNORECASE,
        )
        if not match:
            raise UnsupportedQuery(f"unmodelled query: {sql!r}")

        rows = self._where(
            self._table(match.group("table").lower()),
            match.group("where") or "",
            params,
        )
        cols = match.group("cols").strip()
        if cols.upper() in ("COUNT(*)", "COUNT(1)"):
            return [(len(rows),)]
        names = [c.strip() for c in cols.split(",")]
        return [tuple(r.get(name) for name in names) for r in rows]


def connect_factory(db: FakeDatabase) -> tuple[FakeConnection, Any]:
    """Return ``(connection, connect_callable)`` sharing one connection.

    Patch ``psycopg2.connect`` with the second element; inspect the first
    afterwards for the statements the code under test issued.
    """
    conn = FakeConnection(db)

    def connect(*_args: object, **_kwargs: object) -> FakeConnection:
        return conn

    return conn, connect
