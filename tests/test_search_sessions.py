"""
Tests for ``scripts/search-sessions.py`` — the indexed session-content search.

Lens B found this file had zero coverage in the full suite: dropping the
LIKE escaping, dropping the role filter, and reversing the rank ordering
all passed. The mutations live in the SQL the module builds, so these
tests assert on the generated statement and its parameters as well as on
what comes back.

Nothing here reaches a database. ``psycopg2.connect`` is replaced in every
test that runs a query, and the autouse fixture makes an unpatched connect
raise — a live ``claude_memories`` is reachable on the development
machine, and this module's whole purpose is to avoid unbounded reads of
the archive.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))
search_sessions = __import__("search-sessions")

from _fake_pg import CannedDB, connect_factory  # noqa: E402

#: The column names the search query selects, in order.
_COLUMNS = [
    "archive_dir", "archive_path", "turn_idx", "role", "session_id",
    "project", "title", "started_at", "rank", "snippet",
]


@pytest.fixture(autouse=True)
def _no_real_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unpatched connect is a test bug, not a database round trip."""
    import psycopg2

    def _forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError(
            "psycopg2.connect reached the real driver; patch it in the test"
        )

    monkeypatch.setattr(psycopg2, "connect", _forbidden)


def _canned_row(**overrides: Any) -> tuple[Any, ...]:
    """One synthetic result row in the select's column order."""
    values = {
        "archive_dir": "2026-04-02T09-15_notebook-refactor",
        "archive_path": "2026-04-02T09-15_notebook-refactor/session.jsonl.gz",
        "turn_idx": 12,
        "role": "assistant",
        "session_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "project": "sherds",
        "title": "Notebook refactor",
        "started_at": "2026-04-02T09:15:00+00:00",
        "rank": 0.42,
        "snippet": "we moved the «loader» into its own module",
    }
    values.update(overrides)
    return tuple(values[c] for c in _COLUMNS)


def _install(monkeypatch: pytest.MonkeyPatch, rows: list[tuple[Any, ...]] | None = None):
    """Point ``psycopg2.connect`` at a recording fake."""
    import psycopg2

    # ``rows=[]`` is a meaningful request (the zero-hit path), so only a
    # missing argument gets the default row.
    seeded = [_canned_row()] if rows is None else rows
    db = CannedDB(seeded, [(c,) for c in _COLUMNS])
    connect = connect_factory(db)
    monkeypatch.setattr(psycopg2, "connect", connect)
    return db, connect


# ---------------------------------------------------------------------------
# Connection bounds (audit R9)
# ---------------------------------------------------------------------------


class TestConnectionBounds:
    """Both timeouts must reach the driver."""

    def test_connect_sets_both_timeouts(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Kills: dropping ``connect_timeout`` or the ``options`` string, AND
        setting either bound to zero (which PostgreSQL reads as "no limit").

        The literals are spelled out rather than compared to the module's
        own constants: ``STATEMENT_TIMEOUT_MS = 0`` would satisfy a
        self-referential assertion while removing the protection entirely
        (audit L3).
        """
        _, connect = _install(monkeypatch)
        search_sessions.search("loader")
        kwargs = connect.calls[0]
        assert kwargs["connect_timeout"] == 5
        assert kwargs["options"] == "-c statement_timeout=30000"
        # And the constants themselves must stay bounds, not switches.
        assert search_sessions.CONNECT_TIMEOUT_SECONDS > 0
        assert search_sessions.STATEMENT_TIMEOUT_MS > 0

    def test_connection_is_closed_even_when_the_query_raises(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The ``finally: conn.close()`` contract."""
        db, connect = _install(monkeypatch)

        def _boom(sql: str, params: list[Any]) -> None:
            raise RuntimeError("query exploded")

        monkeypatch.setattr(db, "run", _boom)
        with pytest.raises(RuntimeError):
            search_sessions.search("loader")
        assert connect.connections[0].closed


# ---------------------------------------------------------------------------
# Substring mode (audit R9 floor, lens B LIKE escaping)
# ---------------------------------------------------------------------------


class TestSubstringMode:
    """Trigram ILIKE: escaped, floored, and newest-first."""

    def test_like_wildcards_in_the_query_are_escaped(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Kills: dropping the ``%`` / ``_`` / backslash escaping.

        Without it an identifier like ``build_model_f1`` matches
        ``buildXmodelYf1`` — the opposite of what "exact match" means.
        """
        db, _ = _install(monkeypatch)
        search_sessions.search("build_model_f1", substring=True)
        _, params = db.calls[0]
        assert params[0] == r"%build\_model\_f1%"

    def test_percent_and_backslash_are_escaped_too(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The backslash must be doubled BEFORE the other two are escaped."""
        db, _ = _install(monkeypatch)
        search_sessions.search(r"50%\x", substring=True)
        _, params = db.calls[0]
        assert params[0] == r"%50\%\\x%"

    @pytest.mark.parametrize("pattern", ["ab", " a ", ""])
    def test_short_patterns_are_refused(
        self, monkeypatch: pytest.MonkeyPatch, pattern: str,
    ) -> None:
        """Kills: removing the trigram floor (a sequential scan of every chunk)."""
        _install(monkeypatch)
        with pytest.raises(ValueError) as exc:
            search_sessions.search(pattern, substring=True)
        assert "trgm" in str(exc.value)

    def test_the_floor_does_not_apply_to_full_text_mode(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """FTS has no trigram index to miss, so a short query is fine."""
        _install(monkeypatch)
        assert search_sessions.search("ab") != []

    def test_substring_orders_newest_first_with_a_tiebreak(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db, _ = _install(monkeypatch)
        search_sessions.search("build_model_f1", substring=True)
        sql, _ = db.calls[0]
        assert "ORDER BY s.started_at DESC NULLS LAST, c.id DESC" in sql


# ---------------------------------------------------------------------------
# Full-text mode
# ---------------------------------------------------------------------------


class TestFullTextMode:
    """Ranking, filters, and the returned shape."""

    def test_ordering_is_rank_desc_with_a_deterministic_tiebreak(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Kills: reversing the rank ordering, and dropping the c.id tiebreak.

        ts_rank ties are common on short chunks; without a final tiebreak the
        same query can return different rows from one run to the next
        (audit R11).
        """
        db, _ = _install(monkeypatch)
        search_sessions.search("loader")
        sql, _ = db.calls[0]
        assert "ORDER BY rank DESC, s.started_at DESC NULLS LAST, c.id DESC" in sql
        assert "ORDER BY rank ASC" not in sql

    def test_role_filter_reaches_the_query(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Kills: dropping the ``AND c.role = %s`` clause."""
        db, _ = _install(monkeypatch)
        search_sessions.search("loader", role="user")
        sql, params = db.calls[0]
        assert "AND c.role = %s" in sql
        assert "user" in params

    def test_project_filter_reaches_the_query(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Kills: dropping the ``AND c.project = %s`` clause."""
        db, _ = _install(monkeypatch)
        search_sessions.search("loader", project="sherds")
        sql, params = db.calls[0]
        assert "AND c.project = %s" in sql
        assert "sherds" in params

    def test_no_filters_means_no_extra_clauses(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The filters are conditional, not always-on."""
        db, _ = _install(monkeypatch)
        search_sessions.search("loader")
        sql, params = db.calls[0]
        assert "c.role" not in sql.split(" WHERE ")[1]
        assert params == ["loader", 10]

    def test_limit_is_the_last_parameter(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Kills: dropping ``LIMIT %s`` (an unbounded archive read)."""
        db, _ = _install(monkeypatch)
        search_sessions.search("loader", project="sherds", role="user", limit=3)
        sql, params = db.calls[0]
        assert sql.rstrip().endswith("LIMIT %s")
        assert params[-1] == 3

    def test_rows_come_back_as_dicts_keyed_by_column(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _install(monkeypatch)
        rows = search_sessions.search("loader")
        assert rows[0]["archive_dir"].endswith("notebook-refactor")
        assert rows[0]["role"] == "assistant"

    def test_every_placeholder_has_a_parameter(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A mismatch here is a runtime error against the real driver."""
        db, _ = _install(monkeypatch)
        search_sessions.search("loader", project="sherds", role="user")
        sql, params = db.calls[0]
        assert sql.count("%s") == len(params)


# ---------------------------------------------------------------------------
# show_turns
# ---------------------------------------------------------------------------


class TestShowTurns:
    """Verbatim retrieval stays scoped and windowed."""

    def test_archive_path_disambiguates_when_supplied(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Without it a session dir holding several transcripts cross-joins."""
        db = CannedDB([(12, "user", "text")], [("turn_idx",), ("role",), ("text",)])
        import psycopg2
        monkeypatch.setattr(psycopg2, "connect", connect_factory(db))
        search_sessions.show_turns(
            "2026-04-02T09-15_notebook-refactor", 12,
            archive_path="2026-04-02T09-15_notebook-refactor/session.jsonl.gz",
        )
        sql, params = db.calls[0]
        assert "AND archive_path = %s" in sql
        assert sql.count("%s") == len(params)

    def test_window_is_ranked_not_arithmetic(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """turn_idx has gaps, so the window is over row numbers."""
        db = CannedDB([(12, "user", "text")], [("turn_idx",), ("role",), ("text",)])
        import psycopg2
        monkeypatch.setattr(psycopg2, "connect", connect_factory(db))
        search_sessions.show_turns("dir", 12, context=2)
        sql, _ = db.calls[0]
        assert "row_number() OVER (ORDER BY turn_idx)" in sql
        assert "BETWEEN f.rn - %s AND f.rn + %s" in sql


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


class TestMain:
    """Exit codes are the CLI's contract."""

    def test_hits_exit_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch)
        assert search_sessions.main(["loader"]) == 0

    def test_no_hits_exit_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, rows=[])
        assert search_sessions.main(["loader"]) == 1

    def test_short_substring_pattern_exits_two(
        self, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A usage error, reported on stderr without a traceback."""
        _install(monkeypatch)
        assert search_sessions.main(["ab", "--substring"]) == 2
        assert "trgm" in capsys.readouterr().err

    def test_missing_psycopg2_exits_two(
        self, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def _raise(*args: Any, **kwargs: Any) -> None:
            raise ImportError("no psycopg2")

        monkeypatch.setattr(search_sessions, "_connect", _raise)
        assert search_sessions.main(["loader"]) == 2
        assert "psycopg2" in capsys.readouterr().err

    def test_json_output_is_parseable(
        self, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        import json

        _install(monkeypatch)
        search_sessions.main(["loader", "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert payload[0]["turn_idx"] == 12


# ---------------------------------------------------------------------------
# Audit M-2 — the query never has to pass through a shell
# ---------------------------------------------------------------------------


class TestQueryStdin:
    """``--query-stdin`` exists so user text is never interpolated anywhere.

    R8 removed the query from a SQL string; this is the same hazard one
    layer out, in the shell command that invokes this script.
    """

    def _run(self, monkeypatch: pytest.MonkeyPatch, text: str, argv: list[str]):
        """Drive main() with *text* on stdin, returning (rc, sql, params)."""
        import io

        db, _ = _install(monkeypatch)
        monkeypatch.setattr(sys, "stdin", io.StringIO(text))
        rc = search_sessions.main(argv)
        return rc, db.calls[0] if db.calls else (None, None)

    @pytest.mark.parametrize("text", [
        "it's a wrap",                       # apostrophe ends shell quoting
        "cost $(whoami) dollars",            # command substitution
        "use `uname -a` here",               # backticks
        'he said "quote" then left',         # double quotes
        "semicolon; rm -rf /",               # command separator
        "back\\slash and %percent",          # LIKE metacharacters
    ])
    def test_hostile_text_reaches_the_query_verbatim(
        self, monkeypatch: pytest.MonkeyPatch, text: str,
    ) -> None:
        """Kills: removing --query-stdin (forcing shell interpolation back).

        Whatever the user typed arrives as one parameter, unmodified. It is
        a parameter, not SQL and not a shell word, so none of it can act.
        """
        rc, (_, params) = self._run(
            monkeypatch, text + "\n", ["--query-stdin"],
        )
        assert rc == 0
        assert params[0] == text

    def test_only_one_trailing_newline_is_stripped(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A heredoc adds exactly one; internal newlines are the user's."""
        _, (_, params) = self._run(
            monkeypatch, "first line\nsecond line\n", ["--query-stdin"],
        )
        assert params[0] == "first line\nsecond line"

    def test_trailing_space_is_preserved(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Only the newline goes: a query may legitimately end in a space."""
        _, (_, params) = self._run(
            monkeypatch, "trailing space \n", ["--query-stdin"],
        )
        assert params[0] == "trailing space "

    def test_other_flags_still_apply(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--query-stdin composes with the filters, not replaces them."""
        _, (sql, params) = self._run(
            monkeypatch, "loader\n",
            ["--query-stdin", "--project", "sherds", "--role", "user",
             "--limit", "3"],
        )
        assert "AND c.project = %s" in sql
        assert params == ["loader", "sherds", "user", 3]

    def test_both_forms_together_is_a_usage_error(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Ambiguity is refused rather than silently resolved."""
        import io

        _install(monkeypatch)
        monkeypatch.setattr(sys, "stdin", io.StringIO("from stdin\n"))
        with pytest.raises(SystemExit) as exc:
            search_sessions.main(["positional", "--query-stdin"])
        assert exc.value.code == 2

    def test_empty_stdin_is_a_usage_error(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An empty heredoc would otherwise search for nothing, quietly."""
        import io

        _install(monkeypatch)
        monkeypatch.setattr(sys, "stdin", io.StringIO("   \n"))
        with pytest.raises(SystemExit) as exc:
            search_sessions.main(["--query-stdin"])
        assert exc.value.code == 2

    def test_positional_form_still_works(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The flag is additive; existing callers are unaffected."""
        db, _ = _install(monkeypatch)
        assert search_sessions.main(["loader"]) == 0
        assert db.calls[0][1][0] == "loader"

    def test_substring_floor_still_applies_via_stdin(
        self, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The trigram guard is not bypassed by the new input path."""
        import io

        _install(monkeypatch)
        monkeypatch.setattr(sys, "stdin", io.StringIO("ab\n"))
        assert search_sessions.main(["--query-stdin", "--substring"]) == 2
        assert "trgm" in capsys.readouterr().err
