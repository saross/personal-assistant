# /read — Structured Paper Reading

Deep reading session with a Zotero paper, guided by a specific question.
Captures `source_insight` memories with Zotero key for future retrieval.

## Usage

```text
/read [search query]
/read key:[zotero-key]
```

## Arguments

- `[search query]` — Free-text search across titles, abstracts, and author names
  in the local Zotero database
- `key:[zotero-key]` — Direct lookup by Zotero item key (the 8-character identifier)

## Behaviour

### 1. Search Zotero

Run the search against the local Zotero SQLite database (read-only, immutable mode).

```python
import sys
sys.path.insert(0, "scripts")
from zotero import search_items, get_item, get_pdf_path, get_notes, format_citation
```

- **If query starts with `key:`**: use `get_item(key)` for direct lookup
- **Otherwise**: use `search_items(query)` to search title, abstract, creators

**If multiple matches** (more than 1), present a numbered list:

```text
Found N items matching "[query]":

1. Sobotkova & Ross (2024) Validating Predictions of Burial Mounds...
   Journal of Archaeological Science | Collections: Articles
2. Eftimoski et al. (2017) The impact of land use and depopulation...
   Bulgarian e-Journal of Archaeology | Collections: ML-Archaeology

Which item? (enter number, or refine your search)
```

**If exactly one match**, proceed directly.
**If no matches**, say so and suggest refining the search.

### 2. Load Context

For the selected item, gather:

1. **Full metadata** — use the dict returned by `search_items()` directly
   (it already contains title, authors, date, abstract, DOI, publication,
   volume, pages, tags, collections). Only call `get_item(item["key"])`
   if the `key:` lookup path was used.

2. **PDF** via `get_pdf_path(item_id)`:
   - If a PDF exists, note the path — you can read it with the Read tool
   - If no PDF, note that only metadata is available

3. **Existing notes** via `get_notes(item_id)`:
   - Zotero notes (HTML stripped to plain text)

4. **Prior insights** from the memory system:
   - Search memories for `source_insight` category with matching `zotero_key`
   - Use: `venv/bin/python3 scripts/fetch-memories.py --query "[item key]" --category source_insight`

### 3. Present Overview

```text
## [Title]

**Authors:** [Author list]
**Date:** [Year] | **Publication:** [Journal/Publisher]
**DOI:** [DOI if available]
**Collections:** [collection1, collection2]
**Tags:** [tag1, tag2, tag3]
**Zotero key:** [key]

### Abstract

[Abstract text]

### PDF

[Available at: /path/to/file.pdf | Not available — metadata only]

### Existing Notes

[Zotero notes if any, or "None"]

### Prior Insights (from memory system)

[Any source_insight memories with this zotero_key, or "None — first reading"]
```

### 4. Establish Reading Goal

Ask:

```text
What question are you bringing to this source?
```

Wait for the user's response. This focuses the reading.

### 5. Guided Reading

If a PDF is available:
- Read the PDF using the Read tool (it supports PDFs natively)
- Focus on sections relevant to the user's question
- Summarise key passages, highlight methodology, note findings

If no PDF:
- Work from the abstract and any Zotero notes
- Note what additional information would be needed

Throughout the reading, relate findings to the user's question.

### 6. Capture Insights

At natural stopping points (or when the user indicates they're done), ask:

```text
Should I capture any insights from this reading?
```

For each insight to capture, use `/remember` with:
- **Category:** `source_insight`
- **Content:** Self-contained insight (understandable without conversation context)
- **Tags:** Relevant research tags (topic, method, findings)
- **Zotero key:** The item's 8-character alphanumeric key from Step 3
  (e.g., `MPZHXY3P`, `N2C5KIGL`) — **NOT** a citation slug, author-year,
  DOI, or arXiv ID. This must be the exact value from Zotero's internal
  identifier so the write-back sync can resolve the item via the Zotero API.

Format: `/remember category:source_insight tags:[tags] zotero:[8-char-key] [content]`

**Critical:** The `zotero_key` field must contain only the 8-character
alphanumeric key shown as `**Zotero key:** [key]` in Step 3's overview.
Anything else (slugs, titles, DOIs) breaks the downstream Zotero write-back
sync — the API returns 404 and the insight is never pushed to the item note.

### 7. Summary

At the end of the session, provide a brief summary:
- Key findings relevant to the reading goal
- How many insights were captured
- Connections to other work (if any memories from other projects are relevant)

## Notes

- The Zotero database is at `~/Zotero/zotero.sqlite` (read-only access)
- PDFs are in `~/Zotero/storage/{key}/{filename}`
- The `source_insight` category is permanent (never decays) — insights persist
- The `zotero_key` field enables future write-back to Zotero notes
- This command works offline — all data is local
