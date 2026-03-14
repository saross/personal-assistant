# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

This is the personal assistant system — a cross-project hub for memory, task management, and accountability.

## Repository Structure

```text
~/personal-assistant/                    (PUBLIC repo)
├── commands/          # Slash command definitions
├── hooks/             # Claude Code hooks (extraction, accountability)
├── scripts/           # Sync and maintenance scripts
├── skills/            # Custom Claude Code skills
├── planning/          # System design documents
├── style/             # Writing style guides
├── tests/             # Unit tests for hooks and scripts
├── published/         # Selectively published prompts
├── data/              # PRIVATE submodule (saross/pa-data)
│   ├── memories/      #   Memory system (JSONL canonical)
│   ├── tasks/         #   Task system (FOCUS.md, inbox, projects)
│   ├── notes/         #   Craft notebook (user's practical learnings)
│   ├── reports/       #   Weekly reviews, collaborator reports, retros, work log, time log
│   ├── standups/      #   Daily standup outputs
│   ├── scratchpad.md  #   Claude's learning log (corrections, patterns)
│   └── logs/          #   Runtime logs (gitignored)
├── memories → data/memories   # Symlinks for path compatibility
├── tasks → data/tasks
├── notes → data/notes
├── reports → data/reports
├── standups → data/standups
└── logs → data/logs
```

## Memory System

Memories are automatically extracted from sessions via hooks and stored in `memories/memories.jsonl`.

### Categories

**Research (permanent):** methodology, ethics, provenance, hypothesis, limitation, openness, source_insight

**LLM Research (permanent):** error_mode, surprise, self_reflection, prompt_effectiveness

**Project (mixed):** decision (permanent), architecture (permanent), pattern (180d), gotcha (180d)

**GTD:** commitment (30d after deadline), waiting_for (14d), contact (permanent)

**Transient:** progress (30d), context (30d)

**Retrospective (assigned during review, not extraction):** slip (permanent), completion (90d), blocker_real (30d), blocker_excuse (permanent)

**System Adaptation:** system_evolution (permanent), system_friction (60d), system_success (90d)

### Tag Guidelines

- Use lowercase with hyphens: `gps-accuracy`, `field-method`, `fair-principle`
- Singular forms preferred (consolidate plurals in monthly gardening)
- See `memories/tag-vocabulary.txt` for seed vocabulary

### Commands

- `/recall [query]` — Search memories
- `/remember [content]` — Manually capture a memory
- `/capture [text]` — Quick add to inbox
- `/craft [text]` — Quick craft notebook entry (auto-classifies)
- `/focus add|remove|swap` — Change focus (enforces limits)
- `/done [task]` — Mark complete, celebrate, refocus
- `/standup` — Morning accountability check (escalates over time)
- `/recap` — Evening recap (estimation calibration, work log, daily journal)
- `/track [project] [hours] [description]` — Record time spent on a project
- `/review` — Weekly review + collaborator reports
- `/retro` — Monthly system retrospective
- `/sync-board` — Push task state to GitHub Issues
- `/process-email` — Email triage (Gmail MCP or manual paste)

## Craft Notebook

The `notes/` directory is the user's personal craft notebook — practical
learnings for the *user* to revisit, distinct from `memories/` which stores
context for Claude.

| File | Content |
|------|---------|
| `notes/llm-craft.md` | LLM interaction patterns, prompting techniques |
| `notes/grimoire/` | Effective prompts with mechanism analysis (one file per prompt) |
| `notes/working-practices.md` | Time management, focus, productivity |
| `notes/coding-practices.md` | Tooling, debugging, dev environment |
| `notes/general/` | General notes, reference material, observations (one file per note) |

Use `/craft` for quick entries. Longer observations are discussed in
conversation and added manually.

## Scratchpad

`data/scratchpad.md` is Claude's running learning log — loaded every
session via the startup hook. It captures corrections, preferences, and
patterns that compound across sessions.

### When to write

- **Correction received**: Shawn corrects your output, approach, or
  assumption. Record what was wrong and what was right.
- **Preference discovered**: Something about how Shawn works that isn't
  in CLAUDE.md yet.
- **Approach succeeded or failed**: A technique that produced notably
  good or poor results.
- **Pattern noticed**: Recurring observation about session dynamics.

### When NOT to write

- Things that belong in CLAUDE.md (permanent system rules)
- Things already captured by `/remember` or extraction (project decisions,
  research methodology, commitments)
- Routine exchanges or acknowledgements
- Entries longer than 2–3 lines — the scratchpad is terse

### Format

Append under the relevant section heading. Each entry is a dated bullet:

```text
- 2026-03-14: Shawn corrected X to Y — reason Z
```

### Maintenance

Distilled during monthly `/retro`. Patterns get promoted to memories or
CLAUDE.md rules. Stale entries are pruned. Target: ≤150 lines.

## Task System

### Philosophy

- Maximum 3 **actionable tasks** in active focus (FOCUS.md) — not projects
- Focus slots track concrete deliverables (e.g., "results write-up"), not project umbrellas
- Projects are grouping tags in the `Project` field, not the unit of tracking
- Backlog holds scoped tasks ready for promotion, not abstract project buckets
- Finish before starting
- Sequential beats parallel
- Confrontational accountability
- System adapts based on evidence

### Key Files

- `tasks/FOCUS.md` — Current focus (THE critical file)
- `tasks/SYSTEM.md` — System configuration (tune the parameters)
- `tasks/inbox.md` — Captures awaiting processing
- `tasks/backlog.md` — Scoped tasks ready to promote to focus (table format)
- `tasks/waiting-for.md` — Blocked on others
- `tasks/collaborators.md` — People who receive tailored reports from `/review`
- `tasks/done/` — Monthly completion archives

### Commands

- `/standup` — Morning accountability check (escalates over time)
- `/recap` — Evening recap (estimation calibration, work log, daily journal)
- `/track [project] [hours] [description]` — Record time spent on a project
- `/capture [text]` — Quick add to inbox
- `/done [task]` — Mark complete, celebrate, refocus
- `/focus add|remove|swap` — Change focus (enforces limits)
- `/review` — Weekly reckoning + collaborator reports
- `/retro` — Monthly system retrospective
- `/sync-board` — Push task state to GitHub Issues
- `/process-email` — Email triage (Gmail MCP or manual paste)

### Accountability Agreement

I have permission to be confrontational about:

- Items stuck in focus for too long (escalates over ~2 weeks)
- Patterns of avoidance (research vs personal)
- Gaps between stated priorities and actual time allocation
- Slips on commitments

Hard questions are expected. Honest answers required.

## Context

Shawn is an archaeologist and ancient historian with a long academic career who recently took a redundancy from university. This is a finite window for making progress on research and business goals before returning to "normal" work.

**Time-sensitive work:**

- LLM-History-Paper (end of March 2026)
- fieldmark-docs-staging (EFN startup documentation)

**Less time-sensitive:**

- map-reader-llm
- llm-reproducibility

Research should be primary focus. Personal infrastructure work (this system) should be out-of-hours.

## Tone

- No pleasantries. State reality.
- No softening. "You haven't touched this in 6 days" not "progress may have slowed"
- Connect to stakes. "This blocks participant recruitment" not just "this is overdue"
- Ask real questions. "What's actually blocking this?" expects an answer.
- Notice avoidance. If comfortable work progresses while hard work stalls, say so.

## PostgreSQL Query Layer

JSONL is canonical. PostgreSQL is a derived query layer for structured queries, full-text search, and tag analytics. It can be fully rebuilt from JSONL at any time.

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

PostgreSQL is local per machine (not on sapphire). Each machine rebuilds from JSONL (git-tracked). Setup on a new machine: install PostgreSQL, apply schema, run `rebuild-postgres.py`.

## System Adaptation

The system should adapt to fit Shawn, not the other way around.

- Log friction points (system_friction memory category)
- Monthly /retro reviews what's working
- Parameters in SYSTEM.md can be tuned based on evidence
- Overrides are allowed but logged — patterns suggest system needs to change
