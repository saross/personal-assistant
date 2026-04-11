# /cite-new — Create BibTeX Citation

Generate a BibTeX citation from a DOI, URL, or manual details. Output is
a fenced code block ready to copy to clipboard and import into Zotero
(File → Import from Clipboard).

## Usage

```text
/cite-new [DOI or URL or details]
```

## Arguments

- `10.1234/example.2024` — DOI (with or without `https://doi.org/` prefix)
- `https://doi.org/10.1234/...` — DOI URL
- `https://arxiv.org/abs/...` — arXiv URL (extract DOI or use arXiv metadata)
- Free-text description — author, title, year, publication details for manual entry

## Behaviour

### 1. Detect Input Type

- **DOI pattern** (`10.\d{4,}/...`): Extract the DOI and look up via CrossRef
- **URL containing DOI**: Extract DOI from URL path and look up
- **arXiv URL**: Extract arXiv ID, look up via arXiv API
- **Everything else**: Treat as manual details — ask for missing fields

### 2. DOI Lookup (CrossRef API)

If a DOI is detected, fetch metadata from CrossRef:

```bash
curl -sL -H "Accept: application/json" \
  "https://api.crossref.org/works/{doi}"
```

**API gate note:** This is a free, keyless, read-only API call to a public
metadata service. No cost, no authentication. Does not require user approval
under the API gate protocol (it's not an LLM API call).

Extract from the response:
- `title` — from `message.title[0]`
- `author` — from `message.author[]` (given + family name)
- `container-title` — journal name from `message.container-title[0]`
- `published-print` or `published-online` — date parts `[year, month]`
- `volume`, `issue`, `page`
- `DOI`
- `URL`
- `type` — maps to BibTeX entry type (journal-article → @article, etc.)
- `publisher`
- `ISSN`, `ISBN`

### 3. Generate BibTeX

Map CrossRef fields to BibTeX:

```bibtex
@article{AuthorYear,
  author    = {LastName, FirstName and LastName2, FirstName2},
  title     = {{Title with Proper Capitalisation}},
  journal   = {Journal Name},
  year      = {2024},
  volume    = {45},
  number    = {2},
  pages     = {102--115},
  doi       = {10.1234/example.2024},
  url       = {https://doi.org/10.1234/example.2024},
  publisher = {Publisher Name},
}
```

**Citation key format:** First author's last name + year + first significant
title word if needed for disambiguation. E.g., `Sobotkova2024`,
`Eftimoski2017impact`.

**BibTeX type mapping:**
- `journal-article` → `@article`
- `book` → `@book`
- `book-chapter`, `book-section` → `@incollection`
- `proceedings-article` → `@inproceedings`
- `dissertation` → `@phdthesis`
- `report` → `@techreport`
- `posted-content` (preprint) → `@misc`
- Everything else → `@misc`

### 4. Manual Entry (no DOI)

If no DOI is detected and the input is free text, extract what you can
and ask for the rest:

```text
I'll create a BibTeX entry. Here's what I extracted from your input:

  Author: [detected or "?"]
  Title: [detected or "?"]
  Year: [detected or "?"]
  Type: [article/book/etc or "?"]

What's missing? I need at least author, title, year, and publication type.
```

Then generate the BibTeX from the combined information.

### 5. Output

Present the BibTeX in a fenced code block:

````text
## BibTeX Citation

```bibtex
@article{Sobotkova2024,
  author    = {Sobotkova, Adela and Ross, Shawn A.},
  title     = {{Validating Predictions of Burial Mounds with Field Data}},
  journal   = {Journal of Archaeological Science},
  year      = {2024},
  volume    = {45},
  pages     = {102--115},
  doi       = {10.1234/test.2024},
}
```

**To import:** Copy the BibTeX block above, then in Zotero:
File → Import from Clipboard (or Ctrl+Shift+Alt+I)
````

### 6. Offer to Search Memory

After generating the citation, check if related insights exist:

```text
Should I check the memory system for any existing insights
related to this paper?
```

If yes, run a semantic search on the title.

## Notes

- CrossRef API is free and keyless — no authentication needed
- The generated BibTeX can be imported into any reference manager, not just Zotero
- For arXiv preprints, include the `eprint` and `archiveprefix` fields
- Title is wrapped in double braces `{{...}}` to preserve capitalisation in BibTeX
- Page ranges use en-dash (`--`) per BibTeX convention
- If CrossRef returns incomplete metadata, note what's missing so the user can fill it in
