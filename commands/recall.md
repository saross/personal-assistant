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
2. **Drop forgotten memories**: skip any record whose `is_active` field is
   `false`, exactly as the query branch below does. This applies to **both**
   the counts and the "Most Recent" preview — without it a memory retired
   seconds ago still appears at the top of the preview, which is the one
   place the operator is most likely to look for it.
3. **Count** total memories and breakdown by category
4. **Display**:

```text
## Memory Statistics

Total: [N] memories ([N] extraction, [N] manual)

### By Category (top 10)
  decision:       [N]
  architecture:   [N]
  progress:       [N]
  ...

### Most Recent (5)

[category] (verified|pending|unanchored) — created_at — id
content (truncated to ~100 chars)
---
[... 4 more ...]
```

5. Suggest follow-up: "Use `/recall [keyword]` to search, or `/recall recent` for the last 7 days."

### With Query Arguments

1. **Read** `~/personal-assistant/memories/memories.jsonl` (canonical source)
2. **Parse** each line as a JSON object
3. **Drop forgotten memories**: skip any record whose `is_active` field is
   `false`. A missing `is_active` key means active (the legacy default) —
   only an explicit `false` excludes. This step is **mandatory**, not
   optional: `/forget` promises the record stops surfacing, and `/recall`
   reads the JSONL directly rather than through PostgreSQL's
   `active_memories` view, which applies the filter server-side.
4. **Filter** based on the query:
   - Free-text: case-insensitive substring match on `content` and `source_context`
   - Category filter: exact match on `category` field
   - Tag filter: match against `research_tags` array
   - Combine filters when both are provided (AND logic)
5. **Sort** by `created_at` descending (most recent first)
6. **Return** top 10 matches, formatted as:

```text
[category] (verified|pending|unanchored) — created_at — id
content
Tags: tag1, tag2, tag3
Source: source_context
---
```

7. If more than 10 matches, note the total count and offer to show more

Show the `id` verbatim. It is the handle `/forget` and `/update` take, and
`commands/forget.md` names this command as where to get one; a recall that
hides it leaves no way to retire a memory but grepping the JSONL by hand.

**Verification token** (shown in parentheses, from the memory's `verified`
field — present in the JSONL since v2): `verified` = anchors resolved;
`pending` = anchors not yet checkable; `unanchored` = no anchor to check
(`verified` absent/null — the majority of the corpus). **`unanchored` is a
factual anchor-status, NOT a low-value flag** — most unanchored memories are
perfectly good. This replaces the old `(confidence)` token, which was a
misleading echo of `verified` (write-path plan P9). Omit the token if the
distinction is not useful for the query at hand.

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

## Instrumentation — log which memories were surfaced (earned-utility, item 16)

Separately from the count above, log the **IDs** of the memories you
actually returned, so the earned-utility value signal (item 16, Stage 1 —
`wiki/planning/earned-utility-value-signal-proposal.md`) can track which
memories earn their keep. `/recall` is the strongest-intent surfacing
path, so its IDs matter most. **After serving a `/recall` that returned
one or more memories, run this once** (skip it for the bare statistics
view and zero-match cases — there are no IDs to log):

```bash
python3 ~/personal-assistant/scripts/surfacing_log.py \
  --path recall --ids "<the memory IDs you just returned, space-separated>"
```

- `--ids` — the IDs of the memories actually shown (e.g.
  `2026-06-05-ab12cd34 2026-06-04-ef56ab78`), in the order returned.
  These are Shawn's own record IDs, **never the search text** (privacy).
- Comma separators are also accepted; whitespace is fine.

Best-effort and read-only with respect to the corpus: it appends to
`data/logs/surfaced.log` and never alters the recall output. Unlike the
§8 count log above, this has **no review deadline** — it accrues forward
until the Stage-2 consumption design (proposal §5–§6) is built.

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

Run the search script via Bash, passing the user's text as an **argument**:

```bash
~/personal-assistant/venv/bin/python3 \
  ~/personal-assistant/scripts/search-sessions.py --query-stdin \
  --limit 5 --json <<'RECALL_QUERY'
<the user's query text, verbatim, on its own line>
RECALL_QUERY
```

**Never interpolate the query into the command line.** Audit R8 stopped it
being pasted into SQL; audit M-2 is the same problem one layer out, in the
**shell**. `search-sessions.py "<user query>"` requires this command to be
assembled as a string, and the query is text somebody else wrote: an
apostrophe ends the quoting, and a backtick or `$( )` is executed by the
shell *before* the script runs. `--query-stdin` with a quoted heredoc
(`<<'RECALL_QUERY'` — the quotes on the delimiter suppress every expansion)
removes the shell from the path entirely: there is no string left for it to
parse. The trailing newline is stripped; the text is otherwise used
verbatim.

If a heredoc is impossible in the calling context, the fallback is to
single-quote the argument **and refuse** any query containing a single
quote, a backtick, or `$(`. Do not attempt to escape them.

The **venv** interpreter, not a bare `python3`: this script imports
`psycopg2`, which is installed only in the virtual environment. A system
`python3` exits 2 with "psycopg2 is required", which the graceful-fallback
rule below would then silently swallow as "PostgreSQL unavailable" — the
session search would appear to work and never return anything. (The two
instrumentation calls above are stdlib-only, so a bare `python3` is fine
for them.)

**Never build a SQL string containing the user's text.** This section used
to hand `psql -c` a statement with the query pasted into a
`plainto_tsquery('english', 'QUERY_HERE')` literal, inside a shell
double-quoted string: a single apostrophe broke the statement, and
deliberately crafted text could change it (audit R8, 2026-09-08). The
script parameterises every query, so the same rule applies anywhere else
in `commands/`: no user text is ever interpolated into SQL.

Note this searches transcript **content** (the `session_chunks` index),
not the `sessions` metadata table the old snippet queried — a broader and
more useful match, and the only indexed path that never decompresses an
archive. Each result carries `project`, `title`, `started_at`, an
`archive_dir` and a `turn_idx`.

If the script exits non-zero (PostgreSQL unavailable), skip the session
section silently, as before.

### Display format

If sessions match, show them **after** the memory results in a separate section:

```text
### Related Sessions

project — title — date — «snippet»
project — title — date — «snippet»
```

Offer the retrieval handle when a result looks relevant:
`scripts/search-sessions.py --show <archive_dir> --turn <turn_idx>`.

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

This statement is a fixed literal — it takes no argument, so there is
nothing to interpolate. Keep it that way: if this block ever needs to vary
by user input, move it behind a parameterised script.

Display as:

```text
### Sessions

[N] archived sessions ([M] total minutes, $[X] estimated cost)
```

## Notes

- Memory search reads the JSONL file directly — no database required
- Session search requires PostgreSQL (gracefully skipped if unavailable)
- Memories retired with `/forget` (`is_active: false`) are **excluded** on
  **both** branches — see the mandatory filter steps above. Everything else in the file is
  searched, **including decayed categories**: the JSONL is canonical and
  carries no decay table, so a record PostgreSQL would have aged out can
  still appear here
- If memories.jsonl is empty, say so and suggest using `/remember` to capture something
