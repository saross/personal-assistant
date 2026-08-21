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

## API Credentials

All write-side Zotero scripts read credentials from `~/personal-assistant/.env`.

### Environment variables

| Name | Purpose | Scope | Read by |
|---|---|---|---|
| `ZOTERO_LIBRARY_ID` | User ID for the personal library | — | personal-library scripts (`add-doi-to-zotero.py`, `lit-scout-zotero-import.py`); `sync-to-zotero.py` only when `ZOTERO_SYNC_LIBRARY_TYPE=user` |
| `ZOTERO_GROUP_ID` | Group library ID (paper-b group `5861859`) | — | `scripts/sync-to-zotero.py` (default target since the 2026-07-24 ruling) |
| `ZOTERO_SYNC_LIBRARY_TYPE` | `group` (default) or `user` — which library `sync-to-zotero.py` writes to | — | `scripts/sync-to-zotero.py` |
| `ZOTERO_API_KEY_PERSONAL` | Personal-library write + all-groups read | broad | `scripts/lit-scout-zotero-import.py` |
| `ZOTERO_API_KEY_PAPER_B` | Personal-library **read-only** (library/files/notes, no write — a personal-library DELETE returns 403); group-library write for `2025-MQ-LLM-DH-software-longevity` (groupID 5861859) only; all-groups read (re-verified via the `/keys/current` endpoint, 2026-07-17) | narrow | `scripts/sync-to-zotero.py` |
| `ZOTERO_STAGING_COLLECTION` | Top-level collection key under My Library where dated subcollections are created (current value: `IX8XR97K` for the `staging` collection) | — | `scripts/lit-scout-zotero-import.py` |
| `ZOTERO_API_KEY_FAIMS` | Personal-library write; group write for `FAIMS-internal` (525489) and `FAIMS-Project` (2542876); all-groups read | narrow | no script yet |
| `ZOTERO_API_KEY_SDAM_AU` | Personal-library write; **group write on `all`** plus explicit write on `SDAM-AU` (2366083); all-groups read. **Caveat (2026-08-21): the `all` write scope does NOT hold in practice — item updates in `Archaeology-reproducibility` (5396607) and `HAVI application` (5940452) returned 403, and `/keys/current` reports `write: False` for `TRAP` (2275173) on this key. Treat this key as SDAM-AU-write only; verify per group with `key_info()` before relying on it. Verified working via their dedicated keys: FAIMS-Project (2542876), group 5861859, and — since 2026-08-21 — TRAP via `ZOTERO_API_KEY_TRAP`.** | **broad** | no script yet |
| `ZOTERO_PAPER_B_COLLECTION` | Collection key `H6KXYXKX` = `Paper-B` (171 items) in **group** 5861859, not My Library | — | no script yet |
| `ZOTERO_SPA_COLLECTION` | Collection key `PZN5ATJK` = `SPA` (61 items) in **group** `SDAM-AU` (2366083) | — | no script yet |
| `ZOTERO_API_KEY_TRAP` | Group write for `TRAP` (2275173); minted 2026-08-21, scope verified via `/keys/current` (`library: True, write: True`) and a live collection create | narrow | no script yet |
| `ZOTERO_TRAP_COLLECTION` | Collection key `BTKV5ZIF` = `vlm-burial-mound-detection` in **group** `TRAP` (2275173) — the map-reader/VLM paper's canonical bibliography collection (created 2026-08-21). **Default-target pointer only, not an access control**: `ZOTERO_API_KEY_TRAP` grants write to the whole TRAP library, every collection included. Other TRAP collections as of 2026-08-21: `TRAP-outputs` `TQT5AAJS`, `LP2019` `IF7J3SQI`, `Oxbow-volume` `SPP4ZUU6`, `Complexity` `HZWI96K9` (snapshot — enumerate live via the API when it matters) | — | no script yet |
| `ZOTERO_TRAP_GROUP_ID` | `2275173` | — | no script yet |
| `ZOTERO_FAIMS_INTERNAL_GROUP_ID` | `525489` | — | no script yet |
| `ZOTERO_FAIMS_PROJECT_GROUP_ID` | `2542876` | — | no script yet |

All key scopes above re-verified against `/keys/current` on 2026-07-27; all
four keys read both the personal library (user 3097511) and group 5861859
successfully. `ZOTERO_API_KEY_PAPER_B` confirmed still personal-read-only
with group-5861859 write, exactly as this table has described it.

### Target-suffixed naming convention (adopted 2026-05-22)

When a workflow needs writes to a specific library or item scope, use a
target-suffixed variable name (`ZOTERO_API_KEY_<TARGET>`) rather than the
bare `ZOTERO_API_KEY`. The bare name was retired 2026-05-22 — any new
script that wants Zotero write access should pick a target suffix matching
its scope. `<TARGET>` is a free-form uppercase identifier (`PERSONAL`,
`PAPER_B`, `FIELDWORK`, etc.) and should be added to the table above when
introduced.

### Bash hyphen trap (read before adding a new key)

Use **underscores**, never hyphens, in env-var names. Writing the literal
form

```bash
ZOTERO_API_KEY_PAPER-B=ak_xxxxxxxxxxxxxx
```

at a bash prompt parses as the command `B=ak_xxxxxxxxxxxxxx` with the
prefix `ZOTERO_API_KEY_PAPER-` treated as a (nonsensical) variable
assignment on a non-existent command. The shell's error message echoes
the offending word, including the key, **into the terminal scrollback and
any logs the shell is being piped into**. This happened once 2026-05-22
during the workstream-H Paper-B key rotation; the leaked key was revoked
and reissued the same day. Always quote the value and double-check the
variable name uses only `[A-Z0-9_]` before pressing Enter.

**It recurred 2026-07-27**, and the `.env` file is the dangerous case
rather than the prompt: `~/.claude/settings.json` sources this file under
`set -a` in two session hooks, so a malformed line is re-parsed — and
re-echoed — on every hook run, not once. Three names were affected
(`ZOTERO_API_KEY_SDAM-AU`, `ZOTERO_FAIMS-internal_GROUP_ID`,
`ZOTERO_FAIMS-Project_GROUP_ID`); all were renamed to underscores. Caught
before any hook fired: a full-content search of `~/.claude`, the sync logs,
`~/cc-archives`, and the canonical rpi-server store found **zero**
occurrences of the affected key's value, so no rotation was needed.

Two lessons worth keeping. **A hyphenated name is invisible to the obvious
audit.** Listing variables with `grep -oE '^[A-Za-z_0-9]+='` silently skips
exactly the malformed lines you are looking for — the first pass over this
file reported 14 clean names and missed all three. Anchor the name character
class on `=`, not on what a valid name should look like:
`grep -oE '^[^=]+='`. **And the parse error is the real detector** — source
the file in a subshell and treat any output as a finding:

```bash
bash -c 'set -a; . ~/personal-assistant/.env; set +a' 2>&1   # must be silent
```

## Write-Back Sync (`sync-to-zotero.py`)

`scripts/sync-to-zotero.py` pushes `source_insight` memories to Zotero
item notes via the pyzotero API. Manual invocation only (no cron yet):

```bash
venv/bin/python3 scripts/sync-to-zotero.py [--dry-run] [--limit N] [--verbose]
```

**Requirements:**

- `pyzotero` library (install: `venv/bin/pip install pyzotero`)
- `ZOTERO_GROUP_ID` and `ZOTERO_API_KEY_PAPER_B` env vars (see
  **API Credentials** above). The script targets the paper-b **group**
  library by default (ruled 2026-07-24 — the target items live there);
  set `ZOTERO_SYNC_LIBRARY_TYPE=user` + `ZOTERO_LIBRARY_ID` to target
  the personal library instead
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

## Lit-scout Staging Import (`lit-scout-zotero-import.py`)

`scripts/lit-scout-zotero-import.py` imports a `/lit-scout-iterate`
workspace's final-iteration findings into a dated subcollection under
`My Library → staging`. Auto-invoked by the `/lit-scout-iterate` driver
on any terminal verdict except `LEGACY_PROPOSER`; also runnable manually:

```bash
venv/bin/python3 scripts/lit-scout-zotero-import.py \
    --workspace /path/to/lit-scout-iterate-YYYYMMDD-HHMMSS/ \
    --query "search query string" \
    [--limit N] [--live]
```

Defaults to `--dry-run`; pass `--live` to actually write to Zotero.

**Requirements:**

- `pyzotero` + `httpx` libraries
- `ZOTERO_LIBRARY_ID`, `ZOTERO_API_KEY_PERSONAL`, `ZOTERO_STAGING_COLLECTION`
  env vars (see **API Credentials** above)
- A `/lit-scout-iterate` workspace containing at least one `iter-N/` with
  a non-empty `claims.jsonl`

**Idempotency:** writes a manifest at `<workspace>/zotero-import-manifest.json`
recording every DOI created, skipped (already in a library), or failed.
Re-runs read the prior manifest and skip already-imported DOIs; the new
`merge_manifest_entries_by_doi` helper dedups `items_skipped` /
`items_failed` by case-insensitive DOI so re-run counts don't inflate.

**Dedup:** before creating an item, queries every local Zotero library
(personal + groups) for the DOI via sqlite. Hits are recorded in
`items_skipped` with full library + collection context. Tolerates common
URL/scheme prefixes on stored DOIs (`https://doi.org/`, `doi:`, etc.).

**Tagging:** every imported item is tagged with `lit-scout-staging`,
`lit-scout-run:<TS>`, `lit-scout-fit:<level>`, `lit-scout-cluster:<slug>`,
plus `lit-scout-unverified:<field>` for any FAIL / PARTIAL / UNVERIFIABLE
verifier claim — so unverified rows are visually distinguishable in the
Zotero UI before the user moves them to a working collection.

**Operational note:** pyzotero embeds the API key as a URL path segment
in `GET /keys/<key>` and dumps it into traceback strings on 403. Exception
output from this script is **not safe** to forward into shared logs
without redaction.

## Write permissions — where a write may land (Shawn's ruling, 2026-08-21)

**Having an API key that *can* write to a shared group library is not
authorisation to use it.** Several keys carry write scope on groups
shared with collaborators; scope is a capability, not a permission.

| Situation | Where it goes |
| --- | --- |
| **New discovery** — an item found by a search, sweep, or agent | **A staging collection in My Library** (personal, `libraryID 1`). Initial writes go here by default, whoever asked for them |
| **Correction to an item in a shared group library** — metadata fix, item-type change, collection move, re-filing | **Ask Shawn first.** Articulate what will change and why; wait for approval |
| **Bulk or agent-driven writes to a shared library** | **Ask first, always.** Volume raises the cost of a wrong call and makes it harder to unpick |

**Why.** Group libraries are shared with collaborators who did not
consent to an automated pass over their records, and a batch correction
is hard to reverse item by item. Discovery is cheap to redo in a staging
collection; a bad write in a shared library is someone else's problem
before it is ours.

**Provenance.** Encoded after the 2026-08-21 Fieldmark session, where an
agent made sixteen metadata corrections in the shared `FAIMS-Project`
group on Claude's instruction rather than Shawn's. The corrections were
sound and each was individually justified, but the pattern was not
authorised: Shawn had approved *populating* two collections, and the
improvement pass was generalised from that. His ruling: *"For
corrections, if it's in a shared library please ask first… we need to
exercise somewhat more caution — clear articulation between us and
approval by me — before modifying shared libraries."* Recorded as
user-obs 23 in `fieldmark-docs-staging`.

**Group IDs are not local library IDs**, and the two are easy to confuse
because both are small integers. Translate explicitly when moving
between the SQLite database and the web API. Verified 2026-08-21:
FAIMS-Project = local library 9 = group **2542876**; SDAM-AU = local 6 =
group **2366083**; FAIMS-internal = local 2 = group **525489**;
TRAP = local 5 = group **2275173**.
