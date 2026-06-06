## Infrastructure — Full Reference

**Read this file when** working on hooks, scripts, sync pipelines, integration
points, or troubleshooting the personal-assistant system architecture.

### Architecture Overview

The personal-assistant system is built on three layers:

1. **Extraction** — Hooks capture memories and metadata from Claude Code sessions
2. **Storage** — JSONL (canonical) + PostgreSQL (derived query layer) + pgvector
   (semantic search)
3. **Retrieval** — Session-start loading (Level 1) + on-demand fetch (Level 2)

### Data Canonicality

| Data type | Canonical source | Derived stores |
|-----------|-----------------|----------------|
| Memories | `memories/memories.jsonl` | PostgreSQL `memories` table, pgvector embeddings |
| Sessions | `~/cc-archives/` (JSONL + metadata) | PostgreSQL `sessions` table |
| Tasks | `tasks/*.md` (Markdown) | GitHub Issues (via `/sync-board`) |
| Zotero | `~/Zotero/zotero.sqlite` (Zotero-managed) | None (read-only access) |

**Key principle:** JSONL is always canonical. PostgreSQL can be fully rebuilt
from JSONL at any time via `scripts/rebuild-postgres.py`.

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

### Commands (21 total)

All symlinked from `commands/` to `~/.claude/commands/`.

| Command | Purpose | Category |
|---------|---------|----------|
| `/standup` | Morning accountability check | Task |
| `/recap` | Evening recap + work log | Task |
| `/track` | Time logging (CSV-based) | Task |
| `/capture` | Quick inbox add | Task |
| `/done` | Mark task complete | Task |
| `/focus` | Manage focus slots | Task |
| `/review` | Weekly review + collaborator reports | Task |
| `/retro` | Monthly retrospective | Task |
| `/sync-board` | GitHub Projects sync | Task |
| `/process-email` | Email triage | Task |
| `/recall` | Search memories + sessions (FTS + semantic) | Memory |
| `/remember` | Manual memory capture | Memory |
| `/read` | Structured Zotero paper reading | Research |
| `/synthesise` | Thematic synthesis | Research |
| `/cite` | Quick citation lookup | Research |
| `/cite-new` | Generate BibTeX from DOI | Research |
| `/gaps` | Literature gap analysis (six dimensions, prioritised) | Research |
| `/craft` | Quick notebook entry | Notes |
| `/tags` | Tag vocabulary gardening (stats, duplicate detection, merge) | Memory |
| `/audit` | Code audit | Meta |
| `/reflect` | End-of-session reflection | Meta |

### Skills (2 total)

Symlinked from `skills/` to `~/.claude/skills/`.

| Skill | Purpose |
|-------|---------|
| `improve-prompt` | Prompt hardening workflow |
| `review-implementation` | Implementation review protocol |

### Hooks (2 total)

Located in `hooks/`, registered in `settings.json`.

| Hook | Trigger | Purpose |
|------|---------|---------|
| `extraction-hook.py` | Stop, PreCompact, SessionEnd | Memory extraction via Haiku. Cursor-tracked, slash-command filtered, tag-normalised. Extracts 24 categories of structured memories. `EXTRACTION_MAX_TOKENS = 8000` (raised from 2000 in P10, 2026-06-06); truncated responses are salvaged via `_salvage_truncated_array()` + `stop_reason == "max_tokens"` branch rather than dropped. |
| `session-start-retrieval.py` | SessionStart | Level 1 retrieval. 54 memory slots (35 same-project + 11 cross-project + 8 constraints). Loads scratchpad, task status, and Tier 2 retrieval instructions. Also logs surfaced memory IDs to `data/logs/surfaced.log` via `surfacing_log.log_surfaced()` (item 16 earned-utility instrumentation, 2026-06-06). |

### Scripts

Located in `scripts/`.

**Memory system:**

| Script | Purpose |
|--------|---------|
| `sync-to-postgres.py` | JSONL → PostgreSQL sync + auto-embed (5-min cron). P8 (2026-06-06): now syncs `is_active` in its INSERT so a row forgotten before its first sync lands inactive rather than being resurrected. |
| `sync_memory_edit.py` | Surgical PG `UPDATE` for `/forget` and `/update` (P8, 2026-06-06). Reads the already-edited JSONL record and mirrors the six mutable columns (`is_active`, `content`, `confidence`, `verified`, `anchors`, `revisions`) into PostgreSQL. Idempotent. Called as a mandatory step by both commands. PG-only: runs on amd-tower; no-op notice on other machines. |
| `apply-decay.py` | Mark expired memories inactive (weekly cron, Sun 3am) |
| `fetch-memories.py` | CLI retrieval: `--query` (FTS), `--semantic` (pgvector), `--tag`, `--category`, `--id`. Logs surfaced memory IDs via `surfacing_log` (item 16, 2026-06-06). |
| `embed.py` | Shared Ollama embedding client (nomic-embed-text, 768d) |
| `backfill-summaries.py` | Bulk summary generation via Haiku Batch API |
| `backfill-embeddings.py` | Bulk embedding via Ollama |
| `rebuild-postgres.py` | Truncate + full resync from JSONL |
| `tag-gardening.py` | Tag vocabulary analysis + merge (stats, similar, merge, orphans). Called by `/tags`. |
| `sync-to-zotero.py` | Push `source_insight` memories to Zotero item notes via pyzotero API. Manual invocation; idempotent via footer markers. |
| `memory_mcp.py` | Local MCP server exposing memory DB as 5 read-only tools (search, semantic_search, get_memory, list_recent, memory_statistics). stdio transport, FastMCP. |
| `surfacing_log.py` | Append-only writer for `data/logs/surfaced.log` (item 16, 2026-06-06). Logs one tab-separated line per surfaced memory ID, tagged `path=digest\|fetch\|recall`. Pure formatter + best-effort I/O; never raises. CLI: `--path <path> --ids "<ids>"`. |
| `surfacing_stats.py` | Read-only aggregator over `surfaced.log` (item 16, 2026-06-06). Reports per-memory `active_retrievals`, `digest_exposures`, `last_active_at`; weights active fetch/recall above passive digest. Importable as `aggregate_surfacing()` for the health report. |
| `drift-sweep.py` | Anchor drift trend (item 8, 2026-06-06). Re-resolves the full anchored memory back-set and appends a trend line to `data/logs/drift-sweep.jsonl`. `--alert-threshold` sets an exit-1 threshold on the fail percentage. Read-only against the corpus. |
| `memory-health-report.py` | Standing health report (run by `/weekly-review`). Gained section [G] Memory surfacing (reads `surfaced.log` via `surfacing_stats.aggregate_surfacing()`) and section [H] Anchor drift trend (reads `drift-sweep.jsonl` via `drift_trend()`), both added 2026-06-06. |

**Session archiving:**

| Script | Purpose |
|--------|---------|
| `bulk-archive.py` | 4-mode: discover, archive, enrich, verify. Haiku Batch API for metadata enrichment. Checkpoint/resume. |
| `reprocess-sessions.py` | Extract memories from pre-hook sessions. Haiku Batch API, windowed (30 exchanges). |
| `sync-sessions-to-postgres.py` | Session metadata → PostgreSQL `sessions` table |

**Zotero:**

| Script | Purpose |
|--------|---------|
| `zotero.py` | Read-only Zotero SQLite client (immutable mode). Functions: `search_items`, `get_item`, `get_pdf_path`, `get_notes`, `get_collections`, `list_collections`, `get_collection_items`, `format_citation`. |

**Other:**

| Script | Purpose |
|--------|---------|
| `schema.sql` | PostgreSQL schema (memories + sessions tables, pgvector, 11+ indexes, views) |
| `commit-data.sh` | Submodule two-step commit helper |

### Integrations

**PostgreSQL (`claude_memories` database):**

- ~14,900 memories with pgvector embeddings (nomic-embed-text, 768d)
- ~335 sessions with Haiku-generated metadata
- Full-text search (tsvector) + trigram similarity on content
- pgvector HNSW index for semantic search
- `active_memories` view (applies decay rules)
- `category_config` table (15 categories with decay rules)
- Cron: sync every 5 min, decay weekly (Sun 3am)
- Full reference: `global-claude-md/postgresql-reference.md`

**Ollama (local):**

- nomic-embed-text — embedding generation (768d, ~1ms per embedding)
- Auto-embedded during sync cron (100 records per batch)
- Full model inventory and machine roles: `data/global-claude-md/network-resources.md`

**Zotero (local):**

- `~/Zotero/zotero.sqlite` — 3,763+ items, 1,060 PDFs, 82 collections
- Read-only immutable mode (safe while Zotero is running)
- Write-back via pyzotero API (`sync-to-zotero.py`, manual invocation)
- Full reference: `global-claude-md/zotero-reference.md`

**Local MCP servers:**

- `memory_mcp.py` — exposes the memory database as 5 read-only MCP tools
  (search, semantic_search, get_memory, list_recent, memory_statistics).
  stdio transport via FastMCP. Wraps `fetch-memories.py` query engine.
- Registration: `claude mcp add memory --scope user -- <python> <script>`
- Dependency: `mcp` package (`pip install mcp`)
- Use case: query memories from Claude Desktop, claude.ai, or other
  Claude instances that cannot access the local filesystem directly
- Critical invariant: stdio MCP servers must never write to stdout

**Session archives (`~/cc-archives/`):**

- 334+ sessions archived and enriched with Haiku-generated metadata
- `CATALOG.json` index
- Subagent archives nested under parent sessions
- 1,093 subagent sessions

### Cron Jobs

```text
*/5 * * * * venv/bin/python3 scripts/sync-to-postgres.py   # memory sync + auto-embed
0 3 * * 0   venv/bin/python3 scripts/apply-decay.py         # weekly decay
```

### Test Suite

Tests in `tests/` covering extraction hook, retrieval hook, fetch-memories,
sync scripts, session sync, bulk archive, embedding client, tag gardening,
and Zotero queries. Run with `pytest` from the repo root (venv required).

### Architectural Decisions

- **JSONL is canonical; PostgreSQL is derived** — rebuildable from JSONL
- **Embeddings are PostgreSQL-only** — not stored in JSONL (derived data)
- **Local-first Zotero** — reads are SQLite (immutable mode), writes are
  API-only (never write to Zotero SQLite)
- **Ollama for embeddings ($0)** — Haiku for extraction (quality matters more)
- **Batch API + prompt caching** — for cost optimisation on all Haiku bulk work
- **Summaries generated at extraction time** — ≤150 chars via Haiku, stored in
  JSONL, displayed in session-start retrieval

### What's Not Built Yet

_(empty — see backlog for remaining non-infrastructure items)_
