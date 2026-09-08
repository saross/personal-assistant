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

#: Values that mean "retired", once normalised. Anything else — including a
#: missing key, ``None``, and the empty string — leaves the record active:
#: the field was added with ``/forget``, so the whole legacy corpus predates
#: it, and a reader that treated absence as retirement would hide everything.
_FALSE_TOKENS = frozenset({"false", "0"})


def is_active(mem: dict[str, Any]) -> bool:
    """False only when the record has been explicitly forgotten.

    Accepts the JSON boolean ``false``, the integer ``0``, and the strings
    ``"false"``/``"0"`` in any case, with surrounding whitespace ignored.
    Every other value — absent key, ``None``, ``True``, ``"true"``, a
    string nobody expected — means active.

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
    # come first; by here a numeric 0 is a genuine integer or float zero.
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() not in _FALSE_TOKENS
