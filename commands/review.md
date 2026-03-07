# /review — Weekly Review

The weekly reckoning. Aggregates data from across the system into a scorecard,
surfaces patterns, generates collaborator reports, and asks one strategic question.

## Usage

```text
/review
/review this-week
```

## Arguments

- *(no arguments)* — Review the previous Monday-to-Sunday week
- `this-week` — Review the current week so far (with a note that it's partial)

## Behaviour

### 1. Determine Review Period

- Default: previous Monday (00:00) to Sunday (23:59)
- `this-week`: current Monday to today
- If run on a Monday, default covers the week that just ended (yesterday was Sunday)
- Display the date range prominently in the output header

### 2. Aggregate Data

Read these sources and extract data for the review period:

| Source | What to extract |
|--------|----------------|
| `~/personal-assistant/tasks/done/YYYY-MM.md` | Completions in period (count, items, days in focus) |
| `~/personal-assistant/tasks/FOCUS.md` | Current state, days in focus, approaching deadlines |
| `~/personal-assistant/standups/YYYY-MM-DD.md` | Hard questions asked, patterns detected this week |
| `~/personal-assistant/memories/memories.jsonl` | Memories created in period, by category |
| `~/personal-assistant/tasks/inbox.md` | Items currently unprocessed |
| `~/personal-assistant/tasks/waiting-for.md` | Items waiting, any overdue follow-ups |
| `~/personal-assistant/tasks/collaborators.md` | Who gets reports, what projects they care about |

**Git activity:** For each project listed in FOCUS.md (extract from the `Project:` field),
attempt to find the repo and run `git log --oneline --after="YYYY-MM-DD" --before="YYYY-MM-DD"`
to get commit counts and summaries. Common repo locations:

- `~/personal-assistant/` (this repo)
- `~/Code/[project-name]/`
- `~/[project-name]/`

If a repo cannot be found, note it and move on — git data is supplementary.

**Counting completions:** Parse `done/YYYY-MM.md` tables. Each row has
`| YYYY-MM-DD | Item | Project | Days in Focus | Notes |`. Filter rows where the
date falls within the review period.

**Counting focus changes:** Use `git log --oneline --all -- tasks/FOCUS.md` for commits
in the review period that touched FOCUS.md. Each commit represents a focus change.

**Counting inbox flow:** The inbox file shows items with timestamps. Count items with
dates in the review period (added). Processed items are marked `[x]` — count those too.

**Counting memories:** Read `memories.jsonl`, filter by `created_at` in the review period.
Group by category.

### 3. Load Previous Review (for trends)

Check `~/personal-assistant/reports/weekly/` for the most recent review file
(sorted by filename). If one exists, read its scorecard to populate the Trend column.

- Trend indicators: `+N` (increased), `-N` (decreased), `=` (same), `—` (no prior data)

### 4. Generate Internal Review

Use this template. Match the `standup_tone` from SYSTEM.md.

```text
# Weekly Review — Week of [start date] to [end date]

## Scorecard

| Metric | This week | Trend |
|--------|-----------|-------|
| Items completed | N | [trend] |
| Avg days in focus | N.N | [trend] |
| Focus changes | N | [trend] |
| Inbox items (added/processed) | N/N | [trend] |
| Waiting-for items | N | [trend] |
| Memories extracted | N | [trend] |

## Completions

[List what was completed, with days in focus and project.
If nothing was completed: "Nothing completed this week." — don't soften it.]

## Focus State

[Current focus items from FOCUS.md, with:
- Days in focus
- Deadline proximity
- Flag anything at escalation_confront_day (7+) or beyond
- Note if next actions are stale or undefined]

## Git Activity

[Commits per project for the week.
Format: "project-name: N commits — [brief summary of changes]"
If no git data available: "No git activity tracked."]

## Patterns

[Aggregate patterns from standups and memories:
- Avoidance patterns (comfortable vs hard work — look for progress memories
  on infrastructure while research items stall)
- Completion patterns (what enabled finishing? Single-threading? Deadlines?)
- Commitment accuracy (stated plans from standups vs actual completions)
- System friction points (system_friction memories from the week)

Be specific. "You committed to X on Monday's standup. By Friday, Y happened instead."
If insufficient data for pattern detection, say so briefly.]

## Waiting For

[Items from waiting-for.md, with age.
Flag any where follow-up is overdue (> 7 days without progress).
If none: omit this section.]

## Hard Question

[One strategic question for the week — NOT a daily tactical question.
This should connect to larger goals and stakes.
Examples:
- "You completed 3 infrastructure tasks and 0 research tasks. Is this leave
  being used for what it's for?"
- "The paper deadline is in N days. At current pace, will you make it?"
- "You said X was blocked. Is it still blocked, or are you avoiding it?"
- "What would this week look like if you were being honest about priorities?"]

## Next Week

What are the 1-3 concrete deliverables for next week?
[Leave this section as a prompt — the user fills it in after reading the review.]
```

### 5. Generate Collaborator Reports

1. **Read** `~/personal-assistant/tasks/collaborators.md`
2. **For each collaborator entry**, extract their name, projects, context, and tone
3. **Filter** the review data to only their projects:
   - Completions on their projects
   - Focus state of their projects
   - Git activity on their projects
   - Relevant waiting-for items
4. **Generate** a report using this template:

```text
# Update for [Name] — Week of [start date] to [end date]

## [Project Name]

### Progress

[What was done this week on their project — completions, git commits, focus time.
Write in the tone specified for this collaborator.
If nothing happened: be honest but professional. "No progress this week due to [reason]."]

### Blockers

[Anything blocking progress on their project, from FOCUS.md's "Blocked by" field
or from waiting-for items related to their project.
If none: "None currently."]

### Next Steps

[What's planned for next week on their project — from FOCUS.md's next action
and any commitments from the review.
Be concrete: "Complete results section draft" not "Continue working on paper."]

### Needs from You

[Anything the user needs from this collaborator — derived from waiting-for items,
FOCUS.md blocked-by, or explicit mentions in standups.
If nothing: "Nothing right now."]
```

5. **Save** each collaborator report to:
   `~/personal-assistant/reports/collaborators/[name-lowercase]-YYYY-WXX.md`

### 6. Save Internal Review

Save to `~/personal-assistant/reports/weekly/YYYY-WXX.md`

Use ISO week numbering (`date +%V` or Python `isocalendar()`).

### 7. Display and Follow-up

1. **Display** the full internal review
2. **List** collaborator reports generated with their file paths
3. **Ask:** "Any learnings worth capturing this week?"
   - If yes, offer to route to `/craft` (practical learnings) or `/remember` (context/decisions)
4. **Ask** the user to fill in the "Next Week" section with 1-3 concrete deliverables

## Notes

- The review is not optional. Avoiding the review is itself a data point.
- If data sources are missing (no standups, no completions), report that honestly —
  "No standups this week" is itself information.
- First review will show `—` for all trends. That's fine.
- Collaborator reports use the collaborator's specified tone, NOT the internal
  confrontational tone. Brian doesn't need to hear "you're avoiding this."
- The Hard Question should be genuinely uncomfortable if the data warrants it.
  A week of great progress gets a lighter question.
- Git activity is best-effort. If repos can't be found, skip that section.
- Keep the review factual. Let the data speak. Add interpretation in Patterns
  and the Hard Question, not in the Scorecard.
