# Zotero Integration Reference

**Read this file when** working with `/read`, `/synthesise`, `/cite`,
`/cite-new`, or any Zotero-related queries.

## Installation

Native install via `zotero-deb` apt repository (moved from snap 2026-04-11).

- **Data directory:** `~/Zotero/`
- **Database:** `~/Zotero/zotero.sqlite`
- **PDF storage:** `~/Zotero/storage/{attachment_key}/{filename}`
- **Query module:** `scripts/zotero.py`

## Database Access

**Always use immutable mode** — Zotero holds a WAL lock while running:

```python
import sqlite3
conn = sqlite3.connect(
    'file:///home/shawn/Zotero/zotero.sqlite?immutable=1', uri=True
)
conn.row_factory = sqlite3.Row
```

**Never write to the SQLite database.** Writes go through the Zotero API
(pyzotero) or are cached in the memory JSONL for later sync.

## Schema Overview (59 tables, 7 key ones)

```text
items (itemID PK, itemTypeID, key, dateAdded, dateModified)
  ├── itemData (itemID, fieldID, valueID) → fields + itemDataValues
  ├── itemCreators (itemID, creatorID, orderIndex) → creators + creatorTypes
  ├── itemAttachments (itemID PK, parentItemID, path, contentType, linkMode)
  ├── itemNotes (itemID PK, parentItemID, note [HTML], title)
  ├── itemTags (itemID, tagID) → tags
  └── collectionItems (collectionID, itemID) → collections
```

## Common JOIN Paths

### Title lookup

```sql
SELECT idv.value AS title
FROM itemData id
JOIN fields f ON id.fieldID = f.fieldID
JOIN itemDataValues idv ON id.valueID = idv.valueID
WHERE id.itemID = ? AND f.fieldName = 'title'
```

### All metadata for an item

```sql
SELECT f.fieldName, idv.value
FROM itemData id
JOIN fields f ON id.fieldID = f.fieldID
JOIN itemDataValues idv ON id.valueID = idv.valueID
WHERE id.itemID = ?
```

### Authors (ordered)

```sql
SELECT c.firstName, c.lastName, ct.creatorType
FROM itemCreators ic
JOIN creators c ON ic.creatorID = c.creatorID
JOIN creatorTypes ct ON ic.creatorTypeID = ct.creatorTypeID
WHERE ic.itemID = ?
ORDER BY ic.orderIndex
```

### PDF path resolution

```sql
SELECT i_att.key AS attachment_key, ia.path
FROM itemAttachments ia
JOIN items i_att ON ia.itemID = i_att.itemID
WHERE ia.parentItemID = ?
  AND ia.contentType = 'application/pdf'
```

Path format: `storage:{filename}` → full path is
`~/Zotero/storage/{attachment_key}/{filename}`

`linkMode`: 0 = imported/stored (in storage/), 1 = linked (external), 2 = snapshot

### Exclude deleted items

Always add: `AND i.itemID NOT IN (SELECT itemID FROM deletedItems)`

### Exclude non-content types

Always add: `AND it.typeName NOT IN ('attachment', 'note')`

## Key Field IDs (from fields table)

| fieldID | fieldName | Notes |
|---------|-----------|-------|
| 1 | title | |
| 2 | abstractNote | |
| 3 | date | Free-form (may be "2024", "2024-03", "March 2024") |
| 4 | DOI | |
| 6 | url | |
| 10 | publisher | |
| 22 | volume | |
| 25 | pages | |
| 35 | issue | |
| 41 | publicationTitle | Journal/book title |
| 67 | issue | (duplicate — check actual DB) |

## Library Statistics (as of 2026-04-11, still syncing)

- 3,763+ items (959 journal articles, 337 newspaper articles, 270 books,
  253 book sections)
- 1,060 PDF attachments in 1,415 storage folders
- 82 collections
- 1,748 items with creators (2,777 unique creators)
- 923 items with tags (1,314 unique tags)
- 435 items with notes

### Top Collections

| Collection | Items |
|-----------|------:|
| primary-sources | 307 |
| Photogrammetry | 120 |
| secondary-sources | 110 |
| JDH_article | 90 |
| AI-LLMs | (check) |
| Abductive-research | (check) |
| Agents | (check) |

## scripts/zotero.py Functions

| Function | Signature | Returns |
|----------|-----------|---------|
| `search_items` | `(query: str, limit=10)` | `list[dict]` — title, abstract, creator search |
| `get_item` | `(item_id_or_key: str\|int)` | `dict\|None` — full metadata |
| `get_pdf_path` | `(item_id: int)` | `Path\|None` — resolved PDF file path |
| `get_notes` | `(item_id: int)` | `list[str]` — HTML-stripped note text |
| `get_collections` | `(item_id: int)` | `list[str]` — collection names |
| `list_collections` | `(min_items=0)` | `list[dict]` — name, id, count |
| `get_collection_items` | `(collection_name: str, limit=100)` | `list[dict]` — items in collection |
| `format_citation` | `(item: dict)` | `str` — "Author (Year) Title" |

Item dict keys: `item_id`, `key`, `type`, `title`, `creators`, `date`,
`abstract`, `doi`, `url`, `publication`, `volume`, `issue`, `pages`,
`publisher`, `tags`, `collections`.

Creator dict keys: `first_name`, `last_name`, `type` (author/editor/etc).

## Integration with Memory System

- `source_insight` memories have optional `zotero_key` field
- `/read` captures insights with the item's 8-char Zotero key
- `/remember` accepts `zotero:KEY` prefix for manual capture
- Insights are pushed to Zotero notes by `sync-to-zotero.py`
- Insights are cached in JSONL (offline-safe) until the sync runs

## Write-Back Sync

`scripts/sync-to-zotero.py` pushes `source_insight` memories to Zotero item
notes via the pyzotero API. Manual invocation only (no cron yet):

```bash
venv/bin/python3 scripts/sync-to-zotero.py [--dry-run] [--limit N] [--verbose]
```

**Key requirements:**

- `pyzotero` library (install: `venv/bin/pip install pyzotero`)
- `ZOTERO_LIBRARY_ID` and `ZOTERO_API_KEY_PAPER_B` env vars (in `.env`).
  The bare `ZOTERO_API_KEY` name was retired 2026-05-22 in favour of the
  target-suffixed `ZOTERO_API_KEY_<TARGET>` convention; this script reads
  the Paper-B-scoped key. See workstream H in `planning/continuity.md`
  for the full convention and the related `ZOTERO_API_KEY_PERSONAL` key
  used by `scripts/lit-scout-zotero-import.py`.
- The memory's `zotero_key` field must contain a valid 8-character
  alphanumeric Zotero item key (pattern `^[A-Z0-9]{8}$`). Memories with
  legacy keys (citation slugs, DOIs, arXiv IDs) are skipped with a warning
  and never touched by the sync
- Notes must go through the API, never direct SQLite writes

**Idempotency:** each note written by the sync includes a footer with the
originating memory ID. Before creating a note, the sync fetches existing
notes on the item and skips any memory that is already present. Safe to
re-run at any time.

**Cursor tracking:** line-based in `memories/sync-cursors.json` (key:
`zotero_sync_line`). The cursor only advances on success; failures cause
retry on the next run.

**Failure handling:**

- Item not found (404) → log + skip, cursor still advances (permanent skip)
- Other errors → log + mark failed, cursor does NOT advance (retry on next run)
- Legacy key format → counted as `skipped_legacy`, cursor advances
