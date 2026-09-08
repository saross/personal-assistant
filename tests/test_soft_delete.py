"""
The soft-delete predicate and its write-side mirror (audit M1, M-1).

``/forget`` is carried out by an LLM editing ``memories.jsonl`` by hand, so
the value it writes is not guaranteed to be the JSON boolean. Two things
have to agree about every shape it might produce:

* the READERS (``digest.py``, ``fetch-memories.py``) deciding whether to
  surface the record from JSONL, and
* PostgreSQL, which the ``active_memories`` view filters on
  ``is_active = TRUE``.

Audit M1 closed the gap for ``"false"``. Audit M-1 found the token set was
still a strict subset of PostgreSQL's own boolean-false grammar, so ``"no"``,
``"off"``, ``"f"``, and ``"n"`` reopened the same split one keystroke
further along — and that the write side passed the raw value to a BOOLEAN
column, where an int has no implicit cast and failed the sync outright.

The truth table below is the contract. It is written out in full, rather
than derived from the module's own constants, so a change to those
constants has to be a deliberate edit here too.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from _soft_delete import is_active, normalise_flag  # noqa: E402

#: Every value that must retire a memory. The strings are PostgreSQL's
#: boolean-false inputs (src/backend/utils/adt/bool.c), which is the set the
#: database would agree with; the rest are the JSON shapes a hand-edit
#: produces.
FALSE_VALUES: list[Any] = [
    False,
    0, 0.0, -0.0,
    "false", "FALSE", "False", " false ",
    "f", "F", " f ",
    "no", "NO", "No",
    "n", "N",
    "off", "OFF", "Off",
    "0", " 0 ",
]

#: Every value that must leave a memory active. Includes the shapes nobody
#: expects: the field was added with ``/forget``, so anything unrecognised
#: must NOT be read as retirement or the whole legacy corpus disappears.
TRUE_VALUES: list[Any] = [
    True,
    1, 2, -1, 1.0, 0.5,
    "true", "TRUE", " true ",
    "t", "T",
    "yes", "y", "on", "1",
    "", "   ",
    "maybe", "nope", "none", "null",
]


class TestIsActiveTruthTable:
    """The read side: what hides a memory, and what must not."""

    @pytest.mark.parametrize("value", FALSE_VALUES)
    def test_false_values_retire_the_record(self, value: Any) -> None:
        """Kills: narrowing _FALSE_TOKENS back to {"false", "0"}.

        Each string here is one PostgreSQL reads as false, so leaving any of
        them active reopens the reader/database split.
        """
        assert is_active({"is_active": value}) is False

    @pytest.mark.parametrize("value", TRUE_VALUES)
    def test_true_and_unknown_values_stay_active(self, value: Any) -> None:
        """Kills: treating an unrecognised value as retirement."""
        assert is_active({"is_active": value}) is True

    def test_absent_key_is_active(self) -> None:
        """The legacy default: the field postdates most of the corpus."""
        assert is_active({}) is True
        assert is_active({"id": "2026-03-15-abc123"}) is True

    def test_none_is_active(self) -> None:
        """An explicit null is not a forget instruction."""
        assert is_active({"is_active": None}) is True

    def test_numeric_zero_branch_is_reachable(self) -> None:
        """Pins the isinstance((int, float)) branch, which was unpinned.

        ``bool`` subclasses ``int``, so the bool check must come first;
        deleting the numeric branch entirely would send ``0`` to the string
        comparison, where ``"0"`` happens to be a false token — so this
        asserts the float too, which stringifies to ``"0.0"`` and is NOT.
        """
        assert is_active({"is_active": 0}) is False
        assert is_active({"is_active": 0.0}) is False
        assert str(0.0) not in ("0",)  # the string path would miss it
        assert is_active({"is_active": 2.5}) is True

    def test_readers_share_this_exact_function(self) -> None:
        """Both JSONL readers, one predicate (audit M1)."""
        import digest
        fetch_memories = __import__("fetch-memories")

        assert fetch_memories.is_active is is_active
        assert digest.is_active is is_active


class TestNormaliseFlag:
    """The write side: what reaches a BOOLEAN column."""

    @pytest.mark.parametrize("value", FALSE_VALUES)
    def test_false_values_become_real_false(self, value: Any) -> None:
        result = normalise_flag(value)
        assert result is False, f"{value!r} -> {result!r}"

    @pytest.mark.parametrize("value", TRUE_VALUES)
    def test_true_and_unknown_values_become_real_true(self, value: Any) -> None:
        result = normalise_flag(value)
        assert result is True, f"{value!r} -> {result!r}"

    def test_always_returns_a_bool_never_the_input(self) -> None:
        """Kills: returning the raw value.

        psycopg2 sends an int as an SQL integer literal and PostgreSQL has
        no implicit int4 -> bool cast, so a hand-edited 0 failed the whole
        statement rather than retiring the memory.
        """
        for value in (*FALSE_VALUES, *TRUE_VALUES):
            assert isinstance(normalise_flag(value), bool)

    def test_absent_takes_the_default(self) -> None:
        """Mirrors the column default (TRUE) when the key was missing."""
        assert normalise_flag(None) is True
        assert normalise_flag(None, default=False) is False

    def test_agrees_with_the_reader_on_every_shape(self) -> None:
        """The point of the pair: the database and the JSONL readers must
        never disagree about the same record.

        Kills: widening one token set without the other.
        """
        for value in (*FALSE_VALUES, *TRUE_VALUES):
            assert normalise_flag(value) is is_active({"is_active": value}), value
