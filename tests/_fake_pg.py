"""
Fake ``psycopg2`` connection for the retrieval tests (audit round 4b).

Why this exists
---------------
Lens B found the entire PostgreSQL query body of ``fetch-memories.py``
unreachable: ``try_postgres`` could return a hard-coded list right after
connecting and the suite stayed green, because every test stubbed the
function rather than the driver. Swapping ``active_memories`` for
``memories``, ``AND`` for ``OR``, ``DESC`` for ``ASC``, or dropping the
``LIMIT`` were all invisible for the same reason.

So this module supplies a connection whose cursor **evaluates** the SQL
the production code builds, against rows a test seeds. It is not a
PostgreSQL: it understands exactly the handful of clause shapes these
scripts generate, and raises on anything else rather than quietly
returning the wrong answer. Every call is recorded as ``(sql, params)``
so a test can also assert on the statement itself.

Two engines:

* :class:`FakeMemoryDB` — evaluates the memory queries (``active_memories``
  vs ``memories``, the filter conditions, ordering, cosine distance, and
  ``LIMIT``).
* :class:`CannedDB` — records calls and replays fixed rows, for queries
  whose *text* is the thing under test (the session-chunk join).

Nothing here opens a socket. Tests must still monkeypatch
``psycopg2.connect``; :func:`connect_factory` builds the replacement.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any

#: The version ``_schema_version.assert_schema_version`` expects to read.
#: Kept as a parameter so a test can hand back a mismatching value.
DEFAULT_SCHEMA_VERSION = "3"

_AND_OR = re.compile(r"\s+(AND|OR)\s+")


def _parse_dt(value: Any) -> datetime:
    """Parse a seeded ``created_at`` into an aware datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _cosine_distance(a: list[float], b: list[float]) -> float:
    """pgvector's ``<=>`` operator: 1 - cosine similarity."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if not na or not nb:
        return 1.0
    return 1.0 - dot / (na * nb)


class FakeMemoryDB:
    """Evaluate the memory-table SQL these scripts build, over seeded rows.

    Rows are dicts. ``is_active`` (default True) and ``decayed`` (default
    False) drive the ``active_memories`` view, so a test that seeds a
    forgotten or decayed row can tell the view from the base table.
    """

    def __init__(
        self, rows: list[dict[str, Any]],
        *, schema_version: str = DEFAULT_SCHEMA_VERSION,
    ) -> None:
        self.rows = rows
        self.schema_version = schema_version
        self.calls: list[tuple[str, list[Any]]] = []

    # -- clause helpers ---------------------------------------------------

    def _table_rows(self, table: str) -> list[dict[str, Any]]:
        """Apply the ``active_memories`` view definition (schema.sql)."""
        if table == "memories":
            return list(self.rows)
        if table == "active_memories":
            return [
                r for r in self.rows
                if r.get("is_active", True) and not r.get("decayed", False)
            ]
        raise AssertionError(f"fake db: unknown table {table!r}")

    @staticmethod
    def _condition(cond: str, param: Any):
        """Return a row predicate for one WHERE condition."""
        cond = cond.strip()
        if cond == "TRUE":
            return lambda row: True
        if cond == "embedding IS NOT NULL":
            return lambda row: row.get("embedding") is not None
        if cond.startswith("id = "):
            return lambda row: row.get("id") == param
        if cond.startswith("category = "):
            return lambda row: row.get("category") == param
        if cond.startswith("project = "):
            return lambda row: row.get("project") == param
        if cond.startswith("research_tags && "):
            wanted = {str(t).lower() for t in param}
            return lambda row: bool(
                wanted & {str(t).lower() for t in (row.get("research_tags") or [])}
            )
        if cond.startswith("to_tsvector("):
            # plainto_tsquery ANDs the query's terms; approximate with
            # "every word appears somewhere in the searchable text".
            terms = str(param).lower().split()
            return lambda row: all(
                term in " ".join(
                    str(row.get(f) or "")
                    for f in ("content", "summary", "source_context")
                ).lower()
                for term in terms
            )
        if cond.startswith("created_at > NOW() - make_interval"):
            cutoff = datetime.now(timezone.utc) - timedelta(days=int(param))
            return lambda row: _parse_dt(row["created_at"]) > cutoff
        raise AssertionError(f"fake db: unhandled condition {cond!r}")

    # -- the cursor's entry point ----------------------------------------

    def run(self, sql: str, params: list[Any]):
        """Execute *sql* and return ``(rows, description)``."""
        self.calls.append((sql, list(params)))
        flat = " ".join(sql.split())

        if "FROM meta" in flat:
            return [(self.schema_version,)], [("value",)]
        if flat.startswith("SELECT COUNT(*) FILTER"):
            rows = self._table_rows("active_memories")
            missing = sum(1 for r in rows if r.get("embedding") is None)
            return [(missing, len(rows))], [("count",), ("count",)]

        head, _, rest = flat.partition(" FROM ")
        select_list = head[len("SELECT "):]
        table = rest.split()[0]
        where = ""
        order = ""
        if " WHERE " in rest:
            where = rest.split(" WHERE ", 1)[1]
        tail_order = ""
        if " ORDER BY " in where:
            where, tail_order = where.split(" ORDER BY ", 1)
            order = tail_order
        limit = None
        cursor = iter(params)
        # Placeholders bind in textual order: select list, WHERE, ORDER BY,
        # then LIMIT. The query vector lives in the select list.
        vector = [next(cursor) for _ in range(select_list.count("%s"))]
        rows = self._table_rows(table)

        if where:
            # Tokens alternate condition, operator, condition, ... Binding
            # the parameters here (once, in textual order) rather than per
            # row keeps the operator fold below trivial -- and it is that
            # fold, not a hard-coded ``all()``, that makes an AND -> OR
            # mutation observable.
            tokens = _AND_OR.split(where)
            predicates = []
            operators: list[str] = []
            for index, token in enumerate(tokens):
                if index % 2:
                    operators.append(token)
                    continue
                arg = next(cursor) if "%s" in token else None
                predicates.append(self._condition(token, arg))

            def keep(row: dict[str, Any]) -> bool:
                """Fold the conditions with the operators the SQL used."""
                value = predicates[0](row)
                for op, pred in zip(operators, predicates[1:]):
                    value = (value and pred(row)) if op == "AND" \
                        else (value or pred(row))
                return value

            rows = [r for r in rows if keep(r)]

        if order:
            if " LIMIT " in order:
                order, _ = order.split(" LIMIT ", 1)
            order = order.strip()
            if order.startswith("embedding <=>"):
                target = _as_vector(next(cursor))
                rows.sort(key=lambda r: _cosine_distance(r["embedding"], target))
                # ASC (the default) is closest-first; an explicit DESC would
                # rank the LEAST similar memories first.
                if order.endswith("DESC"):
                    rows.reverse()
            elif order.startswith("created_at"):
                rows.sort(
                    key=lambda r: _parse_dt(r["created_at"]),
                    reverse="DESC" in order,
                )
            else:
                raise AssertionError(f"fake db: unhandled ORDER BY {order!r}")

        if " LIMIT " in flat:
            limit = next(cursor)
            rows = rows[:limit]

        columns = [c.strip() for c in select_list.split(",")]
        out: list[tuple[Any, ...]] = []
        for row in rows:
            values: list[Any] = []
            for col in columns:
                if col.startswith("1 - (embedding"):
                    values.append(
                        1 - _cosine_distance(row["embedding"], _as_vector(vector[0]))
                    )
                else:
                    values.append(row.get(col))
            out.append(tuple(values))
        description = [
            (c.split(" AS ")[-1].strip(),) for c in columns
        ]
        return out, description


def _as_vector(value: Any) -> list[float]:
    """Accept a list or the JSON string ``try_semantic`` sends to pgvector."""
    if isinstance(value, str):
        import json
        return json.loads(value)
    return list(value)


class CannedDB:
    """Record every statement and replay fixed rows regardless of the SQL.

    For queries whose generated *text* is what a test asserts on (the
    session-chunk search: LIKE escaping, the role filter, the ORDER BY),
    evaluating the SQL would add nothing the assertions do not already
    make directly.
    """

    def __init__(
        self, rows: list[tuple[Any, ...]] | None = None,
        description: list[tuple[str]] | None = None,
    ) -> None:
        self.rows = rows or []
        self.description = description or []
        self.calls: list[tuple[str, list[Any]]] = []

    def run(self, sql: str, params: list[Any]):
        """Record the call and hand back the canned rows."""
        self.calls.append((sql, list(params)))
        return list(self.rows), list(self.description)


class FakeCursor:
    """Minimal psycopg2 cursor over one of the engines above."""

    def __init__(self, engine: Any) -> None:
        self._engine = engine
        self._rows: list[tuple[Any, ...]] = []
        self.description: list[tuple[str]] = []
        self.closed = False

    def execute(self, sql: str, params: Any = None) -> None:
        """Run *sql* through the engine, recording it."""
        self._rows, self.description = self._engine.run(
            sql, list(params) if params is not None else [],
        )

    def fetchall(self) -> list[tuple[Any, ...]]:
        """Return every row from the last ``execute``."""
        return self._rows

    def fetchone(self) -> tuple[Any, ...] | None:
        """Return the first row from the last ``execute``, or ``None``."""
        return self._rows[0] if self._rows else None

    def close(self) -> None:
        """Mark the cursor closed (the production code uses ``with``)."""
        self.closed = True

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class FakeConnection:
    """Minimal psycopg2 connection: hands out cursors, records its close."""

    def __init__(self, engine: Any, kwargs: dict[str, Any]) -> None:
        self.engine = engine
        self.kwargs = kwargs
        self.closed = False

    def cursor(self) -> FakeCursor:
        """Return a fresh cursor bound to this connection's engine."""
        return FakeCursor(self.engine)

    def close(self) -> None:
        """Record that the caller closed the connection."""
        self.closed = True


class ConnectRecorder:
    """A ``psycopg2.connect`` replacement that records its keyword arguments.

    ``connections`` holds every :class:`FakeConnection` handed out, so a
    test can assert both on the connection parameters (statement timeout,
    connect timeout) and on whether the connection was closed.
    """

    def __init__(self, engine: Any) -> None:
        self.engine = engine
        self.calls: list[dict[str, Any]] = []
        self.connections: list[FakeConnection] = []

    def __call__(self, *args: Any, **kwargs: Any) -> FakeConnection:
        self.calls.append(dict(kwargs))
        conn = FakeConnection(self.engine, dict(kwargs))
        self.connections.append(conn)
        return conn


def connect_factory(engine: Any) -> ConnectRecorder:
    """Build the ``psycopg2.connect`` stand-in for *engine*."""
    return ConnectRecorder(engine)
