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
| `scripts/sync_memory_edit.py` | Surgical `UPDATE` of mutable columns for a single memory (P8, 2026-06-06). Called by `/forget` and `/update` as a **mandatory** step immediately after the JSONL rewrite. Mirrors `is_active`, `content`, `confidence`, `verified`, `anchors`, `revisions` from the edited JSONL record into PG. Idempotent; reports (does not error) if the row is not yet in PG. PG runs only on amd-tower; the helper prints a no-op notice on other machines. | On `/forget` and `/update` |
| `scripts/apply-decay.py` | Mark expired memories inactive | Weekly manual |
| `scripts/rebuild-postgres.py` | Full rebuild from JSONL | As needed |
| `scripts/schema.sql` | Database schema (tables, indexes, views) | One-time |

All scripts are in `~/personal-assistant/scripts/`.

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
- **Population:** Auto-embedded during sync cron (100 records per batch)
- **Coverage:** All memories embedded (~14,900 as of 2026-04-11)

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

PostgreSQL is local per machine but is currently configured only on
amd-tower. Other machines read the git-synced JSONL directly, so the
PG-writing paths (the sync cron, `sync_memory_edit.py`) are no-ops there
— with no PG to write to, `/forget` and `/update` print a no-op notice
from the helper and the JSONL edit alone suffices.

To set up PG on a new machine: install PostgreSQL, apply schema, run
`rebuild-postgres.py`.
