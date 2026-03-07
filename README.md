# Personal Assistant

A cross-project hub for memory extraction, task management, and accountability,
built on [Claude Code](https://docs.anthropic.com/en/docs/claude-code) hooks and
slash commands.

This system runs as infrastructure around Claude Code sessions: hooks
automatically extract memories from conversations, inject relevant context at
session start, and enforce accountability on active tasks. Slash commands provide
a GTD-inspired workflow for focus management, weekly reviews, and daily standups.

## Architecture

```text
personal-assistant/                      PUBLIC (this repo)
├── commands/          Slash command definitions (/standup, /recall, etc.)
├── hooks/             Session hooks (extraction, retrieval, accountability)
├── scripts/           PostgreSQL sync, memory decay, schema
├── skills/            Custom Claude Code skills
├── planning/          System design documents
├── published/         Selectively published prompts
│
├── data/              PRIVATE submodule (pa-data)
│   ├── memories/      JSONL memory store
│   ├── tasks/         Focus slots, backlog, inbox
│   ├── notes/         Craft notebook
│   ├── standups/      Daily accountability logs
│   ├── reports/       Weekly reviews, retrospectives
│   └── logs/          Runtime logs
│
└── memories, tasks, notes, ...  → symlinks to data/*
```

Infrastructure is public and shareable. Personal data (memories, tasks, notes,
standups, reports) lives in a private git submodule at `data/`. Symlinks at the
repo root preserve all path references, so hooks and scripts work without
modification.

## Key Components

### Memory System

Memories are automatically extracted from Claude Code sessions via a
`Stop`/`PreCompact`/`SessionEnd` hook that calls Claude Haiku to classify and
store observations. Each memory has a category, salience level, tags, and
decay rules.

- **Canonical store:** `memories/memories.jsonl`
- **Query layer:** Local PostgreSQL (Application Programming Interface (API)
  via `psycopg2`), rebuilt from JSONL on each machine
- **Retrieval:** Session-start hook injects relevant memories based on recency
  and salience; `/recall` command for manual search
- **Lifecycle:** Category-based decay rules (permanent for research insights,
  30 days for transient context)

### Task System

A GTD-inspired system enforcing focus through hard limits:

- Maximum 3 active tasks in `FOCUS.md` — not projects, concrete deliverables
- Confrontational accountability: escalating questions after 3 days, direct
  confrontation after 7, abandonment discussion after 14
- `/standup` for morning check-ins, `/recap` for evening calibration
- `/review` for weekly reckoning, `/retro` for monthly system adaptation

### Hooks

| Hook | Trigger | Purpose |
|------|---------|---------|
| `extraction-hook.py` | Stop, PreCompact, SessionEnd | Extract memories from conversation |
| `session-start-retrieval.py` | SessionStart | Inject relevant memories into context |
| `session-start-accountability.py` | SessionStart | Show task status and accountability |

### Commands

| Command | Purpose |
|---------|---------|
| `/standup` | Morning accountability check |
| `/recap` | Evening recap with estimation calibration |
| `/recall [query]` | Search memories |
| `/remember [text]` | Manually capture a memory |
| `/capture [text]` | Quick inbox capture |
| `/craft [text]` | Craft notebook entry |
| `/focus add\|remove\|swap` | Manage focus slots |
| `/done [task]` | Mark task complete |
| `/review` | Weekly review + collaborator reports |
| `/retro` | Monthly system retrospective |
| `/sync-board` | Push task state to GitHub Issues |
| `/process-email` | Email triage |

## Setup

```bash
# Clone with submodule
git clone --recurse-submodules git@github.com:saross/personal-assistant.git
cd personal-assistant

# Run bootstrap (creates symlinks, optional venv)
bash setup.sh
```

See `setup.sh` output for remaining manual steps (`.env` file, cron job,
PostgreSQL schema).

## Design Documents

The `planning/` directory contains the system design thinking:

- Memory system architecture and implementation plan
- Task system design with accountability model
- Progressive memory prototype (three-tier retrieval)
- Benchmarking against other personal knowledge systems

## Licence

MIT — see [LICENSE](LICENSE) for details.
