"""
The single Digital Object Identifier (DOI) matching rule, pinned on both sides.

``scripts/zotero.py``'s ``find_by_doi`` is the READER (lit-scout marks a
candidate ``[IN ZOTERO]``); ``scripts/lit-scout-zotero-import.py``'s
``find_existing_by_doi`` is the WRITER's only duplicate guard, shared with
``add-doi-to-zotero.py``. Before the fix these were two different rules:
the writer compared ``LOWER(idv.value) = LOWER(?)``, so a DOI stored in
the form Zotero's browser connector saves — ``https://doi.org/10.…`` —
was invisible to a bare-DOI lookup and a duplicate was created, while the
reader had already found it.

These tests run BOTH functions against ONE synthetic on-disk library, so
the two can never drift apart again without a failure here.

All identifiers, titles, and names below are invented.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

from no_network_guard import refuse_socket_connections
from zotero_sqlite_fixture import build_zotero_sqlite, load_zotero_module

_IMPORTER_PATH = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "lit-scout-zotero-import.py"
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse every socket connection for the life of each test."""
    refuse_socket_connections(monkeypatch)


def _load_importer():
    """Load the hyphen-named importer module by path."""
    spec = importlib.util.spec_from_file_location(
        "lit_scout_zotero_import_doi", _IMPORTER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: One item stored with a URL-wrapped, mixed-case DOI (the connector's
#: form) and one stored bare, so both directions of the comparison are
#: exercised against the same database.
_LIBRARY = [
    {
        "key": "WRAPPED1",
        "library_id": 1,
        "collection_id": 1,
        "fields": {
            "title": "Terrace Systems of the Upper Vardar",
            "date": "2031",
            "DOI": "https://doi.org/10.1234/ABC-def",
        },
        "creators": [("Nadia", "Petkova")],
    },
    {
        "key": "BAREDOI1",
        "library_id": 2,
        "fields": {
            "title": "Ceramic Fabric Groups at Kaleto",
            "date": "2030",
            "DOI": "10.5555/plain-doi",
        },
        "creators": [("Marek", "Dvorak")],
    },
]


@pytest.fixture
def library(tmp_path: Path) -> Path:
    """Build the synthetic Zotero data directory and return its path."""
    data_dir = tmp_path / "ZoteroSynthetic"
    data_dir.mkdir()
    build_zotero_sqlite(data_dir / "zotero.sqlite", _LIBRARY)
    return data_dir


class TestReaderFindByDoi:
    """``zotero.find_by_doi`` against a file-backed synthetic library."""

    def test_stored_url_wrapped_doi_found_by_bare_lowercase_lookup(
        self, library: Path
    ) -> None:
        """The connector's URL form must match a bare lower-case lookup."""
        zot = load_zotero_module(library)
        hits = zot.find_by_doi("10.1234/abc-def")
        assert [h["key"] for h in hits] == ["WRAPPED1"]

    def test_stored_bare_doi_found_by_url_wrapped_lookup(
        self, library: Path
    ) -> None:
        """A bare stored DOI must match a URL-wrapped lookup."""
        zot = load_zotero_module(library)
        hits = zot.find_by_doi("https://doi.org/10.5555/PLAIN-DOI")
        assert [h["key"] for h in hits] == ["BAREDOI1"]
        assert hits[0]["library_name"] == "Fieldwork Reading Group"

    def test_absent_doi_returns_nothing(self, library: Path) -> None:
        """A DOI in no library returns an empty list."""
        zot = load_zotero_module(library)
        assert zot.find_by_doi("10.9999/not-here") == []

    def test_prefix_rule_is_a_prefix_rule(self, library: Path) -> None:
        """``doi:`` embedded mid-string is not stripped, only a prefix is."""
        zot = load_zotero_module(library)
        assert zot.doi_match_candidates("DOI:10.1/x")[0] == "10.1/x"
        assert zot._normalise_doi("10.1/xdoi:y") == "10.1/xdoi:y"

    def test_empty_doi_yields_no_candidates(self, library: Path) -> None:
        """A blank DOI must not become a match-everything query."""
        zot = load_zotero_module(library)
        assert zot.doi_match_candidates("   ") == []
        assert zot.find_by_doi("   ") == []


class TestWriterFindExistingByDoi:
    """The importer's duplicate guard, on the same synthetic library."""

    @staticmethod
    def _connect(library: Path) -> sqlite3.Connection:
        """Open the synthetic library read-only, as the importer does."""
        return sqlite3.connect(
            f"{(library / 'zotero.sqlite').as_uri()}?immutable=1", uri=True
        )

    def test_stored_url_wrapped_doi_found_by_bare_lowercase_lookup(
        self, library: Path
    ) -> None:
        """The duplicate guard must see the connector's URL form."""
        importer = _load_importer()
        conn = self._connect(library)
        try:
            hits = importer.find_existing_by_doi("10.1234/abc-def", conn)
        finally:
            conn.close()
        assert [h["key"] for h in hits] == ["WRAPPED1"]
        assert hits[0]["collections"] == "Landscape survey"

    def test_stored_bare_doi_found_by_url_wrapped_lookup(
        self, library: Path
    ) -> None:
        """A bare stored DOI must match a URL-wrapped candidate DOI."""
        importer = _load_importer()
        conn = self._connect(library)
        try:
            hits = importer.find_existing_by_doi(
                "https://dx.doi.org/10.5555/Plain-DOI", conn
            )
        finally:
            conn.close()
        assert [h["key"] for h in hits] == ["BAREDOI1"]

    def test_absent_doi_returns_nothing(self, library: Path) -> None:
        """A DOI in no library returns an empty list."""
        importer = _load_importer()
        conn = self._connect(library)
        try:
            assert importer.find_existing_by_doi("10.9999/absent", conn) == []
        finally:
            conn.close()

    def test_reader_and_writer_share_one_normaliser(self) -> None:
        """The importer must reuse zotero.py's rule, not keep a copy."""
        importer = _load_importer()
        zot_path = Path(importer._ZOTERO_CLIENT.__file__).resolve()
        assert zot_path.name == "zotero.py"
        assert importer.find_existing_by_doi.__module__ is not None
        # Same function object semantics: identical candidate expansion.
        with_wrapper = importer._ZOTERO_CLIENT.doi_match_candidates(
            "DOI:10.1/x"
        )
        assert with_wrapper[0] == "10.1/x"
        assert "https://doi.org/10.1/x" in with_wrapper


if __name__ == "__main__":  # pragma: no cover - convenience entry point
    raise SystemExit(pytest.main([__file__, "-v"]))
