# /recall — Search Memories and Sessions

Search the memory system and archived sessions for specific topics, decisions,
or insights.

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

## Instrumentation — log every invocation (mandatory final step)

`/recall` reads `memories.jsonl` directly, so — unlike the autonomous
`fetch-memories.py` path — it is **not** captured by the tier-2 retrieval
log unless logged explicitly. The Vector 2 §8 observation window
(review **2026-06-13**) needs both paths recorded, or measurement (2)
under-counts on-demand depth-fetches. **After serving any `/recall`
(including the bare statistics view and zero-match cases), run this once:**

```bash
python3 ~/personal-assistant/scripts/log-recall.py \
  --selectors "<names>" --results <N>
```

- `<names>` — selector **names only, never the search text** (privacy):
  - bare `/recall` → `none`
  - free-text query → `query`
  - `category:X` → `category:X` (add `;query` if free text is also present, e.g. `category:decision;query`)
  - `tag:Y` → `tag:Y`
  - `recent` → `recent`
- `<N>` — the number of memories actually returned (use `0` for zero matches).

This is best-effort instrumentation: it never alters the recall output
and silently no-ops on failure. Keep doing it until the 2026-06-13 review
decides whether to retire the apparatus.

## Examples

```text
/recall
/recall GPS accuracy
/recall category:decision PostgreSQL
/recall tag:ethics
/recall category:commitment
/recall recent
```

## Session Search

When a free-text query is provided, **also search the sessions table** in PostgreSQL
for matching archived sessions. This surfaces relevant past sessions alongside
memory results.

### How to search sessions

Run a `psql` command via Bash:

```bash
psql -d claude_memories -t -A -F '|' -c "
SELECT id, project, title, started_at::date, duration_minutes
FROM sessions
WHERE to_tsvector('english',
    COALESCE(title, '') || ' ' ||
    COALESCE(purpose, '') || ' ' ||
    COALESCE(prompt_summary, ''))
  @@ plainto_tsquery('english', 'QUERY_HERE')
AND is_active = TRUE
ORDER BY started_at DESC
LIMIT 5;
"
```

### Display format

If sessions match, show them **after** the memory results in a separate section:

```text
### Related Sessions

project — title — date — duration
project — title — date — duration
```

### When to include session search

- **Include**: When the user provides a free-text query (`/recall PostgreSQL`, `/recall GPS accuracy`)
- **Skip**: When using `category:` or `tag:` filters (these are memory-specific)
- **Skip**: When using bare `/recall` (statistics mode) or `/recall recent`
- **Graceful fallback**: If `psql` fails (PostgreSQL not running), silently skip
  session results — do not show an error. Memories from JSONL are always available.

### No arguments: include session statistics

When `/recall` is invoked with no arguments, add a session statistics line after
the memory statistics:

```bash
psql -d claude_memories -t -A -c "
SELECT COUNT(*), COALESCE(SUM(duration_minutes), 0),
       ROUND(COALESCE(SUM(estimated_cost_usd), 0)::numeric, 2)
FROM sessions WHERE is_active = TRUE;
"
```

Display as:

```text
### Sessions

[N] archived sessions ([M] total minutes, $[X] estimated cost)
```

## Notes

- Memory search reads the JSONL file directly — no database required
- Session search requires PostgreSQL (gracefully skipped if unavailable)
- All memories are searched, including decayed categories (the file is canonical)
- If memories.jsonl is empty, say so and suggest using `/remember` to capture something
