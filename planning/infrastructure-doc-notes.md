# Infrastructure Documentation Notes

Raw material for the next session's documentation task. Captures the full
system state as of 2026-04-11 after a major infrastructure session.

## What the Next Session Should Do

1. Review all existing reference docs in `global-claude-md/`:
   - `memory-system-reference.md` — may be stale (pre-dates pgvector, session reprocessing)
   - `postgresql-reference.md` — needs pgvector/embeddings section
   - `network-resources.md` — probably current
   - `scratchpad-reference.md` — probably current
   - `git-reference.md` — probably current
   - `zotero-reference.md` — NEW, written today, should be current

2. Write `global-claude-md/infrastructure-reference.md` — the architecture doc:
   - Capability map (commands, scripts, integrations)
   - Data flow diagrams (text-based)
   - Integration points
   - Constraints and gotchas

3. Update `CLAUDE.md` with a brief capability index pointing to the reference docs

4. Review and update stale reference docs

## Complete System Map (as of 2026-04-11)

### Commands (19 total, all symlinked to ~/.claude/commands/)

**Task system:**
- `/standup` — Morning accountability check
- `/recap` — Evening recap + work log
- `/track` — Time logging (CSV-based)
- `/capture` — Quick inbox add
- `/done` — Mark task complete
- `/focus` — Manage focus slots
- `/review` — Weekly review + collaborator reports
- `/retro` — Monthly retrospective
- `/sync-board` — GitHub Projects sync
- `/process-email` — Email triage

**Memory system:**
- `/recall` — Search memories + sessions (FTS + semantic)
- `/remember` — Manual memory capture

**Research:**
- `/read` — Structured Zotero paper reading (NEW)
- `/synthesise` — Thematic synthesis from memories/collections (NEW)
- `/cite` — Quick citation lookup from Zotero (NEW)
- `/cite-new` — Generate BibTeX from DOI/details (NEW)

**Notes:**
- `/craft` — Quick notebook entry

**Meta:**
- `/audit` — Code audit using Pliny's debug prompt
- `/reflect` — End-of-session reflection protocol

### Skills (2 symlinked to ~/.claude/skills/)

- `improve-prompt` — Prompt hardening workflow
- `review-implementation` — Implementation review protocol

### Scripts (in ~/personal-assistant/scripts/)

**Memory system:**
- `sync-to-postgres.py` — JSONL → PostgreSQL sync (5-min cron). Now includes
  post-insert embedding generation via Ollama nomic-embed-text.
- `apply-decay.py` — Mark expired memories inactive (weekly cron, Sun 3am).
- `fetch-memories.py` — CLI retrieval: `--query` (FTS), `--semantic` (pgvector
  cosine similarity), `--tag`, `--category`, `--id`. PostgreSQL first, JSONL fallback.
- `backfill-summaries.py` — Bulk summary generation via Haiku (Batch API pattern).
- `backfill-embeddings.py` — Bulk embedding via Ollama nomic-embed-text.
- `rebuild-postgres.py` — Truncate + full resync safety net.
- `embed.py` — Shared Ollama embedding client. Functions: `generate_embeddings()`,
  `embed_single()`, `build_embed_text()`, `is_ollama_available()`.

**Session archiving:**
- `bulk-archive.py` — 4-mode script: discover, archive, enrich, verify.
  Archives sessions from ~/.claude/projects/ to ~/cc-archives/. Haiku Batch
  API for metadata enrichment. Checkpoint/resume.
- `reprocess-sessions.py` — Extract memories from pre-hook session transcripts.
  Haiku Batch API, windowed (30 exchanges), cursor-tracked.
- `sync-sessions-to-postgres.py` — Session metadata → PostgreSQL sessions table.

**Zotero:**
- `zotero.py` — Read-only Zotero SQLite client. Immutable mode. Functions:
  search_items, get_item, get_pdf_path, get_notes, get_collections,
  list_collections, get_collection_items, format_citation.

**Other:**
- `schema.sql` — PostgreSQL schema (memories + sessions tables, pgvector,
  11+ indexes, active_memories view, category_config).
- `commit-data.sh` — Submodule two-step commit helper.

### Hooks (in ~/personal-assistant/hooks/)

- `extraction-hook.py` — Memory extraction via Haiku. Fires on Stop,
  PreCompact, SessionEnd. Cursor-tracked, slash-command filtered, tag-normalised.
  Extracts 24 categories of structured memories.
- `session-start-retrieval.py` — Level 1 memory retrieval at session start.
  54 memory slots (35 same-project + 11 cross-project + 8 constraints).
  Includes Tier 2 retrieval instructions (gated: announce → confirm → fetch).

### Integrations

**PostgreSQL (claude_memories database):**
- 14,872 memories (all embedded with pgvector)
- 335 sessions with Haiku-generated metadata
- FTS indexes on content + trigram similarity
- pgvector HNSW index for semantic search (nomic-embed-text, 768d)
- active_memories view (applies decay rules)
- category_config table (15 categories with decay rules)
- Cron: sync every 5 min, decay weekly

**Ollama (local):**
- nomic-embed-text — embedding generation (768d, ~1ms per embedding)
- gpt-oss:120b — best local LLM for structured extraction (18.7s avg)
- gemma4:26b-a4b — best sub-50b model
- Auto-embed in sync cron (100 records per cycle)

**Zotero (local):**
- ~/Zotero/zotero.sqlite — 3,763+ items, 1,060 PDFs, 82 collections
- Read-only immutable mode (safe while Zotero running)
- Write-back via pyzotero API (planned, not built)

**~/cc-archives/:**
- 334 sessions archived and enriched
- CATALOG.json index
- Subagent archives nested under parent sessions
- 1,093 subagent sessions

### Data Flow

```text
Claude Code session
  → extraction-hook.py (Haiku, per-response)
    → memories/memories.jsonl (canonical)
      → sync-to-postgres.py (5-min cron)
        → PostgreSQL memories table
          → embed.py (nomic-embed-text, auto in sync)
            → pgvector embedding column
              → fetch-memories.py --semantic (retrieval)

Session end
  → cc-session-toolkit archive hooks
    → ~/cc-archives/ (compressed JSONL + metadata)
      → sync-sessions-to-postgres.py
        → PostgreSQL sessions table (FTS searchable)

Session start
  → session-start-retrieval.py
    → Level 1: 54 memories loaded into context
    → Level 2: fetch-memories.py (on-demand, gated)
```

### Cron Jobs

```text
*/5 * * * * venv/bin/python3 scripts/sync-to-postgres.py   # memory sync + auto-embed
0 3 * * 0   venv/bin/python3 scripts/apply-decay.py         # weekly decay
```

### Test Suite

277 tests across 9 test files:
- test_extraction_hook.py — extraction hook logic
- test_retrieval_hook.py — session-start retrieval
- test_fetch_memories.py — fetch-memories.py modes
- test_sync_script.py — JSONL → PostgreSQL sync
- test_sync_sessions.py — session metadata sync
- test_bulk_archive.py — bulk archive pipeline (18 tests)
- test_embed.py — Ollama embedding client (15 tests)
- test_zotero.py — Zotero SQLite queries (20 tests)
- (others for decay, etc.)

### What's NOT Built Yet

- Zotero write-back sync (pyzotero API)
- MCP memory server
- Google Calendar MCP integration
- /tags gardening command
- /gaps literature gap analysis
- Research commands /read, /synthesise, /cite depend on Zotero query module
  but the actual reading/synthesis is done by Claude following the command
  prompt — no additional scripts needed

### Key Architectural Decisions

- JSONL is canonical; PostgreSQL is derived (rebuildable)
- Embeddings are derived data (PostgreSQL only, not in JSONL)
- Local-first: Zotero reads are SQLite, not API
- Write-back is API-only (never write to Zotero SQLite)
- Ollama for embeddings ($0), Haiku for extraction (quality)
- gpt-oss:120b viable for bulk local inference but Haiku wins on quality
- Batch API + prompt caching for cost optimisation on all Haiku bulk work
