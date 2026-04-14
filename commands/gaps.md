# /gaps — Literature Gap Analysis

Analyse a Zotero collection or topic search results to identify gaps in
coverage across six dimensions: topical, methodological, population, temporal,
geographic, and theoretical.

## Usage

```text
/gaps [collection name]
/gaps topic:[query]
/gaps
```

## Arguments

- `[collection name]` — Zotero collection to analyse (case-sensitive)
- `topic:[query]` — Search Zotero for items matching a topic
- *(no arguments)* — List available collections and prompt for selection

## Behaviour

### Step 1: Establish Scope

**Collection mode** (`/gaps AI-LLMs`):

```python
import sys
sys.path.insert(0, "scripts")
from zotero import get_collection_items, format_citation
items = get_collection_items("AI-LLMs")
```

**Topic mode** (`/gaps topic:mound detection`):

```python
import sys
sys.path.insert(0, "scripts")
from zotero import search_items, format_citation
# limit=50 (default is 10) — gap analysis needs a broad sample to detect
# coverage patterns, but more than ~50 abstracts strains the context window
items = search_items("mound detection", limit=50)
```

**Bare invocation** (`/gaps`):

```python
import sys
sys.path.insert(0, "scripts")
from zotero import list_collections
collections = list_collections(min_items=3)
```

Present the list and ask the user to choose.

After loading items, guard against empty results:

- If zero items returned, report "Collection not found or empty" and offer to
  list available collections with `list_collections()`. Do not proceed.
- If fewer than 5 items, warn: "Small collection — analysis will be shallow.
  Consider expanding the collection first."

Confirm scope and establish context:

```text
Analysing [N] items in [collection/topic].
Date range: [earliest]–[latest] (or "dates unavailable" if most lack dates).

What is the central research question this collection supports?
(This determines which gaps are high priority.)
```

The research question is needed before mapping coverage — it determines which
dimensions receive emphasis and how gaps are prioritised.

### Step 2: Load Data

For each item, gather:

- Title, creators, date, abstract, item type, Zotero tags, **key** (8-char Zotero key)
- Any `source_insight` memories with a matching `zotero_key`

Fetch source_insight memories for the loaded items. The `zotero_key` field is
not exposed by `fetch-memories.py`, so query the JSONL directly:

```python
import json
from pathlib import Path

jsonl = Path.home() / "personal-assistant/data/memories/memories.jsonl"
# Build set of Zotero keys from loaded items
item_keys = {item["key"] for item in items}

source_insights = []
with open(jsonl) as fh:
    for line in fh:
        if not line.strip():
            continue
        mem = json.loads(line)
        if (
            mem.get("category") == "source_insight"
            and mem.get("zotero_key") in item_keys
        ):
            source_insights.append(mem)
```

This returns only source_insight memories for items in the collection.
Match each memory to its item via `memory["zotero_key"] == item["key"]`.
Note which items have prior insights and which have not been processed
with `/read` (no matching source_insight memory).

**Important:** Abstracts are the primary analysis input. Do NOT attempt to read
PDFs — they are too large for context. If an item has no abstract, note it as
"abstract unavailable" and rely on title + tags + any source_insight memories.

### Step 3: Map Coverage

Analyse each item's title, abstract, tags, and associated source_insight
memories. Map the collection across six dimensions:

1. **Topics/concepts** — What subjects are addressed? Group into clusters.
2. **Methodological approaches** — Qualitative, quantitative, mixed methods,
   computational, field-based, laboratory, archival, review, meta-analysis, etc.
3. **Populations/contexts** — What groups, sites, settings, or domains are studied?
4. **Time periods** — Both publication dates and study periods (if mentioned
   in abstracts). Note chronological clustering.
5. **Geographic regions** — Where was the research conducted or focused?
6. **Theoretical frameworks** — What theories, models, or conceptual frameworks
   are applied?

Present a coverage summary before identifying gaps:

```markdown
### Current Coverage

**Topics:** [N] items cluster around [themes]. Strongest coverage in [X].
**Methods:** Dominated by [approach]. [N] items use [Y].
**Populations/contexts:** Primarily [Z]. [N] items address [W].
**Time periods:** Published [range]. Study periods span [range if known].
**Geography:** Concentrated in [regions]. [N] items from [other regions].
**Theoretical frameworks:** [Frameworks identified]. [N] items are atheoretical.
```

### Step 4: Identify Gaps

For each dimension, identify what is missing or underrepresented. For each gap:

**Distinguish between two types:**

- **"Not in your collection"** — Research likely exists but you haven't gathered it.
  → Suggest search terms and databases.
- **"Not in the literature"** — No one appears to have studied this.
  → Flag as an original contribution opportunity.

**When uncertain (which is most of the time), default to "Not in your
collection."** A gap analysis based on one collection cannot reliably determine
what exists across the entire literature. It is safer to suggest searching
than to claim a gap in the literature. Only flag "Not in the literature" when
the collection is comprehensive enough to make that judgement (e.g., a
systematic review collection), or when the gap is in an area well-enough known
to the user that absence is meaningful.

**Prioritise:**

- **High priority** — Directly affects the user's research goals. Missing this
  would be noticed by a reviewer. Be specific about *why* it matters.
- **Medium priority** — Would strengthen the work. A reviewer might mention it
  but wouldn't reject on this basis.
- **Potential** — Worth noting but may be out of scope. Include only if
  genuinely relevant, not to pad the list.

Use the research question established in Step 1 to determine priority. If the
user did not provide one (e.g., skipped with "just analyse"), use the
collection's apparent scope as a proxy.

### Step 5: Present Analysis

```markdown
## Gap Analysis: [Collection/Topic]

### Scope

[N] items analysed ([date range]). [N] with abstracts, [N] with prior
source_insight memories (via /read), [N] not yet processed with /read.

### Current Coverage

[Coverage summary from Step 3, organised by dimension]

### Identified Gaps

#### High Priority

**[Gap title]** ([dimension])
[What's missing and why it matters for the research. Whether it's "not
collected" or "not studied." Specific enough to act on.]

...

#### Medium Priority

**[Gap title]** ([dimension])
[Description]

...

#### Potential Gaps

**[Gap title]** ([dimension])
[Description]

...

### Recommended Search Terms

For each high and medium gap, suggest concrete search queries:

| Gap | Suggested Search Terms | Databases |
|-----|----------------------|-----------|
| [Gap title] | "term1", "term2 AND term3" | Scopus, Web of Science |
| ... | ... | ... |

### Sources Consulted

[Formatted citation for each item, using format_citation(). List
alphabetically by first author surname (standard academic default). If the
user prefers grouping by theme or chronology, ask after the initial output.]
```

### Step 6: Offer Follow-up

After presenting the analysis:

```text
Would you like me to:
1. Search for sources to fill specific gaps (Scholar Gateway / Zotero)
2. Deep-read a particular item with /read
3. Save this analysis to a file
4. Capture key gaps as research memories
```

If the user wants to search, prefer `mcp__claude_ai_Scholar_Gateway__semanticSearch`
for academic literature (it returns DOIs and metadata suitable for Zotero).
Fall back to general web search for grey literature or very recent work.
Offer to capture findings via `/cite-new` (DOI → BibTeX) for manual addition
to Zotero.

## Notes

- Gap analysis is structured by **dimension**, not by source — this forces
  systematic coverage rather than ad-hoc observation
- The six dimensions come from standard literature review methodology; not
  all will be equally relevant to every collection. Skip dimensions that
  don't apply (e.g., "geographic" for a purely theoretical collection)
- Collections with fewer than 5 items produce shallow analysis — warn the user
  and suggest expanding the collection first
- This command complements `/synthesise`: synthesis shows what the literature
  *says*, gaps shows what it *doesn't say*
- When source_insight memories exist for items in the collection, use them —
  they contain deeper reading notes than abstracts alone
- Items without abstracts are common for older works, book chapters, and grey
  literature. Note them but don't treat missing abstracts as missing coverage
