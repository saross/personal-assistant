# Zotero Integration + Research Commands

## Context

Local Zotero installation at `~/Zotero/` with 3,763+ items, 1,060 PDFs, 82
collections. SQLite database queryable in immutable read-only mode. Combined
with the semantic memory search (just built) and PDF skill (existing), this
enables structured research commands that connect papers to accumulated context.

Write-back to Zotero uses the pyzotero API (offline-safe: insights cached in
memory JSONL until network available).

## Phase 1: Zotero Query Module (foundation)

### `scripts/zotero.py` — Read-only Zotero SQLite client

Shared module imported by all research commands.

```python
ZOTERO_DATA_DIR = Path.home() / "Zotero"
ZOTERO_DB = ZOTERO_DATA_DIR / "zotero.sqlite"
ZOTERO_STORAGE = ZOTERO_DATA_DIR / "storage"
```

Functions:

- `search_items(query, limit=10) → list[dict]` — FTS across title, abstract,
  creator names. Returns items with full metadata.
- `get_item(item_id_or_key) → dict` — Full metadata for one item (title,
  authors, date, abstract, DOI, publication, collections, tags).
- `get_pdf_path(item_id) → Path | None` — Resolve storage path for a PDF
  attachment. Pattern: `storage/{attachment_key}/{filename}`.
- `get_notes(item_id) → list[str]` — HTML notes stripped to plain text.
- `get_collections(item_id) → list[str]` — Collection names for an item.
- `list_collections() → list[dict]` — All collections with item counts.
- `get_collection_items(collection_name) → list[dict]` — Items in a collection.
- `format_citation(item) → str` — "Author et al. (Year) Title" one-liner.

All functions use immutable SQLite connection. Return None/empty on failure.

Key schema paths (verified against actual database):
- Title: `items → itemData → fields(fieldName='title') → itemDataValues`
- Authors: `items → itemCreators → creators` (ordered by orderIndex)
- PDF: `items → itemAttachments(contentType='application/pdf')` → path
  is `storage:{filename}`, full path is `storage/{attachment.key}/{filename}`
- Collections: `items → collectionItems → collections`
- Tags: `items → itemTags → tags`
- Notes: `itemNotes(parentItemID=item.itemID)` — HTML content

### `tests/test_zotero.py` — Unit tests with mock SQLite

Test against a small in-memory SQLite database mimicking Zotero's schema.
No dependency on actual Zotero installation.

## Phase 2: Research Commands

### `commands/read.md` — `/read [query]`

Structured paper reading with insight capture.

1. **Search** — query Zotero by title/author/key via `zotero.search_items()`
2. **Select** — if multiple matches, present options
3. **Load** — fetch metadata, find PDF, check for existing `source_insight`
   memories with matching `zotero_key`
4. **Present overview** — title, authors, year, abstract, collections, tags,
   plus any prior insights from memory system
5. **Establish reading goal** — "What question are you bringing to this source?"
6. **Read** — if PDF exists, use the `pdf` skill to read relevant sections
7. **Capture insights** — at stopping points, offer to save `source_insight`
   memories with `zotero_key` set

### `commands/synthesise.md` — `/synthesise [topic or collection]`

Two modes:
- **Topic mode** (`/synthesise mound detection`): semantic search across
  memories, structured thematic synthesis of accumulated knowledge
- **Collection mode** (`/synthesise collection:AI-LLMs`): load all items
  from a Zotero collection, synthesise across abstracts + any existing
  `source_insight` memories

Output: Markdown synthesis structured by theme, with citations.

### `commands/cite.md` — `/cite [query]`

Quick citation lookup. Search Zotero, return formatted citation(s).

## Phase 3: Write-Back Sync (deferred)

### `scripts/sync-to-zotero.py`

Push `source_insight` memories back to Zotero item notes via pyzotero API.
Cursor-tracked (same pattern as sync-to-postgres.py). Offline-safe: insights
live in JSONL until sync runs.

**Not building today** — the read direction is the immediate value. Write-back
is a separate session once the read commands are validated.

## Files to Create

| File | Phase | Description |
|------|-------|-------------|
| `scripts/zotero.py` | 1 | Read-only Zotero SQLite query module |
| `tests/test_zotero.py` | 1 | Unit tests with mock SQLite |
| `commands/read.md` | 2 | /read structured reading command |
| `commands/synthesise.md` | 2 | /synthesise thematic synthesis command |
| `commands/cite.md` | 2 | /cite quick citation lookup |

## Files to Modify

None — all new files. Existing commands symlinked via setup.sh.

## Verification

1. `python3 -c "from scripts.zotero import search_items; print(search_items('burial mound'))"` — search works
2. `python3 -c "from scripts.zotero import get_pdf_path; ..."` — PDF resolution works
3. `/read Ross 2024 mound` — finds paper, presents overview, reads PDF
4. `/synthesise mound detection` — produces thematic synthesis from memories
5. `/synthesise collection:AI-LLMs` — synthesises across Zotero collection
6. `/cite sobotkova burial` — returns formatted citation
7. Full test suite passes

## Execution Order

1. Build `scripts/zotero.py` + tests (foundation)
2. Build `/read` command (highest research value)
3. Build `/synthesise` command (next highest)
4. Build `/cite` command (quick addition)
5. Symlink new commands to `~/.claude/commands/`
6. Test end-to-end
7. Run `/audit` on all new files
