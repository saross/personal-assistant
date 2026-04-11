# /synthesise — Thematic Synthesis

Produce a structured thematic synthesis of accumulated knowledge on a topic,
drawing from the memory system and optionally from a Zotero collection.

## Usage

```text
/synthesise [topic]
/synthesise collection:[name]
```

## Arguments

- `[topic]` — Free-text topic for memory-based synthesis (semantic search)
- `collection:[name]` — Zotero collection name for literature synthesis

## Behaviour

### Mode 1: Topic Synthesis (`/synthesise mound detection`)

Synthesise everything the memory system knows about a topic.

#### 1. Gather Sources

Run both semantic and keyword searches:

```bash
venv/bin/python3 scripts/fetch-memories.py --semantic "[topic]" --limit 30
venv/bin/python3 scripts/fetch-memories.py --query "[topic]" --limit 20
```

Deduplicate results by memory ID. Also search for `source_insight` memories
related to the topic — these link to specific papers.

#### 2. Analyse

Group the gathered memories by:
- **Category** — decisions, architecture, methodology, gotchas, source_insights
- **Project** — which projects contributed knowledge on this topic
- **Timeline** — how understanding evolved over time

#### 3. Produce Synthesis

Structure by **theme**, not by source or date:

```markdown
# Synthesis: [Topic]

## Overview

[2-3 sentence summary of what the memory system knows about this topic]

## Theme 1: [Theme Name]

[Synthesis paragraph drawing from multiple memories. Cite sources as
(memory category, date) where helpful.]

## Theme 2: [Theme Name]

...

## Key Decisions

[Decisions made about this topic, with rationale. Drawn from `decision`
and `architecture` category memories.]

## Known Pitfalls

[Gotchas, error modes, and limitations. Drawn from `gotcha`, `error_mode`,
and `limitation` memories.]

## Literature Connections

[Any `source_insight` memories on this topic, with Zotero keys if available.
Format as: "Author (Year) found that..." with key for future /read.]

## Open Questions

[Gaps in the accumulated knowledge — what hasn't been addressed?]
```

### Mode 2: Collection Synthesis (`/synthesise collection:AI-LLMs`)

Synthesise across all items in a Zotero collection.

#### 1. Load Collection

```python
import sys
sys.path.insert(0, "scripts")
from zotero import get_collection_items, format_citation
```

Load all items from the named collection. For each item, gather:
- Title, authors, date, abstract
- Any `source_insight` memories with matching `zotero_key`

#### 2. Analyse

Across all items and their associated memories, identify:
- **Common themes** — What do multiple sources address?
- **Methodological approaches** — What methods are used?
- **Key debates** — Where do sources disagree?
- **Gaps** — What's NOT covered that might be expected?

#### 3. Produce Synthesis

```markdown
# Synthesis: [Collection Name]

**Sources:** [N] items ([date range])

## Overview

[2-3 sentence summary of the collection's scope]

## Theme 1: [Theme Name]

[Synthesis paragraph with citations: Author (Year)]

## Theme 2: [Theme Name]

...

## Methodological Approaches

[Summary of methods used across sources]

## Key Debates

[Areas of disagreement or tension]

## Gaps and Opportunities

[What's missing that might warrant further investigation]

## Sources

[Formatted citation for each item referenced, using format_citation()]
```

### 4. Offer to Save

After presenting the synthesis, ask:

```text
Should I save this synthesis? I can:
1. Write it to a markdown file in the project
2. Capture key findings as source_insight memories
3. Both
```

## Notes

- Topic synthesis draws from the semantic memory search (pgvector) —
  it finds conceptually related memories even without exact keyword matches
- Collection synthesis requires a Zotero collection name (case-sensitive).
  Use `list_collections()` to find available collections if unsure
- The two modes can complement each other: topic synthesis shows what you
  *know*, collection synthesis shows what the *literature* says
- Synthesis is structured by theme, never by source — this is a deliberate
  design choice to force integration rather than summarisation
