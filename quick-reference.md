# Personal Assistant — Quick Reference

## Daily Workflow

**Start of day:** Run `/standup` in your first session. It reads your focus, inbox, and waiting-for items, then gives you an honest accountability check. Escalation increases the longer items sit.

**During work:** Just work normally. The system runs silently in the background:

- Memories are extracted automatically when you stop, compact, or end a session
- PostgreSQL syncs every 5 minutes via cron
- Context from previous sessions is injected when you start a new one

**When something comes up:** Use `/capture` to throw it in the inbox without breaking flow. Process the inbox during your next standup.

**When you finish something:** Use `/done` to mark it complete, archive it, and free up a focus slot.

## Commands

| Command | What it does | When to use it |
|---------|-------------|----------------|
| `/standup` | Accountability check — reads focus, inbox, deadlines | Start of day, or when you need a reality check |
| `/capture some text` | Adds to inbox with timestamp | Mid-flow, don't want to lose a thought |
| `/focus add` | Add item to focus (max 3) | After clearing a slot or at week start |
| `/focus remove` | Remove item from focus | Abandoning or pausing something |
| `/focus swap` | Replace one focus item with another | Priorities shifted |
| `/done task name` | Mark complete, archive, prompt for next | When you finish something |
| `/recall query` | Search memories by keyword, category, or tag | "What did we decide about X?" |
| `/recall` | Show memory stats and recent entries | Quick overview of what's stored |
| `/remember content` | Manually save a memory | Important decision or insight worth preserving |

## What Happens Automatically

| Hook | Fires when | What it does |
|------|-----------|--------------|
| Extraction | Stop, PreCompact, SessionEnd | Sends transcript to Haiku, extracts 2-8 memories |
| Memory injection | SessionStart | Loads recent + permanent memories into context |
| Accountability | SessionStart | Shows focus slots, inbox count, waiting-for count |
| Cron sync | Every 5 minutes | Syncs JSONL to PostgreSQL for structured queries |

## Key Files

| File | What it is | When to edit manually |
|------|-----------|----------------------|
| `tasks/FOCUS.md` | Your active work (max 3 items) | Rarely — use `/focus` and `/done` instead |
| `tasks/inbox.md` | Unprocessed captures | Process during standup |
| `tasks/waiting-for.md` | Blocked on others | Update when you poke someone or get a response |
| `tasks/SYSTEM.md` | Tunable parameters (focus limit, escalation days) | When the system needs adjusting |
| `memories/memories.jsonl` | Canonical memory store (git-tracked) | Never directly — use `/remember` |

## Memory Categories at a Glance

**Permanent (never decay):** decisions, architecture, methodology, ethics, error modes, contacts

**Long-lived (180 days):** patterns, gotchas

**Medium (30-90 days):** commitments (from deadline), progress, context, completions

**Short (14-60 days):** waiting-for, system friction

## Maintenance

| Task | Frequency | Command |
|------|-----------|---------|
| Standup | Daily | `/standup` |
| Process inbox | Daily (during standup) | Review `tasks/inbox.md` |
| Decay expired memories | Weekly | `venv/bin/python3 scripts/apply-decay.py` |
| Rebuild PostgreSQL | As needed | `venv/bin/python3 scripts/rebuild-postgres.py` |
| Check sync health | If something seems off | `cat logs/sync.log` |

## Philosophy

- **3 things in focus, maximum.** Finish before starting.
- **Capture everything, process later.** `/capture` is instant; deciding what to do with it is separate.
- **JSONL is canonical.** PostgreSQL is derived. If in doubt, rebuild.
- **The system adapts to you.** Log friction (`system_friction`), review monthly, tune parameters.
