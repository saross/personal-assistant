# Repository Structure Decision

## The Question

Where does the personal assistant system live?

## The Decision

**Dedicated PA repo as hub.** The personal assistant is its own git-tracked repository that serves as the "home base" for cross-project work.

```
~/personal-assistant/                    # Git-tracked repo
├── CLAUDE.md                            # PA persona and instructions
├── memories/
│   ├── memories.jsonl                   # Canonical, git-tracked
│   ├── extraction-cursor.json
│   └── tag-vocabulary.txt
├── tasks/
│   ├── FOCUS.md
│   ├── SYSTEM.md
│   ├── inbox.md
│   ├── waiting-for.md
│   └── projects/
│       ├── research/
│       │   ├── _PROJECT.md
│       │   └── [task files]
│       ├── business/
│       │   ├── _PROJECT.md
│       │   └── [task files]
│       └── personal/
│           ├── _PROJECT.md
│           └── [task files]
├── hooks/
│   ├── extraction-hook.py
│   └── session-start-accountability.py
├── scripts/
│   ├── sync-to-postgres.py
│   ├── apply-decay.py
│   └── tag-gardening.py
├── commands/
│   ├── standup.md
│   ├── recall.md
│   ├── remember.md
│   ├── capture.md
│   ├── done.md
│   ├── focus.md
│   ├── review.md
│   ├── retro.md
│   ├── process-email.md
│   └── sync-board.md
├── reports/
│   ├── weekly/
│   ├── collaborators/
│   └── retros/
├── standups/
└── logs/
```

## Rationale

### Why Not Per-Project Memories?

The PA needs cross-domain visibility:
- Pattern detection: "You're avoiding research while doing personal projects"
- Unified weekly reviews spanning all domains
- Task focus that sees everything in flight
- Collaborator reports that pull from multiple projects

Per-project memories would fragment this.

### Why Not ~/.claude/?

- Not git-tracked by default
- Mixing runtime config with versioned code
- Research transparency requires exportable repo

### Why a Dedicated Repo?

1. **Git tracking:** Entire system is versioned, including memories.jsonl
2. **Research transparency:** Can export/share for open science
3. **Consolidated view:** One memories.jsonl captures everything
4. **Clean separation:** Code/config versioned here, Claude Code runtime stays in ~/.claude/
5. **Portable:** Can clone to new machine and have full history

---

## ~/.claude/ Configuration

The standard Claude Code config location becomes minimal — just points to the PA repo:

```
~/.claude/
├── settings.json      # Hook configuration
├── CLAUDE.md          # Optional global preferences (can be minimal/empty)
└── sessions/          # Claude Code's own session storage (managed by CC)
```

### settings.json

```json
{
  "hooks": {
    "Stop": [
      {
        "type": "command",
        "command": "python3 ~/personal-assistant/hooks/extraction-hook.py",
        "timeout": 30000
      }
    ],
    "PreCompact": [
      {
        "matcher": ["auto", "manual"],
        "type": "command",
        "command": "python3 ~/personal-assistant/hooks/extraction-hook.py",
        "timeout": 30000
      }
    ],
    "SessionEnd": [
      {
        "type": "command",
        "command": "python3 ~/personal-assistant/hooks/extraction-hook.py",
        "timeout": 30000
      }
    ],
    "SessionStart": [
      {
        "type": "command",
        "command": "python3 ~/personal-assistant/hooks/session-start-accountability.py",
        "timeout": 15000
      }
    ]
  }
}
```

---

## Usage Patterns

### PA/Planning Work (Home Base)

```bash
cd ~/personal-assistant
claude
```

Full context available:
- All memories visible
- All tasks visible  
- All commands work
- `/standup`, `/review`, `/focus` operate naturally

### Project-Specific Work with PA Context

```bash
cd ~/research/gps-validation
claude --add-dir ~/personal-assistant
```

Project context + PA context:
- Memories still captured (hooks fire globally)
- Can reference tasks
- Can use PA commands

### Project-Specific Work with @import

In project CLAUDE.md:
```markdown
# GPS Validation Study

See @~/personal-assistant/CLAUDE.md for task system and memory context.

## This Project
...
```

### Pure Project Work (No PA)

```bash
cd ~/research/gps-validation
claude
```

Just project context:
- Memories still captured (hooks fire globally)
- No task system visible
- Use when deep in focused work

---

## Mental Model

| Location | Purpose |
|----------|---------|
| `~/personal-assistant/` | Home base. Planning, reviews, cross-project work. |
| `~/research/[project]/` | Focused research work. Add PA via `--add-dir` when needed. |
| `~/business/[project]/` | Focused business work. Add PA via `--add-dir` when needed. |
| `~/.claude/` | Claude Code runtime config. Minimal. Points hooks to PA repo. |

The personal assistant isn't a feature of each project — it's a project itself that ties the others together.

---

## What Gets Git-Tracked Where

### In ~/personal-assistant/ (this repo)

**Tracked:**
- `memories/memories.jsonl` — canonical memory store
- `memories/tag-vocabulary.txt` — evolving tag vocabulary
- `tasks/**` — all task files including FOCUS.md
- `hooks/**` — extraction and accountability scripts
- `scripts/**` — sync, decay, gardening scripts
- `commands/**` — slash command definitions
- `reports/**` — weekly reviews, collaborator reports, retros
- `standups/**` — daily standup outputs
- `CLAUDE.md` — PA persona and instructions

**Gitignored:**
- `logs/` — runtime logs
- `memories/extraction-cursor.json` — runtime state
- `memories/sync-cursors.json` — runtime state
- `*.pyc`, `__pycache__/`
- `.DS_Store`

### In ~/.claude/ (not a repo)

Not tracked (Claude Code manages):
- `sessions/` — session history
- `settings.json` — local config (could be symlinked from PA repo)

---

## PostgreSQL

Database lives outside the repo (it's runtime infrastructure, not versioned content):

```bash
# Local Postgres, data in standard location
# Or Docker with named volume
docker run -d --name postgres \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 \
  -v claude_postgres_data:/var/lib/postgresql/data \
  postgres:16
```

Connection string in environment:
```bash
export CLAUDE_MEMORIES_DB="postgresql://localhost/claude_memories"
```

The sync script (`scripts/sync-to-postgres.py`) reads from `memories/memories.jsonl` and syncs to Postgres. JSONL remains canonical.

---

## Implementation Steps

1. **Create repo structure:**
   ```bash
   mkdir -p ~/personal-assistant/{memories,tasks/projects/{research,business,personal},hooks,scripts,commands,reports/{weekly,collaborators,retros},standups,logs}
   cd ~/personal-assistant
   git init
   ```

2. **Create .gitignore:**
   ```
   logs/
   memories/extraction-cursor.json
   memories/sync-cursors.json
   *.pyc
   __pycache__/
   .DS_Store
   ```

3. **Create initial files:**
   - `CLAUDE.md` with PA persona
   - `tasks/FOCUS.md` with current reality
   - `tasks/SYSTEM.md` with initial parameters
   - Empty `memories/memories.jsonl`
   - `memories/tag-vocabulary.txt` with seed tags

4. **Set up ~/.claude/settings.json** to point hooks here

5. **Initial commit:**
   ```bash
   git add .
   git commit -m "Initial personal assistant structure"
   ```

6. **Implement hooks and commands** per the design documents
