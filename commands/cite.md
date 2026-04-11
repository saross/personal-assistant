# /cite — Quick Citation Lookup

Search the local Zotero library and return formatted citations.

## Usage

```text
/cite [search query]
/cite key:[zotero-key]
```

## Arguments

- `[search query]` — Free-text search across titles, abstracts, and authors
- `key:[zotero-key]` — Direct lookup by Zotero item key

## Behaviour

### 1. Search

```python
import sys
sys.path.insert(0, "scripts")
from zotero import search_items, get_item, format_citation
```

- **If query starts with `key:`**: direct lookup via `get_item(key)`
- **Otherwise**: search via `search_items(query, limit=5)`

### 2. Present Results

For each match, show a formatted citation with metadata:

```text
## Citations matching "[query]"

1. **Sobotkova & Ross (2024)** Validating Predictions of Burial Mounds
   with Field Data: the Promise and Reality of Machine Learning
   *Journal of Archaeological Science* 45: 102-115
   DOI: 10.1234/test.2024 | Key: ABC12345

2. **Eftimoski et al. (2017)** The impact of land use and depopulation
   on burial mounds in the Kazanlak Valley, Bulgaria
   *Bulgarian e-Journal of Archaeology* 7(2): 127-149
   DOI: 10.5678/bjea.2017 | Key: DEF67890
```

### 3. Copy-Ready Formats

If the user asks for a specific citation format, provide it.
Default format: `Author (Year) Title. *Publication*, Volume(Issue), Pages.`

If asked, also provide:
- **BibTeX** — standard LaTeX citation format
- **In-text** — `(Author et al., Year)` or `Author et al. (Year)`

## Notes

- This is a quick lookup — for deep reading, use `/read`
- The Zotero key is shown so users can reference it in `/read key:[key]`
- All data is local (Zotero SQLite, read-only) — works offline
