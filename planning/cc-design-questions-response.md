# Response to Design Questions

This document addresses the concerns raised about the Memory System and Task System designs.

---

## 1. Retrieval is underspecified

**Verdict:** You're right. This is the biggest gap.

### Retrieval Architecture

Three mechanisms, in order of implementation:

#### A. SessionStart Injection (Automatic)

Every session begins with relevant memories loaded into context via hook:

```python
# session-start-retrieval.py

def get_session_context():
    memories = []
    
    # Recent memories (last 7 days, all categories)
    memories += query_recent(days=7)
    
    # Permanent high-value categories (no date filter)
    memories += query_by_categories([
        'decision', 'architecture', 'methodology', 
        'ethics', 'contact', 'hypothesis'
    ], limit=50)
    
    # Active commitments and waiting-for
    memories += query_by_categories([
        'commitment', 'waiting_for'
    ], where="is_active = TRUE")
    
    # Dedupe and format for context injection
    return format_for_context(memories)
```

Output injected via hook's `additionalContext` field.

#### B. Explicit Query Command (`/recall`)

```markdown
# /recall

Search memories for specific topics.

## Usage

/recall [query]
/recall category:[category] [query]
/recall tag:[tag]

## Examples

/recall GPS accuracy under canopy
/recall category:decision PostgreSQL
/recall tag:ethics

## Behavior

1. Search memories (full-text if Postgres available, keyword match otherwise)
2. Filter by category/tag if specified
3. Return top 10 matches with context
4. Offer to load more if needed
```

#### C. MCP Server (Defer to Phase 2)

A proper MCP server with tools like `memory_search(query, filters)` callable mid-reasoning. Defer until query patterns are clearer from actual usage.

#### Fallback: Direct File Read

If Postgres is unavailable, Claude Code can read `memories.jsonl` directly and filter. Less efficient but functional.

---

## 2. Hook failure modes

**Verdict:** You're right. Add explicit error handling.

### Error Handling Additions

```python
# In extraction-hook.py

import logging

LOG_FILE = CLAUDE_DIR / "logs" / "extraction.log"

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def main():
    try:
        hook_input = json.loads(sys.stdin.read())
    except json.JSONDecodeError as e:
        logging.error(f"Invalid hook input: {e}")
        sys.exit(1)
    
    # ... parsing ...
    
    try:
        extracted = extract_memories(messages, session_id)
    except Exception as e:
        logging.error(f"Extraction failed for session {session_id}: {e}")
        # Don't advance cursor - will retry next time
        sys.exit(1)
    
    if extracted:
        try:
            memories = format_memories(extracted, session_id)
            append_memories(memories)
            # Only advance cursor AFTER successful append
            cursor[session_id] = new_last_uuid
            save_cursor(cursor)
            logging.info(f"Extracted {len(memories)} memories from session {session_id}")
        except Exception as e:
            logging.error(f"Failed to save memories for session {session_id}: {e}")
            sys.exit(1)
```

### Catch-up Mechanism

Add `/catchup` command for processing missed sessions:

```markdown
# /catchup

Process any sessions that weren't extracted (due to crashes, errors, etc.)

## Behavior

1. Scan ~/.claude/projects/*/transcript.jsonl for all transcripts
2. Compare against extraction-cursor.json
3. List sessions with unprocessed content
4. Offer to process them now

## Output

Found 3 sessions with unprocessed content:
  - abc123 (2026-02-05): ~4000 tokens unprocessed
  - def456 (2026-02-06): ~12000 tokens unprocessed  
  - ghi789 (2026-02-07): ~2000 tokens unprocessed

Process all? [yes / select / skip]
```

---

## 3. PostgreSQL for MVP

**Verdict:** Include it, but sequence after core extraction works.

### Rationale for Including

The analytical queries are already specified in the design:
- Weekly review needs completion rates, domain breakdown
- Monthly retro needs slip frequency, pattern detection
- Tag gardening needs frequency distribution, co-occurrence, Levenshtein similarity

These aren't speculative — they're designed features. Building Python scripts to replicate SQL is wasted effort.

### Risk Assessment

| Risk | Probability | Severity | Mitigation |
|------|-------------|----------|------------|
| Install takes >30min | 10% | Low | Docker one-liner as fallback |
| Schema needs debugging | 30% | Low | JSONL is canonical, re-sync after fix |
| Sync script bugs | 50% | Low | JSONL works meanwhile |
| Actual blocker | <5% | Low | Fall back to jq/Python |

**Key protection:** JSONL is canonical. Postgres is derived. If Postgres fails, extraction keeps working and no data is lost.

### Implementation Sequence

1. Days 1-2: Extraction hook → JSONL working
2. Day 2-3: Basic retrieval (SessionStart injection, `/recall`)
3. Day 3-4: Postgres setup and sync script
4. Day 4+: Task system on top of working memory

---

## 4. Zotero sync complexity

**Verdict:** You're right. Defer bidirectional sync.

### What to Keep (Phase 1)

**Read direction (Zotero → Claude):**
- `/read [source]` fetches item from Zotero
- `/cite [topic]` searches Zotero library
- `/synthesise [collection]` loads collection items

**Schema field:**
- Keep `zotero_key` in memory schema
- Capture the link during extraction (costs nothing)
- Enables write sync later

### What to Defer (Phase 2)

**Write direction (insights → Zotero notes):**
- `sync-to-zotero.py` script
- Child note creation/appending
- All the edge cases (deleted items, rate limits, format changes)

Get core extraction working first. Add Zotero write sync when the read direction is proven valuable.

---

## 5. 21 categories — too many?

**Verdict:** Keep the taxonomy, but shrink the extraction working set.

### The Distinction

Some categories are for **real-time extraction** (Haiku assigns during processing).
Some are for **retrospective assignment** (human/review assigns looking back).

### Extraction Working Set (Haiku uses these)

**Always extract:**
- `decision`, `architecture`, `methodology`, `source_insight`
- `commitment`, `waiting_for`, `progress`
- `error_mode`, `surprise`

**Use when clearly applicable:**
- `ethics`, `provenance`, `hypothesis`, `limitation`, `openness`
- `pattern`, `gotcha`, `contact`, `context`
- `prompt_effectiveness`, `self_reflection`

### Retrospective Only (assigned during review)

- `slip` — Assigned when reviewing commitments vs outcomes
- `completion` — Assigned when marking things done
- `blocker_real` — Assigned when analyzing why something was stuck
- `blocker_excuse` — Assigned when pattern reveals avoidance

Haiku doesn't judge whether a blocker is real. You do, looking back at the evidence.

### Updated Extraction Prompt

Add to the prompt:
```
Note: Some categories are assigned retrospectively during weekly review, 
not during extraction. Focus on capturing the information; categorization 
of slip/completion/blocker types happens later with more context.
```

---

## 6. Tag normalisation edge cases

**Verdict:** You're right. The naive approach breaks.

### The Problem

```python
# Current code breaks on:
# analysis → analysi ❌
# status → statu ❌
# hypothesis → hypothesi ❌
# process → proces ❌
# series → serie ❌
```

### The Fix

**Option A: Exception list**

```python
SINGULAR_EXCEPTIONS = {
    'analysis', 'status', 'hypothesis', 'process', 
    'basis', 'thesis', 'series', 'species', 'synopsis'
}

def normalise_tag(tag: str) -> str:
    tag = tag.lower().strip()
    tag = re.sub(r'[_\s]+', '-', tag)
    tag = re.sub(r'[^a-z0-9-]', '', tag)
    tag = re.sub(r'-+', '-', tag).strip('-')
    
    # Only handle obvious cases, skip exceptions
    if tag not in SINGULAR_EXCEPTIONS:
        if tag.endswith('ies') and len(tag) > 4:
            tag = tag[:-3] + 'y'  # methodologies → methodology
    
    # Skip other plural rules — too error-prone
    return tag
```

**Option B: Skip automatic singularisation entirely**

Handle plurals in monthly `/tags` gardening. Less magic, fewer edge cases, more human oversight.

**Recommendation:** Option B. The monthly gardening is already designed for consolidation. Let it handle plurals too.

---

## 7. Manual memory capture

**Verdict:** Fair gap. Add explicit mechanism.

### Inline Capture

When user says "remember that [X]", Claude:
1. Parses the insight
2. Suggests category and tags
3. Writes directly to JSONL (doesn't wait for extraction)

```
User: Remember that the ethics board requires re-consent for linked data

Claude: ✓ Captured to memory:
  Category: ethics
  Content: "Ethics board requires re-consent if survey data linked to interviews"
  Tags: ethics, consent, data-linking
  
Saved to memories.jsonl
```

### Explicit Command

```markdown
# /remember

Manually capture a memory without waiting for extraction.

## Usage

/remember [content]
/remember category:[cat] [content]
/remember category:[cat] tags:[t1,t2] [content]

## Examples

/remember Ethics board requires re-consent for linked data
/remember category:decision Using PostgreSQL for memory store because of query complexity
/remember category:source_insight tags:gps-accuracy,field-methods Smith 2024 reports 3-5m degradation under canopy

## Behavior

1. Parse content and any explicit category/tags
2. If category not specified, suggest one and confirm
3. Apply tag normalisation
4. Write directly to memories.jsonl with source: "manual"
5. Confirm capture
```

### Schema Addition

Add `source` field to distinguish:
```json
{
  "id": "...",
  "source": "extraction" | "manual",
  "category": "...",
  ...
}
```

---

## 8. Thinking block truncation

**Verdict:** Increase limit, but keep truncation.

### The Tradeoff

| Limit | Pros | Cons |
|-------|------|------|
| 500 chars | Lower extraction cost | Misses deeper reasoning |
| 1500 chars | Captures reasoning structure | ~3x more tokens in extraction prompt |
| Full | Complete for research | Could be 20k+ tokens, expensive |

### Recommendation

**Increase to 1500 characters** for routine extraction. Haiku is cheap enough that the cost difference is negligible (~$0.001/session extra).

**Add deep extraction option** for research purposes:

```markdown
# /research-extract [session-id]

Deep extraction of a specific session with full thinking blocks.

## Use Case

When you want to study a particular session's reasoning in detail 
for LLM interaction research.

## Behavior

1. Load full transcript for session
2. Run extraction with complete thinking blocks (no truncation)
3. Tag all extracted memories with research_session: [session-id]
4. Costs more but captures complete reasoning
```

### Updated Extraction Code

```python
MAX_THINKING_CHARS = 1500  # Up from 500

# For /research-extract, pass max_thinking=None to disable truncation
def parse_transcript(transcript_path, last_uuid, max_thinking=MAX_THINKING_CHARS):
    # ...
    if block.get("type") == "thinking":
        thinking = block.get("thinking", "")
        if max_thinking:
            thinking = thinking[:max_thinking]
        text_parts.append(f"[THINKING]: {thinking}")
```

---

## Summary of Changes

| Issue | Action |
|-------|--------|
| Retrieval | Add SessionStart injection + `/recall` command. Defer MCP server. |
| Error handling | Add logging, cursor-after-success, `/catchup` command |
| PostgreSQL | Include it, sequence after extraction works (days 3-4) |
| Zotero | Keep read direction + schema field. Defer write sync to Phase 2. |
| Categories | Keep 21, but distinguish extraction vs retrospective assignment |
| Tag normalisation | Skip automatic singularisation, handle in monthly gardening |
| Manual capture | Add `/remember` command, `source` field in schema |
| Thinking truncation | Increase to 1500 chars, add `/research-extract` for deep dives |

---

## Revised Implementation Sequence

### Phase 1: Core Extraction (Days 1-3)

1. Directory structure and empty files
2. `extraction-hook.py` with error handling
3. Hook configuration in `settings.json`
4. Test extraction produces valid JSONL
5. Basic retrieval: SessionStart injection
6. `/recall` command
7. `/remember` command for manual capture

### Phase 2: Query Infrastructure (Days 3-5)

1. PostgreSQL setup (Docker or native)
2. Run schema SQL
3. `sync-to-postgres.py` script
4. Cron job for sync
5. Test queries work
6. `/catchup` command

### Phase 3: Task System (Days 5-10)

1. Task file structure (FOCUS.md, SYSTEM.md, projects/)
2. Core commands: `/standup`, `/capture`, `/done`, `/focus`
3. SessionStart accountability hook
4. Memory integration (slip detection in extraction prompt)

### Phase 4: Reviews and Integrations (Days 10-14)

1. `/review` command with collaborator reports
2. `/process-email` command
3. `/sync-board` command
4. `/retro` command

### Phase 5: Zotero and Polish (Week 3+)

1. Zotero read integration (`/read`, `/cite`, `/synthesise`)
2. Zotero write sync (insights → notes)
3. `/tags` gardening command
4. `/research-extract` for deep analysis
