"""
PostgreSQL-path tests for ``scripts/fetch-memories.py`` (audit round 4b).

Lens B found the whole query body unreachable: ``try_postgres`` could
return a hard-coded list immediately after connecting and the suite stayed
green, so swapping the ``active_memories`` view for the base table, ``AND``
for ``OR``, ``DESC`` for ``ASC``, or dropping the ``LIMIT`` were all
invisible. These tests drive the real SQL through ``tests/_fake_pg.py``,
which evaluates it against seeded rows.

Nothing here reaches a database: ``psycopg2.connect`` is replaced in every
test, and the autouse fixture below makes an *unpatched* connect attempt
fail loudly rather than opening a socket to the operator's live
``claude_memories``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent))
fetch_memories = __import__("fetch-memories")

from _fake_pg import FakeMemoryDB, connect_factory  # noqa: E402
from _schema_version import EXPECTED_SCHEMA_VERSION  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any connect this file does not explicitly fake is a test bug.

    A live ``claude_memories`` is reachable on the development machine, so
    an unpatched call would silently succeed and read the operator's real
    corpus.
    """
    import psycopg2

    def _forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError(
            "psycopg2.connect reached the real driver; patch it in the test"
        )

    monkeypatch.setattr(psycopg2, "connect", _forbidden)


# ---------------------------------------------------------------------------
# Seed corpus
# ---------------------------------------------------------------------------


def _row(
    mem_id: str,
    *,
    category: str = "decision",
    content: str = "memory content",
    tags: list[str] | None = None,
    created_at: str = "2026-03-15T10:00:00+00:00",
    project: str = "-home-shawn-test-project",
    embedding: list[float] | None = None,
    is_active: bool = True,
    decayed: bool = False,
) -> dict[str, Any]:
    """One seeded row in the fake ``memories`` table."""
    return {
        "id": mem_id,
        "category": category,
        "content": content,
        "summary": f"summary for {mem_id}",
        "confidence": "high",
        "verified": "true",
        "research_tags": tags if tags is not None else ["database"],
        "source_context": "planning",
        "created_at": created_at,
        "project": project,
        "embedding": embedding,
        "is_active": is_active,
        "decayed": decayed,
    }


def _install(monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]], **kw):
    """Point ``psycopg2.connect`` at a fake database seeded with *rows*."""
    import psycopg2

    db = FakeMemoryDB(rows, **kw)
    connect = connect_factory(db)
    monkeypatch.setattr(psycopg2, "connect", connect)
    return db, connect


# ---------------------------------------------------------------------------
# try_postgres — the query body (lens B, RT1-RT3)
# ---------------------------------------------------------------------------


class TestTryPostgresQueryBody:
    """The generated SQL is executed, not merely built."""

    def test_reads_the_active_memories_view_not_the_base_table(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Kills: ``FROM active_memories`` -> ``FROM memories``.

        The view is where the soft-delete and decay rules live
        (schema.sql), so querying the table returns retired records.
        """
        rows = [
            _row("live"),
            _row("forgotten", is_active=False),
            _row("decayed-out", decayed=True),
        ]
        _install(monkeypatch, rows)
        results = fetch_memories.try_postgres(category="decision")
        assert [r["id"] for r in results] == ["live"]

    def test_filters_combine_with_and_not_or(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Kills: joining the conditions with OR.

        The base clause is ``WHERE TRUE``, so an OR fold makes every
        filter a no-op and the query returns the whole corpus.
        """
        rows = [
            _row("both", category="decision", tags=["database"]),
            _row("category-only", category="decision", tags=["ethics"]),
            _row("tag-only", category="progress", tags=["database"]),
        ]
        _install(monkeypatch, rows)
        results = fetch_memories.try_postgres(
            category="decision", tags=["database"],
        )
        assert [r["id"] for r in results] == ["both"]

    def test_orders_newest_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills: ``ORDER BY created_at DESC`` -> ``ASC``."""
        rows = [
            _row("older", created_at="2026-03-01T00:00:00+00:00"),
            _row("newer", created_at="2026-04-01T00:00:00+00:00"),
            _row("middle", created_at="2026-03-20T00:00:00+00:00"),
        ]
        _install(monkeypatch, rows)
        results = fetch_memories.try_postgres(category="decision")
        assert [r["id"] for r in results] == ["newer", "middle", "older"]

    def test_limit_is_applied_server_side(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Kills: dropping the ``LIMIT %s`` clause."""
        rows = [
            _row(f"m{i}", created_at=f"2026-03-{i + 10:02d}T00:00:00+00:00")
            for i in range(5)
        ]
        _install(monkeypatch, rows)
        results = fetch_memories.try_postgres(category="decision", limit=2)
        assert len(results) == 2

    def test_query_matches_summary_and_source_context(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The full-text expression spans the three text columns."""
        rows = [
            _row("hit", content="nothing here", tags=["database"]),
            _row("miss", content="nothing at all", tags=["database"]),
        ]
        rows[0]["source_context"] = "canopy occlusion trial"
        _install(monkeypatch, rows)
        results = fetch_memories.try_postgres(query="canopy occlusion")
        assert [r["id"] for r in results] == ["hit"]

    def test_id_filter_is_exact(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``id = %s`` must not become a prefix match."""
        _install(monkeypatch, [_row("2026-03-15-abc"), _row("2026-03-15-abcdef")])
        results = fetch_memories.try_postgres(memory_id="2026-03-15-abc")
        assert [r["id"] for r in results] == ["2026-03-15-abc"]

    def test_project_filter_is_applied_server_side(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The MCP layer relies on this so LIMIT cannot drop real matches."""
        rows = [
            _row("mine", project="-home-shawn-personal-assistant"),
            _row("theirs", project="-home-shawn-Code-inscriptions"),
        ]
        _install(monkeypatch, rows)
        results = fetch_memories.try_postgres(
            category="decision", project="-home-shawn-personal-assistant",
        )
        assert [r["id"] for r in results] == ["mine"]

    def test_connection_is_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Every path closes the connection it opened.

        The ``connect.connections`` assertion comes first: ``all()`` over an
        empty list is True, so without it this passed even if no connection
        was ever opened (audit L3).
        """
        _, connect = _install(monkeypatch, [_row("a")])
        fetch_memories.try_postgres(category="decision")
        assert connect.connections, "no connection was opened"
        assert all(c.closed for c in connect.connections)

    def test_both_connects_are_bounded(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Audit L3: nothing inspected this script's connect kwargs.

        Kills: dropping ``connect_timeout`` or the ``options`` string from
        either connect site, or setting either bound to 0 -- /recall is
        interactive, so an unbounded connect hangs the session instead of
        falling back to JSONL. Literals, not the module's own constants.
        """
        import embed

        monkeypatch.setattr(embed, "embed_single", lambda text: [1.0, 0.0])
        _, connect = _install(monkeypatch, [_row("a", embedding=[1.0, 0.0])])
        fetch_memories.try_postgres(category="decision")
        fetch_memories.try_semantic("canopy")
        assert len(connect.calls) == 2, "both connect sites must be exercised"
        for kwargs in connect.calls:
            assert kwargs["connect_timeout"] == 5
            assert kwargs["options"] == "-c statement_timeout=30000"
        assert fetch_memories.CONNECT_TIMEOUT_SECONDS > 0
        assert fetch_memories.STATEMENT_TIMEOUT_MS > 0

    def test_datetimes_are_serialised(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A ``datetime`` from the driver comes back as an ISO string."""
        from datetime import datetime, timezone

        row = _row("a")
        row["created_at"] = datetime(2026, 3, 15, 10, tzinfo=timezone.utc)
        _install(monkeypatch, [row])
        results = fetch_memories.try_postgres(category="decision")
        assert results[0]["created_at"] == "2026-03-15T10:00:00+00:00"


# ---------------------------------------------------------------------------
# try_semantic — the vector query (lens B, RT8) and coverage (audit R7)
# ---------------------------------------------------------------------------


class TestTrySemantic:
    """The pgvector query is executed, and its blind spot is reported."""

    @staticmethod
    def _embedded_corpus() -> list[dict[str, Any]]:
        """Two embedded rows plus one with no embedding at all."""
        return [
            _row("far", embedding=[0.0, 1.0]),
            _row("near", embedding=[1.0, 0.05]),
            _row("unembedded", embedding=None),
        ]

    @pytest.fixture(autouse=True)
    def _fake_embedder(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Never call Ollama: the query vector is supplied directly."""
        import embed

        monkeypatch.setattr(embed, "embed_single", lambda text: [1.0, 0.0])

    def test_ranks_by_cosine_distance_closest_first(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Kills: ``ORDER BY embedding <=> %s::vector`` -> ``... DESC``."""
        _install(monkeypatch, self._embedded_corpus())
        results = fetch_memories.try_semantic("canopy")
        assert [r["id"] for r in results] == ["near", "far"]

    def test_unembedded_rows_are_not_searched(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``WHERE embedding IS NOT NULL`` excludes, it does not rank last."""
        _install(monkeypatch, self._embedded_corpus())
        results = fetch_memories.try_semantic("canopy")
        assert "unembedded" not in {r["id"] for r in results}

    def test_similarity_is_one_minus_distance(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An identical vector scores 1.0; an orthogonal one scores 0.0."""
        _install(monkeypatch, [
            _row("same", embedding=[1.0, 0.0]),
            _row("orthogonal", embedding=[0.0, 1.0]),
        ])
        results = fetch_memories.try_semantic("canopy")
        by_id = {r["id"]: r["similarity"] for r in results}
        assert by_id["same"] == pytest.approx(1.0)
        assert by_id["orthogonal"] == pytest.approx(0.0)

    def test_category_and_tag_filters_apply(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Kills: dropping either optional clause from the vector query."""
        rows = [
            _row("wanted", category="decision", tags=["gps"],
                 embedding=[1.0, 0.0]),
            _row("wrong-category", category="progress", tags=["gps"],
                 embedding=[1.0, 0.0]),
            _row("wrong-tag", category="decision", tags=["ethics"],
                 embedding=[1.0, 0.0]),
        ]
        _install(monkeypatch, rows)
        results = fetch_memories.try_semantic(
            "canopy", category="decision", tags=["GPS"],
        )
        assert [r["id"] for r in results] == ["wanted"]

    def test_reports_how_many_active_rows_lack_an_embedding(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Audit R7: the caller must be able to say what was not searched.

        Kills: deleting the coverage COUNT, or counting over the base table.
        """
        rows = self._embedded_corpus() + [
            _row("forgotten-unembedded", embedding=None, is_active=False),
        ]
        _install(monkeypatch, rows)
        coverage: dict[str, Any] = {}
        fetch_memories.try_semantic("canopy", stats=coverage)
        # The forgotten row is outside active_memories, so it is not counted.
        assert coverage == {"unembedded_active": 1, "total_active": 3}

    def test_coverage_is_optional(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Callers that do not ask for coverage still get their results."""
        _install(monkeypatch, self._embedded_corpus())
        assert fetch_memories.try_semantic("canopy") is not None

    def test_main_reports_the_coverage_gap_on_stderr(
        self, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The CLI states the gap rather than implying full coverage."""
        _install(monkeypatch, self._embedded_corpus())
        monkeypatch.setattr(
            sys, "argv", ["fetch-memories.py", "--semantic", "canopy"],
        )
        monkeypatch.setattr(
            fetch_memories, "_log_invocation", lambda args, results: None,
        )
        fetch_memories.main()
        err = capsys.readouterr().err
        assert "1 of 3 active memories have no embedding" in err


# ---------------------------------------------------------------------------
# Schema-version guard at both call sites (lens B, RT14)
# ---------------------------------------------------------------------------


class TestSchemaVersionGuard:
    """A schema mismatch stops the read rather than querying a wrong shape."""

    @pytest.mark.parametrize("call", [
        lambda: fetch_memories.try_postgres(category="decision"),
        lambda: fetch_memories.try_semantic("canopy"),
    ])
    def test_mismatch_exits_two(
        self, monkeypatch: pytest.MonkeyPatch, call,
    ) -> None:
        """Kills: removing ``except SchemaVersionError: sys.exit(2)``."""
        import embed

        monkeypatch.setattr(embed, "embed_single", lambda text: [1.0, 0.0])
        _install(monkeypatch, [_row("a", embedding=[1.0, 0.0])],
                 schema_version="0")
        with pytest.raises(SystemExit) as exc:
            call()
        assert exc.value.code == 2

    def test_matching_version_proceeds(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The guard is not simply always-fail."""
        _install(monkeypatch, [_row("a")],
                 schema_version=EXPECTED_SCHEMA_VERSION)
        assert fetch_memories.try_postgres(category="decision") is not None


# ---------------------------------------------------------------------------
# main() end to end, with PostgreSQL up and down (lens B, RT4)
# ---------------------------------------------------------------------------


class TestMainEndToEnd:
    """``main()`` had no test at all: the JSONL fallback could be deleted."""

    @pytest.fixture(autouse=True)
    def _pinned_log(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        """Pin the invocation log so main() exercises the real writer safely."""
        target = tmp_path / "logs" / "fetch-memories.log"
        monkeypatch.setenv("PA_FETCH_LOG", str(target))
        return target

    def test_postgres_results_are_printed_and_logged(
        self, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str], _pinned_log: Path,
    ) -> None:
        """The happy path: query, render, instrument."""
        _install(monkeypatch, [_row("2026-03-15-abc", content="grid spacing")])
        monkeypatch.setattr(
            sys, "argv", ["fetch-memories.py", "--query", "grid spacing"],
        )
        fetch_memories.main()
        out = capsys.readouterr().out
        assert "Memory Details (1 result)" in out
        line = _pinned_log.read_text(encoding="utf-8")
        assert "selectors=query" in line
        assert "results=1" in line

    def test_falls_back_to_jsonl_when_postgres_is_down(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str], _pinned_log: Path,
    ) -> None:
        """Kills: deleting the JSONL fallback (``results = []`` instead).

        This is the path every machine without PostgreSQL takes for every
        recall, so a silent empty result is a total retrieval failure.
        """
        import json

        import psycopg2

        corpus = tmp_path / "memories.jsonl"
        corpus.write_text(
            json.dumps({
                "id": "2026-03-15-off", "category": "decision",
                "content": "grid spacing is 20 m",
                "created_at": "2026-03-15T10:00:00+00:00",
            }) + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(fetch_memories, "MEMORIES_FILE", corpus)

        def _refuse(*args: Any, **kwargs: Any):
            raise psycopg2.OperationalError("connection refused")

        monkeypatch.setattr(psycopg2, "connect", _refuse)
        monkeypatch.setattr(
            sys, "argv", ["fetch-memories.py", "--query", "grid spacing"],
        )
        fetch_memories.main()
        captured = capsys.readouterr()
        assert "Falling back to JSONL search" in captured.err
        assert "grid spacing is 20 m" in captured.out
        assert "results=1" in _pinned_log.read_text(encoding="utf-8")

    def test_zero_results_still_print_a_message_and_log(
        self, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str], _pinned_log: Path,
    ) -> None:
        """An empty result is reported, never silent."""
        _install(monkeypatch, [])
        monkeypatch.setattr(
            sys, "argv", ["fetch-memories.py", "--query", "nothing matches"],
        )
        fetch_memories.main()
        assert "Memory Details (0 results)" in capsys.readouterr().out
        assert "results=0" in _pinned_log.read_text(encoding="utf-8")

    @pytest.mark.parametrize("argv", [
        ["fetch-memories.py"],                       # no filter at all
        ["fetch-memories.py", "--query", "x", "--limit", "0"],
        ["fetch-memories.py", "--query", "x", "--limit", "-3"],
    ])
    def test_usage_errors_exit_two(
        self, monkeypatch: pytest.MonkeyPatch, argv: list[str],
    ) -> None:
        """Kills: neutering the --limit bound or the at-least-one-filter rule."""
        monkeypatch.setattr(sys, "argv", argv)
        with pytest.raises(SystemExit) as exc:
            fetch_memories.main()
        assert exc.value.code == 2

    def test_archive_is_appended_only_when_asked(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str], _pinned_log: Path,
    ) -> None:
        """``--include-archive`` is opt-in and merges after the active hits."""
        import json

        archive = tmp_path / "archive"
        archive.mkdir()
        (archive / "memories-archive-2026-01.jsonl").write_text(
            json.dumps({
                "id": "2026-01-04-cold", "category": "decision",
                "content": "grid spacing was 10 m in the pilot",
                "created_at": "2026-01-04T10:00:00+00:00",
            }) + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(fetch_memories, "ARCHIVE_DIR", archive)
        _install(monkeypatch, [_row("2026-03-15-hot", content="grid spacing")])
        monkeypatch.setattr(sys, "argv", [
            "fetch-memories.py", "--query", "grid spacing", "--include-archive",
        ])
        fetch_memories.main()
        captured = capsys.readouterr()
        assert "+1 archived record(s)" in captured.err
        assert "Memory Details (2 results)" in captured.out
