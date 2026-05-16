# /remember — Manual Memory Capture

Manually capture a memory without waiting for automatic extraction.

## Usage

```text
/remember [content]
/remember category:[category] [content]
/remember category:[category] tags:[tag1,tag2] [content]
/remember category:source_insight zotero:[8-char-key] tags:[tag1,tag2] [content]
/remember category:feedback why:"why this rule exists" how_to_apply:"when this kicks in" [content]
/remember anchor:file:path/to/file.py:42 anchor:commit:abc1234 [content]
```

## Arguments

- `[content]` — The memory to capture (required)
- `category:[category]` — Explicit category (optional; if omitted, suggest one)
- `tags:[tag1,tag2]` — Comma-separated tags (optional; if omitted, suggest some)
- `zotero:[key]` — 8-character Zotero item key (optional; only meaningful for
  `source_insight`). Populates the memory's `zotero_key` field for later
  write-back sync.
- `anchor:[type]:[ref]` — Repeatable. Re-verifiable anchor for any specific
  claimed in the content. Types: `file` (e.g. `anchor:file:src/foo.py:42`),
  `commit` (e.g. `anchor:commit:abc1234`), `zotero` (8-char key —
  duplicates the `zotero:` field but goes in the structured `anchors`
  array), `url`. Per v2's write-side anti-confabulation rule, *checkable*
  specifics in `content` should carry an anchor; if no anchor is available,
  reword to drop the false precision.
- `why:"..."` — Free text (quoted if multi-word). For guidance categories
  (`feedback`, `decision`, `gotcha`, `methodology`, `pattern`,
  `error_mode`): the reason behind the rule/decision/gotcha. Survives
  drift better than the content itself.
- `how_to_apply:"..."` — Free text (quoted). For guidance categories:
  when/where this kicks in, so edge cases can be judged.

## Behaviour

1. **Parse** the input to extract category, tags, zotero key, and content.
   Recognise these token prefixes: `category:`, `tags:`, `zotero:`. Everything
   else is content.
2. **If category not specified**, suggest one based on content and confirm with user
3. **If tags not specified**, suggest 2-4 relevant tags based on content and vocabulary
4. **Normalise tags** using these rules in order:
   1. Lowercase and strip whitespace
   2. Replace underscores and spaces with hyphens
   3. Remove non-alphanumeric characters (except hyphens)
   4. Collapse multiple consecutive hyphens into one
   5. Strip leading/trailing hyphens
   6. Check against `~/personal-assistant/memories/tag-vocabulary.txt` — prefer existing tags
5. **Generate a unique ID** using the date and a hash
6. **Write** directly to `~/personal-assistant/memories/memories.jsonl` as a single JSON line:

```json
{
  "id": "2026-02-07-a1b2c3d4e5f6",
  "session_id": "[current session ID]",
  "project": "[encoded cwd — see below]",
  "source": "manual",
  "category": "[category]",
  "content": "[content]",
  "summary": "[one-sentence summary, max 150 chars, self-contained]",
  "confidence": "high",
  "research_tags": ["tag1", "tag2"],
  "source_context": "Manual capture via /remember",
  "created_at": "2026-02-07T10:30:00+00:00",
  "zotero_key": "[optional — include for source_insight if known]",
  "deadline_at": "[optional — ISO format, include for commitment if known]",
  "anchors": [{"type": "file", "ref": "src/foo.py", "line": 42}],
  "why": "[optional — only include if non-empty]",
  "how_to_apply": "[optional — only include if non-empty]",
  "is_active": true
}
```

**v2 fields:** `anchors`, `verified`, `links`, `why`, `how_to_apply`,
`superseded_by`, `revisions`, `is_active`. Only include fields that have
values — omit empty ones rather than writing `null` or `[]` (the
PostgreSQL sync layer supplies defaults). `is_active` is always `true`
for new captures (`/forget` sets it to `false`). `verified`, `links`,
`superseded_by`, and `revisions` are managed by other code paths (Phase 2
verification, Phase 4 typed links, `/forget`/`/update` revisions); leave
them out at write time.

**Deriving `project`**: Replace all `/` in the absolute working directory path with `-`.
For example, if the cwd is `/home/shawn/Code/map-reader-llm`, set `project` to
`-home-shawn-Code-map-reader-llm`. This matches the encoding Claude Code uses for
project directories under `~/.claude/projects/`.

**Important**: When writing the JSON line, ensure all string values are properly
JSON-escaped. In particular, escape double quotes (`\"`) and backslashes (`\\`)
within content. Use `json.dumps()` semantics — do not hand-construct the JSON line.

7. **Confirm** the capture to the user:

```text
Captured to memory:
  Category: [category]
  Content: "[content]"
  Tags: [tags]
  Confidence: high
  ID: [id]
```

8. **Update vocabulary** — if any tags are new, append them to
   `~/personal-assistant/memories/tag-vocabulary.txt`

## Category Reference

### Permanent (no decay)

- `methodology` — Analytical approach decisions
- `ethics` — IRB, consent, data handling
- `provenance` — Data origin, transformations
- `hypothesis` — Research questions, predictions
- `limitation` — Known constraints, scope
- `openness` — FAIR, open science, licensing
- `source_insight` — Learnings from scholarly sources
- `error_mode` — LLM mistakes, corrections needed
- `surprise` — Unexpected insights
- `self_reflection` — LLM reasoning reflection
- `prompt_effectiveness` — What prompts work
- `decision` — Explicit choices with rationale
- `architecture` — System design, structure
- `contact` — People, preferences

### Decaying

- `pattern` — Recurring approaches (180 days)
- `gotcha` — Pitfalls, edge cases (180 days)
- `progress` — Status updates (30 days)
- `context` — Background info (30 days)
- `commitment` — Promises, deadlines (30 days after deadline)
- `waiting_for` — Blocked on others (14 days)

## Special Fields

- For `commitment` category: ask about deadline and include `deadline_at` in ISO format
- For `source_insight` category: include `zotero_key` in the memory when a
  Zotero item key is known. If the invocation includes a `zotero:KEY`
  argument, use that value. Otherwise, when invoked outside of a `/read`
  session, ask the user for the key — but do not re-ask if you already
  displayed one in a prior step. **The key must be the 8-character
  alphanumeric key** from Zotero (e.g., `MPZHXY3P`, `N2C5KIGL`) — not a
  citation slug, author-year, title, DOI, or arXiv ID. Any other format
  breaks the Zotero write-back sync. To look up a real key, run
  `search_items()` from `scripts/zotero.py` and use the `key` field of the
  returned item dict. If only a citation slug is known and a lookup is
  impractical, omit the field entirely.
- For `waiting_for` category: note who you're waiting on in the content

## Examples

```text
/remember Ethics board requires re-consent if survey data linked to interviews

/remember category:decision Using PostgreSQL for memory store because of query complexity

/remember category:source_insight zotero:MPZHXY3P tags:gps-accuracy,field-methods Smith 2024 reports 3-5m degradation under canopy

/remember category:commitment tags:deadline Brian needs Fieldmark docs by Wednesday 12 Feb
```

## Notes

- Manual memories are marked with `"source": "manual"` to distinguish from extraction
- Confidence defaults to "high" for manual captures (the user chose to remember it)
- The memory should be self-contained — understandable without conversation context
- If the user's phrasing is ambiguous, rephrase for clarity before saving
