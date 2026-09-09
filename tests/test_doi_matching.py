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
import re
import sqlite3
from pathlib import Path

import pytest

from zotero_sqlite_fixture import build_zotero_sqlite, load_zotero_module

#: The scripts directory, for source-level assertions about zotero.py.
SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

_IMPORTER_PATH = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "lit-scout-zotero-import.py"
)




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
    # Stored with surrounding whitespace — the shape a paste from a PDF
    # or a rendered web page leaves. Only TRIM on the stored side matches
    # it (round 4d-2). Round 4d-3 pads it with EVERY character the trim
    # expression names — tab, carriage return, newline, space, and the
    # three Unicode spaces (U+00A0, U+202F, U+2007) — so dropping any one
    # of them from that expression fails a test rather than none.
    {
        "key": "PADDEDD1",
        "library_id": 1,
        "fields": {
            "title": "Kiln Waste at the Lower Terrace",
            "date": "2029",
            "DOI": (
                "\t\r\n \u00a0\u202f\u2007"
                "10.6666/padded-doi"
                "\u2007\u202f\u00a0 \r\n\t"
            ),
        },
        "creators": [("Iva", "Marinova")],
    },
    # In the trash. Zotero keeps the row and lists the item in
    # deletedItems; a duplicate guard that returns it would withhold an
    # import the operator deliberately made room for (round 4d-2).
    {
        "key": "TRASHED1",
        "library_id": 1,
        "deleted": True,
        "fields": {
            "title": "Withdrawn Preprint on Kiln Waste",
            "date": "2028",
            "DOI": "10.7777/deleted-doi",
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

    def test_reader_and_writer_share_one_normaliser(
        self, library: Path
    ) -> None:
        """The importer must reuse zotero.py's rule, not keep a copy.

        Round 4d-2 replaced a vacuous ``__module__ is not None`` here with
        the claim that actually matters: for every accepted spelling of
        every DOI in the library, the reader and the writer return the
        same set of item keys.
        """
        importer = _load_importer()
        zot = load_zotero_module(library)
        assert Path(importer._ZOTERO_CLIENT.__file__).resolve().name == (
            "zotero.py"
        )

        conn = TestWriterFindExistingByDoi._connect(library)
        try:
            for doi in (
                "10.1234/abc-def",
                "https://doi.org/10.1234/ABC-def",
                "doi:10.5555/plain-doi",
                "10.6666/padded-doi",
                "10.7777/deleted-doi",
                "10.9999/absent",
            ):
                reader = sorted(h["key"] for h in zot.find_by_doi(doi))
                writer = sorted(
                    h["key"] for h in importer.find_existing_by_doi(doi, conn)
                )
                assert reader == writer, (doi, reader, writer)
        finally:
            conn.close()


class TestStoredValueEdgeCases:
    """Round 4d-2 — the two stored shapes that were unrepresented.

    ``TRIM`` on the stored side and the ``deletedItems`` exclusion each
    survived deletion in BOTH functions, because no fixture item had
    surrounding whitespace and none was in the trash.
    """

    def test_a_padded_stored_doi_is_matched(self, library: Path) -> None:
        """A DOI pasted with whitespace still counts as a duplicate."""
        zot = load_zotero_module(library)
        importer = _load_importer()
        conn = TestWriterFindExistingByDoi._connect(library)
        try:
            writer = [
                h["key"]
                for h in importer.find_existing_by_doi(
                    "10.6666/padded-doi", conn
                )
            ]
        finally:
            conn.close()

        assert [h["key"] for h in zot.find_by_doi("10.6666/padded-doi")] == [
            "PADDEDD1"
        ]
        assert writer == ["PADDEDD1"]

    def test_a_trashed_item_is_not_a_duplicate(self, library: Path) -> None:
        """An item in the trash must not withhold a deliberate re-import."""
        zot = load_zotero_module(library)
        importer = _load_importer()
        conn = TestWriterFindExistingByDoi._connect(library)
        try:
            writer = importer.find_existing_by_doi("10.7777/deleted-doi", conn)
        finally:
            conn.close()

        assert zot.find_by_doi("10.7777/deleted-doi") == []
        assert writer == []


class TestTheDivergenceCommentIsTrue:
    """L-a — the comment counts characters, so it can go stale silently.

    Round 4d-4 said 24 and claimed the whole U+2000-U+200A run diverges;
    both were true of the set BEFORE U+2007 and U+202F were added in the
    same commit. A comment that states a number should be checkable.
    """

    @staticmethod
    def _shipped_set() -> set[int]:
        """The code points the shipped SQL trim expression actually names."""
        source = (SCRIPTS / "zotero.py").read_text(encoding="utf-8")
        expression = source.split("_SQL_TRIMMED_DOI = (", 1)[1].split(")\n", 1)[0]
        return {int(n) for n in re.findall(r"char\((\d+)\)", expression)}

    @staticmethod
    def _comment() -> str:
        """The paragraph above the expression, as one string."""
        source = (SCRIPTS / "zotero.py").read_text(encoding="utf-8")
        return source.split("#: SQL expression trimming", 1)[1].split(
            "_SQL_TRIMMED_DOI", 1
        )[0]

    def test_every_trimmed_character_is_whitespace(self) -> None:
        """L1 — the trim set may contain nothing but whitespace.

        The count test above only looks at whitespace code points ABSENT
        from the shipped set, so adding a non-whitespace character to the
        expression was invisible to it: ``char(8239) || char(48)`` --
        which strips ASCII "0" off a stored DOI on the SQL side while the
        Python side keeps it -- survived the whole suite. That is not a
        cosmetic divergence; it silently changes which DOIs are considered
        the same, in the direction of false matches.
        """
        shipped = self._shipped_set()
        assert shipped, "no char() entries found in the expression"
        offenders = [
            f"char({c}) = {chr(c)!r}"
            for c in sorted(shipped)
            if not chr(c).isspace()
        ]
        assert offenders == [], (
            "the SQL trim set strips characters Python's str.strip keeps: "
            + ", ".join(offenders)
        )

    def test_the_stated_count_matches_the_shipped_set(self) -> None:
        """Recompute the divergence over the whole of Unicode."""
        shipped = self._shipped_set()
        diverging = [
            c for c in range(0x110000)
            if chr(c).isspace() and c not in shipped
        ]

        stated = re.search(r"(\d+) characters diverge", self._comment())
        assert stated, self._comment()
        assert int(stated.group(1)) == len(diverging), (
            f"comment says {stated.group(1)}, actual {len(diverging)}"
        )

    def test_the_figure_space_is_documented_as_matching(self) -> None:
        """U+2007 is in the expression, so the run has a gap in it."""
        assert 0x2007 in self._shipped_set()
        comment = self._comment()
        assert "U+2000``-``U+2006" in comment, comment
        assert "U+2008``-``U+200A" in comment, comment

    def test_every_character_the_comment_names_really_diverges(self) -> None:
        """Spot-check the named code points against the shipped set."""
        shipped = self._shipped_set()
        for point in (0x0B, 0x0C, 0x1C, 0x1F, 0x85, 0x1680, 0x2009, 0x3000):
            assert chr(point).isspace()
            assert point not in shipped, hex(point)
        for point in (0x20, 0xA0, 0x2007, 0x202F):
            assert point in shipped, hex(point)


if __name__ == "__main__":  # pragma: no cover - convenience entry point
    raise SystemExit(pytest.main([__file__, "-v"]))
