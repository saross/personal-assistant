# /remember — Manual Memory Capture

Manually capture a memory without waiting for automatic extraction.

## Usage

```text
/remember [content]
/remember category:[category] [content]
/remember category:[category] tags:[tag1,tag2] [content]
```

## Arguments

- `[content]` — The memory to capture (required)
- `category:[category]` — Explicit category (optional; if omitted, suggest one)
- `tags:[tag1,tag2]` — Comma-separated tags (optional; if omitted, suggest some)

## Behaviour

1. **Parse** the input to extract category, tags, and content
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
  "confidence": "high",
  "research_tags": ["tag1", "tag2"],
  "source_context": "Manual capture via /remember",
  "created_at": "2026-02-07T10:30:00+00:00",
  "zotero_key": "[optional — include for source_insight if known]",
  "deadline_at": "[optional — ISO format, include for commitment if known]"
}
```

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
- For `source_insight` category: ask about Zotero key and include `zotero_key` if known
- For `waiting_for` category: note who you're waiting on in the content

## Examples

```text
/remember Ethics board requires re-consent if survey data linked to interviews

/remember category:decision Using PostgreSQL for memory store because of query complexity

/remember category:source_insight tags:gps-accuracy,field-methods Smith 2024 reports 3-5m degradation under canopy

/remember category:commitment tags:deadline Brian needs Fieldmark docs by Wednesday 12 Feb
```

## Notes

- Manual memories are marked with `"source": "manual"` to distinguish from extraction
- Confidence defaults to "high" for manual captures (the user chose to remember it)
- The memory should be self-contained — understandable without conversation context
- If the user's phrasing is ambiguous, rephrase for clarity before saving
