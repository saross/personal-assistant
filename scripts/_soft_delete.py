#!/usr/bin/env python3
"""
The single soft-delete predicate every memory reader must share.

Why this module exists
----------------------
``/forget`` retires a memory by setting ``is_active`` on its JSONL record
(``commands/forget.md``). Two readers had their own copy of the test, and
both wrote it as ``mem.get("is_active", True) is not False`` — an identity
comparison against the JSON boolean, and nothing else.

That is exactly one keystroke away from a silent data-visibility split
(audit round 4b-2, finding M1). ``/forget`` is executed by an LLM editing
JSONL by hand, so writing the **string** ``"false"`` instead of the boolean
is a plausible slip. When it happens:

* PostgreSQL still hides the memory — ``scripts/sync_memory_edit.py`` passes
  the value to a ``BOOLEAN`` column, and the server casts ``'false'``
  correctly, so the ``active_memories`` view drops the row;
* every JSONL reader keeps serving it, because ``"false" is not False``.

So the memory disappears on the machine with a database and keeps
surfacing on every machine without one — the offline half of the failure
audit R2 was raised to close, reintroduced through a type.

The fix is to normalise rather than to compare identities, mirroring how
``digest.is_disproved`` already reads ``verified``: a real bool is honoured,
and any other value is lowercased and compared as text. ``0`` counts as
false too, since JSON numbers are the other shape a hand-edit produces.

Kept deliberately tiny and dependency-free so both ``digest.py`` (a pure
selector module) and ``fetch-memories.py`` can import it without pulling in
anything else, and without either importing the other.
"""

from __future__ import annotations

from typing import Any

#: Every string PostgreSQL accepts as boolean FALSE, lower-cased. Taken from
#: the server's own grammar (``src/backend/utils/adt/bool.c``): ``false``,
#: ``f``, ``no``, ``n``, ``off``, ``0``, plus unique leading prefixes of the
#: spelled-out words. This list must stay a SUPERSET of nothing and an EQUAL
#: of that set — audit M-1 found ``{"false", "0"}`` was a strict subset, so a
#: hand-edited ``"no"``, ``"off"``, ``"f"``, or ``"n"`` read active on every
#: JSONL path and false in PostgreSQL: precisely the split M1 set out to
#: close, one keystroke further along.
#:
#: Anything NOT in this set — a missing key, ``None``, the empty string, a
#: word nobody expected — leaves the record active. The field was added with
#: ``/forget``, so the entire legacy corpus predates it, and a reader that
#: treated the unknown as retirement would hide everything.
_FALSE_TOKENS = frozenset({"false", "f", "no", "n", "off", "0"})

#: The mirror set, for the write side. PostgreSQL is equally liberal about
#: TRUE (``true``, ``t``, ``yes``, ``y``, ``on``, ``1``), and
#: :func:`normalise_flag` needs both to turn a hand-edited value into a real
#: Python bool before it reaches a ``BOOLEAN`` column.
_TRUE_TOKENS = frozenset({"true", "t", "yes", "y", "on", "1"})


def is_active(mem: dict[str, Any]) -> bool:
    """False only when the record has been explicitly forgotten.

    Accepts every shape PostgreSQL would read as false — the JSON boolean
    ``false``, a numeric zero (``0`` or ``0.0``), and the strings ``false``,
    ``f``, ``no``, ``n``, ``off``, ``0`` in any case with surrounding
    whitespace ignored. Every other value — absent key, ``None``, ``True``,
    ``"true"``, a string nobody expected — means active.

    A forgotten memory must never be surfaced eagerly: not in the
    session-start digest, not in the legacy retrieval buckets, and not on
    any JSONL fallback path.
    """
    if "is_active" not in mem:
        return True
    value = mem["is_active"]
    if isinstance(value, bool):
        return value
    if value is None:
        return True
    # ``bool`` is a subclass of ``int``, so the isinstance check above must
    # come first; by here a numeric zero is a genuine int or float zero.
    # ``0.0`` counts: JSON has one number type, so a hand-edit can produce
    # either.
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() not in _FALSE_TOKENS


def normalise_flag(value: Any, *, default: bool = True) -> bool:
    """Coerce a stored ``is_active`` value to a real Python bool.

    For the WRITE side (audit M-1). ``sync_memory_edit.py`` and
    ``sync-to-postgres.py`` passed whatever the JSONL held straight to a
    ``BOOLEAN`` column. psycopg2 adapts a Python ``bool`` and a ``str``
    (which the server then parses), but an ``int`` becomes an SQL integer
    literal, and PostgreSQL has no implicit ``int4 -> bool`` cast — so a
    hand-edited ``0`` raised ``column "is_active" is of type boolean but
    expression is of type integer`` and failed the whole sync, rather than
    retiring the memory.

    Writing a real bool makes the column see exactly what
    :func:`is_active` decided, so the reader and the database can no longer
    disagree about a record whatever shape the flag arrived in.

    *default* applies when the key was absent (``value is None`` only counts
    as "absent" for a field whose column default is TRUE, which this one is).
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    token = str(value).strip().lower()
    if token in _FALSE_TOKENS:
        return False
    if token in _TRUE_TOKENS:
        return True
    # An unrecognised string is not a retirement instruction. Mirrors
    # ``is_active``: only an explicit false-ish value hides a memory.
    return default
