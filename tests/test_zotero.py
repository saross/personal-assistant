"""Tests for scripts/zotero.py — Zotero SQLite query client."""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import zotero


# ============================================================================
# Fixtures — Mock Zotero Database
# ============================================================================


def _create_mock_db() -> sqlite3.Connection:
    """Create an in-memory SQLite database mimicking Zotero's schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Core tables
    cur.executescript("""
        CREATE TABLE itemTypes (
            itemTypeID INTEGER PRIMARY KEY,
            typeName TEXT
        );
        CREATE TABLE items (
            itemID INTEGER PRIMARY KEY,
            itemTypeID INTEGER,
            key TEXT UNIQUE,
            dateAdded TEXT,
            dateModified TEXT
        );
        CREATE TABLE fields (
            fieldID INTEGER PRIMARY KEY,
            fieldName TEXT
        );
        CREATE TABLE itemDataValues (
            valueID INTEGER PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE itemData (
            itemID INTEGER,
            fieldID INTEGER,
            valueID INTEGER,
            PRIMARY KEY (itemID, fieldID)
        );
        CREATE TABLE creatorTypes (
            creatorTypeID INTEGER PRIMARY KEY,
            creatorType TEXT
        );
        CREATE TABLE creators (
            creatorID INTEGER PRIMARY KEY,
            firstName TEXT,
            lastName TEXT,
            fieldMode INTEGER
        );
        CREATE TABLE itemCreators (
            itemID INTEGER,
            creatorID INTEGER,
            creatorTypeID INTEGER,
            orderIndex INTEGER,
            PRIMARY KEY (itemID, creatorID, creatorTypeID)
        );
        CREATE TABLE itemAttachments (
            itemID INTEGER PRIMARY KEY,
            parentItemID INTEGER,
            path TEXT,
            contentType TEXT,
            linkMode INTEGER
        );
        CREATE TABLE collections (
            collectionID INTEGER PRIMARY KEY,
            collectionName TEXT,
            parentCollectionID INTEGER
        );
        CREATE TABLE collectionItems (
            collectionID INTEGER,
            itemID INTEGER,
            PRIMARY KEY (collectionID, itemID)
        );
        CREATE TABLE tags (
            tagID INTEGER PRIMARY KEY,
            name TEXT
        );
        CREATE TABLE itemTags (
            itemID INTEGER,
            tagID INTEGER,
            type INTEGER DEFAULT 0,
            PRIMARY KEY (itemID, tagID)
        );
        CREATE TABLE itemNotes (
            itemID INTEGER PRIMARY KEY,
            parentItemID INTEGER,
            note TEXT,
            title TEXT
        );
        CREATE TABLE deletedItems (
            itemID INTEGER PRIMARY KEY
        );

        -- Item types
        INSERT INTO itemTypes VALUES (1, 'journalArticle');
        INSERT INTO itemTypes VALUES (2, 'attachment');
        INSERT INTO itemTypes VALUES (3, 'note');
        INSERT INTO itemTypes VALUES (4, 'book');

        -- Fields
        INSERT INTO fields VALUES (1, 'title');
        INSERT INTO fields VALUES (2, 'abstractNote');
        INSERT INTO fields VALUES (3, 'date');
        INSERT INTO fields VALUES (4, 'DOI');
        INSERT INTO fields VALUES (5, 'publicationTitle');
        INSERT INTO fields VALUES (6, 'url');
        INSERT INTO fields VALUES (7, 'volume');
        INSERT INTO fields VALUES (8, 'issue');
        INSERT INTO fields VALUES (9, 'pages');
        INSERT INTO fields VALUES (10, 'publisher');

        -- Creator types
        INSERT INTO creatorTypes VALUES (1, 'author');
        INSERT INTO creatorTypes VALUES (2, 'editor');

        -- Item 1: journal article with PDF
        INSERT INTO items VALUES (1, 1, 'ABC12345', '2024-01-01', '2024-06-15');
        INSERT INTO itemDataValues VALUES (1, 'Burial Mound Detection Using Machine Learning');
        INSERT INTO itemDataValues VALUES (2, 'We present a novel approach to detecting burial mounds in satellite imagery.');
        INSERT INTO itemDataValues VALUES (3, '2024');
        INSERT INTO itemDataValues VALUES (4, '10.1234/test.2024');
        INSERT INTO itemDataValues VALUES (5, 'Journal of Archaeological Science');
        INSERT INTO itemData VALUES (1, 1, 1);
        INSERT INTO itemData VALUES (1, 2, 2);
        INSERT INTO itemData VALUES (1, 3, 3);
        INSERT INTO itemData VALUES (1, 4, 4);
        INSERT INTO itemData VALUES (1, 5, 5);

        INSERT INTO creators VALUES (1, 'Adela', 'Sobotkova', 0);
        INSERT INTO creators VALUES (2, 'Shawn', 'Ross', 0);
        INSERT INTO itemCreators VALUES (1, 1, 1, 0);
        INSERT INTO itemCreators VALUES (1, 2, 1, 1);

        -- Attachment for item 1
        INSERT INTO items VALUES (10, 2, 'PDF1KEY1', '2024-01-01', '2024-01-01');
        INSERT INTO itemAttachments VALUES (10, 1, 'storage:Sobotkova2024.pdf', 'application/pdf', 0);

        -- Collection
        INSERT INTO collections VALUES (1, 'ML-Archaeology', NULL);
        INSERT INTO collectionItems VALUES (1, 1);

        -- Tags
        INSERT INTO tags VALUES (1, 'machine-learning');
        INSERT INTO tags VALUES (2, 'archaeology');
        INSERT INTO itemTags VALUES (1, 1, 0);
        INSERT INTO itemTags VALUES (1, 2, 0);

        -- Note
        INSERT INTO items VALUES (11, 3, 'NOTE0001', '2024-02-01', '2024-02-01');
        INSERT INTO itemNotes VALUES (11, 1, '<p>Key finding: <strong>90% accuracy</strong> on test set.</p>', 'Results note');

        -- Item 2: book (no PDF)
        INSERT INTO items VALUES (2, 4, 'DEF67890', '2020-01-01', '2020-01-01');
        INSERT INTO itemDataValues VALUES (6, 'Archaeological Survey Methods');
        INSERT INTO itemDataValues VALUES (7, '2020');
        INSERT INTO itemDataValues VALUES (8, 'Academic Press');
        INSERT INTO itemData VALUES (2, 1, 6);
        INSERT INTO itemData VALUES (2, 3, 7);
        INSERT INTO itemData VALUES (2, 10, 8);

        INSERT INTO creators VALUES (3, 'James', 'Smith', 0);
        INSERT INTO itemCreators VALUES (2, 3, 1, 0);

        -- Item 3: deleted item (should be excluded)
        INSERT INTO items VALUES (3, 1, 'DEL00001', '2024-01-01', '2024-01-01');
        INSERT INTO itemDataValues VALUES (9, 'Deleted Paper About Mounds');
        INSERT INTO itemData VALUES (3, 1, 9);
        INSERT INTO deletedItems VALUES (3);
    """)

    return conn


@pytest.fixture(autouse=True)
def patch_connect():
    """Patch _connect to return a fresh mock database each call."""
    def _factory():
        return _create_mock_db()

    with patch.object(zotero, "_connect", side_effect=_factory):
        yield


# ============================================================================
# Tests — search_items
# ============================================================================


class TestSearchItems:
    """Tests for Zotero item search."""

    def test_finds_by_title(self) -> None:
        """Should find items matching title keywords."""
        results = zotero.search_items("burial mound")
        assert len(results) >= 1
        assert results[0]["title"] == "Burial Mound Detection Using Machine Learning"

    def test_excludes_deleted_items(self) -> None:
        """Should not return items in deletedItems table."""
        results = zotero.search_items("Deleted Paper")
        assert len(results) == 0

    def test_excludes_attachments_and_notes(self) -> None:
        """Should not return attachment or note item types."""
        results = zotero.search_items("Sobotkova")
        for r in results:
            assert r["type"] not in ("attachment", "note")

    def test_returns_full_metadata(self) -> None:
        """Should include creators, tags, collections in results."""
        results = zotero.search_items("burial")
        assert len(results) >= 1
        item = results[0]
        assert len(item["creators"]) == 2
        assert item["creators"][0]["last_name"] == "Sobotkova"
        assert "machine-learning" in item["tags"]
        assert "ML-Archaeology" in item["collections"]

    def test_empty_query_returns_empty(self) -> None:
        """Should return empty list for empty query."""
        assert zotero.search_items("") == []
        assert zotero.search_items("   ") == []

    def test_no_matches_returns_empty(self) -> None:
        """Should return empty list when nothing matches."""
        assert zotero.search_items("zzzznonexistent") == []


# ============================================================================
# Tests — get_item
# ============================================================================


class TestGetItem:
    """Tests for single item retrieval."""

    def test_get_by_key(self) -> None:
        """Should retrieve item by alphanumeric key."""
        item = zotero.get_item("ABC12345")
        assert item is not None
        assert item["title"] == "Burial Mound Detection Using Machine Learning"

    def test_get_by_id(self) -> None:
        """Should retrieve item by numeric ID."""
        item = zotero.get_item(1)
        assert item is not None
        assert item["key"] == "ABC12345"

    def test_not_found_returns_none(self) -> None:
        """Should return None for nonexistent key."""
        assert zotero.get_item("ZZZZZZZZ") is None
        assert zotero.get_item(99999) is None


# ============================================================================
# Tests — get_pdf_path
# ============================================================================


class TestGetPdfPath:
    """Tests for PDF path resolution."""

    def test_finds_pdf(self, tmp_path: Path) -> None:
        """Should resolve PDF path when file exists."""
        # Create the expected file
        pdf_dir = tmp_path / "PDF1KEY1"
        pdf_dir.mkdir()
        pdf_file = pdf_dir / "Sobotkova2024.pdf"
        pdf_file.write_text("fake pdf")

        with patch.object(zotero, "ZOTERO_STORAGE", tmp_path):
            path = zotero.get_pdf_path(1)
        assert path is not None
        assert path.name == "Sobotkova2024.pdf"

    def test_returns_none_when_no_attachment(self) -> None:
        """Should return None for items without PDF attachments."""
        assert zotero.get_pdf_path(2) is None

    def test_returns_none_when_file_missing(self) -> None:
        """Should return None if attachment record exists but file doesn't."""
        with patch.object(zotero, "ZOTERO_STORAGE", Path("/nonexistent")):
            assert zotero.get_pdf_path(1) is None


# ============================================================================
# Tests — get_notes
# ============================================================================


class TestGetNotes:
    """Tests for note retrieval."""

    def test_strips_html(self) -> None:
        """Should return plain text with HTML stripped."""
        notes = zotero.get_notes(1)
        assert len(notes) == 1
        assert "90% accuracy" in notes[0]
        assert "<p>" not in notes[0]
        assert "<strong>" not in notes[0]

    def test_no_notes_returns_empty(self) -> None:
        """Should return empty list for items without notes."""
        assert zotero.get_notes(2) == []


# ============================================================================
# Tests — collections
# ============================================================================


class TestCollections:
    """Tests for collection operations."""

    def test_list_collections(self) -> None:
        """Should list all collections with counts."""
        colls = zotero.list_collections()
        assert len(colls) >= 1
        ml = [c for c in colls if c["name"] == "ML-Archaeology"]
        assert len(ml) == 1
        assert ml[0]["count"] == 1

    def test_get_collection_items(self) -> None:
        """Should return items in a collection."""
        items = zotero.get_collection_items("ML-Archaeology")
        assert len(items) == 1
        assert items[0]["title"] == "Burial Mound Detection Using Machine Learning"

    def test_empty_collection(self) -> None:
        """Should return empty list for nonexistent collection."""
        assert zotero.get_collection_items("Nonexistent") == []


# ============================================================================
# Tests — format_citation
# ============================================================================


class TestFormatCitation:
    """Tests for citation formatting."""

    def test_two_authors(self) -> None:
        """Should format as 'Author & Author (Year) Title'."""
        item = zotero.get_item("ABC12345")
        citation = zotero.format_citation(item)
        assert "Sobotkova & Ross" in citation
        assert "2024" in citation
        assert "Burial Mound" in citation

    def test_single_author(self) -> None:
        """Should format as 'Author (Year) Title'."""
        item = zotero.get_item("DEF67890")
        citation = zotero.format_citation(item)
        assert "Smith" in citation
        assert "2020" in citation

    def test_no_creators(self) -> None:
        """Should use 'Unknown' when no creators."""
        item = {"creators": [], "date": "2024", "title": "Test"}
        assert zotero.format_citation(item).startswith("Unknown")


# ============================================================================
# ET3 / E24 / E12 — the real _connect, the real URI, and the n.d. fallback
#
# Every test above runs against an in-memory database handed in by the
# autouse ``patch_connect`` fixture, so the module's central promise — the
# connection is immutable, and can therefore never interfere with a running
# Zotero — was itself untested: replacing ``_connect`` with a plain
# read-write ``sqlite3.connect`` left the suite green (lens B, tranche 5,
# finding 3). The tests below load a private copy of the module bound to a
# synthetic on-disk library, so the REAL ``_connect`` runs.
# ============================================================================

import socket as _socket

from zotero_sqlite_fixture import build_zotero_sqlite, load_zotero_module




#: One invented item, enough for a connection and a lookup.
_SYNTHETIC_LIBRARY = [
    {
        "key": "SYNTH001",
        "fields": {
            "title": "Chert Sourcing in the Struma Corridor",
            "date": "2031",
            "DOI": "10.2222/synthetic-one",
        },
        "creators": [("Iva", "Marinova")],
    }
]


def _synthetic_data_dir(parent: Path, name: str = "ZoteroSynthetic") -> Path:
    """Build a Zotero data directory called ``name`` under ``parent``."""
    data_dir = parent / name
    data_dir.mkdir(parents=True)
    build_zotero_sqlite(data_dir / "zotero.sqlite", _SYNTHETIC_LIBRARY)
    return data_dir


class TestConnectIsImmutable:
    """ET3 — the read-only promise, exercised through the real _connect."""

    def test_a_write_through_the_connection_fails(self, tmp_path) -> None:
        """An INSERT must be rejected, not merely discouraged by comment."""
        zot = load_zotero_module(_synthetic_data_dir(tmp_path))
        conn = zot._connect()
        try:
            with pytest.raises(sqlite3.OperationalError):
                conn.execute(
                    "INSERT INTO itemDataValues VALUES (9999, 'injected')"
                )
        finally:
            conn.close()

    def test_reads_still_work(self, tmp_path) -> None:
        """The immutable connection is still a usable reader."""
        zot = load_zotero_module(_synthetic_data_dir(tmp_path))
        results = zot.search_items("Chert Sourcing")
        assert [r["key"] for r in results] == ["SYNTH001"]

    def test_the_uri_is_well_formed(self, tmp_path) -> None:
        """Three slashes after ``file:``, and the immutable flag present."""
        data_dir = _synthetic_data_dir(tmp_path)
        zot = load_zotero_module(data_dir)
        captured: list[str] = []
        real_connect = sqlite3.connect

        def _record(target, *args, **kwargs):
            captured.append(str(target))
            return real_connect(target, *args, **kwargs)

        with patch.object(zot.sqlite3, "connect", _record):
            zot._connect().close()

        assert captured, "the module did not open a connection"
        uri = captured[0]
        assert uri.startswith("file:///"), uri
        assert not uri.startswith("file:////"), uri
        assert uri.endswith("?immutable=1"), uri

    def test_awkward_characters_in_the_data_dir_are_encoded(
        self, tmp_path
    ) -> None:
        """E24 — a '#' or '?' in the path must not truncate the URI."""
        data_dir = _synthetic_data_dir(tmp_path, "Zotero #1 (what?)")
        zot = load_zotero_module(data_dir)
        conn = zot._connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM items"
            ).fetchone()
        finally:
            conn.close()
        assert row[0] == len(_SYNTHETIC_LIBRARY)

    def test_a_missing_database_raises_file_not_found(self, tmp_path) -> None:
        """The absent-database branch is a clear error, not a create."""
        empty = tmp_path / "NoZoteroHere"
        empty.mkdir()
        zot = load_zotero_module(empty)
        with pytest.raises(FileNotFoundError):
            zot._connect()
        assert not (empty / "zotero.sqlite").exists(), (
            "the connection attempt created a database file"
        )


class TestCitationWithoutADate:
    """E12 — a dateless item must render "n.d.", not an empty bracket."""

    def test_empty_date_renders_n_d(self) -> None:
        """``_build_item_dict`` supplies "" for a dateless item."""
        item = {
            "creators": [
                {
                    "first_name": "Iva",
                    "last_name": "Marinova",
                    "type": "author",
                }
            ],
            "date": "",
            "title": "A Study Without a Date",
        }
        assert zotero.format_citation(item) == (
            "Marinova (n.d.) A Study Without a Date"
        )

    def test_a_real_dateless_item_renders_n_d(self, tmp_path) -> None:
        """The same, built through the real code path rather than by hand."""
        data_dir = tmp_path / "ZoteroNoDate"
        data_dir.mkdir()
        build_zotero_sqlite(
            data_dir / "zotero.sqlite",
            [
                {
                    "key": "NODATE01",
                    "fields": {"title": "Undated Survey Notes"},
                    "creators": [("Iva", "Marinova")],
                }
            ],
        )
        zot = load_zotero_module(data_dir)
        item = zot.get_item("NODATE01")
        assert zot.format_citation(item) == (
            "Marinova (n.d.) Undated Survey Notes"
        )
