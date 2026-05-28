# Claude Code as personal project manager: A progressive implementation guide

Claude Code can transform from coding assistant to full personal operating system through a three-tier progression—but **80% of the productivity gains come from mastering the markdown-only foundation** before adding complexity. This guide prioritizes Tier 1 and Tier 2 implementations, where you'll spend most of your time, with Tier 3 pointing toward your existing "AI-Powered Personal Operating System" report.

The core insight from community practice: Claude Code's **context window is volatile RAM while your filesystem is persistent disk**. Every successful personal PM implementation treats markdown files as the source of truth, with Claude as the intelligent interface layer.

---

## Tier 1: The markdown-only foundation

The "crawl" tier requires zero external dependencies beyond Claude Code itself. You can implement everything here today using patterns battle-tested by thousands of users.

### CLAUDE.md hierarchy for multi-domain management

Claude Code's four-tier memory hierarchy creates natural separation for research, business, and personal domains:

| Layer | Location | Purpose |
|-------|----------|---------|
| **User global** | `~/.claude/CLAUDE.md` | Your universal preferences, working style, accountability triggers |
| **Project** | `./CLAUDE.md` | Domain-specific rules (research conventions, business processes) |
| **Project local** | `./CLAUDE.local.md` | Personal context, credentials, sandbox URLs (auto-gitignored) |
| **Rules directory** | `.claude/rules/*.md` | Conditional rules with path matching |

For a startup director managing multiple domains, structure your filesystem around this pattern:

```
~/.claude/
├── CLAUDE.md              # Global: working style, communication preferences
├── commands/
│   ├── standup.md         # Morning accountability
│   ├── weekly-review.md   # Weekly reflection
│   └── capture.md         # Quick task capture
│
~/Projects/
├── research/
│   ├── CLAUDE.md          # Research methodology, citation style
│   └── CLAUDE.local.md    # Current paper focus, lab credentials
├── business/
│   ├── CLAUDE.md          # Company processes, stakeholder context
│   └── .claude/rules/
│       ├── investor-comms.md
│       └── product-specs.md
└── personal/
    └── CLAUDE.md          # Life admin patterns
```

**Critical constraint**: Keep total CLAUDE.md content under **3,000 tokens** (roughly 500 lines). Community reports show **20-30% performance degradation** when combined CLAUDE.md files exceed 16KB. Use the `@path/to/file` import syntax for detailed documentation:

```markdown
# CLAUDE.md
## Current Focus
See @docs/q1-goals.md for quarterly priorities
See @tasks/active.md for current task list

## Working Style
- I prefer concise explanations before code
- Always explain tradeoffs for decisions
- Commit messages: conventional commits format
```

### Slash commands for accountability loops

Custom commands stored in `~/.claude/commands/` become globally available. The **wshobson/commands repository** (1.2k stars) provides 57 production-ready commands, but for personal PM, you need four core commands:

**Morning Standup** (`~/.claude/commands/standup.md`):
```markdown
---
description: Generate daily standup with calendar and priorities
allowed-tools: Bash(gcalcli:*), Bash(git log:*), Read
---

## Context
- Today's calendar: !`gcalcli agenda --nocolor`
- Recent commits: !`git log --oneline --since="yesterday" --author="$(git config user.name)"`

## Generate Standup
1. **Today's meetings** and prep needed
2. **Yesterday's accomplishments** from commits
3. **Today's priorities** from @tasks/today.md
4. **Blockers** or context switches to anticipate

Keep it to 5-7 bullet points. Update @daily/$(date +%Y-%m-%d).md with the output.
```

**Task Capture** (`~/.claude/commands/capture.md`):
```markdown
---
description: Quick capture to inbox
argument-hint: [task description in natural language]
---

Add task to @tasks/inbox.md:
- [ ] $ARGUMENTS
- Created: $(date +%Y-%m-%d)
- Context: $(pwd)

Suggest priority level and time estimate using the format:
!high/!medium/!low ~15m/~1h/~2h
```

**Weekly Review** (`~/.claude/commands/weekly-review.md`):
```markdown
---
description: Conduct weekly reflection and planning
allowed-tools: Read, Write, Bash(git log:*), Bash(find:*)
---

## This Week's Data
- Commits: !`git log --oneline --since="7 days ago" --author="$(git config user.name)"`
- Files modified: !`git diff --stat HEAD~20 --name-only | head -30`
- Completed tasks: Read @tasks/archive/$(date +%Y-W%V).md

## Generate Review
1. **Accomplishments**: Summarize completed work
2. **Wins**: What went well?
3. **Challenges**: What was harder than expected?
4. **Learnings**: Key insights to remember
5. **Next week priorities**: Top 3-5 focus areas

Save to @reviews/$(date +%Y-W%V).md and update @tasks/backlog.md priorities.
```

### Markdown kanban patterns

The **aviz85/claude-tasks** repository implements full GTD methodology in pure markdown. The core file structure:

```
tasks/
├── inbox.md      # Capture everything here first
├── today.md      # Max 3 items—your daily focus
├── backlog.md    # Prioritized by Eisenhower matrix
├── someday.md    # Future ideas, low priority
└── archive/      # Completed tasks by week/date
```

**Task format convention** adopted across multiple implementations:
```markdown
- [ ] Task description @project #tag !priority ~estimate
- [ ] Write investor update @business #comms !high ~2h
- [x] Review paper draft @research #writing !medium ~1h ✓2025-02-04
```

For kanban-style workflow tracking, the **Backlog.md pattern** structures boards within a single file:

```markdown
# Project: Q1 Product Launch

## Backlog
- [ ] Finalize pricing model @business !high ~4h
- [ ] Commission design assets @business !medium ~2h

## In Progress (WIP: 3)
- [ ] Draft launch email sequence @business !high ~3h 🔄
- [ ] Prepare demo environment @business !high ~2h 🔄

## Review
- [ ] Legal review of ToS @business !high ~1h 👀

## Done (Week 5)
- [x] Complete feature freeze @business ✓2025-02-03
```

**WIP limits enforcement**: Include the limit in the section header (e.g., "WIP: 3") and instruct Claude via CLAUDE.md: "Never allow more than 3 items in 'In Progress' sections. Move items to Backlog if limit exceeded."

### Session continuity without MCP

Context loss is Claude Code's **biggest limitation for personal PM use**. Community consensus: sessions degrade around **70% context usage**, not 90%. Proactive management is essential.

**Built-in continuity commands**:
```bash
claude --continue          # Resume most recent conversation
claude --resume            # Interactive session picker
claude --resume abc123     # Resume specific session by ID
/compact                   # Compress context mid-session
/context                   # Visualize context usage
/rename payment-integration  # Name sessions for easy retrieval
```

**The Session Handoff Pattern** solves multi-session work. Create a hook or run manually at session end:

```markdown
## Session Handoff - 2026-02-05

### Accomplished
- Implemented OAuth2 flow for calendar integration
- Added JWT validation middleware

### Current State
- Auth working but needs rate limiting
- Tests: 47/52 passing (5 edge cases pending)
- Branch: feature/oauth-integration

### Key Decisions
- RS256 for JWT (security over simplicity)
- 15-min access / 7-day refresh tokens
- Redis for session storage

### Next Steps (Prioritized)
1. Add rate limiting to /auth endpoints
2. Write remaining edge case tests
3. Implement refresh token rotation

### Critical Context
- Don't modify src/legacy/auth.js (deprecated, still used)
- Test user: test@example.com / testpass123
```

Save these to `handoffs/` directory and reference via `@handoffs/session-YYYYMMDD-HHMM.md` in your next session's opening prompt.

### Native calendar and email integration

**gcalcli** provides full Google Calendar access without MCP:

```bash
# Installation
pip install gcalcli

# First-time OAuth setup
gcalcli --client-id=xxx.apps.googleusercontent.com init

# Common commands Claude Code can use
gcalcli agenda                    # View upcoming events
gcalcli quick "Standup at 9am tomorrow"  # Natural language event creation
gcalcli remind 10 "notify-send -u critical %s"  # Set reminders
```

Create a calendar slash command wrapping gcalcli:
```markdown
---
description: Check today's calendar
allowed-tools: Bash(gcalcli:*)
---
!`gcalcli agenda --nocolor`

Summarize my day:
1. Key meetings requiring prep
2. Transition time between events
3. Open blocks for deep work
```

**Email is harder without MCP**. Options include `himalaya` (Rust CLI email client) or `mutt` for power users, but these require significant configuration. Most Tier 1 users simply check email in browser and use Claude Code for drafting responses to paste.

**Note for Pro/Max subscribers**: Claude Desktop (not Claude Code) has native Gmail and Google Calendar integrations that work without MCP setup.

### Accountability loop implementation

The proven pattern across community implementations follows a **morning → execution → evening → weekly** cadence:

**Morning (5-10 minutes)**:
1. Run `/standup` command
2. Review today's calendar
3. Identify top 3 priorities
4. Move tasks to `today.md`

**Execution blocks**:
- Work in focused sessions
- Use `/capture` for interrupting thoughts
- `/compact` at 65-70% context usage

**Evening (5 minutes)**:
1. Run `/progress` to update task statuses
2. Move completed items to archive
3. Note blockers for tomorrow

**Weekly (30-45 minutes)**:
1. Run `/weekly-review` command
2. Process `inbox.md` completely
3. Re-prioritize `backlog.md`
4. Celebrate wins, acknowledge struggles

The **FocusCraft-GTD pattern** automates this with natural language triggers:
- "good morning" → triggers briefing mode
- `/check-calendar` → meeting prep
- `/scan-inboxes` → process captures
- `/prioritize-tasks` → suggest today's top 5

---

## Tier 2: Selective external tools

Move to Tier 2 when you experience these friction points: constant context loss between sessions, need for cross-project knowledge retrieval, or desire for automated workflows. **Don't add tools preemptively**—each adds configuration overhead and potential failure modes.

### When Obsidian adds concrete value

An Obsidian vault is just a folder of markdown files—Claude Code already works with it perfectly by running `claude` from the vault directory. The question is whether Obsidian's features justify adding it.

**Obsidian provides concrete step-up when you have**:
- **100+ interlinked notes** where wiki-style `[[backlinks]]` provide navigation
- **Need for Dataview queries** to surface information programmatically
- **Knowledge bases** requiring graph visualization
- **Templates with JavaScript** (Templater plugin) for dynamic content

**Practical Obsidian + Claude Code workflow**:
```bash
cd ~/Obsidian/MyVault
claude

# Now Claude can:
> "Read my journal from today and add [[backlinks]] to all people and books mentioned"
> "Generate a Dataview query showing all notes tagged #research modified this week"
> "Apply my decision framework template to evaluate this acquisition"
```

**Recommended plugins for Claude Code integration**:
- **Terminal** (polyipseity): Run Claude Code directly in Obsidian sidebar
- **Dataview**: Claude can write queries for you
- **Templater**: Claude can create/edit dynamic templates
- **Local REST API**: Enables future MCP integration

**Skip Obsidian if**: You manage fewer than 50 notes, don't need backlinking, or prefer VS Code for everything.

### First MCP setup guide

MCP (Model Context Protocol) extends Claude Code with persistent tools. Setup is straightforward once you understand the three methods:

**Method 1: CLI Command (Recommended for First MCP)**
```bash
# Add official memory server
claude mcp add memory -- npx -y @modelcontextprotocol/server-memory

# Verify installation
claude mcp list
/mcp  # In Claude Code, check status
```

**Method 2: Config File (For Multiple Servers)**

Edit `~/.claude.json`:
```json
{
  "mcpServers": {
    "memory": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-memory"],
      "env": {
        "MEMORY_FILE_PATH": "~/.claude/memory.json"
      }
    },
    "filesystem": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "/Users/you/Documents",
        "/Users/you/Projects"
      ]
    }
  }
}
```

**Common pitfalls**:
- **Windows users**: Use `cmd /c npx` instead of just `npx`
- **Server not appearing**: Restart Claude Code completely
- **JSON syntax errors**: Validate with `cat ~/.claude.json | jq .`

### Which MCP connectors to add first

**Recommended progression based on personal PM value**:

| Order | MCP Server | Why | Command |
|-------|------------|-----|---------|
| **1** | Memory | Cross-session context persistence | `claude mcp add memory -- npx -y @modelcontextprotocol/server-memory` |
| **2** | Google Calendar | Natural language scheduling | Requires OAuth setup via `@cocal/google-calendar-mcp` |
| **3** | GitHub | Issues as task database, PR workflows | Built-in via `claude /install-github-app` |
| **4** | Filesystem (expanded) | Access files outside project directory | Add specific paths to config |

### Memory MCP tiered architecture

The **memory-mcp** package (github.com/yuvalsuede/memory-mcp) implements a two-tier approach that elegantly solves context management:

**Tier 1: CLAUDE.md (~150 lines)** - Auto-generated compact briefing Claude reads on session start. Contains highest-confidence, most-accessed knowledge.

**Tier 2: .memory/state.json (unlimited)** - Full knowledge graph accessible via `memory_search`, `memory_related`, `memory_ask` tools.

```
your-project/
├── CLAUDE.md              ← Auto-updated summary (80% of sessions need only this)
├── .memory/
│   ├── state.json         ← Full memory store
│   └── cursor.json        ← Tracks processed content
├── .mcp.json              ← MCP server configuration
└── .claude/settings.json  ← Hook configuration for auto-capture
```

**Memory categories** structure knowledge effectively:
- `architecture`: "Next.js 14 app router with Supabase backend"
- `decision`: "Chose server components for SEO requirements"
- `pattern`: "All API routes validate input with zod"
- `gotcha`: "RLS policy requires user_id OR org_id, not both"
- `progress`: "Auth complete, billing in progress"

Setup:
```bash
npm install -g memory-mcp
memory-mcp setup
memory-mcp init ~/Projects/my-app
```

### GitHub Issues as kanban database

**CCPM (Claude Code Project Manager)** with 6.1k stars uses GitHub Issues as the source of truth—no separate database, full audit trail, human developers see AI progress in real-time.

```bash
# Install
cd your-project/
curl -sSL https://automaze.io/ccpm/install | bash
/pm:init

# Core workflow
/pm:prd-new feature-name     # Brainstorm PRD
/pm:epic-oneshot feature     # Decompose → GitHub Issues
/pm:issue-start 1234         # Begin work on issue
/pm:standup                  # Daily standup report
```

This pattern enables **multiple Claude instances working in parallel**—each on separate issues, separate git branches, coordinated through GitHub's issue state.

### Automation with hooks and scheduling

**Hooks** automate actions at specific events. Configure in `.claude/settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [{
      "matcher": "Write",
      "hooks": [{
        "type": "command",
        "command": "prettier --write $CLAUDE_FILE_PATH"
      }]
    }],
    "Stop": [{
      "hooks": [{
        "type": "command",
        "command": "osascript -e 'display notification \"Task complete\" with title \"Claude Code\"'"
      }]
    }],
    "PreCompact": [{
      "hooks": [{
        "type": "command",
        "command": "python scripts/save_session_summary.py"
      }]
    }]
  }
}
```

**Key hook events for personal PM**:
- `SessionStart`: Load context reminders, check calendar
- `PreCompact`: Save session summary before context compression
- `Stop`: Generate handoff document, send notification
- `PostToolUse`: Auto-format code, run tests

**claude-code-scheduler** enables automated recurring tasks:
```bash
/plugin marketplace add jshchnz/claude-code-scheduler
/plugin install scheduler@claude-code-scheduler

# Schedule commands
/scheduler:schedule-add
# "Daily code review every weekday at 9am"
```

For simpler needs, traditional cron works:
```bash
# crontab -e
0 9 * * 1-5 cd ~/Projects && claude --print "Run /standup and save to daily/$(date +%Y-%m-%d).md"
```

---

## Tier 3: Full architecture (brief summary)

Tier 3 implements the comprehensive vision detailed in your existing "Building an AI-Powered Personal Operating System with Claude Code" report. Key additions beyond Tier 2:

**Tasks Feature (v2.1.16+, January 2026)**: Replaces ephemeral todos with persistent tasks supporting dependency graphs (DAGs). Tasks survive crashes, share state across sessions via `CLAUDE_CODE_TASK_LIST_ID` environment variable, and coordinate work across subagents.

**Full MCP ecosystem**: Notion MCP for database integration, Linear MCP for team project management, Todoist MCP for personal task sync, email MCPs for automated triage. Each adds capability but also configuration overhead and token costs from tool definitions.

**Multi-agent orchestration**: CCPM pattern with specialized agents (research agent, implementation agent, review agent) working in parallel across git worktrees. Background agents for monitoring, async subagents for long-running tasks.

**When to advance to Tier 3**: You've hit limits of Tier 2 tools, need team coordination features, want autonomous agents handling multi-day workflows, or require integration with enterprise tools.

Refer to your comprehensive report for implementation details. Most users find Tier 2 sufficient for sophisticated personal PM workflows.

---

## Cross-cutting considerations

### Kanban workflow management with Claude Code

Effective kanban in Claude Code combines explicit state conventions with Claude's ability to update them:

**State progression**: Backlog → Today → In Progress (WIP: 3) → Review → Done

**CLAUDE.md instruction**:
```markdown
## Task Management Rules
- Never exceed WIP limit (3 items in Progress)
- Move blocked items back to Backlog with #blocked tag
- Archive completed items weekly to archive/YYYY-WNN.md
- Estimate all tasks using ~15m/~1h/~2h/~4h format
```

**Deliverable tracking**: Use headers with target dates:
```markdown
## Q1 Launch (Target: 2026-03-15)
### Milestone: Alpha Complete (2026-02-01) ✓
### Milestone: Beta (2026-02-28)
- [ ] Payment integration @business !high ~8h
- [ ] Load testing @technical !medium ~4h
```

### Real limitations and failure modes

**Context management is the central challenge**. From community reports:
- Performance degrades at **70% context usage**, not 90%
- Auto-compact can trigger unpredictably
- **MCP tool definitions consume 26-40% of context** even when idle
- After ~100 exchanges, responses become repetitive and lose focus

**Mitigation strategies**:
1. Compact proactively at 65-70% (`/compact`)
2. Commit between sessions so work persists in filesystem
3. Disable unused MCP servers
4. Keep CLAUDE.md under 4-8KB combined
5. Document decisions in files, not just session history

**What doesn't work well**:
- Unsupervised multi-day tasks
- Complex reasoning near context limits
- Company-specific knowledge without extensive setup
- Consistent quality during high-demand periods

### Cost considerations by tier

| Tier | Typical Monthly Cost | Notes |
|------|---------------------|-------|
| **Tier 1** | $0-20 | Free tier or Pro plan sufficient |
| **Tier 2** | $20-100 | Pro plan with occasional overages; memory-mcp extraction ~$0.001/session |
| **Tier 3** | $100-200+ | Max plan recommended; multi-agent workflows multiply costs |

**API costs if using direct API**: Sonnet 4.5 at $3 input / $15 output per 1M tokens means heavy users (50 sessions/week with substantial context) could see $100-200/month.

**Optimization strategies**:
- Use `/compact` and `/clear` between unrelated tasks
- Reserve Opus for complex reasoning, use Sonnet for 80% of work
- Batch related changes into focused sessions
- Prompt caching saves 90% on repeated context

### What each tier upgrade actually buys you

**Tier 1 → Tier 2**: Persistent memory across sessions (the game-changer), automated workflows without manual triggers, natural language calendar management, GitHub Issues as coordinated task database.

**Tier 2 → Tier 3**: True multi-agent parallelism, enterprise tool integration, autonomous long-running workflows, team coordination features.

**The honest assessment**: Most productivity gains come from mastering Tier 1 patterns. Tier 2 removes friction. Tier 3 is for power users hitting genuine limits. Start simple, add complexity only when specific friction points emerge.

---

## Recommended starting configuration

For immediate implementation as a startup director with Google Apps:

**Day 1**: Set up CLAUDE.md hierarchy and three core slash commands (standup, capture, weekly-review).

**Week 1**: Establish morning/evening accountability rhythm. Create tasks/ folder structure.

**Week 2**: Add gcalcli integration. Implement handoff document pattern.

**Week 3**: Evaluate friction points. If context loss is painful, add Memory MCP.

**Month 2**: Consider Obsidian if knowledge base grows. Add GitHub integration if using Issues.

The community consensus is clear: Claude Code works best as **"a capable chief of staff"**—excellent for delegating cognitive tasks, synthesizing information, and maintaining systems, but requiring human oversight for anything business-critical. Build the foundation first, then expand incrementally based on actual needs rather than anticipated ones.