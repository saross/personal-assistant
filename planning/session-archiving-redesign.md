# Session Archiving Redesign

**Status:** Phase 1 implemented (2026-03-15). Phases 4-5 partially superseded by memory system Phase 1c. 1M context window now available — changes Level 3 calculus.
**Created:** 2026-02-15
**Context:** Weekend infrastructure review of cc-session-toolkit archiving system

---

## Problem Statement

The current session archiving workflow (cc-session-toolkit) is entirely manual:
the user runs `cc-session archive` after a session, optionally provides metadata
interactively, and archives are stored per-project. This creates two problems:

1. **Sessions are lost** when the user forgets to archive (which is most of the
   time). Claude Code may clean up old session files, and compaction/clear events
   destroy full transcripts permanently.
2. **Cross-project querying is impossible** without manual aggregation. Each
   project maintains its own `CATALOG.json` with no global index.

## Goals

1. **Automated capture** — every session is archived without human intervention
2. **Centralised storage** — single canonical archive with cross-project querying
3. **Split archive from enrichment** — capture is automated; metadata enrichment
   is interactive and can happen later
4. **Reuse existing code** — extend cc-session-toolkit rather than building from
   scratch

---

## Current Architecture

### cc-session-toolkit (v0.1.0)

**Storage model:** Per-project. Each project stores archives in its own
`{project-root}/archive/cc-sessions/{project-name}/{session-dirs}/`.

**Archive workflow:**
1. User runs `cc-session archive` (manual invocation)
2. Toolkit discovers session files in `~/.claude/projects/{encoded-path}/`
3. Extracts statistics (turns, tokens, duration, tool calls, thinking blocks,
   artifacts, relationship hints)
4. Copies transcript to project's archive directory (optional gzip)
5. Optionally generates interactive metadata (title, purpose, tags, Three Ps)
6. Writes `session.jsonl[.gz]` + `session.meta.json`
7. Updates project's `CATALOG.json`

**Catalogue:** Per-project `CATALOG.json` (schema v1.1) with tag index,
relationship graph, and project rollup. No cross-project aggregation.

**Metadata schema (v1.1):**
- Session: id, timestamps, duration
- Project: name, directory
- Model: provider, model_id, access_method
- Thinking blocks: ethics metadata (sharing preference, use constraints)
- Relationships: continues, continuedBy, isPartOf, references, etc.
- Artifacts: created/modified/referenced files with types
- Statistics: turns, tokens, tool calls, thinking blocks, tool outputs, cost
- Auto-generated: title, purpose, tags
- Three Ps: prompt summary, process summary, provenance summary
- Archive: JSONL path, SHA256, byte counts, compression

### Community Approaches

**simonw/claude-code-transcripts:**
- Converts transcripts to paginated HTML with timeline index
- Batch processing via `all` command across projects
- No metadata enrichment or structured archiving
- Useful as an export format, not a storage system

**denubis-plugins (Denubis/denubis-plugins):**
- Manual `/transcript` skill (not hook-based)
- Interactive metadata enrichment using Three Ps framework (IDW2025)
- Proleptic reasoning: "what won't make sense in 6 months?"
- Multi-format output: SUMMARY.md + index.html + session.meta.json
- Per-project storage in `./ai_transcripts/`
- Wraps simonw's tool for HTML generation
- Strength: high-quality metadata through mandatory interactivity
- Weakness: depends on user remembering to invoke it
- Weakness: `claude-transcript-archive` CLI wrapper not included in repo
- Weakness: no cross-session search or indexing

**GWUDCAP/cc-sessions:**
- Task-centric persistence in markdown, not transcript archiving
- Different philosophy (persist task state, not session transcripts)

### Available Hook Events

Claude Code provides these relevant lifecycle events:

| Event | When it fires | Transcript accessible? | Matcher values |
|-------|--------------|----------------------|----------------|
| `SessionEnd` | Exit, `/clear`, logout | Yes — last chance | `clear`, `logout`, `prompt_input_exit`, `other` |
| `PreCompact` | Before `/compact` or auto-compact | Yes — full pre-compaction | `manual`, `auto` |
| `Stop` | After every Claude response | Yes — partial | None |
| `SessionStart` | Startup, resume, clear, compact | No (empty/compacted) | `startup`, `resume`, `clear`, `compact` |

**Key constraints:**
- Hooks receive `session_id`, `transcript_path`, `cwd` via stdin (JSON)
- Timeout: configurable up to 600 seconds (10 minutes)
- `async: true` mode: runs in background, cannot return decisions
- SessionEnd with `reason: "clear"` is the last chance before transcript erasure
- PreCompact is the last chance before compaction summarises the transcript

---

## /review-implementation Analysis

A structured review (using the /review-implementation skill) of the proposed
plan identified several improvements. Full protocol results below.

### Phase 1: Capability Scan (What Else Exists?)

**Hook capabilities we initially overlooked:**
- `async: true` — hooks can run in background without blocking session end
- `matcher` support — can skip archiving trivial sessions (<5 turns) or
  sessions that ended immediately after `/clear`
- 600-second timeout — even with an LLM API call for auto-metadata, we have
  headroom

**Storage alternatives:**
- Don't copy transcripts at all — store path references to
  `~/.claude/projects/`. Cheaper but fragile (CC may clean up old sessions)
- SQLite or PostgreSQL catalogue instead of CATALOG.json — we already have
  PostgreSQL running for the memory system
- Compression — cc-session-toolkit already supports gzip (10x reduction)
- Remote storage on rpi-server (16TB free on QNAP) for large archives

**Metadata alternatives:**
- LLM-generated metadata at capture time — the extraction hook already calls
  Haiku API at Stop events. Archive hook could do the same for title/purpose,
  giving 80% of metadata for free
- Derive from memory system — by SessionEnd, the extraction hook has already
  processed the transcript and stored memories containing key decisions and
  progress. Session metadata could reference those memories
- Proleptic reasoning (from denubis-plugins) — "what context will be missing
  in 6 months?" during interactive enrichment

**Cross-project querying:**
- PostgreSQL full-text search (same infrastructure as memories)
- simonw HTML rendering as complementary browsing format

### Phase 2: Exploitation Review (Are We Using It Fully?)

**Underused capabilities:**

1. **Hook async mode** — archive operations should be async. Never block
   session end. The user shouldn't notice archiving happening.

2. **cc-session-toolkit** — already has all the extraction, compression, and
   cataloguing logic. We should make it hook-compatible (`cc-session archive
   --from-hook`) rather than writing a new archiver from scratch.

3. **PostgreSQL** — already set up for memories with full-text search.
   Extending the schema to include session metadata is trivial. The sync
   pattern is proven: JSONL canonical, PostgreSQL derived, full-text search.

4. **Memory system integration** — extraction hook runs at Stop events and
   produces memories with category, tags, and content. Session metadata could
   link to memories extracted from that session, avoiding re-analysis.

5. **SessionEnd matchers** — can distinguish exit types and skip trivial
   sessions.

### Phase 3: Quantitative Audit

| Dimension | Original plan | Improved approach | Difference |
|-----------|-------------|-------------------|------------|
| Storage per session | ~2MB avg uncompressed | ~200KB avg gzipped | 10x reduction |
| Storage per month (~120 sessions) | ~240MB | ~24MB | Critical for git repo |
| Hook execution time | 3-10s synchronous | Non-blocking (async) | Session end not delayed |
| Metadata at capture | Stats only (title/purpose empty) | Stats + LLM title/purpose | 80% metadata for free |
| Implementation effort | New hook from scratch | `cc-session archive --from-hook` | Reuse existing code |
| Cross-project queries | CATALOG.json (manual) | PostgreSQL full-text search | Dramatically better |
| Git repo impact | ~240MB/month JSONL in personal-assistant | Gitignored transcripts, tracked index | Repo stays lean |

**Critical finding:** Storing raw transcripts in the personal-assistant git
repo will bloat it. At ~2MB per session and ~120 sessions/month, that's
~240MB/month of JSONL in git history. Even compressed (~24MB/month), this
accumulates permanently in git. Transcripts must be stored outside git or
gitignored.

### Phase 4: Recommendation Summary

**Three low-effort improvements:**

1. Store transcripts outside git (`~/cc-archives/` or gitignored within
   personal-assistant). Track catalogue/index in git, not JSONL files. Back
   up via rsync to rpi-server.

2. Use `async: true` for archive hooks. Archiving must never block session end.

3. Make cc-session-toolkit hook-compatible (`cc-session archive --from-hook`)
   rather than writing new archiver code.

**Two medium-effort improvements:**

4. Add LLM-generated metadata at capture time (call Haiku for title and
   one-sentence purpose during archive hook).

5. Extend PostgreSQL to session metadata — add `sessions` table alongside
   `memories` table.

---

## Revised Design

### Storage Architecture

```text
~/cc-archives/                          # Canonical archive (NOT git-tracked)
├── {project-name}/
│   └── {timestamp}_{short-id}/
│       ├── session.jsonl.gz            # Compressed transcript
│       └── session.meta.json           # Full metadata
├── CATALOG.json                        # Global catalogue (cross-project)
└── .backup-manifest                    # rsync tracking for rpi-server

~/personal-assistant/                   # Git-tracked hub
├── planning/session-archiving-...      # This document
└── scripts/
    └── schema.sql                      # Extended with sessions table
```

**Backup:** rsync to `rpi-server:/mnt/qnap/cc-archives/` (16TB free).
Frequency TBD (daily cron or manual).

### Automation: Dual-Hook Strategy

**Hook 1 — SessionEnd (async):**
Fires on exit, `/clear`, logout. Archives the full transcript before it
disappears.

```json
{
  "hooks": {
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "cc-session archive --from-hook --gzip --auto-metadata",
            "timeout": 120,
            "async": true
          }
        ]
      }
    ]
  }
}
```

**Hook 2 — PreCompact (async):**
Fires before compaction. Archives the full pre-compaction transcript.

```json
{
  "hooks": {
    "PreCompact": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "cc-session archive --from-hook --gzip --auto-metadata --pre-compact",
            "timeout": 120,
            "async": true
          }
        ]
      }
    ]
  }
}
```

### Archive Workflow (Automated)

When the hook fires:

1. **Read hook input** from stdin: `{session_id, transcript_path, cwd, ...}`
2. **Skip trivial sessions** — fewer than 5 turns or <1 minute duration
3. **Check for duplicates** — skip if session_id already archived (handles
   PreCompact followed by SessionEnd for the same session)
4. **Copy and compress** transcript to `~/cc-archives/{project}/{timestamp}_{short-id}/`
5. **Extract statistics** — reuse cc-session-toolkit's existing extraction:
   turns, tokens, duration, tool calls, thinking blocks, artifacts,
   relationship hints
6. **Auto-generate metadata** — call Haiku API for title and one-sentence
   purpose (budget: ~$0.001 per session, well within timeout)
7. **Write** `session.jsonl.gz` + `session.meta.json` (stats + auto-metadata;
   Three Ps and relationships left empty for later enrichment)
8. **Update** `CATALOG.json` (global, cross-project)
9. **Sync to PostgreSQL** if available (optional, non-blocking)

### Metadata Enrichment (Interactive, Later)

For sessions that warrant full metadata:

```bash
cc-session update <session-id>
```

Interactive enrichment adds:
- Three Ps (Prompt, Process, Provenance) — from cc-session-toolkit
- Proleptic reasoning — "what context will be missing in 6 months?"
  (adopted from denubis-plugins)
- Relationship tagging (continues, isPartOf, references)
- Manual tags and purpose refinement

A `SessionStart` hook could optionally nudge: "You have N untagged sessions.
Run `cc-session untagged` to review." (Low priority — implement after core
automation works.)

### New cc-session-toolkit Commands

| Command | Purpose |
|---------|---------|
| `cc-session archive --from-hook` | Hook-compatible archive mode (reads stdin) |
| `cc-session archive --auto-metadata` | Call Haiku for title/purpose |
| `cc-session archive --pre-compact` | Tag as pre-compaction snapshot |
| `cc-session untagged` | List sessions missing Three Ps |
| `cc-session search <query>` | Full-text search across all sessions (PostgreSQL) |

### PostgreSQL Extension

Add to existing `scripts/schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    project TEXT NOT NULL,
    title TEXT,
    purpose TEXT,
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    duration_minutes INTEGER,
    model TEXT,
    turns INTEGER,
    human_messages INTEGER,
    assistant_messages INTEGER,
    thinking_blocks INTEGER,
    tool_calls INTEGER,
    tokens_input INTEGER,
    tokens_output INTEGER,
    estimated_cost_usd NUMERIC(10, 4),
    prompt_summary TEXT,
    process_summary TEXT,
    provenance_summary TEXT,
    tags TEXT[],
    archive_path TEXT,
    needs_review BOOLEAN DEFAULT TRUE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_sessions_project ON sessions(project);
CREATE INDEX idx_sessions_started ON sessions(started_at DESC);
CREATE INDEX idx_sessions_tags ON sessions USING GIN(tags);
CREATE INDEX idx_sessions_fts ON sessions USING GIN(
    to_tsvector('english', COALESCE(title, '') || ' ' ||
    COALESCE(purpose, '') || ' ' || COALESCE(prompt_summary, ''))
);

CREATE VIEW untagged_sessions AS
SELECT id, project, title, started_at, duration_minutes
FROM sessions
WHERE needs_review = TRUE AND is_active = TRUE
ORDER BY started_at DESC;
```

### Deduplication Strategy

Sessions may trigger both PreCompact and SessionEnd hooks. Handle via:

1. Check `CATALOG.json` for existing `session_id` before archiving
2. If a pre-compaction snapshot exists and SessionEnd fires for the same
   session, keep the pre-compaction version (it has the full transcript)
3. Tag pre-compaction snapshots distinctly in metadata so they can be
   identified

---

## Comparison with denubis-plugins (Brian's Implementation)

Brian independently implemented the Three Ps framework in his
denubis-plugins repository (`/transcript` skill wrapping simonw's
claude-code-transcripts). Both implementations share the RDA IG origin
and align on core definitions (Prompt = what was asked, Process = how
the tool was used, Provenance = role in broader research context).

### Where the Implementations Diverge

| Dimension | cc-session-toolkit (ours) | denubis-plugins (Brian's) |
|-----------|--------------------------|---------------------------|
| Collection | Hybrid automated + LLM-assisted | Fully interactive, mandatory AskUserQuestion |
| Philosophy | Store complete, query on demand | Think proleptically — what's missing in 6 months? |
| Specification | Formal (1,600+ lines, versioned schema, FAIR mapping) | Procedural only (80-line SKILL.md, no schema doc) |
| Metadata depth | 11 sections: thinking blocks ethics, typed relationships, tool output stats | Three Ps + artifacts + basic statistics |
| Human-readable output | None pre-generated (LLM-intermediated on demand) | Pre-generated SUMMARY.md alongside metadata |
| Automation | High (target <2 min/session) | Low (requires confirmation at every step) |
| Catalogue | Per-project CATALOG.json with tag index | None |

### What We Should Adopt from Brian's Approach

**1. Proleptic reasoning question.** "What context will be missing in 6
months?" — already planned for the enrichment workflow (`cc-session update`).
This is the single most valuable design idea in Brian's implementation.

**2. The framing shift: metadata for understanding, not just finding.**
Our original philosophy ("metadata for finding, not reading") optimises
for discovery. Brian's proleptic framing optimises for future
interpretability. Both are needed. Practical implications:

- **Three Ps should encode rationale, not just description.** "Implemented
  batch API module" is findable. "Implemented batch API because concurrent
  approach hit rate limits at scale; chose batch over streaming because
  workload is embarrassingly parallel" is understandable. The
  `populate-metadata.md` prompt should be tuned to elicit *why*, not just
  *what*.

- **Relationship tagging becomes higher value.** The `continues`,
  `isPartOf`, `supersedes` predicates are the difference between an
  isolated session and a session in narrative context. Worth prioritising
  in auto-metadata — even a simple "this continues the most recent session
  in the same project" heuristic covers most cases.

- **The memory system is already the understanding layer.** Memories
  extracted from sessions (via the extraction hook) are condensed, tagged,
  categorised decisions and insights. If session metadata links to memory
  IDs via the shared `session_id` field, you get on-demand understanding
  without pre-generating summaries. Query a session, get its memories.
  The infrastructure exists; it needs the bidirectional link wired up.

- **Query prompt quality IS output quality.** If human-readable content
  is always LLM-intermediated, the six query prompts in `data/queries/`
  are the real interface to the archive. They deserve the same
  `/improve-prompt` treatment as any critical prompt. The improve-prompt
  skill is proving exceptionally effective — these queries are high-value
  candidates.

**3. We are NOT adopting pre-generated SUMMARY.md.** Brian pre-generates
a human-readable summary at archive time. We prefer on-demand generation
via query prompts to avoid the "write-once-read-never" problem. The query
prompts plus the memory linkage provide equivalent functionality without
maintaining a static artefact that decays.

### What Brian Could Adopt from Our Approach

- Formal schema specification (his has no documented JSON structure)
- Versioned schema with migration path
- Automation option for routine sessions (quick archive vs full interactive)
- Comprehensive metadata beyond Three Ps (thinking blocks ethics, typed
  relationships, tool output statistics)
- Catalogue system with cross-session indexing and tag search
- FAIR alignment documentation
- Compression and scale planning (gzip, PostgreSQL query layer)

### Memory–Session–Three Ps Integration

The three systems (memories, session archives, Three Ps) should be linked:

```text
Session Archive                Memory System
  session.meta.json    ←───→    memories.jsonl
  - session_id                  - session_id (already exists)
  - three_ps                    - category, tags, content
  - memory_ids[] (NEW)          - (condensed understanding)

  Query on demand:
  "Show me session X" → session metadata + linked memories
  "What decisions did I make about Y?" → memory search → session context
```

The `session_id` field already exists in both systems. The missing link
is a `memory_ids` array in session metadata (or a PostgreSQL JOIN on
session_id). This is a Phase 4 refinement item.

### Potential Joint Publication

Both implementations together make a stronger case than either alone:
ours demonstrates that the Three Ps framework can be formally specified
and automated at scale; Brian's demonstrates that it can drive meaningful
human reflection. A joint paper or RDA recommendation could present both
as complementary implementation patterns — "automated archiving with
proleptic enrichment" — showing the framework works across the automation
spectrum.

**Action:** Discuss with Brian at next opportunity. The RDA IG context
makes this a natural fit — two co-chairs independently implementing and
validating the same framework is exactly the kind of evidence an IG
output needs.

---

## Implementation Phases

### Phase 1: Core Automation (Weekend/Evenings) — COMPLETE (2026-03-15)

- [x] Add `--from-hook` mode to cc-session-toolkit CLI — reads `{session_id, transcript_path, cwd}` from stdin JSON
- [x] Add `--auto-metadata` flag (Haiku API call for title/purpose) — graceful fallback if API unavailable
- [x] Change default archive root to `~/cc-archives/` (configurable via `--archive-root`)
- [x] Add deduplication check (skip already-archived session_id via CATALOG.json)
- [x] Add trivial-session filter (<5 turns or <1 min, configurable via `--min-turns`)
- [x] Add `--pre-compact` flag to tag pre-compaction snapshots
- [x] Add `capture_type` field to archive metadata (`session_end` / `pre_compact`)
- [x] Tests: 32 new tests (85 total), all passing
- [x] Configure dual hooks in `~/.claude/settings.json` — SessionEnd + PreCompact, both async with 120s timeout
- [ ] Test: verify archives appear after session end and compaction (will validate on next session close)

### Phase 2: PostgreSQL Integration (2026-03-15)

- [x] Extend `scripts/schema.sql` with sessions table (with `raw_metadata JSONB`, cache token columns, `capture_type`)
- [x] New `scripts/sync-sessions-to-postgres.py` — walks `~/cc-archives/` for `session.meta.json`, upserts into sessions table
- [x] Hook wiring — chained sync after archive via `&&` in SessionEnd + PreCompact hooks
- [x] `/recall` extended with session search section (PostgreSQL full-text search, graceful fallback)
- [x] `untagged_sessions` and `session_costs` views created
- [x] Tests: 24 new tests (176 total), all passing
- [x] Settings.json tracked in public repo with symlink from `~/.claude/settings.json`
- [ ] Add `cc-session search` CLI subcommand (deferred to follow-up session)
- [ ] Add `cc-session untagged` CLI subcommand (deferred to follow-up session)

### Phase 3: Enrichment Workflow

- [ ] Incorporate proleptic reasoning question into `cc-session update`
- [ ] Tune `populate-metadata.md` to elicit rationale ("why", not just "what")
- [ ] Add relationship auto-heuristic ("continues most recent session in project")
- [ ] Add optional `SessionStart` nudge hook for untagged sessions
- [ ] Add HTML export option (integrate simonw's tool)
- [ ] Set up rsync backup to rpi-server

### Phase 4: Progressive Disclosure Memory (Levels 1 & 2)

**Partially superseded by memory system Phase 1c (2026-03-15).**
Summary field, extraction-time generation, and backfill are done.
Remaining items below are incremental improvements.

- [x] Add `summary` field to extraction prompt — done (Phase 1c, ≤150 chars)
- [x] Add `summary` column to PostgreSQL schema — done (Phase 1c)
- [x] Batch-generate summaries for existing memories — done (7,752 backfilled)
- [x] Modify session-start hook: compact Level 1 format — done (2026-03-15). Dropped confidence, moved date to end, removed `tags:` prefix. Content-first reading flow.
- [x] Increase slot allocation from 54 to 90 memories — done (2026-03-15). 62% more coverage at 50% more chars (0.44% of 1M context).
- [x] Level 2 retrieval instruction — done (2026-03-15). `/recall [query]` instruction in session-start header. `/recall` command already implements Level 2 retrieval.
- [ ] Add `source_messages` column to PostgreSQL schema (Phase 5 enabler)
- [ ] Add PostgreSQL availability check at session start (fallback to JSONL)
- [ ] Add explicit retrieval announcement ("retrieving memories about [topic]")
- [ ] Test: compare Level 1 awareness coverage vs current flat injection
- [ ] Tune Level 2 retrieval count (start at 5-10, adjust based on usage)

### Phase 5: Eidetic Recall (Level 3) and Full Integration

**1M context window now available (2026-03-15).** This fundamentally changes
Level 3: an entire session transcript (~100K tokens) uses ~10% of available
context. Level 3 retrieval is now routine, not expensive. The gating prompt
("retrieve full conversation? Y/N") can be relaxed or removed — CC can load
full transcripts without meaningful context pressure.

Implications:
- Level 3 gating is no longer necessary for cost reasons
- Multiple session transcripts can be loaded simultaneously
- The progressive disclosure model (L1→L2→L3) still has value for *focus*
  (knowing which session to load) but the *cost* argument is weaker
- Consider making Level 3 auto-triggered when CC detects high relevance

- [ ] Re-archive all existing sessions into `~/cc-archives/` with new schema
- [ ] Re-extract memories with source_messages tracking from archived transcripts
- [ ] Wire up memory–session linkage (PostgreSQL JOIN on session_id)
- [ ] Implement Level 3 retrieval: decompress archive → search → extract section
- [ ] ~~Add Level 3 gating prompt~~ — no longer needed with 1M context; auto-trigger on high relevance instead
- [ ] Add `cc-session memories <session-id>` command (show linked memories)
- [ ] Run all 6 query prompts through /improve-prompt skill
- [ ] Test local model summary generation on sapphire (compare quality to Haiku)
- [ ] Monitor archive sizes and compression ratios
- [ ] Tune trivial-session threshold based on real data
- [ ] Review whether auto-metadata quality is sufficient or needs tuning
- [ ] Discuss joint publication with Brian (RDA IG context)

---

## Progressive Disclosure Memory System

### Concept

The memory system currently injects ~40 full memories at session start,
consuming ~3,500 tokens of context. This is a flat approach: everything
loaded is at the same level of detail. The progressive disclosure model
replaces this with three tiers of increasing detail, inspired by (a) the
skill system's progressive loading pattern and (b) how human memory
actually works — you know *that* you know something before you can
articulate the details, and the details come back when you engage with
the topic.

### The Three Levels

**Level 1 — Compact Index (session start, always loaded)**

A tag-and-summary index of all active memories, category-grouped. Each
entry is ~65 chars vs ~350 chars for a full memory. This serves as an
awareness net: CC knows what topics exist in memory without consuming
context on full content.

```text
## decision (54)
- #postgresql #architecture — chose PostgreSQL for query layer [2026-02-08]
- #session-archiving #hooks — dual async hooks for capture [2026-02-15]
- #three-ps #rda — compare our vs Brian's implementation [2026-02-15]
```

**Capacity:** ~150 memories in ~2,400 tokens (vs current 40 memories in
~3,500 tokens). 3.75x more coverage in 67% of the space.

**Level 2 — Full Memory (on-demand, topic-triggered)**

When a conversation topic matches tags in the Level 1 index, CC fetches
the full memory content. This is roughly what the current system injects
at session start — the complete memory with content, confidence, tags,
and source context.

```text
[decision] (high, 2026-02-08)
Using PostgreSQL for memory store because of query complexity and
existing infrastructure. Full-text search, trigram indexes, and
category-based views provide rich querying. JSONL remains canonical;
PostgreSQL is derived and rebuildable.
Tags: postgresql, architecture, memory-system
```

**Triggered by:** CC recognises a topic match between conversation
content and Level 1 tags. CC explicitly announces the retrieval:
"I have memories about [topic], retrieving details..." This keeps
the process transparent so the user can tune or gate retrieval.

**Level 3 — Eidetic Recall (on-demand, rare, user-gated)**

Follow the memory's `session_id` to the session archive and retrieve
the relevant section of the original transcript. This provides the full
reasoning thread — alternatives considered, trade-offs weighed, the
complete context of how a decision was reached.

```text
User: What approach should we use for batch processing?
CC: The Gemini API supports a Batch API that offers...
[15 exchanges showing the full exploration and decision process]
```

**Triggered by:** CC asks the user before escalating to Level 3, since
it consumes significant context. "I can retrieve the full conversation
where we discussed [topic]. Want me to pull it up?" Once token budgets
increase (1M context), this gating can be relaxed.

### How the Levels Connect

```text
Level 1 (Index)                    Level 2 (Memory)              Level 3 (Transcript)
  tags + summary    ──match──→     full content        ──link──→   session archive
  ~65 chars/entry                  ~300 chars/entry                ~2-10K chars/section
  loaded at start                  fetched on demand               fetched on demand
  150+ entries                     3-8 per topic                   1-2 per session
  passive awareness                active retrieval                deep retrieval
```

The transition mechanism is natural, not mechanical:

1. Session starts → Level 1 index loads (compact, wide awareness)
2. Topic arises → CC sees matching tags in index → fetches Level 2
3. Deep context needed → CC asks user → reads archived transcript

### PostgreSQL as the Query Engine

PostgreSQL supports all three levels through existing infrastructure:

**Level 1 — Index generation (session-start hook):**

```sql
SELECT id, category, research_tags, LEFT(content, 70) AS summary,
       created_at::date AS date
FROM active_memories
WHERE project = $1 OR project IS NULL
ORDER BY category, created_at DESC;
```

**Level 2 — Full memory retrieval (mid-conversation):**

```sql
SELECT * FROM active_memories
WHERE to_tsvector('english', content) @@ plainto_tsquery('english', $1)
   OR research_tags && ARRAY[$2, $3]
ORDER BY created_at DESC
LIMIT 10;
```

**Level 3 — Session archive lookup:**

```sql
SELECT s.archive_path, s.title, s.started_at, s.purpose
FROM sessions s
WHERE s.id = (SELECT session_id FROM memories WHERE id = $1);
```

Then decompress and search the archive for relevant exchanges.

**Fallback:** If PostgreSQL is unavailable (e.g., on a machine without
it configured), fall back to JSONL-based retrieval. The session-start
hook checks for PostgreSQL availability once at startup and uses the
appropriate backend for the session. This mirrors the current pattern
where JSONL is canonical and PostgreSQL is a derived query layer.

### Schema Extensions

Add to the `memories` table:

```sql
-- One-sentence summary for Level 1 display (generated during extraction)
ALTER TABLE memories ADD COLUMN IF NOT EXISTS summary TEXT;

-- Message UUIDs from the transcript that generated this memory
-- Enables precise Level 3 retrieval instead of fuzzy search
ALTER TABLE memories ADD COLUMN IF NOT EXISTS source_messages TEXT[];
```

### Extraction Pipeline Changes

The extraction hook needs two additions:

1. **Summary generation.** When Haiku extracts memories, also request a
   one-sentence summary (≤80 chars) for the Level 1 index. This is a
   minor prompt modification — the extraction prompt already asks for
   `content` and `source_context`; adding `summary` is trivial.

2. **Source message tracking.** Record which transcript message UUIDs
   contributed to each extracted memory. This requires passing message
   UUIDs to Haiku alongside the conversation text and asking it to cite
   source messages. Post-hoc matching (finding which messages the memory
   content relates to) is the simpler alternative — match by content
   similarity rather than explicit citation.

For existing memories without summaries, a batch retroactive generation
pass using Haiku (or a capable local model on sapphire — explore
Gemma 3 27B, QwQ 32B, or similar) would populate the `summary` field.
At ~3,600 memories and ~$0.001/memory, the Haiku cost would be ~$3.60.
A local model would be free but slower.

### Session-Start Hook Redesign

The current `session-start-retrieval.py` hook would be modified:

1. **Check PostgreSQL availability** at startup (one connection attempt)
2. **If PostgreSQL available:** Run Level 1 query, format as compact
   category-grouped index
3. **If PostgreSQL unavailable:** Fall back to JSONL scan with in-memory
   grouping (current approach, but with compact formatting)
4. **Output format:** Category-grouped Level 1 index with retrieval
   instructions ("Use psql or /recall to fetch full memories")

The hook's slot allocation logic (same-project vs other-project
bucketing) remains, but applies to compact entries rather than full
memories, allowing many more entries within the same context budget.

### Context Budget Analysis

| Scenario | Memories | Context cost | Coverage |
|----------|----------|-------------|----------|
| Current (flat L2) | 40 | ~3,500 tokens | Narrow: recent + permanent |
| Level 1 only | 150 | ~2,400 tokens | Wide: most active memories |
| L1 + 5 L2 fetches | 150 + 5 full | ~3,200 tokens | Wide + deep on active topic |
| L1 + L2 + 1 L3 fetch | 150 + 5 + transcript | ~5,700+ tokens | Full depth, one topic |

The progressive approach gives wider awareness at lower base cost,
with depth available on demand. The current approach uses more base
context for narrower coverage.

With 1M token context windows (now available as of 2026-03-15),
Level 3 is routine — an entire session transcript (~100K tokens)
uses 10% of available context. Multiple transcripts can be loaded
simultaneously. The progressive disclosure model retains value for
*focus* (knowing which session is relevant) but the cost argument
for gating Level 3 access is no longer compelling.

### Analogy to Human Memory

This architecture mirrors how human episodic memory works:

- **Level 1 (semantic tags):** "I know I know something about PostgreSQL
  and memory systems." The feeling of knowing — enough to recognise
  relevance when the topic comes up.
- **Level 2 (declarative recall):** "We chose PostgreSQL because of
  query complexity and existing infrastructure." The facts, retrieved
  when the topic is active.
- **Level 3 (episodic recall):** "I remember the conversation — we
  considered SQLite, Redis, and PostgreSQL, weighed the trade-offs..."
  The full experiential context, available with effort.

As the user noted: "I'm always amazed what details I remember when I'm
giving a lecture and as I talk all this detail starts coming back to
mind." Level 1 is the lecture notes. Level 2 is what you say when
someone asks a question. Level 3 is the detailed memory that surfaces
when you really engage with a topic.

### Resolved Design Questions

1. **Query backend:** PostgreSQL primary, JSONL fallback. Check once at
   session start.
2. **Retrieval transparency:** Explicit — CC announces "retrieving
   memories about [topic]." User can tune or gate as needed.
3. **Level 3 gating:** Always ask before escalating. Relax when token
   budgets increase.
4. **Retroactive summaries:** Batch-generate for existing memories via
   Haiku or local model during archive migration.
5. **Source message tracking:** Add to extraction pipeline; re-extract
   from archived transcripts during migration.

### Observations from Prototype (2026-02-16)

The prototype (`planning/progressive-memory-prototype.md`) generated
from real memory data revealed several issues worth addressing before
implementation:

**1. Extraction volume spikes.** 2,669 of 3,618 memories (74%) were
created in the last 7 days during an intensive work period. The Level 1
index needs a strategy for high-volume periods — otherwise transient
categories like `progress` (25 entries) and `gotcha` (23 entries)
dominate the index while contributing less value than permanent
categories like `decision` or `methodology`. Options:

- Per-category caps in the Level 1 index (e.g., max 5 `progress`
  entries, unlimited `decision` entries)
- Recency-weighted ranking within categories (show the 3 most recent
  per category, regardless of absolute count)
- A two-tier approach: permanent categories get full representation;
  transient categories get capped

**2. Summary quality floor vs ceiling.** The prototype uses
first-sentence truncation as a stand-in for the `summary` field.
Purpose-written summaries from the extraction prompt will be
considerably better — the prototype shows the floor, not the ceiling.
This matters because the Level 1 index is the primary matching surface;
poor summaries mean missed matches.

**3. Tag coverage gaps.** 7% of memories (269 total) have zero tags.
These are invisible to tag-based Level 2 retrieval. The retroactive
summary generation pass should also fill in missing tags. Going
forward, the extraction prompt should treat empty tags as a quality
failure — every memory should have at least one tag.

**4. Date display in dense periods.** When most memories share the same
date (e.g., all showing `2026-02-15`), the date loses its value as a
distinguishing feature. Consider relative dating in the Level 1 format
("today", "2d ago", "last week") for recency-at-a-glance during high-
volume periods.

**5. Memory IDs add visual noise.** The `2026-02-16-6fe6602f143e` format
is useful for retrieval but clutters the Level 1 display. Drop IDs from
the display format — they're still in the backing data for Level 2
lookup. The category + tags + summary is sufficient for matching.

### Implementation Dependencies

Level 1 and Level 2 can be implemented **immediately** — they only
require the existing memory system (JSONL + PostgreSQL):

- Modify extraction prompt to generate summaries
- Modify session-start hook for compact format
- Add PostgreSQL-backed `/recall --deep` for Level 2

Level 3 requires the session archive system (Phase 1 of the archiving
redesign) to be operational:

- Session archives must exist with discoverable paths
- `sessions` table in PostgreSQL must link session_id to archive_path
- Decompression and search capability for archived transcripts

---

## Open Questions

1. **Archive root location:** `~/cc-archives/` vs `~/personal-assistant/archive/`
   (gitignored)? The former is cleaner; the latter keeps everything under one
   roof. Leaning toward `~/cc-archives/` for separation of concerns.

2. **Haiku API cost:** At ~$0.001/session and ~120 sessions/month, auto-metadata
   costs ~$0.12/month. Negligible. But need to handle API failures gracefully
   (archive without metadata rather than failing entirely).

3. **Pre-compaction snapshots:** Should we archive every auto-compaction, or only
   manual compactions? Auto-compaction can fire multiple times in a long session,
   potentially creating many snapshots of the same session. Need a strategy:
   perhaps only archive if no snapshot exists yet for this session_id.

4. **Sharing via cc-session-toolkit:** The toolkit is public on GitHub. The
   `--from-hook` mode and centralised archiving would be broadly useful.
   Design the feature for general use, not just our setup.

5. **Local model for summary generation:** Can sapphire's local models
   (Gemma 3 27B, QwQ 32B, or similar via Ollama) generate adequate Level 1
   summaries, or is Haiku quality required? Test during retroactive summary
   generation. If local works, ongoing extraction can use local models for
   summaries while Haiku handles the harder memory extraction task.

6. **Level 2 retrieval granularity:** How many memories should be fetched per
   topic match? Current thinking: 5-10, but this needs tuning based on actual
   usage patterns. Too few misses context; too many wastes budget.
