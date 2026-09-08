"""
Synthetic Zotero SQLite fixtures for the test suite.

Several scripts read a *local* Zotero SQLite database directly:
``scripts/zotero.py`` (the read-only query client) and
``scripts/lit-scout-zotero-import.py`` (its duplicate guard). Both promise
the connection is opened immutable and both normalise Digital Object
Identifiers (DOIs) before comparing them. Neither promise can be pinned
against an in-memory database handed to the code by a patched
``_connect`` — the connection URI is exactly the thing under test.

This module therefore builds a *file-backed* database with enough of
Zotero's real schema for those queries to run, and loads a private copy of
``scripts/zotero.py`` whose module-level ``ZOTERO_DATA_DIR`` constant
points at it.

Every name, title, and identifier below is invented. Nothing here is
copied from a real library.
"""

from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

#: Directory holding the scripts under test, resolved from this file so the
#: helper works from any worktree.
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"

#: The subset of Zotero's schema the DOI queries touch. Column order
#: matters: the inserts below are positional, as Zotero's own are.
_SCHEMA = """
    CREATE TABLE libraries (
        libraryID INTEGER PRIMARY KEY,
        type TEXT
    );
    CREATE TABLE groups (
        groupID INTEGER PRIMARY KEY,
        libraryID INTEGER,
        name TEXT
    );
    CREATE TABLE itemTypes (
        itemTypeID INTEGER PRIMARY KEY,
        typeName TEXT
    );
    CREATE TABLE items (
        itemID INTEGER PRIMARY KEY,
        itemTypeID INTEGER,
        libraryID INTEGER,
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

    INSERT INTO libraries VALUES (1, 'user');
    INSERT INTO libraries VALUES (2, 'group');
    INSERT INTO groups VALUES (900, 2, 'Fieldwork Reading Group');

    INSERT INTO itemTypes VALUES (1, 'journalArticle');
    INSERT INTO itemTypes VALUES (2, 'attachment');
    INSERT INTO itemTypes VALUES (3, 'note');
    INSERT INTO itemTypes VALUES (4, 'book');

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

    INSERT INTO creatorTypes VALUES (1, 'author');
    INSERT INTO creatorTypes VALUES (2, 'editor');

    INSERT INTO collections VALUES (1, 'Landscape survey', NULL);
"""

#: Field name → fieldID, mirroring the ``fields`` rows inserted above.
_FIELD_IDS = {
    "title": 1,
    "abstractNote": 2,
    "date": 3,
    "DOI": 4,
    "publicationTitle": 5,
    "url": 6,
    "volume": 7,
    "issue": 8,
    "pages": 9,
    "publisher": 10,
}


def build_zotero_sqlite(
    db_path: Path,
    items: list[dict[str, Any]],
) -> Path:
    """
    Write a synthetic ``zotero.sqlite`` containing ``items``.

    Args:
        db_path: Destination file. Parent directories must already exist.
        items: One dict per item. Recognised keys — ``key`` (the eight-
            character Zotero item key), ``fields`` (field name → value),
            ``library_id`` (1 for the personal library, 2 for the group
            library defined in the schema), ``type_id``, ``deleted``
            (place the item in ``deletedItems``), ``collection_id``, and
            ``creators`` (list of ``(first, last)`` pairs).

    Returns:
        ``db_path``, for convenience at the call site.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_SCHEMA)
        value_id = 0
        creator_id = 0
        for item_id, spec in enumerate(items, start=1):
            conn.execute(
                "INSERT INTO items VALUES (?, ?, ?, ?, ?, ?)",
                (
                    item_id,
                    spec.get("type_id", 1),
                    spec.get("library_id", 1),
                    spec["key"],
                    "2031-01-01",
                    "2031-01-01",
                ),
            )
            for field_name, value in spec.get("fields", {}).items():
                value_id += 1
                conn.execute(
                    "INSERT INTO itemDataValues VALUES (?, ?)",
                    (value_id, value),
                )
                conn.execute(
                    "INSERT INTO itemData VALUES (?, ?, ?)",
                    (item_id, _FIELD_IDS[field_name], value_id),
                )
            for order_index, (first, last) in enumerate(
                spec.get("creators", [])
            ):
                creator_id += 1
                conn.execute(
                    "INSERT INTO creators VALUES (?, ?, ?, 0)",
                    (creator_id, first, last),
                )
                conn.execute(
                    "INSERT INTO itemCreators VALUES (?, ?, 1, ?)",
                    (item_id, creator_id, order_index),
                )
            if spec.get("collection_id"):
                conn.execute(
                    "INSERT INTO collectionItems VALUES (?, ?)",
                    (spec["collection_id"], item_id),
                )
            if spec.get("deleted"):
                conn.execute(
                    "INSERT INTO deletedItems VALUES (?)", (item_id,)
                )
        conn.commit()
    finally:
        conn.close()
    return db_path


def load_zotero_module(data_dir: Path) -> types.ModuleType:
    """
    Load a private copy of ``scripts/zotero.py`` bound to ``data_dir``.

    ``zotero.py`` freezes ``ZOTERO_DATA_DIR`` into a module constant at
    import time, so a test that wants the REAL ``_connect`` to open a
    synthetic database must import the module afresh with the environment
    already pointing at it. The copy is deliberately not registered in
    ``sys.modules`` so the shared ``zotero`` module other tests patch is
    left untouched.

    Args:
        data_dir: Directory containing a ``zotero.sqlite`` file.

    Returns:
        The freshly executed module object.
    """
    spec = importlib.util.spec_from_file_location(
        "zotero_under_test", SCRIPTS_DIR / "zotero.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    previous = os.environ.get("ZOTERO_DATA_DIR")
    os.environ["ZOTERO_DATA_DIR"] = str(data_dir)
    try:
        spec.loader.exec_module(module)
    finally:
        # Restore rather than delete: the ambient value (if any) belongs to
        # whoever set it, and conftest does not pop this variable.
        if previous is None:
            os.environ.pop("ZOTERO_DATA_DIR", None)
        else:
            os.environ["ZOTERO_DATA_DIR"] = previous
    return module


@contextmanager
def scripts_on_path() -> Iterator[None]:
    """Temporarily place ``scripts/`` first on ``sys.path``."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        yield
    finally:
        try:
            sys.path.remove(str(SCRIPTS_DIR))
        except ValueError:  # pragma: no cover - another test removed it
            pass
