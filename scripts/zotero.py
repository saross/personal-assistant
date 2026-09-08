#!/usr/bin/env python3
"""
Read-only Zotero SQLite query client.

Provides functions for searching and retrieving items from a local Zotero
installation. Uses immutable mode to safely read the database while Zotero
is running. Never writes to the database.

The Zotero database uses a normalised schema: item metadata is stored
across items, itemData, itemDataValues, and fields tables. This module
abstracts those JOINs into simple function calls.

Usage:
    from zotero import search_items, get_item, get_pdf_path

    results = search_items("burial mound detection")
    item = get_item("ABC12345")
    pdf = get_pdf_path(item["item_id"])
"""

import html
import logging
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

# ============================================================================
# Configuration
# ============================================================================

ZOTERO_DATA_DIR = Path(
    os.environ.get("ZOTERO_DATA_DIR", str(Path.home() / "Zotero"))
)
ZOTERO_DB = ZOTERO_DATA_DIR / "zotero.sqlite"
ZOTERO_STORAGE = ZOTERO_DATA_DIR / "storage"

logger = logging.getLogger("zotero")


# ============================================================================
# Database Connection
# ============================================================================


def _connect() -> sqlite3.Connection:
    """
    Open an immutable read-only connection to the Zotero SQLite database.

    Uses ``?immutable=1`` to prevent any locking interference with the
    running Zotero application. This means we see a snapshot of the
    database at connection time — changes made by Zotero while we're
    reading are not visible (which is fine for our use case).

    Returns:
        sqlite3.Connection configured for read-only access.

    Raises:
        FileNotFoundError: If the Zotero database does not exist.
    """
    if not ZOTERO_DB.exists():
        raise FileNotFoundError(
            f"Zotero database not found: {ZOTERO_DB}\n"
            f"Set ZOTERO_DATA_DIR environment variable if Zotero data "
            f"is in a non-standard location."
        )

    # Audit round 4d (E24): build the URI with Path.as_uri() rather than
    # f-string concatenation. The old form produced four slashes after
    # "file:" (the path already begins with one) and left the path
    # unencoded, so a ZOTERO_DATA_DIR containing "#" or "?" silently
    # truncated the database path into a fragment or query string and the
    # open failed with a misleading "unable to open database file".
    conn = sqlite3.connect(
        f"{ZOTERO_DB.as_uri()}?immutable=1",
        uri=True,
    )
    conn.row_factory = sqlite3.Row
    return conn


# ============================================================================
# Internal Helpers
# ============================================================================


def _get_field_value(
    cur: sqlite3.Cursor,
    item_id: int,
    field_name: str,
) -> str | None:
    """Fetch a single metadata field value for an item."""
    cur.execute(
        """
        SELECT idv.value
        FROM itemData id
        JOIN fields f ON id.fieldID = f.fieldID
        JOIN itemDataValues idv ON id.valueID = idv.valueID
        WHERE id.itemID = ?
          AND f.fieldName = ?
        """,
        (item_id, field_name),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _get_creators(
    cur: sqlite3.Cursor,
    item_id: int,
) -> list[dict[str, str]]:
    """Fetch all creators (authors, editors, etc.) for an item."""
    cur.execute(
        """
        SELECT c.firstName, c.lastName, ct.creatorType
        FROM itemCreators ic
        JOIN creators c ON ic.creatorID = c.creatorID
        JOIN creatorTypes ct ON ic.creatorTypeID = ct.creatorTypeID
        WHERE ic.itemID = ?
        ORDER BY ic.orderIndex
        """,
        (item_id,),
    )
    return [
        {
            "first_name": row["firstName"] or "",
            "last_name": row["lastName"] or "",
            "type": row["creatorType"],
        }
        for row in cur.fetchall()
    ]


def _get_item_tags(
    cur: sqlite3.Cursor,
    item_id: int,
) -> list[str]:
    """Fetch all tags for an item."""
    cur.execute(
        """
        SELECT t.name
        FROM itemTags it
        JOIN tags t ON it.tagID = t.tagID
        WHERE it.itemID = ?
        ORDER BY t.name
        """,
        (item_id,),
    )
    return [row["name"] for row in cur.fetchall()]


def _get_item_collections(
    cur: sqlite3.Cursor,
    item_id: int,
) -> list[str]:
    """Fetch all collection names for an item."""
    cur.execute(
        """
        SELECT c.collectionName
        FROM collectionItems ci
        JOIN collections c ON ci.collectionID = c.collectionID
        WHERE ci.itemID = ?
        ORDER BY c.collectionName
        """,
        (item_id,),
    )
    return [row["collectionName"] for row in cur.fetchall()]


def _strip_html(text: str) -> str:
    """Strip HTML tags from a string and decode entities."""
    # Remove HTML tags
    clean = re.sub(r"<[^>]+>", "", text)
    # Decode HTML entities
    clean = html.unescape(clean)
    # Collapse whitespace
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def _build_item_dict(
    cur: sqlite3.Cursor,
    item_id: int,
    item_key: str,
    type_name: str,
) -> dict[str, Any]:
    """Build a complete item dictionary from an itemID."""
    creators = _get_creators(cur, item_id)
    tags = _get_item_tags(cur, item_id)
    collections = _get_item_collections(cur, item_id)

    # Fetch common metadata fields
    title = _get_field_value(cur, item_id, "title") or "Untitled"
    abstract = _get_field_value(cur, item_id, "abstractNote") or ""
    date = _get_field_value(cur, item_id, "date") or ""
    doi = _get_field_value(cur, item_id, "DOI") or ""
    url = _get_field_value(cur, item_id, "url") or ""
    publication = _get_field_value(cur, item_id, "publicationTitle") or ""
    volume = _get_field_value(cur, item_id, "volume") or ""
    issue = _get_field_value(cur, item_id, "issue") or ""
    pages = _get_field_value(cur, item_id, "pages") or ""
    publisher = _get_field_value(cur, item_id, "publisher") or ""

    return {
        "item_id": item_id,
        "key": item_key,
        "type": type_name,
        "title": title,
        "creators": creators,
        "date": date,
        "abstract": abstract,
        "doi": doi,
        "url": url,
        "publication": publication,
        "volume": volume,
        "issue": issue,
        "pages": pages,
        "publisher": publisher,
        "tags": tags,
        "collections": collections,
    }


# ============================================================================
# Public API
# ============================================================================


def search_items(
    query: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Search Zotero items by title, abstract, or creator name.

    Performs a case-insensitive LIKE search across title, abstract, and
    creator names. Returns items sorted by relevance (title matches
    first, then abstract, then creator).

    Args:
        query: Search string (supports multiple space-separated terms).
        limit: Maximum results to return.

    Returns:
        List of item dicts with full metadata.
    """
    conn = _connect()
    cur = conn.cursor()

    try:
        # Split query into terms for AND matching
        terms = [t.strip() for t in query.split() if t.strip()]
        if not terms:
            return []

        # Search across title, abstract, and creator names
        # Use UNION to combine matches from different fields
        like_clauses = []
        params: list[str] = []

        for term in terms:
            like_clauses.append(
                "idv_title.value LIKE ?"
            )
            params.append(f"%{term}%")

        title_where = " AND ".join(like_clauses)

        # Title search
        cur.execute(
            f"""
            SELECT DISTINCT
                i.itemID, i.key, it.typeName
            FROM items i
            JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
            JOIN itemData id ON i.itemID = id.itemID
            JOIN fields f ON id.fieldID = f.fieldID
            JOIN itemDataValues idv_title ON id.valueID = idv_title.valueID
            WHERE f.fieldName = 'title'
              AND ({title_where})
              AND it.typeName NOT IN ('attachment', 'note')
              AND i.itemID NOT IN (
                  SELECT itemID FROM deletedItems
              )
            LIMIT ?
            """,
            (*params, limit),
        )
        results = []
        seen_ids: set[int] = set()

        for row in cur.fetchall():
            if row["itemID"] not in seen_ids:
                seen_ids.add(row["itemID"])
                results.append(
                    _build_item_dict(
                        cur, row["itemID"], row["key"], row["typeName"]
                    )
                )

        # If not enough results, also search abstracts
        if len(results) < limit:
            abstract_params: list[str] = []
            abstract_clauses = []
            for term in terms:
                abstract_clauses.append("idv_abs.value LIKE ?")
                abstract_params.append(f"%{term}%")

            abstract_where = " AND ".join(abstract_clauses)

            cur.execute(
                f"""
                SELECT DISTINCT
                    i.itemID, i.key, it.typeName
                FROM items i
                JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
                JOIN itemData id ON i.itemID = id.itemID
                JOIN fields f ON id.fieldID = f.fieldID
                JOIN itemDataValues idv_abs
                    ON id.valueID = idv_abs.valueID
                WHERE f.fieldName = 'abstractNote'
                  AND ({abstract_where})
                  AND it.typeName NOT IN ('attachment', 'note')
                  AND i.itemID NOT IN (
                      SELECT itemID FROM deletedItems
                  )
                LIMIT ?
                """,
                (*abstract_params, limit - len(results)),
            )

            for row in cur.fetchall():
                if row["itemID"] not in seen_ids:
                    seen_ids.add(row["itemID"])
                    results.append(
                        _build_item_dict(
                            cur, row["itemID"], row["key"],
                            row["typeName"],
                        )
                    )

        # If still not enough, search creator names
        if len(results) < limit:
            creator_params: list[str] = []
            creator_clauses = []
            for term in terms:
                creator_clauses.append(
                    "(c.firstName LIKE ? OR c.lastName LIKE ?)"
                )
                creator_params.extend([f"%{term}%", f"%{term}%"])

            creator_where = " AND ".join(creator_clauses)

            cur.execute(
                f"""
                SELECT DISTINCT
                    i.itemID, i.key, it.typeName
                FROM items i
                JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
                JOIN itemCreators ic ON i.itemID = ic.itemID
                JOIN creators c ON ic.creatorID = c.creatorID
                WHERE ({creator_where})
                  AND it.typeName NOT IN ('attachment', 'note')
                  AND i.itemID NOT IN (
                      SELECT itemID FROM deletedItems
                  )
                LIMIT ?
                """,
                (*creator_params, limit - len(results)),
            )

            for row in cur.fetchall():
                if row["itemID"] not in seen_ids:
                    seen_ids.add(row["itemID"])
                    results.append(
                        _build_item_dict(
                            cur, row["itemID"], row["key"],
                            row["typeName"],
                        )
                    )

        return results[:limit]

    finally:
        conn.close()


# Common URL/scheme prefixes that Zotero users sometimes paste in front
# of a bare DOI. Stripped on both sides of the comparison in find_by_doi
# so that e.g. "10.1/abc", "https://doi.org/10.1/abc", and "doi:10.1/abc"
# all match each other. Lowercase form only — comparison is done after
# LOWER() on both sides.
_DOI_URL_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "doi:",
)


def _normalise_doi(doi: str) -> str:
    """Strip URL/scheme prefixes and whitespace; return bare lowercase DOI."""
    s = doi.strip().lower()
    for prefix in _DOI_URL_PREFIXES:
        if s.startswith(prefix):
            return s[len(prefix):]
    return s


#: SQL expression trimming the stored DOI the way Python's ``str.strip``
#: trims the lookup one. SQLite's bare ``TRIM`` removes SPACES only, so a
#: value pasted with a trailing newline — what a copy out of a PDF or a
#: web form leaves — stayed unmatched while the Python side had already
#: stripped it (round 4d-2).
#:
#: The character set is tab, newline, carriage return, space, and
#: non-breaking space. That is NOT the whole of what ``str.strip`` removes
#: (round 4d-3): ``\x0b`` (vertical tab), ``\x0c`` (form feed), and
#: ``\x85`` (next line) are still stripped on the Python side and kept on
#: the SQL side, so a DOI stored with one of those around it would go
#: unmatched. They are vanishingly rare in a pasted identifier, whereas
#: U+00A0 is what a copy out of a rendered web page routinely leaves, so
#: it is worth the character and the others are not worth an unreadable
#: expression. If this ever needs to be exact, normalise on the way in
#: rather than lengthening this list.
_SQL_TRIMMED_DOI = (
    "TRIM(LOWER(idv.value), "
    "char(9) || char(10) || char(13) || char(32) || char(160))"
)


def doi_match_candidates(doi: str) -> list[str]:
    """
    Return every stored spelling of ``doi`` that must count as the same DOI.

    This is the single canonical DOI comparison rule for the repository:
    ``find_by_doi`` below and the duplicate guard in
    ``lit-scout-zotero-import.py`` both call it, so the reader and the
    writer can never disagree about what a duplicate is.

    SQLite has no prefix-strip primitive. Normalising the *stored* side
    with a chained ``REPLACE`` (the previous approach) stripped ``doi:``
    wherever it occurred, not only at the front, so the SQL rule and the
    Python rule disagreed. Expanding the *lookup* side into the bare DOI
    plus every wrapped spelling and comparing with ``IN`` reproduces the
    prefix rule exactly, in both languages.

    Args:
        doi: A DOI in any of the accepted spellings.

    Returns:
        Lowercase candidates: the bare DOI first, then each wrapped form.
        Empty list for a falsy or whitespace-only DOI, so a caller cannot
        turn a missing DOI into a match-everything query.
    """
    bare = _normalise_doi(doi)
    if not bare:
        return []
    return [bare] + [prefix + bare for prefix in _DOI_URL_PREFIXES]


def find_by_doi(doi: str) -> list[dict[str, Any]]:
    """
    Return all items across every local library whose DOI field matches.

    Matching is case-insensitive on the canonical Digital Object
    Identifier (DOI) string and tolerant of common URL/scheme wrappers
    (``https://doi.org/``, ``http://dx.doi.org/``, ``doi:``) on either
    side of the comparison. Designed for proposer-side deduplication
    (lit-scout Phase 5): given a candidate's DOI, return any existing
    Zotero entries so the proposer can flag them as [IN ZOTERO] without
    relying on title/creator text matching.

    Falsy or whitespace-only ``doi`` returns an empty list — callers
    should fall back to ``search_items`` for DOI-less candidates.

    Returns:
        List of item dicts from ``_build_item_dict``, augmented with a
        ``library_name`` field whose value is either the literal string
        ``"My Library"`` (for items in the user's personal library) or
        the Zotero group name (for items in a group library). Empty
        list if no match (item is NEW).

    Comparison with proposer's pre-2026-05-23 ``search_items`` flow:
    a 2026-05-22 smoke test (n=35) caught 2/5 actual duplicates via
    text search vs 5/5 via this DOI-based query. See workstream H in
    wiki/continuity.md.
    """
    candidates = doi_match_candidates(doi)
    if not candidates:
        return []

    conn = _connect()
    cur = conn.cursor()

    try:
        # The DOI field can be stored bare or wrapped in any of the
        # URL/scheme prefixes in _DOI_URL_PREFIXES. Compare the stored
        # value against every accepted spelling of the lookup DOI rather
        # than trying to strip prefixes in SQL — see doi_match_candidates.
        placeholders = ", ".join("?" for _ in candidates)
        cur.execute(
            f"""
            SELECT DISTINCT
                i.itemID, i.key, it.typeName,
                COALESCE(g.name, 'My Library') AS library_name
            FROM items i
            JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
            JOIN itemData id ON i.itemID = id.itemID
            JOIN fields f ON id.fieldID = f.fieldID
            JOIN itemDataValues idv ON id.valueID = idv.valueID
            JOIN libraries l ON i.libraryID = l.libraryID
            LEFT JOIN groups g ON l.libraryID = g.libraryID
            WHERE f.fieldName = 'DOI'
              AND {_SQL_TRIMMED_DOI} IN ({placeholders})
              AND it.typeName NOT IN ('attachment', 'note')
              AND i.itemID NOT IN (
                  SELECT itemID FROM deletedItems
              )
            """,
            tuple(candidates),
        )

        results = []
        for row in cur.fetchall():
            item = _build_item_dict(
                cur, row["itemID"], row["key"], row["typeName"]
            )
            item["library_name"] = row["library_name"]
            results.append(item)

        return results

    finally:
        conn.close()


def get_item(item_id_or_key: str | int) -> dict[str, Any] | None:
    """
    Retrieve full metadata for a single Zotero item.

    Accepts either a numeric itemID or an alphanumeric item key.

    Args:
        item_id_or_key: Zotero itemID (int) or item key (str).

    Returns:
        Item dict with full metadata, or None if not found.
    """
    conn = _connect()
    cur = conn.cursor()

    try:
        if isinstance(item_id_or_key, int):
            cur.execute(
                """
                SELECT i.itemID, i.key, it.typeName
                FROM items i
                JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
                WHERE i.itemID = ?
                """,
                (item_id_or_key,),
            )
        else:
            cur.execute(
                """
                SELECT i.itemID, i.key, it.typeName
                FROM items i
                JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
                WHERE i.key = ?
                """,
                (str(item_id_or_key),),
            )

        row = cur.fetchone()
        if not row:
            return None

        return _build_item_dict(
            cur, row["itemID"], row["key"], row["typeName"]
        )

    finally:
        conn.close()


def get_pdf_path(item_id: int) -> Path | None:
    """
    Find the PDF file path for a Zotero item.

    Looks for PDF attachments linked to the item. Zotero stores files
    in ``storage/{attachment_key}/{filename}`` with the path field
    formatted as ``storage:{filename}``.

    Args:
        item_id: Zotero itemID of the parent item.

    Returns:
        Path to the PDF file, or None if no PDF is attached or the
        file doesn't exist on disk.
    """
    conn = _connect()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT ia.itemID, i_att.key, ia.path
            FROM itemAttachments ia
            JOIN items i_att ON ia.itemID = i_att.itemID
            WHERE ia.parentItemID = ?
              AND ia.contentType = 'application/pdf'
            ORDER BY ia.itemID
            """,
            (item_id,),
        )

        for row in cur.fetchall():
            path_str = row["path"] or ""
            attachment_key = row["key"]

            if path_str.startswith("storage:"):
                filename = path_str[len("storage:"):]
                full_path = ZOTERO_STORAGE / attachment_key / filename
                if full_path.exists():
                    return full_path

        return None

    finally:
        conn.close()


def get_notes(item_id: int) -> list[str]:
    """
    Retrieve notes attached to a Zotero item.

    Notes are stored as HTML in Zotero. This function strips HTML tags
    and returns plain text.

    Args:
        item_id: Zotero itemID of the parent item.

    Returns:
        List of note text strings (HTML stripped).
    """
    conn = _connect()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT note
            FROM itemNotes
            WHERE parentItemID = ?
            ORDER BY itemID
            """,
            (item_id,),
        )
        return [
            _strip_html(row["note"])
            for row in cur.fetchall()
            if row["note"]
        ]

    finally:
        conn.close()


def get_collections(item_id: int) -> list[str]:
    """
    Get collection names for a Zotero item.

    Convenience wrapper — same as item["collections"] from get_item(),
    but callable without loading full metadata.

    Args:
        item_id: Zotero itemID.

    Returns:
        List of collection name strings.
    """
    conn = _connect()
    cur = conn.cursor()

    try:
        return _get_item_collections(cur, item_id)
    finally:
        conn.close()


def list_collections(
    min_items: int = 0,
) -> list[dict[str, Any]]:
    """
    List all Zotero collections with item counts.

    Args:
        min_items: Only return collections with at least this many items.

    Returns:
        List of dicts with ``name``, ``collection_id``, and ``count``.
    """
    conn = _connect()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT c.collectionID, c.collectionName,
                   COUNT(ci.itemID) as item_count
            FROM collections c
            LEFT JOIN collectionItems ci
                ON c.collectionID = ci.collectionID
            GROUP BY c.collectionID, c.collectionName
            HAVING COUNT(ci.itemID) >= ?
            ORDER BY c.collectionName
            """,
            (min_items,),
        )
        return [
            {
                "collection_id": row["collectionID"],
                "name": row["collectionName"],
                "count": row["item_count"],
            }
            for row in cur.fetchall()
        ]

    finally:
        conn.close()


def get_collection_items(
    collection_name: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    Retrieve all items in a named Zotero collection.

    Args:
        collection_name: Exact collection name (case-sensitive).
        limit: Maximum items to return.

    Returns:
        List of item dicts with full metadata.
    """
    conn = _connect()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT DISTINCT
                i.itemID, i.key, it.typeName
            FROM items i
            JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
            JOIN collectionItems ci ON i.itemID = ci.itemID
            JOIN collections c ON ci.collectionID = c.collectionID
            WHERE c.collectionName = ?
              AND it.typeName NOT IN ('attachment', 'note')
              AND i.itemID NOT IN (
                  SELECT itemID FROM deletedItems
              )
            LIMIT ?
            """,
            (collection_name, limit),
        )

        return [
            _build_item_dict(
                cur, row["itemID"], row["key"], row["typeName"]
            )
            for row in cur.fetchall()
        ]

    finally:
        conn.close()


def format_citation(item: dict[str, Any]) -> str:
    """
    Format an item as a short citation string.

    Produces "Author et al. (Year) Title" format. For single authors,
    uses "Author (Year) Title". For two authors, "Author & Author (Year)".

    Args:
        item: Item dict from search_items() or get_item().

    Returns:
        Formatted citation string.
    """
    creators = item.get("creators", [])
    authors = [c for c in creators if c["type"] == "author"]
    if not authors:
        authors = creators  # Use whatever creator type exists

    if not authors:
        author_str = "Unknown"
    elif len(authors) == 1:
        author_str = authors[0]["last_name"]
    elif len(authors) == 2:
        author_str = (
            f"{authors[0]['last_name']} & {authors[1]['last_name']}"
        )
    else:
        author_str = f"{authors[0]['last_name']} et al."

    # `_build_item_dict` always supplies a "date" key, empty when the item
    # has no date, so the dict default never fires. Audit round 4d (E12):
    # test the VALUE, or a dateless item renders as "Smith () A study".
    year = item.get("date") or "n.d."
    # Extract just the year if date is longer
    year_match = re.search(r"\d{4}", year)
    if year_match:
        year = year_match.group(0)

    title = item.get("title", "Untitled")
    return f"{author_str} ({year}) {title}"
