# /recall — Search Memories

Search the memory system for specific topics, decisions, or insights.

## Usage

```text
/recall [query]
/recall category:[category] [query]
/recall tag:[tag]
/recall recent
```

## Arguments

- *(no arguments)* — Show memory statistics: total count, breakdown by category, and
  the 5 most recent memories as a preview
- `[query]` — Free-text search across all memory content
- `category:[category]` — Filter to a specific category (e.g., `category:decision`)
- `tag:[tag]` — Filter to memories with a specific tag (e.g., `tag:gps-accuracy`)
- `recent` — Show memories from the last 7 days

## Behaviour

### No Arguments (bare `/recall`)

When invoked with no arguments, show memory statistics and a preview:

1. **Read** `~/personal-assistant/memories/memories.jsonl`
2. **Count** total memories and breakdown by category
3. **Display**:

```text
## Memory Statistics

Total: [N] memories ([N] extraction, [N] manual)

### By Category (top 10)
  decision:       [N]
  architecture:   [N]
  progress:       [N]
  ...

### Most Recent (5)

[category] (confidence) — created_at
content (truncated to ~100 chars)
---
[... 4 more ...]
```

4. Suggest follow-up: "Use `/recall [keyword]` to search, or `/recall recent` for the last 7 days."

### With Query Arguments

1. **Read** `~/personal-assistant/memories/memories.jsonl` (canonical source)
2. **Parse** each line as a JSON object
3. **Filter** based on the query:
   - Free-text: case-insensitive substring match on `content` and `source_context`
   - Category filter: exact match on `category` field
   - Tag filter: match against `research_tags` array
   - Combine filters when both are provided (AND logic)
4. **Sort** by `created_at` descending (most recent first)
5. **Return** top 10 matches, formatted as:

```text
[category] (confidence) — created_at
content
Tags: tag1, tag2, tag3
Source: source_context
---
```

6. If more than 10 matches, note the total count and offer to show more

### Zero Matches

If a search returns **zero results**, respond with:

```text
No memories found matching "[query]".

Try:
  - Broader keywords (e.g., "GPS" instead of "GPS accuracy under canopy")
  - Drop the category filter: /recall [keyword]
  - Search by tag: /recall tag:[tag-name]
  - Browse recent: /recall recent
  - Check available categories: /recall
```

Do not return empty results silently.

## Examples

```text
/recall
/recall GPS accuracy
/recall category:decision PostgreSQL
/recall tag:ethics
/recall category:commitment
/recall recent
```

## Notes

- This reads the JSONL file directly — no database required
- All memories are searched, including decayed categories (the file is canonical)
- If memories.jsonl is empty, say so and suggest using `/remember` to capture something
- For fuzzy/semantic search, PostgreSQL full-text search will be available in Phase 2
