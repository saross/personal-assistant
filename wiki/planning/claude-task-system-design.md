# Claude Code Task System: Design Document

## Design Principles

This system is built around specific psychological insights:

1. **Sequential focus wins** - You do best with 1-2 things at a time, finished before starting new work
2. **Parallel sprawl fails** - Multiple "in progress" items leads to nothing completed
3. **External accountability works** - Collaborators, co-working, founders meetings provide real pressure
4. **Confrontation over nagging** - State the gap bluntly, connect to values, ask what's really happening
5. **Completion over activity** - Track things finished, not hours spent

**Core constraint:** Maximum 2 items in active focus at any time. Everything else is queued.

---

## File Structure

```
~/tasks/
├── FOCUS.md                    # THE critical file: your 1-2 active items
├── SYSTEM.md                   # System configuration and parameters
├── inbox.md                    # Unclarified captures (GTD inbox)
├── waiting-for.md              # Blocked on others
├── someday.md                  # Ideas, not committed
├── done/
│   ├── 2026-02.md              # Completed items by month
│   └── ...
├── projects/
│   ├── research/
│   │   ├── _PROJECT.md         # Project metadata, collaborators, goals
│   │   ├── gps-validation.md   # Project tasks
│   │   ├── ethics-submission.md
│   │   └── ...
│   ├── business/
│   │   ├── _PROJECT.md
│   │   ├── efn-q1-roadmap.md
│   │   └── ...
│   └── personal/
│       ├── _PROJECT.md
│       ├── claude-pm.md
│       └── ...
├── reports/
│   ├── weekly/
│   │   ├── 2026-W06.md         # Internal weekly review
│   │   └── ...
│   ├── collaborators/
│   │   ├── efn-2026-W06.md     # For EFN founders
│   │   ├── research-2026-W06.md # For research collaborators
│   │   └── ...
│   └── retros/
│       ├── 2026-02.md          # Monthly system retrospectives
│       └── ...
└── standups/
    ├── 2026-02-07.md
    └── ...
```

---

## Core Files

### FOCUS.md - The Most Important File

This is your cockpit. Maximum 2 items. If you want to add a third, something must move out.

```markdown
# Current Focus

**Last updated:** 2026-02-07 09:15
**Focus check:** 2 of 2 slots filled ✓

---

## 🎯 Slot 1: Ethics Submission Revision
- **Project:** research/ethics-submission
- **Started:** 2026-01-26 (12 days ago)
- **Collaborators:** Sarah (supervisor), Ethics Board
- **Deadline:** Was 2026-02-05 ⚠️ OVERDUE
- **Why this matters:** Required before participant recruitment can begin. Blocking the entire study timeline.
- **Next action:** Address reviewer comment 3 (methodology clarification)
- **What's actually blocking this?** [Answer honestly]

---

## 🎯 Slot 2: Memory System Implementation  
- **Project:** personal/claude-pm
- **Started:** 2026-02-04 (3 days ago)
- **Collaborators:** None (personal infrastructure)
- **Deadline:** None (self-imposed)
- **Why this matters:** Foundation for productivity system. But is it urgent, or are you hiding here?
- **Next action:** Create extraction-hook.py
- **What's actually blocking this?** Nothing - making good progress

---

## ⏸️ Paused (Must Finish Focus Before Resuming)

| Item | Project | Paused Since | Why Paused |
|------|---------|--------------|------------|
| GPS validation script | research/gps-validation | 2026-02-01 | Ethics must come first |
| Q1 roadmap draft | business/efn-q1-roadmap | 2026-01-30 | Waiting for founders input |

---

## Rules

1. **Max 2 focus items.** No exceptions. Not "just this one small thing."
2. **Finish or explicitly abandon** before starting something new.
3. **If stuck for 3+ days**, something is wrong. Surface it.
4. **Paused items are paused**, not "also working on." Don't touch them.
```

### inbox.md - Capture Without Commitment

```markdown
# Inbox

Quick captures. Process daily during standup.

---

- [ ] 2026-02-07 08:30 | Email from finance@ about Q3 budget - need to respond
- [ ] 2026-02-06 15:20 | Idea: could we use DuckDB for the GPS analysis instead of pandas?
- [ ] 2026-02-06 11:00 | Sarah mentioned new ethics template - check if we need to update
- [ ] 2026-02-05 | Schedule dentist appointment
```

### projects/_PROJECT.md - Project Metadata

Each project directory has a `_PROJECT.md` with context:

```markdown
# Project: GPS Validation Study

## Overview
Validating GPS accuracy under forest canopy for field data collection protocols.

## Collaborators
- **Sarah Chen** (supervisor) - weekly check-ins Thursdays
- **Mike Torres** (PhD student) - doing field data collection
- **External:** Forestry Commission (data access)

## Key Dates
- Ethics approval: Required before 2026-03-01
- Field season: 2026-04-15 to 2026-06-30
- Conference deadline: 2026-08-01

## Current Status
Phase 1 (ethics) - BLOCKED on ethics revision

## Weekly Report Recipients
Sarah, Mike (cc on research weekly report)

## Links
- Zotero collection: GPS-Validation
- GitHub repo: research/gps-validation
- Ethics application: [link]
```

### waiting-for.md

```markdown
# Waiting For

Items blocked on others. Review weekly.

---

| Item | Waiting On | Since | Last Poked | Next Action If No Response |
|------|------------|-------|------------|---------------------------|
| Ethics feedback | Ethics Board | 2026-02-03 | - | Follow up 2026-02-10 |
| Q1 priorities input | EFN founders | 2026-01-28 | 2026-02-01 | Raise at founders meeting |
| GPS data access | Forestry Commission | 2026-01-15 | 2026-01-25 | Escalate to Sarah |
```

---

## Task Format

Individual tasks within project files use this format:

```markdown
## Task: Address Ethics Reviewer Comments

- **Status:** 🔴 In Focus | 🟡 Queued | 🟢 Done | ⏸️ Paused | ❌ Abandoned
- **Created:** 2026-01-20
- **In Focus Since:** 2026-01-26
- **Deadline:** 2026-02-05
- **Blocked by:** Nothing
- **Blocks:** Participant recruitment, field data collection

### Description
The ethics board returned our application with three comments requiring response.

### Progress Log
- 2026-02-01: Addressed comments 1 and 2
- 2026-01-28: Reviewed feedback, identified required changes
- 2026-01-26: Received reviewer comments

### Subtasks
- [x] Address comment 1 (consent form wording)
- [x] Address comment 2 (data retention policy)
- [ ] Address comment 3 (methodology clarification)
- [ ] Resubmit to ethics board
```

---

## Commands

### /standup - Daily Confrontation

**Purpose:** Force you to face reality every morning. Not optional.

**Trigger:** Run manually, or via SessionStart hook.

**Output:** Written to `standups/YYYY-MM-DD.md` and displayed.

```markdown
# /standup

When the user runs /standup or starts a session, generate a confrontational status check.

## Workflow

1. **Load state**
   - Read FOCUS.md for current focus items
   - Read inbox.md for unprocessed captures
   - Read waiting-for.md for blocked items
   - Check git history for recent activity
   - Load relevant memories (commitments, patterns, slips)

2. **Calculate metrics**
   - Days in focus for each focus item
   - Days since last commit/update per project
   - Overdue deadlines
   - Items in "waiting for" that need poking

3. **Detect patterns** (from memory system)
   - Recurring slips on same items
   - Avoidance patterns (research stalls while personal moves)
   - Stated priorities vs actual time allocation

4. **Generate standup**

## Standup Template

```
📊 STANDUP - [Day] [Date]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## Focus Check

Slot 1: [Item]
  • In focus: [N] days
  • Last activity: [date] ([N] days ago)
  • Deadline: [date] [STATUS]
  • [Honest assessment of progress]

Slot 2: [Item]
  • In focus: [N] days
  • Last activity: [date] ([N] days ago)
  • [Honest assessment of progress]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## Overdue / At Risk

[List anything past deadline or approaching deadline with no recent progress]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## Patterns I'm Noticing

[Based on memory system slip tracking and recent history]

Examples:
- "The ethics submission has been in focus for 12 days. You addressed 2 of 3 comments in the first 3 days, then stopped. What's different about comment 3?"
- "You've touched personal/claude-pm every day this week but research/ethics not once. Are you avoiding something?"
- "This is the second week you've said you'd finish [X] and haven't. What's actually in the way?"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## Hard Question

[One direct question that needs an honest answer]

Examples:
- "What's actually blocking the ethics submission? Not 'busy.' What specifically?"
- "Is the memory system more important than the ethics deadline, or are you hiding in comfortable work?"
- "You have 4 hours of 'ethics work' on your calendar this week but zero commits. What happened in those blocks?"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## Inbox ([N] items)

[List captures that need processing]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## Waiting For (needs attention)

[Any items that need poking or have been waiting too long]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## Today

Given the above, what are you *actually* going to do today?

Not what you hope. What you're committing to.
```

## Tone Guidelines

- **No pleasantries.** Don't open with "Good morning!" State reality.
- **No softening.** "You haven't touched this in 6 days" not "It looks like progress may have slowed"
- **Connect to stakes.** "This blocks participant recruitment" not just "This is overdue"
- **Ask real questions.** "What's actually blocking this?" expects an answer.
- **Notice avoidance.** If comfortable work is progressing while hard work stalls, say so.
- **Track patterns.** "This is the third week..." is more powerful than "This is late"

## After Standup

Ask: "What's the honest answer to the hard question?"

Then: "Given that, what's your focus for today? One thing."
```

### /capture - Quick Add to Inbox

```markdown
# /capture

Add something to inbox without processing. Zero friction.

## Usage

/capture [text]

## Behavior

1. Append to inbox.md with timestamp
2. Confirm capture
3. Don't ask clarifying questions - that's for processing time

## Example

User: /capture email from Sarah about new ethics template

Claude: 
✓ Captured to inbox:
  "email from Sarah about new ethics template"

[No further commentary. Back to work.]
```

### /done - Complete a Task

```markdown
# /done

Mark something complete. Celebrate briefly, then refocus.

## Usage

/done [task description or reference]

## Behavior

1. Find the matching task in project files
2. Update status to 🟢 Done
3. Add completion date
4. If it was in FOCUS.md, remove it
5. Add to done/YYYY-MM.md archive
6. Update any GitHub Issues via `gh` CLI
7. Brief acknowledgment

## After Completion

If a Focus slot is now empty:
"Slot freed up. You have [N] items in Paused and [M] in project queues. What moves into focus next, or do you want to run single-threaded on [remaining focus item]?"

Encourage single-threading:
"You could pull something into the empty slot, or you could focus exclusively on [remaining item] until it's done. Given your pattern of finishing faster with single focus, I'd suggest the latter."

## Example

User: /done ethics comment 3

Claude:
✓ Completed: Address comment 3 (methodology clarification)
  Project: research/ethics-submission
  In focus for: 14 days
  
Remaining subtask:
  - [ ] Resubmit to ethics board

Focus Slot 1 still active (1 subtask remaining).

Want to knock out the resubmission now while you have momentum?
```

### /focus - Change What's In Focus

```markdown
# /focus

Explicitly change focus items. Enforces the 2-item limit.

## Usage

/focus add [task/project]
/focus remove [task/project]  
/focus swap [current] -> [new]

## Adding to Focus

If already at 2 items:
"Focus is full:
  1. [Current item 1]
  2. [Current item 2]

To add [new item], you must remove or pause one of these. Which one?

Or, if [new item] is genuinely more important, make the case. Why should it displace what you've already committed to?"

If under 2 items:
"Adding [item] to Focus Slot [N].

Why this matters: [pull from project context]
What's the first concrete next action?"

## Removing from Focus

"Removing [item] from focus.

Be honest: is this...
  (a) Done - moving to complete
  (b) Paused - will return to it (when?)
  (c) Abandoned - not doing this (why?)
  (d) Delegated - someone else owns it now

[Choice affects where it goes and how it's tracked]"

## The Integrity Check

If someone tries to add a third item or frequently swaps:
"You've changed focus 4 times this week. Each swap costs momentum.

Current pattern:
  - Ethics submission: in focus → paused → in focus → paused
  - GPS validation: in focus → paused
  - Memory system: added, still active

The ethics submission has been 'in focus' three separate times without completing.

What would it take to actually finish it, rather than rotating through items?"
```

### /review - Weekly Reckoning

```markdown
# /review

Weekly review that produces both an internal reckoning and external reports.

## Run When

- Manually via /review
- Suggested Friday afternoon or Sunday evening
- Reminder if not run by Sunday night

## Workflow

1. **Gather data**
   - Completed items this week (from done/YYYY-MM.md)
   - Focus item history (from FOCUS.md git history)
   - Commits per project (from git)
   - Calendar time vs actual output
   - Slips and patterns (from memory system)

2. **Generate internal review** → reports/weekly/YYYY-WNN.md

3. **Generate collaborator reports** → reports/collaborators/[name]-YYYY-WNN.md

4. **Update memory system** with any slip patterns

5. **Plan next week**

## Internal Review Template

```markdown
# Week [N] Review: [Date Range]

## Completions
[What actually got done and shipped]

## Focus Tracking

| Item | Days in Focus | Started | Outcome |
|------|---------------|---------|---------|
| Ethics submission | 14 | Jan 26 | Still in progress |
| Memory system | 7 | Feb 1 | Completed |

## Commitments vs Reality

**What you said you'd do:**
- [ ] Finish ethics submission (week 3 of saying this)
- [x] Design memory system
- [ ] Draft Q1 roadmap

**What actually happened:**
[Honest accounting]

## Time Allocation

| Domain | Commits | Hours (calendar) | Completed Items |
|--------|---------|------------------|-----------------|
| Research | 3 | 12 | 0 |
| Business | 7 | 8 | 1 |
| Personal | 24 | 15 | 2 |

**Observation:** [Pattern analysis]

## Slips

[Items that slipped, and why - captured to memory system]

## Hard Questions

1. [Question about the biggest gap between stated and actual priorities]
2. [Question about recurring patterns]

## Next Week

**Focus items:**
1. [Item 1 - carryover or new]
2. [Item 2 - or deliberately single-threading]

**Commitments** (specific, completable):
- [ ] [Specific deliverable, not "work on X"]
- [ ] [Specific deliverable]

**Warning signs to watch:**
- [Pattern that indicates slipping]
```

## Collaborator Report Template

Separate report per collaborator group, shareable externally.

```markdown
# Progress Report: [Project/Domain]
**Week of [Date]**
**For:** [Collaborator names]

## Summary

[2-3 sentence executive summary]

## Completed This Week

- [Completed item with brief context]
- [Completed item]

## In Progress

- [Current focus item] - [status, expected completion]
- [Secondary item if relevant]

## Blockers / Needs Input

- [Anything you need from collaborators]
- [Decisions that need to be made together]

## Next Week

- [What you're committing to deliver]

## Questions / Discussion Items

- [For next meeting/co-working session]

---
*Generated [timestamp]. Next sync: [meeting date]*
```

## Report Distribution

After generating collaborator reports:
"Reports generated:
  - reports/collaborators/efn-2026-W06.md (for founders meeting)
  - reports/collaborators/research-2026-W06.md (for Sarah, Mike)

Actions:
  (a) Review and send now
  (b) Edit first, then send
  (c) Save for meeting discussion

The EFN founders meeting is [day]. The research sync with Sarah is [day]."
```

### /process-email - Drain Starred Emails

```markdown
# /process-email

Process starred emails into tasks or decisions.

## Workflow

1. **Fetch starred emails** via Gmail MCP/API
2. **For each email, determine:**
   - Is this actionable? (task)
   - Is this reference? (file or ignore)
   - Is this waiting-for? (someone owes me something)
   - Does this need a response? (commitment)

3. **Present batch for processing:**

```
📧 Starred Email Processing

You have 47 starred emails. Scanning...

=== NEEDS ACTION (12) ===

1. "Re: Q3 budget review" - finance@company (Dec 15, 54 days ago)
   → Respond with budget approval? [task / respond now / delegate / delete]

2. "Ethics board feedback" - ethics@uni (Feb 3, 4 days ago)  
   → This is the feedback you're addressing. [already tracked / archive]

3. "GPS paper reviews" - journal@ (Jan 20, 18 days ago)
   → Reviews for revision. Deadline? [task with deadline / read now / defer]

...

=== WAITING FOR (8) ===

4. "Data access request" - forestry@ (Jan 15, 23 days ago)
   → You requested, no response. [add to waiting-for / follow up now / drop]

...

=== PROBABLY REFERENCE (15) ===

[Newsletters, receipts, confirmations - batch archive?]

=== UNCLEAR (12) ===

[Need to open and read to determine]

---

Process all, or start with "Needs Action"?
```

4. **For each processed email:**
   - Create task in appropriate project
   - Add to waiting-for if applicable
   - Unstar in Gmail (removes from queue)

## Goal

Inbox zero on starred emails. Everything either:
- Becomes a task (in a project file)
- Goes to waiting-for
- Gets archived (not your action)
- Gets responded to (done)
```

### /sync-board - Push to GitHub Projects

```markdown
# /sync-board

Sync current state to GitHub Projects for kanban visualization.

## Workflow

1. **Read current state** from markdown files
2. **Map to GitHub Issues:**
   - FOCUS.md items → "In Progress" column
   - Paused items → "Backlog" or "On Hold" column  
   - waiting-for.md → "Blocked" column
   - done/ items (this week) → "Done" column

3. **For each item, via `gh` CLI:**
   - Create issue if doesn't exist (with labels for project/domain)
   - Update issue status/column if changed
   - Close issue if completed
   - Add comment if there's a status update

4. **Report sync results:**

```
📋 Board Sync Complete

Created: 2 new issues
Updated: 5 issues moved between columns
Closed: 3 issues marked done

Board: https://github.com/users/[you]/projects/[N]

Current state:
  In Progress (2): Ethics submission, Memory system
  Blocked (3): GPS data access, Q1 input, ...
  Backlog (8): ...
  Done this week (3): ...
```

## Column Mapping

| Markdown State | GitHub Column |
|----------------|---------------|
| FOCUS.md Slot 1/2 | 🔥 In Progress |
| FOCUS.md Paused | ⏸️ On Hold |
| waiting-for.md | 🚧 Blocked |
| Project file, status Queued | 📋 Backlog |
| done/ | ✅ Done |

## Sync Frequency

- Manual via /sync-board
- Optionally: after each /done
- Optionally: at end of each session
```

---

## SessionStart Hook

Every Claude Code session begins with accountability.

### Hook Configuration

```json
{
  "hooks": {
    "SessionStart": [
      {
        "type": "command",
        "command": "python3 ~/.claude/hooks/session-start-accountability.py",
        "timeout": 15000
      }
    ]
  }
}
```

### session-start-accountability.py

```python
#!/usr/bin/env python3
"""
SessionStart hook that loads task state and displays accountability check.
Cannot be skipped - it's automatic.
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta

TASKS_DIR = Path.home() / "tasks"
FOCUS_FILE = TASKS_DIR / "FOCUS.md"
INBOX_FILE = TASKS_DIR / "inbox.md"
WAITING_FILE = TASKS_DIR / "waiting-for.md"

def count_inbox():
    if not INBOX_FILE.exists():
        return 0
    lines = INBOX_FILE.read_text().splitlines()
    return len([l for l in lines if l.strip().startswith("- [ ]")])

def get_focus_summary():
    if not FOCUS_FILE.exists():
        return "No FOCUS.md found. Run /standup to initialize."
    
    content = FOCUS_FILE.read_text()
    # Parse focus items (simplified - real impl would be more robust)
    # Return summary for display
    return content[:2000]  # First 2000 chars for context

def get_waiting_count():
    if not WAITING_FILE.exists():
        return 0
    lines = WAITING_FILE.read_text().splitlines()
    return len([l for l in lines if l.strip().startswith("|") and "Waiting On" not in l and "---" not in l])

def main():
    try:
        hook_input = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        hook_input = {}
    
    inbox_count = count_inbox()
    waiting_count = get_waiting_count()
    focus_summary = get_focus_summary()
    
    today = datetime.now().strftime("%A, %B %d")
    
    context = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 SESSION START - {today}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Inbox: {inbox_count} items waiting to be processed
Waiting for: {waiting_count} items blocked on others

Run /standup for full status check and hard questions.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    
    print(json.dumps({
        "hookSpecificOutput": {
            "additionalContext": context
        }
    }))

if __name__ == "__main__":
    main()
```

---

## Memory System Integration

### Additional Categories

Add to memory system for task tracking:

```python
# Task-related memory categories

"slip": {
    "description": "Commitments not met, patterns of avoidance",
    "decay": None,  # Patterns matter long-term
    "examples": [
        "Ethics submission pushed for third consecutive week - pattern of avoiding reviewer comment 3",
        "Claimed time pressure but commit history shows 40 commits to side project"
    ]
}

"completion": {
    "description": "Successfully finished items, what enabled success",
    "decay": 90,  # Keep for pattern recognition, but not forever
    "examples": [
        "Finished memory system design in 4 days - single-threaded focus, clear scope, no blockers",
        "Ethics comments 1-2 done in 3 days when working with Sarah present on video call"
    ]
}

"blocker_real": {
    "description": "Genuine blockers identified (not excuses)",
    "decay": 30,
    "examples": [
        "Ethics comment 3 requires methodology expertise I don't have - need to consult with Sarah",
        "Can't proceed on GPS validation until ethics approved - true dependency"
    ]
}

"blocker_excuse": {
    "description": "Stated blockers that turned out to be avoidance",
    "decay": None,  # Important to remember these patterns
    "examples": [
        "Said 'too busy' but calendar shows 4 free hours that went to twitter",
        "Said 'waiting for input' but never actually asked for the input"
    ]
}
```

### Slip Detection Prompt

Add to extraction hook:

```python
SLIP_DETECTION_PROMPT = """
In addition to standard memory extraction, analyze for task management patterns:

1. **Slips**: Did the user commit to something and not deliver? Note:
   - What was promised
   - What actually happened
   - Any stated reason (and whether it seems genuine)

2. **Avoidance**: Is there evidence of avoiding certain work while doing other work?
   - Hard work stalling while easy work progresses
   - Research stalling while personal projects advance
   - Repeated context-switching away from stuck items

3. **Completion patterns**: When something was finished, what enabled it?
   - Single focus vs multi-tasking
   - External pressure (deadline, collaborator)
   - Time of day, context, conditions

4. **Blocker analysis**: When stuck is mentioned, is it:
   - Genuine dependency (can't proceed without X)
   - Missing information (could ask but hasn't)
   - Avoidance dressed as a blocker

Extract these as memories with categories: slip, completion, blocker_real, blocker_excuse
"""
```

---

## Weekly Report Distribution

### Collaborator Mapping

In `projects/_PROJECT.md`, define who gets reports:

```markdown
## Weekly Report Recipients
- Sarah Chen: sarah@uni.edu (research progress, blockers)
- Mike Torres: mike@uni.edu (cc on research reports)
- EFN Founders: founders@efn.co (business progress, decisions needed)
```

### Report Generation

`/review` generates:

1. **Internal review** (full honesty, hard questions) → `reports/weekly/`
2. **Per-collaborator reports** (appropriate for sharing) → `reports/collaborators/`

The collaborator reports are:
- Professional in tone (no self-flagellation)
- Focused on outcomes and next steps
- Include "needs input" clearly
- Appropriate for forwarding or screen-sharing in meetings

### Distribution Workflow

After `/review`:

```
Reports ready for distribution:

1. research-2026-W06.md
   Recipients: Sarah, Mike
   Next meeting: Thursday standup
   Action: [send now / edit first / discuss at meeting]

2. efn-2026-W06.md  
   Recipients: EFN founders
   Next meeting: Friday founders sync (in 2 days)
   Action: [send now / edit first / bring to meeting]

How do you want to handle these?
```

---

## CLAUDE.md Integration

Add to project CLAUDE.md:

```markdown
## Task System

### Philosophy
- Maximum 2 items in active focus
- Finish before starting
- Sequential beats parallel
- Confrontational accountability
- System adapts based on evidence

### Key Files
- `~/tasks/FOCUS.md` - Current focus (THE critical file)
- `~/tasks/SYSTEM.md` - System configuration (tune the parameters)
- `~/tasks/inbox.md` - Captures awaiting processing
- `~/tasks/projects/` - Project-specific task lists

### Commands
- `/standup` - Morning accountability check (escalates: questions → confrontation → abandon discussion)
- `/capture [text]` - Quick add to inbox
- `/done [task]` - Mark complete, celebrate, refocus
- `/focus add|remove|swap` - Change focus (enforces limits)
- `/review` - Weekly reckoning + collaborator reports
- `/process-email` - Drain starred emails to tasks
- `/sync-board` - Push state to GitHub Projects
- `/retro` - Monthly system retrospective (adapt the system itself)

### Accountability Agreement
I have permission to be confrontational about:
- Items stuck in focus for too long (escalates over ~2 weeks)
- Patterns of avoidance (research vs personal)
- Gaps between stated priorities and actual time allocation
- Slips on commitments

Hard questions are expected. Honest answers required.

### System Adaptation
The system should adapt to fit you, not the other way around.
- Log friction points (system_friction memory category)
- Monthly /retro reviews what's working
- Parameters in SYSTEM.md can be tuned based on evidence
- Overrides are allowed but logged - patterns suggest system needs to change

### Collaborators
- Research: Sarah (supervisor), Mike (PhD student)
- Business: EFN founders
- Weekly reports generated via /review

### Context
[Shawn is on redundancy leave from university. This is a finite window 
for making progress on research and business goals. Productivity system 
building is useful but can become avoidance. Research should be primary.]
```

---

## Implementation Checklist

### Phase 1: File Structure (30 mins)

- [ ] Create `~/tasks/` directory structure
- [ ] Create initial `FOCUS.md` with current reality
- [ ] Create empty `inbox.md`
- [ ] Create `waiting-for.md` with any current blocked items
- [ ] Create `projects/` structure with `_PROJECT.md` files
- [ ] Create `SYSTEM.md` with initial configuration
- [ ] Git init and first commit

### Phase 2: Core Commands (2-3 hours)

- [ ] Implement `/standup` command (with escalation levels)
- [ ] Implement `/capture` command  
- [ ] Implement `/done` command
- [ ] Implement `/focus` command
- [ ] Test each command manually

### Phase 3: SessionStart Hook (30 mins)

- [ ] Create `session-start-accountability.py`
- [ ] Add to hooks configuration
- [ ] Test that it fires on new sessions

### Phase 4: Weekly Review (1-2 hours)

- [ ] Implement `/review` command
- [ ] Create collaborator report templates
- [ ] Test report generation
- [ ] Set up `reports/` directory structure

### Phase 5: Integrations (1-2 hours)

- [ ] Implement `/process-email` command
- [ ] Implement `/sync-board` command
- [ ] Test GitHub Projects sync via `gh` CLI
- [ ] Test email processing

### Phase 6: Memory Integration (30 mins)

- [ ] Add task-related categories to memory schema
- [ ] Add slip detection to extraction prompt
- [ ] Add system_evolution, system_friction, system_success categories
- [ ] Test memory extraction captures task patterns

### Phase 7: Retrospective System (30 mins)

- [ ] Implement `/retro` command
- [ ] Create SYSTEM.md configuration file
- [ ] Add month-end reminder logic
- [ ] Test retrospective generation with sample data

### Phase 8: First Real Use (Week 1)

- [ ] Populate FOCUS.md with actual current work
- [ ] Run first real standup
- [ ] Process existing starred emails via /process-email
- [ ] Generate first weekly review
- [ ] Share first collaborator report

### Phase 9: First Retrospective (End of Month 1)

- [ ] Run /retro with real data
- [ ] Make at least one evidence-based adjustment
- [ ] Document in SYSTEM.md adjustment history
- [ ] Log to memory as system_evolution

---

## System Review and Adaptation

### /retro - Monthly System Retrospective

This isn't about tasks - it's about *the system itself*. Run monthly to assess what's working and adapt.

```markdown
# /retro

Monthly review of whether the productivity system is serving you.

## Trigger

- Run manually via /retro
- Prompted at first session after month-end
- Can be triggered anytime if system feels broken

## Workflow

1. **Gather system metrics** (from memory + task files)
   - Completion rate (items finished vs started)
   - Average days in focus before completion
   - Focus slot churn (how often items swap in/out)
   - Standup compliance (sessions that engaged vs skipped)
   - Slip frequency and patterns
   - Inbox high-water mark (how full does it get?)

2. **Review system interactions** (from memory)
   - What confrontations landed vs felt annoying?
   - When did you override the system? Why?
   - What workarounds emerged?

3. **Generate retrospective**

## Retrospective Template

```
🔧 SYSTEM RETROSPECTIVE - [Month Year]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## System Health Metrics

| Metric | This Month | Last Month | Trend |
|--------|------------|------------|-------|
| Items completed | X | Y | ↑/↓/→ |
| Avg days in focus | X | Y | ↑/↓/→ |
| Focus slot churn | X swaps | Y swaps | ↑/↓/→ |
| Slips recorded | X | Y | ↑/↓/→ |
| Inbox peak | X items | Y items | ↑/↓/→ |

**Interpretation:** [What do these numbers suggest?]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## What's Working

[Evidence-based observations about what's helping]

Examples:
- "Completing items faster when single-slotting (1 focus item) - 4 days avg vs 9 days with 2"
- "Weekly reports to Sarah creating real accountability pressure"
- "Hard questions on day 7 consistently trigger action"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## What's Not Working

[Evidence-based observations about friction or failure]

Examples:
- "2-item limit being bypassed via 'quick tasks' that aren't tracked"
- "Standup confrontation feeling repetitive - same questions, tuning out"
- "Inbox processing happening weekly not daily - items going stale"
- "GitHub sync abandoned after week 2 - not providing value"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## System Overrides

Times you worked around or ignored the system:

[List from memory, with context]

- "Feb 12: Added third focus item for 'urgent' client request - was it actually urgent?"
- "Feb 18-22: Skipped standups entirely during conference travel"
- "Feb 25: Marked item 'done' that wasn't really done to clear the slot"

**Pattern:** [What do the overrides suggest about system fit?]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## Configuration Questions

Based on this month, consider:

1. **Focus limit:** Is 2 right, or should we try 1 or 3?
   Current: 2
   Evidence suggests: [X]
   
2. **Escalation timeline:** Is 3/7/14 days right?
   Current: Questions at day 3, confrontation at day 7, abandon discussion at day 14
   Evidence suggests: [X]

3. **Standup tone:** Is confrontational working, or becoming noise?
   Current: Direct, no pleasantries, hard questions
   Observed response: [X]

4. **Review cadence:** Weekly internal + weekly collaborator?
   Current: Weekly
   Evidence suggests: [X]

5. **What's missing?** What needs did the system not anticipate?

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## Proposed Adjustments

Based on the above:

1. [Specific change with rationale]
2. [Specific change with rationale]
3. [Keep as-is with rationale]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## Decision

What changes are we making?

[ ] Accept proposed adjustments
[ ] Modify (specify)
[ ] Keep current system for another month
[ ] System needs fundamental rethink (escalate to design session)
```

## After Retrospective

1. **Update system configuration** if changes agreed
2. **Log to memory** what changed and why (category: `system_evolution`)
3. **Update CLAUDE.md** with any new parameters
4. **Reset metrics** for next month's comparison

## Tone

Unlike standups (confrontational), retrospectives should be:
- **Curious** not judgmental - "interesting that you bypassed X" not "you failed to follow X"
- **Collaborative** - "should we try..." not "you should..."
- **Evidence-based** - "the data shows..." not "I think..."

The goal is system improvement, not personal accountability (that's what standups are for).
```

### Memory Categories for System Adaptation

Add to memory system:

```python
# System-level memory categories

"system_evolution": {
    "description": "Changes made to the productivity system and why",
    "decay": None,  # Keep history of what was tried
    "examples": [
        "March 2026: Reduced focus limit from 2 to 1 after data showed faster completion",
        "April 2026: Softened standup tone after feedback that confrontation became noise",
        "May 2026: Added '/quick' command for <15min tasks that don't need focus slots"
    ]
}

"system_friction": {
    "description": "Points where the system creates friction or gets bypassed",
    "decay": 60,  # Keep until addressed in retro
    "examples": [
        "Marked item done prematurely to free focus slot - system pressure causing dishonesty",
        "Started using paper notes to avoid inbox.md - capture friction too high",
        "Ignored standup three days running - questions feeling repetitive"
    ]
}

"system_success": {
    "description": "Moments where the system clearly helped",
    "decay": 90,  # Keep for pattern recognition
    "examples": [
        "Hard question on day 7 made me realize I was avoiding ethics because I didn't understand reviewer comment",
        "Focus limit prevented me from starting shiny new thing, finished GPS validation instead",
        "Weekly report to Sarah created commitment that got me through the block"
    ]
}
```

### Configurable Parameters

Store in `~/tasks/SYSTEM.md`:

```markdown
# System Configuration

Last updated: 2026-02-07
Last retro: [not yet run]

## Parameters

| Parameter | Current | Default | Notes |
|-----------|---------|---------|-------|
| focus_limit | 2 | 2 | Max items in FOCUS.md |
| escalation_question_day | 3 | 3 | When to start asking questions |
| escalation_confront_day | 7 | 7 | When to get confrontational |
| escalation_abandon_day | 14 | 14 | When to discuss abandonment |
| standup_tone | confrontational | confrontational | Options: gentle, direct, confrontational |
| review_cadence | weekly | weekly | Options: daily, weekly, fortnightly |
| inbox_process_cadence | daily | daily | When to prompt inbox processing |
| retro_cadence | monthly | monthly | When to run system review |

## Adjustment History

| Date | Parameter | From | To | Reason |
|------|-----------|------|-----|--------|
| 2026-02-07 | [initial] | - | - | System created |

## Override Policy

Overrides are allowed but logged. Patterns of override suggest system misfit.

Acceptable overrides:
- True emergencies (define what qualifies)
- Travel/conference periods (note in advance)
- Illness (no judgment)

Concerning overrides:
- "Just this once" repeatedly
- Marking incomplete items as done
- Creating workarounds that bypass tracking
```

### Adaptive Standup Escalation

The standup should vary based on how long something has been stuck:

```markdown
## Escalation Levels (Configurable)

### Days 1-2: Neutral Status
"Ethics submission: Day 2 in focus. Next action: [X]"

### Days 3-6: Curious Questions (escalation_question_day)
"Ethics submission: Day 4 in focus. You addressed comments 1-2 quickly but comment 3 has stalled. What's different about it?"

### Days 7-13: Direct Confrontation (escalation_confront_day)  
"Ethics submission: Day 9 in focus. This is now the longest any item has stayed in focus this month. 

The pattern I'm seeing: you're making progress on other things while this sits. When you have made progress, it was when [X - from memory]. 

What's actually going on? Not 'busy.' What specifically is in the way?"

### Day 14+: Abandon Discussion (escalation_abandon_day)
"Ethics submission: Day 16 in focus.

At this point we need to have a different conversation. Options:

1. **Recommit with a plan**: What specifically will be different? What support do you need?
2. **Pause deliberately**: Move to Paused, set a condition for return ('after X is done')
3. **Abandon**: This isn't happening. Remove it and be honest about why.
4. **Escalate**: This needs external help. Who can unblock you?

Carrying it forward unchanged isn't an option. Which is it?"
```

---

## What Success Looks Like

**After 1 week:**
- Standup runs every session (automatic via hook)
- You've completed at least 1-2 focus items fully before starting new ones
- Weekly review generated and shared with collaborators
- System friction points being logged (even if not yet addressed)

**After 1 month:**
- Clear reduction in "items started but not finished"
- Patterns visible in memory system (what enables completion)
- Collaborators receiving regular updates without manual effort
- First retrospective completed, at least one adjustment made based on evidence

**After 3 months:**
- Sustainable rhythm of focus → complete → next
- Board reflects reality (sync working)
- Inbox stays near zero (capture + process working)
- Research progress commensurate with stated priority
- System has evolved based on 2-3 retrospectives - it fits *your* patterns, not generic best practices
- Overrides are rare, and when they happen, they're logged and addressed

**The meta-goal:**
The system should feel like it's *yours* - adapted to your actual psychology and work patterns - not an imposed discipline you're fighting against. If it still feels like external constraint after 3 months, something is wrong with the system, not with you.
