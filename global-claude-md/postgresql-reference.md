## PostgreSQL Query Layer

JSONL is canonical. PostgreSQL is a derived query layer for structured
queries, full-text search, and tag analytics. It can be fully rebuilt
from JSONL at any time.

### Connection

- **Database:** `claude_memories`
- **Auth:** Peer authentication via unix socket (no password)
- **Connection string:** `postgresql:///claude_memories`
- **Python:** `psycopg2.connect(dbname="claude_memories")`

### Scripts

| Script | Purpose | Schedule |
|--------|---------|----------|
| `scripts/sync-to-postgres.py` | JSONL → PostgreSQL sync + auto-embed. P8 (2026-06-06): `is_active` is now included in the INSERT column list so a row forgotten before its first sync lands with `is_active=false` rather than being resurrected by the column default (`ON CONFLICT DO NOTHING` means a subsequent sync will not overwrite it). | Cron every 5 min |
| `scripts/sync_memory_edit.py` | Surgical `UPDATE` of mutable columns for a single memory (P8, 2026-06-06). Called by `/forget` and `/update` as a **mandatory** step immediately after the JSONL rewrite. Mirrors `is_active`, `content`, `confidence`, `verified`, `anchors`, `revisions` from the edited JSONL record into PG. Idempotent; reports (does not error) if the row is not yet in PG. The helper simply attempts a local connection — on a machine without PG it warns and exits non-zero (recall there reads JSONL, so the edit still lands); a connection that succeeds but whose query fails (schema mismatch) is reported as "query failed", pointing at `schema.sql` + rebuild (labelling fixed 2026-07-04). | On `/forget` and `/update` |
| `scripts/apply-decay.py` | Mark expired memories inactive | Weekly manual |
| `scripts/rebuild-postgres.py` | Full rebuild from JSONL | As needed — **see the rebuild preconditions below** |
| `scripts/schema.sql` | Database schema (tables, indexes, views) | One-time |
| `scripts/check-memory-drift.py` | Cross-store integrity check: finds records that survive in only one store (PG-only, or stranded in a daily-sync stash) | Daily via `daily-sync.sh`; on demand before any rebuild |

All scripts are in `~/personal-assistant/scripts/`.

### ⛔ Rebuild preconditions (standing rule, 2026-08-22)

**Run `check-memory-drift.py` IMMEDIATELY BEFORE `rebuild-postgres.py` or any
`sync-sessions-to-postgres.py --full-resync`, and recover anything it finds
first** (`--recover`). A rebuild treats the canonical JSONL as complete by
definition, so it cannot see a PG-only record and will silently destroy it —
on 2026-08-20 a rebuild would have destroyed 38 records that existed only in
PG (they were recovered first; `data` commit `108d044`).

Two **independent** preconditions gate `--full-resync`, and both must clear:

1. **Drift check clean** (this rule) — protects PG-only memory records.
2. **The archive-integrity session** (`tasks/backlog.md`, "Archive-integrity
   session" row) — B6 catalogue recursion, duplicate triage, and the indexer
   fixes must land first, or the re-index bakes known defects back into
   `session_chunks`.

### Why `/forget` and `/update` require the lockstep helper

`sync-to-postgres.py` is INSERT-only (`ON CONFLICT (id) DO NOTHING`). It does
**not** propagate edits to rows already in PG. The PG-reading recall paths — the
session-start digest and the autonomous `fetch-memories.py` depth-fetch, both
via the `active_memories` view — therefore kept surfacing forgotten or stale
memories until a manual `rebuild-postgres`. `sync_memory_edit.py` closes that
gap with a targeted `UPDATE`. If PG is unreachable the helper prints a WARNING
and exits non-zero; run `rebuild-postgres.py` to reconcile later.

Pre-P8 behaviour was described as "PG sync is automatic" — that claim was false
and has been removed from the command docs.

### Useful Queries

```sql
-- Full-text search
SELECT id, LEFT(content, 80), category FROM memories
WHERE to_tsvector('english', content) @@ plainto_tsquery('english', 'search terms');

-- Category breakdown
SELECT category, COUNT(*) FROM memories GROUP BY category ORDER BY count DESC;

-- Tag analytics (top tags)
SELECT tag, COUNT(*) FROM memories, UNNEST(research_tags) AS tag
GROUP BY tag ORDER BY count DESC LIMIT 15;

-- Active memories (respects decay rules)
SELECT * FROM active_memories WHERE category = 'decision' ORDER BY created_at DESC;

-- Source breakdown
SELECT source, COUNT(*) FROM memories GROUP BY source;
```

### Embeddings (pgvector)

The `memories` table includes an `embedding` column (`vector(768)`) populated
by Ollama's nomic-embed-text model via `scripts/embed.py`.

- **Extension:** pgvector (`CREATE EXTENSION vector`)
- **Index:** HNSW on `embedding` column (cosine distance)
- **Dimension:** 768 (nomic-embed-text output)
- **Population:** Auto-embedded during sync cron (100 records per batch);
  `scripts/backfill-embeddings.py` embeds the whole backlog in one pass
- **Coverage:** All memories embedded (~29,180 as of 2026-07-04)

**Semantic search query:**

```sql
SELECT id, LEFT(content, 80), category,
       1 - (embedding <=> $1::vector) AS similarity
FROM memories
WHERE embedding IS NOT NULL
ORDER BY embedding <=> $1::vector
LIMIT 10;
```

Use `scripts/fetch-memories.py --semantic "query text"` for CLI access
(handles embedding generation and similarity search automatically).

### Sessions Table

The `sessions` table stores archived session metadata from `~/cc-archives/`.
Synced via `scripts/sync-sessions-to-postgres.py`.

- **Key columns:** `session_id`, `project`, `tags`, `summary`, `total_cost`,
  `duration_minutes`, `raw_metadata` (JSONB)
- **Views:** `untagged_sessions`, `session_costs`
- **FTS:** Full-text search on summary and tags

```sql
-- Search sessions by topic
SELECT session_id, project, summary, total_cost
FROM sessions
WHERE to_tsvector('english', summary) @@ plainto_tsquery('english', 'search terms')
ORDER BY archived_at DESC;

-- Cost breakdown by project
SELECT project, COUNT(*), SUM(total_cost) AS total
FROM sessions GROUP BY project ORDER BY total DESC;
```

### Multi-Machine Setup

PostgreSQL is local per machine, currently configured on **amd-tower and
zbook** (zbook repaired 2026-07-04 after drifting since 2026-05-02 — see
below). Machines without PG read the git-synced JSONL directly; the
PG-writing paths fail loudly there (`sync_memory_edit.py` warns and exits
non-zero) but the JSONL edit alone suffices for recall.

To set up PG on a new machine: install PostgreSQL, apply schema, run
`rebuild-postgres.py`.

**Schema migrations must be applied on EVERY PG machine.** Each script
asserts `meta.schema_version` before touching the DB, so a host that
misses a migration has its sync halted by design — silently, from the
user's perspective, because recall falls back to JSONL. This is exactly
what happened on zbook: the version gate landed in code on 2026-05-02
(audit batch 4) but `schema.sql` was applied only on amd-tower, and
zbook's cron then failed every 5 minutes for two months (13,231 runs)
before a `/forget` surfaced it. After any schema change: apply
`schema.sql` on each PG machine, then check that machine's
`data/logs/sync-cron.log` shows a clean run.
