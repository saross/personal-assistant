# Progressive Disclosure / Multi-Tier Retrieval Plan

**Created:** 2026-04-05
**Updated:** 2026-04-10 (Phase 0 complete)
**Status:** Phase 0 done — ready for Phase 1 (Tier 2 autonomous fetch)
**Author:** Claude (research session while Shawn is AFK)
**Depends on:** session-archiving-redesign.md (Phases 1-2 complete),
memory system Phase 1c (summaries + compact format, complete)

### Decisions (2026-04-07)

1. **Tier 2 trigger:** Start gated (announce + confirm), relax to proactive later
2. **Phase order:** Phase 1 (Tier 2 fetch) before Phase 2 (bulk archive)
3. **Auto-metadata model:** Fix Haiku first, pilot local models separately
4. **Bulk archive:** Lightweight Haiku indexing first (~$0.55 with batch+cache);
   explore local models (Gemma 4, Qwen 3.6) for full-transcript processing
5. **Summary backfill:** Yes, re-run for 7,944 memories (~$0.20 with batch+cache)
6. **Reflection linkage:** Implement the full approach (all phases)
7. **Anonymisation:** Create sanitised examples at demo time, not in advance
8. **MCP server priority:** Deprioritised — progressive disclosure works without it
9. **Subagent sessions:** Archive as children of parent session
   (`{parent_archive}/subagents/{agent_id}.jsonl.gz`), preserving delegation chain
10. **Transcript retention:** Keep 99999-day cleanup until archive reliability proven,
    then reduce to ~30 days
11. **Cost optimisation:** Use Anthropic Batch API (50% off) + prompt caching
    (90% off cache reads) for all bulk Haiku operations. Combined: up to 95% reduction.
    Full-transcript indexing drops from ~$441 to ~$22 — revisit whether to do
    full rather than lightweight indexing at Phase 2.

---

## 1. Current State Assessment

### What exists and works

**Memory extraction pipeline** (`hooks/extraction-hook.py`):

- Fires on Stop, PreCompact, SessionEnd events
- Calls Haiku to extract structured memories from session transcripts
- Appends to `memories/memories.jsonl` (canonical source, 20,202 memories)
- Each memory has: `id`, `session_id`, `category`, `content`, `summary`,
  `confidence`, `research_tags`, `source_context`, `project`, `created_at`
- 20,144 of 20,202 memories have `session_id` populated (99.7%)
- 12,258 of 20,202 memories have `summary` populated (60.7% — backfill
  covered the first 7,716; ~7,944 generated since without summaries)

**Session-start retrieval** (`hooks/session-start-retrieval.py`):

- Loads Level 1 compact index at session start (90 slots total)
- Uses `summary` field when available, falls back to `content`
- Project-aware bucketing: 60 same-project + 20 other-project + 10 constraints
- Tag-overlap scoring for cross-project relevance
- Scratchpad injection (Claude's learning log)

**Session archiving** (`cc-session archive --from-hook`, cc-session-toolkit):

- Dual async hooks fire on SessionEnd and PreCompact
- Archives to `~/cc-archives/{project}/{timestamp}_{short-id}/`
- Produces `session.jsonl.gz` + `session.meta.json`
- Global `CATALOG.json` with 14 sessions archived so far
- PostgreSQL sync runs chained after archive (`sync-sessions-to-postgres.py`)
- Sessions table in `claude_memories` database with full-text search (FTS)

**PostgreSQL query layer** (`scripts/schema.sql`):

- `memories` table with FTS indexes, trigram search, tag GIN indexes
- `sessions` table with FTS across title/purpose/prompt_summary
- `active_memories` and `research_memories` views
- `untagged_sessions` and `session_costs` views
- Rebuild-from-scratch capability via `scripts/rebuild-postgres.py`

**Recall command** (`commands/recall.md`):

- Free-text search against JSONL (always available)
- Session search against PostgreSQL (graceful fallback)
- Category and tag filtering
- Functions as the current Level 2 retrieval mechanism

**Reflect pipeline** (`skills/reflect/SKILL.md`):

- End-of-session reflection protocol, priority-ordered documents
- Session reflection with rotating prompt pool
- Conditional documents (abductive reasoning) triggered by content
- Outputs: `session-reflection.md`, `session-log.md`, `working-notes.md`,
  `abductive-reasoning.md` in per-project `docs/notes/reflections/`

**cc-session-toolkit** (`~/Code/cc-session-toolkit/`):

- Archive, catalogue, extraction, naming, project, queries, summarise modules
- Six query prompts in `data/queries/` (summarise, decisions, methodology,
  artefacts, issues, populate-metadata)
- Archiving specification (1,140 lines) aligned with RDA IG Three Ps framework
- PostgreSQL query module with search and untagged-sessions functions

### What is broken or incomplete

1. ~~**Auto-metadata is failing.**~~ **Fixed (2026-04-10).** Root cause:
   hook's `export $(grep ... .env | xargs)` was not reliably passing
   `ANTHROPIC_API_KEY` to the Haiku call. Fix: added `_ensure_anthropic_api_key()`
   fallback in `cc-session-toolkit/archive.py` that reads `.env` directly.
   Added file-based logging to `auto-metadata.log`. All 20 archived sessions
   now have proper Haiku-generated metadata. Synced to PostgreSQL.

2. **Archive coverage is tiny.** Only 20 sessions archived vs. 259 unique
   session IDs in the memory system (and 603 main session files in
   `~/.claude/projects/`). The archiving hooks have been running since
   mid-March, but most historical sessions were never archived.

3. ~~**Summary backfill is incomplete.**~~ **Resolved (2026-04-10).** The
   original estimate of 7,944 missing summaries was stale — the extraction
   hook had been generating summaries correctly for new memories. Only 1
   memory lacked a summary (Haiku had corrupted the ID during the original
   backfill). Patched manually. 21,098/21,098 memories now have summaries.

4. **No `source_messages` tracking.** Memories lack the message UUIDs linking
   back to specific transcript exchanges. This means Level 3 retrieval can
   only do fuzzy content matching, not precise lookups.

5. **No Level 2 "announce and fetch" behaviour.** The session-start hook
   injects Level 1 summaries, and `/recall` provides manual Level 2 retrieval,
   but there is no mechanism for CC to autonomously recognise topic matches
   and fetch full memories mid-conversation. This is the core progressive
   disclosure behaviour that does not yet exist.

6. **No Level 3 retrieval path.** No code exists to decompress an archived
   session transcript and extract relevant sections. The architecture is
   designed but unbuilt.

### Raw data inventory

| Asset | Location | Volume | Format |
|---|---|---|---|
| Active memories | `memories/memories.jsonl` | 21,098 records, ~16 MB | JSONL |
| Raw transcripts | `~/.claude/projects/` | 603 main + 1,236 subagent, 4.8 GB | JSONL |
| Archived transcripts | `~/cc-archives/` | 20 sessions, compressed | JSONL.gz + meta.json |
| PostgreSQL memories | `claude_memories.memories` | Derived from JSONL | Table |
| PostgreSQL sessions | `claude_memories.sessions` | 20 rows (all with metadata) | Table |

---

## 2. Proposed Architecture

### Tier model (refined)

The original three-level model from `session-archiving-redesign.md` remains
sound, but the names and transitions need refinement based on what actually
exists.

```text
Tier 1: Awareness Index (always loaded, session start)
  What CC knows it knows — category + summary + tags + date
  90 compact entries, ~1,300 tokens
  Source: session-start-retrieval.py → memories.jsonl

Tier 2: Full Memory (on demand, mid-conversation)
  The complete memory content, confidence, tags, source context
  Fetched when conversation matches Tier 1 tags
  Source: /recall or autonomous fetch → memories.jsonl or PostgreSQL

Tier 3: Source Transcript (on demand, rare)
  The original conversation section that generated the memory
  Fetched when deep context is needed (why was this decided?)
  Source: session archive → ~/cc-archives/ → decompress + extract
```

### Data flow diagram

```text
Session in progress
  │
  ├─ Stop hook ──────────────→ extraction-hook.py
  │                              │
  │                              ├─ Haiku extracts memories (with summary)
  │                              ├─ Appends to memories.jsonl
  │                              └─ (future) Records source_messages UUIDs
  │
  ├─ SessionEnd / PreCompact ─→ extraction-hook.py (same as above)
  │                           ─→ cc-session archive --from-hook
  │                              │
  │                              ├─ Compress transcript to ~/cc-archives/
  │                              ├─ Generate auto-metadata (title, purpose, tags)
  │                              ├─ Write session.meta.json
  │                              └─ sync-sessions-to-postgres.py
  │
  └─ (future) /reflect ───────→ Reflection documents (per-project)
                                  │
                                  └─ (future) Link reflections to sessions

Next session starts
  │
  └─ SessionStart hook ────────→ session-start-retrieval.py
                                  │
                                  ├─ Load Tier 1 index (compact summaries)
                                  ├─ Load scratchpad
                                  └─ (future) Include Tier 2 fetch instructions

Mid-conversation (future)
  │
  ├─ CC detects topic match ──→ Autonomous Tier 2 fetch
  │     with Tier 1 tags          (announce → query → inject)
  │
  └─ Deep context needed ─────→ Tier 3 transcript retrieval
        (user or CC triggers)     (decompress → search → extract section)
```

### Tier 2 autonomous retrieval design

This is the key missing capability. Two implementation approaches:

**Option A — Tool-based retrieval (recommended):**
Add a custom MCP tool or hook that CC can invoke to fetch full memories by
topic. The Tier 1 injection includes an instruction like:

> When a topic matches tags in the Memory Index above, fetch full content
> using: `psql -d claude_memories -c "SELECT * FROM active_memories
> WHERE research_tags && ARRAY['topic-tag'] ORDER BY created_at DESC LIMIT 5"`
> Announce the retrieval: "I have memories about [topic], retrieving details..."

CC already has Bash access and can run psql. This requires no new code — just
a revised instruction block in the session-start output and possibly a helper
script for cleaner invocation.

**Option B — MCP memory server:**
Build an MCP server exposing memory queries as tools. This is the long-term
vision (identified in `planning/memory-system-benchmarking.md` as the highest-
value gap to close). It would enable cross-tool access (Claude.ai, Cursor,
etc.) and cleaner invocation than raw psql. But it is a larger project and
not required for the core progressive disclosure behaviour.

**Recommendation:** Start with Option A (psql-based, zero new code for the
retrieval mechanism itself). Migrate to Option B when the MCP server is built.
The instruction block in the session-start output is the same regardless.

### Tier 3 transcript retrieval design

Two sub-problems: (a) finding the right session, (b) extracting the relevant
section.

**Finding the session:**

```sql
-- From a memory ID, find the session archive
SELECT s.archive_path, s.title, s.started_at
FROM sessions s
JOIN memories m ON m.session_id = s.id
WHERE m.id = 'memory-id-here';
```

This requires `session_id` in memories (99.7% coverage) and `archive_path`
in sessions. Currently only 14 sessions are archived, so coverage is minimal.

**Extracting the relevant section:**

```python
# Pseudocode for Tier 3 extraction
def extract_section(archive_path, search_terms):
    """Decompress archive, find relevant exchanges, return context window."""
    transcript = decompress_jsonl_gz(archive_path / "session.jsonl.gz")
    # Find exchanges matching search terms
    matches = [entry for entry in transcript
               if any(term in entry.get('message', '') for term in search_terms)]
    # Return a window of N exchanges around each match
    return extract_windows(transcript, matches, window=10)
```

With 1M context windows, an entire session transcript (~100K tokens average)
fits in ~10% of context. For most cases, loading the full transcript is
simpler than section extraction. The progressive disclosure value at Tier 3
is not token savings but **focus** — knowing *which* session to load.

---

## 3. Dependencies and Prerequisites

### Must fix before implementation — ALL COMPLETE ✓

| # | Item | Status | Completed |
|---|---|---|---|
| P0 | ~~**Fix auto-metadata**~~ | Fixed: fallback .env loader + logging. 20/20 sessions have metadata. | 2026-04-10 |
| P1 | ~~**Complete summary backfill**~~ | Only 1 memory needed fixing. 21,098/21,098 = 100%. | 2026-04-10 |
| P2 | ~~**Verify summary generation**~~ | Confirmed: extraction hook generates summaries correctly. | 2026-04-10 |

### Should do before or during implementation

| # | Item | Enables | Effort |
|---|---|---|---|
| D1 | **Bulk archive historical sessions** — 603 main sessions in `~/.claude/projects/` need archiving to `~/cc-archives/`. `cc-session archive` can process them, but needs a batch mode. | Tier 3 coverage (currently 14/603 = 2.3%) | Medium — write a batch script, ~600 sessions to process |
| D2 | ~~**Fix or backfill auto-metadata for archived sessions**~~ — Done (2026-04-10). All 20 sessions backfilled via `scripts/backfill-session-metadata.py`. | Session search quality | **Complete** |
| D3 | **Add `source_messages` to extraction** — modify extraction prompt to record which transcript message UUIDs generated each memory. | Precise Tier 3 retrieval (vs fuzzy search) | Medium — prompt modification + schema change |

### Nice to have

| # | Item | Value | Effort |
|---|---|---|---|
| N1 | **MCP memory server** — expose memories and sessions as MCP tools. | Cross-tool access, cleaner Tier 2 invocation | Large |
| N2 | **Semantic search (pgvector)** — vector embeddings for conceptual similarity. | Better Tier 2 matching for conceptual queries | Medium |
| N3 | **Reflection–session linkage** — link `/reflect` output to session archives. | RDA WG transparency, richer session context | Small |

---

## 4. Implementation Phases

### Phase 0: Foundations (prerequisites, do first) — COMPLETE ✓

**Goal:** Fix the broken plumbing so the existing infrastructure works as
designed.

**Completed 2026-04-10:**

1. ~~**Debug auto-metadata**~~ — Root cause: hook's env export not reliably
   passing API key. Fixed with `_ensure_anthropic_api_key()` fallback in
   `cc-session-toolkit/archive.py`. Added `_log_metadata_event()` for
   file-based diagnostics. All 20 archived sessions backfilled via
   `scripts/backfill-session-metadata.py`. Tests updated to mock Anthropic
   client (4 tests). Actual cost: ~$0.02 (18 Haiku calls).

2. ~~**Summary backfill**~~ — Only 1 memory lacked a summary (not 7,944).
   The extraction hook was generating summaries correctly. Patched the
   single orphan manually (Haiku had corrupted its ID during original
   backfill). 21,098/21,098 = 100% coverage.

3. ~~**Verify extraction prompt**~~ — Confirmed: last 10 memories all have
   summaries. Extraction working as designed.

**Actual effort:** ~2 hours
**Actual cost:** ~$0.02

### Phase 1: Tier 2 Autonomous Fetch (core progressive disclosure)

**Goal:** CC can recognise topic matches against Tier 1 and autonomously
retrieve full memories mid-conversation.

1. **Revise session-start output** in `session-start-retrieval.py` to include
   explicit Tier 2 retrieval instructions. Add a block like:

   ```text
   ## Retrieval Instructions

   When a conversation topic matches tags in the Memory Index above, you
   should retrieve full memory content. Use one of:

   1. psql: SELECT id, category, content, confidence, research_tags, created_at
      FROM active_memories
      WHERE research_tags && ARRAY['matching-tag']
      ORDER BY created_at DESC LIMIT 5;

   2. /recall [topic] — manual invocation by user

   Announce retrievals: "I have memories about [topic], retrieving details..."
   ```

2. **Write a helper script** (`scripts/fetch-memories.py`) that accepts a
   topic/tag query and returns formatted full memories. This is cleaner than
   raw psql and handles the PostgreSQL-unavailable fallback to JSONL grep.
   CC invokes it via Bash.

3. **Test the end-to-end flow:** Start a session, observe Tier 1 loading,
   discuss a topic covered in memories, verify CC fetches and announces
   Tier 2 retrieval.

**Estimated effort:** 4-6 hours
**Estimated cost:** $0 (no API calls beyond normal session costs)

### Phase 2: Historical Archive Migration

**Goal:** Archive all historical sessions so Tier 3 has data to work with.

1. **Write `scripts/bulk-archive.py`** — walks `~/.claude/projects/` for
   all session JSONL files not yet in `~/cc-archives/`. Calls cc-session-toolkit's
   archive function for each. Includes:
   - Deduplication against existing CATALOG.json
   - Trivial-session filtering (configurable min turns)
   - Progress reporting
   - Auto-metadata generation (Haiku, lightweight — first/last messages +
     user messages only, not full transcript)

2. **Run the bulk archive.** 603 sessions at ~20K input tokens each.
   - Haiku cost: ~$10.85 (see cost analysis below)
   - Alternative: run on sapphire/zbook via Ollama for $0, ~3.4 hours
   - Produces ~600 compressed archives + metadata in `~/cc-archives/`

3. **Sync to PostgreSQL** — run `sync-sessions-to-postgres.py --full-resync`
   to populate the sessions table with all 600+ sessions.

4. **Verify session search** — use `/recall` to search sessions by topic
   and confirm FTS returns meaningful results.

**Estimated effort:** 6-8 hours
**Estimated cost:** ~$10 via Haiku or $0 via local models

### Phase 3: Tier 3 Transcript Retrieval

**Goal:** CC can follow a memory back to its source conversation.

1. **Write `scripts/fetch-transcript-section.py`** — accepts a memory ID or
   session ID, decompresses the archive, and extracts relevant sections.
   Options:
   - Full transcript mode (load entire session — viable with 1M context)
   - Section mode (extract a window around matching content)
   - Summary mode (return session metadata + linked memories without
     the full transcript)

2. **Add Tier 3 instructions** to session-start retrieval output:

   ```text
   For deep context on any memory, retrieve the source session:
   python3 ~/personal-assistant/scripts/fetch-transcript-section.py --memory-id <id>
   ```

3. **Add `source_messages` tracking to extraction** (optional, enhances
   precision). Modify the extraction prompt to ask Haiku to cite which
   message UUIDs contributed to each memory. Add `source_messages TEXT[]`
   column to PostgreSQL schema. This enables jumping directly to the
   relevant exchange rather than searching the full transcript.

**Estimated effort:** 8-12 hours
**Estimated cost:** $0 (on-demand retrieval, no batch processing)

### Phase 4: Integration and Refinement

**Goal:** Connect progressive disclosure to the /reflect pipeline and
prepare for RDA WG transparency work.

1. **Link reflections to sessions.** When `/reflect` writes a session
   reflection, record the session_id in the reflection document header
   or a separate index. This creates a bidirectional path:
   session → memories → reflection documents.

2. **Add reflection content to Tier 3.** When retrieving a session's
   context, also surface any reflection documents that reference it.
   Reflections are higher-quality, curated analysis of session dynamics
   — they complement the raw transcript.

3. **MCP memory server** (if prioritised). Expose Tier 1/2/3 retrieval
   as MCP tools. This enables:
   - Claude.ai web access to memories
   - Cursor/other MCP-capable tools
   - Cleaner invocation than Bash + psql
   - Potential for the RDA WG to demonstrate the Three Ps framework
     with a working retrieval system

4. **Tune slot allocation** based on usage data. The current 90 slots
   (60 + 20 + 10) may need adjustment once Tier 2 autonomous fetch is
   active. If CC frequently fetches the same memories, the Tier 1 budget
   could shift toward broader coverage (more slots, shorter summaries).

**Estimated effort:** 10-15 hours
**Estimated cost:** Variable (MCP server is the largest item)

---

## 5. Cost Analysis

### Transcript reprocessing

The 4.8 GB of raw transcripts in `~/.claude/projects/` (603 main sessions,
1,236 subagent sessions) is the largest processing task.

| Approach | Scope | Input tokens | Standard cost | Batch+cache cost | Time |
|---|---|---|---|---|---|
| **Full transcript Haiku** | 603 sessions, full content | ~550M tokens | ~$441 | ~$22 | Minutes (parallel) |
| **Lightweight Haiku** (first/last + user messages) | 603 sessions, excerpts | ~12M tokens | ~$11 | ~$0.55 | Minutes |
| **Local model** (Ollama, sapphire/zbook) | 603 sessions, excerpts | ~12M tokens | $0 | $0 | ~3.4 hours |
| **On-demand only** (no batch) | Per-request | ~900K tokens/session | $0.72/session | — | Seconds |

**Decision (2026-04-07):** Start with lightweight Haiku indexing via batch
API + prompt caching (~$0.55 for all 603 sessions). This gets searchable
metadata in place immediately. In parallel, pilot local models (Gemma 4,
Qwen 3.6 — both released April 2026) for full-transcript processing.

With batch+cache, full-transcript indexing drops to ~$22 — making it a
viable option if local model quality proves inadequate or if we want Haiku
as a quality baseline. Revisit at Phase 2.

### Ongoing costs

| Item | Frequency | Cost |
|---|---|---|
| Memory extraction (Haiku) | Every Stop/SessionEnd/PreCompact | ~$0.01/session |
| Auto-metadata at archive | Every SessionEnd/PreCompact | ~$0.02/session |
| Summary generation (extraction) | Included in extraction | $0 incremental |
| Tier 2 autonomous fetch | Mid-conversation, on demand | $0 (local psql query) |
| Tier 3 transcript retrieval | Rare, on demand | $0 (local file decompression) |
| **Monthly total** (~120 sessions) | | ~$3.60/month |

### Local model alternatives

For batch operations (summary backfill, metadata generation), local models
on sapphire (16 GB VRAM, ROCm) or zbook (96 GB VRAM) are viable:

- **sapphire:** Gemma 3 27B or QwQ 32B via Ollama. ~1K tokens/sec.
  Adequate for metadata generation. Check loaded models before loading
  new ones (16 GB VRAM limit).
- **zbook:** Faster inference, larger models possible. But noisier
  (fan consideration for extended runs).
- **Quality tradeoff:** Haiku-generated summaries were used for the original
  backfill and proved adequate. Local models need quality validation against
  Haiku before committing to batch use. Run a pilot: process 20 sessions
  with both Haiku and a local model, compare output quality.

---

## 6. Integration with /reflect and RDA Working Group

### Current state of /reflect

The `/reflect` skill produces structured end-of-session reflections stored
in per-project `docs/notes/reflections/` directories. These documents
capture what happened (session-log), why it matters (session-reflection),
and how it connects to broader research (abductive-reasoning, working-notes).

The reflect pipeline currently has **no machine-readable link** to the
session that generated the reflection. The session date and project are
embedded in headers, but there is no `session_id` field.

### Integration design

```text
Session Archive                Memories                    Reflections
  session.meta.json    ←───→    memories.jsonl    ←───→    session-reflection.md
  - session_id                  - session_id               - session_id (NEW)
  - three_ps                    - category, tags           - prompt pool responses
  - archive_path                - content, summary         - working notes

  Linking: session_id is the foreign key across all three.
  Query: "Show me the full context of decision X" returns:
    1. The memory (Tier 2)
    2. The session metadata (archive)
    3. The reflection entry (if any)
    4. The raw transcript section (Tier 3)
```

**Changes needed:**

1. Modify `/reflect` SKILL.md to include `session_id` in the dated section
   header of each reflection entry. The session ID is available from the
   hook input or can be read from `~/.claude/.session_id` (if Claude Code
   exposes it to skills — needs verification).

2. Add a `reflections` column or table to PostgreSQL linking session_id to
   reflection file paths and entry line numbers. This enables:
   ```sql
   SELECT r.file_path, r.entry_date, s.title
   FROM reflections r
   JOIN sessions s ON r.session_id = s.id
   WHERE s.project = 'map-reader-llm';
   ```

3. When Tier 3 retrieves a session's context, also check for and surface
   any linked reflection entries.

### RDA Working Group relevance

The RDA Interest Group (IG) on Documenting GenAI Interactions develops
frameworks for transparent documentation of human-AI collaboration. The
Three Ps framework (Prompt, Process, Provenance) is a core output.

Progressive disclosure directly serves the IG's goals:

- **Tier 1 → Prompt metadata.** The compact index (category + tags +
  summary) is analogous to the Prompt facet — what topics were addressed.

- **Tier 2 → Process documentation.** Full memory content captures
  decisions and their rationale — the Process facet of how the tool was used.

- **Tier 3 → Provenance evidence.** The raw transcript is the ultimate
  provenance record — the complete chain of reasoning.

- **Reflections → Human assessment.** The `/reflect` outputs provide
  the researcher's assessment of the interaction quality and dynamics,
  which the Three Ps framework calls for but most implementations lack.

The progressive disclosure system would be a **concrete implementation
demonstrating the Three Ps at scale** — not just for a single session
(as Brian's denubis-plugins and cc-session-toolkit do today) but across
an entire research workflow. This is the kind of evidence the IG needs
for its recommendations.

**Potential outputs:**

- An RDA recommendation citing this system as a reference implementation
- A joint paper with Brian comparing automated (our approach) vs.
  interactive (his approach) Three Ps implementation
- A demonstration dataset: the personal-assistant memory + session archive,
  suitably anonymised, as a worked example of research transparency

---

## 7. Open Questions for Shawn

### Architecture decisions

1. **Tier 2 trigger mechanism:** Should CC autonomously fetch full memories
   when it detects a topic match (proactive), or should it announce
   "I have memories about X — retrieve?" and wait for confirmation
   (gated)? Proactive is smoother but uses context without explicit
   consent. Gated preserves user control. The session-archiving-redesign
   document planned for gated, but with 1M context the cost argument
   is weaker. **Recommendation:** Start gated, relax to proactive once
   the system proves reliable.

   Shawn: Agree, let's start gated

2. **Historical session archiving priority:** The 603 unarchived sessions
   represent significant historical context. Should we prioritise bulk
   archiving (Phase 2) before Tier 2 autonomous fetch (Phase 1), or
   get the core progressive disclosure working first with the 14 archived
   sessions? **Recommendation:** Phase 1 first — it works without archives
   (Tier 2 is memory-based, not transcript-based).

   Shawn: Agree, let's get Phase 1 working first.

3. **Auto-metadata model:** When fixing auto-metadata (P0), should we
   use Haiku (proven for extraction, ~$0.02/session) or test a local model
   on sapphire? The cc-session-toolkit already has the Haiku integration
   code; local would need new code. **Recommendation:** Fix Haiku first
   (smallest path to working), pilot local models separately.

   Shawn: Agree, let's use Haiku

### Cost and resource decisions

4. **Bulk archive approach:** Haiku (~$11 for lightweight indexing of 603
   sessions) vs. local model ($0 but ~3.4 hours on sapphire)? If local,
   which model — Gemma 3 27B or QwQ 32B?

   Shawn: What would optimal (vs. 'lightweight') indexing cost? I'd want 
   to test local models before committing to one, noting that Gemma 4 and Qwen 3.6 
   were just released this week.

5. **Summary backfill scope:** Re-run backfill for the 7,944 memories
   missing summaries (~$4 Haiku cost), or accept the gap and only
   generate summaries for new memories going forward? The gap means
   39% of Tier 1 entries show truncated content instead of purpose-written
   summaries. **Recommendation:** Re-run the backfill; $4 is negligible
   and the quality difference is significant.

   Shawn: Agree, backfill.

### RDA WG and research

6. **Reflection linkage priority:** The `/reflect` → session linkage
   (Phase 4) is straightforward but adds complexity. Is this worth doing
   before the RDA WG output deadline, or is it a post-publication
   refinement? Need to know the IG's timeline.

   Shawn: I'd like to implement the entire approach (assuming that no emergent
   problems, issues, or opportunities arise that lead us to change course).

7. **Anonymisation requirements:** If the progressive disclosure system
   is demonstrated as a reference implementation, what level of
   anonymisation is needed for the memory and session data? The data
   submodule is private, but demonstration might require sanitised
   examples.

   Shawn: Good question - if we do a demo can we create a sanitised example 
   at that time?

8. **MCP server priority:** The MCP memory server was identified as the
   highest-value gap in the benchmarking analysis. Does progressive
   disclosure change that priority (since Tier 2 works via psql without
   MCP), or does the cross-tool access argument still dominate?

   Shawn: Yes, I think progressive disclosure changes this priority, 
   in that everything works without MCP (acknowledging that MCP offers 
   new interoperability options). 

### System design

9. **Subagent session handling:** The 1,236 subagent sessions in
   `~/.claude/projects/` are fragments of parent sessions. Should they
   be archived separately, folded into parent session archives, or
   ignored? They represent 282 MB (vs. 4.1 GB for main sessions).

   Shawn: What is your recommendation here? What presentation of the subagents 
   would best acheive our *intent* of (a) gaining practical utility from having 
   access to the 'Eidetic memory' that session transcripts represent, and (b) 
   translating open science best practices to the LLM realm.

10. **Session transcript retention in `~/.claude/`:** Claude Code's
    `cleanupPeriodDays` is set to 99999 (effectively never clean up).
    Once sessions are archived to `~/cc-archives/`, should this be
    reduced? The raw transcripts are 4.8 GB and growing. But reducing
    cleanup risks losing sessions if the archive hook fails silently.
    **Recommendation:** Keep the high retention period until archive
    reliability is proven (P0 fix + monitoring).

    Shawn: Yes, agree - we keep it until we're sure things are working, then we 
    return to a ~30 day cleanup.

---

## 8. Summary of Recommendations

1. ~~**Fix auto-metadata first**~~ (P0). **Done 2026-04-10.**

2. ~~**Complete summary backfill**~~ (P1). **Done 2026-04-10.** 100% coverage.

3. **Implement Tier 2 autonomous fetch** (Phase 1). Revise session-start
   output with retrieval instructions, write a helper script. This is
   the core new capability — prerequisites are cleared.

4. **Bulk archive historical sessions** (Phase 2). ~$11 via Haiku or
   $0 via local models. Gets Tier 3 coverage from 2.3% to near 100%.

5. **Build Tier 3 retrieval** (Phase 3). Write the decompression and
   extraction script. With 1M context, full-transcript loading is
   viable for most sessions.

6. **Connect to /reflect and RDA WG** (Phase 4). Add session_id to
   reflections, link the three data streams, prepare for IG outputs.

Total estimated cost: ~$23-25 (Haiku batch+cache for everything) or
~$0.75 (batch+cache for backfill + lightweight indexing, local models
for full-transcript processing).

Total estimated effort: 30-45 hours across 4 phases, suitable for
evening/weekend infrastructure work over several weeks.

**Next action:** Start Phase 1 — Tier 2 autonomous fetch.
