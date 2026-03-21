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
| `scripts/sync-to-postgres.py` | JSONL → PostgreSQL sync | Cron every 5 min |
| `scripts/apply-decay.py` | Mark expired memories inactive | Weekly manual |
| `scripts/rebuild-postgres.py` | Full rebuild from JSONL | As needed |
| `scripts/schema.sql` | Database schema (tables, indexes, views) | One-time |

All scripts are in `~/personal-assistant/scripts/`.

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

### Multi-Machine Setup

PostgreSQL is local per machine. Each machine rebuilds from JSONL
(git-tracked). Setup on a new machine: install PostgreSQL, apply schema,
run `rebuild-postgres.py`.
