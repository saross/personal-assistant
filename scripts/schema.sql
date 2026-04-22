-- PostgreSQL schema for claude_memories database.
--
-- Prerequisites (run as superuser before applying this file):
--   sudo -u postgres createuser shawn
--   sudo -u postgres createdb claude_memories -O shawn
--   sudo -u postgres psql -d claude_memories -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
--   sudo -u postgres psql -d claude_memories -c "CREATE EXTENSION IF NOT EXISTS vector;"
--
-- Apply: psql -d claude_memories < scripts/schema.sql
--
-- JSONL remains canonical. PostgreSQL is a derived query layer that can
-- be fully rebuilt at any time via scripts/rebuild-postgres.py.

-- ============================================================================
-- Main memories table
-- ============================================================================

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    source TEXT DEFAULT 'extraction',
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    summary TEXT,  -- One-sentence summary for session-start display (≤150 chars)
    confidence TEXT DEFAULT 'medium',
    research_tags TEXT[] DEFAULT '{}',
    zotero_key TEXT,
    source_context TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL,
    synced_at TIMESTAMPTZ DEFAULT NOW(),

    -- Project identifier (encoded cwd, e.g. -home-shawn-Code-map-reader-llm)
    project TEXT,

    -- For commitment category: when is the deadline?
    deadline_at TIMESTAMPTZ,

    -- Soft delete for decay (never hard delete)
    decayed_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT TRUE
);

-- ============================================================================
-- Indexes
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_memories_session ON memories(session_id);
CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
CREATE INDEX IF NOT EXISTS idx_memories_confidence ON memories(confidence);
CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_tags ON memories USING GIN(research_tags);
CREATE INDEX IF NOT EXISTS idx_memories_zotero ON memories(zotero_key)
    WHERE zotero_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_memories_active ON memories(is_active)
    WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project)
    WHERE project IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_memories_content_trgm
    ON memories USING GIN(content gin_trgm_ops);

-- Full-text search index
CREATE INDEX IF NOT EXISTS idx_memories_content_fts
    ON memories USING GIN(to_tsvector('english', content));

-- Semantic embedding (pgvector — nomic-embed-text, 768 dimensions).
-- NULL when embedding has not yet been generated.
-- Requires: CREATE EXTENSION IF NOT EXISTS vector;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS embedding vector(768);

-- HNSW index for cosine similarity search. Partial index on non-null
-- embeddings only. HNSW chosen over IVFFlat: no training step needed,
-- works incrementally, better recall at this scale (~15K records).
CREATE INDEX IF NOT EXISTS idx_memories_embedding_hnsw
    ON memories USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;

-- ============================================================================
-- Sync tracking
-- ============================================================================

CREATE TABLE IF NOT EXISTS sync_state (
    id SERIAL PRIMARY KEY,
    sync_type TEXT NOT NULL UNIQUE,
    last_position TEXT,
    last_sync_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO sync_state (sync_type, last_position) VALUES
    ('jsonl_to_postgres', '0'),
    ('postgres_to_zotero', '2000-01-01T00:00:00Z')
ON CONFLICT (sync_type) DO NOTHING;

-- ============================================================================
-- Category configuration (decay rules)
-- ============================================================================

CREATE TABLE IF NOT EXISTS category_config (
    category TEXT PRIMARY KEY,
    decay_days INTEGER,  -- NULL = never decay
    description TEXT
);

-- Research categories (permanent)
INSERT INTO category_config (category, decay_days, description) VALUES
    ('methodology', NULL, 'Analytical approach decisions'),
    ('ethics', NULL, 'IRB, consent, data handling'),
    ('provenance', NULL, 'Data origin and transformations'),
    ('hypothesis', NULL, 'Research questions and predictions'),
    ('limitation', NULL, 'Known constraints and scope'),
    ('openness', NULL, 'FAIR, open science, licensing'),
    ('source_insight', NULL, 'Insights from scholarly sources')
ON CONFLICT (category) DO NOTHING;

-- LLM research categories (permanent)
INSERT INTO category_config (category, decay_days, description) VALUES
    ('error_mode', NULL, 'LLM mistakes and corrections'),
    ('surprise', NULL, 'Unexpected insights'),
    ('self_reflection', NULL, 'LLM self-awareness moments'),
    ('prompt_effectiveness', NULL, 'What prompts work')
ON CONFLICT (category) DO NOTHING;

-- Project categories (mixed)
INSERT INTO category_config (category, decay_days, description) VALUES
    ('decision', NULL, 'Explicit choices with rationale'),
    ('architecture', NULL, 'System design'),
    ('contact', NULL, 'People and relationships'),
    ('pattern', 180, 'Recurring approaches'),
    ('gotcha', 180, 'Pitfalls and edge cases')
ON CONFLICT (category) DO NOTHING;

-- GTD categories (transient)
INSERT INTO category_config (category, decay_days, description) VALUES
    ('commitment', 30, 'Promises and deadlines (decays from deadline_at)'),
    ('waiting_for', 14, 'Blocked on others')
ON CONFLICT (category) DO NOTHING;

-- Transient categories
INSERT INTO category_config (category, decay_days, description) VALUES
    ('progress', 30, 'Status updates'),
    ('context', 30, 'Background information')
ON CONFLICT (category) DO NOTHING;

-- Retrospective categories (Phase 3 additions)
INSERT INTO category_config (category, decay_days, description) VALUES
    ('slip', NULL, 'Commitments not honoured — permanent for pattern detection'),
    ('completion', 90, 'Completed work records'),
    ('blocker_real', 30, 'Genuine external blockers'),
    ('blocker_excuse', NULL, 'Rationalised non-blockers — permanent for self-awareness'),
    ('system_evolution', NULL, 'How the PA system itself changes'),
    ('system_friction', 60, 'Where the system creates friction'),
    ('system_success', 90, 'What works well in the system')
ON CONFLICT (category) DO NOTHING;

-- ============================================================================
-- Views
-- ============================================================================

-- Active memories: filters by decay rules and is_active flag
CREATE OR REPLACE VIEW active_memories AS
SELECT m.*
FROM memories m
LEFT JOIN category_config c ON m.category = c.category
WHERE m.is_active = TRUE
  AND (
    c.decay_days IS NULL
    OR (m.category != 'commitment'
        AND m.created_at > NOW() - (c.decay_days || ' days')::INTERVAL)
    OR (m.category = 'commitment'
        AND COALESCE(m.deadline_at, m.created_at)
            > NOW() - (c.decay_days || ' days')::INTERVAL)
  );

-- Research memories: permanent scholarly and LLM-research categories
CREATE OR REPLACE VIEW research_memories AS
SELECT * FROM memories
WHERE category IN (
    'methodology', 'ethics', 'provenance', 'hypothesis',
    'limitation', 'openness', 'source_insight',
    'error_mode', 'surprise', 'self_reflection', 'prompt_effectiveness',
    'slip', 'blocker_excuse', 'system_evolution'
)
AND is_active = TRUE
ORDER BY created_at DESC;

-- Pending Zotero sync
CREATE OR REPLACE VIEW pending_zotero_sync AS
SELECT m.*
FROM memories m
WHERE m.category = 'source_insight'
  AND m.zotero_key IS NOT NULL
  AND m.created_at > (
    SELECT last_position::TIMESTAMPTZ
    FROM sync_state
    WHERE sync_type = 'postgres_to_zotero'
  );

-- ============================================================================
-- Sessions table (Phase 2)
-- ============================================================================
-- Stores metadata from archived Claude Code sessions. Canonical source
-- is session.meta.json in ~/cc-archives/; this table is a derived query
-- layer for full-text search and cross-project discovery.

CREATE TABLE IF NOT EXISTS sessions (
    -- Identity
    id TEXT PRIMARY KEY,           -- UUID from session.meta.json → session.id
    project TEXT NOT NULL,         -- e.g. "personal-assistant"
    project_directory TEXT,        -- e.g. "/home/shawn/personal-assistant"

    -- Auto-generated metadata (from Haiku API)
    title TEXT,
    purpose TEXT,
    tags TEXT[] DEFAULT '{}',

    -- Timestamps
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    duration_minutes INTEGER,

    -- Model
    model_provider TEXT,           -- e.g. "anthropic"
    model_id TEXT,                 -- e.g. "claude-opus-4-6"

    -- Statistics
    turns INTEGER,
    human_messages INTEGER,
    assistant_messages INTEGER,
    thinking_blocks INTEGER,
    tool_calls INTEGER,
    tokens_input INTEGER,
    tokens_output INTEGER,
    tokens_cache_read INTEGER,
    tokens_cache_creation INTEGER,
    estimated_cost_usd NUMERIC(10, 4),

    -- Three Ps (Prompt, Process, Provenance)
    prompt_summary TEXT,
    process_summary TEXT,
    provenance_summary TEXT,

    -- Archive info
    archive_path TEXT,             -- Filesystem path to session directory
    capture_type TEXT,             -- "session_end" or "pre_compact"

    -- Sub-agent rollup (v1.2 schema). Per-sub-agent detail lives in
    -- raw_metadata->'subagents'; these typed columns exist so
    -- "find sub-agent-heavy sessions" is indexable.
    subagent_count INTEGER DEFAULT 0,
    subagent_total_cost_usd NUMERIC(10, 4) DEFAULT 0,

    -- Full metadata for fields not broken out into columns
    raw_metadata JSONB,

    -- Review workflow
    needs_review BOOLEAN DEFAULT TRUE,
    is_active BOOLEAN DEFAULT TRUE,

    -- Sync tracking
    synced_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================================
-- Session indexes
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project);
CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_tags ON sessions USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_sessions_model ON sessions(model_id);
CREATE INDEX IF NOT EXISTS idx_sessions_capture_type ON sessions(capture_type);
CREATE INDEX IF NOT EXISTS idx_sessions_active ON sessions(is_active)
    WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_sessions_subagent_count ON sessions(subagent_count)
    WHERE subagent_count > 0;

-- Full-text search across title, purpose, and prompt summary
CREATE INDEX IF NOT EXISTS idx_sessions_fts ON sessions USING GIN(
    to_tsvector('english',
        COALESCE(title, '') || ' ' ||
        COALESCE(purpose, '') || ' ' ||
        COALESCE(prompt_summary, ''))
);

-- ============================================================================
-- Session views
-- ============================================================================

-- Sessions needing manual review (Three Ps enrichment, tagging)
CREATE OR REPLACE VIEW untagged_sessions AS
SELECT id, project, title, started_at, duration_minutes, capture_type
FROM sessions
WHERE needs_review = TRUE AND is_active = TRUE
ORDER BY started_at DESC;

-- Session cost summary by project
CREATE OR REPLACE VIEW session_costs AS
SELECT
    project,
    COUNT(*) AS session_count,
    SUM(duration_minutes) AS total_minutes,
    SUM(estimated_cost_usd) AS total_cost_usd,
    AVG(estimated_cost_usd) AS avg_cost_usd,
    SUM(tokens_input + tokens_output) AS total_tokens
FROM sessions
WHERE is_active = TRUE
GROUP BY project
ORDER BY total_cost_usd DESC;

-- Add sync state entry for session sync
INSERT INTO sync_state (sync_type, last_position) VALUES
    ('sessions_to_postgres', '2000-01-01T00:00:00Z')
ON CONFLICT (sync_type) DO NOTHING;
