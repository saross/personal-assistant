# Claude Code Memory System: Implementation Plan v2

## Overview

A custom memory extraction and retrieval system for Claude Code designed for:
- **HASS data science and research software development**
- **LLM interaction research** (studying error modes, prompt effectiveness)
- **GTD-based personal project management**
- **Deep Zotero integration** for scholarly workflow

Key principles:
- **Automated capture** via Claude Code hooks + Haiku extraction
- **Research transparency** via git-tracked JSONL (canonical source)
- **Structured querying** via PostgreSQL
- **Folksonomy tags** with periodic consolidation
- **Zotero as source of truth** for references, memories capture contextual insights
- **Decay by category** - transient memories fade, research persists

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Claude Code Session                          │
│                                                                     │
│  Commands:                                                          │
│    /read [source]      → Deep reading with insight capture          │
│    /synthesise [coll]  → Cross-source synthesis                     │
│    /cite [topic]       → Find and insert citation                   │
│    /gaps [collection]  → Analyse literature gaps                    │
│    /tags               → Review and consolidate tags                │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  │ Hooks fire: SessionEnd, Stop, PreCompact
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      extraction-hook.py                             │
│  1. Read transcript JSONL (from hook's transcript_path)             │
│  2. Find new content since last cursor position                     │
│  3. Send to Haiku for structured extraction                         │
│  4. Normalise tags (lowercase, hyphens, singular)                   │
│  5. Append extracted memories to memories.jsonl                     │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    ~/.claude/memories.jsonl                         │
│  • Append-only, one JSON object per line                            │
│  • Git-tracked for research transparency                            │
│  • Canonical source of truth                                        │
└─────────────────────────────────────────────────────────────────────┘
                                  │
              ┌───────────────────┼───────────────────┐
              ▼                   ▼                   ▼
┌──────────────────────┐ ┌───────────────┐ ┌─────────────────────┐
│     PostgreSQL       │ │    Zotero     │ │   Retrieval Layer   │
│                      │ │  (via API)    │ │                     │
│ • Structured queries │ │               │ │ • MCP tools         │
│ • Decay filtering    │ │ • Bidirectional│ │ • Direct file access│
│ • Tag analytics      │ │   sync of     │ │ • LLM reasoning     │
│ • Future: pgvector   │ │   insights    │ │                     │
└──────────────────────┘ └───────────────┘ └─────────────────────┘
```

---

## Memory Schema

### JSONL Record Format

Each line in `memories.jsonl` is a complete JSON object:

```json
{
  "id": "2026-02-07-a1b2c3d4",
  "session_id": "abc123",
  "category": "source_insight",
  "content": "Smith et al. 2024 reports 3-5m GPS degradation under deciduous canopy, worse under conifers. Recommends 30-second averaging for field data capture.",
  "confidence": "high",
  "research_tags": ["gps-accuracy", "field-methods", "data-quality"],
  "zotero_key": "ABC123XY",
  "source_context": "Reading session on GPS accuracy literature",
  "created_at": "2026-02-07T10:30:00Z"
}
```

### Category Reference

#### Research Methodology (No Decay)

| Category | Purpose | Example |
|----------|---------|---------|
| `methodology` | Analytical approach decisions | "Chose thematic analysis over grounded theory because we have prior theoretical framework from pilot study" |
| `ethics` | IRB, consent, data handling, anonymisation | "Ethics board requires re-consent if we link survey data to interviews - affects Phase 2 design" |
| `provenance` | Data origin, transformations, chain of custody | "Interview transcripts: Rev.ai → manual correction by RA → /data/interviews/cleaned/" |
| `hypothesis` | Research questions, testable predictions | "H2: Field data capture adoption correlates with institutional support, not individual tech comfort" |
| `limitation` | Known constraints, scope boundaries | "Sample excludes researchers without institutional email - potential bias toward larger institutions" |
| `openness` | FAIR, open science, reproducibility, licensing | "Released cleaning scripts under MIT; raw data embargoed until paper acceptance per funder agreement" |
| `source_insight` | What was learned from scholarly sources | "Broman & Woo 2018: 'one rectangle' principle applies to our field data templates" |

#### LLM Interaction Research (No Decay)

| Category | Purpose | Example |
|----------|---------|---------|
| `error_mode` | Claude mistakes, corrections needed | "Claude repeatedly confused StatusLine API with Hooks API despite explicit correction - context window issue?" |
| `surprise` | Unexpected insights, abductive reasoning | "Claude independently suggested decay-based memory pruning - wasn't in my original requirements" |
| `self_reflection` | Claude reflecting on its own reasoning | "Acknowledged uncertainty about vector DB performance claims - appropriately epistemic" |
| `prompt_effectiveness` | What prompts work well/poorly | "Structured XML prompts for extraction yield more consistent JSON than natural language instructions" |

#### Project / Architecture

| Category | Purpose | Decay |
|----------|---------|-------|
| `decision` | Explicit choices with rationale | None |
| `architecture` | System design, structure | None |
| `pattern` | Recurring approaches, conventions | 180 days |
| `gotcha` | Pitfalls, edge cases, things that broke | 180 days |

#### GTD / Personal Assistant

| Category | Purpose | Decay |
|----------|---------|-------|
| `commitment` | Promises made, deadlines agreed | 30 days after deadline |
| `waiting_for` | Blocked on others, follow-up needed | 14 days |
| `contact` | People, preferences, relationships | None (update in place) |

#### Transient

| Category | Purpose | Decay |
|----------|---------|-------|
| `progress` | Status updates, milestones | 30 days |
| `context` | Background information | 30 days |

### Decay Configuration

```python
# decay_config.py

CATEGORY_DECAY_DAYS = {
    # ===== NEVER DECAY =====
    # Research methodology
    "methodology": None,
    "ethics": None,
    "provenance": None,
    "hypothesis": None,
    "limitation": None,
    "openness": None,
    "source_insight": None,
    
    # LLM interaction research
    "error_mode": None,
    "surprise": None,
    "self_reflection": None,
    "prompt_effectiveness": None,
    
    # Core project knowledge
    "decision": None,
    "architecture": None,
    "contact": None,
    
    # ===== MODERATE DECAY =====
    "pattern": 180,
    "gotcha": 180,
    
    # ===== FAST DECAY =====
    "progress": 30,
    "context": 30,
    "commitment": 30,  # Days after the deadline, not creation
    "waiting_for": 14,
}

def get_decay_days(category: str) -> int | None:
    """Return decay days for category, or None if no decay."""
    return CATEGORY_DECAY_DAYS.get(category, 90)  # Default 90 days for unknown
```

### Confidence Levels

| Level | Meaning | Use When |
|-------|---------|----------|
| `high` | Explicit statement, verified fact, clear decision | Direct quote, confirmed outcome, deliberate choice |
| `medium` | Reasonable inference, likely correct | Implied from context, probable interpretation |
| `low` | Tentative, uncertain, may need verification | Speculation, incomplete information |

---

## Research Tags: Folksonomy with Guardrails

### Normalisation Rules

Applied automatically during extraction:

1. **Lowercase only**: `GPS-Accuracy` → `gps-accuracy`
2. **Hyphens not underscores**: `field_methods` → `field-methods`
3. **Singular not plural**: `interviews` → `interview`
4. **No bare acronyms**: `FAIR` → `fair-principles` (on first use)
5. **No spaces**: `data quality` → `data-quality`

### Seed Vocabulary

Suggested tags (not enforced, grows organically):

**Research domains:**
- `field-methods`, `data-quality`, `sampling`, `instrument-design`
- `qualitative`, `quantitative`, `mixed-methods`
- `interview`, `survey`, `observation`, `sensor-data`

**FAIR / Open science:**
- `findable`, `accessible`, `interoperable`, `reusable`
- `open-data`, `open-code`, `preprint`, `reproducibility`
- `licensing`, `embargo`, `doi`, `metadata`

**Technical:**
- `gps-accuracy`, `data-pipeline`, `etl`, `validation`
- `api`, `database`, `performance`, `testing`

**LLM research:**
- `context-window`, `prompt-engineering`, `hallucination`
- `self-correction`, `instruction-following`, `reasoning`

### Tag Gardening Query

Run monthly to identify consolidation candidates:

```sql
-- Tag frequency analysis
SELECT tag, COUNT(*) as usage
FROM memories, UNNEST(research_tags) AS tag
GROUP BY tag
ORDER BY usage DESC;

-- Singleton tags (candidates for consolidation)
SELECT tag, 
       (SELECT content FROM memories m2 
        WHERE tag = ANY(m2.research_tags) LIMIT 1) as example
FROM memories, UNNEST(research_tags) AS tag
GROUP BY tag
HAVING COUNT(*) = 1
ORDER BY tag;

-- Similar tags (potential duplicates)
SELECT DISTINCT a.tag, b.tag
FROM (SELECT DISTINCT UNNEST(research_tags) as tag FROM memories) a,
     (SELECT DISTINCT UNNEST(research_tags) as tag FROM memories) b
WHERE a.tag < b.tag
  AND levenshtein(a.tag, b.tag) <= 2;
```

---

## PostgreSQL Schema

### Database Setup

```sql
-- Create database
CREATE DATABASE claude_memories;

\c claude_memories

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- For fuzzy text search
-- CREATE EXTENSION IF NOT EXISTS vector;  -- Future: pgvector

-- Main memories table
CREATE TABLE memories (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    confidence TEXT DEFAULT 'medium',
    research_tags TEXT[] DEFAULT '{}',
    zotero_key TEXT,  -- Link to Zotero item
    source_context TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL,
    synced_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- For commitment category: when is the deadline?
    deadline_at TIMESTAMPTZ,
    
    -- Soft delete for decay (never hard delete)
    decayed_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT TRUE
);

-- Indexes
CREATE INDEX idx_memories_session ON memories(session_id);
CREATE INDEX idx_memories_category ON memories(category);
CREATE INDEX idx_memories_confidence ON memories(confidence);
CREATE INDEX idx_memories_created ON memories(created_at DESC);
CREATE INDEX idx_memories_tags ON memories USING GIN(research_tags);
CREATE INDEX idx_memories_zotero ON memories(zotero_key) WHERE zotero_key IS NOT NULL;
CREATE INDEX idx_memories_active ON memories(is_active) WHERE is_active = TRUE;
CREATE INDEX idx_memories_content_trgm ON memories USING GIN(content gin_trgm_ops);

-- Full-text search
CREATE INDEX idx_memories_content_fts ON memories 
    USING GIN(to_tsvector('english', content));

-- Sync tracking
CREATE TABLE sync_state (
    id SERIAL PRIMARY KEY,
    sync_type TEXT NOT NULL,  -- 'jsonl_to_postgres', 'postgres_to_zotero'
    last_position TEXT,       -- Line number or timestamp
    last_sync_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO sync_state (sync_type, last_position) VALUES 
    ('jsonl_to_postgres', '0'),
    ('postgres_to_zotero', '2000-01-01T00:00:00Z');

-- Category metadata (for decay configuration)
CREATE TABLE category_config (
    category TEXT PRIMARY KEY,
    decay_days INTEGER,  -- NULL = never decay
    description TEXT
);

INSERT INTO category_config (category, decay_days, description) VALUES
    ('methodology', NULL, 'Analytical approach decisions'),
    ('ethics', NULL, 'IRB, consent, data handling'),
    ('provenance', NULL, 'Data origin and transformations'),
    ('hypothesis', NULL, 'Research questions and predictions'),
    ('limitation', NULL, 'Known constraints and scope'),
    ('openness', NULL, 'FAIR, open science, licensing'),
    ('source_insight', NULL, 'Insights from scholarly sources'),
    ('error_mode', NULL, 'LLM mistakes and corrections'),
    ('surprise', NULL, 'Unexpected insights'),
    ('self_reflection', NULL, 'LLM self-awareness moments'),
    ('prompt_effectiveness', NULL, 'What prompts work'),
    ('decision', NULL, 'Explicit choices with rationale'),
    ('architecture', NULL, 'System design'),
    ('contact', NULL, 'People and relationships'),
    ('pattern', 180, 'Recurring approaches'),
    ('gotcha', 180, 'Pitfalls and edge cases'),
    ('progress', 30, 'Status updates'),
    ('context', 30, 'Background information'),
    ('commitment', 30, 'Promises and deadlines'),
    ('waiting_for', 14, 'Blocked on others');

-- View: Active memories with decay filtering
CREATE VIEW active_memories AS
SELECT m.* 
FROM memories m
LEFT JOIN category_config c ON m.category = c.category
WHERE m.is_active = TRUE
  AND (
    c.decay_days IS NULL  -- Never decay
    OR m.created_at > NOW() - (c.decay_days || ' days')::INTERVAL
    OR (m.category = 'commitment' AND m.deadline_at > NOW() - INTERVAL '30 days')
  );

-- View: Research memories (never decay)
CREATE VIEW research_memories AS
SELECT * FROM memories
WHERE category IN (
    'methodology', 'ethics', 'provenance', 'hypothesis', 
    'limitation', 'openness', 'source_insight',
    'error_mode', 'surprise', 'self_reflection', 'prompt_effectiveness'
)
ORDER BY created_at DESC;

-- View: Memories needing Zotero sync
CREATE VIEW pending_zotero_sync AS
SELECT m.* 
FROM memories m
WHERE m.category = 'source_insight'
  AND m.zotero_key IS NOT NULL
  AND m.created_at > (
    SELECT last_position::timestamptz 
    FROM sync_state 
    WHERE sync_type = 'postgres_to_zotero'
  );
```

### Useful Queries

```sql
-- Recent active memories by category
SELECT category, content, confidence, created_at
FROM active_memories
WHERE created_at > NOW() - INTERVAL '7 days'
ORDER BY created_at DESC;

-- All insights from a specific Zotero source
SELECT content, research_tags, created_at
FROM memories
WHERE zotero_key = 'ABC123XY'
ORDER BY created_at;

-- Tag co-occurrence (what tags appear together?)
SELECT a.tag as tag1, b.tag as tag2, COUNT(*) as co_occurrences
FROM memories m,
     UNNEST(m.research_tags) AS a(tag),
     UNNEST(m.research_tags) AS b(tag)
WHERE a.tag < b.tag
GROUP BY a.tag, b.tag
ORDER BY co_occurrences DESC
LIMIT 20;

-- Research category distribution over time
SELECT DATE_TRUNC('week', created_at) as week,
       category,
       COUNT(*) as count
FROM research_memories
GROUP BY week, category
ORDER BY week DESC, count DESC;

-- Commitments due soon
SELECT content, deadline_at, created_at
FROM memories
WHERE category = 'commitment'
  AND deadline_at BETWEEN NOW() AND NOW() + INTERVAL '7 days'
ORDER BY deadline_at;

-- Full-text search
SELECT content, category, created_at
FROM active_memories
WHERE to_tsvector('english', content) @@ plainto_tsquery('english', 'GPS accuracy canopy');

-- Fuzzy search (typo-tolerant)
SELECT content, category, 
       similarity(content, 'reproducability') as sim
FROM active_memories
WHERE content % 'reproducability'
ORDER BY sim DESC
LIMIT 10;
```

---

## File Structure

```
~/.claude/
├── memories.jsonl                  # Canonical memory store (git-tracked)
├── extraction-cursor.json          # Tracks last processed transcript position
├── sync-cursors.json               # Tracks sync positions (Postgres, Zotero)
├── tag-vocabulary.txt              # Seed tags (grows over time)
├── hooks/
│   ├── extraction-hook.py          # Main extraction hook
│   └── zotero-sync-hook.py         # Bidirectional Zotero sync
├── scripts/
│   ├── sync-to-postgres.py         # JSONL → PostgreSQL sync
│   ├── sync-to-zotero.py           # Insights → Zotero notes
│   ├── apply-decay.py              # Mark decayed memories inactive
│   └── tag-gardening.py            # Tag consolidation helper
├── mcp-servers/
│   └── memory-server.py            # MCP retrieval server
├── commands/
│   ├── read.md                     # /read command
│   ├── synthesise.md               # /synthesise command
│   ├── cite.md                     # /cite command
│   ├── gaps.md                     # /gaps command
│   └── tags.md                     # /tags command
├── logs/
│   └── sync.log                    # Sync job logs
└── settings.json                   # Hook and MCP configuration
```

---

## Component 1: Extraction Hook

### File: `~/.claude/hooks/extraction-hook.py`

```python
#!/usr/bin/env python3
"""
Memory extraction hook for Claude Code.
Triggered by SessionEnd, Stop, and PreCompact hooks.

Extracts structured memories via Haiku, normalises tags,
and appends to canonical JSONL file.
"""

import json
import sys
import os
import re
from pathlib import Path
from datetime import datetime
from typing import Optional
import hashlib

# ============================================================================
# Configuration
# ============================================================================

CLAUDE_DIR = Path.home() / ".claude"
MEMORIES_FILE = CLAUDE_DIR / "memories.jsonl"
CURSOR_FILE = CLAUDE_DIR / "extraction-cursor.json"
VOCABULARY_FILE = CLAUDE_DIR / "tag-vocabulary.txt"

HAIKU_MODEL = "claude-3-5-haiku-20241022"
MIN_CONTENT_LENGTH = 500
MAX_EXCHANGES = 30
MAX_MESSAGE_CHARS = 3000

# ============================================================================
# Categories and Extraction Prompt
# ============================================================================

CATEGORIES_REFERENCE = """
## Categories

### Research Methodology (permanent)
- `methodology` — Analytical approach decisions, why this method over alternatives
- `ethics` — IRB, consent, data handling, anonymisation decisions
- `provenance` — Data origin, transformations, processing chain
- `hypothesis` — Research questions, testable predictions
- `limitation` — Known constraints, scope boundaries, what won't work
- `openness` — FAIR compliance, open science, licensing, reproducibility decisions
- `source_insight` — Key learnings from scholarly sources (include zotero_key if mentioned)

### LLM Interaction Research (permanent)
- `error_mode` — Cases where Claude made mistakes, misunderstood, or needed correction
- `surprise` — Unexpected insights, abductive reasoning, emergent understanding
- `self_reflection` — Claude reflecting on its own reasoning or limitations
- `prompt_effectiveness` — Observations about which prompts worked well or poorly

### Project / Architecture
- `decision` — Explicit choices with rationale (permanent)
- `architecture` — System design, structure decisions (permanent)
- `pattern` — Recurring approaches, conventions (decays after 180 days)
- `gotcha` — Pitfalls, edge cases, things that broke (decays after 180 days)

### GTD / Personal Assistant
- `commitment` — Promises made, deadlines agreed (include deadline if mentioned)
- `waiting_for` — Blocked on others, follow-up needed
- `contact` — People info, preferences, communication style (permanent)

### Transient
- `progress` — Status updates, milestones (decays after 30 days)
- `context` — Background information, requirements (decays after 30 days)
"""

EXTRACTION_PROMPT = """Analyse this conversation and extract memories worth preserving for future sessions.

{categories}

## Output Format

Return a JSON array. Each object must have:
- `category`: One of the categories above
- `content`: The memory (1-3 sentences, specific and self-contained)
- `confidence`: "high", "medium", or "low"
- `research_tags`: Array of relevant tags (see guidelines below)
- `zotero_key`: If a Zotero item key was mentioned, include it (optional)
- `deadline_at`: For commitments, the deadline in ISO format (optional)
- `source_context`: Brief note on conversation context (optional)

## Tag Guidelines

- Use lowercase with hyphens: `gps-accuracy` not `GPS_Accuracy`
- Use singular forms: `interview` not `interviews`
- Be specific: `gps-accuracy` not just `accuracy`
- Prefer existing tags when they fit: {seed_tags}
- Create new tags when needed (they'll be reviewed later)

## Extraction Guidelines

- Extract genuinely important information for future sessions
- Each memory should be understandable without conversation context
- For decisions: include the rationale, not just the choice
- For source_insight: capture what was learned, not bibliographic details
- For error_mode: describe what went wrong AND the correction
- Skip routine exchanges, greetings, acknowledgments
- Prefer fewer high-quality memories over many low-quality ones
- Typical extraction: 2-8 memories per session

<conversation>
{conversation}
</conversation>

Return ONLY a valid JSON array. No other text, no markdown fences."""

# ============================================================================
# Tag Normalisation
# ============================================================================

def normalise_tag(tag: str) -> str:
    """Normalise a tag according to folksonomy rules."""
    # Lowercase
    tag = tag.lower().strip()
    
    # Replace underscores and spaces with hyphens
    tag = re.sub(r'[_\s]+', '-', tag)
    
    # Remove non-alphanumeric except hyphens
    tag = re.sub(r'[^a-z0-9-]', '', tag)
    
    # Collapse multiple hyphens
    tag = re.sub(r'-+', '-', tag)
    
    # Strip leading/trailing hyphens
    tag = tag.strip('-')
    
    # Simple plurals → singular (basic cases)
    if tag.endswith('ies'):
        tag = tag[:-3] + 'y'  # methodologies → methodology
    elif tag.endswith('es') and not tag.endswith('ses'):
        tag = tag[:-2]  # approaches → approach
    elif tag.endswith('s') and not tag.endswith('ss'):
        tag = tag[:-1]  # patterns → pattern
    
    return tag

def normalise_tags(tags: list[str]) -> list[str]:
    """Normalise and deduplicate a list of tags."""
    normalised = [normalise_tag(t) for t in tags if t]
    return list(dict.fromkeys(normalised))  # Dedupe preserving order

def load_seed_tags() -> list[str]:
    """Load seed vocabulary for extraction prompt."""
    if VOCABULARY_FILE.exists():
        return [t.strip() for t in VOCABULARY_FILE.read_text().splitlines() if t.strip()]
    return [
        "field-method", "data-quality", "reproducibility", "fair-principle",
        "gps-accuracy", "interview", "survey", "ethics", "consent",
        "context-window", "prompt-engineering", "self-correction"
    ]

def update_vocabulary(new_tags: list[str]):
    """Add new tags to vocabulary file."""
    existing = set(load_seed_tags())
    new = set(new_tags) - existing
    if new:
        with open(VOCABULARY_FILE, "a") as f:
            for tag in sorted(new):
                f.write(f"{tag}\n")

# ============================================================================
# Core Logic
# ============================================================================

def load_cursor() -> dict:
    """Load cursor tracking last processed position per session."""
    if CURSOR_FILE.exists():
        return json.loads(CURSOR_FILE.read_text())
    return {}

def save_cursor(cursor: dict):
    """Save cursor state."""
    CURSOR_FILE.parent.mkdir(parents=True, exist_ok=True)
    CURSOR_FILE.write_text(json.dumps(cursor, indent=2))

def parse_transcript(transcript_path: str, last_uuid: Optional[str]) -> tuple[list[dict], Optional[str]]:
    """Parse transcript JSONL, returning new content since last_uuid."""
    messages = []
    last_seen_uuid = None
    found_cursor = last_uuid is None
    
    with open(transcript_path) as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            
            entry_uuid = entry.get("uuid")
            
            if not found_cursor:
                if entry_uuid == last_uuid:
                    found_cursor = True
                continue
            
            if entry_uuid:
                last_seen_uuid = entry_uuid
            
            if entry.get("type") in ("user", "assistant"):
                msg = entry.get("message", {})
                content = msg.get("content", "")
                
                if isinstance(content, list):
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict):
                            if block.get("type") == "text":
                                text_parts.append(block.get("text", ""))
                            elif block.get("type") == "thinking":
                                # Include thinking for research value
                                thinking = block.get("thinking", "")[:500]
                                text_parts.append(f"[THINKING]: {thinking}")
                        elif isinstance(block, str):
                            text_parts.append(block)
                    content = " ".join(text_parts)
                
                if content and content.strip():
                    messages.append({
                        "role": entry["type"],
                        "content": content[:MAX_MESSAGE_CHARS],
                        "uuid": entry_uuid
                    })
    
    return messages, last_seen_uuid

def extract_memories(messages: list[dict], session_id: str) -> list[dict]:
    """Send messages to Haiku for extraction."""
    try:
        from anthropic import Anthropic
    except ImportError:
        log("Error: anthropic package not installed")
        return []
    
    conversation_text = "\n\n".join(
        f"[{m['role'].upper()}]: {m['content']}" 
        for m in messages[-MAX_EXCHANGES:]
    )
    
    if len(conversation_text) < MIN_CONTENT_LENGTH:
        return []
    
    seed_tags = ", ".join(load_seed_tags()[:20])
    prompt = EXTRACTION_PROMPT.format(
        categories=CATEGORIES_REFERENCE,
        seed_tags=seed_tags,
        conversation=conversation_text
    )
    
    client = Anthropic()
    try:
        response = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
    except Exception as e:
        log(f"Error calling Haiku: {e}")
        return []
    
    response_text = response.content[0].text.strip()
    
    # Handle markdown fences
    if response_text.startswith("```"):
        lines = response_text.split("\n")
        response_text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    
    try:
        extracted = json.loads(response_text)
        if not isinstance(extracted, list):
            return []
        return extracted
    except json.JSONDecodeError as e:
        log(f"Error parsing extraction response: {e}")
        return []

def format_memories(extracted: list[dict], session_id: str) -> list[dict]:
    """Format extracted memories with metadata and normalised tags."""
    timestamp = datetime.utcnow().isoformat() + "Z"
    memories = []
    all_tags = []
    
    for i, mem in enumerate(extracted):
        if not mem.get("content"):
            continue
        
        # Generate unique ID
        id_source = f"{session_id}-{timestamp}-{i}"
        mem_id = hashlib.sha256(id_source.encode()).hexdigest()[:12]
        
        # Normalise tags
        raw_tags = mem.get("research_tags", [])
        normalised_tags = normalise_tags(raw_tags)
        all_tags.extend(normalised_tags)
        
        record = {
            "id": f"{datetime.utcnow().strftime('%Y-%m-%d')}-{mem_id}",
            "session_id": session_id,
            "category": mem.get("category", "context"),
            "content": mem.get("content"),
            "confidence": mem.get("confidence", "medium"),
            "research_tags": normalised_tags,
            "source_context": mem.get("source_context", ""),
            "created_at": timestamp
        }
        
        # Optional fields
        if mem.get("zotero_key"):
            record["zotero_key"] = mem["zotero_key"]
        if mem.get("deadline_at"):
            record["deadline_at"] = mem["deadline_at"]
        
        memories.append(record)
    
    # Update vocabulary with new tags
    update_vocabulary(all_tags)
    
    return memories

def append_memories(memories: list[dict]):
    """Append memories to JSONL file."""
    MEMORIES_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    with open(MEMORIES_FILE, "a") as f:
        for mem in memories:
            f.write(json.dumps(mem) + "\n")

def log(message: str):
    """Log to stderr."""
    print(f"[extraction-hook] {message}", file=sys.stderr)

def main():
    try:
        hook_input = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        log("Invalid JSON input")
        sys.exit(1)
    
    transcript_path = hook_input.get("transcript_path")
    session_id = hook_input.get("session_id", "unknown")
    
    if not transcript_path or not Path(transcript_path).exists():
        sys.exit(0)
    
    cursor = load_cursor()
    last_uuid = cursor.get(session_id)
    
    messages, new_last_uuid = parse_transcript(transcript_path, last_uuid)
    
    if not messages:
        sys.exit(0)
    
    if new_last_uuid:
        cursor[session_id] = new_last_uuid
        save_cursor(cursor)
    
    extracted = extract_memories(messages, session_id)
    
    if extracted:
        memories = format_memories(extracted, session_id)
        append_memories(memories)
        log(f"Extracted {len(memories)} memories from {len(messages)} messages")
    
    # Suppress output from transcript
    print(json.dumps({"hookSpecificOutput": {"suppressOutput": True}}))

if __name__ == "__main__":
    main()
```

---

## Component 2: PostgreSQL Sync

### File: `~/.claude/scripts/sync-to-postgres.py`

```python
#!/usr/bin/env python3
"""
Sync memories from JSONL to PostgreSQL.
Run via cron, SessionStart hook, or manually.
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime

import psycopg2
from psycopg2.extras import execute_values

# ============================================================================
# Configuration
# ============================================================================

MEMORIES_FILE = Path.home() / ".claude" / "memories.jsonl"
CURSORS_FILE = Path.home() / ".claude" / "sync-cursors.json"
DATABASE_URL = os.environ.get("CLAUDE_MEMORIES_DB", "postgresql://localhost/claude_memories")

# ============================================================================
# Main Logic
# ============================================================================

def load_cursors() -> dict:
    if CURSORS_FILE.exists():
        return json.loads(CURSORS_FILE.read_text())
    return {}

def save_cursors(cursors: dict):
    CURSORS_FILE.write_text(json.dumps(cursors, indent=2))

def main():
    if not MEMORIES_FILE.exists():
        print("No memories file found")
        return
    
    cursors = load_cursors()
    last_line = int(cursors.get("jsonl_to_postgres", 0))
    
    memories_to_insert = []
    current_line = 0
    
    with open(MEMORIES_FILE) as f:
        for i, line in enumerate(f):
            current_line = i + 1
            if i < last_line:
                continue
            
            try:
                mem = json.loads(line.strip())
            except json.JSONDecodeError:
                print(f"Skipping invalid JSON on line {current_line}", file=sys.stderr)
                continue
            
            memories_to_insert.append((
                mem.get("id"),
                mem.get("session_id"),
                mem.get("category"),
                mem.get("content"),
                mem.get("confidence", "medium"),
                mem.get("research_tags", []),
                mem.get("zotero_key"),
                mem.get("source_context", ""),
                mem.get("created_at"),
                mem.get("deadline_at"),
            ))
    
    if not memories_to_insert:
        print(f"No new memories to sync (at line {last_line})")
        return
    
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    try:
        execute_values(cur, """
            INSERT INTO memories (
                id, session_id, category, content, confidence,
                research_tags, zotero_key, source_context, created_at, deadline_at
            ) VALUES %s
            ON CONFLICT (id) DO NOTHING
        """, memories_to_insert)
        
        conn.commit()
        print(f"Synced {len(memories_to_insert)} memories")
        
        cursors["jsonl_to_postgres"] = str(current_line)
        save_cursors(cursors)
        
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    main()
```

---

## Component 3: Zotero Bidirectional Sync

### File: `~/.claude/scripts/sync-to-zotero.py`

```python
#!/usr/bin/env python3
"""
Sync source_insight memories back to Zotero item notes.
Appends timestamped insights to the Notes field of referenced Zotero items.

Requires: pyzotero (pip install pyzotero)
Environment: ZOTERO_LIBRARY_ID, ZOTERO_API_KEY
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime

from pyzotero import zotero

# ============================================================================
# Configuration
# ============================================================================

CURSORS_FILE = Path.home() / ".claude" / "sync-cursors.json"
MEMORIES_FILE = Path.home() / ".claude" / "memories.jsonl"

LIBRARY_ID = os.environ.get("ZOTERO_LIBRARY_ID")
LIBRARY_TYPE = os.environ.get("ZOTERO_LIBRARY_TYPE", "user")  # or "group"
API_KEY = os.environ.get("ZOTERO_API_KEY")

# ============================================================================
# Main Logic
# ============================================================================

def load_cursors() -> dict:
    if CURSORS_FILE.exists():
        return json.loads(CURSORS_FILE.read_text())
    return {}

def save_cursors(cursors: dict):
    CURSORS_FILE.write_text(json.dumps(cursors, indent=2))

def main():
    if not all([LIBRARY_ID, API_KEY]):
        print("Missing ZOTERO_LIBRARY_ID or ZOTERO_API_KEY", file=sys.stderr)
        sys.exit(1)
    
    if not MEMORIES_FILE.exists():
        print("No memories file found")
        return
    
    cursors = load_cursors()
    last_sync = cursors.get("postgres_to_zotero", "2000-01-01T00:00:00Z")
    last_sync_dt = datetime.fromisoformat(last_sync.replace("Z", "+00:00"))
    
    # Find source_insights with zotero_key since last sync
    insights_to_sync = []
    
    with open(MEMORIES_FILE) as f:
        for line in f:
            try:
                mem = json.loads(line.strip())
            except json.JSONDecodeError:
                continue
            
            if mem.get("category") != "source_insight":
                continue
            if not mem.get("zotero_key"):
                continue
            
            created = mem.get("created_at", "")
            try:
                created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                if created_dt > last_sync_dt:
                    insights_to_sync.append(mem)
            except ValueError:
                continue
    
    if not insights_to_sync:
        print("No new insights to sync to Zotero")
        return
    
    print(f"Syncing {len(insights_to_sync)} insights to Zotero...")
    
    # Connect to Zotero
    zot = zotero.Zotero(LIBRARY_ID, LIBRARY_TYPE, API_KEY)
    
    # Group insights by Zotero key
    by_key = {}
    for insight in insights_to_sync:
        key = insight["zotero_key"]
        if key not in by_key:
            by_key[key] = []
        by_key[key].append(insight)
    
    synced_count = 0
    latest_timestamp = last_sync
    
    for zotero_key, insights in by_key.items():
        try:
            # Fetch current item
            item = zot.item(zotero_key)
            
            # Build note content to append
            note_additions = []
            for insight in insights:
                timestamp = insight.get("created_at", "")[:10]  # Just date
                content = insight.get("content", "")
                tags = ", ".join(insight.get("research_tags", []))
                
                note_entry = f"\n\n---\n[Claude Code Insight - {timestamp}]\n{content}"
                if tags:
                    note_entry += f"\nTags: {tags}"
                note_additions.append(note_entry)
                
                # Track latest timestamp
                if insight.get("created_at", "") > latest_timestamp:
                    latest_timestamp = insight["created_at"]
            
            # Check if item has a note child or use item note field
            # For simplicity, we'll create/append to a child note
            children = zot.children(zotero_key)
            existing_note = None
            
            for child in children:
                if child["data"].get("itemType") == "note":
                    title = child["data"].get("note", "")
                    if "[Claude Code Insights]" in title or title.startswith("<p>[Claude Code"):
                        existing_note = child
                        break
            
            combined_additions = "".join(note_additions)
            
            if existing_note:
                # Append to existing note
                current_note = existing_note["data"]["note"]
                updated_note = current_note + combined_additions
                existing_note["data"]["note"] = updated_note
                zot.update_item(existing_note)
                print(f"  Updated note for {zotero_key}")
            else:
                # Create new note
                new_note = {
                    "itemType": "note",
                    "parentItem": zotero_key,
                    "note": f"<p><strong>[Claude Code Insights]</strong></p>{combined_additions}"
                }
                zot.create_items([new_note])
                print(f"  Created note for {zotero_key}")
            
            synced_count += len(insights)
            
        except Exception as e:
            print(f"  Error syncing {zotero_key}: {e}", file=sys.stderr)
            continue
    
    # Update cursor
    cursors["postgres_to_zotero"] = latest_timestamp
    save_cursors(cursors)
    
    print(f"Synced {synced_count} insights to Zotero")

if __name__ == "__main__":
    main()
```

---

## Component 4: Decay Management

### File: `~/.claude/scripts/apply-decay.py`

```python
#!/usr/bin/env python3
"""
Mark decayed memories as inactive based on category configuration.
Run weekly via cron.

Note: This does NOT delete from JSONL (preserving research transparency).
It only marks records inactive in Postgres for query filtering.
"""

import os
import psycopg2

DATABASE_URL = os.environ.get("CLAUDE_MEMORIES_DB", "postgresql://localhost/claude_memories")

def main():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    try:
        # Mark memories as decayed based on category config
        cur.execute("""
            UPDATE memories m
            SET is_active = FALSE, decayed_at = NOW()
            FROM category_config c
            WHERE m.category = c.category
              AND c.decay_days IS NOT NULL
              AND m.is_active = TRUE
              AND m.created_at < NOW() - (c.decay_days || ' days')::INTERVAL
              AND m.category != 'commitment'
            RETURNING m.id, m.category
        """)
        
        decayed_regular = cur.fetchall()
        
        # Handle commitments separately (decay based on deadline, not creation)
        cur.execute("""
            UPDATE memories
            SET is_active = FALSE, decayed_at = NOW()
            WHERE category = 'commitment'
              AND is_active = TRUE
              AND deadline_at IS NOT NULL
              AND deadline_at < NOW() - INTERVAL '30 days'
            RETURNING id
        """)
        
        decayed_commitments = cur.fetchall()
        
        conn.commit()
        
        total = len(decayed_regular) + len(decayed_commitments)
        print(f"Marked {total} memories as decayed:")
        
        # Summarise by category
        from collections import Counter
        categories = Counter(m[1] for m in decayed_regular)
        for cat, count in categories.most_common():
            print(f"  {cat}: {count}")
        if decayed_commitments:
            print(f"  commitment: {len(decayed_commitments)}")
            
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    main()
```

---

## Component 5: Custom Commands

### File: `~/.claude/commands/read.md`

```markdown
# Deep Reading Session

When the user invokes `/read [query]`, conduct a structured reading session:

## Workflow

1. **Find the source**
   - Search Zotero for the query (title, author, or item key)
   - If multiple matches, present options and ask user to select
   - If no matches, offer to search web or ask for clarification

2. **Load the source**
   - Fetch full item metadata from Zotero
   - Check for attached PDF or linked file
   - Load any existing Zotero notes
   - Check memory system for previous `source_insight` entries with this zotero_key

3. **Present overview**
   ```
   📖 [Title]
   Authors: [Authors] ([Year])
   Collections: [Zotero collections]
   
   Abstract:
   [Abstract text]
   
   Previous insights from this source:
   [Any existing source_insight memories]
   ```

4. **Establish reading goal**
   Ask: "What question are you bringing to this source?"
   
5. **Guided reading**
   Based on their question:
   - If PDF available: identify relevant sections, summarise key passages
   - If no PDF: work from abstract and any notes
   - Highlight passages that address their question
   - Note methodological details relevant to their work

6. **Capture insights**
   At natural stopping points, ask:
   "Should I capture any insights from this discussion?"
   
   For each insight to capture:
   - Category: `source_insight`
   - Include the `zotero_key`
   - Tag with relevant research_tags
   - Make content self-contained (understandable without the conversation)

7. **Update Zotero**
   Ask: "Should I add our insights to the Zotero notes for this item?"
   If yes, format and append via Zotero API.

## Example Interaction

```
User: /read Smith 2024 GPS accuracy

Claude: I found this item in your Zotero library:

📖 Field GPS Accuracy Under Forest Canopy: A Systematic Review
Authors: Smith, J. & Chen, L. (2024)
Collections: Field Methods, GPS Research

Abstract:
This systematic review examines GPS positional accuracy under various forest canopy conditions...

I also found 1 previous insight from this source in your memories:
- "Smith et al. 2024 reports 3-5m GPS degradation under deciduous canopy"

What question are you bringing to this source today?

User: I want to understand their methodology for measuring accuracy

Claude: [Reads relevant sections, summarises methodology]
...
```
```

### File: `~/.claude/commands/synthesise.md`

```markdown
# Literature Synthesis

When the user invokes `/synthesise [collection]`, produce a thematic synthesis:

## Workflow

1. **Load collection**
   - Fetch all items from the named Zotero collection
   - For each item: title, authors, year, abstract, notes
   - Also load any `source_insight` memories linked to these items

2. **Initial analysis**
   Present:
   ```
   📚 Synthesis: [Collection Name]
   Sources: [N] items
   Date range: [Earliest] - [Latest]
   
   Loading abstracts and notes...
   ```

3. **Identify themes**
   Analyse across all sources to identify:
   - **Common themes**: What do multiple sources address?
   - **Methodological approaches**: What methods are used?
   - **Key debates**: Where do sources disagree?
   - **Gaps**: What's NOT covered that might be expected?

4. **Produce synthesis**
   Structure by theme, NOT by source:
   
   ```markdown
   # Synthesis: [Collection Name]
   
   ## Overview
   [2-3 sentence summary of the collection's scope]
   
   ## Theme 1: [Theme Name]
   [Synthesis paragraph with citations (Author, Year)]
   
   ## Theme 2: [Theme Name]
   ...
   
   ## Methodological Approaches
   [Summary of methods used across sources]
   
   ## Key Debates
   [Areas of disagreement or tension]
   
   ## Gaps and Opportunities
   [What's missing that might warrant further investigation]
   
   ## References
   [Full citations for all sources referenced]
   ```

5. **Save and offer updates**
   - Save synthesis to a markdown file
   - Offer to add synthesis summary to Zotero collection notes

## Guidelines

- Cite sources inline as (Author, Year)
- Synthesise across sources—don't just summarise each one
- Note the strength of evidence (single study vs. multiple confirmations)
- Flag your confidence level for inferences
- Keep synthesis actionable for the user's research context
```

### File: `~/.claude/commands/cite.md`

```markdown
# Citation on Demand

When the user indicates they need a citation while writing—using markers like `[cite]`, `[citation needed]`, `[ref]`, or phrases like "find a source for this"—provide appropriate citations.

## Workflow

1. **Identify the claim**
   Determine exactly what claim needs support

2. **Search for sources**
   Priority order:
   a. Check memory system for relevant `source_insight` entries
   b. Search Zotero library for matching sources
   c. If nothing suitable, note this and offer to search web

3. **Present options**
   If multiple candidates:
   ```
   Found 3 potential sources for this claim:
   1. Smith (2024) - directly addresses GPS accuracy under canopy
   2. Chen et al. (2023) - broader review, mentions this in discussion
   3. Wilson (2022) - tangentially related
   
   Which would you prefer, or should I use the strongest match?
   ```

4. **Insert citation**
   - Detect citation format from context (APA, Chicago, etc.)
   - If unclear, ask or use (Author, Year) as default
   - Insert at the marked location

5. **Offer full reference**
   After inserting, offer: "Want me to add the full reference to your bibliography?"

## Format Detection

Look for existing citations in the document to match format:
- `(Smith, 2024)` or `Smith (2024)` → APA
- `Smith et al.` with footnotes → Chicago
- `[1]` or `[Smith2024]` → Numbered or key-based
- If no existing citations, ask user preference

## Example

```
User: GPS accuracy degrades significantly under forest canopy [cite], which affects our field data collection protocol.

Claude: I found a strong source for this in your Zotero library:

Smith, J. & Chen, L. (2024) report 3-5m degradation under deciduous canopy in their systematic review.

Updated text:
"GPS accuracy degrades significantly under forest canopy (Smith & Chen, 2024), which affects our field data collection protocol."

Should I add the full reference to your bibliography?
```
```

### File: `~/.claude/commands/gaps.md`

```markdown
# Literature Gap Analysis

When the user invokes `/gaps [collection or topic]`, analyse what's missing from their literature:

## Workflow

1. **Establish scope**
   - If collection name provided: load that Zotero collection
   - If topic provided: search Zotero for relevant items
   - Confirm scope with user before proceeding

2. **Map coverage**
   Analyse what the current sources cover:
   - **Topics/concepts**: What subjects are addressed?
   - **Methods**: What methodological approaches are used?
   - **Populations/contexts**: Who/what is studied?
   - **Time periods**: When was research conducted?
   - **Geographies**: Where was research conducted?
   - **Theoretical frameworks**: What theories are applied?

3. **Identify gaps**
   Based on the topic and what a complete literature would include:
   - **Missing topics**: Expected subjects not covered
   - **Methodological gaps**: Approaches not represented
   - **Population gaps**: Groups not studied
   - **Temporal gaps**: Time periods not covered
   - **Geographic gaps**: Regions not represented
   - **Theoretical gaps**: Frameworks not applied

4. **Present analysis**
   ```markdown
   # Gap Analysis: [Collection/Topic]
   
   ## Current Coverage
   Your [N] sources cover:
   - Topics: [list]
   - Methods: [list]
   - Contexts: [list]
   
   ## Identified Gaps
   
   ### High Priority
   [Gaps that seem most significant for your research]
   
   ### Medium Priority
   [Gaps that might be worth addressing]
   
   ### Potential Gaps
   [Gaps that may or may not be relevant]
   
   ## Recommendations
   [Specific suggestions for filling important gaps]
   ```

5. **Offer to search**
   "Would you like me to search for sources that might fill any of these gaps?"
   
   If yes:
   - Search web for recent publications
   - Present promising finds
   - Offer to add to Zotero

## Guidelines

- Be specific about what's missing, not vague
- Consider the user's research context when prioritising gaps
- Distinguish between "no one has studied this" vs "you haven't collected this yet"
- Suggest search terms for finding gap-filling sources
```

### File: `~/.claude/commands/tags.md`

```markdown
# Tag Gardening

When the user invokes `/tags`, help review and consolidate research tags:

## Workflow

1. **Load tag statistics**
   Query the memory system for:
   - All unique tags with usage counts
   - Singleton tags (used only once)
   - Similar tags (potential duplicates)
   - Recent tags (last 30 days)

2. **Present overview**
   ```
   📊 Tag Statistics
   
   Total unique tags: [N]
   Total tag usages: [M]
   
   Top 10 tags:
   1. field-method (47)
   2. data-quality (35)
   ...
   
   Singleton tags (used once): [N]
   Potential duplicates detected: [N]
   ```

3. **Suggest consolidations**
   Identify and suggest merges:
   ```
   Suggested consolidations:
   
   1. gps-error (3) + gps-accuracy (7) + gps-precision (2)
      → Recommend: gps-accuracy (12 total)
      Reason: All refer to GPS measurement quality
   
   2. interview (5) + interviews (3)
      → Recommend: interview (8 total)
      Reason: Singular form preferred
   
   3. fair (4) + fair-principle (2)
      → Recommend: fair-principle (6 total)
      Reason: More specific
   
   Apply these consolidations? [all / select / skip]
   ```

4. **Review singletons**
   For singleton tags:
   ```
   Singleton tags to review:
   
   - canopy-density: "Smith 2024 found canopy density affects GPS more than species"
     [keep / merge with → / delete]
   
   - baseline-drift: "Sensor baseline drift requires daily recalibration"  
     [keep / merge with → / delete]
   ```

5. **Apply changes**
   If consolidations approved:
   - Update memories in JSONL (rewrite file)
   - Update Postgres
   - Update vocabulary file

6. **Show results**
   ```
   ✅ Tag consolidation complete
   
   Merged: 3 tag groups
   Deleted: 2 singleton tags
   Kept: 5 singleton tags
   
   New tag count: [N] (was [M])
   ```

## Consolidation Rules

When merging tags:
- Prefer more specific over less specific
- Prefer established vocabulary terms
- Prefer singular forms
- Keep research-significant distinctions (don't merge "qualitative" into "method")
- Document non-obvious merges in tag vocabulary file

## Automated Suggestions

Detect potential duplicates using:
- Levenshtein distance ≤ 2
- Singular/plural variations
- Hyphenation variations
- Common synonyms (e.g., "gps" / "gnss")
```

---

## Component 6: CLAUDE.md Integration

Add to your project or global CLAUDE.md:

```markdown
## Memory System

This workspace uses an automated memory extraction system for capturing insights across sessions.

### Automatic Capture

Memories are automatically extracted after responses via hooks:
- Stored in `~/.claude/memories.jsonl` (canonical, git-tracked)
- Synced to PostgreSQL for queries
- Source insights synced back to Zotero notes

### Categories

**Research (permanent):** methodology, ethics, provenance, hypothesis, limitation, openness, source_insight
**LLM Research (permanent):** error_mode, surprise, self_reflection, prompt_effectiveness
**Project (mixed):** decision (permanent), architecture (permanent), pattern (180d), gotcha (180d)
**GTD:** commitment (30d), waiting_for (14d), contact (permanent)
**Transient:** progress (30d), context (30d)

### Commands

- `/read [source]` — Deep reading session with a Zotero source
- `/synthesise [collection]` — Thematic synthesis across a collection
- `/cite [topic]` — Find and insert citation while writing
- `/gaps [collection]` — Analyse literature gaps
- `/tags` — Review and consolidate research tags

### Tag Guidelines

Use lowercase with hyphens: `gps-accuracy`, `field-method`, `fair-principle`
Prefer existing tags; create new ones when needed (reviewed monthly via `/tags`)

### Zotero Integration

Zotero is the source of truth for references. The memory system captures:
- **What you learned** from sources (source_insight)
- **How sources influenced decisions** (with zotero_key links)

NOT captured in memories (Zotero handles these):
- Bibliographic metadata
- PDFs and attachments
- Collection organisation

### Citation Handling

When writing documents that need citations:
- Mark with [cite], [citation needed], or "find a source for this"
- I'll search your Zotero library and memory system
- I'll match the citation format already in use

### Manual Memory Capture

If you want to explicitly capture something:
"Remember that [insight]" — I'll format and queue for extraction

Or create directly:
```json
{"category": "decision", "content": "...", "confidence": "high", "research_tags": [...]}
```
```

---

## Hook Configuration

### File: `~/.claude/settings.json`

```json
{
  "hooks": {
    "Stop": [
      {
        "type": "command",
        "command": "python3 ~/.claude/hooks/extraction-hook.py",
        "timeout": 30000
      }
    ],
    "PreCompact": [
      {
        "matcher": ["auto", "manual"],
        "type": "command",
        "command": "python3 ~/.claude/hooks/extraction-hook.py",
        "timeout": 30000
      }
    ],
    "SessionEnd": [
      {
        "type": "command",
        "command": "python3 ~/.claude/hooks/extraction-hook.py",
        "timeout": 30000
      }
    ]
  }
}
```

---

## Cron Jobs

```bash
# Add to crontab (crontab -e)

# Sync JSONL to Postgres every 5 minutes
*/5 * * * * python3 ~/.claude/scripts/sync-to-postgres.py >> ~/.claude/logs/sync.log 2>&1

# Sync insights to Zotero hourly
0 * * * * python3 ~/.claude/scripts/sync-to-zotero.py >> ~/.claude/logs/zotero-sync.log 2>&1

# Apply decay weekly (Sunday 3am)
0 3 * * 0 python3 ~/.claude/scripts/apply-decay.py >> ~/.claude/logs/decay.log 2>&1
```

---

## Implementation Checklist

### Phase 1: Core Extraction (Day 1)

- [ ] Create directory structure: `mkdir -p ~/.claude/{hooks,scripts,commands,logs,mcp-servers}`
- [ ] Install Python packages: `pip install anthropic psycopg2-binary pyzotero`
- [ ] Create `extraction-hook.py`
- [ ] Create `tag-vocabulary.txt` with seed tags
- [ ] Add hook configuration to `~/.claude/settings.json`
- [ ] Test: have a conversation, check `~/.claude/memories.jsonl`
- [ ] Initialise git: `cd ~/.claude && git init && git add memories.jsonl tag-vocabulary.txt`

### Phase 2: PostgreSQL (Day 1-2)

- [ ] Create database: `createdb claude_memories`
- [ ] Run schema SQL (save above to file, then `psql claude_memories < schema.sql`)
- [ ] Create `sync-to-postgres.py`
- [ ] Test manual sync
- [ ] Set up cron job for automatic sync

### Phase 3: Zotero Integration (Day 2)

- [ ] Verify Zotero API credentials in environment
- [ ] Create `sync-to-zotero.py`
- [ ] Test manual sync with a known source_insight
- [ ] Set up cron job for hourly sync
- [ ] Verify notes appear in Zotero

### Phase 4: Commands (Day 2-3)

- [ ] Create `/read` command
- [ ] Create `/synthesise` command
- [ ] Create `/cite` command
- [ ] Create `/gaps` command
- [ ] Create `/tags` command
- [ ] Test each command with real data

### Phase 5: Decay and Maintenance (Day 3)

- [ ] Create `apply-decay.py`
- [ ] Set up weekly decay cron job
- [ ] Create `tag-gardening.py` helper script
- [ ] Document monthly maintenance routine

### Phase 6: Documentation (Day 3)

- [ ] Update CLAUDE.md with memory system documentation
- [ ] Create README for ~/.claude directory
- [ ] Document backup and export procedures

---

## Dependencies

```bash
# Python packages
pip install anthropic psycopg2-binary pyzotero

# PostgreSQL (Ubuntu)
sudo apt install postgresql postgresql-contrib

# Or via Docker
docker run -d --name postgres \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 \
  -v claude_postgres_data:/var/lib/postgresql/data \
  postgres:16

# Enable fuzzy text search extension
psql claude_memories -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```

### Environment Variables

```bash
# Add to ~/.bashrc or ~/.zshrc

export ANTHROPIC_API_KEY="your-anthropic-key"
export CLAUDE_MEMORIES_DB="postgresql://localhost/claude_memories"
export ZOTERO_LIBRARY_ID="your-library-id"
export ZOTERO_API_KEY="your-zotero-api-key"
export ZOTERO_LIBRARY_TYPE="user"  # or "group"
```

---

## Estimated Costs

| Component | Cost |
|-----------|------|
| Haiku extraction (~20 calls/day) | ~$0.005/day |
| PostgreSQL (local) | $0 |
| Zotero API | $0 |
| Storage (~10KB/day) | Negligible |
| **Total** | **< $2/month** |

---

## Backup and Export

### Git Backup (Recommended)

```bash
# In ~/.claude directory
git add memories.jsonl tag-vocabulary.txt
git commit -m "Memory backup $(date +%Y-%m-%d)"
git push  # If you have a remote configured
```

### Full Export

```bash
# Export everything for research sharing
mkdir -p ~/claude-memory-export-$(date +%Y%m%d)
cp ~/.claude/memories.jsonl ~/claude-memory-export-$(date +%Y%m%d)/
pg_dump claude_memories > ~/claude-memory-export-$(date +%Y%m%d)/postgres-dump.sql
cp ~/.claude/tag-vocabulary.txt ~/claude-memory-export-$(date +%Y%m%d)/
```

### Research Dataset Export

```bash
# Export just research-relevant memories
psql claude_memories -c "
COPY (
    SELECT id, category, content, confidence, research_tags, zotero_key, created_at
    FROM research_memories
    ORDER BY created_at
) TO STDOUT WITH CSV HEADER
" > research-memories-export.csv
```

---

## Troubleshooting

### Extraction not running

1. Check hook registration: `cat ~/.claude/settings.json`
2. Check Python path: `which python3`
3. Test manually: `echo '{"transcript_path": "/path/to/transcript.jsonl", "session_id": "test"}' | python3 ~/.claude/hooks/extraction-hook.py`
4. Check Claude Code verbose mode (Ctrl+O)

### Tags not normalising

1. Check `normalise_tag()` function is being called
2. Review `tag-vocabulary.txt` for unexpected entries
3. Run `/tags` to identify and fix inconsistencies

### Zotero sync failing

1. Verify credentials: `echo $ZOTERO_API_KEY`
2. Test API access: `python3 -c "from pyzotero import zotero; z = zotero.Zotero('$ZOTERO_LIBRARY_ID', 'user', '$ZOTERO_API_KEY'); print(z.top(limit=1))"`
3. Check for rate limiting (Zotero limits to ~100 requests/hour)
4. Review sync logs: `tail ~/.claude/logs/zotero-sync.log`

### Decay not applying

1. Check category_config table has correct decay_days values
2. Verify cron job is running: `grep decay /var/log/syslog`
3. Run manually: `python3 ~/.claude/scripts/apply-decay.py`
4. Check for NULL deadline_at on commitment memories
