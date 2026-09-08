"""
Tests for ``scripts/resolve_session_id.py`` — the cross-machine session
resolver.

The module had no coverage at all (lens B, RT16), although
``wiki/planning/memory-system-v2-implementation-plan.md`` lists this file
as a deliverable. Everything here runs against a throwaway archive tree
under ``tmp_path``; the live default root (an rpi share mount) is never
touched.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import resolve_session_id as resolver  # noqa: E402

SESSION_ID = "11111111-2222-3333-4444-555555555555"
OTHER_ID = "99999999-8888-7777-6666-555555555555"


def _archive(root: Path, rel: str, session_id: str) -> Path:
    """Create one archived session directory with its metadata sidecar."""
    directory = root / rel
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "session.meta.json").write_text(
        json.dumps({"session": {"id": session_id, "title": "grid survey"}}),
        encoding="utf-8",
    )
    (directory / "session.jsonl.gz").write_bytes(b"")
    return directory


def _catalogue(root: Path, entries: list[dict[str, Any]]) -> None:
    """Write a CATALOG.json with the given session entries."""
    (root / "CATALOG.json").write_text(
        json.dumps({"sessions": entries}), encoding="utf-8",
    )


class TestResolveViaCatalogue:
    """The fast path, and the containment check it now applies."""

    def test_finds_a_catalogued_session(self, tmp_path: Path) -> None:
        target = _archive(tmp_path, "fieldwork/2026-04-02T09-15_grid", SESSION_ID)
        _catalogue(tmp_path, [
            {"id": SESSION_ID, "path": "fieldwork/2026-04-02T09-15_grid"},
        ])
        assert resolver.resolve_via_catalogue(SESSION_ID, tmp_path) == target

    @pytest.mark.parametrize("field", ["path", "archive_relpath", "relative_path"])
    def test_accepts_every_schema_version_of_the_path_field(
        self, tmp_path: Path, field: str,
    ) -> None:
        """The field name has shifted between catalogue schema versions."""
        target = _archive(tmp_path, "fieldwork/session", SESSION_ID)
        _catalogue(tmp_path, [{"id": SESSION_ID, field: "fieldwork/session"}])
        assert resolver.resolve_via_catalogue(SESSION_ID, tmp_path) == target

    def test_absolute_path_in_the_catalogue_is_refused(
        self, tmp_path: Path,
    ) -> None:
        """Kills: dropping the containment check (audit R13).

        ``Path(root) / "/etc"`` is ``/etc``: an absolute entry silently
        replaces the archive root, and the resolver would hand a caller a
        path from outside the archive as an archived session.
        """
        outside = tmp_path / "outside"
        outside.mkdir()
        root = tmp_path / "archive"
        root.mkdir()
        _catalogue(root, [{"id": SESSION_ID, "path": str(outside)}])
        assert resolver.resolve_via_catalogue(SESSION_ID, root) is None

    def test_dot_dot_escape_is_refused(self, tmp_path: Path) -> None:
        """A relative entry may not walk out of the archive root either."""
        root = tmp_path / "archive"
        root.mkdir()
        _archive(tmp_path, "elsewhere", SESSION_ID)
        _catalogue(root, [{"id": SESSION_ID, "path": "../elsewhere"}])
        assert resolver.resolve_via_catalogue(SESSION_ID, root) is None

    def test_missing_catalogue_returns_none(self, tmp_path: Path) -> None:
        assert resolver.resolve_via_catalogue(SESSION_ID, tmp_path) is None

    def test_malformed_catalogue_returns_none(self, tmp_path: Path) -> None:
        """A corrupt catalogue degrades to the filesystem walk, not a crash."""
        (tmp_path / "CATALOG.json").write_text("{not json", encoding="utf-8")
        assert resolver.resolve_via_catalogue(SESSION_ID, tmp_path) is None

    def test_catalogued_but_missing_directory_returns_none(
        self, tmp_path: Path,
    ) -> None:
        _catalogue(tmp_path, [{"id": SESSION_ID, "path": "gone/away"}])
        assert resolver.resolve_via_catalogue(SESSION_ID, tmp_path) is None


class TestResolveViaFilesystem:
    """The exhaustive fallback for anything the catalogue missed."""

    def test_finds_a_nested_session(self, tmp_path: Path) -> None:
        target = _archive(
            tmp_path, "LLM-History-Paper/theseus-ship/2026-04-02T09-15", SESSION_ID,
        )
        assert resolver.resolve_via_filesystem(SESSION_ID, tmp_path) == target

    def test_matches_the_id_exactly(self, tmp_path: Path) -> None:
        """Kills: a prefix match on the session id."""
        _archive(tmp_path, "a", SESSION_ID)
        assert resolver.resolve_via_filesystem(SESSION_ID[:8], tmp_path) is None

    def test_skips_malformed_metadata(self, tmp_path: Path) -> None:
        broken = tmp_path / "broken"
        broken.mkdir()
        (broken / "session.meta.json").write_text("{oops", encoding="utf-8")
        target = _archive(tmp_path, "good", SESSION_ID)
        assert resolver.resolve_via_filesystem(SESSION_ID, tmp_path) == target


class TestResolve:
    """Catalogue first, filesystem second."""

    def test_prefers_the_catalogue(self, tmp_path: Path) -> None:
        target = _archive(tmp_path, "catalogued", SESSION_ID)
        _catalogue(tmp_path, [{"id": SESSION_ID, "path": "catalogued"}])
        assert resolver.resolve(SESSION_ID, tmp_path) == target

    def test_falls_back_to_the_walk(self, tmp_path: Path) -> None:
        """Nested sessions are exactly what rebuild_catalogue misses."""
        target = _archive(tmp_path, "deep/nested/session", SESSION_ID)
        _catalogue(tmp_path, [{"id": OTHER_ID, "path": "other"}])
        assert resolver.resolve(SESSION_ID, tmp_path) == target

    def test_missing_root_returns_none(self, tmp_path: Path) -> None:
        assert resolver.resolve(SESSION_ID, tmp_path / "no-such-root") is None


class TestMain:
    """Exit codes are this script's whole interface."""

    def test_hit_exits_zero_and_prints_the_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        target = _archive(tmp_path, "session", SESSION_ID)
        monkeypatch.setattr(
            sys, "argv", ["resolve_session_id.py", SESSION_ID, str(tmp_path)],
        )
        assert resolver.main() == 0
        assert capsys.readouterr().out.strip() == str(target)

    def test_miss_exits_one(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(
            sys, "argv", ["resolve_session_id.py", SESSION_ID, str(tmp_path)],
        )
        assert resolver.main() == 1
        assert "NOT FOUND" in capsys.readouterr().err

    def test_no_arguments_exits_two(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["resolve_session_id.py"])
        assert resolver.main() == 2

    def test_io_error_exits_two_with_one_line(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Kills: removing the OSError handler (audit R14).

        The default root is a share mount; a stale mount raises mid-walk,
        and a traceback with exit 1 is indistinguishable to a caller from
        "no such session".
        """
        def _stale(*args: Any, **kwargs: Any) -> None:
            raise OSError(116, "Stale file handle")

        monkeypatch.setattr(resolver, "resolve", _stale)
        monkeypatch.setattr(
            sys, "argv", ["resolve_session_id.py", SESSION_ID, str(tmp_path)],
        )
        assert resolver.main() == 2
        err = capsys.readouterr().err
        assert err.count("\n") == 1
        assert "Stale file handle" in err


# ---------------------------------------------------------------------------
# Audit L5 — a wrong-shaped catalogue is an error, not a traceback
# ---------------------------------------------------------------------------


class TestMalformedCatalogueShapes:
    """Valid JSON, wrong structure. Each used to escape as a traceback."""

    @pytest.mark.parametrize("payload,fragment", [
        # Top-level list: data.get(...) raised AttributeError.
        ([{"id": SESSION_ID, "path": "session"}], "expected a JSON object"),
        # sessions is not a list: iteration raised or silently misbehaved.
        ({"sessions": {"id": SESSION_ID}}, "must be a list"),
        # An entry that is not an object: entry.get raised AttributeError.
        ({"sessions": ["just a string"]}, "entries must be objects"),
    ])
    def test_shape_errors_raise_catalogue_error(
        self, tmp_path: Path, payload: Any, fragment: str,
    ) -> None:
        """Kills: dropping any of the isinstance guards."""
        (tmp_path / "CATALOG.json").write_text(
            json.dumps(payload), encoding="utf-8",
        )
        with pytest.raises(resolver.CatalogueError) as exc:
            resolver.resolve_via_catalogue(SESSION_ID, tmp_path)
        assert fragment in str(exc.value)

    def test_non_string_path_raises_catalogue_error(
        self, tmp_path: Path,
    ) -> None:
        """``root / {"a": 1}`` raised TypeError before audit L5."""
        _catalogue(tmp_path, [{"id": SESSION_ID, "path": {"nested": "object"}}])
        with pytest.raises(resolver.CatalogueError) as exc:
            resolver.resolve_via_catalogue(SESSION_ID, tmp_path)
        assert "must be a string" in str(exc.value)

    @pytest.mark.parametrize("payload", [
        [{"id": SESSION_ID, "path": "session"}],
        {"sessions": {"id": SESSION_ID}},
    ])
    def test_main_exits_two_with_one_line(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str], payload: Any,
    ) -> None:
        """Kills: removing the CatalogueError handler from main().

        Exit 1 with a traceback is indistinguishable to a caller from
        "no such session"; exit 2 is what the docstring promises.
        """
        (tmp_path / "CATALOG.json").write_text(
            json.dumps(payload), encoding="utf-8",
        )
        monkeypatch.setattr(
            sys, "argv", ["resolve_session_id.py", SESSION_ID, str(tmp_path)],
        )
        assert resolver.main() == 2
        err = capsys.readouterr().err
        assert err.count("\n") == 1
        assert "resolve-session-id:" in err

    def test_a_well_formed_catalogue_still_works(self, tmp_path: Path) -> None:
        """The guards must not reject the ordinary case."""
        target = _archive(tmp_path, "fieldwork/session", SESSION_ID)
        _catalogue(tmp_path, [{"id": SESSION_ID, "path": "fieldwork/session"}])
        assert resolver.resolve_via_catalogue(SESSION_ID, tmp_path) == target

    def test_an_entry_without_a_path_field_is_skipped_not_rejected(
        self, tmp_path: Path,
    ) -> None:
        """A missing path is a miss; only a wrong-typed one is an error."""
        _catalogue(tmp_path, [{"id": SESSION_ID}])
        assert resolver.resolve_via_catalogue(SESSION_ID, tmp_path) is None


class TestContainmentRejectionIsVisible:
    """A catalogue pointing outside its archive is a defect to report."""

    def test_escape_is_reported_on_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Kills: rejecting silently.

        The filesystem walk that follows would otherwise make a broken
        catalogue entry look like an ordinary catalogue miss.
        """
        root = tmp_path / "archive"
        root.mkdir()
        _archive(tmp_path, "elsewhere", SESSION_ID)
        _catalogue(root, [{"id": SESSION_ID, "path": "../elsewhere"}])
        assert resolver.resolve_via_catalogue(SESSION_ID, root) is None
        err = capsys.readouterr().err
        assert "escapes the archive root" in err
        assert "../elsewhere" in err

    def test_an_ordinary_miss_is_silent(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Only escapes are reported; a normal miss says nothing."""
        _catalogue(tmp_path, [{"id": OTHER_ID, "path": "other"}])
        assert resolver.resolve_via_catalogue(SESSION_ID, tmp_path) is None
        assert capsys.readouterr().err == ""
